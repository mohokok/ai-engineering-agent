"""Deterministic extractors for PDF documents (text, tables, page PNGs, OCR fallback) and raster images."""

from pathlib import Path

import pdfplumber
from PIL import Image
import pymupdf

from app.schemas.extraction import ExtractedItem
from app.services.extractors.ocr import (
    TESSERACT_NOT_INSTALLED_STATUS,
    OcrRunner,
    detect_tesseract,
    run_ocr_on_image_bytes,
)
from app.services.extractors.office import ExtractedPayload

_MIN_NATIVE_PDF_CHARS_BEFORE_OCR = 15


def _normalize_pdf_table(raw_table: list[list[str | None]]) -> list[list[str]]:
    return [
        [" ".join(str(cell).split()) if cell is not None else "" for cell in row]
        for row in raw_table
    ]


def extract_pdf(
    path: Path,
    *,
    output_pages_dir: Path,
    pages_relative_prefix: str,
    source_file: str,
    file_id: str | None,
    version_number: int,
    configured_tesseract_cmd: str = "",
    ocr_runner: OcrRunner | None = None,
    force_ocr: bool = False,
) -> ExtractedPayload:
    """Extract PDF text, tables, rendered PNG page images, and Arabic+English OCR fallback for scans."""
    payload = ExtractedPayload()
    output_pages_dir.mkdir(parents=True, exist_ok=True)
    ocr_capability = detect_tesseract(configured_tesseract_cmd)

    idx = 0
    saw_scanned_page = False
    ocr_applied = False
    ocr_missing = False

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

                # Render lossless PNG preview into 03_Analysis (never altering the source PDF)
                pix = fitz_page.get_pixmap(dpi=150)
                png_bytes = pix.tobytes("png")
                page_filename = f"page_{page_num:03d}.png"
                (output_pages_dir / page_filename).write_bytes(png_bytes)
                rel_img_path = f"{pages_relative_prefix.rstrip('/')}/{page_filename}"
                payload.rendered_page_images.append(rel_img_path)
                payload.counts.rendered_page_images += 1

                # Extract selectable text (pdfplumber first, PyMuPDF fallback if empty)
                pp_text = (pp_page.extract_text() if pp_page is not None else None) or ""
                fitz_text = fitz_page.get_text("text") or ""
                page_text = pp_text.strip() or fitz_text.strip()

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
                            extraction_method="native",
                        )
                    )
                    payload.counts.text_items += 1

                # Extract vector tables cleanly using pdfplumber
                if pp_page is not None:
                    raw_tables = pp_page.extract_tables() or []
                    for t_idx, raw_table in enumerate(raw_tables, start=1):
                        matrix = _normalize_pdf_table(raw_table)
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
                                extraction_method="native",
                            )
                        )
                        payload.counts.tables += 1

                # OCR fallback when selectable text is absent/sparse (likely scanned) or requested.
                # Re-rasterize at 300 DPI for scanned OCR so fine Arabic ligatures stay sharp.
                compact_chars = len("".join(page_text.split()))
                if compact_chars < _MIN_NATIVE_PDF_CHARS_BEFORE_OCR or force_ocr:
                    saw_scanned_page = True
                    ocr_input_bytes = (
                        fitz_page.get_pixmap(dpi=300).tobytes("png")
                        if ocr_runner is None and ocr_capability.installed
                        else png_bytes
                    )
                    ocr_text, ocr_warning = run_ocr_on_image_bytes(
                        ocr_input_bytes,
                        configured_cmd=configured_tesseract_cmd,
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
                                extraction_method="ocr",
                            )
                        )
                        payload.counts.ocr_items += 1
                        ocr_applied = True
                    elif not ocr_capability.installed and ocr_runner is None:
                        ocr_missing = True
                    if ocr_warning and ocr_warning not in payload.warnings:
                        payload.warnings.append(f"{page_label}: {ocr_warning}")
    finally:
        fitz_doc.close()

    if ocr_applied:
        payload.ocr_status = "ocr_applied"
    elif ocr_missing or (saw_scanned_page and not ocr_capability.installed and ocr_runner is None):
        payload.ocr_status = TESSERACT_NOT_INSTALLED_STATUS
        payload.status = "partial_ocr_unavailable"
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
    ocr_runner: OcrRunner | None = None,
) -> ExtractedPayload:
    """Extract lossless image metadata via Pillow and run ara+eng OCR when Tesseract is available."""
    payload = ExtractedPayload()
    ocr_capability = detect_tesseract(configured_tesseract_cmd)

    raw_bytes = path.read_bytes()
    with Image.open(path) as img:
        width, height = img.size
        img_format = img.format or path.suffix.lstrip(".").upper()
        img_mode = img.mode
        dpi = img.info.get("dpi")
        dpi_str = f"{dpi[0]}x{dpi[1]}" if isinstance(dpi, tuple) and len(dpi) >= 2 else "unspecified"

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
            unit_or_format=f"{width}x{height} px",
            extraction_method="native",
        )
    )
    payload.counts.pages = 1
    payload.counts.text_items = 1

    ocr_text, ocr_warning = run_ocr_on_image_bytes(
        raw_bytes,
        configured_cmd=configured_tesseract_cmd,
        ocr_runner=ocr_runner,
    )
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
