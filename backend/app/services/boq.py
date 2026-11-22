"""Step 10 Bill of Quantities service: DXF/IFC deterministic takeoffs, XLSX/PDF import, checks, rate provenance, and versioned exports."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.models import (
    AuditLog,
    BoqItem,
    BoqSheet,
    Deliverable,
    FileExtraction,
    Project,
    ProjectFile,
    ResearchSource,
)
from app.schemas.boq import (
    BoqCheckIssue,
    BoqChecksSummaryOut,
    BoqDetailOut,
    BoqExportOut,
    BoqExportRequest,
    BoqImportExtractionsRequest,
    BoqItemCreateRequest,
    BoqItemOut,
    BoqItemUpdateRequest,
    BoqListResponse,
    BoqSheetCreateRequest,
    BoqSheetSummaryOut,
    BoqSheetUpdateRequest,
    _validate_rate_source,
)
from app.schemas.reports import DeliverableOut
from app.services.boq_export import _sha256_file, generate_boq_csv, generate_boq_xlsx
from app.services.extraction import extract_project_file
from app.services.extractors.cad import (
    CAD_UNIT_SCALE_MAP,
    compute_layer_area_groups,
    compute_layer_length_groups,
    recover_dxf_block_insert_groups,
    resolve_cad_unit_context,
)
from app.services.extractors.pdf_and_image import assess_native_pdf_text_reliability
from app.services.projects import ProjectNotFoundError
from app.services.workspace import resolve_project_file_path

_ARABIC_INDIC_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
_WS_RE = re.compile(r"\s+")
_NUM_EXTRACT_RE = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)")
_SUMMARY_ROW_RE = re.compile(r"^(?:total|sub[-\s]?total|grand\s+total|الإجمالي|المجموع|الجملة)\b", re.IGNORECASE)

_UNIT_ALIASES: dict[str, tuple[str, str]] = {
    "m2": ("m2", "area_metric"),
    "m²": ("m2", "area_metric"),
    "sqm": ("m2", "area_metric"),
    "sq m": ("m2", "area_metric"),
    "sq.m": ("m2", "area_metric"),
    "م2": ("m2", "area_metric"),
    "م²": ("m2", "area_metric"),
    "متر مربع": ("m2", "area_metric"),
    "cm2": ("cm2", "area_submetric"),
    "cm²": ("cm2", "area_submetric"),
    "sq cm": ("cm2", "area_submetric"),
    "mm2": ("mm2", "area_submetric"),
    "mm²": ("mm2", "area_submetric"),
    "sq_in": ("sq_in", "area_imperial"),
    "sq in": ("sq_in", "area_imperial"),
    "in2": ("sq_in", "area_imperial"),
    "sq_ft": ("sq_ft", "area_imperial"),
    "sq ft": ("sq_ft", "area_imperial"),
    "ft2": ("sq_ft", "area_imperial"),
    "m": ("m", "length_metric"),
    "lm": ("m", "length_metric"),
    "m.l": ("m", "length_metric"),
    "م": ("m", "length_metric"),
    "م.ط": ("m", "length_metric"),
    "متر": ("m", "length_metric"),
    "متر طولي": ("m", "length_metric"),
    "cm": ("cm", "length_submetric"),
    "سم": ("cm", "length_submetric"),
    "mm": ("mm", "length_submetric"),
    "مم": ("mm", "length_submetric"),
    "in": ("in", "length_imperial"),
    "ft": ("ft", "length_imperial"),
    "m3": ("m3", "volume_metric"),
    "m³": ("m3", "volume_metric"),
    "cbm": ("m3", "volume_metric"),
    "م3": ("m3", "volume_metric"),
    "م³": ("m3", "volume_metric"),
    "متر مكعب": ("m3", "volume_metric"),
    "nos": ("nos", "count"),
    "no": ("nos", "count"),
    "no.": ("nos", "count"),
    "nr": ("nos", "count"),
    "pcs": ("nos", "count"),
    "pc": ("nos", "count"),
    "ea": ("nos", "count"),
    "each": ("nos", "count"),
    "عدد": ("nos", "count"),
    "قطعة": ("nos", "count"),
    "وحدة": ("nos", "count"),
    "kg": ("kg", "weight"),
    "كغ": ("kg", "weight"),
    "كجم": ("kg", "weight"),
    "ton": ("ton", "weight"),
    "tonne": ("ton", "weight"),
    "t": ("ton", "weight"),
    "طن": ("ton", "weight"),
    "ls": ("LS", "lump_sum"),
    "l.s": ("LS", "lump_sum"),
    "lump sum": ("LS", "lump_sum"),
    "مقطوعية": ("LS", "lump_sum"),
    "مقطوع": ("LS", "lump_sum"),
}

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "item_no": ("item no", "item no.", "item #", "item", "no.", "no", "code", "رقم البند", "البند", "رقم", "م"),
    "description": ("description", "item description", "work description", "particulars", "الوصف", "بيان الأعمال", "بيان", "التفاصيل"),
    "unit": ("unit", "uom", "u.m", "u/m", "الوحدة", "وحدة القياس", "وحدة"),
    "quantity": ("quantity", "qty", "est. qty", "est qty", "الكمية", "كمية"),
    "unit_rate": ("unit rate", "rate", "unit price", "price", "سعر الوحدة", "الفئة", "السعر الإفرادي", "السعر"),
    "reported_total": ("total", "amount", "line total", "value", "الإجمالي", "المجموع", "القيمة", "الجملة"),
    "technical_reference": ("technical reference", "tech ref", "technical ref", "spec", "specification", "standard", "المرجع الفني", "المواصفة"),
    "drawing_reference": ("drawing reference", "drawing ref", "dwg ref", "drawing", "sheet", "مرجع المخطط", "المخطط", "اللوحة"),
    "remarks": ("remarks", "notes", "comment", "ملاحظات"),
}

_AREA_DESC_HINTS = ("floor", "tile", "tiling", "plaster", "paint", "slab", "area", "roofing", "بلاط", "دهان", "لياسة", "أرضية", "مساحة")
_COUNT_DESC_HINTS = ("door", "window", "valve", "outlet", "fixture", "باب", "أبواب", "نافذة", "نوافذ", "شباك", "شبابيك")


class BoqNotFoundError(LookupError):
    """Raised when a BOQ sheet or line item does not exist."""


class BoqValidationError(ValueError):
    """Raised when unsourced rates, invalid units, or invalid provenance rules are violated."""


def normalize_boq_unit(raw_unit: str | None) -> tuple[str, str]:
    """Normalize BOQ unit string into (canonical_label, unit_family)."""
    cleaned = _WS_RE.sub(" ", str(raw_unit or "").strip())
    if not cleaned:
        return "", "missing"
    low = cleaned.lower()
    if any(tok in low for tok in ("unconfirmed", "unitless", "unspecified", "غير محدد")):
        return cleaned, "unconfirmed"
    if low in _UNIT_ALIASES:
        return _UNIT_ALIASES[low]
    compact = low.replace(" ", "")
    if compact in _UNIT_ALIASES:
        return _UNIT_ALIASES[compact]
    return cleaned, f"custom:{low}"


def _parse_numeric_cell(raw_val: Any) -> float | None:
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
        return float(raw_val)
    text = str(raw_val).strip().translate(_ARABIC_INDIC_TRANS)
    if not text:
        return None
    if text.startswith("="):
        return None
    m = _NUM_EXTRACT_RE.search(text.replace(" ", ""))
    if not m:
        return None
    num_str = m.group(1).replace(",", "")
    try:
        dec = Decimal(num_str)
        return float(dec)
    except (InvalidOperation, ValueError):
        return None


def _norm_text_key(val: str | None) -> str:
    return _WS_RE.sub(" ", str(val or "").strip().lower())


def _safe_filename_slug(name: str, default: str = "boq") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name.strip()).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:48] or default


def _verify_research_source_date_and_review(
    db: Session,
    project_id: str,
    *,
    unit_rate: float | None,
    rate_source_kind: str | None,
    rate_source_ref: str | None,
    rate_source_date: str | None,
) -> None:
    """Block unsourced rates, undated research rates, or unreviewed research sources cleanly."""
    if unit_rate is None:
        return
    try:
        _validate_rate_source(
            unit_rate=unit_rate,
            rate_source_kind=rate_source_kind,  # type: ignore[arg-type]
            rate_source_ref=rate_source_ref,
            rate_source_date=rate_source_date,
        )
    except ValueError as exc:
        raise BoqValidationError(str(exc)) from exc

    if rate_source_kind == "dated_research" and rate_source_ref:
        ref_low = rate_source_ref.lower()
        proj_sources = db.scalars(
            select(ResearchSource).where(ResearchSource.project_id == project_id)
        ).all()
        for src in proj_sources:
            url_match = src.url and src.url.lower() in ref_low
            id_match = src.id and src.id.lower() in ref_low
            if (url_match or id_match) and not src.reviewed:
                raise BoqValidationError(
                    f"Blocked rate from unreviewed research source '{src.source_name}' ({src.url})."
                )


def _compute_line_total(
    *,
    quantity: float,
    unit_rate: float | None,
    unit: str,
) -> float | None:
    if unit_rate is None:
        return None
    _, fam = normalize_boq_unit(unit)
    if fam == "unconfirmed":
        raise BoqValidationError(
            "Cannot price or total an unconfirmed CAD unit item; confirm the drawing unit via confirm-unit first."
        )
    return float((Decimal(str(quantity)) * Decimal(str(unit_rate))).quantize(Decimal("0.0001")))


def _detect_header_column_map(row_cells: list[str]) -> dict[str, int]:
    col_map: dict[str, int] = {}
    for c_idx, raw_cell in enumerate(row_cells):
        norm = _WS_RE.sub(" ", str(raw_cell or "").strip().lower()).rstrip(":")
        if not norm:
            continue
        for field_name, aliases in _COLUMN_ALIASES.items():
            if field_name in col_map:
                continue
            if norm in aliases or any(norm == a or norm.startswith(f"{a} (") or norm.startswith(f"{a}/") for a in aliases):
                col_map[field_name] = c_idx
                break
    return col_map


def _parse_boq_rows_from_table(
    rows: list[list[str]],
    *,
    source_file: str,
    file_id: str,
    extraction_id: str,
    sheet_or_page: str,
    is_ocr: bool = False,
) -> list[dict[str, Any]]:
    """Deterministically parse BOQ line items from an extracted XLSX/CSV/PDF table matrix."""
    header_idx: int | None = None
    col_map: dict[str, int] = {}
    for r_idx, row in enumerate(rows):
        candidate_map = _detect_header_column_map([str(c or "") for c in row])
        if "description" in candidate_map and (
            "quantity" in candidate_map or "unit" in candidate_map or "item_no" in candidate_map
        ):
            header_idx = r_idx
            col_map = candidate_map
            break

    if header_idx is None:
        return []

    parsed_rows: list[dict[str, Any]] = []
    for rel_r, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue
        if len(_detect_header_column_map(cells)) >= 3:
            continue

        def _get(field: str) -> str:
            idx = col_map.get(field)
            return cells[idx] if idx is not None and idx < len(cells) else ""

        item_no = _get("item_no")
        desc = _get("description")
        unit_raw = _get("unit")
        qty_raw = _get("quantity")
        rate_raw = _get("unit_rate")
        rep_total_raw = _get("reported_total")
        tech_ref = _get("technical_reference")
        dwg_ref = _get("drawing_reference")
        remarks = _get("remarks")

        if _SUMMARY_ROW_RE.match(desc) or _SUMMARY_ROW_RE.match(item_no):
            continue
        if not desc and not item_no:
            continue

        qty_val = _parse_numeric_cell(qty_raw)
        rate_val = _parse_numeric_cell(rate_raw)
        rep_total_val = _parse_numeric_cell(rep_total_raw)

        canon_unit, unit_fam = normalize_boq_unit(unit_raw)
        needs_check_reasons: list[str] = []
        if is_ocr:
            needs_check_reasons.append("Imported from OCR PDF table — verify OCR digits")
        if qty_val is None or qty_val <= 0:
            needs_check_reasons.append("Missing or non-positive quantity in imported schedule")
        if not canon_unit or unit_fam == "missing":
            needs_check_reasons.append("Missing unit in imported schedule")
        if rate_val is not None and qty_val is not None and rep_total_val is not None:
            expected = round(qty_val * rate_val, 4)
            if abs(rep_total_val - expected) > 0.01:
                needs_check_reasons.append(
                    f"Imported total ({rep_total_val}) != quantity*rate ({expected})"
                )

        if not desc:
            desc = f"Item {item_no}".strip()

        resolved_qty = float(qty_val) if qty_val is not None and qty_val >= 0 else 0.0
        resolved_total = (
            float((Decimal(str(resolved_qty)) * Decimal(str(rate_val))).quantize(Decimal("0.0001")))
            if rate_val is not None and unit_fam != "unconfirmed"
            else None
        )
        loc_note = f"{source_file} | {sheet_or_page} | row:{rel_r}"
        combined_remarks = "; ".join(bit for bit in (remarks, *needs_check_reasons) if bit)
        parsed_rows.append(
            {
                "item_no": item_no or f"IMP-{len(parsed_rows) + 1:02d}",
                "description": desc,
                "unit": canon_unit,
                "quantity": round(resolved_qty, 4),
                "unit_rate": round(float(rate_val), 4) if rate_val is not None else None,
                "total": resolved_total,
                "reported_total": round(float(rep_total_val), 4) if rep_total_val is not None else None,
                "technical_reference": tech_ref or None,
                "drawing_reference": dwg_ref or loc_note,
                "remarks": combined_remarks or f"Imported from {loc_note}",
                "verification_status": (
                    "Extracted-Needs-Check" if needs_check_reasons else "Extracted-Verified"
                ),
                "rate_source_kind": "owner_input" if rate_val is not None else None,
                "rate_source_ref": (
                    f"Imported BOQ '{source_file}' ({sheet_or_page}, row {rel_r})"
                    if rate_val is not None
                    else None
                ),
                "rate_source_date": datetime.now(timezone.utc).date().isoformat()
                if rate_val is not None
                else None,
                "source_file_id": file_id,
                "source_extraction_id": extraction_id,
                "discipline": "imported_boq",
                "layer_or_category": sheet_or_page,
            }
        )
    return parsed_rows


def _parse_boq_rows_from_pdf_text(
    text: str,
    *,
    source_file: str,
    file_id: str,
    extraction_id: str,
    page_label: str,
    is_ocr: bool,
) -> list[dict[str, Any]]:
    """Fallback parser for borderless tabular PDF text lines delimited by tabs, pipes, or double spaces."""
    candidate_rows: list[list[str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
        elif "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r"\s{2,}", line) if p.strip()]
        if len(parts) >= 3:
            candidate_rows.append(parts)
    if len(candidate_rows) < 2:
        return []
    return _parse_boq_rows_from_table(
        candidate_rows,
        source_file=source_file,
        file_id=file_id,
        extraction_id=extraction_id,
        sheet_or_page=page_label,
        is_ocr=is_ocr,
    )


def _extract_quantities_from_cad_and_bim(
    pf: ProjectFile,
    ext: FileExtraction,
    *,
    settings: Settings,
    project: Project,
    is_ar: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], int, list[str]]:
    """Build deterministic BOQ quantities (areas, lengths, counts) from DXF/DWG or IFC extractions."""
    payload = ext.payload_json if isinstance(ext.payload_json, dict) else {}
    inv = payload.get("drawing_inventory") if isinstance(payload.get("drawing_inventory"), dict) else {}
    rows: list[dict[str, Any]] = []
    expected_coverage: list[dict[str, str]] = []
    total_candidates = 0
    omitted_notes: list[str] = []

    if inv.get("kind") == "cad_dxf":
        unit_ctx = resolve_cad_unit_context(payload, inv, is_ar=is_ar)
        cad_doubtful = bool(unit_ctx["is_doubtful"])
        active_unit = str(unit_ctx["active_unit"])
        raw_declared = str(unit_ctx["raw_declared"])
        basis_display = str(unit_ctx["basis_display"])
        scale_to_m = CAD_UNIT_SCALE_MAP.get(active_unit, (None, ""))[0] if not cad_doubtful else None

        area_groups = list(inv.get("layer_area_groups") or [])
        if not area_groups and inv.get("closed_areas"):
            area_groups = compute_layer_area_groups(
                list(inv.get("closed_areas") or []),
                list(inv.get("layers") or []),
                units_doubtful=cad_doubtful,
            )

        area_idx = 0
        non_area_omitted = 0
        for grp in area_groups:
            if not isinstance(grp, dict):
                continue
            native_sum = float(grp.get("area_native_sum") or 0.0)
            if native_sum <= 0:
                continue
            total_candidates += 1
            if not grp.get("area_bearing"):
                non_area_omitted += 1
                continue
            layer = str(grp.get("layer") or "0")
            etype = str(grp.get("entity_type") or "LWPOLYLINE")
            cnt = int(grp.get("count") or 0)
            m2_sum = grp.get("area_m2_sum")
            area_idx += 1
            dwg_ref = f"{pf.original_filename} | layer:{layer} | {etype}"
            expected_coverage.append(
                {
                    "key": f"{pf.id}:cad_area:{layer}:{etype}",
                    "drawing_reference": dwg_ref,
                    "label": f"{pf.original_filename} layer '{layer}' ({etype}) area",
                }
            )
            if not cad_doubtful and m2_sum is not None:
                # Geometric contour sums (not net building area) always default to Extracted-Needs-Check until owner verifies!
                rows.append(
                    {
                        "item_no": f"CAD-A-{area_idx:02d}",
                        "description": (
                            f"مساحة هندسية — طبقة '{layer}' ({etype}، {cnt} محيط) [{pf.original_filename}]"
                            if is_ar
                            else f"Geometric area — layer '{layer}' ({etype}, {cnt} contours) [{pf.original_filename}]"
                        ),
                        "unit": "m2",
                        "quantity": round(float(m2_sum), 4),
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": f"DXF geometric contour sum ({basis_display})",
                        "drawing_reference": dwg_ref,
                        "remarks": "Geometric contour sum (not net building area; verify openings/overlaps) — defaults Extracted-Needs-Check",
                        "verification_status": "Extracted-Needs-Check",
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "cad_area",
                        "layer_or_category": layer,
                    }
                )
            else:
                # Never silently convert doubtful or unconfirmed units to m²!
                unconf_unit = (
                    f"unconfirmed ({raw_declared} sq)"
                    if raw_declared not in {"unitless", "unspecified unit", "غير محدد"}
                    else "unitless sq (confirm-unit required)"
                )
                rows.append(
                    {
                        "item_no": f"CAD-A-{area_idx:02d}",
                        "description": (
                            f"مساحة خام غير مؤكدة الوحدة — طبقة '{layer}' ({etype}، {cnt} محيط) [{pf.original_filename}]"
                            if is_ar
                            else f"Unconfirmed-unit CAD area — layer '{layer}' ({etype}, {cnt} contours) [{pf.original_filename}]"
                        ),
                        "unit": unconf_unit,
                        "quantity": round(native_sum, 4),
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": f"Raw CAD area blocked from metric conversion ({basis_display})",
                        "drawing_reference": dwg_ref,
                        "remarks": "BLOCKED METRIC CONVERSION: Drawing unit unconfirmed/doubtful — confirm drawing unit via confirm-unit before converting to m² or pricing.",
                        "verification_status": "Extracted-Needs-Check",
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "cad_area",
                        "layer_or_category": layer,
                    }
                )
        if non_area_omitted > 0:
            omitted_notes.append(f"{non_area_omitted} non-area-bearing CAD contour group(s) in {pf.original_filename}")

        len_groups = list(inv.get("layer_length_groups") or [])
        if len_groups:
            len_groups = compute_layer_length_groups(
                len_groups,
                scale_to_m=scale_to_m,
                units_doubtful=cad_doubtful,
            )
        len_idx = 0
        anno_len_omitted = 0
        for lgrp in len_groups:
            if not isinstance(lgrp, dict):
                continue
            native_sum = float(lgrp.get("length_native_sum") or 0.0)
            if native_sum <= 0:
                continue
            total_candidates += 1
            if lgrp.get("is_non_structural_layer"):
                anno_len_omitted += 1
                continue
            layer = str(lgrp.get("layer") or "0")
            etype = str(lgrp.get("entity_type") or "LINE")
            cnt = int(lgrp.get("count") or 0)
            m_sum = lgrp.get("length_m_sum")
            len_idx += 1
            dwg_ref = f"{pf.original_filename} | layer:{layer} | {etype}"
            expected_coverage.append(
                {
                    "key": f"{pf.id}:cad_len:{layer}:{etype}",
                    "drawing_reference": dwg_ref,
                    "label": f"{pf.original_filename} layer '{layer}' ({etype}) length",
                }
            )
            if not cad_doubtful and m_sum is not None:
                # Linear geometric sums also default to Extracted-Needs-Check; keep Extracted-Verified for block counts or owner-verified rows
                rows.append(
                    {
                        "item_no": f"CAD-L-{len_idx:02d}",
                        "description": (
                            f"أطوال خطية — طبقة '{layer}' ({etype}، {cnt} عنصر) [{pf.original_filename}]"
                            if is_ar
                            else f"Linear length — layer '{layer}' ({etype}, {cnt} entities) [{pf.original_filename}]"
                        ),
                        "unit": "m",
                        "quantity": round(float(m_sum), 4),
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": f"DXF linear sum ({basis_display})",
                        "drawing_reference": dwg_ref,
                        "remarks": f"ModelSpace {etype} cumulative length across {cnt} entity(ies) (defaults Extracted-Needs-Check until verified)",
                        "verification_status": "Extracted-Needs-Check",
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "cad_length",
                        "layer_or_category": layer,
                    }
                )
            else:
                unconf_lin = (
                    f"unconfirmed ({raw_declared})"
                    if raw_declared not in {"unitless", "unspecified unit", "غير محدد"}
                    else "unitless (confirm-unit required)"
                )
                rows.append(
                    {
                        "item_no": f"CAD-L-{len_idx:02d}",
                        "description": (
                            f"أطوال خطية خام غير مؤكدة الوحدة — طبقة '{layer}' ({etype}، {cnt} عنصر) [{pf.original_filename}]"
                            if is_ar
                            else f"Unconfirmed-unit CAD length — layer '{layer}' ({etype}, {cnt} entities) [{pf.original_filename}]"
                        ),
                        "unit": unconf_lin,
                        "quantity": round(native_sum, 4),
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": f"Raw CAD length blocked from metric conversion ({basis_display})",
                        "drawing_reference": dwg_ref,
                        "remarks": "BLOCKED METRIC CONVERSION: Drawing unit unconfirmed/doubtful — confirm drawing unit via confirm-unit before converting to m or pricing.",
                        "verification_status": "Extracted-Needs-Check",
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "cad_length",
                        "layer_or_category": layer,
                    }
                )
        if anno_len_omitted > 0:
            omitted_notes.append(f"{anno_len_omitted} annotation/dimension linear group(s) in {pf.original_filename}")

        blk_groups = list(inv.get("block_insert_groups") or [])
        if not blk_groups and inv.get("blocks"):
            # Recover real INSERT entity layers from read-only DXF/converted DXF on disk instead of inventing 'ModelSpace'
            recovered_groups: list[dict[str, Any]] = []
            try:
                candidate_paths: list[Path] = []
                if (pf.extension or Path(pf.original_filename).suffix).lower() == ".dxf":
                    candidate_paths.append(
                        resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, pf.stored_relative_path)
                    )
                if ext.artifact_relative_path:
                    conv_dir = (
                        resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, ext.artifact_relative_path).parent
                        / "converted"
                    )
                    if conv_dir.is_dir():
                        candidate_paths.extend(sorted(conv_dir.glob("*.dxf")))
                for cand_dxf in candidate_paths:
                    if cand_dxf.is_file():
                        recovered_groups = recover_dxf_block_insert_groups(cand_dxf)
                        if recovered_groups:
                            break
            except Exception:
                recovered_groups = []

            if recovered_groups:
                blk_groups = recovered_groups
            else:
                blk_groups = [
                    {
                        "layer": "unrecorded_layer_reextract",
                        "block_name": str(b.get("name") or ""),
                        "count": int(b.get("insert_count") or 0),
                        "layer_unrecorded": True,
                    }
                    for b in (inv.get("blocks") or [])
                    if isinstance(b, dict) and int(b.get("insert_count") or 0) > 0 and not b.get("is_xref")
                ]

        # Group deterministically by (block_name, layer) summing counts if duplicated
        blk_buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for bgrp in blk_groups:
            if not isinstance(bgrp, dict):
                continue
            b_cnt = int(bgrp.get("count") or 0)
            b_name = str(bgrp.get("block_name") or "").strip()
            b_layer = str(bgrp.get("layer") or "0")
            if b_cnt <= 0 or not b_name:
                continue
            key = (b_name, b_layer)
            bucket = blk_buckets.setdefault(
                key,
                {
                    "block_name": b_name,
                    "layer": b_layer,
                    "count": 0,
                    "layer_unrecorded": bool(bgrp.get("layer_unrecorded")),
                },
            )
            bucket["count"] += b_cnt

        all_defined_blocks = [
            b for b in (inv.get("blocks") or []) if isinstance(b, dict)
        ]
        zero_or_xref_blocks = sum(
            1
            for b in all_defined_blocks
            if int(b.get("insert_count") or 0) <= 0 or b.get("is_xref")
        )
        total_candidates += len(blk_buckets) + zero_or_xref_blocks
        if zero_or_xref_blocks > 0:
            omitted_notes.append(
                f"{zero_or_xref_blocks} unused/xref CAD block definition(s) in {pf.original_filename}"
            )

        cnt_idx = 0
        for (b_name, b_layer), bucket in sorted(blk_buckets.items()):
            b_cnt = int(bucket["count"])
            layer_unrecorded = bool(bucket["layer_unrecorded"])
            cnt_idx += 1
            dwg_ref = f"{pf.original_filename} | layer:{b_layer} | block:{b_name}"
            expected_coverage.append(
                {
                    "key": f"{pf.id}:cad_blk:{b_layer}:{b_name}",
                    "drawing_reference": dwg_ref,
                    "label": f"{pf.original_filename} block '{b_name}' on layer '{b_layer}' count",
                }
            )
            rows.append(
                {
                    "item_no": f"CAD-C-{cnt_idx:02d}",
                    "description": (
                        f"عدد البلوكات '{b_name}' على طبقة '{b_layer}' [{pf.original_filename}]"
                        if is_ar
                        else f"Block '{b_name}' inserts on layer '{b_layer}' [{pf.original_filename}]"
                    ),
                    "unit": "nos",
                    "quantity": float(b_cnt),
                    "unit_rate": None,
                    "total": None,
                    "reported_total": None,
                    "technical_reference": "DXF deterministic block insertion count (block + INSERT layer)",
                    "drawing_reference": dwg_ref,
                    "remarks": (
                        "Legacy extraction lacked INSERT entity layer — re-extract DXF to verify block layer."
                        if layer_unrecorded
                        else (
                            "Count extracted; parent drawing length unit is doubtful/unconfirmed (verify scale context)."
                            if cad_doubtful
                            else "Deterministic INSERT block count grouped by (block name + real layer)"
                        )
                    ),
                    "verification_status": (
                        "Extracted-Needs-Check" if (cad_doubtful or layer_unrecorded) else "Extracted-Verified"
                    ),
                    "rate_source_kind": None,
                    "rate_source_ref": None,
                    "rate_source_date": None,
                    "source_file_id": pf.id,
                    "source_extraction_id": ext.id,
                    "discipline": "cad_count",
                    "layer_or_category": b_layer,
                }
            )

    elif inv.get("kind") == "bim_ifc":
        units_map = inv.get("units") if isinstance(inv.get("units"), dict) else {}
        area_u_raw = units_map.get("AREAUNIT")
        len_u_raw = units_map.get("LENGTHUNIT")
        units_missing = not bool(area_u_raw or len_u_raw)
        canon_area_u = str(area_u_raw or "unconfirmed_area_unit")
        canon_len_u = str(len_u_raw or "unconfirmed_length_unit")

        spaces = list(inv.get("spaces") or [])
        for s_idx, sp in enumerate(spaces, start=1):
            if not isinstance(sp, dict):
                continue
            gid = str(sp.get("global_id") or s_idx)
            sp_name = str(sp.get("name") or sp.get("long_name") or gid)
            storey = str(sp.get("storey") or "unassigned")
            sp_area = sp.get("area")
            sp_src = str(sp.get("area_source") or "not_provided_in_ifc")
            dwg_ref = f"{pf.original_filename} | IfcSpace:{gid}"
            expected_coverage.append(
                {
                    "key": f"{pf.id}:ifc_space:{gid}",
                    "drawing_reference": dwg_ref,
                    "label": f"{pf.original_filename} IfcSpace '{sp_name}'",
                }
            )
            if sp_area is not None and not units_missing:
                rows.append(
                    {
                        "item_no": f"IFC-S-{s_idx:02d}",
                        "description": (
                            f"مساحة فراغ BIM: '{sp_name}' (الطابق: {storey}) [{pf.original_filename}]"
                            if is_ar
                            else f"BIM IfcSpace '{sp_name}' (Storey: {storey}) [{pf.original_filename}]"
                        ),
                        "unit": canon_area_u,
                        "quantity": round(float(sp_area), 4),
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": sp_src,
                        "drawing_reference": dwg_ref,
                        "remarks": f"Authored IFC quantity ({sp_src})",
                        "verification_status": "Extracted-Verified",
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "bim_space",
                        "layer_or_category": "IfcSpace",
                    }
                )
            else:
                rows.append(
                    {
                        "item_no": f"IFC-S-{s_idx:02d}",
                        "description": (
                            f"مساحة فراغ BIM مفقودة الكمية: '{sp_name}' (الطابق: {storey}) [{pf.original_filename}]"
                            if is_ar
                            else f"BIM IfcSpace '{sp_name}' (Storey: {storey}) — missing area [{pf.original_filename}]"
                        ),
                        "unit": canon_area_u if not units_missing else "unconfirmed_area_unit",
                        "quantity": round(float(sp_area), 4) if sp_area is not None else 0.0,
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": sp_src,
                        "drawing_reference": dwg_ref,
                        "remarks": (
                            "Missing IFC UnitsInContext — verify unit before pricing"
                            if units_missing
                            else "Missing authored Qto_SpaceBaseQuantities area in IFC model — verify in BIM tool"
                        ),
                        "verification_status": "Extracted-Needs-Check",
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "bim_space",
                        "layer_or_category": "IfcSpace",
                    }
                )

        elements = [e for e in (inv.get("elements") or []) if isinstance(e, dict)]
        walls = [e for e in elements if str(e.get("ifc_type") or "") in {"IfcWall", "IfcWallStandardCase"}]
        if walls:
            wall_areas = [float(w["area"]) for w in walls if w.get("area") is not None]
            if wall_areas:
                dwg_ref = f"{pf.original_filename} | IfcWall:area_sum"
                expected_coverage.append(
                    {
                        "key": f"{pf.id}:ifc_wall_area",
                        "drawing_reference": dwg_ref,
                        "label": f"{pf.original_filename} IfcWall authored area",
                    }
                )
                all_authored = len(wall_areas) == len(walls)
                rows.append(
                    {
                        "item_no": "IFC-W-01",
                        "description": (
                            f"مساحة الجدران الموثّقة في IFC ({len(wall_areas)}/{len(walls)} جدار) [{pf.original_filename}]"
                            if is_ar
                            else f"BIM IfcWall authored surface area ({len(wall_areas)} of {len(walls)} walls) [{pf.original_filename}]"
                        ),
                        "unit": canon_area_u if not units_missing else "unconfirmed_area_unit",
                        "quantity": round(sum(wall_areas), 4),
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": "Qto_WallBaseQuantities",
                        "drawing_reference": dwg_ref,
                        "remarks": (
                            "Authored wall areas extracted deterministically from Qto_WallBaseQuantities"
                            if all_authored and not units_missing
                            else f"Only {len(wall_areas)}/{len(walls)} walls had explicit Qto area; check unauthored walls"
                        ),
                        "verification_status": (
                            "Extracted-Verified" if all_authored and not units_missing else "Extracted-Needs-Check"
                        ),
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "bim_wall",
                        "layer_or_category": "IfcWall",
                    }
                )

            wall_lengths: list[float] = []
            for w in walls:
                qtos = w.get("quantities") if isinstance(w.get("quantities"), dict) else {}
                for _qname, qvals in qtos.items():
                    if isinstance(qvals, dict) and isinstance(qvals.get("Length"), (int, float)):
                        wall_lengths.append(float(qvals["Length"]))
                        break
            if wall_lengths:
                rows.append(
                    {
                        "item_no": "IFC-W-02",
                        "description": (
                            f"أطوال الجدران الموثّقة في IFC ({len(wall_lengths)}/{len(walls)} جدار) [{pf.original_filename}]"
                            if is_ar
                            else f"BIM IfcWall authored length ({len(wall_lengths)} of {len(walls)} walls) [{pf.original_filename}]"
                        ),
                        "unit": canon_len_u if not units_missing else "unconfirmed_length_unit",
                        "quantity": round(sum(wall_lengths), 4),
                        "unit_rate": None,
                        "total": None,
                        "reported_total": None,
                        "technical_reference": "Qto_WallBaseQuantities.Length",
                        "drawing_reference": f"{pf.original_filename} | IfcWall:length_sum",
                        "remarks": "Authored IFC wall length sum",
                        "verification_status": (
                            "Extracted-Verified"
                            if len(wall_lengths) == len(walls) and not units_missing
                            else "Extracted-Needs-Check"
                        ),
                        "rate_source_kind": None,
                        "rate_source_ref": None,
                        "rate_source_date": None,
                        "source_file_id": pf.id,
                        "source_extraction_id": ext.id,
                        "discipline": "bim_wall",
                        "layer_or_category": "IfcWall",
                    }
                )

        pcounts = inv.get("product_counts") if isinstance(inv.get("product_counts"), dict) else {}
        count_idx = 0
        for cls_name in ("IfcDoor", "IfcWindow", "IfcWall", "IfcSlab", "IfcColumn", "IfcBeam", "IfcStair"):
            c_val = int(pcounts.get(cls_name) or 0)
            if c_val <= 0:
                continue
            count_idx += 1
            dwg_ref = f"{pf.original_filename} | {cls_name}:count"
            expected_coverage.append(
                {
                    "key": f"{pf.id}:ifc_cnt:{cls_name}",
                    "drawing_reference": dwg_ref,
                    "label": f"{pf.original_filename} {cls_name} count",
                }
            )
            rows.append(
                {
                    "item_no": f"IFC-C-{count_idx:02d}",
                    "description": (
                        f"حصر عدد عناصر {cls_name} في نموذج IFC [{pf.original_filename}]"
                        if is_ar
                        else f"BIM {cls_name} element count [{pf.original_filename}]"
                    ),
                    "unit": "nos",
                    "quantity": float(c_val),
                    "unit_rate": None,
                    "total": None,
                    "reported_total": None,
                    "technical_reference": f"IFC schema {inv.get('schema') or 'IFC'} product count",
                    "drawing_reference": dwg_ref,
                    "remarks": (
                        "Counted from IfcProduct summary (3D Qto dimensions/volumes not auto-calculated)"
                        if cls_name not in {"IfcDoor", "IfcWindow", "IfcWall"}
                        else f"Deterministic count of {cls_name} instances"
                    ),
                    "verification_status": (
                        "Extracted-Verified"
                        if cls_name in {"IfcDoor", "IfcWindow", "IfcWall"} and not units_missing
                        else "Extracted-Needs-Check"
                    ),
                    "rate_source_kind": None,
                    "rate_source_ref": None,
                    "rate_source_date": None,
                    "source_file_id": pf.id,
                    "source_extraction_id": ext.id,
                    "discipline": "bim_count",
                    "layer_or_category": cls_name,
                }
            )

        bim_added = len(rows)
        total_candidates += bim_added

    return rows, expected_coverage, total_candidates, omitted_notes


def run_boq_checks_on_sheet(
    sheet: BoqSheet,
    items: list[BoqItem],
    *,
    expected_coverage: list[dict[str, str]] | None = None,
) -> BoqChecksSummaryOut:
    """Execute deterministic BOQ audit checks (duplicates, missing items, unit consistency, arithmetic totals)."""
    issues: list[BoqCheckIssue] = []
    flagged_map: dict[str, dict[str, Any]] = {}
    chk_counter = 0

    def next_chk_id() -> str:
        nonlocal chk_counter
        chk_counter += 1
        return f"CHK-{chk_counter:03d}"

    def _flag(item: BoqItem, reason: str) -> None:
        if item.id not in flagged_map:
            flagged_map[item.id] = {
                "item_id": item.id,
                "item_no": item.item_no,
                "description": item.description,
                "unit": item.unit,
                "quantity": item.quantity,
                "verification_status": item.verification_status,
                "reasons": [reason],
            }
        elif reason not in flagged_map[item.id]["reasons"]:
            flagged_map[item.id]["reasons"].append(reason)

    if not items:
        issues.append(
            BoqCheckIssue(
                issue_id=next_chk_id(),
                check_type="missing_item",
                severity="high",
                message="BOQ contains no line items; import DXF/IFC/XLSX/PDF or add manual lines.",
                recommended_action="Import extracted drawings/BOQs or add manual items before issuing.",
            )
        )

    # 1. Duplicate checks: item_no collisions + near-identical (description, unit, quantity) or drawing_reference
    by_item_no: dict[str, list[BoqItem]] = {}
    by_desc_sig: dict[tuple[str, str, float], list[BoqItem]] = {}
    for item in items:
        ino_key = _norm_text_key(item.item_no)
        if ino_key:
            by_item_no.setdefault(ino_key, []).append(item)
        canon_u, _ = normalize_boq_unit(item.unit)
        desc_sig = (_norm_text_key(item.description), canon_u.lower(), round(float(item.quantity or 0.0), 4))
        if desc_sig[0]:
            by_desc_sig.setdefault(desc_sig, []).append(item)

    for ino_key, group in by_item_no.items():
        if len(group) > 1:
            ids_lbl = ", ".join(it.item_no for it in group)
            for it in group:
                _flag(it, f"Duplicate item number '{it.item_no}'")
            issues.append(
                BoqCheckIssue(
                    issue_id=next_chk_id(),
                    check_type="duplicate_item",
                    severity="high",
                    item_id=group[0].id,
                    item_no=group[0].item_no,
                    message=f"Duplicate item number '{ino_key}' appears {len(group)} times ({ids_lbl}).",
                    recommended_action="Renumber distinct items or merge duplicate BOQ lines.",
                )
            )

    for sig, group in by_desc_sig.items():
        if len(group) > 1:
            ino_list = ", ".join(it.item_no or f"row#{it.row_order}" for it in group)
            for it in group:
                _flag(it, "Duplicate BOQ description/unit/quantity signature")
            issues.append(
                BoqCheckIssue(
                    issue_id=next_chk_id(),
                    check_type="duplicate_item",
                    severity="high",
                    item_id=group[0].id,
                    item_no=group[0].item_no,
                    message=f"Duplicate item detected across rows [{ino_list}]: '{group[0].description[:90]}' ({sig[2]} {sig[1]}).",
                    recommended_action="Verify whether duplicate entry is double-counting the same scope.",
                )
            )

    # 2. Per-item missing fields, unit consistency, arithmetic totals, rate provenance, & human-verification tagging
    area_families_seen: set[str] = set()
    len_families_seen: set[str] = set()
    verified_subtotal = Decimal("0")
    needs_check_subtotal = Decimal("0")
    grand_total = Decimal("0")
    priced_count = 0
    unpriced_count = 0

    for item in items:
        canon_u, fam = normalize_boq_unit(item.unit)
        qty_val = float(item.quantity or 0.0)

        if item.verification_status == "Extracted-Needs-Check":
            _flag(item, "Tagged Extracted-Needs-Check — human review required")

        if not item.item_no.strip():
            issues.append(
                BoqCheckIssue(
                    issue_id=next_chk_id(),
                    check_type="missing_item",
                    severity="medium",
                    item_id=item.id,
                    message=f"Row #{item.row_order} ('{item.description[:60]}') is missing an Item No.",
                    recommended_action="Assign a sequential BOQ item number.",
                )
            )
            _flag(item, "Missing item number")

        if fam == "missing" or not canon_u:
            issues.append(
                BoqCheckIssue(
                    issue_id=next_chk_id(),
                    check_type="missing_item",
                    severity="high",
                    item_id=item.id,
                    item_no=item.item_no,
                    message=f"Item '{item.item_no or item.row_order}' is missing a measurement unit.",
                    recommended_action="Assign explicit measurement unit before pricing or tender issue.",
                )
            )
            _flag(item, "Missing measurement unit")

        if qty_val <= 0:
            issues.append(
                BoqCheckIssue(
                    issue_id=next_chk_id(),
                    check_type="missing_item",
                    severity="high",
                    item_id=item.id,
                    item_no=item.item_no,
                    message=f"Item '{item.item_no or item.row_order}' ({item.description[:70]}) has zero/missing quantity ({qty_val}).",
                    recommended_action="Verify missing drawing/BIM quantity in source file or enter confirmed measurement.",
                )
            )
            _flag(item, f"Missing or zero quantity ({qty_val})")

        if fam == "unconfirmed":
            issues.append(
                BoqCheckIssue(
                    issue_id=next_chk_id(),
                    check_type="unverified_unit",
                    severity="high",
                    item_id=item.id,
                    item_no=item.item_no,
                    message=f"Item '{item.item_no}' uses unconfirmed CAD unit '{item.unit}'; metric conversion & pricing are blocked.",
                    recommended_action="Confirm drawing unit via /confirm-unit and re-import CAD quantities.",
                )
            )
            _flag(item, f"Unconfirmed unit '{item.unit}' — metric conversion blocked")

        if fam.startswith("area_"):
            area_families_seen.add(fam)
        elif fam.startswith("length_"):
            len_families_seen.add(fam)

        desc_low = _norm_text_key(item.description)
        if canon_u == "nos" and any(k in desc_low for k in _AREA_DESC_HINTS) and not any(k in desc_low for k in _COUNT_DESC_HINTS):
            issues.append(
                BoqCheckIssue(
                    issue_id=next_chk_id(),
                    check_type="unit_consistency",
                    severity="medium",
                    item_id=item.id,
                    item_no=item.item_no,
                    message=f"Item '{item.item_no}' ('{item.description[:60]}') uses count unit 'nos' for a surface/area description.",
                    recommended_action="Verify whether unit should be 'm2' rather than 'nos'.",
                )
            )
            _flag(item, "Unit vs description mismatch ('nos' on area description)")

        if item.unit_rate is not None:
            priced_count += 1
            if not item.rate_source_kind or (
                item.rate_source_kind == "dated_research" and not (item.rate_source_date and item.rate_source_ref)
            ):
                issues.append(
                    BoqCheckIssue(
                        issue_id=next_chk_id(),
                        check_type="rate_provenance",
                        severity="high",
                        item_id=item.id,
                        item_no=item.item_no,
                        message=f"Item '{item.item_no}' has a unit rate without complete owner/dated-research attribution.",
                        recommended_action="Attach owner input reference or dated research citation (with date), or clear unit rate.",
                    )
                )
                _flag(item, "Incomplete rate provenance")

            expected_dec = (Decimal(str(qty_val)) * Decimal(str(item.unit_rate))).quantize(Decimal("0.0001"))
            expected_float = float(expected_dec)
            if item.total is None or abs(float(item.total) - expected_float) > 0.01:
                issues.append(
                    BoqCheckIssue(
                        issue_id=next_chk_id(),
                        check_type="arithmetic_total",
                        severity="high",
                        item_id=item.id,
                        item_no=item.item_no,
                        message=(
                            f"Arithmetic mismatch on '{item.item_no}': stored total ({item.total}) != "
                            f"quantity ({qty_val}) * unit_rate ({item.unit_rate}) = {expected_float}."
                        ),
                        recommended_action="Recompute line total deterministically via Python/BOQ save.",
                    )
                )
                _flag(item, f"Arithmetic total mismatch ({item.total} vs {expected_float})")
            if item.reported_total is not None and abs(float(item.reported_total) - expected_float) > 0.01:
                issues.append(
                    BoqCheckIssue(
                        issue_id=next_chk_id(),
                        check_type="arithmetic_total",
                        severity="high",
                        item_id=item.id,
                        item_no=item.item_no,
                        message=(
                            f"Imported BOQ arithmetic discrepancy on '{item.item_no}': source schedule stated {item.reported_total} {sheet.currency}, "
                            f"but {qty_val} * {item.unit_rate} = {expected_float} {sheet.currency}."
                        ),
                        recommended_action="Review imported BOQ spreadsheet/PDF arithmetic error against owner baseline.",
                    )
                )
                _flag(item, f"Imported stated total {item.reported_total} != computed {expected_float}")

            grand_total += expected_dec
            if item.verification_status == "Extracted-Needs-Check":
                needs_check_subtotal += expected_dec
            else:
                verified_subtotal += expected_dec
        else:
            unpriced_count += 1

    # 3. Cross-sheet mixed area/length system consistency check (e.g. mixing m2 with cm2/sq_in)
    if len(area_families_seen) > 1:
        issues.append(
            BoqCheckIssue(
                issue_id=next_chk_id(),
                check_type="unit_consistency",
                severity="high",
                message=f"Inconsistent area unit systems within BOQ sheet: {', '.join(sorted(area_families_seen))}.",
                recommended_action="Standardize area rows to consistent metric 'm2' after confirming drawing units.",
            )
        )
    if len(len_families_seen) > 1:
        issues.append(
            BoqCheckIssue(
                issue_id=next_chk_id(),
                check_type="unit_consistency",
                severity="high",
                message=f"Inconsistent linear unit systems within BOQ sheet: {', '.join(sorted(len_families_seen))}.",
                recommended_action="Standardize linear lengths to consistent metric 'm' after confirming drawing units.",
            )
        )

    # 4. Expected drawing/BIM element coverage check (detects omitted DXF/IFC elements!)
    if expected_coverage:
        existing_refs = {_norm_text_key(it.drawing_reference) for it in items if it.drawing_reference}
        for cov in expected_coverage:
            ref_key = _norm_text_key(cov.get("drawing_reference"))
            if ref_key and ref_key not in existing_refs:
                issues.append(
                    BoqCheckIssue(
                        issue_id=next_chk_id(),
                        check_type="missing_item",
                        severity="high",
                        message=f"Missing extracted quantity item in BOQ for {cov['label']} ({cov['drawing_reference']}).",
                        recommended_action="Re-import drawing/BIM quantities or add explicit BOQ coverage note if excluded intentionally.",
                    )
                )

    # 5. Surface explicit "N of M" note in checks when any extracted items/groups were omitted during selection/filtering
    sheet_meta = sheet.source_metadata_json if isinstance(sheet.source_metadata_json, dict) else {}
    om_sum = sheet_meta.get("omission_summary")
    if isinstance(om_sum, dict) and int(om_sum.get("omitted_count") or 0) > 0:
        issues.append(
            BoqCheckIssue(
                issue_id=next_chk_id(),
                check_type="missing_item",
                severity="info",
                message=str(
                    om_sum.get("note")
                    or f"Included {om_sum.get('included_count')} of {om_sum.get('total_count')} extracted items/groups."
                ),
                recommended_action="Review omitted non-area-bearing layers, annotation lines, or unused block definitions.",
            )
        )

    flagged_list = [
        {
            "item_id": entry["item_id"],
            "item_no": entry["item_no"],
            "description": entry["description"],
            "unit": entry["unit"],
            "quantity": entry["quantity"],
            "verification_status": entry["verification_status"],
            "reason": "; ".join(entry["reasons"]),
        }
        for entry in flagged_map.values()
    ]
    high_cnt = sum(1 for i in issues if i.severity == "high")

    return BoqChecksSummaryOut(
        total_items=len(items),
        verified_items_count=sum(1 for i in items if i.verification_status == "Extracted-Verified"),
        needs_check_items_count=sum(1 for i in items if i.verification_status == "Extracted-Needs-Check"),
        manual_items_count=sum(1 for i in items if i.verification_status == "Manual"),
        priced_items_count=priced_count,
        unpriced_items_count=unpriced_count,
        verified_priced_subtotal=round(float(verified_subtotal), 4),
        needs_check_priced_subtotal=round(float(needs_check_subtotal), 4),
        grand_total=round(float(grand_total), 4),
        issues_count=len(issues),
        high_issues_count=high_cnt,
        issues=issues,
        flagged_item_ids=list(flagged_map.keys()),
        flagged_items=flagged_list,
    )


def _persist_checks_snapshot(sheet: BoqSheet, checks: BoqChecksSummaryOut) -> None:
    sheet.checks_summary_json = checks.model_dump()


def _load_expected_coverage_for_sheet(
    db: Session,
    sheet: BoqSheet,
) -> list[dict[str, str]]:
    meta = sheet.source_metadata_json if isinstance(sheet.source_metadata_json, dict) else {}
    cov = meta.get("expected_coverage")
    return [dict(c) for c in cov if isinstance(c, dict)] if isinstance(cov, list) else []


def _to_item_out(item: BoqItem) -> BoqItemOut:
    return BoqItemOut(
        id=item.id,
        boq_sheet_id=item.boq_sheet_id,
        row_order=item.row_order,
        item_no=item.item_no,
        description=item.description,
        unit=item.unit,
        quantity=float(item.quantity or 0.0),
        unit_rate=float(item.unit_rate) if item.unit_rate is not None else None,
        total=float(item.total) if item.total is not None else None,
        reported_total=float(item.reported_total) if item.reported_total is not None else None,
        technical_reference=item.technical_reference,
        drawing_reference=item.drawing_reference,
        remarks=item.remarks,
        verification_status=item.verification_status,  # type: ignore[arg-type]
        rate_source_kind=item.rate_source_kind,  # type: ignore[arg-type]
        rate_source_ref=item.rate_source_ref,
        rate_source_date=item.rate_source_date,
        source_file_id=item.source_file_id,
        source_extraction_id=item.source_extraction_id,
        discipline=item.discipline,
        layer_or_category=item.layer_or_category,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _to_deliverable_out(row: Deliverable) -> DeliverableOut:
    return DeliverableOut(
        id=row.id,
        project_id=row.project_id,
        report_id=row.report_id,
        boq_id=row.boq_id,
        drawing_id=row.drawing_id,
        calculation_id=row.calculation_id,
        specification_id=row.specification_id,
        comparison_id=row.comparison_id,
        schedule_id=row.schedule_id,
        assessment_id=row.assessment_id,
        structural_id=row.structural_id,
        task_id=row.task_id,
        file_id=row.file_id,
        title=row.title,
        deliverable_type=row.deliverable_type,
        discipline=row.discipline,
        format=row.format,
        classification=row.classification,
        status=row.status,
        version=row.version,
        folder_name=row.folder_name,
        filename=row.filename,
        relative_path=row.relative_path,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        summary=row.summary,
        download_url=f"/api/deliverables/{row.id}/download",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_boq_summary_out(sheet: BoqSheet, checks: BoqChecksSummaryOut | None = None) -> BoqSheetSummaryOut:
    if checks is None:
        if isinstance(sheet.checks_summary_json, dict) and sheet.checks_summary_json:
            checks = BoqChecksSummaryOut.model_validate(sheet.checks_summary_json)
        else:
            checks = run_boq_checks_on_sheet(sheet, list(sheet.items or []))
    return BoqSheetSummaryOut(
        id=sheet.id,
        project_id=sheet.project_id,
        project_code=sheet.project.code if sheet.project else "",
        project_name=sheet.project.name if sheet.project else "",
        task_id=sheet.task_id,
        title=sheet.title,
        language=sheet.language,
        currency=sheet.currency,
        classification=sheet.classification,
        revision=sheet.revision,
        version=sheet.version,
        export_version=sheet.export_version,
        source_scope=sheet.source_scope,
        status=sheet.status,
        summary=sheet.summary,
        items_count=checks.total_items,
        grand_total=checks.grand_total,
        issues_count=checks.issues_count,
        high_issues_count=checks.high_issues_count,
        created_at=sheet.created_at,
        updated_at=sheet.updated_at,
    )


def _to_boq_detail_out(sheet: BoqSheet, checks: BoqChecksSummaryOut | None = None) -> BoqDetailOut:
    items = list(sheet.items or [])
    if checks is None:
        if isinstance(sheet.checks_summary_json, dict) and sheet.checks_summary_json:
            checks = BoqChecksSummaryOut.model_validate(sheet.checks_summary_json)
        else:
            checks = run_boq_checks_on_sheet(sheet, items)
    summary_out = _to_boq_summary_out(sheet, checks)
    delivs = sorted(list(sheet.deliverables or []), key=lambda d: (d.version, d.format), reverse=True)
    return BoqDetailOut(
        **summary_out.model_dump(),
        checks=checks,
        items=[_to_item_out(it) for it in items],
        deliverables=[_to_deliverable_out(d) for d in delivs],
        source_metadata=dict(sheet.source_metadata_json or {}),
    )


def _gather_rows_from_files(
    db: Session,
    settings: Settings,
    *,
    project: Project,
    file_ids: list[str],
    include_dxf_ifc: bool,
    include_boq_imports: bool,
    is_ar: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str], list[str]]:
    if file_ids:
        target_files = [db.get(ProjectFile, fid) for fid in dict.fromkeys(file_ids)]
        missing = [fid for fid, pf in zip(dict.fromkeys(file_ids), target_files) if pf is None]
        if missing:
            raise BoqNotFoundError(f"Project file(s) not found: {', '.join(missing)}")
        resolved_files = [pf for pf in target_files if pf is not None]
        for pf in resolved_files:
            if pf.project_id != project.id:
                raise BoqValidationError(f"File '{pf.original_filename}' belongs to a different project.")
    else:
        resolved_files = db.scalars(
            select(ProjectFile)
            .where(ProjectFile.project_id == project.id)
            .order_by(ProjectFile.created_at.asc())
        ).all()

    collected_rows: list[dict[str, Any]] = []
    expected_cov: list[dict[str, str]] = []
    used_file_ids: list[str] = []
    skipped_notes: list[str] = []
    total_candidates = 0
    omission_reasons: list[str] = []

    for pf in resolved_files:
        ext_lower = (pf.extension or Path(pf.original_filename).suffix).lower()
        is_cad_bim = ext_lower in {".dxf", ".dwg", ".ifc"}
        is_boq_doc = ext_lower in {".xlsx", ".pdf", ".csv"}
        if is_cad_bim and not include_dxf_ifc:
            continue
        if is_boq_doc and not include_boq_imports:
            continue
        if not is_cad_bim and not is_boq_doc:
            continue

        latest_ext = db.scalar(
            select(FileExtraction)
            .where(FileExtraction.file_id == pf.id, FileExtraction.status != "failed")
            .order_by(FileExtraction.version_number.desc(), FileExtraction.extraction_version.desc())
            .limit(1)
        )
        if latest_ext is None:
            try:
                extract_project_file(db, settings, pf.id)
            except Exception as exc:
                skipped_notes.append(f"Skipped '{pf.original_filename}' (extraction unavailable: {exc})")
                continue
            latest_ext = db.scalar(
                select(FileExtraction)
                .where(FileExtraction.file_id == pf.id, FileExtraction.status != "failed")
                .order_by(FileExtraction.version_number.desc(), FileExtraction.extraction_version.desc())
                .limit(1)
            )
            if latest_ext is None:
                continue

        payload = latest_ext.payload_json if isinstance(latest_ext.payload_json, dict) else {}
        if is_cad_bim:
            cad_rows, cov, file_total_cand, file_omitted = _extract_quantities_from_cad_and_bim(
                pf,
                latest_ext,
                settings=settings,
                project=project,
                is_ar=is_ar,
            )
            total_candidates += file_total_cand
            omission_reasons.extend(file_omitted)
            if cad_rows:
                used_file_ids.append(pf.id)
                collected_rows.extend(cad_rows)
                expected_cov.extend(cov)
            elif cov:
                expected_cov.extend(cov)
        elif is_boq_doc:
            ext_items = list(payload.get("items") or [])
            imported_for_file: list[dict[str, Any]] = []
            for item in ext_items:
                if not isinstance(item, dict):
                    continue
                if item.get("item_type") == "table" and isinstance(item.get("raw_values"), list):
                    tbl_text = " ".join(
                        str(c) for r in item["raw_values"] for c in (r or []) if c
                    )
                    bad_nat, _ = assess_native_pdf_text_reliability(tbl_text)
                    if bad_nat:
                        msg = f"Skipped unreliable native table in '{pf.original_filename}' ({item.get('page_or_sheet')})."
                        skipped_notes.append(msg)
                        omission_reasons.append(msg)
                        total_candidates += 1
                        continue
                    parsed_tbl = _parse_boq_rows_from_table(
                        item["raw_values"],
                        source_file=pf.original_filename,
                        file_id=pf.id,
                        extraction_id=latest_ext.id,
                        sheet_or_page=str(item.get("page_or_sheet") or "sheet"),
                        is_ocr=bool(item.get("extraction_method") == "ocr"),
                    )
                    total_candidates += len(parsed_tbl)
                    imported_for_file.extend(parsed_tbl)
            # PDF fallback when tables lacked grid borders
            if not imported_for_file and ext_lower == ".pdf":
                for item in ext_items:
                    if not isinstance(item, dict):
                        continue
                    p_status = str(item.get("page_status") or "")
                    if p_status in {"failed", "ocr_empty_or_blank"} or item.get("native_text_unreliable"):
                        continue
                    raw_txt = str(item.get("text") or "").strip()
                    if not raw_txt:
                        continue
                    bad_txt, _ = assess_native_pdf_text_reliability(raw_txt)
                    if bad_txt:
                        continue
                    parsed_pdf = _parse_boq_rows_from_pdf_text(
                        raw_txt,
                        source_file=pf.original_filename,
                        file_id=pf.id,
                        extraction_id=latest_ext.id,
                        page_label=str(item.get("page_or_sheet") or "page"),
                        is_ocr=bool(
                            item.get("item_type") == "ocr_text"
                            or item.get("extraction_method") == "ocr"
                            or item.get("ocr_low_confidence")
                        ),
                    )
                    total_candidates += len(parsed_pdf)
                    imported_for_file.extend(parsed_pdf)
            if imported_for_file:
                used_file_ids.append(pf.id)
                collected_rows.extend(imported_for_file)

    included_count = len(collected_rows)
    effective_total = max(total_candidates, included_count)
    omitted_count = max(0, effective_total - included_count)
    omission_summary: dict[str, Any] = {
        "included_count": included_count,
        "total_count": effective_total,
        "omitted_count": omitted_count,
        "details": omission_reasons,
        "note": (
            f"Included {included_count} of {effective_total} extracted items/groups ({omitted_count} omitted: {'; '.join(omission_reasons)})"
            if omitted_count > 0
            else f"Included {included_count} of {effective_total} extracted items/groups (none omitted)"
        ),
    }
    return collected_rows, expected_cov, used_file_ids, skipped_notes, omission_summary


def create_boq_sheet(
    db: Session,
    settings: Settings,
    project_id: str,
    payload: BoqSheetCreateRequest,
) -> BoqDetailOut:
    """Create a BOQ sheet populated deterministically from selected/all DXF/IFC/XLSX/PDF extractions."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    max_ver = db.scalar(
        select(func.coalesce(func.max(BoqSheet.version), 0)).where(BoqSheet.project_id == project.id)
    )
    version = int(max_ver or 0) + 1
    revision = f"Rev {version:02d}"
    is_ar = payload.language == "ar"
    title = payload.title or (
        f"جدول الكميات والمواصفات — {project.code}"
        if is_ar
        else f"Bill of Quantities (BOQ) — {project.code}"
    )

    extracted_rows, expected_cov, used_files, skipped_notes, omission_summary = _gather_rows_from_files(
        db,
        settings,
        project=project,
        file_ids=payload.file_ids,
        include_dxf_ifc=payload.include_dxf_ifc,
        include_boq_imports=payload.include_boq_imports,
        is_ar=is_ar,
    )

    sheet = BoqSheet(
        project_id=project.id,
        task_id=payload.task_id,
        title=title,
        language=payload.language,
        currency=payload.currency,
        classification=payload.classification,
        revision=revision,
        version=version,
        export_version=0,
        source_scope="extracted" if extracted_rows else "manual",
        status="draft",
        source_metadata_json={
            "imported_file_ids": used_files,
            "expected_coverage": expected_cov,
            "skipped_notes": skipped_notes,
            "omission_summary": omission_summary,
        },
    )
    db.add(sheet)
    db.flush()

    created_items: list[BoqItem] = []
    for r_ord, row_data in enumerate(extracted_rows, start=1):
        item = BoqItem(boq_sheet_id=sheet.id, row_order=r_ord, **row_data)
        db.add(item)
        created_items.append(item)
    db.flush()

    checks = run_boq_checks_on_sheet(sheet, created_items, expected_coverage=expected_cov)
    _persist_checks_snapshot(sheet, checks)
    sheet.summary = (
        f"BOQ {revision} ({sheet.currency}): {checks.total_items} items "
        f"(Verified={checks.verified_items_count}, Needs-Check={checks.needs_check_items_count}, Manual={checks.manual_items_count}), "
        f"Grand Total={checks.grand_total} {sheet.currency}, Check Issues={checks.issues_count}."
    )
    db.add(
        AuditLog(
            project_id=project.id,
            action="boq.created",
            entity_type="boq_sheet",
            entity_id=sheet.id,
            actor="boq_module",
            details_json={
                "currency": sheet.currency,
                "classification": sheet.classification,
                "items_count": checks.total_items,
                "issues_count": checks.issues_count,
            },
        )
    )
    db.commit()
    return get_boq_detail(db, sheet.id)


def list_project_boq_sheets(db: Session, project_id: str) -> BoqListResponse:
    """List all BOQ sheets for a project ordered newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(BoqSheet)
        .options(selectinload(BoqSheet.project), selectinload(BoqSheet.items))
        .where(BoqSheet.project_id == project.id)
        .order_by(BoqSheet.version.desc(), BoqSheet.created_at.desc())
    ).all()
    return BoqListResponse(
        sheets=[_to_boq_summary_out(r) for r in rows],
        total=len(rows),
        classification=project.classification,  # type: ignore[arg-type]
    )


def get_boq_detail(db: Session, boq_id: str) -> BoqDetailOut:
    """Fetch complete BOQ sheet with items, checks, and exports."""
    db.expire_all()
    sheet = db.scalar(
        select(BoqSheet)
        .options(
            selectinload(BoqSheet.project),
            selectinload(BoqSheet.items),
            selectinload(BoqSheet.deliverables),
        )
        .execution_options(populate_existing=True)
        .where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")
    return _to_boq_detail_out(sheet)


def _fetch_sheet_items(db: Session, boq_id: str) -> list[BoqItem]:
    """Query current BOQ items directly from DB, avoiding stale ORM relationship collections."""
    return list(
        db.scalars(
            select(BoqItem)
            .where(BoqItem.boq_sheet_id == boq_id)
            .order_by(BoqItem.row_order.asc())
        ).all()
    )


def update_boq_sheet(
    db: Session,
    boq_id: str,
    payload: BoqSheetUpdateRequest,
) -> BoqDetailOut:
    """Update BOQ metadata (currency, title, classification, language) cleanly."""
    sheet = db.scalar(
        select(BoqSheet)
        .options(selectinload(BoqSheet.items))
        .where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")
    if payload.title is not None:
        sheet.title = payload.title
    if payload.currency is not None:
        sheet.currency = payload.currency
    if payload.classification is not None:
        sheet.classification = payload.classification
    if payload.language is not None:
        sheet.language = payload.language

    checks = run_boq_checks_on_sheet(
        sheet,
        list(sheet.items or []),
        expected_coverage=_load_expected_coverage_for_sheet(db, sheet),
    )
    _persist_checks_snapshot(sheet, checks)
    db.commit()
    return get_boq_detail(db, boq_id)


def import_extractions_into_boq(
    db: Session,
    settings: Settings,
    boq_id: str,
    payload: BoqImportExtractionsRequest,
) -> BoqDetailOut:
    """Import/merge DXF/IFC deterministic takeoffs or XLSX/PDF existing BOQ tables into a BOQ sheet."""
    sheet = db.scalar(
        select(BoqSheet)
        .options(selectinload(BoqSheet.project), selectinload(BoqSheet.items))
        .where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")

    extracted_rows, expected_cov, used_files, skipped_notes, omission_summary = _gather_rows_from_files(
        db,
        settings,
        project=sheet.project,
        file_ids=payload.file_ids,
        include_dxf_ifc=payload.include_dxf_ifc,
        include_boq_imports=payload.include_boq_imports,
        is_ar=(sheet.language == "ar"),
    )

    if payload.replace_extracted:
        del_stmt = delete(BoqItem).where(
            BoqItem.boq_sheet_id == sheet.id,
            BoqItem.verification_status != "Manual",
        )
        if payload.file_ids:
            del_stmt = del_stmt.where(BoqItem.source_file_id.in_(payload.file_ids))
        db.execute(del_stmt)
        db.flush()
    remaining = _fetch_sheet_items(db, sheet.id)

    next_order = max((it.row_order for it in remaining), default=0) + 1
    for idx_r, row_data in enumerate(extracted_rows):
        item = BoqItem(boq_sheet_id=sheet.id, row_order=next_order + idx_r, **row_data)
        db.add(item)
    db.flush()
    new_items = _fetch_sheet_items(db, sheet.id)

    meta = dict(sheet.source_metadata_json or {})
    if payload.replace_extracted and not payload.file_ids:
        meta["expected_coverage"] = expected_cov
        meta["imported_file_ids"] = used_files
    else:
        prev_cov = {c["key"]: c for c in _load_expected_coverage_for_sheet(db, sheet) if "key" in c}
        if payload.replace_extracted and payload.file_ids:
            prefixes = tuple(f"{fid}:" for fid in payload.file_ids)
            prev_cov = {k: v for k, v in prev_cov.items() if not k.startswith(prefixes)}
        for c in expected_cov:
            prev_cov[c["key"]] = c
        meta["expected_coverage"] = list(prev_cov.values())
        meta["imported_file_ids"] = list(dict.fromkeys(list(meta.get("imported_file_ids") or []) + used_files))
    meta["skipped_notes"] = skipped_notes
    meta["omission_summary"] = omission_summary
    sheet.source_metadata_json = meta

    checks = run_boq_checks_on_sheet(
        sheet,
        new_items,
        expected_coverage=list(meta.get("expected_coverage") or []),
    )
    _persist_checks_snapshot(sheet, checks)
    db.commit()
    return get_boq_detail(db, boq_id)


def add_boq_item(
    db: Session,
    boq_id: str,
    payload: BoqItemCreateRequest,
) -> BoqDetailOut:
    """Add a manual BOQ line item (blocking unsourced unit rates and unconfirmed-unit pricing)."""
    sheet = db.scalar(
        select(BoqSheet).options(selectinload(BoqSheet.items)).where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")

    _verify_research_source_date_and_review(
        db,
        sheet.project_id,
        unit_rate=payload.unit_rate,
        rate_source_kind=payload.rate_source_kind,
        rate_source_ref=payload.rate_source_ref,
        rate_source_date=payload.rate_source_date,
    )
    canon_unit, unit_fam = normalize_boq_unit(payload.unit)
    computed_total = _compute_line_total(
        quantity=float(payload.quantity),
        unit_rate=payload.unit_rate,
        unit=canon_unit or payload.unit,
    )
    next_order = max((it.row_order for it in (sheet.items or [])), default=0) + 1
    item = BoqItem(
        boq_sheet_id=sheet.id,
        row_order=next_order,
        item_no=payload.item_no or f"MAN-{next_order:02d}",
        description=payload.description,
        unit=canon_unit if unit_fam != "missing" else payload.unit,
        quantity=round(float(payload.quantity), 4),
        unit_rate=round(float(payload.unit_rate), 4) if payload.unit_rate is not None else None,
        total=computed_total,
        reported_total=round(float(payload.reported_total), 4) if payload.reported_total is not None else None,
        technical_reference=payload.technical_reference,
        drawing_reference=payload.drawing_reference,
        remarks=payload.remarks,
        verification_status=payload.verification_status,
        rate_source_kind=payload.rate_source_kind if payload.unit_rate is not None else None,
        rate_source_ref=payload.rate_source_ref if payload.unit_rate is not None else None,
        rate_source_date=payload.rate_source_date if payload.unit_rate is not None else None,
        discipline=payload.discipline or "manual",
        layer_or_category=payload.layer_or_category,
    )
    db.add(item)
    db.flush()

    all_items = _fetch_sheet_items(db, sheet.id)
    checks = run_boq_checks_on_sheet(
        sheet,
        all_items,
        expected_coverage=_load_expected_coverage_for_sheet(db, sheet),
    )
    _persist_checks_snapshot(sheet, checks)
    db.commit()
    return get_boq_detail(db, boq_id)


def update_boq_item(
    db: Session,
    boq_id: str,
    item_id: str,
    payload: BoqItemUpdateRequest,
) -> BoqDetailOut:
    """Edit a BOQ item cleanly while enforcing sourced rates and recalculating totals in Python."""
    sheet = db.scalar(
        select(BoqSheet).options(selectinload(BoqSheet.items)).where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")
    item = next((it for it in (sheet.items or []) if it.id == item_id), None)
    if item is None:
        raise BoqNotFoundError(f"BOQ item '{item_id}' was not found in sheet '{boq_id}'.")

    if payload.item_no is not None:
        item.item_no = payload.item_no
    if payload.description is not None:
        item.description = payload.description
    if payload.unit is not None:
        canon_u, _ = normalize_boq_unit(payload.unit)
        item.unit = canon_u or payload.unit
    if payload.quantity is not None:
        item.quantity = round(float(payload.quantity), 4)
    if payload.reported_total is not None:
        item.reported_total = round(float(payload.reported_total), 4)
    if payload.technical_reference is not None:
        item.technical_reference = payload.technical_reference
    if payload.drawing_reference is not None:
        item.drawing_reference = payload.drawing_reference
    if payload.remarks is not None:
        item.remarks = payload.remarks
    if payload.verification_status is not None:
        item.verification_status = payload.verification_status
    if payload.discipline is not None:
        item.discipline = payload.discipline
    if payload.layer_or_category is not None:
        item.layer_or_category = payload.layer_or_category

    if payload.clear_rate:
        item.unit_rate = None
        item.total = None
        item.rate_source_kind = None
        item.rate_source_ref = None
        item.rate_source_date = None
    elif payload.unit_rate is not None:
        _verify_research_source_date_and_review(
            db,
            sheet.project_id,
            unit_rate=payload.unit_rate,
            rate_source_kind=payload.rate_source_kind,
            rate_source_ref=payload.rate_source_ref,
            rate_source_date=payload.rate_source_date,
        )
        new_total = _compute_line_total(
            quantity=float(item.quantity),
            unit_rate=float(payload.unit_rate),
            unit=item.unit,
        )
        item.unit_rate = round(float(payload.unit_rate), 4)
        item.total = new_total
        item.rate_source_kind = payload.rate_source_kind
        item.rate_source_ref = payload.rate_source_ref
        item.rate_source_date = payload.rate_source_date or datetime.now(timezone.utc).date().isoformat()
    elif item.unit_rate is not None and payload.quantity is not None:
        item.total = _compute_line_total(
            quantity=float(item.quantity),
            unit_rate=float(item.unit_rate),
            unit=item.unit,
        )

    db.flush()
    checks = run_boq_checks_on_sheet(
        sheet,
        _fetch_sheet_items(db, sheet.id),
        expected_coverage=_load_expected_coverage_for_sheet(db, sheet),
    )
    _persist_checks_snapshot(sheet, checks)
    db.commit()
    return get_boq_detail(db, boq_id)


def delete_boq_item(db: Session, boq_id: str, item_id: str) -> BoqDetailOut:
    """Remove a BOQ row and rerun deterministic checks."""
    sheet = db.scalar(
        select(BoqSheet).options(selectinload(BoqSheet.items)).where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")
    item = next((it for it in (sheet.items or []) if it.id == item_id), None)
    if item is None:
        raise BoqNotFoundError(f"BOQ item '{item_id}' was not found.")
    db.delete(item)
    db.flush()
    remaining = _fetch_sheet_items(db, sheet.id)

    checks = run_boq_checks_on_sheet(
        sheet,
        remaining,
        expected_coverage=_load_expected_coverage_for_sheet(db, sheet),
    )
    _persist_checks_snapshot(sheet, checks)
    db.commit()
    return get_boq_detail(db, boq_id)


def rerun_boq_checks(db: Session, boq_id: str) -> BoqDetailOut:
    """Re-run all deterministic BOQ checks (duplicates, missing items, units, arithmetic) and persist summary."""
    sheet = db.scalar(
        select(BoqSheet).options(selectinload(BoqSheet.items)).where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")
    checks = run_boq_checks_on_sheet(
        sheet,
        list(sheet.items or []),
        expected_coverage=_load_expected_coverage_for_sheet(db, sheet),
    )
    _persist_checks_snapshot(sheet, checks)
    db.commit()
    return get_boq_detail(db, boq_id)


def export_boq_deliverables(
    db: Session,
    settings: Settings,
    boq_id: str,
    payload: BoqExportRequest | None = None,
) -> BoqExportOut:
    """Export versioned XLSX (with live Excel formulas) and UTF-8 CSV into 06_BOQ as tracked deliverables."""
    opts = payload or BoqExportRequest()
    sheet = db.scalar(
        select(BoqSheet)
        .options(selectinload(BoqSheet.project), selectinload(BoqSheet.items))
        .where(BoqSheet.id == boq_id)
    )
    if sheet is None:
        raise BoqNotFoundError(f"BOQ sheet '{boq_id}' was not found.")

    items = _fetch_sheet_items(db, sheet.id)
    checks = run_boq_checks_on_sheet(
        sheet,
        items,
        expected_coverage=_load_expected_coverage_for_sheet(db, sheet),
    )
    _persist_checks_snapshot(sheet, checks)

    next_export_ver = int(sheet.export_version or 0) + 1
    sheet.export_version = next_export_ver
    sheet.status = "exported"
    export_lang = opts.language or ("en" if sheet.language == "en" else "ar")

    short_id = sheet.id.replace("-", "")[:8]
    title_slug = _safe_filename_slug(sheet.title, default="boq")
    rel_xlsx = f"06_BOQ/{title_slug}_{short_id}_v{next_export_ver}.xlsx"
    rel_csv = f"06_BOQ/{title_slug}_{short_id}_v{next_export_ver}.csv"

    path_xlsx = resolve_project_file_path(settings.workspaces_dir, sheet.project.workspace_slug, rel_xlsx)
    path_csv = resolve_project_file_path(settings.workspaces_dir, sheet.project.workspace_slug, rel_csv)
    if path_xlsx.exists() or path_csv.exists():
        raise FileExistsError(f"Refusing to overwrite existing BOQ export version v{next_export_ver} in 06_BOQ.")

    sheet_meta = sheet.source_metadata_json if isinstance(sheet.source_metadata_json, dict) else {}
    om_sum = sheet_meta.get("omission_summary") if isinstance(sheet_meta.get("omission_summary"), dict) else {}
    omission_note = str(om_sum.get("note")) if om_sum.get("omitted_count") else None

    row_dicts = [_to_item_out(it).model_dump() for it in items]
    generate_boq_xlsx(
        path_xlsx,
        title=sheet.title,
        project_code=sheet.project.code,
        project_name=sheet.project.name,
        classification=sheet.classification,
        currency=sheet.currency,
        revision=sheet.revision,
        export_version=next_export_ver,
        language=export_lang,
        items=row_dicts,
        checks=checks,
        include_checks_sheet=opts.include_checks_sheet,
        omission_note=omission_note,
    )
    generate_boq_csv(
        path_csv,
        currency=sheet.currency,
        items=row_dicts,
        checks=checks,
    )

    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    d_xlsx = Deliverable(
        project_id=sheet.project_id,
        task_id=sheet.task_id,
        boq_id=sheet.id,
        title=f"{sheet.title} (v{next_export_ver} XLSX — {sheet.currency})",
        deliverable_type="boq_schedule",
        discipline="quantity_surveying",
        format="xlsx",
        classification=sheet.classification,
        status="issued",
        version=next_export_ver,
        folder_name="06_BOQ",
        filename=path_xlsx.name,
        relative_path=rel_xlsx,
        mime_type=mime_xlsx,
        size_bytes=path_xlsx.stat().st_size,
        sha256=_sha256_file(path_xlsx),
        summary=f"BOQ XLSX export with live Excel formulas ({checks.total_items} items, {checks.grand_total} {sheet.currency}).",
    )
    d_csv = Deliverable(
        project_id=sheet.project_id,
        task_id=sheet.task_id,
        boq_id=sheet.id,
        title=f"{sheet.title} (v{next_export_ver} CSV — {sheet.currency})",
        deliverable_type="boq_schedule",
        discipline="quantity_surveying",
        format="csv",
        classification=sheet.classification,
        status="issued",
        version=next_export_ver,
        folder_name="06_BOQ",
        filename=path_csv.name,
        relative_path=rel_csv,
        mime_type="text/csv; charset=utf-8",
        size_bytes=path_csv.stat().st_size,
        sha256=_sha256_file(path_csv),
        summary=f"BOQ UTF-8 CSV export ({checks.total_items} items, {checks.grand_total} {sheet.currency}).",
    )
    db.add(d_xlsx)
    db.add(d_csv)
    db.add(
        AuditLog(
            project_id=sheet.project_id,
            action="boq.exported",
            entity_type="boq_sheet",
            entity_id=sheet.id,
            actor="boq_module",
            details_json={
                "export_version": next_export_ver,
                "currency": sheet.currency,
                "xlsx": rel_xlsx,
                "csv": rel_csv,
                "grand_total": checks.grand_total,
            },
        )
    )
    db.commit()
    detail = get_boq_detail(db, boq_id)
    xlsx_out = next(d for d in detail.deliverables if d.id == d_xlsx.id)
    csv_out = next(d for d in detail.deliverables if d.id == d_csv.id)
    return BoqExportOut(boq=detail, xlsx_deliverable=xlsx_out, csv_deliverable=csv_out)
