"""Step 12 independent QA Agent: isolated context builder (zero producer reasoning) and deterministic cross-deliverable verifiers."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import or_, select
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
    ProjectSchedule,
    ResearchSource,
    ReviewReport,
    SpecialistAssessment,
    Specification,
    StandardDocument,
    Task,
    TechnicalComparison,
)
from app.schemas.calculations import VERIFY_CODE_LABEL
from app.schemas.comparisons import ComparisonCriterionIn, ComparisonOptionIn, NOT_PROVIDED_LABEL
from app.schemas.drawings import ParametricPlanModel
from app.schemas.planning import (
    ScheduleActivityIn,
    ScheduleResultOut,
    WbsItemIn,
    WorkCalendarIn,
)
from app.schemas.qa import IssueCategory, IssueSeverity, QaCheckMetricOut, QaContextIsolationReport
from app.schemas.specialist import NO_VERIFIED_STANDARD_LABEL as SPECIALIST_NO_STD_LABEL
from app.schemas.specifications import NO_VERIFIED_STANDARD_LABEL, SPEC_SECTION_PARTS
from app.services.parametric_cad import build_schedules_from_model, compute_room_metrics, sha256_file
from app.services.workspace import resolve_project_file_path
from app.skills.calculations import evaluate_calculation
from app.skills.comparisons import recompute_comparison_matrix
from app.skills.planning import _detect_graph_issues, evaluate_project_schedule
from app.skills.specialist import SpecialistInputError, evaluate_specialist_assessment
from app.skills.standards import STANDARD_CODE_DETECT_RE, find_citations_for_standard, resolve_supersession_chain

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
    comparisons: list[dict[str, Any]] = field(default_factory=list)
    schedules: list[dict[str, Any]] = field(default_factory=list)
    standards_library: list[dict[str, Any]] = field(default_factory=list)
    specialist_assessments: list[dict[str, Any]] = field(default_factory=list)
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
                "comparison_id": d.comparison_id,
                "schedule_id": d.schedule_id,
                "assessment_id": d.assessment_id,
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

    cmp_rows = db.scalars(
        select(TechnicalComparison)
        .where(TechnicalComparison.project_id == project.id)
        .order_by(TechnicalComparison.created_at.desc())
    ).all()
    for cmp_row in cmp_rows:
        if task is not None and cmp_row.task_id and cmp_row.task_id != task.id:
            continue
        ctx.comparisons.append(
            {
                "id": cmp_row.id,
                "task_id": cmp_row.task_id,
                "title": cmp_row.title,
                "comparison_scope": cmp_row.comparison_scope,
                "discipline": cmp_row.discipline,
                "language": cmp_row.language,
                "classification": cmp_row.classification,
                "revision": cmp_row.revision,
                "version": cmp_row.version,
                "export_version": cmp_row.export_version,
                "ai_draft_status": cmp_row.ai_draft_status,
                "owner_decision_status": cmp_row.owner_decision_status,
                "owner_selected_option_id": cmp_row.owner_selected_option_id,
                "criteria_json": list(cmp_row.criteria_json or []),
                "options_json": list(cmp_row.options_json or []),
                "matrix_result_json": dict(cmp_row.matrix_result_json or {}),
            }
        )

    sched_rows = db.scalars(
        select(ProjectSchedule)
        .where(ProjectSchedule.project_id == project.id)
        .order_by(ProjectSchedule.created_at.desc())
    ).all()
    for s_row in sched_rows:
        if task is not None and s_row.task_id and s_row.task_id != task.id:
            continue
        ctx.schedules.append(
            {
                "id": s_row.id,
                "task_id": s_row.task_id,
                "baseline_schedule_id": s_row.baseline_schedule_id,
                "title": s_row.title,
                "discipline": s_row.discipline,
                "language": s_row.language,
                "classification": s_row.classification,
                "revision": s_row.revision,
                "version": s_row.version,
                "export_version": s_row.export_version,
                "is_baseline": bool(s_row.is_baseline),
                "start_date": s_row.start_date,
                "ai_draft_status": s_row.ai_draft_status,
                "calendar_json": dict(s_row.calendar_json or {}),
                "wbs_items_json": list(s_row.wbs_items_json or []),
                "activities_json": list(s_row.activities_json or []),
                "schedule_result_json": dict(s_row.schedule_result_json or {}),
            }
        )

    std_rows = db.scalars(
        select(StandardDocument)
        .where(or_(StandardDocument.project_id == project.id, StandardDocument.project_id.is_(None)))
        .order_by(StandardDocument.standard_number.asc())
    ).all()
    std_raw_by_id = {
        s.id: {
            "id": s.id,
            "standard_number": s.standard_number,
            "title": s.title,
            "edition_year": s.edition_year,
            "status": s.status,
            "superseded_by_id": s.superseded_by_id,
        }
        for s in std_rows
    }
    for s in std_rows:
        sup_num, sup_title, chain_summary = resolve_supersession_chain(
            std_id=s.id,
            docs_by_id=std_raw_by_id,
        )
        ctx.standards_library.append(
            {
                "id": s.id,
                "project_id": s.project_id,
                "standard_number": s.standard_number,
                "title": s.title,
                "issuing_body": s.issuing_body,
                "edition_year": s.edition_year,
                "status": s.status,
                "superseded_by_id": s.superseded_by_id,
                "superseded_by_number": sup_num,
                "superseded_by_title": sup_title,
                "supersession_chain": chain_summary,
                "metadata_status": s.metadata_status,
                "ai_suggestion_status": s.ai_suggestion_status,
                "adopted_locally": bool(s.adopted_locally),
                "jurisdiction": s.jurisdiction,
            }
        )

    assess_rows = db.scalars(
        select(SpecialistAssessment)
        .where(SpecialistAssessment.project_id == project.id)
        .order_by(SpecialistAssessment.created_at.desc())
    ).all()
    for a_row in assess_rows:
        if task is not None and a_row.task_id and a_row.task_id != task.id:
            continue
        ctx.specialist_assessments.append(
            {
                "id": a_row.id,
                "task_id": a_row.task_id,
                "domain": a_row.domain,
                "workflow_mode": a_row.workflow_mode,
                "title": a_row.title,
                "language": a_row.language,
                "classification": a_row.classification,
                "revision": a_row.revision,
                "version": a_row.version,
                "export_version": a_row.export_version,
                "status": a_row.status,
                "checks_passed": bool(a_row.checks_passed),
                "blocked_missing_count": a_row.blocked_missing_count,
                "failed_checks_count": a_row.failed_checks_count,
                "standards_status": a_row.standards_status,
                "use_ai": bool(a_row.use_ai),
                "ai_draft_status": a_row.ai_draft_status,
                "inputs_json": dict(a_row.inputs_json or {}),
                "results_json": dict(a_row.results_json or {}),
                "references_json": list(a_row.references_json or []),
                "software_recommendation": a_row.software_recommendation or "",
                "summary": a_row.summary or "",
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
        + len(ctx.comparisons)
        + len(ctx.schedules)
        + len(ctx.specialist_assessments)
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
    haystacks.extend(
        f"{c.get('title', '')} {c.get('discipline', '')} {c.get('comparison_scope', '')} comparison tradeoff trade-off matrix".lower()
        for c in ctx.comparisons
    )
    haystacks.extend(
        f"{sc.get('title', '')} {sc.get('discipline', '')} schedule wbs gantt critical path planning".lower()
        for sc in ctx.schedules
    )
    haystacks.extend(
        f"{sa.get('title', '')} {sa.get('domain', '')} {sa.get('workflow_mode', '')} hvac fire healthcare".lower()
        for sa in ctx.specialist_assessments
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
        inspected_comparison_ids=[c["id"] for c in ctx.comparisons],
        inspected_schedule_ids=[s["id"] for s in ctx.schedules],
        inspected_standard_ids=[s["id"] for s in ctx.standards_library],
        inspected_assessment_ids=[a["id"] for a in ctx.specialist_assessments],
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
        "comparisons": [
            {
                "id": c["id"],
                "title": c["title"],
                "comparison_scope": c["comparison_scope"],
                "discipline": c["discipline"],
                "ai_draft_status": c["ai_draft_status"],
                "owner_decision_status": c["owner_decision_status"],
                "options_count": len(c.get("options_json") or []),
                "criteria_count": len(c.get("criteria_json") or []),
            }
            for c in ctx.comparisons
        ],
        "schedules": [
            {
                "id": s["id"],
                "title": s["title"],
                "discipline": s["discipline"],
                "is_baseline": s["is_baseline"],
                "ai_draft_status": s["ai_draft_status"],
                "activities_count": len(s.get("activities_json") or []),
            }
            for s in ctx.schedules
        ],
        "standards_library": [
            {
                "id": s["id"],
                "standard_number": s["standard_number"],
                "edition_year": s["edition_year"],
                "status": s["status"],
                "metadata_status": s["metadata_status"],
                "ai_suggestion_status": s["ai_suggestion_status"],
                "superseded_by_number": s.get("superseded_by_number"),
            }
            for s in ctx.standards_library
        ],
        "specialist_assessments": [
            {
                "id": a["id"],
                "domain": a["domain"],
                "workflow_mode": a["workflow_mode"],
                "title": a["title"],
                "checks_passed": a["checks_passed"],
                "blocked_missing_count": a["blocked_missing_count"],
                "failed_checks_count": a["failed_checks_count"],
                "standards_status": a["standards_status"],
            }
            for a in ctx.specialist_assessments
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
                    if d.get("comparison_id"):
                        formula_hits = 0
                        for r_i in range(1, ws.max_row + 1):
                            for c_i in range(1, ws.max_column + 1):
                                val = ws.cell(row=r_i, column=c_i).value
                                if isinstance(val, str) and (val.startswith("=ROUND(") or val.startswith("=SUM(")):
                                    formula_hits += 1
                        if formula_hits == 0:
                            findings.append(
                                QaCandidateFinding(
                                    check_category="arithmetic",
                                    discipline=d.get("discipline") or "multidisciplinary",
                                    severity="high",
                                    title="Exported comparison XLSX missing live Excel formulas",
                                    description=f"Comparison XLSX '{rel_xlsx}' contains no live =SUM/=ROUND formulas.",
                                    reference=str(rel_xlsx),
                                    corrective_action="Re-export comparison DOCX + PDF + live-formula XLSX via POST /api/comparisons/{id}/export.",
                                    deliverable_id=d["id"],
                                    task_id=d.get("task_id"),
                                )
                            )
                    elif d.get("schedule_id"):
                        sched_formula_hits = 0
                        for r_i in range(1, ws.max_row + 1):
                            for c_i in range(1, ws.max_column + 1):
                                val = ws.cell(row=r_i, column=c_i).value
                                if isinstance(val, str) and (
                                    val.startswith("=IF(") or val.startswith("=MAX(") or val.startswith("=COUNTIF(")
                                ):
                                    sched_formula_hits += 1
                        if sched_formula_hits == 0:
                            findings.append(
                                QaCandidateFinding(
                                    check_category="arithmetic",
                                    discipline=d.get("discipline") or "multidisciplinary",
                                    severity="high",
                                    title="Exported schedule XLSX missing live Excel formulas",
                                    description=f"Schedule XLSX '{rel_xlsx}' contains no live =IF/=COUNTIF formulas.",
                                    reference=str(rel_xlsx),
                                    corrective_action="Re-export schedule PDF + live-formula XLSX via POST /api/schedules/{id}/export.",
                                    deliverable_id=d["id"],
                                    task_id=d.get("task_id"),
                                )
                            )
                    elif not d.get("calculation_id"):
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

    # Recompute Step 15 technical comparison weighted Decimal matrices strictly from raw criteria/options
    deliv_by_cmp = {d["comparison_id"]: d["id"] for d in ctx.deliverables if d.get("comparison_id")}
    for cmp_row in ctx.comparisons:
        checked += 1
        cmp_deliv_id = deliv_by_cmp.get(cmp_row["id"])
        ref = f"Comparison {cmp_row['title']} ({cmp_row['id'][:8]})"
        try:
            crit_objs = [ComparisonCriterionIn.model_validate(c) for c in (cmp_row.get("criteria_json") or [])]
            opt_objs = [ComparisonOptionIn.model_validate(o) for o in (cmp_row.get("options_json") or [])]
            stored_mat = cmp_row.get("matrix_result_json") or {}
            life_yrs = stored_mat.get("lifecycle_years")
            recomp = recompute_comparison_matrix(
                criteria=crit_objs,
                options=opt_objs,
                language=cmp_row.get("language") or "en",
                lifecycle_years=life_yrs if isinstance(life_yrs, (int, float)) else None,
            )
            if not recomp.weights_sum_valid:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=cmp_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Technical comparison criteria weights do not sum to 100",
                        description=(
                            f"Comparison '{cmp_row['title']}' criteria weights sum to {recomp.total_weight:.4f}% "
                            "instead of strict 100.0000%."
                        ),
                        reference=ref,
                        corrective_action="Adjust criterion weights so all active weights sum strictly to 100%.",
                        deliverable_id=cmp_deliv_id,
                        task_id=cmp_row.get("task_id"),
                    )
                )

            mismatches: list[str] = []
            stored_tot_w = _to_decimal(stored_mat.get("total_weight"))
            recomp_tot_w = _to_decimal(recomp.total_weight)
            if stored_tot_w is None or recomp_tot_w is None or abs(stored_tot_w - recomp_tot_w) > Decimal("0.01"):
                mismatches.append(f"total_weight: stored={stored_mat.get('total_weight')}, expected={recomp.total_weight}")

            stored_opts = {
                str(o.get("option_id") or ""): o
                for o in (stored_mat.get("options") or [])
                if isinstance(o, dict)
            }
            for r_opt in recomp.options:
                s_opt = stored_opts.get(r_opt.option_id)
                if not s_opt:
                    mismatches.append(f"missing option {r_opt.option_id} in stored matrix")
                    continue
                s_score = _to_decimal(s_opt.get("total_weighted_score"))
                r_score = _to_decimal(r_opt.total_weighted_score)
                if s_score is None or r_score is None or abs(s_score - r_score) > Decimal("0.01"):
                    mismatches.append(
                        f"option '{r_opt.option_id}' total_weighted_score: stored={s_score}, expected={r_score}"
                    )
                if bool(s_opt.get("mandatory_passed")) != r_opt.mandatory_passed:
                    mismatches.append(
                        f"option '{r_opt.option_id}' mandatory_passed: stored={s_opt.get('mandatory_passed')}, expected={r_opt.mandatory_passed}"
                    )
                if int(s_opt.get("advisory_rank") or 0) != r_opt.advisory_rank:
                    mismatches.append(
                        f"option '{r_opt.option_id}' advisory_rank: stored={s_opt.get('advisory_rank')}, expected={r_opt.advisory_rank}"
                    )
                s_cells = {
                    str(c.get("criterion_id") or ""): c
                    for c in (s_opt.get("cells") or [])
                    if isinstance(c, dict)
                }
                for r_cell in r_opt.cells:
                    s_cell = s_cells.get(r_cell.criterion_id)
                    if not s_cell:
                        mismatches.append(f"{r_opt.option_id}.{r_cell.criterion_id} missing cell")
                        continue
                    sn = _to_decimal(s_cell.get("normalized_score"))
                    rn = _to_decimal(r_cell.normalized_score)
                    sw = _to_decimal(s_cell.get("weighted_score"))
                    rw = _to_decimal(r_cell.weighted_score)
                    if sn is None or rn is None or abs(sn - rn) > Decimal("0.01"):
                        mismatches.append(f"{r_opt.option_id}.{r_cell.criterion_id} norm={sn} vs {rn}")
                    if sw is None or rw is None or abs(sw - rw) > Decimal("0.01"):
                        mismatches.append(f"{r_opt.option_id}.{r_cell.criterion_id} weighted={sw} vs {rw}")

            if mismatches:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=cmp_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Technical comparison score arithmetic mismatch",
                        description=(
                            f"Comparison '{cmp_row['title']}' stored scores disagree with independent Decimal "
                            f"recomputation: {'; '.join(mismatches[:5])}."
                        ),
                        reference=ref,
                        corrective_action="Re-evaluate comparison deterministically via POST /api/projects/{id}/comparisons.",
                        deliverable_id=cmp_deliv_id,
                        task_id=cmp_row.get("task_id"),
                    )
                )
        except Exception as exc:
            findings.append(
                QaCandidateFinding(
                    check_category="arithmetic",
                    discipline=cmp_row.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Technical comparison failed deterministic Decimal re-evaluation",
                    description=f"Comparison '{cmp_row['title']}' failed QA recomputation: {exc}",
                    reference=ref,
                    corrective_action="Fix invalid comparison inputs or units and re-evaluate.",
                    deliverable_id=cmp_deliv_id,
                    task_id=cmp_row.get("task_id"),
                )
            )

    # Recompute Step 16 project schedules (date arithmetic, floats & critical path) independently
    deliv_by_sched = {d["schedule_id"]: d["id"] for d in ctx.deliverables if d.get("schedule_id")}
    sched_by_id = {s["id"]: s for s in ctx.schedules}
    for s_row in ctx.schedules:
        checked += 1
        s_deliv_id = deliv_by_sched.get(s_row["id"])
        s_ref = f"Schedule {s_row['title']} ({s_row['id'][:8]})"
        try:
            cal_in = WorkCalendarIn.model_validate(s_row.get("calendar_json") or {})
            wbs_in = [WbsItemIn.model_validate(w) for w in (s_row.get("wbs_items_json") or [])]
            acts_in = [
                ScheduleActivityIn.model_validate(
                    {
                        **a,
                        "source_ref": str(a.get("source_ref") or "").strip() or NOT_PROVIDED_LABEL,
                    }
                )
                for a in (s_row.get("activities_json") or [])
                if isinstance(a, dict)
            ]
            base_row = sched_by_id.get(s_row.get("baseline_schedule_id") or "")
            base_res_obj = (
                ScheduleResultOut.model_validate(base_row.get("schedule_result_json") or {})
                if base_row and isinstance(base_row.get("schedule_result_json"), dict)
                else None
            )
            recomp_sched = evaluate_project_schedule(
                start_date=s_row.get("start_date") or "",
                calendar=cal_in,
                wbs_items=wbs_in,
                activities=acts_in,
                baseline_result=base_res_obj,
                baseline_schedule_id=s_row.get("baseline_schedule_id"),
                baseline_title=base_row.get("title") if base_row else None,
                strict=False,
            )
            stored = s_row.get("schedule_result_json") or {}
            date_mismatches: list[str] = []
            cp_mismatches: list[str] = []

            if stored.get("effective_start_date") != recomp_sched.effective_start_date:
                date_mismatches.append(
                    f"effective_start_date: {stored.get('effective_start_date')} vs {recomp_sched.effective_start_date}"
                )
            if stored.get("project_finish_date") != recomp_sched.project_finish_date:
                date_mismatches.append(
                    f"project_finish_date: {stored.get('project_finish_date')} vs {recomp_sched.project_finish_date}"
                )
            if stored.get("total_duration_wd") != recomp_sched.total_duration_wd:
                date_mismatches.append(
                    f"total_duration_wd: {stored.get('total_duration_wd')} vs {recomp_sched.total_duration_wd}"
                )
            if bool(stored.get("critical_path_complete")) != recomp_sched.critical_path_complete:
                cp_mismatches.append(
                    f"critical_path_complete: {stored.get('critical_path_complete')} vs {recomp_sched.critical_path_complete}"
                )
            if list(stored.get("critical_path_ids") or []) != recomp_sched.critical_path_ids:
                cp_mismatches.append(
                    f"critical_path_ids: {stored.get('critical_path_ids')} vs {recomp_sched.critical_path_ids}"
                )

            stored_acts = {
                str(a.get("activity_id") or ""): a
                for a in (stored.get("activities") or [])
                if isinstance(a, dict)
            }
            for ra in recomp_sched.activities:
                sa = stored_acts.get(ra.activity_id)
                if not sa:
                    date_mismatches.append(f"missing activity {ra.activity_id} in stored result")
                    continue
                for fld in (
                    "early_start_wd",
                    "early_finish_wd",
                    "late_start_wd",
                    "late_finish_wd",
                    "total_float_wd",
                    "planned_start",
                    "planned_finish",
                    "finish_variance_wd",
                ):
                    if sa.get(fld) != getattr(ra, fld):
                        date_mismatches.append(f"{ra.activity_id}.{fld}: {sa.get(fld)} vs {getattr(ra, fld)}")
                if bool(sa.get("is_critical")) != ra.is_critical:
                    cp_mismatches.append(f"{ra.activity_id}.is_critical: {sa.get('is_critical')} vs {ra.is_critical}")

            if date_mismatches:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=s_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Project schedule date or float arithmetic mismatch",
                        description=(
                            f"Schedule '{s_row['title']}' stored working dates or float values disagree with "
                            f"independent CPM recomputation: {'; '.join(date_mismatches[:5])}."
                        ),
                        reference=s_ref,
                        corrective_action="Re-evaluate schedule via POST /api/projects/{id}/schedules to restore exact CPM arithmetic.",
                        deliverable_id=s_deliv_id,
                        task_id=s_row.get("task_id"),
                    )
                )
            if cp_mismatches:
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=s_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Project schedule critical path mismatch",
                        description=(
                            f"Schedule '{s_row['title']}' stored critical path disagrees with independent CPM "
                            f"recomputation: {'; '.join(cp_mismatches[:5])}."
                        ),
                        reference=s_ref,
                        corrective_action="Re-evaluate critical path deterministically from owner-supplied durations.",
                        deliverable_id=s_deliv_id,
                        task_id=s_row.get("task_id"),
                    )
                )
        except Exception as exc:
            findings.append(
                QaCandidateFinding(
                    check_category="arithmetic",
                    discipline=s_row.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Project schedule failed deterministic CPM re-evaluation",
                    description=f"Schedule '{s_row['title']}' failed QA CPM recomputation: {exc}",
                    reference=s_ref,
                    corrective_action="Fix invalid calendar or activity structure and re-evaluate schedule.",
                    deliverable_id=s_deliv_id,
                    task_id=s_row.get("task_id"),
                )
            )

    # Recompute Step 18 HVAC / Fire / Healthcare preflight assessments independently
    deliv_by_assess = {
        d["assessment_id"]: d["id"]
        for d in ctx.deliverables
        if d.get("assessment_id") and d.get("format") == "xlsx"
    }
    for a_row in ctx.specialist_assessments:
        checked += 1
        a_deliv_id = deliv_by_assess.get(a_row["id"])
        a_ref = f"Specialist {a_row['domain'].upper()} / {a_row['title']} ({a_row['id'][:8]})"
        try:
            re_ev = evaluate_specialist_assessment(
                domain=a_row["domain"],
                workflow_mode=a_row["workflow_mode"],
                inputs=a_row.get("inputs_json") or {},
            )
            stored_res = a_row.get("results_json") or {}
            if (
                bool(a_row.get("checks_passed")) != re_ev.checks_passed
                or int(a_row.get("failed_checks_count") or 0) != re_ev.failed_checks_count
                or int(a_row.get("blocked_missing_count") or 0) != re_ev.blocked_missing_count
                or stored_res.get("metrics") != re_ev.metrics
                or stored_res.get("check_rows") != re_ev.check_rows
            ):
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=a_row["domain"],
                        severity="critical",
                        title="Specialist assessment arithmetic or verdict mismatch",
                        description=(
                            f"Specialist {a_row['domain']} assessment '{a_row['title']}' stored results/verdict "
                            "disagree with independent deterministic recomputation."
                        ),
                        reference=a_ref,
                        corrective_action="Re-evaluate via PATCH /api/specialist-assessments/{id} cleanly.",
                        deliverable_id=a_deliv_id,
                        task_id=a_row.get("task_id"),
                    )
                )
            elif re_ev.failed_checks_count > 0:
                failed_labels = [
                    f"{c.get('item_id')}: {c.get('label')} (actual={c.get('actual')}, expected={c.get('expected')})"
                    for c in re_ev.check_rows
                    if "FAIL" in str(c.get("status") or "")
                ]
                findings.append(
                    QaCandidateFinding(
                        check_category="arithmetic",
                        discipline=a_row["domain"],
                        severity="high",
                        title=f"Specialist {a_row['domain'].upper()} engineering check failed",
                        description=(
                            f"Assessment '{a_row['title']}' has {re_ev.failed_checks_count} failed engineering check(s): "
                            f"{'; '.join(failed_labels[:5])}."
                        ),
                        reference=a_ref,
                        corrective_action="Correct engineering design/software inputs and re-run Step 18 preflight checks.",
                        deliverable_id=a_deliv_id,
                        task_id=a_row.get("task_id"),
                    )
                )
        except SpecialistInputError as exc:
            findings.append(
                QaCandidateFinding(
                    check_category="arithmetic",
                    discipline=a_row["domain"],
                    severity="high",
                    title="Invalid specialist assessment input payload",
                    description=f"Assessment '{a_row['title']}' failed deterministic evaluation: {exc}",
                    reference=a_ref,
                    corrective_action="Supply valid domain inputs cleanly.",
                    deliverable_id=a_deliv_id,
                    task_id=a_row.get("task_id"),
                )
            )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="arithmetic",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Recomputed {checked} BOQ/XLSX/drawing/calculation/comparison/schedule arithmetic target(s); found {failed_cnt} issue(s).",
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

    # Step 15 technical comparison unit conversion & mismatch checks
    deliv_by_cmp_u = {d["comparison_id"]: d["id"] for d in ctx.deliverables if d.get("comparison_id")}
    for cmp_row in ctx.comparisons:
        mat = cmp_row.get("matrix_result_json") or {}
        cmp_deliv_id = deliv_by_cmp_u.get(cmp_row["id"])
        for opt in mat.get("options") or []:
            if not isinstance(opt, dict):
                continue
            for cell in opt.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                checked += 1
                if cell.get("unit_status") == "flagged_mismatch":
                    findings.append(
                        QaCandidateFinding(
                            check_category="unit",
                            discipline=cmp_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Mixed or incompatible units in technical comparison",
                            description=(
                                f"Comparison '{cmp_row['title']}', option '{opt.get('name')}', criterion "
                                f"'{cell.get('label')}' flagged a unit/currency mismatch: "
                                f"{cell.get('conversion_note') or (str(cell.get('raw_unit')) + ' vs ' + str(cell.get('target_unit')))}"
                            ),
                            reference=f"Comparison {cmp_row['title']} / {opt.get('option_id')}.{cell.get('criterion_id')}",
                            corrective_action="Standardize option metrics to explicit compatible units or an owner-verified FX rate.",
                            deliverable_id=cmp_deliv_id,
                            task_id=cmp_row.get("task_id"),
                        )
                    )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="unit",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Checked {checked} BOQ/drawing/CAD/calculation/comparison units; found {failed_cnt} unit issue(s).",
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
    reviewed_rs_text = " ".join(
        f"{rs.get('source_name') or ''} {rs.get('url') or ''} {rs.get('relevant_info') or ''}"
        for rs in reviewed_rs_by_id.values()
    ).lower()
    lib_std_corpus = " ".join(
        str(s.get("standard_number") or "").strip() for s in ctx.standards_library
    ).lower()
    reviewed_corpus = f"{reviewed_rs_text} {boq_ref_corpus} {lib_std_corpus}".strip()
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

    # 5. Check Step 15 technical comparisons: every non-missing metric keeps valid provenance (BOQ/Spec/Calc/Reviewed Source/Owner)
    deliv_by_cmp_r = {d["comparison_id"]: d["id"] for d in ctx.deliverables if d.get("comparison_id")}
    valid_cmp_boq_ids = {str(it["id"]) for b in ctx.boq_sheets for it in b["items"]}
    valid_cmp_spec_ids = {str(s["id"]) for s in ctx.specifications}
    valid_cmp_calc_ids = {str(c["id"]) for c in ctx.calculations}
    cmp_url_re = re.compile(r"https?://[^\s,;\"')>\]]+", re.IGNORECASE)

    for cmp_row in ctx.comparisons:
        cmp_deliv_id = deliv_by_cmp_r.get(cmp_row["id"])
        cmp_ref = f"Comparison {cmp_row['title']} ({cmp_row['id'][:8]})"
        crit_cat_by_id = {
            str(c.get("criterion_id") or ""): str(c.get("category") or "")
            for c in (cmp_row.get("criteria_json") or [])
            if isinstance(c, dict)
        }
        mat = cmp_row.get("matrix_result_json") or {}
        for opt in mat.get("options") or []:
            if not isinstance(opt, dict):
                continue
            for cell in opt.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                checked += 1
                is_miss = bool(cell.get("is_missing"))
                src_kind = str(cell.get("source_kind") or "")
                src_ref = str(cell.get("source_ref") or "").strip()
                cid = str(cell.get("criterion_id") or "")
                c_ref = f"{cmp_ref} / {opt.get('option_id')}.{cid}"

                if not is_miss and (not src_ref or src_ref.lower() == NOT_PROVIDED_LABEL):
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=cmp_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Unsourced metric value in technical comparison",
                            description=(
                                f"Comparison '{cmp_row['title']}' option '{opt.get('name')}' metric "
                                f"'{cell.get('label')}' carries value '{cell.get('display_value')}' without a source reference."
                            ),
                            reference=c_ref,
                            corrective_action="Attach a traceable BOQ item, specification, calculation, reviewed source, or owner quote reference.",
                            deliverable_id=cmp_deliv_id,
                            task_id=cmp_row.get("task_id"),
                        )
                    )

                if src_kind == "boq_item":
                    bid = str(cell.get("boq_item_id") or "")
                    if not bid or bid not in valid_cmp_boq_ids:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=cmp_row.get("discipline") or "multidisciplinary",
                                severity="high",
                                title="Comparison cell traces to missing BOQ item",
                                description=f"Cell {opt.get('option_id')}.{cid} references invalid/missing BOQ item '{bid}'.",
                                reference=c_ref,
                                corrective_action="Link an active BOQ item belonging to this project.",
                                deliverable_id=cmp_deliv_id,
                                task_id=cmp_row.get("task_id"),
                            )
                        )
                elif src_kind == "specification":
                    sid = str(cell.get("specification_id") or "")
                    if not sid or sid not in valid_cmp_spec_ids:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=cmp_row.get("discipline") or "multidisciplinary",
                                severity="high",
                                title="Comparison cell traces to missing Specification",
                                description=f"Cell {opt.get('option_id')}.{cid} references missing Specification '{sid}'.",
                                reference=c_ref,
                                corrective_action="Link an active Technical Specification belonging to this project.",
                                deliverable_id=cmp_deliv_id,
                                task_id=cmp_row.get("task_id"),
                            )
                        )
                elif src_kind == "calculation":
                    calc_id = str(cell.get("calculation_id") or "")
                    if calc_id:
                        if calc_id not in valid_cmp_calc_ids:
                            findings.append(
                                QaCandidateFinding(
                                    check_category="reference",
                                    discipline=cmp_row.get("discipline") or "multidisciplinary",
                                    severity="high",
                                    title="Comparison cell traces to missing Calculation",
                                    description=f"Cell {opt.get('option_id')}.{cid} references missing Calculation '{calc_id}'.",
                                    reference=c_ref,
                                    corrective_action="Link an active Step 13 Calculation belonging to this project.",
                                    deliverable_id=cmp_deliv_id,
                                    task_id=cmp_row.get("task_id"),
                                )
                            )
                    elif crit_cat_by_id.get(cid) != "lifecycle_cost":
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=cmp_row.get("discipline") or "multidisciplinary",
                                severity="high",
                                title="Comparison calculation reference missing calculation_id",
                                description=f"Cell {opt.get('option_id')}.{cid} sets source_kind='calculation' without calculation_id.",
                                reference=c_ref,
                                corrective_action="Link the source Step 13 calculation ID.",
                                deliverable_id=cmp_deliv_id,
                                task_id=cmp_row.get("task_id"),
                            )
                        )
                elif src_kind == "research_source":
                    rsid = str(cell.get("research_source_id") or "")
                    if not rsid or rsid not in reviewed_rs_by_id:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=cmp_row.get("discipline") or "multidisciplinary",
                                severity="high",
                                title="Comparison cell cites unreviewed or missing ResearchSource",
                                description=f"Cell {opt.get('option_id')}.{cid} traces to unreviewed/missing source '{rsid}'.",
                                reference=c_ref,
                                corrective_action="Mark source reviewed in ResearchSource log or replace with a reviewed source.",
                                deliverable_id=cmp_deliv_id,
                                task_id=cmp_row.get("task_id"),
                            )
                        )

                if not is_miss and src_ref:
                    for url_hit in cmp_url_re.findall(src_ref):
                        if not _url_is_reviewed(url_hit):
                            findings.append(
                                QaCandidateFinding(
                                    check_category="reference",
                                    discipline=cmp_row.get("discipline") or "multidisciplinary",
                                    severity="high",
                                    title="Comparison cell cites unreviewed external URL",
                                    description=f"Cell {opt.get('option_id')}.{cid} embeds unreviewed URL '{url_hit}'.",
                                    reference=c_ref,
                                    corrective_action="Verify URL in ResearchSource log before citing it in technical comparisons.",
                                    deliverable_id=cmp_deliv_id,
                                    task_id=cmp_row.get("task_id"),
                                )
                            )

    # 6. Check Step 16 project schedules: activities & calendars must trace to BOQ/Spec/Calc/Reviewed Source/Owner
    deliv_by_sched_r = {d["schedule_id"]: d["id"] for d in ctx.deliverables if d.get("schedule_id")}
    sched_url_re = re.compile(r"https?://[^\s,;\"')>\]]+", re.IGNORECASE)
    for s_row in ctx.schedules:
        s_deliv_id = deliv_by_sched_r.get(s_row["id"])
        s_ref = f"Schedule {s_row['title']} ({s_row['id'][:8]})"
        cal_dict = s_row.get("calendar_json") or {}
        for url_hit in sched_url_re.findall(str(cal_dict.get("source_ref") or "")):
            checked += 1
            if not _url_is_reviewed(url_hit):
                findings.append(
                    QaCandidateFinding(
                        check_category="reference",
                        discipline=s_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Schedule calendar cites unreviewed URL",
                        description=f"Schedule '{s_row['title']}' calendar source_ref cites unreviewed URL '{url_hit}'.",
                        reference=s_ref,
                        corrective_action="Verify source in ResearchSource log before citing URL in schedule.",
                        deliverable_id=s_deliv_id,
                        task_id=s_row.get("task_id"),
                    )
                )

        for act in s_row.get("activities_json") or []:
            if not isinstance(act, dict):
                continue
            checked += 1
            aid = str(act.get("activity_id") or "")
            src_kind = str(act.get("source_kind") or "")
            src_ref = str(act.get("source_ref") or "").strip()
            a_ref = f"{s_ref} / {aid}"

            if not src_ref or src_ref.lower() == NOT_PROVIDED_LABEL:
                findings.append(
                    QaCandidateFinding(
                        check_category="reference",
                        discipline=s_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Project schedule activity missing source reference",
                        description=(
                            f"Schedule '{s_row['title']}' activity '{aid}' ('{act.get('name')}') has no "
                            "BOQ/specification/calculation/owner source attribution."
                        ),
                        reference=a_ref,
                        corrective_action="Link every activity duration/quantity to an active BOQ item, spec, calc, reviewed source, or explicit owner quote.",
                        deliverable_id=s_deliv_id,
                        task_id=s_row.get("task_id"),
                    )
                )

            if src_kind == "boq_item":
                bid = str(act.get("boq_item_id") or "")
                if not bid or bid not in valid_cmp_boq_ids:
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=s_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Schedule activity traces to missing BOQ item",
                            description=f"Activity '{aid}' references invalid/missing BOQ item '{bid}'.",
                            reference=a_ref,
                            corrective_action="Link an active BOQ item from this project.",
                            deliverable_id=s_deliv_id,
                            task_id=s_row.get("task_id"),
                        )
                    )
            elif src_kind == "specification":
                spid = str(act.get("specification_id") or "")
                if not spid or spid not in valid_cmp_spec_ids:
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=s_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Schedule activity traces to missing Specification",
                            description=f"Activity '{aid}' references missing Specification '{spid}'.",
                            reference=a_ref,
                            corrective_action="Link an active Specification from this project.",
                            deliverable_id=s_deliv_id,
                            task_id=s_row.get("task_id"),
                        )
                    )
            elif src_kind == "calculation":
                cid_s = str(act.get("calculation_id") or "")
                if not cid_s or cid_s not in valid_cmp_calc_ids:
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=s_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Schedule activity traces to missing Calculation",
                            description=f"Activity '{aid}' references missing Calculation '{cid_s}'.",
                            reference=a_ref,
                            corrective_action="Link an active Step 13 Calculation from this project.",
                            deliverable_id=s_deliv_id,
                            task_id=s_row.get("task_id"),
                        )
                    )
            elif src_kind == "research_source":
                rsid = str(act.get("research_source_id") or "")
                if not rsid or rsid not in reviewed_rs_by_id:
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=s_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Schedule activity cites unreviewed or missing ResearchSource",
                            description=f"Activity '{aid}' references unreviewed/missing ResearchSource '{rsid}'.",
                            reference=a_ref,
                            corrective_action="Verify source in ResearchSource log or replace with an owner-verified basis.",
                            deliverable_id=s_deliv_id,
                            task_id=s_row.get("task_id"),
                        )
                    )

            for url_hit in sched_url_re.findall(src_ref):
                if not _url_is_reviewed(url_hit):
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=s_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Schedule activity cites unreviewed external URL",
                            description=f"Activity '{aid}' embeds unreviewed URL '{url_hit}'.",
                            reference=a_ref,
                            corrective_action="Verify URL in ResearchSource log before referencing it in schedules.",
                            deliverable_id=s_deliv_id,
                            task_id=s_row.get("task_id"),
                        )
                    )

    # 7. Check Step 17 Standards Library: flag cited superseded/withdrawn/unknown/unconfirmed standards & codes outside Library + reviewed ResearchSource log
    deliv_by_id_lookup = {
        "specification": deliv_by_spec,
        "calculation": deliv_by_calc,
        "comparison": deliv_by_cmp_r,
        "review_report": deliv_by_rep,
        "schedule": deliv_by_sched_r,
    }
    task_id_by_art: dict[tuple[str, str], str | None] = {}
    for _sp in ctx.specifications:
        task_id_by_art[("specification", _sp["id"])] = _sp.get("task_id")
    for _ca in ctx.calculations:
        task_id_by_art[("calculation", _ca["id"])] = _ca.get("task_id")
    for _cm in ctx.comparisons:
        task_id_by_art[("comparison", _cm["id"])] = _cm.get("task_id")
    for _rp in ctx.review_reports:
        task_id_by_art[("review_report", _rp["id"])] = _rp.get("task_id")
    for _sc in ctx.schedules:
        task_id_by_art[("schedule", _sc["id"])] = _sc.get("task_id")

    for std_doc in ctx.standards_library:
        checked += 1
        hits, _ = find_citations_for_standard(
            std_doc=std_doc,
            specifications=ctx.specifications,
            calculations=ctx.calculations,
            comparisons=ctx.comparisons,
            review_reports=ctx.review_reports,
            schedules=ctx.schedules,
        )
        if not hits:
            continue
        std_num = str(std_doc.get("standard_number") or "")
        std_status = str(std_doc.get("status") or "unknown")
        ed_year = str(std_doc.get("edition_year") or "unknown").strip().lower()
        meta_status = str(std_doc.get("metadata_status") or "")
        ai_status = str(std_doc.get("ai_suggestion_status") or "")

        defective_reasons: list[str] = []
        if std_status == "withdrawn":
            defective_reasons.append("status is 'withdrawn'")
        elif std_status == "superseded":
            rep_info = (
                f" (superseded by {std_doc['superseded_by_number']})"
                if std_doc.get("superseded_by_number")
                else ""
            )
            defective_reasons.append(f"status is 'superseded'{rep_info}")
        elif std_status == "unknown" or not ed_year or ed_year == "unknown":
            defective_reasons.append(
                f"edition/status is unknown or unverified (status={std_status}, edition={std_doc.get('edition_year') or 'unknown'})"
            )
        if meta_status == "unconfirmed" or ai_status == "unverified":
            defective_reasons.append(
                f"uploaded/AI standard metadata awaits owner confirmation ({meta_status}/{ai_status})"
            )

        if defective_reasons:
            severity_val: IssueSeverity = "critical" if std_status in {"withdrawn", "superseded"} else "high"
            for hit in hits:
                checked += 1
                findings.append(
                    QaCandidateFinding(
                        check_category="reference",
                        discipline="multidisciplinary",
                        severity=severity_val,
                        title=f"Deliverable cites {std_status} or unverified standard '{std_num}'",
                        description=(
                            f"{hit.module} '{hit.artifact_title}' ({hit.location}) cites standard '{std_num}', "
                            f"which is flagged because: {'; '.join(defective_reasons)}."
                        ),
                        reference=f"{std_num} -> {hit.artifact_title} ({hit.location})",
                        corrective_action=(
                            f"Replace '{std_num}' with replacement standard '{std_doc['superseded_by_number']}'"
                            if std_doc.get("superseded_by_number")
                            else f"Replace or confirm '{std_num}' in the Standards Library before relying on this deliverable."
                        ),
                        deliverable_id=deliv_by_id_lookup.get(hit.module, {}).get(hit.artifact_id),
                        task_id=task_id_by_art.get((hit.module, hit.artifact_id)),
                    )
                )

    std_ground_corpus = f"{reviewed_rs_text} {lib_std_corpus}".strip()

    def _std_code_is_grounded(code: str) -> bool:
        code_norm = code.strip().lower()
        if not code_norm:
            return True
        return bool(
            std_ground_corpus
            and re.search(rf"(?<![a-z0-9]){re.escape(code_norm)}(?![a-z0-9])", std_ground_corpus)
        )

    def _emit_unregistered_std_findings(
        *,
        text_blob: str,
        module_name: str,
        art_id: str,
        art_title: str,
        location: str,
        discipline_val: str,
        task_id_val: str | None,
        extra_allow_corpus: str = "",
    ) -> None:
        nonlocal checked
        if not text_blob:
            return
        seen_codes: set[str] = set()
        for raw_code in STANDARD_CODE_DETECT_RE.findall(text_blob):
            code_clean = " ".join(raw_code.split())
            code_key = code_clean.lower()
            if code_key in seen_codes:
                continue
            seen_codes.add(code_key)
            checked += 1
            if _std_code_is_grounded(code_clean):
                continue
            if extra_allow_corpus and re.search(
                rf"(?<![a-z0-9]){re.escape(code_key)}(?![a-z0-9])",
                extra_allow_corpus.lower(),
            ):
                continue
            findings.append(
                QaCandidateFinding(
                    check_category="reference",
                    discipline=discipline_val or "multidisciplinary",
                    severity="high",
                    title="Deliverable cites standard missing from Standards Library and reviewed source log",
                    description=(
                        f"{module_name} '{art_title}' ({location}) cites standard code '{code_clean}', "
                        "which is neither registered in the project Standards Library nor verified in the ResearchSource log."
                    ),
                    reference=f"{art_title} ({location}) / {code_clean}",
                    corrective_action=(
                        f"Register/upload '{code_clean}' in the Standards Library (owner-supplied) or add a verified ResearchSource log entry."
                    ),
                    deliverable_id=deliv_by_id_lookup.get(module_name, {}).get(art_id),
                    task_id=task_id_val,
                )
            )

    for sp in ctx.specifications:
        for sec in sp.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            sec_code = str(sec.get("section_code") or "SPEC")
            stds_blob = " ".join(
                f"{st.get('source_name', '')} {st.get('citation_text', '')}"
                for st in (sec.get("standards") or [])
                if isinstance(st, dict) and st.get("status") != "no_verified_standard_on_file"
            )
            _emit_unregistered_std_findings(
                text_blob=stds_blob,
                module_name="specification",
                art_id=sp["id"],
                art_title=sp["title"],
                location=f"{sec_code} / standards",
                discipline_val=str(sec.get("discipline") or sp.get("discipline") or "multidisciplinary"),
                task_id_val=sp.get("task_id"),
                extra_allow_corpus=boq_ref_corpus,
            )

    for calc in ctx.calculations:
        c_blob = " ".join(
            [str(calc.get("references_text") or "")]
            + [
                f"{r.get('source_name', '')} {r.get('source_ref', '')} {r.get('notes', '')}"
                for r in (calc.get("references_json") or [])
                if isinstance(r, dict)
            ]
        )
        _emit_unregistered_std_findings(
            text_blob=c_blob,
            module_name="calculation",
            art_id=calc["id"],
            art_title=calc["title"],
            location="references",
            discipline_val=str(calc.get("discipline") or "multidisciplinary"),
            task_id_val=calc.get("task_id"),
        )

    for cmp_row in ctx.comparisons:
        cmp_blob = " ".join(
            [str(cr.get("source_ref") or "") for cr in (cmp_row.get("criteria_json") or []) if isinstance(cr, dict)]
            + [
                str(cell.get("source_ref") or "")
                for opt in (cmp_row.get("options_json") or [])
                if isinstance(opt, dict)
                for cell in (opt.get("cells") or [])
                if isinstance(cell, dict)
            ]
        )
        _emit_unregistered_std_findings(
            text_blob=cmp_blob,
            module_name="comparison",
            art_id=cmp_row["id"],
            art_title=cmp_row["title"],
            location="criteria_and_cells",
            discipline_val=str(cmp_row.get("discipline") or "multidisciplinary"),
            task_id_val=cmp_row.get("task_id"),
        )

    for rep in ctx.review_reports:
        rep_blob = json.dumps(
            {
                "findings": rep.get("findings") or [],
                "verified_facts": rep.get("verified_facts") or [],
                "source_registry": rep.get("source_registry") or [],
            },
            ensure_ascii=False,
        )
        _emit_unregistered_std_findings(
            text_blob=rep_blob,
            module_name="review_report",
            art_id=rep["id"],
            art_title=rep["title"],
            location="report_body",
            discipline_val=str(rep.get("discipline") or "multidisciplinary"),
            task_id_val=rep.get("task_id"),
        )

    for s_row in ctx.schedules:
        sc_blob = " ".join(
            [str((s_row.get("calendar_json") or {}).get("source_ref") or "")]
            + [str(a.get("source_ref") or "") for a in (s_row.get("activities_json") or []) if isinstance(a, dict)]
        )
        _emit_unregistered_std_findings(
            text_blob=sc_blob,
            module_name="schedule",
            art_id=s_row["id"],
            art_title=s_row["title"],
            location="activities",
            discipline_val=str(s_row.get("discipline") or "multidisciplinary"),
            task_id_val=s_row.get("task_id"),
        )

    # 8. Check Step 18 specialist assessments: WHO/FGI/NFPA/ASHRAE/code references allowed ONLY when verified in Standards Library or reviewed ResearchSource log
    deliv_by_assess_r = {d["assessment_id"]: d["id"] for d in ctx.deliverables if d.get("assessment_id")}
    std_lib_by_id_r = {s["id"]: s for s in ctx.standards_library}
    healthcare_code_re = re.compile(r"\b(?:WHO|FGI|NFPA|ASHRAE)\b")
    for a_row in ctx.specialist_assessments:
        a_deliv_id = deliv_by_assess_r.get(a_row["id"])
        a_ref = f"Specialist {a_row['domain'].upper()} / {a_row['title']} ({a_row['id'][:8]})"
        refs_list = a_row.get("references_json") or []
        if not refs_list:
            checked += 1
            findings.append(
                QaCandidateFinding(
                    check_category="reference",
                    discipline=a_row["domain"],
                    severity="high",
                    title="Specialist assessment missing standard or fallback declaration",
                    description=(
                        f"Assessment '{a_row['title']}' has no references_json entries and fails to declare "
                        f"'{SPECIALIST_NO_STD_LABEL}'."
                    ),
                    reference=a_ref,
                    corrective_action=f"Bind a verified Standards Library / ResearchSource entry or declare '{SPECIALIST_NO_STD_LABEL}'.",
                    deliverable_id=a_deliv_id,
                    task_id=a_row.get("task_id"),
                )
            )

        for r_item in refs_list:
            if not isinstance(r_item, dict):
                continue
            checked += 1
            skind = str(r_item.get("source_kind") or "")
            if skind == "no_verified_standard_on_file":
                if SPECIALIST_NO_STD_LABEL not in str(r_item.get("code_or_source_name") or "").lower() and SPECIALIST_NO_STD_LABEL not in str(r_item.get("verification_label") or "").lower():
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=a_row["domain"],
                            severity="high",
                            title="Missing unverified-standard disclaimer in specialist assessment",
                            description=f"Assessment '{a_row['title']}' omits required '{SPECIALIST_NO_STD_LABEL}' notice.",
                            reference=a_ref,
                            corrective_action=f"State exact notice '{SPECIALIST_NO_STD_LABEL}'.",
                            deliverable_id=a_deliv_id,
                            task_id=a_row.get("task_id"),
                        )
                    )
            elif skind == "verified_source_log":
                rsid = str(r_item.get("research_source_id") or "")
                if not rsid or rsid not in reviewed_rs_by_id:
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=a_row["domain"],
                            severity="high",
                            title="Specialist assessment cites unreviewed or missing ResearchSource",
                            description=f"Assessment '{a_row['title']}' references unreviewed/missing ResearchSource '{rsid}'.",
                            reference=a_ref,
                            corrective_action="Bind only a reviewed accessible/owner-provided ResearchSource.",
                            deliverable_id=a_deliv_id,
                            task_id=a_row.get("task_id"),
                        )
                    )
            elif skind == "standard_library":
                stid = str(r_item.get("standard_library_id") or "")
                st_doc = std_lib_by_id_r.get(stid)
                if st_doc is None:
                    findings.append(
                        QaCandidateFinding(
                            check_category="reference",
                            discipline=a_row["domain"],
                            severity="high",
                            title="Specialist assessment cites missing Standards Library entry",
                            description=f"Assessment '{a_row['title']}' links standard_library_id '{stid}' not present in Standards Library.",
                            reference=a_ref,
                            corrective_action="Register and confirm the standard in Step 17 Standards Library first.",
                            deliverable_id=a_deliv_id,
                            task_id=a_row.get("task_id"),
                        )
                    )
                else:
                    st_status = str(st_doc.get("status") or "unknown")
                    ed_y = str(st_doc.get("edition_year") or "unknown").strip().lower()
                    unconf = st_doc.get("metadata_status") == "unconfirmed" or st_doc.get("metadata_status") in {"unverified_suggestion", "unverified_ai_suggestion"} or st_doc.get("ai_suggestion_status") == "unverified_ai_suggestion"
                    if st_status != "current" or not ed_y or ed_y == "unknown" or unconf:
                        findings.append(
                            QaCandidateFinding(
                                check_category="reference",
                                discipline=a_row["domain"],
                                severity="critical" if st_status in {"superseded", "withdrawn"} else "high",
                                title=f"Specialist assessment cites {st_status} or unconfirmed standard '{st_doc['standard_number']}'",
                                description=f"Assessment '{a_row['title']}' depends on non-current/unconfirmed standard '{st_doc['standard_number']}'.",
                                reference=a_ref,
                                corrective_action="Replace with a confirmed current edition in Standards Library.",
                                deliverable_id=a_deliv_id,
                                task_id=a_row.get("task_id"),
                            )
                        )

        # Scan inputs + references + summary for unverified WHO/FGI/NFPA/ASHRAE/SYN codes not grounded in Library or reviewed ResearchSource
        assess_text_blob = json.dumps(
            {
                "inputs": a_row.get("inputs_json") or {},
                "references": refs_list,
                "summary": a_row.get("summary") or "",
            },
            ensure_ascii=False,
        )
        _emit_unregistered_std_findings(
            text_blob=assess_text_blob,
            module_name="specialist",
            art_id=a_row["id"],
            art_title=a_row["title"],
            location="inputs_and_references",
            discipline_val=a_row["domain"],
            task_id_val=a_row.get("task_id"),
        )
        for agency_hit in set(healthcare_code_re.findall(assess_text_blob)):
            checked += 1
            if not _std_code_is_grounded(agency_hit):
                findings.append(
                    QaCandidateFinding(
                        check_category="reference",
                        discipline=a_row["domain"],
                        severity="high",
                        title=f"Specialist assessment cites unverified code/guidance '{agency_hit}'",
                        description=(
                            f"Assessment '{a_row['title']}' mentions '{agency_hit}' which is neither registered as a verified "
                            "standard in Standards Library nor verified in the ResearchSource log."
                        ),
                        reference=f"{a_ref} / {agency_hit}",
                        corrective_action=f"Remove unverified '{agency_hit}' citation or add it via Standards Library / reviewed ResearchSource.",
                        deliverable_id=a_deliv_id,
                        task_id=a_row.get("task_id"),
                    )
                )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="reference",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Verified {checked} report/BOQ/calculation/specification/comparison/schedule source & drawing references against project logs; found {failed_cnt} issue(s).",
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

    # 5. Check Step 15 technical comparisons: missing mandatory values ('not provided') & unapproved AI drafts
    deliv_by_cmp_c = {d["comparison_id"]: d["id"] for d in ctx.deliverables if d.get("comparison_id")}
    for cmp_row in ctx.comparisons:
        checked += 1
        cmp_deliv_id = deliv_by_cmp_c.get(cmp_row["id"])
        cmp_ref = f"Comparison {cmp_row['title']} ({cmp_row['id'][:8]})"

        if cmp_row.get("ai_draft_status") == "unverified_ai_draft":
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=cmp_row.get("discipline") or "multidisciplinary",
                    severity="medium",
                    title="AI-drafted comparison summary pending owner approval",
                    description=(
                        f"Technical comparison '{cmp_row['title']}' includes an executive summary tagged "
                        "'unverified_ai_draft' that has not yet been approved by the owner."
                    ),
                    reference=cmp_ref,
                    corrective_action="Review summary and record owner decision/approval via POST /api/comparisons/{id}/decide.",
                    deliverable_id=cmp_deliv_id,
                    task_id=cmp_row.get("task_id"),
                )
            )

        mat = cmp_row.get("matrix_result_json") or {}
        for opt in mat.get("options") or []:
            if not isinstance(opt, dict):
                continue
            for cell in opt.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                if bool(cell.get("is_mandatory")) and bool(cell.get("is_missing")):
                    checked += 1
                    findings.append(
                        QaCandidateFinding(
                            check_category="schedule_consistency",
                            discipline=cmp_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Missing mandatory criterion value ('not provided') in technical comparison",
                            description=(
                                f"Comparison '{cmp_row['title']}', option '{opt.get('name')}', mandatory criterion "
                                f"'{cell.get('label')}' is '{NOT_PROVIDED_LABEL}'."
                            ),
                            reference=f"{cmp_ref} / {opt.get('option_id')}.{cell.get('criterion_id')}",
                            corrective_action="Obtain verified value from vendor submittal, BOQ, calculation, or owner input, or disqualify option explicitly.",
                            deliverable_id=cmp_deliv_id,
                            task_id=cmp_row.get("task_id"),
                        )
                    )

    # 6. Check Step 16 project schedules: dependency cycles, orphan tasks/WBS, missing durations ('not provided'), unapproved AI drafts
    deliv_by_sched_c = {d["schedule_id"]: d["id"] for d in ctx.deliverables if d.get("schedule_id")}
    for s_row in ctx.schedules:
        checked += 1
        s_deliv_id = deliv_by_sched_c.get(s_row["id"])
        s_ref = f"Schedule {s_row['title']} ({s_row['id'][:8]})"

        if s_row.get("ai_draft_status") == "unverified_ai_draft":
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=s_row.get("discipline") or "multidisciplinary",
                    severity="medium",
                    title="AI-drafted schedule summary pending owner approval",
                    description=(
                        f"Schedule '{s_row['title']}' includes a narrative tagged 'unverified_ai_draft' "
                        "pending owner approval."
                    ),
                    reference=s_ref,
                    corrective_action="Review schedule narrative and approve via POST /api/schedules/{id}/approve.",
                    deliverable_id=s_deliv_id,
                    task_id=s_row.get("task_id"),
                )
            )

        try:
            wbs_in = [WbsItemIn.model_validate(w) for w in (s_row.get("wbs_items_json") or [])]
            acts_in = [
                ScheduleActivityIn.model_validate(
                    {
                        **a,
                        "source_ref": str(a.get("source_ref") or "").strip() or NOT_PROVIDED_LABEL,
                    }
                )
                for a in (s_row.get("activities_json") or [])
                if isinstance(a, dict)
            ]
            dup_errs, orphan_flags, cycle_nodes, _, _, _ = _detect_graph_issues(
                wbs_items=wbs_in,
                activities=acts_in,
            )
            if cycle_nodes:
                findings.append(
                    QaCandidateFinding(
                        check_category="schedule_consistency",
                        discipline=s_row.get("discipline") or "multidisciplinary",
                        severity="critical",
                        title="Dependency cycle detected in project schedule",
                        description=(
                            f"Schedule '{s_row['title']}' contains a predecessor cycle involving: "
                            f"{', '.join(sorted(cycle_nodes))}."
                        ),
                        reference=s_ref,
                        corrective_action="Remove circular Finish-to-Start dependency edges so network forms a DAG.",
                        deliverable_id=s_deliv_id,
                        task_id=s_row.get("task_id"),
                    )
                )
            for orph in dup_errs + orphan_flags:
                findings.append(
                    QaCandidateFinding(
                        check_category="schedule_consistency",
                        discipline=s_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Orphan activity or broken WBS/dependency link in project schedule",
                        description=f"Schedule '{s_row['title']}': {orph}",
                        reference=s_ref,
                        corrective_action="Fix missing WBS codes or broken predecessor IDs.",
                        deliverable_id=s_deliv_id,
                        task_id=s_row.get("task_id"),
                    )
                )
            for a_obj in acts_in:
                if not a_obj.is_milestone and a_obj.duration_days is None:
                    findings.append(
                        QaCandidateFinding(
                            check_category="schedule_consistency",
                            discipline=s_row.get("discipline") or "multidisciplinary",
                            severity="high",
                            title="Missing activity duration ('not provided') blocks critical path in project schedule",
                            description=(
                                f"Schedule '{s_row['title']}', activity '{a_obj.activity_id}' ('{a_obj.name}') "
                                f"duration is '{NOT_PROVIDED_LABEL}', blocking critical-path computation for its branch."
                            ),
                            reference=f"{s_ref} / {a_obj.activity_id}",
                            corrective_action="Supply owner-verified activity duration (working days) and re-evaluate CPM.",
                            deliverable_id=s_deliv_id,
                            task_id=s_row.get("task_id"),
                        )
                    )
        except Exception as exc:
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=s_row.get("discipline") or "multidisciplinary",
                    severity="high",
                    title="Invalid WBS or schedule activity payload",
                    description=f"Schedule '{s_row['title']}' failed schema inspection: {exc}",
                    reference=s_ref,
                    corrective_action="Repair malformed WBS/activity records and re-evaluate schedule.",
                    deliverable_id=s_deliv_id,
                    task_id=s_row.get("task_id"),
                )
            )

    # 7. Check Step 18 HVAC / Fire / Healthcare missing 'not provided' inputs, unapproved AI drafts, and software disclaimer
    deliv_by_assess_c = {d["assessment_id"]: d["id"] for d in ctx.deliverables if d.get("assessment_id")}
    for a_row in ctx.specialist_assessments:
        checked += 1
        a_deliv_id = deliv_by_assess_c.get(a_row["id"])
        a_ref = f"Specialist {a_row['domain'].upper()} / {a_row['title']} ({a_row['id'][:8]})"
        if int(a_row.get("blocked_missing_count") or 0) > 0:
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=a_row["domain"],
                    severity="high",
                    title="Specialist assessment blocked by missing ('not provided') inputs",
                    description=(
                        f"Assessment '{a_row['title']}' has {a_row['blocked_missing_count']} blocked item(s) due to '{NOT_PROVIDED_LABEL}' inputs."
                    ),
                    reference=a_ref,
                    corrective_action="Supply all required engineering inputs/targets and re-run Step 18 preflight checks.",
                    deliverable_id=a_deliv_id,
                    task_id=a_row.get("task_id"),
                )
            )
        if a_row.get("ai_draft_status") == "unverified_ai_draft":
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=a_row["domain"],
                    severity="high",
                    title="Specialist assessment AI narrative pending owner / engineer approval",
                    description=f"Assessment '{a_row['title']}' carries UNVERIFIED AI DRAFT summary awaiting owner approval.",
                    reference=a_ref,
                    corrective_action="Approve via POST /api/specialist-assessments/{id}/approve.",
                    deliverable_id=a_deliv_id,
                    task_id=a_row.get("task_id"),
                )
            )
        if not str(a_row.get("software_recommendation") or "").strip():
            findings.append(
                QaCandidateFinding(
                    check_category="schedule_consistency",
                    discipline=a_row["domain"],
                    severity="high",
                    title="Specialist assessment missing validated commercial software recommendation",
                    description=f"Assessment '{a_row['title']}' omits mandatory validated commercial software handoff notice.",
                    reference=a_ref,
                    corrective_action="Include validated commercial software handoff recommendation.",
                    deliverable_id=a_deliv_id,
                    task_id=a_row.get("task_id"),
                )
            )

    failed_cnt = len(findings)
    return (
        QaCheckMetricOut(
            category="schedule_consistency",
            checked_count=checked,
            failed_count=failed_cnt,
            passed=(failed_cnt == 0),
            details=f"Evaluated {checked} drawing/BOQ/calculation/specification/comparison/schedule consistency checks; found {failed_cnt} issue(s).",
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
    delivs_by_cmp: dict[str, set[str]] = {}
    delivs_by_sched: dict[str, set[str]] = {}
    delivs_by_assess: dict[str, set[str]] = {}

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
        if d.get("comparison_id"):
            delivs_by_cmp.setdefault(d["comparison_id"], set()).add(str(d.get("format") or "").lower())
        if d.get("schedule_id"):
            delivs_by_sched.setdefault(d["schedule_id"], set()).add(str(d.get("format") or "").lower())
        if d.get("assessment_id"):
            delivs_by_assess.setdefault(d["assessment_id"], set()).add(str(d.get("format") or "").lower())

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

    for cmp_row in ctx.comparisons:
        if int(cmp_row.get("export_version") or 0) > 0:
            checked += 1
            fmts = delivs_by_cmp.get(cmp_row["id"], set())
            missing = sorted({"docx", "pdf", "xlsx"} - fmts)
            if missing:
                findings.append(
                    QaCandidateFinding(
                        check_category="missing_deliverable",
                        discipline=cmp_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Exported technical comparison deliverables incomplete",
                        description=(
                            f"Technical comparison '{cmp_row['title']}' is missing {', '.join(missing).upper()} "
                            "export file(s) in 09_Comparisons."
                        ),
                        reference=f"Comparison {cmp_row['title']}",
                        corrective_action="Re-export technical comparison DOCX + PDF + XLSX into 09_Comparisons.",
                        task_id=cmp_row.get("task_id"),
                    )
                )

    for s_row in ctx.schedules:
        if int(s_row.get("export_version") or 0) > 0:
            checked += 1
            fmts = delivs_by_sched.get(s_row["id"], set())
            missing = sorted({"pdf", "xlsx"} - fmts)
            if missing:
                findings.append(
                    QaCandidateFinding(
                        check_category="missing_deliverable",
                        discipline=s_row.get("discipline") or "multidisciplinary",
                        severity="high",
                        title="Exported project schedule deliverables incomplete",
                        description=(
                            f"Project schedule '{s_row['title']}' is missing {', '.join(missing).upper()} "
                            "export file(s) in 03_Analysis."
                        ),
                        reference=f"Schedule {s_row['title']}",
                        corrective_action="Re-export project schedule Gantt PDF + XLSX into 03_Analysis.",
                        task_id=s_row.get("task_id"),
                    )
                )

    for a_row in ctx.specialist_assessments:
        if int(a_row.get("export_version") or 0) > 0:
            checked += 1
            fmts = delivs_by_assess.get(a_row["id"], set())
            missing = sorted({"docx", "pdf", "xlsx"} - fmts)
            if missing:
                findings.append(
                    QaCandidateFinding(
                        check_category="missing_deliverable",
                        discipline=a_row["domain"],
                        severity="high",
                        title="Exported specialist assessment deliverables incomplete",
                        description=(
                            f"Specialist assessment '{a_row['title']}' is missing {', '.join(missing).upper()} "
                            "export file(s) in 04_Engineering_Calculations."
                        ),
                        reference=f"Specialist {a_row['title']}",
                        corrective_action="Re-export DOCX + PDF + XLSX via POST /api/specialist-assessments/{id}/export.",
                        task_id=a_row.get("task_id"),
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
        has_cmp = bool(ctx.comparisons) or any(
            d.get("folder_name") == "09_Comparisons" for d in ctx.deliverables
        )
        has_sched = bool(ctx.schedules) or any(
            d.get("deliverable_type") == "project_schedule" or d.get("folder_name") == "03_Analysis"
            for d in ctx.deliverables
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
            elif any(k in low for k in ("comparison", "trade-off", "tradeoff", "matrix", "مقارنة", "مفاضلة")):
                if not has_cmp:
                    findings.append(
                        QaCandidateFinding(
                            check_category="missing_deliverable",
                            discipline="multidisciplinary",
                            severity="high",
                            title="Missing expected technical comparison deliverable for task",
                            description=f"Task expects deliverable '{exp}', but no TechnicalComparison or 09_Comparisons deliverable is linked.",
                            reference=f"Task {ctx.task_id[:8]} / {exp}",
                            corrective_action="Evaluate and export technical comparison DOCX + PDF + XLSX for this task.",
                            task_id=ctx.task_id,
                        )
                    )
            elif any(k in low for k in ("schedule", "wbs", "gantt", "critical path", "planning", "جدول زمني", "مسار حرج", "جانت")):
                if not has_sched:
                    findings.append(
                        QaCandidateFinding(
                            check_category="missing_deliverable",
                            discipline="multidisciplinary",
                            severity="high",
                            title="Missing expected project schedule deliverable for task",
                            description=f"Task expects deliverable '{exp}', but no ProjectSchedule or 03_Analysis deliverable is linked.",
                            reference=f"Task {ctx.task_id[:8]} / {exp}",
                            corrective_action="Create and export WBS/CPM Gantt PDF + XLSX schedule for this task.",
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
        ctx.deliverables or ctx.boq_sheets or ctx.drawings or ctx.review_reports or ctx.calculations or ctx.specifications or ctx.comparisons or ctx.schedules or ctx.specialist_assessments
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
