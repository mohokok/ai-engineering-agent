"""Step 19 structural assessment support & I/O check service: verified-only code citations, optional AI gate, and DOCX/PDF/XLSX export."""

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.base import utc_now
from app.db.models import AuditLog, Deliverable, Project, StructuralAssessment, Task
from app.providers.base import TokenUsage
from app.providers.secrets import SecretStore
from app.schemas.specialist import SpecialistReferenceOut
from app.schemas.structural import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    PRELIMINARY_STRUCTURAL_LABEL_AR,
    PRELIMINARY_STRUCTURAL_LABEL_EN,
    STRUCTURAL_SOFTWARE_RECOMMENDATION,
    StructuralApproveRequest,
    StructuralAssessmentCreateRequest,
    StructuralAssessmentUpdateRequest,
    StructuralDetailOut,
    StructuralExportOut,
    StructuralListResponse,
    StructuralPresetListResponse,
    StructuralSummaryOut,
)
from app.schemas.tasks import TaskTokenUsageOut
from app.services.calc_export import sha256_file
from app.services.projects import ProjectNotFoundError
from app.services.review_reports import _to_deliverable_out
from app.services.specialist import SpecialistValidationError, _validate_and_bind_references
from app.services.specialist_export import (
    SpecialistRenderData,
    generate_specialist_docx,
    generate_specialist_pdf,
    generate_specialist_xlsx,
)
from app.services.workspace import resolve_project_file_path
from app.skills.structural import (
    StructuralInputError,
    draft_structural_narrative_with_ai,
    evaluate_structural_assessment,
    get_synthetic_structural_presets,
)


class StructuralNotFoundError(LookupError):
    """Raised when a Step 19 structural assessment ID does not exist."""


class StructuralValidationError(ValueError):
    """Raised when structural inputs, code citations, or ownership violate Step 19 rules."""


def _ai_label(ai_draft_status: str, lang: str) -> str:
    if ai_draft_status == "unverified_ai_draft":
        return AI_UNVERIFIED_DRAFT_LABEL_AR if lang == "ar" else AI_UNVERIFIED_DRAFT_LABEL_EN
    if ai_draft_status == "owner_approved":
        return "Licensed Structural Engineer / Owner Approved"
    return "Deterministic (0 AI Tokens)"


def _to_summary(row: StructuralAssessment) -> StructuralSummaryOut:
    prelim = PRELIMINARY_STRUCTURAL_LABEL_AR if row.language == "ar" else PRELIMINARY_STRUCTURAL_LABEL_EN
    return StructuralSummaryOut(
        id=row.id,
        project_id=row.project_id,
        project_code=row.project.code if row.project else "",
        project_name=row.project.name if row.project else "",
        task_id=row.task_id,
        assessment_type=row.assessment_type,
        title=row.title,
        language=row.language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=row.export_version,
        status=row.status,
        checks_passed=bool(row.checks_passed),
        blocked_missing_count=row.blocked_missing_count,
        failed_checks_count=row.failed_checks_count,
        standards_status=row.standards_status,
        use_ai=bool(row.use_ai),
        ai_draft_status=row.ai_draft_status,
        ai_draft_label=_ai_label(row.ai_draft_status, row.language),
        owner_approved_by=row.owner_approved_by,
        owner_approved_at=row.owner_approved_at,
        tokens_used=row.tokens_used,
        preliminary_label=prelim,
        software_recommendation=row.software_recommendation or STRUCTURAL_SOFTWARE_RECOMMENDATION,
        summary=row.summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail(row: StructuralAssessment) -> StructuralDetailOut:
    sm = _to_summary(row)
    raw_usage = row.token_usage_json if isinstance(row.token_usage_json, dict) else {}
    usage = TaskTokenUsageOut(
        prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
        output_tokens=int(raw_usage.get("output_tokens") or 0),
        total_tokens=int(raw_usage.get("total_tokens") or row.tokens_used or 0),
        thoughts_tokens=int(raw_usage.get("thoughts_tokens") or 0),
        cached_tokens=int(raw_usage.get("cached_tokens") or 0),
    )
    delivs = [_to_deliverable_out(d) for d in sorted(row.deliverables or [], key=lambda x: x.created_at)]
    return StructuralDetailOut(
        **sm.model_dump(),
        inputs=dict(row.inputs_json or {}),
        results=dict(row.results_json or {}),
        references=[SpecialistReferenceOut.model_validate(r) for r in (row.references_json or [])],
        preliminary_assumptions=list(row.preliminary_assumptions_json or []),
        token_usage=usage,
        deliverables=delivs,
    )


def _eval_dict(ev: Any) -> dict[str, Any]:
    return {
        "equations": ev.equations,
        "methodology": ev.methodology,
        "prepared_items": ev.prepared_items,
        "check_rows": ev.check_rows,
        "blocked_flags": ev.blocked_flags,
        "metrics": ev.metrics,
    }


def list_structural_presets() -> StructuralPresetListResponse:
    return StructuralPresetListResponse(presets=get_synthetic_structural_presets())


def create_structural_assessment(
    db: Session,
    secret_store: SecretStore,
    project_id: str,
    payload: StructuralAssessmentCreateRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> StructuralDetailOut:
    """Create and deterministically run Step 19 structural checks (0 AI tokens default; never designs members)."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project not found: {project_id}")

    if payload.task_id:
        task = db.get(Task, payload.task_id)
        if task is None or task.project_id != project_id:
            raise StructuralValidationError("task_id does not belong to this project.")

    try:
        refs_dicts, std_status = _validate_and_bind_references(
            db,
            project_id=project_id,
            refs=payload.references,
        )
    except SpecialistValidationError as exc:
        raise StructuralValidationError(str(exc)) from exc

    try:
        ev = evaluate_structural_assessment(
            assessment_type=payload.assessment_type,
            inputs=payload.inputs,
        )
    except StructuralInputError as exc:
        raise StructuralValidationError(str(exc)) from exc

    ai_status = "not_used"
    tokens_used = 0
    usage_dict: dict[str, Any] = TokenUsage().__dict__
    summary_txt = (
        f"STRUCTURAL ({payload.assessment_type}): "
        f"{ev.metrics.get('passed_checks_count', 0)} passed, "
        f"{ev.failed_checks_count} failed, {ev.blocked_missing_count} blocked ('not provided')."
    )

    if payload.use_ai:
        refs_text = "; ".join(r["verification_label"] for r in refs_dicts)
        prose, usage = draft_structural_narrative_with_ai(
            db,
            secret_store,
            assessment_type=payload.assessment_type,
            title=payload.title,
            evaluation=ev,
            standards_summary=refs_text,
            complexity=payload.complexity,
            project_id=project_id,
            client_factory=client_factory,
        )
        ai_status = "unverified_ai_draft"
        tokens_used = usage.total_tokens
        usage_dict = {
            "prompt_tokens": usage.prompt_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "thoughts_tokens": usage.thoughts_tokens,
            "cached_tokens": usage.cached_tokens,
        }
        lbl_tag = AI_UNVERIFIED_DRAFT_LABEL_AR if payload.language == "ar" else AI_UNVERIFIED_DRAFT_LABEL_EN
        summary_txt = f"[{lbl_tag}] {prose}"

    row = StructuralAssessment(
        project_id=project.id,
        task_id=payload.task_id,
        assessment_type=payload.assessment_type,
        title=payload.title,
        language=payload.language,
        classification=payload.classification,
        revision=payload.revision,
        version=1,
        export_version=0,
        status=ev.status,
        checks_passed=ev.checks_passed,
        blocked_missing_count=ev.blocked_missing_count,
        failed_checks_count=ev.failed_checks_count,
        standards_status=std_status,
        use_ai=payload.use_ai,
        ai_draft_status=ai_status,
        tokens_used=tokens_used,
        token_usage_json=usage_dict,
        inputs_json=dict(payload.inputs),
        results_json=_eval_dict(ev),
        references_json=refs_dicts,
        preliminary_assumptions_json=ev.preliminary_assumptions,
        software_recommendation=ev.software_recommendation,
        summary=summary_txt,
    )
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            project_id=project.id,
            action="structural_assessment_created",
            entity_type="structural_assessment",
            entity_id=row.id,
            details_json={"assessment_type": row.assessment_type, "checks_passed": row.checks_passed, "tokens_used": tokens_used},
        )
    )
    db.commit()
    return get_structural_detail(db, row.id)


def list_project_structural_assessments(db: Session, project_id: str) -> StructuralListResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project not found: {project_id}")
    rows = db.scalars(
        select(StructuralAssessment)
        .options(selectinload(StructuralAssessment.project))
        .where(StructuralAssessment.project_id == project_id)
        .order_by(StructuralAssessment.created_at.desc())
    ).all()
    return StructuralListResponse(assessments=[_to_summary(r) for r in rows], total=len(rows))


def get_structural_detail(db: Session, assessment_id: str) -> StructuralDetailOut:
    row = db.scalars(
        select(StructuralAssessment)
        .options(selectinload(StructuralAssessment.project), selectinload(StructuralAssessment.deliverables))
        .where(StructuralAssessment.id == assessment_id)
    ).first()
    if row is None:
        raise StructuralNotFoundError(f"Structural assessment not found: {assessment_id}")
    return _to_detail(row)


def update_structural_assessment(
    db: Session,
    assessment_id: str,
    payload: StructuralAssessmentUpdateRequest,
) -> StructuralDetailOut:
    row = db.get(StructuralAssessment, assessment_id)
    if row is None:
        raise StructuralNotFoundError(f"Structural assessment not found: {assessment_id}")

    next_type = payload.assessment_type or row.assessment_type
    next_inputs = payload.inputs if payload.inputs is not None else dict(row.inputs_json or {})

    if payload.references is not None:
        try:
            refs_dicts, std_status = _validate_and_bind_references(
                db,
                project_id=row.project_id,
                refs=payload.references,
            )
        except SpecialistValidationError as exc:
            raise StructuralValidationError(str(exc)) from exc
        row.references_json = refs_dicts
        row.standards_status = std_status

    try:
        ev = evaluate_structural_assessment(
            assessment_type=next_type,  # type: ignore[arg-type]
            inputs=next_inputs,
        )
    except StructuralInputError as exc:
        raise StructuralValidationError(str(exc)) from exc

    row.assessment_type = next_type
    if payload.title is not None:
        row.title = payload.title
    if payload.language is not None:
        row.language = payload.language
    if payload.classification is not None:
        row.classification = payload.classification
    if payload.revision is not None:
        row.revision = payload.revision

    row.inputs_json = next_inputs
    row.results_json = _eval_dict(ev)
    row.preliminary_assumptions_json = ev.preliminary_assumptions
    row.status = ev.status
    row.checks_passed = ev.checks_passed
    row.blocked_missing_count = ev.blocked_missing_count
    row.failed_checks_count = ev.failed_checks_count
    row.version += 1
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    return get_structural_detail(db, row.id)


def approve_structural_assessment(
    db: Session,
    assessment_id: str,
    payload: StructuralApproveRequest,
) -> StructuralDetailOut:
    row = db.get(StructuralAssessment, assessment_id)
    if row is None:
        raise StructuralNotFoundError(f"Structural assessment not found: {assessment_id}")
    row.ai_draft_status = "owner_approved"
    row.owner_approved_by = payload.approved_by.strip()
    row.owner_approved_at = utc_now()
    row.updated_at = utc_now()
    db.add(row)
    db.add(
        AuditLog(
            project_id=row.project_id,
            actor=row.owner_approved_by or "owner",
            action="structural_assessment_approved",
            entity_type="structural_assessment",
            entity_id=row.id,
            details_json={"assessment_type": row.assessment_type, "version": row.version},
        )
    )
    db.commit()
    return get_structural_detail(db, row.id)


def export_structural_deliverables(
    db: Session,
    settings: Settings,
    assessment_id: str,
    *,
    language: str | None = None,
) -> StructuralExportOut:
    """Export immutable bilingual DOCX, PDF, and live-formula XLSX structural report into 04_Engineering_Calculations with SHA-256."""
    row = db.scalars(
        select(StructuralAssessment)
        .options(selectinload(StructuralAssessment.project), selectinload(StructuralAssessment.deliverables))
        .where(StructuralAssessment.id == assessment_id)
    ).first()
    if row is None:
        raise StructuralNotFoundError(f"Structural assessment not found: {assessment_id}")
    project = row.project
    if project is None:
        raise ProjectNotFoundError(f"Project not found for structural assessment {assessment_id}")

    lang_val = language or row.language or "ar"
    if lang_val not in {"ar", "en"}:
        raise StructuralValidationError("Language must be 'ar' or 'en'.")

    next_export = row.export_version + 1
    short_id = row.id[:8]
    rel_docx = f"04_Engineering_Calculations/structural_{short_id}_v{row.version}_e{next_export}_{lang_val}.docx"
    rel_pdf = f"04_Engineering_Calculations/structural_{short_id}_v{row.version}_e{next_export}_{lang_val}.pdf"
    rel_xlsx = f"04_Engineering_Calculations/structural_{short_id}_v{row.version}_e{next_export}_{lang_val}.xlsx"

    p_docx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_docx)
    p_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_pdf)
    p_xlsx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_xlsx)

    res = dict(row.results_json or {})
    heading = (
        "الخطوة 19: دعم التقييم الإنشائي وفحص المدخلات والمخرجات"
        if lang_val == "ar"
        else "Step 19: Structural Assessment Support & I/O Check Report"
    )
    prelim = PRELIMINARY_STRUCTURAL_LABEL_AR if lang_val == "ar" else PRELIMINARY_STRUCTURAL_LABEL_EN

    render_data = SpecialistRenderData(
        project_code=project.code,
        project_name=project.name,
        title=row.title,
        domain="STRUCTURAL",
        workflow_mode=row.assessment_type,
        language=lang_val,  # type: ignore[arg-type]
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        status=row.status,
        checks_passed=bool(row.checks_passed),
        standards_status=row.standards_status,
        software_recommendation=row.software_recommendation,
        ai_draft_status=row.ai_draft_status,
        owner_approved_by=row.owner_approved_by,
        issued_at_iso=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        equations=list(res.get("equations") or []),
        methodology=str(res.get("methodology") or ""),
        preliminary_assumptions=list(row.preliminary_assumptions_json or []),
        prepared_items=list(res.get("prepared_items") or []),
        check_rows=list(res.get("check_rows") or []),
        blocked_flags=list(res.get("blocked_flags") or []),
        references=[SpecialistReferenceOut.model_validate(r) for r in (row.references_json or [])],
        metrics=dict(res.get("metrics") or {}),
        summary=row.summary,
        report_heading=heading,
        preliminary_notice=prelim,
    )

    generate_specialist_docx(p_docx, render_data)
    generate_specialist_pdf(p_pdf, render_data)
    generate_specialist_xlsx(p_xlsx, render_data)

    docx_deliv = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        structural_id=row.id,
        title=f"{row.title} ({row.revision} e{next_export} — Structural DOCX {lang_val.upper()})",
        deliverable_type="structural_assessment",
        discipline="structural",
        format="docx",
        classification=row.classification,
        status="exported",
        version=next_export,
        folder_name="04_Engineering_Calculations",
        filename=p_docx.name,
        relative_path=rel_docx,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=p_docx.stat().st_size,
        sha256=sha256_file(p_docx),
        summary=f"Step 19 structural DOCX export (standards={row.standards_status})",
    )
    pdf_deliv = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        structural_id=row.id,
        title=f"{row.title} ({row.revision} e{next_export} — Structural PDF {lang_val.upper()})",
        deliverable_type="structural_assessment",
        discipline="structural",
        format="pdf",
        classification=row.classification,
        status="exported",
        version=next_export,
        folder_name="04_Engineering_Calculations",
        filename=p_pdf.name,
        relative_path=rel_pdf,
        mime_type="application/pdf",
        size_bytes=p_pdf.stat().st_size,
        sha256=sha256_file(p_pdf),
        summary=f"Step 19 structural PDF export (standards={row.standards_status})",
    )
    xlsx_deliv = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        structural_id=row.id,
        title=f"{row.title} ({row.revision} e{next_export} — Structural XLSX {lang_val.upper()})",
        deliverable_type="structural_assessment",
        discipline="structural",
        format="xlsx",
        classification=row.classification,
        status="exported",
        version=next_export,
        folder_name="04_Engineering_Calculations",
        filename=p_xlsx.name,
        relative_path=rel_xlsx,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=p_xlsx.stat().st_size,
        sha256=sha256_file(p_xlsx),
        summary=f"Step 19 structural live XLSX export (standards={row.standards_status})",
    )
    db.add_all([docx_deliv, pdf_deliv, xlsx_deliv])
    row.export_version = next_export
    if row.status == "evaluated":
        row.status = "exported"
    row.updated_at = utc_now()
    db.add(row)
    db.add(
        AuditLog(
            project_id=project.id,
            actor="owner-export",
            action="structural_assessment_exported",
            entity_type="structural_assessment",
            entity_id=row.id,
            details_json={"assessment_type": row.assessment_type, "language": lang_val, "export_version": next_export},
        )
    )
    db.commit()

    return StructuralExportOut(
        assessment=get_structural_detail(db, row.id),
        docx_deliverable=_to_deliverable_out(docx_deliv),
        pdf_deliverable=_to_deliverable_out(pdf_deliv),
        xlsx_deliverable=_to_deliverable_out(xlsx_deliv),
    )
