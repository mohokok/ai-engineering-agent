"""Deterministic extractors for PDF documents (text, tables, page PNGs, OCR fallback) and raster images."""

from pathlib import Path

import pdfplumber
from PIL import Image
import pymupdf

from app.schemas.extraction import ExtractedItem
from app.services.extractors.ocr import (
    TESSERACT_NOT_INSTALLED_STATUS,
    OcrRunner,
    TesseractProbe,
    probe_tesseract,
    run_ocr_on_image_bytes,
)
from app.services.extractors.office import (
    ExtractedPayload,
    _collapse_table_with_raw,
    _strip_with_raw,
)

_MIN_NATIVE_PDF_CHARS_BEFORE_OCR = 15
PDF_PREVIEW_DPI = 150
PDF_OCR_RENDER_DPI = 300


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
    """Extract PDF text, tables, 150 DPI previews, and separate >=300 DPI Arabic+English OCR fallback."""
    payload = ExtractedPayload()
    output_pages_dir.mkdir(parents=True, exist_ok=True)
    active_probe = ocr_probe if ocr_probe is not None else probe_tesseract(configured_tesseract_cmd)
    ocr_capability = active_probe.capability

    idx = 0
    saw_scanned_page = False
    ocr_applied = False
    ocr_missing = False
    ocr_render_performed = False
    seen_ocr_warnings: set[str] = set()

    fitz_doc = pymupdf.open(str(path))
    try:
        with pdfplumber.open(path) as pp_doc:
            page_count = len(fitz_doc)
            payload.counts.pages = page_count

            for page_idx in range(page_count):
                page_num = page_idx + 1
                page_label = f"page:{page_num}"
                fitz_page = fitz_doc[page_idx]
                pp_page = pp_doc.pages[page_idx] if page_idx < len(pp_doc.pages) else None

                # Render lossless 150 DPI PNG preview into 03_Analysis (never altering the source PDF)
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

                if page_text:
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
                        )
                    )
                    payload.counts.text_items += 1

                # Extract vector tables cleanly using pdfplumber
                if pp_page is not None:
                    raw_tables = pp_page.extract_tables() or []
                    for t_idx, raw_table in enumerate(raw_tables, start=1):
                        matrix, raw_uncollapsed, tbl_norm = _normalize_pdf_table(raw_table)
                        if not any(any(cell for cell in row) for row in matrix):
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

                # OCR fallback when selectable text is absent/sparse (< 15 chars) or forced.
                # Always render a dedicated 300 DPI bitmap separate from the 150 DPI UI preview.
                compact_chars = len("".join(page_text.split()))
                if compact_chars < _MIN_NATIVE_PDF_CHARS_BEFORE_OCR or force_ocr:
                    saw_scanned_page = True
                    ocr_input_bytes = fitz_page.get_pixmap(dpi=PDF_OCR_RENDER_DPI).tobytes("png")
                    if ocr_capability.installed or ocr_runner is not None:
                        ocr_render_performed = True
                    ocr_text, ocr_warning = run_ocr_on_image_bytes(
                        ocr_input_bytes,
                        configured_cmd=configured_tesseract_cmd,
                        ocr_probe=active_probe,
                        ocr_runner=ocr_runner,
                    )
                    if ocr_text:
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
                                text=ocr_text,
                                normalization_applied="outer_whitespace_trimmed",
                                ocr_dpi=PDF_OCR_RENDER_DPI,
                                extraction_method="ocr",
                            )
                        )
                        payload.counts.ocr_items += 1
                        ocr_applied = True
                    elif not ocr_capability.installed and ocr_runner is None:
                        ocr_missing = True
                    if ocr_warning and ocr_warning not in seen_ocr_warnings:
                        seen_ocr_warnings.add(ocr_warning)
                        payload.warnings.append(ocr_warning)
    finally:
        fitz_doc.close()

    if ocr_render_performed:
        payload.ocr_dpi = PDF_OCR_RENDER_DPI

    if ocr_applied:
        payload.ocr_status = "ocr_applied"
    elif ocr_missing or (saw_scanned_page and not ocr_capability.installed and ocr_runner is None):
        payload.ocr_status = TESSERACT_NOT_INSTALLED_STATUS
        payload.status = "partial_ocr_unavailable"
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

    ocr_text, ocr_warning = run_ocr_on_image_bytes(
        raw_bytes,
        configured_cmd=configured_tesseract_cmd,
        ocr_probe=active_probe,
        ocr_runner=ocr_runner,
    )
    if ocr_capability.installed or ocr_runner is not None:
        payload.ocr_dpi = numeric_dpi

    if ocr_text:
        payload.items.append(
            ExtractedItem(
                item_index=2,
                item_type="ocr_text",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet="image:1",
                location="ocr_full_image",
                text=ocr_text,
                normalization_applied="outer_whitespace_trimmed",
                ocr_dpi=numeric_dpi,
                extraction_method="ocr",
            )
        )
        payload.counts.ocr_items = 1
        payload.ocr_status = "ocr_applied"
    else:
        if not ocr_capability.installed and ocr_runner is None:
            payload.ocr_status = TESSERACT_NOT_INSTALLED_STATUS
            payload.status = "partial_ocr_unavailable"
        else:
            payload.ocr_status = "ocr_no_text_detected"
        if ocr_warning:
            payload.warnings.append(ocr_warning)

    payload.counts.total_items = len(payload.items)
    return payload
