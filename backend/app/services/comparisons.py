"""Step 15 technical comparison service: project source validation, Decimal matrix persistence, owner decision gate, SHA-256 exports."""

import json
import re
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.base import new_uuid, utc_now
from app.db.models import (
    AuditLog,
    BoqItem,
    BoqSheet,
    Calculation,
    Deliverable,
    Project,
    ResearchSource,
    Specification,
    Task,
    TechnicalComparison,
)
from app.providers.base import TokenUsage
from app.providers.secrets import SecretStore
from app.schemas.comparisons import (
    ADVISORY_NOTICE_AR,
    ADVISORY_NOTICE_EN,
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    ComparisonCreateRequest,
    ComparisonCriterionIn,
    ComparisonDecideRequest,
    ComparisonExportRequest,
    ComparisonMatrixOut,
    ComparisonOptionIn,
    ComparisonPresetListResponse,
    TechnicalComparisonDetailOut,
    TechnicalComparisonExportOut,
    TechnicalComparisonListResponse,
    TechnicalComparisonSummaryOut,
)
from app.schemas.reports import ReportLanguage
from app.schemas.tasks import TaskTokenUsageOut
from app.services.calc_export import sha256_file
from app.services.comparison_export import (
    ComparisonRenderData,
    generate_comparison_docx,
    generate_comparison_pdf,
    generate_comparison_xlsx,
)
from app.services.projects import ProjectNotFoundError
from app.services.review_reports import _to_deliverable_out
from app.services.workspace import resolve_project_file_path
from app.skills.comparisons import (
    ComparisonInputError,
    draft_comparison_narrative_with_ai,
    evaluate_technical_comparison,
    get_synthetic_comparison_presets,
)

_URL_RE = re.compile(r"https?://[^\s,;\"')>\]]+", re.IGNORECASE)


class ComparisonNotFoundError(LookupError):
    """Raised when a requested technical comparison ID does not exist."""


class ComparisonValidationError(ValueError):
    """Raised when comparison weights, units, entity links, or provenance violate Step 15 rules."""


class ComparisonConflictError(FileExistsError):
    """Raised when writing an immutable versioned comparison export collides on disk."""


def _ai_draft_label(ai_draft_status: str, language: str, decided_by: str | None) -> str:
    if ai_draft_status == "unverified_ai_draft":
        return AI_UNVERIFIED_DRAFT_LABEL_AR if language == "ar" else AI_UNVERIFIED_DRAFT_LABEL_EN
    if ai_draft_status == "owner_approved":
        who = decided_by or "Owner"
        return (
            f"ملخص ذكاء اصطناعي مُعتمد من المالك ({who})"
            if language == "ar"
            else f"AI Summary — Owner Approved ({who})"
        )
    return (
        "تقييم حتمي برمجياً بالـ Decimal (0 توكن)"
        if language == "ar"
        else "Deterministic Decimal Matrix (0 AI tokens)"
    )


def _to_summary_out(row: TechnicalComparison) -> TechnicalComparisonSummaryOut:
    criteria = row.criteria_json if isinstance(row.criteria_json, list) else []
    options = row.options_json if isinstance(row.options_json, list) else []
    mat_raw = row.matrix_result_json if isinstance(row.matrix_result_json, dict) else {}
    return TechnicalComparisonSummaryOut(
        id=row.id,
        project_id=row.project_id,
        project_code=row.project.code if row.project else "",
        project_name=row.project.name if row.project else "",
        task_id=row.task_id,
        title=row.title,
        comparison_scope=row.comparison_scope,
        discipline=row.discipline,
        language=row.language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=row.export_version,
        status=row.status,
        use_ai=bool(row.use_ai),
        ai_draft_status=row.ai_draft_status,
        ai_draft_label=_ai_draft_label(row.ai_draft_status, row.language, row.owner_decided_by),
        owner_decision_status=row.owner_decision_status,
        owner_selected_option_id=row.owner_selected_option_id,
        owner_decision_note=row.owner_decision_note,
        owner_decided_by=row.owner_decided_by,
        owner_decided_at=row.owner_decided_at,
        total_weight=float(mat_raw.get("total_weight") or 0.0),
        criteria_count=len(criteria),
        options_count=len(options),
        tokens_used=int(row.tokens_used or 0),
        summary=row.summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail_out(row: TechnicalComparison) -> TechnicalComparisonDetailOut:
    summary_out = _to_summary_out(row)
    criteria = [ComparisonCriterionIn.model_validate(c) for c in (row.criteria_json or [])]
    matrix = ComparisonMatrixOut.model_validate(row.matrix_result_json or {})
    raw_usage = row.token_usage_json if isinstance(row.token_usage_json, dict) else {}
    usage = TaskTokenUsageOut(
        prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
        output_tokens=int(raw_usage.get("output_tokens") or 0),
        total_tokens=int(raw_usage.get("total_tokens") or row.tokens_used or 0),
        thoughts_tokens=int(raw_usage.get("thoughts_tokens") or 0),
        cached_tokens=int(raw_usage.get("cached_tokens") or 0),
    )
    deliverables = [_to_deliverable_out(d) for d in sorted(row.deliverables, key=lambda x: x.created_at, reverse=True)]
    return TechnicalComparisonDetailOut(
        **summary_out.model_dump(),
        criteria=criteria,
        matrix=matrix,
        token_usage=usage,
        deliverables=deliverables,
    )


def _validate_comparison_sources(
    db: Session,
    *,
    project_id: str,
    payload: ComparisonCreateRequest,
) -> None:
    """Ensure every linked BOQ item, specification, calculation, and research source belongs to this project and is valid."""
    if payload.task_id:
        task = db.get(Task, payload.task_id)
        if task is None or task.project_id != project_id:
            raise ComparisonValidationError(f"Task '{payload.task_id}' does not belong to project '{project_id}'.")

    project_boq_ids = set(
        db.scalars(
            select(BoqItem.id)
            .join(BoqSheet, BoqItem.boq_sheet_id == BoqSheet.id)
            .where(BoqSheet.project_id == project_id)
        ).all()
    )
    project_spec_ids = set(db.scalars(select(Specification.id).where(Specification.project_id == project_id)).all())
    project_calc_ids = set(db.scalars(select(Calculation.id).where(Calculation.project_id == project_id)).all())
    project_sources = {
        rs.id: rs
        for rs in db.scalars(select(ResearchSource).where(ResearchSource.project_id == project_id)).all()
    }
    reviewed_source_urls = {
        rs.url.strip().lower()
        for rs in project_sources.values()
        if rs.reviewed and rs.access_status in {"accessible", "owner_provided"} and rs.url
    }

    def _check_ref(
        *,
        owner_label: str,
        source_kind: str,
        source_ref: str | None,
        boq_item_id: str | None,
        specification_id: str | None,
        calculation_id: str | None,
        research_source_id: str | None,
        is_lifecycle_criterion: bool = False,
        is_missing: bool = False,
    ) -> None:
        if source_kind == "boq_item":
            if not boq_item_id:
                raise ComparisonValidationError(f"{owner_label}: source_kind='boq_item' requires boq_item_id.")
            if boq_item_id not in project_boq_ids:
                raise ComparisonValidationError(
                    f"{owner_label}: boq_item_id '{boq_item_id}' does not belong to project '{project_id}'."
                )
        elif boq_item_id and boq_item_id not in project_boq_ids:
            raise ComparisonValidationError(
                f"{owner_label}: boq_item_id '{boq_item_id}' does not belong to project '{project_id}'."
            )

        if source_kind == "specification":
            if not specification_id:
                raise ComparisonValidationError(f"{owner_label}: source_kind='specification' requires specification_id.")
            if specification_id not in project_spec_ids:
                raise ComparisonValidationError(
                    f"{owner_label}: specification_id '{specification_id}' does not belong to project '{project_id}'."
                )
        elif specification_id and specification_id not in project_spec_ids:
            raise ComparisonValidationError(
                f"{owner_label}: specification_id '{specification_id}' does not belong to project '{project_id}'."
            )

        if source_kind == "calculation":
            if calculation_id:
                if calculation_id not in project_calc_ids:
                    raise ComparisonValidationError(
                        f"{owner_label}: calculation_id '{calculation_id}' does not belong to project '{project_id}'."
                    )
            elif not is_lifecycle_criterion:
                raise ComparisonValidationError(
                    f"{owner_label}: source_kind='calculation' requires calculation_id (except derived lifecycle_cost)."
                )
        elif calculation_id and calculation_id not in project_calc_ids:
            raise ComparisonValidationError(
                f"{owner_label}: calculation_id '{calculation_id}' does not belong to project '{project_id}'."
            )

        if source_kind == "research_source":
            if not research_source_id:
                raise ComparisonValidationError(
                    f"{owner_label}: source_kind='research_source' requires research_source_id."
                )
            rs = project_sources.get(research_source_id)
            if rs is None or not rs.reviewed or rs.access_status not in {"accessible", "owner_provided"}:
                raise ComparisonValidationError(
                    f"{owner_label}: research_source_id '{research_source_id}' is missing or not reviewed/accessible."
                )
        elif research_source_id:
            rs = project_sources.get(research_source_id)
            if rs is None or not rs.reviewed or rs.access_status not in {"accessible", "owner_provided"}:
                raise ComparisonValidationError(
                    f"{owner_label}: linked research_source_id '{research_source_id}' must belong to project and be reviewed/accessible."
                )

        if not is_missing and source_ref:
            for url_hit in _URL_RE.findall(source_ref):
                if url_hit.lower() not in reviewed_source_urls:
                    raise ComparisonValidationError(
                        f"{owner_label}: URL '{url_hit}' is not registered as a reviewed ResearchSource for this project."
                    )

    crit_map = {c.criterion_id: c for c in payload.criteria}
    for crit in payload.criteria:
        _check_ref(
            owner_label=f"Criterion '{crit.criterion_id}'",
            source_kind=crit.source_kind,
            source_ref=crit.source_ref,
            boq_item_id=crit.boq_item_id,
            specification_id=crit.specification_id,
            calculation_id=crit.calculation_id,
            research_source_id=crit.research_source_id,
            is_lifecycle_criterion=(crit.category == "lifecycle_cost"),
            is_missing=False,
        )

    for opt in payload.options:
        for cell in opt.cells:
            crit = crit_map.get(cell.criterion_id)
            if crit is None:
                raise ComparisonValidationError(
                    f"Option '{opt.option_id}' cell references unknown criterion_id '{cell.criterion_id}'."
                )
            cell_missing = cell.value is None or (
                isinstance(cell.value, str) and cell.value.strip().lower() in {"", "not provided", "n/a", "na", "tbd", "none", "null"}
            )
            _check_ref(
                owner_label=f"Option '{opt.option_id}' cell '{cell.criterion_id}'",
                source_kind=cell.source_kind,
                source_ref=cell.source_ref,
                boq_item_id=cell.boq_item_id,
                specification_id=cell.specification_id,
                calculation_id=cell.calculation_id,
                research_source_id=cell.research_source_id,
                is_lifecycle_criterion=(crit.category == "lifecycle_cost"),
                is_missing=cell_missing,
            )


def _deterministic_summary(matrix: ComparisonMatrixOut, language: ReportLanguage) -> str:
    leader = matrix.leading_option_name
    if language == "ar":
        lead_part = (
            f"أعلى خيار استشارياً وفق التقييم الموزون (مع اجتياز المتطلبات الإلزامية): {leader}."
            if leader
            else "لم يجتز أي خيار كافة المتطلبات الإلزامية حتى الآن."
        )
        return (
            f"{lead_part} إجمالي الأوزان = {matrix.total_weight:.2f}%؛ "
            f"تنبيهات الوحدات = {len(matrix.unit_mismatch_flags)}؛ "
            f"قيم إلزامية مفقودة = {len(matrix.missing_mandatory_flags)}. "
            f"{ADVISORY_NOTICE_AR}"
        )
    lead_part = (
        f"Highest advisory weighted option (passing mandatory gates): {leader}."
        if leader
        else "No candidate option currently satisfies all mandatory criteria."
    )
    return (
        f"{lead_part} Total weight sum = {matrix.total_weight:.2f}%; "
        f"unit mismatch flags = {len(matrix.unit_mismatch_flags)}; "
        f"missing mandatory flags = {len(matrix.missing_mandatory_flags)}. "
        f"{ADVISORY_NOTICE_EN}"
    )


def _write_versioned_comparison_files(
    settings: Settings,
    *,
    project: Project,
    row: TechnicalComparison,
    language: ReportLanguage,
    export_ver: int,
) -> tuple[Deliverable, Deliverable, Deliverable]:
    criteria = [ComparisonCriterionIn.model_validate(c) for c in (row.criteria_json or [])]
    matrix = ComparisonMatrixOut.model_validate(row.matrix_result_json or {})

    short_id = row.id.replace("-", "")[:8]
    rel_docx = f"09_Comparisons/cmp_{short_id}_v{row.version}_e{export_ver}_{language}.docx"
    rel_pdf = f"09_Comparisons/cmp_{short_id}_v{row.version}_e{export_ver}_{language}.pdf"
    rel_xlsx = f"09_Comparisons/cmp_{short_id}_v{row.version}_e{export_ver}_{language}.xlsx"
    rel_json = f"09_Comparisons/cmp_{short_id}_v{row.version}_e{export_ver}_{language}.json"

    path_docx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_docx)
    path_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_pdf)
    path_xlsx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_xlsx)
    path_json = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_json)

    for target in (path_docx, path_pdf, path_xlsx, path_json):
        if target.exists():
            raise ComparisonConflictError(f"Refusing to overwrite existing comparison deliverable: {target.name}")

    render_data = ComparisonRenderData(
        project_code=project.code,
        project_name=project.name,
        title=row.title,
        comparison_scope=row.comparison_scope,
        discipline=row.discipline,
        language=language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=export_ver,
        issued_at_iso=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        use_ai=bool(row.use_ai),
        ai_draft_status=row.ai_draft_status,
        owner_decision_status=row.owner_decision_status,
        owner_selected_option_id=row.owner_selected_option_id,
        owner_decision_note=row.owner_decision_note,
        owner_decided_by=row.owner_decided_by,
        owner_decided_at_iso=row.owner_decided_at.isoformat() if row.owner_decided_at else None,
        summary=row.summary,
        criteria=criteria,
        matrix=matrix,
    )

    generate_comparison_docx(path_docx, render_data)
    generate_comparison_pdf(path_pdf, render_data)
    generate_comparison_xlsx(path_xlsx, render_data)

    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(
        json.dumps(
            {
                "comparison_id": row.id,
                "project_id": project.id,
                "title": row.title,
                "comparison_scope": row.comparison_scope,
                "discipline": row.discipline,
                "language": language,
                "classification": row.classification,
                "version": row.version,
                "export_version": export_ver,
                "use_ai": row.use_ai,
                "ai_draft_status": row.ai_draft_status,
                "owner_decision_status": row.owner_decision_status,
                "owner_selected_option_id": row.owner_selected_option_id,
                "owner_decided_by": row.owner_decided_by,
                "criteria": row.criteria_json,
                "options": row.options_json,
                "matrix_result": row.matrix_result_json,
                "files": {
                    "docx": {"relative_path": rel_docx, "sha256": sha256_file(path_docx)},
                    "pdf": {"relative_path": rel_pdf, "sha256": sha256_file(path_pdf)},
                    "xlsx": {"relative_path": rel_xlsx, "sha256": sha256_file(path_xlsx)},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    mime_docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    deliv_docx = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        comparison_id=row.id,
        title=f"{row.title} ({row.revision} v{export_ver} — DOCX {language.upper()})",
        deliverable_type="technical_comparison",
        discipline=row.discipline,
        format="docx",
        classification=row.classification,
        status="issued",
        version=export_ver,
        folder_name="09_Comparisons",
        filename=path_docx.name,
        relative_path=rel_docx,
        mime_type=mime_docx,
        size_bytes=path_docx.stat().st_size,
        sha256=sha256_file(path_docx),
        summary=row.summary,
    )
    deliv_pdf = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        comparison_id=row.id,
        title=f"{row.title} ({row.revision} v{export_ver} — PDF {language.upper()})",
        deliverable_type="technical_comparison",
        discipline=row.discipline,
        format="pdf",
        classification=row.classification,
        status="issued",
        version=export_ver,
        folder_name="09_Comparisons",
        filename=path_pdf.name,
        relative_path=rel_pdf,
        mime_type="application/pdf",
        size_bytes=path_pdf.stat().st_size,
        sha256=sha256_file(path_pdf),
        summary=row.summary,
    )
    deliv_xlsx = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        comparison_id=row.id,
        title=f"{row.title} ({row.revision} v{export_ver} — XLSX {language.upper()})",
        deliverable_type="technical_comparison",
        discipline=row.discipline,
        format="xlsx",
        classification=row.classification,
        status="issued",
        version=export_ver,
        folder_name="09_Comparisons",
        filename=path_xlsx.name,
        relative_path=rel_xlsx,
        mime_type=mime_xlsx,
        size_bytes=path_xlsx.stat().st_size,
        sha256=sha256_file(path_xlsx),
        summary=row.summary,
    )
    return deliv_docx, deliv_pdf, deliv_xlsx


def create_technical_comparison(
    db: Session,
    settings: Settings,
    secret_store: SecretStore,
    project_id: str,
    payload: ComparisonCreateRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> TechnicalComparisonDetailOut:
    """Create a deterministic weighted Decimal technical comparison, optional AI narrative, and initial versioned exports."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    _validate_comparison_sources(db, project_id=project_id, payload=payload)

    try:
        matrix = evaluate_technical_comparison(
            criteria=payload.criteria,
            options=payload.options,
            language=payload.language,
            lifecycle_years=payload.lifecycle_years,
            enforce_weight_sum=True,
        )
    except ComparisonInputError as exc:
        raise ComparisonValidationError(str(exc)) from exc

    title = payload.title or (
        f"مقارنة فنية ({payload.comparison_scope}) — {project.name}"
        if payload.language == "ar"
        else f"Technical Comparison ({payload.comparison_scope}) — {project.name}"
    )

    tokens_used = 0
    ai_draft_status = "not_used"
    summary_text = _deterministic_summary(matrix, payload.language)
    usage_dict: dict[str, Any] = {
        "prompt_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "thoughts_tokens": 0,
        "cached_tokens": 0,
    }

    if payload.use_ai:
        ai_note, token_usage, _, _ = draft_comparison_narrative_with_ai(
            db,
            secret_store,
            project_id=project.id,
            project_code=project.code,
            project_name=project.name,
            title=title,
            language=payload.language,
            matrix=matrix,
            criteria=payload.criteria,
            complexity=payload.complexity,
            client_factory=client_factory,
            task_id=payload.task_id,
        )
        tokens_used = int(token_usage.total_tokens)
        ai_draft_status = "unverified_ai_draft"
        summary_text = ai_note
        usage_dict = {
            "prompt_tokens": int(token_usage.prompt_tokens),
            "output_tokens": int(token_usage.output_tokens),
            "total_tokens": int(token_usage.total_tokens),
            "thoughts_tokens": int(getattr(token_usage, "thoughts_tokens", 0) or 0),
            "cached_tokens": int(getattr(token_usage, "cached_tokens", 0) or 0),
        }

    max_ver = db.scalar(
        select(func.coalesce(func.max(TechnicalComparison.version), 0)).where(TechnicalComparison.project_id == project.id)
    )
    next_version = int(max_ver or 0) + 1

    matrix_dict = matrix.model_dump(mode="json")
    matrix_dict["lifecycle_years"] = payload.lifecycle_years

    row = TechnicalComparison(
        id=new_uuid(),
        project_id=project.id,
        task_id=payload.task_id,
        title=title,
        comparison_scope=payload.comparison_scope,
        discipline=payload.discipline,
        language=payload.language,
        classification=payload.classification,
        revision=payload.revision,
        version=next_version,
        export_version=1,
        status="evaluated",
        use_ai=bool(payload.use_ai),
        ai_draft_status=ai_draft_status,
        owner_decision_status="pending_owner_decision",
        tokens_used=tokens_used,
        token_usage_json=usage_dict,
        criteria_json=[c.model_dump(mode="json") for c in payload.criteria],
        options_json=[o.model_dump(mode="json") for o in payload.options],
        matrix_result_json=matrix_dict,
        summary=summary_text,
    )
    db.add(row)
    db.flush()

    deliv_docx, deliv_pdf, deliv_xlsx = _write_versioned_comparison_files(
        settings,
        project=project,
        row=row,
        language=payload.language,
        export_ver=1,
    )
    db.add_all([deliv_docx, deliv_pdf, deliv_xlsx])
    db.add(
        AuditLog(
            project_id=project.id,
            actor="comparison-engine" if not payload.use_ai else "comparison-ai-draft",
            action="technical_comparison_created",
            entity_type="technical_comparison",
            entity_id=row.id,
            details_json={
                "version": row.version,
                "language": row.language,
                "criteria_count": len(payload.criteria),
                "options_count": len(payload.options),
                "tokens_used": tokens_used,
                "export_version": 1,
                "docx_sha256": deliv_docx.sha256,
                "pdf_sha256": deliv_pdf.sha256,
                "xlsx_sha256": deliv_xlsx.sha256,
            },
        )
    )
    db.commit()
    return get_comparison_detail(db, row.id)


def list_project_comparisons(db: Session, project_id: str) -> TechnicalComparisonListResponse:
    """List persisted Step 15 technical comparisons for a project ordered newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(TechnicalComparison)
        .options(selectinload(TechnicalComparison.project))
        .where(TechnicalComparison.project_id == project_id)
        .order_by(TechnicalComparison.created_at.desc(), TechnicalComparison.version.desc())
    ).all()
    items = [_to_summary_out(r) for r in rows]
    return TechnicalComparisonListResponse(comparisons=items, total=len(items))


def get_comparison_detail(db: Session, comparison_id: str) -> TechnicalComparisonDetailOut:
    """Retrieve complete technical comparison matrix, criteria, options, provenance, and deliverables."""
    row = db.scalar(
        select(TechnicalComparison)
        .options(selectinload(TechnicalComparison.project), selectinload(TechnicalComparison.deliverables))
        .where(TechnicalComparison.id == comparison_id)
    )
    if row is None:
        raise ComparisonNotFoundError(f"Technical comparison '{comparison_id}' was not found.")
    return _to_detail_out(row)


def decide_technical_comparison(
    db: Session,
    settings: Settings,
    comparison_id: str,
    payload: ComparisonDecideRequest,
) -> TechnicalComparisonDetailOut:
    """Record explicit Owner / Licensed Engineer decision and optionally sign off AI narrative."""
    row = db.scalar(
        select(TechnicalComparison)
        .options(selectinload(TechnicalComparison.project), selectinload(TechnicalComparison.deliverables))
        .where(TechnicalComparison.id == comparison_id)
    )
    if row is None:
        raise ComparisonNotFoundError(f"Technical comparison '{comparison_id}' was not found.")

    valid_option_ids = {str(o.get("option_id") or "") for o in (row.options_json or [])}
    if payload.selected_option_id not in valid_option_ids:
        raise ComparisonValidationError(
            f"selected_option_id '{payload.selected_option_id}' is not among options {sorted(valid_option_ids)}."
        )

    now_ts = utc_now()
    decided_by = payload.decided_by.strip()
    row.owner_decision_status = "owner_selected"
    row.owner_selected_option_id = payload.selected_option_id
    row.owner_decision_note = payload.decision_note.strip()
    row.owner_decided_by = decided_by
    row.owner_decided_at = now_ts
    row.status = "owner_decided"

    if payload.approve_ai_draft and row.ai_draft_status == "unverified_ai_draft":
        row.ai_draft_status = "owner_approved"
        if row.summary:
            cleaned = row.summary
            for tag in (f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] ", f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] "):
                if cleaned.startswith(tag):
                    cleaned = cleaned[len(tag):]
            row.summary = cleaned

    if payload.export_after_decision and row.project is not None:
        row.export_version = int(row.export_version or 0) + 1
        d_docx, d_pdf, d_xlsx = _write_versioned_comparison_files(
            settings,
            project=row.project,
            row=row,
            language=row.language,  # type: ignore[arg-type]
            export_ver=row.export_version,
        )
        db.add_all([d_docx, d_pdf, d_xlsx])

    db.add(
        AuditLog(
            project_id=row.project_id,
            actor=decided_by,
            action="technical_comparison_owner_decided",
            entity_type="technical_comparison",
            entity_id=row.id,
            details_json={
                "selected_option_id": payload.selected_option_id,
                "ai_draft_status": row.ai_draft_status,
                "export_version": row.export_version,
            },
        )
    )
    db.commit()
    return get_comparison_detail(db, row.id)


def export_technical_comparison(
    db: Session,
    settings: Settings,
    comparison_id: str,
    payload: ComparisonExportRequest | None = None,
) -> TechnicalComparisonExportOut:
    """Generate immutable SHA-256 versioned DOCX, PDF & XLSX package in 09_Comparisons plus Deliverable records."""
    row = db.scalar(
        select(TechnicalComparison)
        .options(selectinload(TechnicalComparison.project), selectinload(TechnicalComparison.deliverables))
        .where(TechnicalComparison.id == comparison_id)
    )
    if row is None:
        raise ComparisonNotFoundError(f"Technical comparison '{comparison_id}' was not found.")
    if row.project is None:
        raise ProjectNotFoundError(f"Project '{row.project_id}' was not found.")

    lang: ReportLanguage = (payload.language if payload and payload.language else row.language)  # type: ignore[assignment]
    next_export = int(row.export_version or 0) + 1
    row.export_version = next_export

    deliv_docx, deliv_pdf, deliv_xlsx = _write_versioned_comparison_files(
        settings,
        project=row.project,
        row=row,
        language=lang,
        export_ver=next_export,
    )
    db.add_all([deliv_docx, deliv_pdf, deliv_xlsx])
    db.add(
        AuditLog(
            project_id=row.project_id,
            actor="owner-export",
            action="technical_comparison_exported",
            entity_type="technical_comparison",
            entity_id=row.id,
            details_json={
                "export_version": next_export,
                "language": lang,
                "docx_sha256": deliv_docx.sha256,
                "pdf_sha256": deliv_pdf.sha256,
                "xlsx_sha256": deliv_xlsx.sha256,
            },
        )
    )
    db.commit()

    detail = get_comparison_detail(db, row.id)
    return TechnicalComparisonExportOut(
        comparison=detail,
        docx_deliverable=_to_deliverable_out(deliv_docx),
        pdf_deliverable=_to_deliverable_out(deliv_pdf),
        xlsx_deliverable=_to_deliverable_out(deliv_xlsx),
    )


def list_comparison_presets() -> ComparisonPresetListResponse:
    """Return synthetic clinic equipment presets (0% client data)."""
    return ComparisonPresetListResponse(presets=get_synthetic_comparison_presets())
