"""Deterministic extractors for DOCX, XLSX, CSV, PPTX, and plain text engineering files."""

import csv
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
import re
from typing import Any

from docx import Document
import openpyxl
from pptx import Presentation

from app.schemas.extraction import ExtractedItem, ExtractionCounts, ExtractionStatus

_FIXED_DECIMAL_RE = re.compile(r"^0\.(0+)")


@dataclass
class ExtractedPayload:
    """Intermediate normalized extraction bundle returned by format-specific extractors."""

    items: list[ExtractedItem] = field(default_factory=list)
    counts: ExtractionCounts = field(default_factory=ExtractionCounts)
    warnings: list[str] = field(default_factory=list)
    rendered_page_images: list[str] = field(default_factory=list)
    ocr_status: str = "not_needed"
    status: ExtractionStatus = "extracted"


def _format_excel_scalar(value: Any, number_format: str | None = None) -> tuple[str, str | None]:
    """Format Excel cell value preserving exact numeric precision and trailing formatted zeros."""
    fmt_clean = number_format.strip() if isinstance(number_format, str) else None
    exposed_fmt = fmt_clean if fmt_clean and fmt_clean not in ("General", "@") else None

    if value is None:
        return "", exposed_fmt
    if isinstance(value, bool):
        return ("TRUE" if value else "FALSE"), exposed_fmt
    if isinstance(value, str):
        return value, exposed_fmt
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(str(value))
    elif isinstance(value, Decimal):
        dec = value
    else:
        return str(value), exposed_fmt

    if exposed_fmt:
        match = _FIXED_DECIMAL_RE.match(exposed_fmt)
        if match:
            target_places = len(match.group(1))
            _, _, exponent = dec.as_tuple()
            actual_places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
            if actual_places <= target_places:
                return f"{dec:.{target_places}f}", exposed_fmt

    normalized = format(dec, "f") if "E" in str(dec).upper() else str(dec)
    return normalized, exposed_fmt


def _decode_text_bytes(raw_bytes: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            return raw_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace"), "utf-8-replace"


def extract_docx(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
) -> ExtractedPayload:
    """Extract paragraphs and tables verbatim from a read-only DOCX file."""
    payload = ExtractedPayload()
    idx = 0

    with path.open("rb") as handle:
        doc = Document(handle)
        for p_i, para in enumerate(doc.paragraphs, start=1):
            text = para.text.strip()
            if not text:
                continue
            idx += 1
            payload.items.append(
                ExtractedItem(
                    item_index=idx,
                    item_type="text",
                    source_file=source_file,
                    file_id=file_id,
                    version_number=version_number,
                    page_or_sheet="docx:body",
                    location=f"paragraph:{p_i}",
                    text=text,
                    extraction_method="native",
                )
            )
            payload.counts.text_items += 1

        for t_i, table in enumerate(doc.tables, start=1):
            matrix = [
                [" ".join(cell.text.split()) for cell in row.cells]
                for row in table.rows
            ]
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
                    page_or_sheet="docx:tables",
                    location=f"table:{t_i}",
                    raw_values=matrix,
                    extraction_method="native",
                )
            )
            payload.counts.tables += 1

    payload.counts.total_items = len(payload.items)
    return payload


def extract_xlsx(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
) -> ExtractedPayload:
    """Extract XLSX sheets preserving both formulas and cached cell values/units."""
    payload = ExtractedPayload()
    idx = 0
    uncached_formula_count = 0

    wb_formulas = openpyxl.load_workbook(path, read_only=True, data_only=False)
    wb_values = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        payload.counts.sheets = len(wb_formulas.sheetnames)
        for sheet_name in wb_formulas.sheetnames:
            ws_f = wb_formulas[sheet_name]
            ws_v = wb_values[sheet_name]
            sheet_label = f"sheet:{sheet_name}"

            cached_grid: dict[tuple[int, int], Any] = {}
            for r_i, v_row in enumerate(ws_v.iter_rows(values_only=True), start=1):
                for c_i, val in enumerate(v_row, start=1):
                    if val is not None:
                        cached_grid[(r_i, c_i)] = val

            sheet_rows: list[list[str]] = []
            formula_items: list[ExtractedItem] = []

            for r_i, f_row in enumerate(ws_f.iter_rows(values_only=False), start=1):
                row_strings: list[str] = []
                row_has_data = False
                for c_i, cell in enumerate(f_row, start=1):
                    raw_formula_or_val = cell.value
                    num_fmt = getattr(cell, "number_format", None)
                    coord = getattr(cell, "coordinate", None) or f"R{r_i}C{c_i}"
                    cached_val = cached_grid.get((r_i, c_i))

                    if isinstance(raw_formula_or_val, str) and raw_formula_or_val.startswith("="):
                        cached_str, exposed_fmt = _format_excel_scalar(cached_val, num_fmt)
                        if cached_val is None:
                            uncached_formula_count += 1
                        row_strings.append(cached_str if cached_val is not None else raw_formula_or_val)
                        row_has_data = True
                        formula_items.append(
                            ExtractedItem(
                                item_index=0,
                                item_type="cell_formula",
                                source_file=source_file,
                                file_id=file_id,
                                version_number=version_number,
                                page_or_sheet=sheet_label,
                                location=f"cell:{coord}",
                                text=cached_str if cached_val is not None else raw_formula_or_val,
                                formula=raw_formula_or_val,
                                cached_value=cached_str if cached_val is not None else None,
                                unit_or_format=exposed_fmt,
                                extraction_method="native",
                            )
                        )
                    else:
                        formatted_val, exposed_fmt = _format_excel_scalar(
                            raw_formula_or_val, num_fmt
                        )
                        if raw_formula_or_val is not None and formatted_val != "":
                            row_has_data = True
                        row_strings.append(formatted_val)

                if row_has_data:
                    # Trim empty trailing columns while preserving column positions inside the row.
                    while row_strings and row_strings[-1] == "":
                        row_strings.pop()
                    sheet_rows.append(row_strings)

            if sheet_rows:
                idx += 1
                payload.items.append(
                    ExtractedItem(
                        item_index=idx,
                        item_type="table",
                        source_file=source_file,
                        file_id=file_id,
                        version_number=version_number,
                        page_or_sheet=sheet_label,
                        location=f"rows:1..{len(sheet_rows)}",
                        raw_values=sheet_rows,
                        extraction_method="native",
                    )
                )
                payload.counts.tables += 1

            for f_item in formula_items:
                idx += 1
                payload.items.append(f_item.model_copy(update={"item_index": idx}))
                payload.counts.formulas += 1
    finally:
        wb_formulas.close()
        wb_values.close()

    if uncached_formula_count > 0:
        payload.warnings.append(
            f"{uncached_formula_count} formula cell(s) have no pre-computed cached value in the file; "
            "exact formulas are preserved without recalculation."
        )
    payload.counts.total_items = len(payload.items)
    return payload


def extract_csv(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
) -> ExtractedPayload:
    """Extract CSV rows verbatim preserving exact numeric decimals, units, and Arabic text."""
    payload = ExtractedPayload()
    text_content, encoding_used = _decode_text_bytes(path.read_bytes())
    reader = csv.reader(text_content.splitlines())
    rows = [
        [cell.strip() for cell in row]
        for row in reader
        if any(cell.strip() for cell in row)
    ]

    payload.counts.sheets = 1
    if rows:
        payload.items.append(
            ExtractedItem(
                item_index=1,
                item_type="table",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet="sheet:CSV",
                location=f"rows:1..{len(rows)}",
                raw_values=rows,
                unit_or_format=encoding_used,
                extraction_method="native",
            )
        )
        payload.counts.tables = 1
    payload.counts.total_items = len(payload.items)
    return payload


def extract_pptx(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
) -> ExtractedPayload:
    """Extract PPTX slide text frames, shape tables, and presenter notes in slide order."""
    payload = ExtractedPayload()
    idx = 0

    with path.open("rb") as handle:
        prs = Presentation(handle)
        payload.counts.slides = len(prs.slides)
        for slide_idx, slide in enumerate(prs.slides, start=1):
            slide_label = f"slide:{slide_idx}"
            for shape_idx, shape in enumerate(slide.shapes, start=1):
                if shape.has_text_frame:
                    paragraphs = [
                        p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()
                    ]
                    if paragraphs:
                        idx += 1
                        payload.items.append(
                            ExtractedItem(
                                item_index=idx,
                                item_type="text",
                                source_file=source_file,
                                file_id=file_id,
                                version_number=version_number,
                                page_or_sheet=slide_label,
                                location=f"shape:{shape_idx}",
                                text="\n".join(paragraphs),
                                extraction_method="native",
                            )
                        )
                        payload.counts.text_items += 1
                if shape.has_table:
                    matrix = [
                        [" ".join(cell.text.split()) for cell in row.cells]
                        for row in shape.table.rows
                    ]
                    if any(any(cell for cell in row) for row in matrix):
                        idx += 1
                        payload.items.append(
                            ExtractedItem(
                                item_index=idx,
                                item_type="table",
                                source_file=source_file,
                                file_id=file_id,
                                version_number=version_number,
                                page_or_sheet=slide_label,
                                location=f"table:{shape_idx}",
                                raw_values=matrix,
                                extraction_method="native",
                            )
                        )
                        payload.counts.tables += 1

            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    idx += 1
                    payload.items.append(
                        ExtractedItem(
                            item_index=idx,
                            item_type="slide_note",
                            source_file=source_file,
                            file_id=file_id,
                            version_number=version_number,
                            page_or_sheet=slide_label,
                            location="notes",
                            text=notes_text,
                            extraction_method="native",
                        )
                    )
                    payload.counts.text_items += 1

    payload.counts.total_items = len(payload.items)
    return payload


def extract_plain_text(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
) -> ExtractedPayload:
    """Extract UTF-8/Arabic plain-text documents line by line preserving exact content."""
    payload = ExtractedPayload()
    text_content, _encoding = _decode_text_bytes(path.read_bytes())
    idx = 0
    for line_no, raw_line in enumerate(text_content.splitlines(), start=1):
        cleaned = raw_line.strip()
        if not cleaned:
            continue
        idx += 1
        payload.items.append(
            ExtractedItem(
                item_index=idx,
                item_type="text",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet="text:body",
                location=f"line:{line_no}",
                text=cleaned,
                extraction_method="native",
            )
        )
        payload.counts.text_items += 1
    payload.counts.total_items = len(payload.items)
    return payload
