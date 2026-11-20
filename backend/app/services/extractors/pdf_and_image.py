"""Deterministic extractors for PDF documents (text, tables, page PNGs, OCR fallback) and raster images."""

from pathlib import Path
import re
import unicodedata

import pdfplumber
from PIL import Image
import pymupdf

from app.schemas.extraction import ExtractedItem, PageReconciliationOut
from app.services.extractors.ocr import (
    OCR_LOW_CONFIDENCE_THRESHOLD,
    TESSERACT_NOT_INSTALLED_STATUS,
    OcrRunner,
    TesseractProbe,
    probe_tesseract,
    run_ocr_with_details,
)
from app.services.extractors.office import (
    ExtractedPayload,
    _collapse_table_with_raw,
    _strip_with_raw,
)

_MIN_NATIVE_PDF_CHARS_BEFORE_OCR = 15
PDF_PREVIEW_DPI = 150
PDF_OCR_RENDER_DPI = 300

_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)", re.IGNORECASE)
_ARABIC_TASHKEEL_RE = re.compile(r"[\u064B-\u065F\u0670]")
_ARABIC_WORD_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]+")
_CORRECT_COMMON_ARABIC_WORDS = frozenset({"في", "من", "على", "إلى", "الى"})
_REVERSED_COMMON_ARABIC_WORDS = frozenset({"يف", "نم", "ىلع", "ىلإ", "ىلا"})


def assess_native_pdf_text_reliability(raw_text: str) -> tuple[bool, str | None]:
    """Detect unreliable PDF native text (CID font placeholders or reversed visual-order Arabic)."""
    if not raw_text:
        return False, None

    cid_hits = len(_CID_TOKEN_RE.findall(raw_text))
    normalized = unicodedata.normalize("NFKC", raw_text)
    stripped_marks = _ARABIC_TASHKEEL_RE.sub("", normalized)
    tokens = _ARABIC_WORD_RE.findall(stripped_marks)
    correct_count = sum(1 for tok in tokens if tok in _CORRECT_COMMON_ARABIC_WORDS)
    reversed_count = sum(1 for tok in tokens if tok in _REVERSED_COMMON_ARABIC_WORDS)

    reasons: list[str] = []
    if cid_hits > 0:
        reasons.append(f"cid_placeholders={cid_hits}")
    if reversed_count > 0 and reversed_count > correct_count:
        reasons.append(
            f"reversed_arabic_words={reversed_count}>correct={correct_count}"
        )

    if reasons:
        return True, "; ".join(reasons)
    return False, None


def _normalize_pdf_table(
    raw_table: list[list[str | None]],
) -> tuple[list[list[str]], list[list[str]] | None, str]:
    raw_strings = [
        [str(cell) if cell is not None else "" for cell in row]
        for row in raw_table
    ]
    return _collapse_table_with_raw(raw_strings)


def extract_pdf(
    path: Path,
    *,
    output_pages_dir: Path,
    pages_relative_prefix: str,
    source_file: str,
    file_id: str | None,
    version_number: int,
    configured_tesseract_cmd: str = "",
    ocr_probe: TesseractProbe | None = None,
    ocr_runner: OcrRunner | None = None,
    force_ocr: bool = False,
) -> ExtractedPayload:
    """Extract PDF text, tables, 150 DPI previews, and >=300 DPI Arabic+English OCR with full page reconciliation."""
    payload = ExtractedPayload()
    output_pages_dir.mkdir(parents=True, exist_ok=True)
    active_probe = ocr_probe if ocr_probe is not None else probe_tesseract(configured_tesseract_cmd)
    ocr_capability = active_probe.capability

    idx = 0
    saw_scanned_page = False
    saw_unreliable_native = False
    ocr_applied = False
    ocr_missing = False
    ocr_failed_error = False
    ocr_render_performed = False
    seen_ocr_warnings: set[str] = set()

    status_counts: dict[str, int] = {
        "text": 0,
        "ocr_text": 0,
        "ocr_empty_or_blank": 0,
        "failed": 0,
    }
    blank_pages: list[int] = []
    failed_pages: list[int] = []
    unreliable_native_pages: list[int] = []
    low_confidence_pages: list[int] = []

    fitz_doc = pymupdf.open(str(path))
    try:
        with pdfplumber.open(path) as pp_doc:
            page_count = len(fitz_doc)
            payload.counts.pages = page_count

            for page_idx in range(page_count):
                page_num = page_idx + 1
                page_label = f"page:{page_num}"
                try:
                    fitz_page = fitz_doc[page_idx]
                    pp_page = pp_doc.pages[page_idx] if page_idx < len(pp_doc.pages) else None

                    # Render lossless 150 DPI PNG preview into 03_Analysis (never altering source PDF)
                    preview_pix = fitz_page.get_pixmap(dpi=PDF_PREVIEW_DPI)
                    preview_png_bytes = preview_pix.tobytes("png")
                    page_filename = f"page_{page_num:03d}.png"
                    (output_pages_dir / page_filename).write_bytes(preview_png_bytes)
                    rel_img_path = f"{pages_relative_prefix.rstrip('/')}/{page_filename}"
                    payload.rendered_page_images.append(rel_img_path)
                    payload.counts.rendered_page_images += 1

                    # Extract selectable text (pdfplumber first, PyMuPDF fallback if empty)
                    pp_text = (pp_page.extract_text() if pp_page is not None else None) or ""
                    fitz_text = fitz_page.get_text("text") or ""
                    raw_page_candidate = pp_text if pp_text.strip() else fitz_text
                    page_text, raw_page_text, page_norm = _strip_with_raw(raw_page_candidate)
                    compact_chars = len("".join(page_text.split()))

                    is_unreliable_native = False
                    unreliable_reason: str | None = None
                    if page_text:
                        is_unreliable_native, unreliable_reason = assess_native_pdf_text_reliability(
                            raw_page_text or page_text
                        )
                    if is_unreliable_native:
                        saw_unreliable_native = True
                        unreliable_native_pages.append(page_num)
                        payload.warnings.append(
                            f"Page {page_num} ({page_label}) native PDF text failed sanity check "
                            f"({unreliable_reason}); flagged native_text_unreliable and routed to 300 DPI OCR."
                        )

                    needs_ocr = bool(
                        force_ocr
                        or is_unreliable_native
                        or compact_chars < _MIN_NATIVE_PDF_CHARS_BEFORE_OCR
                    )

                    if not needs_ocr:
                        idx += 1
                        payload.items.append(
                            ExtractedItem(
                                item_index=idx,
                                item_type="text",
                                source_file=source_file,
                                file_id=file_id,
                                version_number=version_number,
                                page_or_sheet=page_label,
                                location="body",
                                text=page_text,
                                raw_text=raw_page_text,
                                normalization_applied=page_norm,
                                extraction_method="native",
                                page_status="text",
                                native_text_unreliable=False,
                            )
                        )
                        status_counts["text"] += 1
                        payload.counts.text_items += 1

                        # Extract vector tables cleanly using pdfplumber (skip tables containing unreliable CID/reversed text)
                        if pp_page is not None:
                            raw_tables = pp_page.extract_tables() or []
                            for t_idx, raw_table in enumerate(raw_tables, start=1):
                                matrix, raw_uncollapsed, tbl_norm = _normalize_pdf_table(raw_table)
                                if not any(any(cell for cell in row) for row in matrix):
                                    continue
                                flat_tbl_text = " ".join(cell for row in matrix for cell in row if cell)
                                tbl_bad, tbl_bad_reason = assess_native_pdf_text_reliability(flat_tbl_text)
                                if tbl_bad:
                                    payload.warnings.append(
                                        f"Skipped unreliable native vector table {t_idx} on {page_label} ({tbl_bad_reason})."
                                    )
                                    continue
                                idx += 1
                                payload.items.append(
                                    ExtractedItem(
                                        item_index=idx,
                                        item_type="table",
                                        source_file=source_file,
                                        file_id=file_id,
                                        version_number=version_number,
                                        page_or_sheet=page_label,
                                        location=f"table:{t_idx}",
                                        raw_values=matrix,
                                        raw_uncollapsed_values=raw_uncollapsed,
                                        normalization_applied=tbl_norm,
                                        extraction_method="native",
                                    )
                                )
                                payload.counts.tables += 1
                    else:
                        if not is_unreliable_native:
                            saw_scanned_page = True
                        raw_native_for_item = (raw_page_text or page_text) if page_text else None
                        ocr_input_bytes = fitz_page.get_pixmap(dpi=PDF_OCR_RENDER_DPI).tobytes("png")

                        if not ocr_capability.installed and ocr_runner is None:
                            ocr_missing = True
                            idx += 1
                            missing_msg = (
                                "Tesseract OCR is not installed - pending owner; OCR text extraction skipped."
                            )
                            payload.items.append(
                                ExtractedItem(
                                    item_index=idx,
                                    item_type="ocr_text" if not is_unreliable_native else "text",
                                    source_file=source_file,
                                    file_id=file_id,
                                    version_number=version_number,
                                    page_or_sheet=page_label,
                                    location="ocr_full_page" if not is_unreliable_native else "body",
                                    text=None,
                                    raw_text=None,
                                    raw_native_text=raw_native_for_item,
                                    native_text_unreliable=is_unreliable_native,
                                    native_unreliable_reason=unreliable_reason,
                                    extraction_method="ocr" if not is_unreliable_native else "native",
                                    page_status="failed",
                                    page_error=missing_msg,
                                )
                            )
                            status_counts["failed"] += 1
                            failed_pages.append(page_num)
                            if missing_msg not in seen_ocr_warnings:
                                seen_ocr_warnings.add(missing_msg)
                                payload.warnings.append(missing_msg)
                        else:
                            ocr_render_performed = True
                            try:
                                ocr_res = run_ocr_with_details(
                                    ocr_input_bytes,
                                    configured_cmd=configured_tesseract_cmd,
                                    ocr_probe=active_probe,
                                    ocr_runner=ocr_runner,
                                )
                            except Exception as ocr_exc:
                                ocr_failed_error = True
                                idx += 1
                                err_txt = f"{ocr_exc.__class__.__name__}: {ocr_exc}"
                                payload.items.append(
                                    ExtractedItem(
                                        item_index=idx,
                                        item_type="ocr_text",
                                        source_file=source_file,
                                        file_id=file_id,
                                        version_number=version_number,
                                        page_or_sheet=page_label,
                                        location="ocr_full_page",
                                        text=None,
                                        raw_text=None,
                                        raw_native_text=raw_native_for_item,
                                        native_text_unreliable=is_unreliable_native,
                                        native_unreliable_reason=unreliable_reason,
                                        ocr_dpi=PDF_OCR_RENDER_DPI,
                                        extraction_method="ocr",
                                        page_status="failed",
                                        page_error=err_txt,
                                    )
                                )
                                status_counts["failed"] += 1
                                failed_pages.append(page_num)
                                payload.warnings.append(f"OCR failed on {page_label}: {err_txt}")
                                continue

                            if ocr_res.warning and ocr_res.warning not in seen_ocr_warnings:
                                seen_ocr_warnings.add(ocr_res.warning)
                                payload.warnings.append(ocr_res.warning)

                            if ocr_res.text:
                                idx += 1
                                payload.items.append(
                                    ExtractedItem(
                                        item_index=idx,
                                        item_type="ocr_text",
                                        source_file=source_file,
                                        file_id=file_id,
                                        version_number=version_number,
                                        page_or_sheet=page_label,
                                        location="ocr_full_page",
                                        text=ocr_res.text,
                                        normalization_applied="outer_whitespace_trimmed",
                                        ocr_dpi=PDF_OCR_RENDER_DPI,
                                        ocr_confidence_mean=ocr_res.confidence_mean,
                                        ocr_low_confidence=ocr_res.low_confidence,
                                        native_text_unreliable=is_unreliable_native,
                                        native_unreliable_reason=unreliable_reason,
                                        raw_native_text=raw_native_for_item,
                                        extraction_method="ocr",
                                        page_status="ocr_text",
                                    )
                                )
                                status_counts["ocr_text"] += 1
                                payload.counts.ocr_items += 1
                                ocr_applied = True
                                if ocr_res.low_confidence:
                                    low_confidence_pages.append(page_num)
                                    payload.warnings.append(
                                        f"Low OCR confidence on {page_label}: mean={ocr_res.confidence_mean}% "
                                        f"(< {OCR_LOW_CONFIDENCE_THRESHOLD:.0f}%)."
                                    )
                            else:
                                idx += 1
                                payload.items.append(
                                    ExtractedItem(
                                        item_index=idx,
                                        item_type="ocr_text",
                                        source_file=source_file,
                                        file_id=file_id,
                                        version_number=version_number,
                                        page_or_sheet=page_label,
                                        location="ocr_full_page",
                                        text=None,
                                        normalization_applied="ocr_empty_or_blank",
                                        ocr_dpi=PDF_OCR_RENDER_DPI,
                                        ocr_confidence_mean=ocr_res.confidence_mean,
                                        ocr_low_confidence=False,
                                        native_text_unreliable=is_unreliable_native,
                                        native_unreliable_reason=unreliable_reason,
                                        raw_native_text=raw_native_for_item,
                                        extraction_method="ocr",
                                        page_status="ocr_empty_or_blank",
                                    )
                                )
                                status_counts["ocr_empty_or_blank"] += 1
                                blank_pages.append(page_num)
                                payload.warnings.append(
                                    f"Blank or unreadable page on {page_label} (status: ocr_empty_or_blank)."
                                )
                except Exception as page_exc:
                    ocr_failed_error = True
                    idx += 1
                    err_txt = f"{page_exc.__class__.__name__}: {page_exc}"
                    payload.items.append(
                        ExtractedItem(
                            item_index=idx,
                            item_type="text",
                            source_file=source_file,
                            file_id=file_id,
                            version_number=version_number,
                            page_or_sheet=page_label,
                            location="body",
                            text=None,
                            extraction_method="native",
                            page_status="failed",
                            page_error=err_txt,
                        )
                    )
                    status_counts["failed"] += 1
                    failed_pages.append(page_num)
                    payload.warnings.append(f"Page processing failed on {page_label}: {err_txt}")
    finally:
        fitz_doc.close()

    if ocr_render_performed:
        payload.ocr_dpi = PDF_OCR_RENDER_DPI

    page_items_count = sum(status_counts.values())
    payload.page_reconciliation = PageReconciliationOut(
        total_pages=payload.counts.pages,
        page_items_count=page_items_count,
        reconciled=(page_items_count == payload.counts.pages),
        status_counts=status_counts,
        blank_pages=blank_pages,
        failed_pages=failed_pages,
        unreliable_native_pages=unreliable_native_pages,
        low_confidence_pages=low_confidence_pages,
        low_confidence_threshold=OCR_LOW_CONFIDENCE_THRESHOLD,
    )

    if ocr_missing:
        payload.status = "partial_ocr_unavailable"
        payload.ocr_status = (
            "partial_ocr_unavailable" if saw_unreliable_native else TESSERACT_NOT_INSTALLED_STATUS
        )
    elif ocr_applied:
        payload.ocr_status = (
            "ocr_applied (native text unreliable)" if saw_unreliable_native else "ocr_applied"
        )
    elif saw_unreliable_native:
        if ocr_failed_error:
            payload.status = "partial_ocr_unavailable"
            payload.ocr_status = "partial_ocr_unavailable"
        else:
            payload.ocr_status = "ocr_no_text_detected (native text unreliable)"
    elif ocr_failed_error:
        payload.status = "partial_ocr_unavailable"
        payload.ocr_status = "partial_ocr_unavailable"
    elif saw_scanned_page and (ocr_capability.installed or ocr_runner is not None):
        payload.ocr_status = "ocr_no_text_detected"
    else:
        payload.ocr_status = "not_needed"

    payload.counts.total_items = len(payload.items)
    return payload


def extract_image(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
    configured_tesseract_cmd: str = "",
    ocr_probe: TesseractProbe | None = None,
    ocr_runner: OcrRunner | None = None,
) -> ExtractedPayload:
    """Extract lossless image metadata via Pillow and run ara+eng OCR on first frame when available."""
    payload = ExtractedPayload()
    active_probe = ocr_probe if ocr_probe is not None else probe_tesseract(configured_tesseract_cmd)
    ocr_capability = active_probe.capability

    raw_bytes = path.read_bytes()
    with Image.open(path) as img:
        width, height = img.size
        img_format = img.format or path.suffix.lstrip(".").upper()
        img_mode = img.mode
        dpi = img.info.get("dpi")
        n_frames = int(getattr(img, "n_frames", 1) or 1)
        dpi_str = (
            f"{dpi[0]}x{dpi[1]}" if isinstance(dpi, tuple) and len(dpi) >= 2 else "unspecified"
        )
        numeric_dpi: int | float | None = (
            round(float(dpi[0])) if isinstance(dpi, tuple) and len(dpi) >= 2 and dpi[0] else None
        )

    if n_frames > 1:
        payload.warnings.append(
            f"Multi-frame TIFF/image detected ({n_frames} frames); only frame 1 was extracted."
        )

    payload.items.append(
        ExtractedItem(
            item_index=1,
            item_type="image_meta",
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
            page_or_sheet="image:1",
            location="image:metadata",
            text=f"format={img_format}, width={width}px, height={height}px, mode={img_mode}, dpi={dpi_str}",
            normalization_applied="verbatim",
            unit_or_format=f"{width}x{height} px",
            extraction_method="native",
        )
    )
    payload.counts.pages = 1
    payload.counts.text_items = 1

    ocr_res = run_ocr_with_details(
        raw_bytes,
        configured_cmd=configured_tesseract_cmd,
        ocr_probe=active_probe,
        ocr_runner=ocr_runner,
    )
    if ocr_capability.installed or ocr_runner is not None:
        payload.ocr_dpi = numeric_dpi

    if ocr_res.text:
        payload.items.append(
            ExtractedItem(
                item_index=2,
                item_type="ocr_text",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet="image:1",
                location="ocr_full_image",
                text=ocr_res.text,
                normalization_applied="outer_whitespace_trimmed",
                ocr_dpi=numeric_dpi,
                ocr_confidence_mean=ocr_res.confidence_mean,
                ocr_low_confidence=ocr_res.low_confidence,
                page_status="ocr_text",
                extraction_method="ocr",
            )
        )
        payload.counts.ocr_items = 1
        payload.ocr_status = "ocr_applied"
        if ocr_res.low_confidence:
            payload.warnings.append(
                f"Low OCR confidence on image:1: mean={ocr_res.confidence_mean}% "
                f"(< {OCR_LOW_CONFIDENCE_THRESHOLD:.0f}%)."
            )
    else:
        if not ocr_capability.installed and ocr_runner is None:
            payload.ocr_status = TESSERACT_NOT_INSTALLED_STATUS
            payload.status = "partial_ocr_unavailable"
        else:
            payload.ocr_status = "ocr_no_text_detected"
        if ocr_res.warning:
            payload.warnings.append(ocr_res.warning)

    payload.counts.total_items = len(payload.items)
    return payload
