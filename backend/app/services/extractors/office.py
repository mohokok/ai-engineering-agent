"""Deterministic extractors for DOCX, XLSX, CSV, PPTX, and plain text engineering files."""

import csv
from dataclasses import dataclass, field
from decimal import Decimal
import io
from pathlib import Path
import re
from typing import Any

from docx import Document
from openpyxl.chartsheet import Chartsheet
from openpyxl.reader.excel import ExcelReader
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

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
    ocr_dpi: int | float | None = None
    status: ExtractionStatus = "extracted"


class _SafeExcelReader(ExcelReader):
    """Work around openpyxl 3.1.5 chartsheet crash when a chartsheet has no .rels entry."""

    def read_chartsheet(self, sheet: Any, rel: Any) -> Any:
        try:
            return super().read_chartsheet(sheet, rel)
        except AttributeError as exc:
            if "'list' object has no attribute 'find'" not in str(exc):
                raise
            # cs was already appended to self.wb before rels.find failed; keep sheet stub and continue
            return None


def _open_openpyxl_readonly(path: Path, *, data_only: bool) -> Any:
    """Load an XLSX workbook read-only while guarding against empty-rels Chartsheet crashes."""
    reader = _SafeExcelReader(
        path,
        read_only=True,
        keep_vba=False,
        data_only=data_only,
        keep_links=True,
        rich_text=False,
    )
    reader.read()
    return reader.wb


def _strip_with_raw(raw_text: str) -> tuple[str, str | None, str]:
    """Trim leading/trailing whitespace and retain the raw string when modified."""
    cleaned = raw_text.strip()
    if cleaned != raw_text:
        return cleaned, raw_text, "outer_whitespace_trimmed"
    return cleaned, None, "verbatim"


def _collapse_table_with_raw(
    raw_rows: list[list[str]],
) -> tuple[list[list[str]], list[list[str]] | None, str]:
    """Collapse multi-whitespace/newline runs inside table cells while retaining raw values on change."""
    collapsed = [[" ".join(cell.split()) for cell in row] for row in raw_rows]
    if collapsed != raw_rows:
        return collapsed, raw_rows, "cell_whitespace_collapsed"
    return collapsed, None, "verbatim"


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
            text, raw_text, norm = _strip_with_raw(para.text)
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
                    raw_text=raw_text,
                    normalization_applied=norm,
                    extraction_method="native",
                )
            )
            payload.counts.text_items += 1

        for t_i, table in enumerate(doc.tables, start=1):
            raw_matrix = [[cell.text for cell in row.cells] for row in table.rows]
            matrix, raw_uncollapsed, norm = _collapse_table_with_raw(raw_matrix)
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
                    raw_uncollapsed_values=raw_uncollapsed,
                    normalization_applied=norm,
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
    """Extract XLSX worksheets with exact cell coordinates, formulas, cached values, and reset dimensions."""
    payload = ExtractedPayload()
    idx = 0
    uncached_formula_count = 0

    wb_formulas = _open_openpyxl_readonly(path, data_only=False)
    wb_values = _open_openpyxl_readonly(path, data_only=True)
    try:
        payload.counts.sheets = len(wb_formulas.sheetnames)
        for sheet_name in wb_formulas.sheetnames:
            ws_f = wb_formulas[sheet_name]
            ws_v = wb_values[sheet_name]

            if isinstance(ws_f, Chartsheet) or not hasattr(ws_f, "iter_rows") or not hasattr(ws_v, "iter_rows"):
                payload.warnings.append(
                    f"Sheet '{sheet_name}' is a chartsheet with no worksheet grid cells; chart data was skipped."
                )
                continue

            # Reset cached <dimension> metadata so stale or truncated XML bounds cannot drop cells.
            if hasattr(ws_f, "reset_dimensions"):
                ws_f.reset_dimensions()
            if hasattr(ws_v, "reset_dimensions"):
                ws_v.reset_dimensions()

            sheet_state = getattr(ws_f, "sheet_state", "visible")
            if sheet_state != "visible":
                payload.warnings.append(
                    f"Sheet '{sheet_name}' has sheet_state='{sheet_state}'; hidden sheet contents were extracted."
                )

            sheet_label = f"sheet:{sheet_name}"

            cached_grid: dict[tuple[int, int], Any] = {}
            for r_i, v_row in enumerate(ws_v.iter_rows(values_only=False), start=1):
                for c_fallback, v_cell in enumerate(v_row, start=1):
                    val = getattr(v_cell, "value", None)
                    if val is not None:
                        col_idx = getattr(v_cell, "column", None) or c_fallback
                        row_idx = getattr(v_cell, "row", None) or r_i
                        cached_grid[(row_idx, col_idx)] = val

            recorded_rows: list[tuple[int, dict[int, str]]] = []
            formula_items: list[ExtractedItem] = []
            min_col: int | None = None
            max_col: int | None = None

            for r_i, f_row in enumerate(ws_f.iter_rows(values_only=False), start=1):
                row_cells: dict[int, str] = {}
                actual_row_num = r_i
                for c_fallback, cell in enumerate(f_row, start=1):
                    col_idx = getattr(cell, "column", None) or c_fallback
                    actual_row_num = getattr(cell, "row", None) or r_i
                    raw_formula_or_val = cell.value
                    num_fmt = getattr(cell, "number_format", None)
                    coord = (
                        getattr(cell, "coordinate", None)
                        or f"{get_column_letter(col_idx)}{actual_row_num}"
                    )
                    cached_val = cached_grid.get((actual_row_num, col_idx))

                    if isinstance(raw_formula_or_val, str) and raw_formula_or_val.startswith("="):
                        cached_str, exposed_fmt = _format_excel_scalar(cached_val, num_fmt)
                        if cached_val is None:
                            uncached_formula_count += 1
                        row_cells[col_idx] = (
                            cached_str if cached_val is not None else raw_formula_or_val
                        )
                        min_col = col_idx if min_col is None else min(min_col, col_idx)
                        max_col = col_idx if max_col is None else max(max_col, col_idx)
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
                                normalization_applied="verbatim_formula",
                                start_row=actual_row_num,
                                start_column=col_idx,
                                start_column_letter=get_column_letter(col_idx),
                                row_numbers=[actual_row_num],
                                extraction_method="native",
                            )
                        )
                    else:
                        formatted_val, exposed_fmt = _format_excel_scalar(
                            raw_formula_or_val, num_fmt
                        )
                        if raw_formula_or_val is not None and formatted_val != "":
                            row_cells[col_idx] = formatted_val
                            min_col = col_idx if min_col is None else min(min_col, col_idx)
                            max_col = col_idx if max_col is None else max(max_col, col_idx)

                if row_cells:
                    recorded_rows.append((actual_row_num, row_cells))

            if recorded_rows and min_col is not None and max_col is not None:
                row_numbers = [row_num for row_num, _ in recorded_rows]
                sheet_rows = [
                    [row_cells.get(c, "") for c in range(min_col, max_col + 1)]
                    for _, row_cells in recorded_rows
                ]
                start_col_letter = get_column_letter(min_col)
                end_col_letter = get_column_letter(max_col)
                range_loc = f"range:{start_col_letter}{row_numbers[0]}:{end_col_letter}{row_numbers[-1]}"
                idx += 1
                payload.items.append(
                    ExtractedItem(
                        item_index=idx,
                        item_type="table",
                        source_file=source_file,
                        file_id=file_id,
                        version_number=version_number,
                        page_or_sheet=sheet_label,
                        location=range_loc,
                        raw_values=sheet_rows,
                        normalization_applied="excel_number_format_preserving_precision",
                        start_row=row_numbers[0],
                        start_column=min_col,
                        start_column_letter=start_col_letter,
                        row_numbers=row_numbers,
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
    """Extract CSV records using StringIO(newline='') with exact row/column traceability."""
    payload = ExtractedPayload()
    text_content, encoding_used = _decode_text_bytes(path.read_bytes())
    reader = csv.reader(io.StringIO(text_content, newline=""))

    recorded: list[tuple[int, list[str], list[str]]] = []
    min_col: int | None = None
    max_col: int | None = None

    for record_num, row in enumerate(reader, start=1):
        stripped_row = [cell.strip() for cell in row]
        non_empty_cols = [c_idx for c_idx, val in enumerate(stripped_row, start=1) if val]
        if not non_empty_cols:
            continue
        min_col = non_empty_cols[0] if min_col is None else min(min_col, non_empty_cols[0])
        max_col = non_empty_cols[-1] if max_col is None else max(max_col, non_empty_cols[-1])
        recorded.append((record_num, stripped_row, list(row)))

    payload.counts.sheets = 1
    if recorded and min_col is not None and max_col is not None:
        row_numbers = [r_num for r_num, _, _ in recorded]
        rows = [
            [
                s_row[c - 1] if c - 1 < len(s_row) else ""
                for c in range(min_col, max_col + 1)
            ]
            for _, s_row, _ in recorded
        ]
        raw_untrimmed = [
            [
                raw_row[c - 1] if c - 1 < len(raw_row) else ""
                for c in range(min_col, max_col + 1)
            ]
            for _, _, raw_row in recorded
        ]
        changed = raw_untrimmed != rows
        start_col_letter = get_column_letter(min_col)
        end_col_letter = get_column_letter(max_col)
        range_loc = f"range:{start_col_letter}{row_numbers[0]}:{end_col_letter}{row_numbers[-1]}"
        payload.items.append(
            ExtractedItem(
                item_index=1,
                item_type="table",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet="sheet:CSV",
                location=range_loc,
                raw_values=rows,
                raw_uncollapsed_values=raw_untrimmed if changed else None,
                normalization_applied="outer_whitespace_trimmed" if changed else "verbatim",
                unit_or_format=encoding_used,
                start_row=row_numbers[0],
                start_column=min_col,
                start_column_letter=start_col_letter,
                row_numbers=row_numbers,
                extraction_method="native",
            )
        )
        payload.counts.tables = 1
    payload.counts.total_items = len(payload.items)
    return payload


def _iter_pptx_shapes(shapes: Any, prefix: str = "") -> list[tuple[str, str, Any]]:
    """Flatten PPTX slide shapes including nested grouped shapes with deterministic location paths."""
    collected: list[tuple[str, str, Any]] = []
    for shape_idx, shape in enumerate(shapes, start=1):
        if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP and hasattr(shape, "shapes"):
            group_prefix = f"{prefix}group:{shape_idx}/"
            collected.extend(_iter_pptx_shapes(shape.shapes, prefix=group_prefix))
        else:
            shape_loc = f"{prefix}shape:{shape_idx}"
            table_loc = f"{prefix}table:{shape_idx}"
            collected.append((shape_loc, table_loc, shape))
    return collected


def extract_pptx(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
) -> ExtractedPayload:
    """Extract PPTX slide text frames, grouped shapes, shape tables, and presenter notes."""
    payload = ExtractedPayload()
    idx = 0

    with path.open("rb") as handle:
        prs = Presentation(handle)
        payload.counts.slides = len(prs.slides)
        for slide_idx, slide in enumerate(prs.slides, start=1):
            slide_label = f"slide:{slide_idx}"
            for shape_loc, table_loc, shape in _iter_pptx_shapes(slide.shapes):
                if shape.has_text_frame:
                    raw_paragraphs = [p.text for p in shape.text_frame.paragraphs]
                    cleaned_paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
                    if cleaned_paragraphs:
                        idx += 1
                        joined_cleaned = "\n".join(cleaned_paragraphs)
                        joined_raw = "\n".join(raw_paragraphs)
                        payload.items.append(
                            ExtractedItem(
                                item_index=idx,
                                item_type="text",
                                source_file=source_file,
                                file_id=file_id,
                                version_number=version_number,
                                page_or_sheet=slide_label,
                                location=shape_loc,
                                text=joined_cleaned,
                                raw_text=joined_raw if joined_raw != joined_cleaned else None,
                                normalization_applied=(
                                    "outer_whitespace_trimmed"
                                    if joined_raw != joined_cleaned
                                    else "verbatim"
                                ),
                                extraction_method="native",
                            )
                        )
                        payload.counts.text_items += 1
                if shape.has_table:
                    raw_matrix = [[cell.text for cell in row.cells] for row in shape.table.rows]
                    matrix, raw_uncollapsed, norm = _collapse_table_with_raw(raw_matrix)
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
                                location=table_loc,
                                raw_values=matrix,
                                raw_uncollapsed_values=raw_uncollapsed,
                                normalization_applied=norm,
                                extraction_method="native",
                            )
                        )
                        payload.counts.tables += 1

            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_text, raw_notes, notes_norm = _strip_with_raw(
                    slide.notes_slide.notes_text_frame.text
                )
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
                            raw_text=raw_notes,
                            normalization_applied=notes_norm,
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
        cleaned, raw_orig, norm = _strip_with_raw(raw_line)
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
                raw_text=raw_orig,
                normalization_applied=norm,
                extraction_method="native",
            )
        )
        payload.counts.text_items += 1
    payload.counts.total_items = len(payload.items)
    return payload
