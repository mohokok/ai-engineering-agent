"""Step 12 independent QA Agent: isolated context builder (zero producer reasoning) and deterministic cross-deliverable verifiers."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.models import (
    BoqSheet,
    Calculation,
    Deliverable,
    FileExtraction,
    ParametricDrawing,
    Project,
    ProjectFile,
    ResearchSource,
    ReviewReport,
    Specification,
    Task,
)
from app.schemas.calculations import VERIFY_CODE_LABEL
from app.schemas.drawings import ParametricPlanModel
from app.schemas.qa import IssueCategory, IssueSeverity, QaCheckMetricOut, QaContextIsolationReport
from app.schemas.specifications import NO_VERIFIED_STANDARD_LABEL, SPEC_SECTION_PARTS
from app.services.parametric_cad import build_schedules_from_model, compute_room_metrics, sha256_file
from app.services.workspace import resolve_project_file_path
from app.skills.calculations import evaluate_calculation

PRODUCER_REASONING_EXCLUDED_FIELDS: tuple[str, ...] = (
    "Task.plan_summary",
    "Task.result_summary",
    "Task.structured_output_json",
    "TaskStep.notes",
    "TaskStep.output_payload.understanding",
    "ReviewReport.ai_reasoning",
)

_COUNT_UNIT_TOKENS = frozenset({"nos", "no", "no.", "pcs", "pc", "each", "ea", "unit", "units", "nr"})
_AREA_UNIT_TOKENS = frozenset({"m2", "m²", "sqm", "sq m", "sq_m"})
_VOLUME_UNIT_TOKENS = frozenset({"m3", "m³", "cum"})
_LENGTH_METRIC_TOKENS = frozenset({"m", "lm", "l.m", "rm"})
_SUBMETRIC_OR_IMPERIAL_TOKENS = frozenset({"cm", "mm", "in", "ft", "yd", "sq_in", "sq_ft", "sq in", "sq ft"})

_AREA_DESC_CUES = ("floor", "tiling", "tile", "paint", "plaster", "screed", "waterproofing", "finish", "slab", "ceiling", "area", "بلاط", "دهان", "تشطيب", "أرضيات", "مساحة")
_COUNT_DESC_CUES = ("door", "window", "luminaire", "socket", "breaker", "fan", "pump", "valve", "wc", "sink", "fixture", "باب", "أبواب", "نافذة", "نوافذ", "مضخة")
_DOOR_CUES = ("door", "doors", "باب", "أبواب")
_WINDOW_CUES = ("window", "windows", "نافذة", "نوافذ", "شباك", "شبابيك")
_FLOOR_TOTAL_CUES = ("total floor", "floor finish", "all rooms floor", "building floor", "ground floor", "مساحة الغرف", "تشطيب الأرضيات")
_URL_RE = re.compile(r"(?:https?://|project-file://)[^\s,;\"')>\]]+", re.IGNORECASE)
_STD_CODE_CITATION_RE = re.compile(r"\b(?:EXT|RES|SRC|CAD|IFC)-\d+\b", re.IGNORECASE)
_DRAWING_SHEET_REF_RE = re.compile(r"\b(?:[A-Z]{1,3}-\d{2,4}|DWG-[A-Z0-9_-]+)\b")


@dataclass(frozen=True)
class QaCandidateFinding:
    """Deterministic defect discovered by the independent QA evaluator."""

    check_category: IssueCategory
    discipline: str
    severity: IssueSeverity
    title: str
    description: str
    reference: str
    corrective_action: str
    deliverable_id: str | None = None
    task_id: str | None = None


@dataclass
class QaContextData:
    """Strictly isolated QA evidence snapshot containing raw deliverables and provenance logs only (zero producer reasoning)."""

    project_id: str
    project_code: str
    project_name: str
    task_id: str | None
    expected_task_deliverables: list[str]
    deliverables: list[dict[str, Any]] = field(default_factory=list)
    boq_sheets: list[dict[str, Any]] = field(default_factory=list)
    drawings: list[dict[str, Any]] = field(default_factory=list)
    review_reports: list[dict[str, Any]] = field(default_factory=list)
    calculations: list[dict[str, Any]] = field(default_factory=list)
    specifications: list[dict[str, Any]] = field(default_factory=list)
    extractions: list[dict[str, Any]] = field(default_factory=list)
    project_files: list[dict[str, Any]] = field(default_factory=list)
    reviewed_research_urls: set[str] = field(default_factory=set)
    unreviewed_research_urls: set[str] = field(default_factory=set)
    all_research_sources: list[dict[str, Any]] = field(default_factory=list)


def build_isolated_qa_context(
    db: Session,
    project: Project,
    *,
    task: Task | None = None,
) -> QaContextData:
    """Assemble an independent QA inspection bundle explicitly omitting producer plans, summaries, notes, and LLM chain-of-thought."""
    expected_delivs: list[str] = []
    if task is not None and isinstance(task.structured_output_json, dict):
        # Take ONLY expected deliverables labels; never read producer restated_assignment, assumptions, plan_summary, result_summary, or TaskStep.notes.
        expected_delivs = [
            str(x).strip()
            for x in (task.structured_output_json.get("expected_deliverables") or [])
            if str(x).strip()
        ]

    ctx = QaContextData(
        project_id=project.id,
        project_code=project.code,
        project_name=project.name,
        task_id=task.id if task is not None else None,
        expected_task_deliverables=expected_delivs,
    )

    deliverable_rows = db.scalars(
        select(Deliverable)
        .where(Deliverable.project_id == project.id)
        .order_by(Deliverable.created_at.desc())
    ).all()
    for d in deliverable_rows:
        if task is not None and d.task_id and d.task_id != task.id:
            continue
        ctx.deliverables.append(
            {
                "id": d.id,
                "task_id": d.task_id,
                "report_id": d.report_id,
                "boq_id": d.boq_id,
                "drawing_id": d.drawing_id,
                "calculation_id": d.calculation_id,
                "specification_id": d.specification_id,
                "title": d.title,
                "deliverable_type": d.deliverable_type,
                "discipline": d.discipline,
                "format": d.format,
                "classification": d.classification,
                "status": d.status,
                "version": d.version,
                "folder_name": d.folder_name,
                "filename": d.filename,
                "relative_path": d.relative_path,
                "sha256": d.sha256,
            }
        )

    boq_rows = db.scalars(
        select(BoqSheet)
        .options(selectinload(BoqSheet.items))
        .where(BoqSheet.project_id == project.id)
        .order_by(BoqSheet.created_at.desc())
    ).all()
    for b in boq_rows:
        if task is not None and b.task_id and b.task_id != task.id:
            continue
        ctx.boq_sheets.append(
            {
                "id": b.id,
                "task_id": b.task_id,
                "title": b.title,
                "currency": b.currency,
                "revision": b.revision,
                "status": b.status,
                "export_version": b.export_version,
                "items": [
                    {
                        "id": it.id,
                        "row_order": it.row_order,
                        "item_no": it.item_no,
                        "description": it.description,
                        "unit": it.unit,
                        "quantity": it.quantity,
                        "unit_rate": it.unit_rate,
                        "total": it.total,
                        "reported_total": it.reported_total,
                        "technical_reference": it.technical_reference,
                        "drawing_reference": it.drawing_reference,
                        "verification_status": it.verification_status,
                        "rate_source_kind": it.rate_source_kind,
                        "rate_source_ref": it.rate_source_ref,
                        "rate_source_date": it.rate_source_date,
                        "discipline": it.discipline,
                        "layer_or_category": it.layer_or_category,
                        "source_file_id": it.source_file_id,
                    }
                    for it in b.items
                ],
            }
        )

    dwg_rows = db.scalars(
        select(ParametricDrawing)
        .where(ParametricDrawing.project_id == project.id)
        .order_by(ParametricDrawing.created_at.desc())
    ).all()
    for dr in dwg_rows:
        if task is not None and dr.task_id and dr.task_id != task.id:
            continue
        ctx.drawings.append(
            {
                "id": dr.id,
                "task_id": dr.task_id,
                "drawing_no": dr.drawing_no,
                "title": dr.title,
                "units": dr.units,
                "scale_denominator": dr.scale_denominator,
                "revision": dr.revision,
                "round_trip_passed": dr.round_trip_passed,
                "model_json": dr.model_json if isinstance(dr.model_json, dict) else {},
                "computed_metrics_json": (
                    dr.computed_metrics_json if isinstance(dr.computed_metrics_json, dict) else {}
                ),
            }
        )

    report_rows = db.scalars(
        select(ReviewReport)
        .where(ReviewReport.project_id == project.id)
        .order_by(ReviewReport.created_at.desc())
    ).all()
    for rep in report_rows:
        if task is not None and rep.task_id and rep.task_id != task.id:
            continue
        raw_payload = rep.structured_payload_json if isinstance(rep.structured_payload_json, dict) else {}
        # Deliberately omit rep.summary & narrative AI prose; inspect ONLY objective findings, facts, calculations, and source_registry.
        ctx.review_reports.append(
            {
                "id": rep.id,
                "task_id": rep.task_id,
                "title": rep.title,
                "discipline": rep.discipline,
                "revision": rep.revision,
                "document_register": list(raw_payload.get("document_register") or []),
                "findings": list(raw_payload.get("findings") or []),
                "verified_facts": list(raw_payload.get("verified_facts") or []),
                "calculated_items": list(raw_payload.get("calculated_items") or []),
                "source_registry": list(raw_payload.get("source_registry") or []),
            }
        )

    calc_rows = db.scalars(
        select(Calculation)
        .where(Calculation.project_id == project.id)
        .order_by(Calculation.created_at.desc())
    ).all()
    for c_row in calc_rows:
        if task is not None and c_row.task_id and c_row.task_id != task.id:
            continue
        ctx.calculations.append(
            {
                "id": c_row.id,
                "task_id": c_row.task_id,
                "title": c_row.title,
                "discipline": c_row.discipline,
                "calculation_type": c_row.calculation_type,
                "inputs_json": dict(c_row.inputs_json or {}),
                "units_json": dict(c_row.units_json or {}),
                "equations": c_row.equations or "",
                "methodology": c_row.methodology or "",
                "assumptions": c_row.assumptions or "",
                "results_json": dict(c_row.results_json or {}),
                "acceptance_criteria": c_row.acceptance_criteria or "",
                "references_text": c_row.references_text or "",
                "references_json": list(c_row.references_json or []),
                "revision": c_row.revision,
                "version": c_row.version,
                "export_version": c_row.export_version,
                "acceptance_passed": bool(c_row.acceptance_passed),
            }
        )

    spec_rows = db.scalars(
        select(Specification)
        .where(Specification.project_id == project.id)
        .order_by(Specification.created_at.desc())
    ).all()
    for sp in spec_rows:
        if task is not None and sp.task_id and sp.task_id != task.id:
            continue
        sp_payload = sp.structured_payload_json if isinstance(sp.structured_payload_json, dict) else {}
        ctx.specifications.append(
            {
                "id": sp.id,
                "task_id": sp.task_id,
                "title": sp.title,
                "discipline": sp.discipline,
                "language": sp.language,
                "revision": sp.revision,
                "version": sp.version,
                "export_version": sp.export_version,
                "status": sp.status,
                "use_ai": bool(sp.use_ai),
                "ai_draft_status": sp.ai_draft_status,
                "source_boq_sheet_ids": list(sp_payload.get("source_boq_sheet_ids") or []),
                "source_drawing_ids": list(sp_payload.get("source_drawing_ids") or []),
                "source_research_ids": list(sp_payload.get("source_research_ids") or []),
                "sections": list(sp_payload.get("sections") or []),
            }
        )

    files = db.scalars(select(ProjectFile).where(ProjectFile.project_id == project.id)).all()
    file_name_by_id = {f.id: f.original_filename for f in files}
    for f in files:
        ctx.project_files.append(
            {
                "id": f.id,
                "original_filename": f.original_filename,
                "current_version": f.current_version,
                "extension": f.extension,
            }
        )

    exts = db.scalars(
        select(FileExtraction)
        .where(FileExtraction.project_id == project.id)
        .order_by(FileExtraction.created_at.desc())
    ).all()
    seen_ext_file_ids: set[str] = set()
    for ext in exts:
        if ext.file_id in seen_ext_file_ids:
            continue
        seen_ext_file_ids.add(ext.file_id)
        pjson = ext.payload_json if isinstance(ext.payload_json, dict) else {}
        ctx.extractions.append(
            {
                "id": ext.id,
                "file_id": ext.file_id,
                "filename": file_name_by_id.get(ext.file_id) or pjson.get("source_file") or "",
                "file_type": pjson.get("file_type"),
                "status": ext.status,
                "unit_context": pjson.get("unit_context") if isinstance(pjson.get("unit_context"), dict) else {},
                "counts": ext.counts_json if isinstance(ext.counts_json, dict) else {},
                "drawing_inventory": (
                    pjson.get("drawing_inventory") if isinstance(pjson.get("drawing_inventory"), dict) else {}
                ),
            }
        )

    r_sources = db.scalars(
        select(ResearchSource).where(ResearchSource.project_id == project.id)
    ).all()
    for rs in r_sources:
        ctx.all_research_sources.append(
            {
                "id": rs.id,
                "url": rs.url,
                "source_name": rs.source_name,
                "reviewed": bool(rs.reviewed),
                "access_status": rs.access_status,
                "reliability_assessment": rs.reliability_assessment,
            }
        )
        if rs.reviewed and rs.access_status in ("accessible", "owner_provided"):
            ctx.reviewed_research_urls.add(rs.url)
        else:
            ctx.unreviewed_research_urls.add(rs.url)

    return ctx


def count_inspected_artefacts(ctx: QaContextData) -> int:
    """Return total concrete deliverables, BOQ sheets, drawings, calculations, specifications, and reports available for QA inspection."""
    return (
        len(ctx.boq_sheets)
        + len(ctx.drawings)
        + len(ctx.review_reports)
        + len(ctx.calculations)
        + len(ctx.specifications)
        + len(ctx.deliverables)
    )


def _expected_deliverable_covered(exp: str, ctx: QaContextData) -> bool:
    """Return True when a non-BOQ/drawing/report expected deliverable matches at least one inspected artefact."""
    haystacks = [
        f"{d.get('title', '')} {d.get('deliverable_type', '')} {d.get('filename', '')} {d.get('folder_name', '')}".lower()
        for d in ctx.deliverables
    ]
    haystacks.extend(f"{b.get('title', '')} boq bill of quantities".lower() for b in ctx.boq_sheets)
    haystacks.extend(f"{dr.get('title', '')} {dr.get('drawing_no', '')} drawing plan cad".lower() for dr in ctx.drawings)
    haystacks.extend(f"{rp.get('title', '')} {rp.get('discipline', '')} report review".lower() for rp in ctx.review_reports)
    haystacks.extend(
        f"{c.get('title', '')} {c.get('discipline', '')} {c.get('calculation_type', '')} calculation".lower()
        for c in ctx.calculations
    )
    haystacks.extend(
        f"{s.get('title', '')} {s.get('discipline', '')} specification specifications".lower()
        for s in ctx.specifications
    )
    if not haystacks:
        return False

    tokens = re.findall(r"[\w\u0600-\u06FF]{3,}", exp.lower())
    stop = {"and", "the", "for", "with", "from", "into"}
    generic = {"sheet", "document", "schedule", "list", "draft", "output", "file", "deliverable", "memo", "package"}
    informative = [t for t in tokens if t not in stop]
    specific = [t for t in informative if t not in generic]
    target_tokens = specific or informative
    if not target_tokens:
        return bool(ctx.deliverables)
    return any(any(tok in hay for tok in target_tokens) for hay in haystacks)


def build_qa_context_isolation_report(ctx: QaContextData) -> QaContextIsolationReport:
    """Build serializable QA context audit showing exact inspected artifacts and zero producer reasoning exposure."""
    return QaContextIsolationReport(
        producer_reasoning_excluded=True,
        excluded_fields=list(PRODUCER_REASONING_EXCLUDED_FIELDS),
        inspected_boq_ids=[b["id"] for b in ctx.boq_sheets],
        inspected_drawing_ids=[d["id"] for d in ctx.drawings],
        inspected_report_ids=[r["id"] for r in ctx.review_reports],
        inspected_calculation_ids=[c["id"] for c in ctx.calculations],
        inspected_specification_ids=[s["id"] for s in ctx.specifications],
        inspected_deliverable_ids=[d["id"] for d in ctx.deliverables],
        inspected_extraction_ids=[e["id"] for e in ctx.extractions],
        inspected_research_source_count=len(ctx.all_research_sources),
        expected_task_deliverables=list(ctx.expected_task_deliverables),
    )


def serialize_isolated_qa_prompt_context(ctx: QaContextData) -> str:
    """Serialize isolated QA inspection payload as standalone JSON without any producer reasoning."""
    payload = {
        "project_code": ctx.project_code,
        "project_name": ctx.project_name,
        "task_id": ctx.task_id,
        "expected_task_deliverables": ctx.expected_task_deliverables,
        "boq_sheets": [
            {
                "id": b["id"],
                "title": b["title"],
                "currency": b["currency"],
                "items_count": len(b["items"]),
                "items": b["items"],
            }
            for b in ctx.boq_sheets
        ],
        "drawings": [
            {
                "id": d["id"],
                "drawing_no": d["drawing_no"],
                "units": d["units"],
                "rooms": (d["computed_metrics_json"] or {}).get("rooms", []),
                "total_area_m2": (d["computed_metrics_json"] or {}).get("total_area_m2"),
                "door_schedule": (d["computed_metrics_json"] or {}).get("door_schedule", []),
                "window_schedule": (d["computed_metrics_json"] or {}).get("window_schedule", []),
            }
            for d in ctx.drawings
        ],
        "calculations": [
            {
                "id": c["id"],
                "title": c["title"],
                "discipline": c["discipline"],
                "calculation_type": c["calculation_type"],
                "inputs": c["inputs_json"],
                "units": c["units_json"],
                "results": c["results_json"],
                "acceptance_passed": c["acceptance_passed"],
                "references": c["references_json"],
            }
            for c in ctx.calculations
        ],
        "specifications": [
            {
                "id": s["id"],
                "title": s["title"],
                "discipline": s["discipline"],
                "ai_draft_status": s["ai_draft_status"],
                "sections_count": len(s.get("sections") or []),
            }
            for s in ctx.specifications
        ],
        "deliverables": ctx.deliverables,
        "reviewed_research_urls": sorted(ctx.reviewed_research_urls),
    }
    return json.dumps(payload, ensure_ascii=False)


def _to_decimal(val: Any) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return None


def _round4(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _classify_unit_family(unit: str) -> str:
    norm = " ".join((unit or "").strip().lower().split())
    if not norm:
        return "missing"
    if any(tok in norm for tok in ("unconfirmed", "doubtful", "unknown", "unitless", "??")):
        return "unconfirmed"
    if norm in _COUNT_UNIT_TOKENS:
        return "count"
    if norm in _AREA_UNIT_TOKENS:
        return "area_metric"
    if norm in _VOLUME_UNIT_TOKENS:
        return "volume_metric"
    if norm in _LENGTH_METRIC_TOKENS:
        return "length_metric"
    if norm in _SUBMETRIC_OR_IMPERIAL_TOKENS or norm.startswith("unconfirmed "):
        return "non_standard_or_mixed"
    return "other"


def _check_arithmetic(
    ctx: QaContextData,
    settings: Settings,
    workspace_slug: str,
) -> tuple[QaCheckMetricOut, list[QaCandidateFinding]]:
    checked = 0
    findings: list[QaCandidateFinding] = []
    deliv_by_boq = {d["boq_id"]: d["id"] for d in ctx.deliverables if d.get("boq_id")}

    for boq in ctx.boq_sheets:
        boq_deliv_id = deliv_by_boq.get(boq["id"])
        for it in boq["items"]:
            checked += 1
            qty = _to_decimal(it.get("quantity"))
            rate = _to_decimal(it.get("unit_rate"))
            stored_total = _to_decimal(it.get("total"))
            reported_total = _to_decimal(it.get("reported_total"))
            ref = f"BOQ {boq['title']} / Item {it.get('item_no') or it.get('row_order')}"

            if qty is not None and qty < 0:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=it.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Negative quantity in BOQ",
                        description=f"BOQ item '{it.get('item_no')}' has negative quantity ({qty}).",
                        reference=ref,
                        corrective_action="Correct negative BOQ quantity to a verified non-negative measurement.",
                        deliverable_id=boq_deliv_id,
                        task_id=boq.get("task_id"),
                    )
                )
            if rate is not None and rate < 0:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=it.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Negative unit rate in BOQ",
                        description=f"BOQ item '{it.get('item_no')}' has negative unit rate ({rate}).",
                        reference=ref,
                        corrective_action="Correct unit rate to a positive sourced rate.",
                        deliverable_id=boq_deliv_id,
                        task_id=boq.get("task_id"),
                    )
                )

            if qty is not None and rate is not None:
                expected = _round4(qty * rate)
                if stored_total is None or abs(stored_total - expected) > Decimal("0.01"):
                    findings.append(
                        QaCandidateFinding(
                            check_category="arithmetic",
                            discipline=it.get("discipline") or "quantity_surveying",
                            severity="high",
                            title="BOQ line total arithmetic mismatch",
                            description=(
                                f"Arithmetic mismatch on BOQ item '{it.get('item_no')}' ({it.get('description', '')[:80]}): "
                                f"recomputed {qty} * {rate} = {expected} {boq['currency']}, stored total = {stored_total}."
                            ),
                            reference=ref,
                            corrective_action=f"Recompute and set item total strictly to {expected} {boq['currency']}.",
                            deliverable_id=boq_deliv_id,
                            task_id=boq.get("task_id"),
                        )
                    )
                if reported_total is not None and abs(reported_total - expected) > Decimal("0.01"):
                    findings.append(
                        QaCandidateFinding(
                            check_category="arithmetic",
                            discipline=it.get("discipline") or "quantity_surveying",
                            severity="high",
                            title="Imported BOQ reported total mismatch",
                            description=(
                                f"Imported BOQ item '{it.get('item_no')}' reported_total={reported_total} disagrees with "
                                f"code-recomputed {qty} * {rate} = {expected}."
                            ),
                            reference=ref,
                            corrective_action="Reconcile imported spreadsheet/PDF arithmetic against quantity x rate.",
                            deliverable_id=boq_deliv_id,
                            task_id=boq.get("task_id"),
                        )
                    )
            elif rate is None and stored_total is not None and abs(stored_total) > Decimal("0.01"):
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=it.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Total present without unit rate",
                        description=(
                            f"BOQ item '{it.get('item_no')}' stores non-zero total ({stored_total}) while unit_rate is None."
                        ),
                        reference=ref,
                        corrective_action="Remove fabricated total or supply an attributable unit rate.",
                        deliverable_id=boq_deliv_id,
                        task_id=boq.get("task_id"),
                    )
                )

    # Check exported XLSX files on disk verify formulas vs hardcoded static totals
    for d in ctx.deliverables:
        if str(d.get("format") or "").lower() == "xlsx":
            checked += 1
            rel_xlsx = d.get("relative_path")
            try:
                if not rel_xlsx:
                    raise FileNotFoundError("Deliverable has no workspace relative_path for XLSX inspection.")
                fpath = resolve_project_file_path(settings.workspaces_dir, workspace_slug, rel_xlsx)
                if not fpath.is_file():
                    raise FileNotFoundError(f"Exported XLSX '{rel_xlsx}' does not exist on disk.")
                wb = load_workbook(str(fpath), data_only=False)
                try:
                    ws = wb.active
                    if ws is None:
                        raise ValueError(f"Exported XLSX '{rel_xlsx}' has no active worksheet.")
                    if not d.get("calculation_id"):
                        for row_idx in range(6, ws.max_row + 1):
                            qty_cell = ws.cell(row=row_idx, column=4).value
                            rate_cell = ws.cell(row=row_idx, column=5).value
                            tot_cell = ws.cell(row=row_idx, column=6).value
                            item_no_cell = ws.cell(row=row_idx, column=1).value
                            if item_no_cell and qty_cell is not None and rate_cell is not None:
                                if not (isinstance(tot_cell, str) and tot_cell.startswith("=")):
                                    q_d = _to_decimal(qty_cell)
                                    r_d = _to_decimal(rate_cell)
                                    t_d = _to_decimal(tot_cell)
                                    if q_d is not None and r_d is not None and t_d is not None:
                                        exp = _round4(q_d * r_d)
                                        if abs(t_d - exp) > Decimal("0.01"):
                                            findings.append(
                                                QaCandidateFinding(
                                                    check_category="arithmetic",
                                                    discipline="quantity_surveying",
                                                    severity="high",
                                                    title="Exported XLSX hardcoded total mismatch",
                                                    description=(
                                                        f"XLSX row {row_idx} ({item_no_cell}) contains non-formula total {t_d} "
                                                        f"instead of expected {exp}."
                                                    ),
                                                    reference=str(rel_xlsx),
                                                    corrective_action="Re-export BOQ XLSX with live Excel formulas.",
                                                    deliverable_id=d["id"],
                                                    task_id=d.get("task_id"),
                                                )
                                            )
                finally:
                    wb.close()
            except Exception as exc:
                findings.append(
                    QaCandidateFinding(
                        check_category="integrity",
                        discipline=d.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Exported XLSX unreadable or missing",
                        description=(
                            f"Exported XLSX '{rel_xlsx or d.get('title')}' failed workbook read during arithmetic QA "
                            f"({type(exc).__name__}: {exc})."
                        ),
                        reference=str(rel_xlsx or f"Deliverable {d['id'][:8]}"),
                        corrective_action="Restore or re-export a readable valid XLSX workbook into 06_BOQ.",
                        deliverable_id=d["id"],
                        task_id=d.get("task_id"),
                    )
                )

    # Recompute parametric drawing Shoelace areas strictly from model_json coordinates
    deliv_by_dwg = {d["drawing_id"]: d["id"] for d in ctx.deliverables if d.get("drawing_id")}
    for dwg in ctx.drawings:
        checked += 1
        dwg_deliv_id = deliv_by_dwg.get(dwg["id"])
        try:
            plan = ParametricPlanModel.model_validate(dwg["model_json"])
            recomputed_rooms = compute_room_metrics(plan.rooms)
            expected_total = round(sum(r.area_m2 for r in recomputed_rooms), 4)
            stored_total = float((dwg["computed_metrics_json"] or {}).get("total_area_m2") or 0.0)
            if abs(expected_total - stored_total) > 0.01:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline="architecture",
                        severity="high",
                        title="Parametric drawing room area total mismatch",
                        description=(
                            f"Drawing {dwg['drawing_no']} stores total_area_m2={stored_total:.2f}, "
                            f"whereas independent Shoelace recomputation yields {expected_total:.2f} m2."
                        ),
                        reference=f"Drawing {dwg['drawing_no']} ({dwg['id'][:8]})",
                        corrective_action="Regenerate parametric drawing metrics cleanly from coordinates.",
                        deliverable_id=dwg_deliv_id,
                        task_id=dwg.get("task_id"),
                    )
                )
        except Exception as exc:
            findings.append(
                QaCandidateFinding(
                    check_category="arithmetic",
                    discipline="architecture",
                    severity="high",
                    title="Invalid parametric drawing coordinate model",
                    description=f"Drawing {dwg['drawing_no']} coordinate model failed QA geometry check: {exc}",
                    reference=f"Drawing {dwg['drawing_no']}",
                    corrective_action="Fix room/wall geometry JSON and regenerate DXF + PDF.",
                    deliverable_id=dwg_deliv_id,
                    task_id=dwg.get("task_id"),
                )
            )

    # Recompute Step 13 engineering calculations strictly from inputs_json
    deliv_by_calc = {d["calculation_id"]: d["id"] for d in ctx.deliverables if d.get("calculation_id")}
    for calc in ctx.calculations:
        checked += 1
        calc_deliv_id = deliv_by_calc.get(calc["id"])
        ref = f"Calculation {calc['title']} ({calc['id'][:8]})"
        try:
            ev = evaluate_calculation(calc["calculation_type"], calc.get("inputs_json") or {})
            stored_res = calc.get("results_json") or {}
            mismatches: list[str] = []
            for key, exp_val in ev.results.items():
                if isinstance(exp_val, bool):
                    if bool(stored_res.get(key)) != exp_val:
                        mismatches.append(f"{key}: stored={stored_res.get(key)}, expected={exp_val}")
                elif isinstance(exp_val, (int, float)):
                    stored_num = _to_decimal(stored_res.get(key))
                    exp_num = _to_decimal(exp_val)
                    if stored_num is None or exp_num is None or abs(stored_num - exp_num) > Decimal("0.01"):
                        mismatches.append(f"{key}: stored={stored_res.get(key)}, expected={exp_val}")
                elif key in ("data_provenance", "acceptance_outcome_label"):
                    if str(stored_res.get(key) or "") != str(exp_val or ""):
                        mismatches.append(f"{key}: stored={stored_res.get(key)}, expected={exp_val}")
                elif exp_val is None and key in ("outer_diameter_mm", "wall_thickness_mm"):
                    if stored_res.get(key) is not None:
                        mismatches.append(f"{key}: stored={stored_res.get(key)}, expected=None")
            if mismatches:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=calc.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Engineering calculation result mismatch",
                        description=(
                            f"Calculation '{calc['title']}' ({calc['calculation_type']}) stored results disagree with "
                            f"independent Python recomputation: {'; '.join(mismatches[:5])}."
                        ),
                        reference=ref,
                        corrective_action="Re-run deterministic calculation via PATCH /api/calculations/{id} to restore code-computed outputs.",
                        deliverable_id=calc_deliv_id,
                        task_id=calc.get("task_id"),
                    )
                )
        except Exception as exc:
            findings.append(
                QaCandidateFinding(
                    check_category="arithmetic",
                    discipline=calc.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Engineering calculation failed deterministic re-evaluation",
                    description=f"Calculation '{calc['title']}' failed QA recomputation: {exc}",
                    reference=ref,
                    corrective_action="Fix invalid calculation inputs or type and recompute.",
                    deliverable_id=calc_deliv_id,
                    task_id=calc.get("task_id"),
                )
            )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="arithmetic",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Recomputed {checked} BOQ/XLSX/drawing/calculation arithmetic target(s); found {failed_cnt} issue(s).",
        ),
        findings,
    )


def _check_units(ctx: QaContextData) -> tuple[QaCheckMetricOut, list[QaCandidateFinding]]:
    checked = 0
    findings: list[QaCandidateFinding] = []
    deliv_by_boq = {d["boq_id"]: d["id"] for d in ctx.deliverables if d.get("boq_id")}

    for boq in ctx.boq_sheets:
        boq_deliv_id = deliv_by_boq.get(boq["id"])
        length_families: set[str] = set()
        for it in boq["items"]:
            checked += 1
            unit = str(it.get("unit") or "").strip()
            qty = float(it.get("quantity") or 0.0)
            desc_lower = str(it.get("description") or "").lower()
            ref = f"BOQ {boq['title']} / Item {it.get('item_no') or it.get('row_order')}"
            fam = _classify_unit_family(unit)

            if fam == "missing" and abs(qty) > 0:
                findings.append(
                    QaCandidateFinding(
                        check_category="unit",
                        discipline=it.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Missing measurement unit on BOQ item",
                        description=f"BOQ item '{it.get('item_no')}' has quantity {qty} with blank unit.",
                        reference=ref,
                        corrective_action="Assign verified unit (m2, m, nos, m3, etc.) from source document.",
                        deliverable_id=boq_deliv_id,
                        task_id=boq.get("task_id"),
                    )
                )
            elif fam == "unconfirmed":
                findings.append(
                    QaCandidateFinding(
                        check_category="unit",
                        discipline=it.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Unconfirmed CAD drawing unit propagated into BOQ",
                        description=f"BOQ item '{it.get('item_no')}' uses unconfirmed/doubtful unit '{unit}'.",
                        reference=ref,
                        corrective_action="Confirm drawing units via /api/extractions/{id}/confirm-unit and re-import BOQ.",
                        deliverable_id=boq_deliv_id,
                        task_id=boq.get("task_id"),
                    )
                )

            if fam in ("length_metric", "non_standard_or_mixed"):
                length_families.add("metric" if fam == "length_metric" else unit.lower())

            # Detect clearly wrong unit for item category (e.g. door quantified in m2/m3 or flooring in nos/kg)
            if any(c in desc_lower for c in _COUNT_DESC_CUES) and fam in ("area_metric", "volume_metric"):
                findings.append(
                    QaCandidateFinding(
                        check_category="unit",
                        discipline=it.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Incompatible unit for countable fixture/opening",
                        description=(
                            f"BOQ item '{it.get('item_no')}' ('{it.get('description', '')[:70]}') uses '{unit}' "
                            "instead of a count unit such as 'nos'."
                        ),
                        reference=ref,
                        corrective_action="Change unit to 'nos' and verify quantity against opening schedule.",
                        deliverable_id=boq_deliv_id,
                        task_id=boq.get("task_id"),
                    )
                )
            elif any(c in desc_lower for c in _AREA_DESC_CUES) and fam in ("count",):
                findings.append(
                    QaCandidateFinding(
                        check_category="unit",
                        discipline=it.get("discipline") or "quantity_surveying",
                        severity="high",
                        title="Incompatible count unit on surface/finish item",
                        description=(
                            f"BOQ item '{it.get('item_no')}' ('{it.get('description', '')[:70]}') uses count unit '{unit}' "
                            "on a surface-area description."
                        ),
                        reference=ref,
                        corrective_action="Verify unit as 'm2' and recompute net area.",
                        deliverable_id=boq_deliv_id,
                        task_id=boq.get("task_id"),
                    )
                )

        if len(length_families) > 1 or any(lf != "metric" for lf in length_families):
            findings.append(
                QaCandidateFinding(
                    check_category="unit",
                    discipline="quantity_surveying",
                    severity="high",
                    title="Mixed or non-standard linear/submetric units in BOQ",
                    description=(
                        f"BOQ sheet '{boq['title']}' mixes or uses non-metric linear/area units: "
                        f"{', '.join(sorted(length_families))}."
                    ),
                    reference=f"BOQ {boq['title']}",
                    corrective_action="Standardize BOQ quantities strictly to consistent metric 'm' / 'm2'.",
                    deliverable_id=boq_deliv_id,
                    task_id=boq.get("task_id"),
                )
            )

    for ext in ctx.extractions:
        if ext.get("file_type") in {"dxf", "dwg"}:
            checked += 1
            uc = ext.get("unit_context") or {}
            if uc.get("is_doubtful") and not uc.get("owner_confirmed_unit"):
                findings.append(
                    QaCandidateFinding(
                        check_category="unit",
                        discipline="cad_bim",
                        severity="high",
                        title="CAD drawing unit unconfirmed",
                        description=f"CAD file '{ext.get('filename')}' has doubtful/unconfirmed units ({uc.get('declared_label', 'unknown')}).",
                        reference=f"File {ext.get('filename')}",
                        corrective_action="Owner must explicitly confirm drawing units before relying on metric quantities.",
                        task_id=ctx.task_id,
                    )
                )

    for dwg in ctx.drawings:
        checked += 1
        if str(dwg.get("units") or "").lower() != "mm":
            findings.append(
                QaCandidateFinding(
                    check_category="unit",
                    discipline="architecture",
                    severity="high",
                    title="Parametric drawing not in millimetres",
                    description=f"Drawing {dwg['drawing_no']} uses '{dwg.get('units')}' instead of strict 'mm' ($INSUNITS=4).",
                    reference=f"Drawing {dwg['drawing_no']}",
                    corrective_action="Enforce millimetres (mm) on parametric drawing coordinates.",
                    task_id=dwg.get("task_id"),
                )
            )

    deliv_by_calc = {d["calculation_id"]: d["id"] for d in ctx.deliverables if d.get("calculation_id")}
    for calc in ctx.calculations:
        checked += 1
        units_map = calc.get("units_json") or {}
        ref = f"Calculation {calc['title']} ({calc['id'][:8]})"
        calc_deliv_id = deliv_by_calc.get(calc["id"])
        if not units_map:
            findings.append(
                QaCandidateFinding(
                    check_category="unit",
                    discipline=calc.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Engineering calculation missing units map",
                    description=f"Calculation '{calc['title']}' does not declare units_json for inputs/results.",
                    reference=ref,
                    corrective_action="Recompute calculation so explicit SI/engineering units are persisted.",
                    deliverable_id=calc_deliv_id,
                    task_id=calc.get("task_id"),
                )
            )
        else:
            bad_units = [
                f"{k}={v}"
                for k, v in units_map.items()
                if not str(v).strip()
                or any(tok in str(v).lower() for tok in ("unconfirmed", "unknown", "ft", "in", "psi", "??"))
            ]
            if bad_units:
                findings.append(
                    QaCandidateFinding(
                        check_category="unit",
                        discipline=calc.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Invalid or unconfirmed unit in calculation",
                        description=f"Calculation '{calc['title']}' declares non-standard/unconfirmed unit(s): {', '.join(bad_units)}.",
                        reference=ref,
                        corrective_action="Standardize calculation units strictly to confirmed SI/engineering units.",
                        deliverable_id=calc_deliv_id,
                        task_id=calc.get("task_id"),
                    )
                )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="unit",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Checked {checked} BOQ/drawing/CAD/calculation units; found {failed_cnt} unit issue(s).",
        ),
        findings,
    )


def _check_references(ctx: QaContextData) -> tuple[QaCheckMetricOut, list[QaCandidateFinding]]:
    checked = 0
    findings: list[QaCandidateFinding] = []
    deliv_by_boq = {d["boq_id"]: d["id"] for d in ctx.deliverables if d.get("boq_id")}
    deliv_by_rep = {
        d["report_id"]: d["id"]
        for d in ctx.deliverables
        if d.get("report_id") and d.get("folder_name") == "10_Final_Deliverables"
    }

    valid_filenames = {str(f["original_filename"]).strip().lower() for f in ctx.project_files if f.get("original_filename")}
    valid_file_ids = {str(f["id"]) for f in ctx.project_files}
    valid_drawing_nos = {str(d["drawing_no"]).strip().upper() for d in ctx.drawings if d.get("drawing_no")}
    for ext in ctx.extractions:
        if ext.get("filename"):
            valid_filenames.add(str(ext["filename"]).strip().lower())

    def _url_is_reviewed(candidate_url: str) -> bool:
        if candidate_url in ctx.reviewed_research_urls:
            return True
        if candidate_url.startswith("project-file://"):
            rest = candidate_url[len("project-file://") :].split("/", 1)[0]
            return rest in valid_file_ids or candidate_url in ctx.reviewed_research_urls
        return False

    # 1. Check ReviewReports source_ref_ids & URL citations against Source Log & FileExtractions
    for rep in ctx.review_reports:
        rep_deliv_id = deliv_by_rep.get(rep["id"])
        src_reg = {
            str(entry.get("ref_id")): entry
            for entry in (rep.get("source_registry") or [])
            if isinstance(entry, dict) and entry.get("ref_id")
        }

        for ref_id, entry in src_reg.items():
            checked += 1
            src_url = str(entry.get("url") or "").strip()
            src_file = str(entry.get("source_file") or "").strip().lower()
            if src_url:
                if not _url_is_reviewed(src_url):
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=rep.get("discipline") or "multidisciplinary",
                            severity="critical",
                            title="Report source_registry cites unreviewed or nonexistent URL",
                            description=(
                                f"Review Report '{rep['title']}' entry '{ref_id}' points to URL '{src_url}' "
                                "which is absent from reviewed project Research Sources."
                            ),
                            reference=f"Report {rep['revision']} / {ref_id}",
                            corrective_action="Replace with a reviewed source URL/file or mark finding unverified.",
                            deliverable_id=rep_deliv_id,
                            task_id=rep.get("task_id"),
                        )
                    )
            elif ref_id.upper().startswith("EXT-") and src_file and src_file not in valid_filenames:
                findings.append(
                    QaCandidateFinding(
                        check_category="reference",
                        discipline=rep.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Report references missing project file",
                        description=f"Review Report '{rep['title']}' source '{ref_id}' names unknown file '{entry.get('source_file')}'.",
                        reference=f"Report {rep['revision']} / {ref_id}",
                        corrective_action="Verify uploaded file and re-run extraction + report.",
                        deliverable_id=rep_deliv_id,
                        task_id=rep.get("task_id"),
                    )
                )

        for coll_name in ("findings", "verified_facts", "calculated_items"):
            for item in rep.get(coll_name) or []:
                if not isinstance(item, dict):
                    continue
                for rid in item.get("source_ref_ids") or []:
                    checked += 1
                    if str(rid) not in src_reg:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=item.get("discipline") or rep.get("discipline") or "multidisciplinary",
                                severity="critical",
                                title="Fake/orphan source reference ID in Review Report",
                                description=(
                                    f"Review Report '{rep['title']}' ({coll_name}) cites unknown reference ID '{rid}' "
                                    "which does not exist in source_registry or source logs."
                                ),
                                reference=f"Report {rep['revision']} / {rid}",
                                corrective_action="Remove fabricated citation or bind claim to an actual verified source ID.",
                                deliverable_id=rep_deliv_id,
                                task_id=rep.get("task_id"),
                            )
                        )

    # 2. Check BOQ rate_source_ref, technical_reference, and drawing_reference against actual sources/drawings
    for boq in ctx.boq_sheets:
        boq_deliv_id = deliv_by_boq.get(boq["id"])
        for it in boq["items"]:
            checked += 1
            item_ref_label = f"BOQ {boq['title']} / Item {it.get('item_no') or it.get('row_order')}"
            rate_kind = it.get("rate_source_kind")
            rate_ref = str(it.get("rate_source_ref") or "").strip()

            if rate_kind == "dated_research":
                if not rate_ref or not _url_is_reviewed(rate_ref):
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=it.get("discipline") or "quantity_surveying",
                            severity="high",
                            title="BOQ research rate references fake or unreviewed source",
                            description=(
                                f"BOQ item '{it.get('item_no')}' dated_research rate cites '{rate_ref or 'None'}', "
                                "which is not a reviewed ResearchSource in the source log."
                            ),
                            reference=item_ref_label,
                            corrective_action="Link rate_source_ref to a reviewed ResearchSource URL or convert to owner_input.",
                            deliverable_id=boq_deliv_id,
                            task_id=boq.get("task_id"),
                        )
                    )

            for field_name in ("technical_reference", "drawing_reference"):
                val = str(it.get(field_name) or "").strip()
                if not val:
                    continue
                for url_match in _URL_RE.findall(val):
                    checked += 1
                    if not _url_is_reviewed(url_match):
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=it.get("discipline") or "quantity_surveying",
                                severity="high",
                                title="Fake or unreviewed URL cited in BOQ",
                                description=(
                                    f"BOQ item '{it.get('item_no')}' {field_name} cites '{url_match}', "
                                    "which does not exist as a reviewed source in ResearchSource logs."
                                ),
                                reference=item_ref_label,
                                corrective_action="Verify URL via Research tab or replace with an actual project source.",
                                deliverable_id=boq_deliv_id,
                                task_id=boq.get("task_id"),
                            )
                        )
                if field_name == "drawing_reference":
                    val_lower = val.lower()
                    for m_sheet in _DRAWING_SHEET_REF_RE.findall(val.upper()):
                        checked += 1
                        if m_sheet not in valid_drawing_nos and not any(m_sheet.lower() in fn for fn in valid_filenames):
                            findings.append(
                                QaCandidateFinding(
                                    check_category="reference",
                                    discipline=it.get("discipline") or "quantity_surveying",
                                    severity="high",
                                    title="BOQ references nonexistent drawing number",
                                    description=(
                                        f"BOQ item '{it.get('item_no')}' cites drawing reference '{m_sheet}' ({val}), "
                                        "which matches no project parametric drawing or uploaded file."
                                    ),
                                    reference=item_ref_label,
                                    corrective_action="Update drawing_reference to match an issued drawing sheet or upload the missing sheet.",
                                    deliverable_id=boq_deliv_id,
                                    task_id=boq.get("task_id"),
                                )
                            )
                    if "source_file_id" in it and it.get("source_file_id") and it["source_file_id"] not in valid_file_ids:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline="quantity_surveying",
                                severity="high",
                                title="Missing source_file_id on BOQ item",
                                description=f"BOQ item '{it.get('item_no')}' references missing project file ID '{it['source_file_id']}'.",
                                reference=item_ref_label,
                                corrective_action="Re-import BOQ from active project files.",
                                deliverable_id=boq_deliv_id,
                                task_id=boq.get("task_id"),
                            )
                        )
                    if "fake" in val_lower or "nonexistent" in val_lower or "unknown_ref" in val_lower:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline="quantity_surveying",
                                severity="high",
                                title="Unverified/placeholder drawing reference in BOQ",
                                description=f"BOQ item '{it.get('item_no')}' carries suspicious unverified reference '{val}'.",
                                reference=item_ref_label,
                                corrective_action="Replace placeholder reference with an authoritative file/drawing link.",
                                deliverable_id=boq_deliv_id,
                                task_id=boq.get("task_id"),
                            )
                        )

    # 3. Check Step 13 calculation references against owner/verified source logs & mandatory verify-code label
    deliv_by_calc = {d["calculation_id"]: d["id"] for d in ctx.deliverables if d.get("calculation_id")}
    reviewed_rs_ids = {
        str(rs["id"])
        for rs in ctx.all_research_sources
        if rs.get("reviewed") and rs.get("access_status") in ("accessible", "owner_provided")
    }
    for calc in ctx.calculations:
        checked += 1
        calc_deliv_id = deliv_by_calc.get(calc["id"])
        ref_label = f"Calculation {calc['title']} ({calc['id'][:8]})"
        refs_list = calc.get("references_json") or []
        refs_text = str(calc.get("references_text") or "").strip()

        if not refs_list and not refs_text:
            findings.append(
                QaCandidateFinding(
                    check_category="reference",
                    discipline=calc.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Calculation missing standards/owner references",
                    description=f"Calculation '{calc['title']}' has no owner-supplied or verified source-log references.",
                    reference=ref_label,
                    corrective_action="Attach at least one owner-supplied or reviewed ResearchSource reference labelled 'verify against the locally adopted code'.",
                    deliverable_id=calc_deliv_id,
                    task_id=calc.get("task_id"),
                )
            )
            continue

        if VERIFY_CODE_LABEL not in refs_text.lower() and any(
            VERIFY_CODE_LABEL not in str(r.get("verification_label") or "").lower()
            for r in refs_list
            if isinstance(r, dict)
        ):
            findings.append(
                QaCandidateFinding(
                    check_category="reference",
                    discipline=calc.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Calculation reference missing locally-adopted-code verification label",
                    description=(
                        f"Calculation '{calc['title']}' references lack the mandatory '{VERIFY_CODE_LABEL}' label."
                    ),
                    reference=ref_label,
                    corrective_action=f"Label every calculation reference with '{VERIFY_CODE_LABEL}'.",
                    deliverable_id=calc_deliv_id,
                    task_id=calc.get("task_id"),
                )
            )

        for r_item in refs_list:
            if not isinstance(r_item, dict):
                continue
            checked += 1
            s_kind = str(r_item.get("source_kind") or "")
            s_ref = str(r_item.get("source_ref") or "").strip()
            rs_id = str(r_item.get("research_source_id") or "").strip()
            if s_kind == "verified_source_log":
                url_ok = s_ref in ctx.reviewed_research_urls or any(
                    u in s_ref for u in ctx.reviewed_research_urls
                )
                id_ok = bool(rs_id and rs_id in reviewed_rs_ids)
                if not (url_ok or id_ok):
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=calc.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Calculation cites unreviewed or missing research source",
                            description=(
                                f"Calculation '{calc['title']}' verified_source_log reference '{s_ref}' "
                                "does not match a reviewed ResearchSource in the project log."
                            ),
                            reference=ref_label,
                            corrective_action="Bind calculation reference to an accessible, reviewed ResearchSource or use owner_supplied.",
                            deliverable_id=calc_deliv_id,
                            task_id=calc.get("task_id"),
                        )
                    )
            for url_match in _URL_RE.findall(s_ref):
                if not _url_is_reviewed(url_match):
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=calc.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Calculation cites unreviewed URL",
                            description=(
                                f"Calculation '{calc['title']}' reference cites '{url_match}', "
                                "which is absent from reviewed project ResearchSource logs."
                            ),
                            reference=ref_label,
                            corrective_action="Verify URL via Research tab or replace with an approved owner source.",
                            deliverable_id=calc_deliv_id,
                            task_id=calc.get("task_id"),
                        )
                    )

        for url_match in _URL_RE.findall(refs_text):
            checked += 1
            if not _url_is_reviewed(url_match):
                findings.append(
                    QaCandidateFinding(
                        check_category="reference",
                        discipline=calc.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Calculation references_text cites unreviewed URL",
                        description=(
                            f"Calculation '{calc['title']}' references_text cites '{url_match}', "
                            "which is not in reviewed project ResearchSource logs."
                        ),
                        reference=ref_label,
                        corrective_action="Replace unreviewed URL with a reviewed ResearchSource or owner-supplied document reference.",
                        deliverable_id=calc_deliv_id,
                        task_id=calc.get("task_id"),
                    )
                )

    # 4. Check Step 14 specifications: no orphan/unsourced standards, unreviewed URLs, or invented standard codes
    deliv_by_spec = {d["specification_id"]: d["id"] for d in ctx.deliverables if d.get("specification_id")}
    reviewed_rs_by_id = {
        str(rs["id"]): rs
        for rs in ctx.all_research_sources
        if rs.get("reviewed") and rs.get("access_status") in ("accessible", "owner_provided")
    }
    boq_ref_corpus = " ".join(
        f"{it.get('technical_reference') or ''} {it.get('description') or ''}"
        for b in ctx.boq_sheets
        for it in b["items"]
    ).lower()
    reviewed_corpus = (
        " ".join(
            f"{rs.get('source_name') or ''} {rs.get('url') or ''} {rs.get('relevant_info') or ''}"
            for rs in reviewed_rs_by_id.values()
        ).lower()
        + " "
        + boq_ref_corpus
    )
    ungrounded_std_re = re.compile(
        r"\b(?:ASTM|ACI|BS|EN|IEC|IEEE|ISO|ASHRAE|NFPA|ASME|ANSI|SBC|LBC)\s*[A-Z]?\s*\d[\w./-]*\b",
        re.IGNORECASE,
    )

    for spec in ctx.specifications:
        checked += 1
        spec_deliv_id = deliv_by_spec.get(spec["id"])
        spec_ref = f"Specification {spec['title']} ({spec['id'][:8]})"
        sections = spec.get("sections") or []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_code = str(sec.get("section_code") or "SPEC")
            stds = sec.get("standards") or []
            if not stds:
                findings.append(
                    QaCandidateFinding(
                        check_category="reference",
                        discipline=str(sec.get("discipline") or spec.get("discipline") or "multidisciplinary"),
                        severity="high",
                        title="Specification section missing standards declaration",
                        description=(
                            f"Specification '{spec['title']}' section {sec_code} has an empty standards list "
                            f"and fails to state '{NO_VERIFIED_STANDARD_LABEL}'."
                        ),
                        reference=f"{spec_ref} / {sec_code}",
                        corrective_action=f"Cite reviewed source-log entries or set '{NO_VERIFIED_STANDARD_LABEL}'.",
                        deliverable_id=spec_deliv_id,
                        task_id=spec.get("task_id"),
                    )
                )
            for st in stds:
                if not isinstance(st, dict):
                    continue
                checked += 1
                st_status = str(st.get("status") or "")
                rs_id = str(st.get("research_source_id") or "").strip()
                st_url = str(st.get("url") or "").strip()
                cite_txt = str(st.get("citation_text") or "")
                verif_lbl = str(st.get("verification_label") or "")
                if st_status == "no_verified_standard_on_file":
                    if (
                        NO_VERIFIED_STANDARD_LABEL not in cite_txt.lower()
                        and NO_VERIFIED_STANDARD_LABEL not in verif_lbl.lower()
                    ):
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=str(sec.get("discipline") or "multidisciplinary"),
                                severity="high",
                                title="Missing unverified-standard disclaimer in specification",
                                description=(
                                    f"Section {sec_code} in '{spec['title']}' lacks the mandatory "
                                    f"'{NO_VERIFIED_STANDARD_LABEL}' notice."
                                ),
                                reference=f"{spec_ref} / {sec_code}",
                                corrective_action=f"Include exact label '{NO_VERIFIED_STANDARD_LABEL}'.",
                                deliverable_id=spec_deliv_id,
                                task_id=spec.get("task_id"),
                            )
                        )
                elif st_status == "verified_source_log":
                    rs_ok = bool(rs_id and rs_id in reviewed_rs_by_id)
                    url_ok = bool(st_url and _url_is_reviewed(st_url))
                    if not (rs_ok and url_ok):
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=str(sec.get("discipline") or "multidisciplinary"),
                                severity="high",
                                title="Orphan or unsourced standard cited in specification",
                                description=(
                                    f"Specification '{spec['title']}' section {sec_code} cites standard "
                                    f"'{st.get('source_name')}' (source_id={rs_id or 'none'}, url={st_url or 'none'}) "
                                    "which is missing, unreviewed, or inaccessible in ResearchSource log."
                                ),
                                reference=f"{spec_ref} / {sec_code}",
                                corrective_action="Replace orphan/unreviewed standard with a reviewed ResearchSource or explicit unverified-standard notice.",
                                deliverable_id=spec_deliv_id,
                                task_id=spec.get("task_id"),
                            )
                        )
                else:
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=str(sec.get("discipline") or "multidisciplinary"),
                            severity="high",
                            title="Unsourced standard status in specification",
                            description=f"Section {sec_code} declares unsupported standard status '{st_status}'.",
                            reference=f"{spec_ref} / {sec_code}",
                            corrective_action="Use only verified_source_log entries or no_verified_standard_on_file.",
                            deliverable_id=spec_deliv_id,
                            task_id=spec.get("task_id"),
                        )
                    )

            for cl in sec.get("clauses") or []:
                if not isinstance(cl, dict):
                    continue
                cl_txt = str(cl.get("text") or "")
                for url_hit in _URL_RE.findall(cl_txt):
                    checked += 1
                    if not _url_is_reviewed(url_hit):
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=str(sec.get("discipline") or "multidisciplinary"),
                                severity="high",
                                title="Specification clause cites unreviewed URL",
                                description=(
                                    f"Section {sec_code} clause {cl.get('clause_id')} cites '{url_hit}' "
                                    "which is absent from reviewed project ResearchSource entries."
                                ),
                                reference=f"{spec_ref} / {cl.get('clause_id')}",
                                corrective_action="Remove unreviewed URL or verify source via Research log first.",
                                deliverable_id=spec_deliv_id,
                                task_id=spec.get("task_id"),
                            )
                        )
                for std_hit in ungrounded_std_re.findall(cl_txt):
                    checked += 1
                    if std_hit.lower() not in reviewed_corpus:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=str(sec.get("discipline") or "multidisciplinary"),
                                severity="high",
                                title="Unsourced standard code citation in specification clause",
                                description=(
                                    f"Specification '{spec['title']}' section {sec_code} clause {cl.get('clause_id')} "
                                    f"cites unverified code '{std_hit}' not present in reviewed project ResearchSource or BOQ logs."
                                ),
                                reference=f"{spec_ref} / {cl.get('clause_id')}",
                                corrective_action="Cite standards ONLY from reviewed source-log entries or state 'no verified standard on file - verify against the locally adopted code'.",
                                deliverable_id=spec_deliv_id,
                                task_id=spec.get("task_id"),
                            )
                        )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="reference",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Verified {checked} report/BOQ/calculation source & drawing references against project logs; found {failed_cnt} issue(s).",
        ),
        findings,
    )


def _check_cross_deliverable_consistency(ctx: QaContextData) -> tuple[QaCheckMetricOut, list[QaCandidateFinding]]:
    checked = 0
    findings: list[QaCandidateFinding] = []
    deliv_by_dwg = {d["drawing_id"]: d["id"] for d in ctx.deliverables if d.get("drawing_id")}
    deliv_by_boq = {d["boq_id"]: d["id"] for d in ctx.deliverables if d.get("boq_id")}

    all_boq_items = [
        (boq, deliv_by_boq.get(boq["id"]), it)
        for boq in ctx.boq_sheets
        for it in boq["items"]
    ]

    for dwg in ctx.drawings:
        checked += 1
        dwg_no = str(dwg.get("drawing_no") or "")
        dwg_deliv_id = deliv_by_dwg.get(dwg["id"])
        metrics = dwg.get("computed_metrics_json") or {}
        door_sched = metrics.get("door_schedule") or []
        win_sched = metrics.get("window_schedule") or []

        # 1. Internal drawing model vs schedule consistency
        try:
            plan = ParametricPlanModel.model_validate(dwg["model_json"])
            expected_ds, expected_ws = build_schedules_from_model(plan)
            sched_door_total = sum(int(r.get("count") or 0) for r in door_sched)
            sched_win_total = sum(int(r.get("count") or 0) for r in win_sched)
            if sched_door_total != len(plan.doors):
                findings.append(
                    QaCandidateFinding(
                        check_category="schedule_consistency",
                        discipline="architecture",
                        severity="high",
                        title="Drawing door schedule vs model count mismatch",
                        description=(
                            f"Drawing {dwg_no} door_schedule sums to {sched_door_total} door(s), "
                            f"but plan_model.doors defines {len(plan.doors)} door(s)."
                        ),
                        reference=f"Drawing {dwg_no}",
                        corrective_action="Regenerate drawing schedules cleanly from plan_model.",
                        deliverable_id=dwg_deliv_id,
                        task_id=dwg.get("task_id"),
                    )
                )
            if sched_win_total != len(plan.windows):
                findings.append(
                    QaCandidateFinding(
                        check_category="schedule_consistency",
                        discipline="architecture",
                        severity="high",
                        title="Drawing window schedule vs model count mismatch",
                        description=(
                            f"Drawing {dwg_no} window_schedule sums to {sched_win_total} window(s), "
                            f"but plan_model.windows defines {len(plan.windows)} window(s)."
                        ),
                        reference=f"Drawing {dwg_no}",
                        corrective_action="Regenerate drawing schedules cleanly from plan_model.",
                        deliverable_id=dwg_deliv_id,
                        task_id=dwg.get("task_id"),
                    )
                )
        except Exception:
            sched_door_total = sum(int(r.get("count") or 0) for r in door_sched)
            sched_win_total = sum(int(r.get("count") or 0) for r in win_sched)

        if not dwg.get("round_trip_passed"):
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline="architecture",
                    severity="high",
                    title="Parametric DXF round-trip verification failed",
                    description=f"Drawing {dwg_no} failed internal DXF read-back round-trip consistency check.",
                    reference=f"Drawing {dwg_no}",
                    corrective_action="Inspect DXF round-trip mismatches and regenerate drawing.",
                    deliverable_id=dwg_deliv_id,
                    task_id=dwg.get("task_id"),
                )
            )

        # 2. Cross-check ParametricDrawing schedules against Project BOQ sheets!
        if all_boq_items:
            checked += 1
            for boq in ctx.boq_sheets:
                boq_deliv_id = deliv_by_boq.get(boq["id"])
                door_boq_items = [
                    it
                    for it in boq["items"]
                    if any(k in str(it.get("description") or "").lower() for k in _DOOR_CUES)
                    and _classify_unit_family(str(it.get("unit") or "")) == "count"
                    and (not str(it.get("drawing_reference") or "").strip() or dwg_no.upper() in str(it.get("drawing_reference") or "").upper())
                ]
                if door_boq_items:
                    boq_doors = sum(float(it.get("quantity") or 0.0) for it in door_boq_items)
                    if abs(boq_doors - sched_door_total) > 0.01:
                        findings.append(
                            QaCandidateFinding(
                                check_category="schedule_consistency",
                                discipline="coordination",
                                severity="high",
                                title="Door schedule vs BOQ quantity mismatch",
                                description=(
                                    f"Schedule mismatch: Drawing {dwg_no} Door Schedule specifies {sched_door_total} door(s), "
                                    f"whereas BOQ '{boq['title']}' quantifies {boq_doors:g} door(s)."
                                ),
                                reference=f"Drawing {dwg_no} <-> BOQ {boq['title']}",
                                corrective_action=f"Reconcile BOQ door quantities to match Drawing {dwg_no} Door Schedule ({sched_door_total} nos) or revise drawing.",
                                deliverable_id=boq_deliv_id or dwg_deliv_id,
                                task_id=boq.get("task_id") or dwg.get("task_id"),
                            )
                        )

                win_boq_items = [
                    it
                    for it in boq["items"]
                    if any(k in str(it.get("description") or "").lower() for k in _WINDOW_CUES)
                    and _classify_unit_family(str(it.get("unit") or "")) == "count"
                    and (not str(it.get("drawing_reference") or "").strip() or dwg_no.upper() in str(it.get("drawing_reference") or "").upper())
                ]
                if win_boq_items:
                    boq_wins = sum(float(it.get("quantity") or 0.0) for it in win_boq_items)
                    if abs(boq_wins - sched_win_total) > 0.01:
                        findings.append(
                            QaCandidateFinding(
                                check_category="schedule_consistency",
                                discipline="coordination",
                                severity="high",
                                title="Window schedule vs BOQ quantity mismatch",
                                description=(
                                    f"Schedule mismatch: Drawing {dwg_no} Window Schedule specifies {sched_win_total} window(s), "
                                    f"whereas BOQ '{boq['title']}' quantifies {boq_wins:g} window(s)."
                                ),
                                reference=f"Drawing {dwg_no} <-> BOQ {boq['title']}",
                                corrective_action=f"Reconcile BOQ window quantities to match Drawing {dwg_no} Window Schedule ({sched_win_total} nos).",
                                deliverable_id=boq_deliv_id or dwg_deliv_id,
                                task_id=boq.get("task_id") or dwg.get("task_id"),
                            )
                        )

                # Whole-plan floor finishes BOQ area check vs Drawing total_area_m2
                dwg_total_area = float(metrics.get("total_area_m2") or 0.0)
                whole_floor_items = [
                    it
                    for it in boq["items"]
                    if any(k in str(it.get("description") or "").lower() for k in _FLOOR_TOTAL_CUES)
                    and _classify_unit_family(str(it.get("unit") or "")) == "area_metric"
                    and dwg_no.upper() in str(it.get("drawing_reference") or "").upper()
                ]
                if whole_floor_items and dwg_total_area > 0:
                    boq_floor_area = sum(float(it.get("quantity") or 0.0) for it in whole_floor_items)
                    if abs(boq_floor_area - dwg_total_area) > max(0.5, dwg_total_area * 0.02):
                        findings.append(
                            QaCandidateFinding(
                                check_category="schedule_consistency",
                                discipline="coordination",
                                severity="high",
                                title="Drawing net floor area vs BOQ floor finish area mismatch",
                                description=(
                                    f"Schedule/area mismatch: Drawing {dwg_no} computed net room area is {dwg_total_area:.2f} m2, "
                                    f"whereas BOQ '{boq['title']}' total floor finish quantity is {boq_floor_area:.2f} m2."
                                ),
                                reference=f"Drawing {dwg_no} <-> BOQ {boq['title']}",
                                corrective_action=f"Align BOQ floor area takeoff with Drawing {dwg_no} computed area ({dwg_total_area:.2f} m2).",
                                deliverable_id=boq_deliv_id or dwg_deliv_id,
                                task_id=boq.get("task_id") or dwg.get("task_id"),
                            )
                        )

    # 3. Check Step 13 calculation acceptance criteria & mandatory 8-section completeness
    deliv_by_calc = {d["calculation_id"]: d["id"] for d in ctx.deliverables if d.get("calculation_id")}
    for calc in ctx.calculations:
        checked += 1
        calc_deliv_id = deliv_by_calc.get(calc["id"])
        ref = f"Calculation {calc['title']} ({calc['id'][:8]})"
        missing_sections = [
            sec
            for sec, val in (
                ("inputs_json", calc.get("inputs_json")),
                ("units_json", calc.get("units_json")),
                ("equations", calc.get("equations")),
                ("methodology", calc.get("methodology")),
                ("assumptions", calc.get("assumptions")),
                ("results_json", calc.get("results_json")),
                ("acceptance_criteria", calc.get("acceptance_criteria")),
                ("references", calc.get("references_json") or calc.get("references_text")),
            )
            if not val
        ]
        if missing_sections:
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=calc.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Calculation missing mandatory framework sections",
                    description=(
                        f"Calculation '{calc['title']}' is missing required section(s): {', '.join(missing_sections)}."
                    ),
                    reference=ref,
                    corrective_action="Recompute calculation so all 8 required documentation sections are populated.",
                    deliverable_id=calc_deliv_id,
                    task_id=calc.get("task_id"),
                )
            )
        if not calc.get("acceptance_passed") or not (calc.get("results_json") or {}).get("acceptance_passed"):
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=calc.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Calculation fails engineering acceptance criteria",
                    description=(
                        f"Calculation '{calc['title']}' ({calc['calculation_type']}) did not pass its engineering acceptance criteria "
                        f"({calc.get('acceptance_criteria', '')[:200]})."
                    ),
                    reference=ref,
                    corrective_action="Adjust sizing/design parameters until all acceptance criteria pass and re-run calculation.",
                    deliverable_id=calc_deliv_id,
                    task_id=calc.get("task_id"),
                )
            )

    # 4. Check Step 14 specifications: every section maps to >= 1 BOQ item/drawing, zero orphan refs, all 8 sub-sections present
    deliv_by_spec = {d["specification_id"]: d["id"] for d in ctx.deliverables if d.get("specification_id")}
    valid_boq_item_ids = {str(it["id"]) for b in ctx.boq_sheets for it in b["items"]}
    valid_drawing_ids = {str(d["id"]) for d in ctx.drawings}
    valid_source_ids = {str(rs["id"]) for rs in ctx.all_research_sources if rs.get("reviewed") and rs.get("access_status") in ("accessible", "owner_provided")}

    for spec in ctx.specifications:
        checked += 1
        spec_deliv_id = deliv_by_spec.get(spec["id"])
        spec_ref = f"Specification {spec['title']} ({spec['id'][:8]})"

        if spec.get("ai_draft_status") == "unverified_ai_draft":
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=spec.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="AI-drafted specification pending owner approval",
                    description=(
                        f"Specification '{spec['title']}' contains AI-drafted prose marked 'unverified_ai_draft' "
                        "and has not yet been approved by the owner."
                    ),
                    reference=spec_ref,
                    corrective_action="Review clauses and record owner approval via POST /api/specifications/{id}/approve.",
                    deliverable_id=spec_deliv_id,
                    task_id=spec.get("task_id"),
                )
            )

        sections = spec.get("sections") or []
        if not sections:
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=spec.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Specification package missing sections",
                    description=f"Specification '{spec['title']}' has no specification sections.",
                    reference=spec_ref,
                    corrective_action="Regenerate specification from active BOQ items and drawing schedules.",
                    deliverable_id=spec_deliv_id,
                    task_id=spec.get("task_id"),
                )
            )
            continue

        for sec in sections:
            if not isinstance(sec, dict):
                continue
            checked += 1
            sec_code = str(sec.get("section_code") or "SPEC")
            sec_disc = str(sec.get("discipline") or spec.get("discipline") or "multidisciplinary")
            mapped_boqs = [str(bid) for bid in (sec.get("mapped_boq_item_ids") or []) if str(bid)]
            mapped_dwgs = [str(did) for did in (sec.get("mapped_drawing_ids") or []) if str(did)]

            orphan_boqs = [bid for bid in mapped_boqs if bid not in valid_boq_item_ids]
            orphan_dwgs = [did for did in mapped_dwgs if did not in valid_drawing_ids]
            valid_links_cnt = (len(mapped_boqs) - len(orphan_boqs)) + (len(mapped_dwgs) - len(orphan_dwgs))

            if orphan_boqs or orphan_dwgs or valid_links_cnt == 0:
                findings.append(
                    QaCandidateFinding(
                        check_category="schedule_consistency",
                        discipline=sec_disc,
                        severity="high",
                        title="Orphan or unmapped specification section",
                        description=(
                            f"Specification '{spec['title']}' section {sec_code} fails BOQ/drawing traceability "
                            f"(valid_links={valid_links_cnt}, orphan_boqs={orphan_boqs}, orphan_drawings={orphan_dwgs})."
                        ),
                        reference=f"{spec_ref} / {sec_code}",
                        corrective_action="Ensure every specification section maps directly to existing project BOQ items or parametric drawing schedules.",
                        deliverable_id=spec_deliv_id,
                        task_id=spec.get("task_id"),
                    )
                )

            clauses = [c for c in (sec.get("clauses") or []) if isinstance(c, dict)]
            present_parts = {str(c.get("part") or "") for c in clauses if str(c.get("text") or "").strip()}
            missing_parts = [p for p in SPEC_SECTION_PARTS if p not in present_parts]
            if missing_parts:
                findings.append(
                    QaCandidateFinding(
                        check_category="schedule_consistency",
                        discipline=sec_disc,
                        severity="high",
                        title="Specification section missing mandatory sub-sections",
                        description=(
                            f"Specification '{spec['title']}' section {sec_code} is missing required sub-section(s): "
                            f"{', '.join(missing_parts)}."
                        ),
                        reference=f"{spec_ref} / {sec_code}",
                        corrective_action="Populate all 8 mandatory parts (scope, standards, materials, execution, testing, acceptance, submittals, warranty).",
                        deliverable_id=spec_deliv_id,
                        task_id=spec.get("task_id"),
                    )
                )

            for cl in clauses:
                traces = [tr for tr in (cl.get("trace_refs") or []) if isinstance(tr, dict)]
                if not traces:
                    findings.append(
                        QaCandidateFinding(
                            check_category="schedule_consistency",
                            discipline=sec_disc,
                            severity="high",
                            title="Specification clause missing source traceability anchor",
                            description=f"Section {sec_code} clause {cl.get('clause_id')} has zero BOQ/drawing/source traces.",
                            reference=f"{spec_ref} / {cl.get('clause_id')}",
                            corrective_action="Attach valid BOQ item, drawing schedule, or source trace reference to every clause.",
                            deliverable_id=spec_deliv_id,
                            task_id=spec.get("task_id"),
                        )
                    )
                for tr in traces:
                    if tr.get("boq_item_id") and str(tr["boq_item_id"]) not in valid_boq_item_ids:
                        findings.append(
                            QaCandidateFinding(
                                check_category="schedule_consistency",
                                discipline=sec_disc,
                                severity="high",
                                title="Specification clause traces to missing BOQ item",
                                description=f"Clause {cl.get('clause_id')} traces to non-existent BOQ item ID '{tr['boq_item_id']}'.",
                                reference=f"{spec_ref} / {cl.get('clause_id')}",
                                corrective_action="Re-generate specification from active project BOQ items.",
                                deliverable_id=spec_deliv_id,
                                task_id=spec.get("task_id"),
                            )
                        )
                    if tr.get("drawing_id") and str(tr["drawing_id"]) not in valid_drawing_ids:
                        findings.append(
                            QaCandidateFinding(
                                check_category="schedule_consistency",
                                discipline=sec_disc,
                                severity="high",
                                title="Specification clause traces to missing drawing",
                                description=f"Clause {cl.get('clause_id')} traces to non-existent drawing ID '{tr['drawing_id']}'.",
                                reference=f"{spec_ref} / {cl.get('clause_id')}",
                                corrective_action="Re-generate specification from active project drawings.",
                                deliverable_id=spec_deliv_id,
                                task_id=spec.get("task_id"),
                            )
                        )
                    if tr.get("research_source_id") and str(tr["research_source_id"]) not in valid_source_ids:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=sec_disc,
                                severity="high",
                                title="Specification clause traces to unreviewed/missing ResearchSource",
                                description=f"Clause {cl.get('clause_id')} traces to unreviewed/missing source '{tr['research_source_id']}'.",
                                reference=f"{spec_ref} / {cl.get('clause_id')}",
                                corrective_action="Replace trace with reviewed ResearchSource ID.",
                                deliverable_id=spec_deliv_id,
                                task_id=spec.get("task_id"),
                            )
                        )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="schedule_consistency",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Evaluated {checked} drawing/BOQ/calculation consistency & acceptance check(s); found {failed_cnt} issue(s).",
        ),
        findings,
    )


def _check_missing_deliverables_and_integrity(
    ctx: QaContextData,
    settings: Settings,
    workspace_slug: str,
) -> tuple[QaCheckMetricOut, list[QaCandidateFinding]]:
    checked = 0
    findings: list[QaCandidateFinding] = []

    # 1. Check every registered Deliverable exists on disk and SHA-256 matches
    delivs_by_dwg: dict[str, set[str]] = {}
    delivs_by_report: dict[str, set[str]] = {}
    delivs_by_boq: dict[str, set[str]] = {}
    delivs_by_calc: dict[str, set[str]] = {}
    delivs_by_spec: dict[str, set[str]] = {}

    for d in ctx.deliverables:
        checked += 1
        rel = d.get("relative_path")
        if d.get("drawing_id"):
            delivs_by_dwg.setdefault(d["drawing_id"], set()).add(str(d.get("format") or "").lower())
        if d.get("report_id"):
            delivs_by_report.setdefault(d["report_id"], set()).add(f"{d.get('folder_name')}:{d.get('format')}")
        if d.get("boq_id"):
            delivs_by_boq.setdefault(d["boq_id"], set()).add(str(d.get("format") or "").lower())
        if d.get("calculation_id"):
            delivs_by_calc.setdefault(d["calculation_id"], set()).add(str(d.get("format") or "").lower())
        if d.get("specification_id"):
            delivs_by_spec.setdefault(d["specification_id"], set()).add(str(d.get("format") or "").lower())

        if not rel:
            findings.append(
                QaCandidateFinding(
                    check_category="missing_deliverable",
                    discipline=d.get("discipline") or "multidisciplinary",
                    severity="critical",
                    title="Deliverable missing relative file path",
                    description=f"Deliverable '{d['title']}' has no on-disk relative path registered.",
                    reference=f"Deliverable {d['id'][:8]}",
                    corrective_action="Regenerate deliverable so file is written cleanly to project workspace.",
                    deliverable_id=d["id"],
                    task_id=d.get("task_id"),
                )
            )
            continue

        disk_path = resolve_project_file_path(settings.workspaces_dir, workspace_slug, rel)
        if not disk_path.is_file():
            findings.append(
                QaCandidateFinding(
                    check_category="missing_deliverable",
                    discipline=d.get("discipline") or "multidisciplinary",
                    severity="critical",
                    title="Deliverable file missing from workspace disk",
                    description=f"Registered deliverable file '{rel}' is missing on disk.",
                    reference=str(rel),
                    corrective_action="Regenerate or restore deliverable file and verify SHA-256.",
                    deliverable_id=d["id"],
                    task_id=d.get("task_id"),
                )
            )
        elif d.get("sha256"):
            actual_sha = sha256_file(disk_path)
            if actual_sha != d["sha256"]:
                findings.append(
                    QaCandidateFinding(
                        check_category="integrity",
                        discipline=d.get("discipline") or "multidisciplinary",
                        severity="critical",
                        title="Deliverable SHA-256 integrity mismatch",
                        description=(
                            f"Deliverable '{rel}' SHA-256 ({actual_sha[:12]}) disagrees with registered "
                            f"checksum ({str(d['sha256'])[:12]})."
                        ),
                        reference=str(rel),
                        corrective_action="Quarantine modified artifact and regenerate clean versioned deliverable.",
                        deliverable_id=d["id"],
                        task_id=d.get("task_id"),
                    )
                )

    # 2. Required paired deliverables (DXF + PDF for drawings; XLSX + CSV for exported BOQs; DOCX + PDF for reports)
    for dwg in ctx.drawings:
        checked += 1
        fmts = delivs_by_dwg.get(dwg["id"], set())
        if not {"dxf", "pdf"}.issubset(fmts):
            missing = sorted({"dxf", "pdf"} - fmts)
            findings.append(
                QaCandidateFinding(
                    check_category="missing_deliverable",
                    discipline="architecture",
                    severity="high",
                    title="Parametric drawing package incomplete",
                    description=f"Drawing {dwg['drawing_no']} is missing {', '.join(missing).upper()} deliverable file(s) in 05_Design_Drawings.",
                    reference=f"Drawing {dwg['drawing_no']}",
                    corrective_action="Re-export complete DXF + true-scale PDF package.",
                    task_id=dwg.get("task_id"),
                )
            )

    for rep in ctx.review_reports:
        checked += 1
        keys = delivs_by_report.get(rep["id"], set())
        needed = {"08_Reports:docx", "08_Reports:pdf", "10_Final_Deliverables:docx", "10_Final_Deliverables:pdf"}
        missing = sorted(needed - keys)
        if missing:
            findings.append(
                QaCandidateFinding(
                    check_category="missing_deliverable",
                    discipline=rep.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Review report deliverable files incomplete",
                    description=f"Review Report '{rep['title']}' is missing output(s): {', '.join(missing)}.",
                    reference=f"Report {rep['revision']}",
                    corrective_action="Regenerate DOCX + PDF into 08_Reports and 10_Final_Deliverables.",
                    task_id=rep.get("task_id"),
                )
            )

    for boq in ctx.boq_sheets:
        if int(boq.get("export_version") or 0) > 0:
            checked += 1
            fmts = delivs_by_boq.get(boq["id"], set())
            missing = sorted({"xlsx", "csv"} - fmts)
            if missing:
                findings.append(
                    QaCandidateFinding(
                        check_category="missing_deliverable",
                        discipline="quantity_surveying",
                        severity="high",
                        title="Exported BOQ deliverables incomplete",
                        description=f"BOQ '{boq['title']}' is missing {', '.join(missing).upper()} export file(s) in 06_BOQ.",
                        reference=f"BOQ {boq['title']}",
                        corrective_action="Re-export BOQ XLSX + CSV package into 06_BOQ.",
                        task_id=boq.get("task_id"),
                    )
                )

    for calc in ctx.calculations:
        if int(calc.get("export_version") or 0) > 0:
            checked += 1
            fmts = delivs_by_calc.get(calc["id"], set())
            missing = sorted({"docx", "pdf", "xlsx"} - fmts)
            if missing:
                findings.append(
                    QaCandidateFinding(
                        check_category="missing_deliverable",
                        discipline=calc.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Exported calculation deliverables incomplete",
                        description=(
                            f"Calculation '{calc['title']}' is missing {', '.join(missing).upper()} "
                            "export file(s) in 04_Engineering_Calculations."
                        ),
                        reference=f"Calculation {calc['title']}",
                        corrective_action="Re-export calculation DOCX + PDF + XLSX into 04_Engineering_Calculations.",
                        task_id=calc.get("task_id"),
                    )
                )

    for spec in ctx.specifications:
        if int(spec.get("export_version") or 0) > 0:
            checked += 1
            fmts = delivs_by_spec.get(spec["id"], set())
            missing = sorted({"docx", "pdf"} - fmts)
            if missing:
                findings.append(
                    QaCandidateFinding(
                        check_category="missing_deliverable",
                        discipline=spec.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Exported specification deliverables incomplete",
                        description=(
                            f"Specification '{spec['title']}' is missing {', '.join(missing).upper()} "
                            "export file(s) in 07_Technical_Specifications."
                        ),
                        reference=f"Specification {spec['title']}",
                        corrective_action="Re-export specification DOCX + PDF into 07_Technical_Specifications.",
                        task_id=spec.get("task_id"),
                    )
                )

    # 3. Task expected deliverables coverage check (without reading producer reasoning)
    if ctx.task_id and ctx.expected_task_deliverables:
        has_boq = bool(ctx.boq_sheets) or any(d.get("folder_name") == "06_BOQ" for d in ctx.deliverables)
        has_drawing = bool(ctx.drawings) or any(d.get("folder_name") == "05_Design_Drawings" for d in ctx.deliverables)
        has_report = bool(ctx.review_reports) or any(
            d.get("folder_name") in {"08_Reports", "10_Final_Deliverables"} for d in ctx.deliverables
        )
        has_calc = bool(ctx.calculations) or any(
            d.get("folder_name") == "04_Engineering_Calculations" for d in ctx.deliverables
        )
        has_spec = bool(ctx.specifications) or any(
            d.get("folder_name") == "07_Technical_Specifications" for d in ctx.deliverables
        )
        for exp in ctx.expected_task_deliverables:
            checked += 1
            low = exp.lower()
            if any(k in low for k in ("boq", "bill of quantities", "quantity", "كميات")):
                if not has_boq:
                    findings.append(
                        QaCandidateFinding(
                            check_category="missing_deliverable",
                            discipline="quantity_surveying",
                            severity="high",
                            title="Missing expected BOQ deliverable for task",
                            description=f"Task expects deliverable '{exp}', but no BOQ sheet or 06_BOQ deliverable is linked.",
                            reference=f"Task {ctx.task_id[:8]} / {exp}",
                            corrective_action="Generate and link BOQ deliverable for this task before verification.",
                            task_id=ctx.task_id,
                        )
                    )
            elif any(k in low for k in ("drawing", "plan", "dxf", "cad", "مخطط", "لوحة")):
                if not has_drawing:
                    findings.append(
                        QaCandidateFinding(
                            check_category="missing_deliverable",
                            discipline="architecture",
                            severity="high",
                            title="Missing expected CAD drawing deliverable for task",
                            description=f"Task expects deliverable '{exp}', but no Parametric CAD drawing or 05_Design_Drawings deliverable is linked.",
                            reference=f"Task {ctx.task_id[:8]} / {exp}",
                            corrective_action="Generate and link DXF + true-scale PDF drawing package for this task.",
                            task_id=ctx.task_id,
                        )
                    )
            elif any(k in low for k in ("report", "review", "تقرير", "مراجعة")):
                if not has_report:
                    findings.append(
                        QaCandidateFinding(
                            check_category="missing_deliverable",
                            discipline="multidisciplinary",
                            severity="high",
                            title="Missing expected review report deliverable for task",
                            description=f"Task expects deliverable '{exp}', but no Review Report deliverable in 08_Reports/10_Final_Deliverables is linked.",
                            reference=f"Task {ctx.task_id[:8]} / {exp}",
                            corrective_action="Generate DOCX + PDF Review Report for this task before verification.",
                            task_id=ctx.task_id,
                        )
                    )
            elif any(k in low for k in ("calculation", "calc", "load schedule", "cable sizing", "voltage drop", "water demand", "pipe sizing", "حسابات", "حساب")):
                if not has_calc:
                    findings.append(
                        QaCandidateFinding(
                            check_category="missing_deliverable",
                            discipline="multidisciplinary",
                            severity="high",
                            title="Missing expected engineering calculation deliverable for task",
                            description=f"Task expects deliverable '{exp}', but no Calculation or 04_Engineering_Calculations deliverable is linked.",
                            reference=f"Task {ctx.task_id[:8]} / {exp}",
                            corrective_action="Run and link deterministic calculation (and export DOCX/PDF/XLSX) for this task.",
                            task_id=ctx.task_id,
                        )
                    )
            elif any(k in low for k in ("spec", "specification", "specifications", "مواصفات", "مواصفة")):
                if not has_spec:
                    findings.append(
                        QaCandidateFinding(
                            check_category="missing_deliverable",
                            discipline="multidisciplinary",
                            severity="high",
                            title="Missing expected technical specification deliverable for task",
                            description=f"Task expects deliverable '{exp}', but no Specification or 07_Technical_Specifications deliverable is linked.",
                            reference=f"Task {ctx.task_id[:8]} / {exp}",
                            corrective_action="Generate and link project Technical Specifications (DOCX + PDF) for this task.",
                            task_id=ctx.task_id,
                        )
                    )
            elif not _expected_deliverable_covered(exp, ctx):
                findings.append(
                    QaCandidateFinding(
                        check_category="missing_deliverable",
                        discipline="multidisciplinary",
                        severity="high",
                        title="Missing expected deliverable for task",
                        description=f"Task expects deliverable '{exp}', but no matching deliverable is linked.",
                        reference=f"Task {ctx.task_id[:8]} / {exp}",
                        corrective_action=f"Produce and link '{exp}' deliverable for this task before verification.",
                        task_id=ctx.task_id,
                    )
                )

    # Also catch zero-deliverable QA run on a task so an empty task never falsely passes verification
    if ctx.task_id and not (
        ctx.deliverables or ctx.boq_sheets or ctx.drawings or ctx.review_reports or ctx.calculations or ctx.specifications
    ):
        checked += 1
        findings.append(
            QaCandidateFinding(
                check_category="missing_deliverable",
                discipline="multidisciplinary",
                severity="high",
                title="No deliverables produced for task",
                description="Task has no linked deliverables, BOQs, drawings, or reports for QA inspection.",
                reference=f"Task {ctx.task_id[:8]}",
                corrective_action="Produce required engineering deliverables before submitting task for QA verification.",
                task_id=ctx.task_id,
            )
        )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="missing_deliverable",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Verified {checked} deliverable disk/checksum/completeness expectation(s); found {failed_cnt} issue(s).",
        ),
        findings,
    )


def evaluate_independent_qa(
    ctx: QaContextData,
    *,
    settings: Settings,
    workspace_slug: str,
    check_arithmetic: bool = True,
    check_units: bool = True,
    check_references: bool = True,
    check_consistency: bool = True,
    check_missing_deliverables: bool = True,
) -> tuple[list[QaCheckMetricOut], list[QaCandidateFinding]]:
    """Run all requested independent deterministic QA checks (0 AI tokens)."""
    metrics: list[QaCheckMetricOut] = []
    all_findings: list[QaCandidateFinding] = []

    if check_arithmetic:
        m, f = _check_arithmetic(ctx, settings, workspace_slug)
        metrics.append(m)
        all_findings.extend(f)

    if check_units:
        m, f = _check_units(ctx)
        metrics.append(m)
        all_findings.extend(f)

    if check_references:
        m, f = _check_references(ctx)
        metrics.append(m)
        all_findings.extend(f)

    if check_consistency:
        m, f = _check_cross_deliverable_consistency(ctx)
        metrics.append(m)
        all_findings.extend(f)

    if check_missing_deliverables:
        m, f = _check_missing_deliverables_and_integrity(ctx, settings, workspace_slug)
        metrics.append(m)
        all_findings.extend(f)

    return metrics, all_findings
