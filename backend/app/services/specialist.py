"""Step 18 HVAC, Fire & Healthcare service: verified-only standards binding, deterministic checks, optional AI banner, and DOCX/PDF/XLSX export."""

from typing import Any, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.base import utc_now
from app.db.models import (
    AuditLog,
    Deliverable,
    Project,
    ResearchSource,
    SpecialistAssessment,
    StandardDocument,
    Task,
)
from app.providers.base import TokenUsage
from app.providers.secrets import SecretStore
from app.schemas.specialist import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NO_VERIFIED_STANDARD_LABEL,
    PRELIMINARY_ENGINEER_LABEL_AR,
    PRELIMINARY_ENGINEER_LABEL_EN,
    SpecialistApproveRequest,
    SpecialistAssessmentCreateRequest,
    SpecialistAssessmentUpdateRequest,
    SpecialistDetailOut,
    SpecialistExportOut,
    SpecialistListResponse,
    SpecialistPresetListResponse,
    SpecialistReferenceIn,
    SpecialistReferenceOut,
    SpecialistSummaryOut,
)
from app.schemas.tasks import TaskTokenUsageOut
from app.services.calc_export import sha256_file
from app.services.projects import ProjectNotFoundError
from app.services.review_reports import _to_deliverable_out
from app.services.specialist_export import (
    SpecialistRenderData,
    generate_specialist_docx,
    generate_specialist_pdf,
    generate_specialist_xlsx,
)
from app.services.workspace import resolve_project_file_path
from app.skills.specialist import (
    SpecialistInputError,
    draft_specialist_narrative_with_ai,
    evaluate_specialist_assessment,
    get_synthetic_specialist_presets,
)


class SpecialistNotFoundError(LookupError):
    """Raised when a Step 18 assessment ID does not exist."""


class SpecialistValidationError(ValueError):
    """Raised when references, inputs, or approval state violate Step 18 engineering rules."""


def _ai_label(ai_draft_status: str, lang: str) -> str:
    if ai_draft_status == "unverified_ai_draft":
        return AI_UNVERIFIED_DRAFT_LABEL_AR if lang == "ar" else AI_UNVERIFIED_DRAFT_LABEL_EN
    if ai_draft_status == "owner_approved":
        return "Owner / Licensed Engineer Approved"
    return "Deterministic (0 AI Tokens)"


def _validate_and_bind_references(
    db: Session,
    *,
    project_id: str,
    refs: list[SpecialistReferenceIn],
) -> tuple[list[dict[str, Any]], str]:
    """Cite WHO/FGI/NFPA/ASHRAE/codes ONLY when verified in Standards Library or reviewed ResearchSource log."""
    if not refs:
        fallback = SpecialistReferenceOut(
            source_kind="no_verified_standard_on_file",
            code_or_source_name=NO_VERIFIED_STANDARD_LABEL,
            edition_or_date="unknown",
            status="no_verified_standard_on_file",
            citation_note="No standard or source linked; verify against the locally adopted code.",
            verification_label=NO_VERIFIED_STANDARD_LABEL,
        )
        return [fallback.model_dump()], "no_verified_standard_on_file"

    std_rows = {
        s.id: s
        for s in db.scalars(
            select(StandardDocument).where(
                or_(StandardDocument.project_id == project_id, StandardDocument.project_id.is_(None))
            )
        ).all()
    }
    rs_rows = {
        rs.id: rs
        for rs in db.scalars(
            select(ResearchSource).where(ResearchSource.project_id == project_id)
        ).all()
    }

    bound: list[dict[str, Any]] = []
    verified_count = 0
    flagged_count = 0

    for ref in refs:
        if ref.source_kind == "no_verified_standard_on_file":
            bound.append(
                SpecialistReferenceOut(
                    source_kind="no_verified_standard_on_file",
                    code_or_source_name=NO_VERIFIED_STANDARD_LABEL,
                    edition_or_date="unknown",
                    status="no_verified_standard_on_file",
                    citation_note=ref.citation_note,
                    verification_label=NO_VERIFIED_STANDARD_LABEL,
                ).model_dump()
            )
            continue

        if ref.source_kind == "standard_library":
            std = std_rows.get(ref.standard_library_id or "")
            if std is None:
                raise SpecialistValidationError(
                    "Referenced standard_library_id was not found in the owner's Standards Library for this project."
                )
            is_unconfirmed = std.metadata_status in {"unverified_suggestion", "unverified_ai_suggestion"} or std.ai_suggestion_status == "unverified_ai_suggestion"
            is_current = std.status == "current" and (std.edition_year or "").strip().lower() not in {"", "unknown"} and not is_unconfirmed
            if is_current:
                verified_count += 1
                st_label = "verified_standard_library"
                ver_lbl = f"Owner Standards Library: {std.standard_number} ({std.edition_year})"
            else:
                flagged_count += 1
                st_label = f"flagged_{std.status}" if not is_unconfirmed else "unconfirmed_library_entry"
                ver_lbl = f"FLAGGED ({std.status}, edition={std.edition_year}, metadata={std.metadata_status})"
            bound.append(
                SpecialistReferenceOut(
                    source_kind="standard_library",
                    standard_library_id=std.id,
                    code_or_source_name=f"{std.standard_number} — {std.title}",
                    edition_or_date=std.edition_year,
                    status=st_label,
                    citation_note=ref.citation_note,
                    verification_label=ver_lbl,
                ).model_dump()
            )
            continue

        if ref.source_kind == "verified_source_log":
            rs = rs_rows.get(ref.research_source_id or "")
            if rs is None or not rs.reviewed or rs.access_status not in {"accessible", "owner_provided"}:
                raise SpecialistValidationError(
                    "Referenced research_source_id is missing, unreviewed, or inaccessible in this project's ResearchSource log."
                )
            verified_count += 1
            bound.append(
                SpecialistReferenceOut(
                    source_kind="verified_source_log",
                    research_source_id=rs.id,
                    code_or_source_name=f"{rs.source_name} ({rs.url})",
                    edition_or_date=rs.publication_date or "unknown",
                    status="verified_source_log",
                    citation_note=ref.citation_note,
                    verification_label=f"Reviewed ResearchSource ({rs.source_priority_tier})",
                ).model_dump()
            )

    if verified_count > 0 and flagged_count == 0 and all(b["status"] != "no_verified_standard_on_file" for b in bound):
        overall = "verified_standards"
    elif verified_count > 0 or flagged_count > 0:
        overall = "mixed"
    else:
        overall = "no_verified_standard_on_file"
    return bound, overall


def _to_summary(row: SpecialistAssessment) -> SpecialistSummaryOut:
    prelim = PRELIMINARY_ENGINEER_LABEL_AR if row.language == "ar" else PRELIMINARY_ENGINEER_LABEL_EN
    return SpecialistSummaryOut(
        id=row.id,
        project_id=row.project_id,
        project_code=row.project.code if row.project else "",
        project_name=row.project.name if row.project else "",
        task_id=row.task_id,
        domain=row.domain,
        workflow_mode=row.workflow_mode,
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
        software_recommendation=row.software_recommendation,
        summary=row.summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail(row: SpecialistAssessment) -> SpecialistDetailOut:
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
    return SpecialistDetailOut(
        **sm.model_dump(),
        inputs=dict(row.inputs_json or {}),
        results=dict(row.results_json or {}),
        references=[SpecialistReferenceOut.model_validate(r) for r in (row.references_json or [])],
        preliminary_assumptions=list(row.preliminary_assumptions_json or []),
        token_usage=usage,
        deliverables=delivs,
    )


def _eval_to_results_dict(ev: Any) -> dict[str, Any]:
    return {
        "equations": ev.equations,
        "methodology": ev.methodology,
        "prepared_items": ev.prepared_items,
        "check_rows": ev.check_rows,
        "blocked_flags": ev.blocked_flags,
        "metrics": ev.metrics,
    }


def list_specialist_presets() -> SpecialistPresetListResponse:
    return SpecialistPresetListResponse(presets=get_synthetic_specialist_presets())


def create_specialist_assessment(
    db: Session,
    secret_store: SecretStore,
    project_id: str,
    payload: SpecialistAssessmentCreateRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> SpecialistDetailOut:
    """Create and deterministically evaluate an HVAC/Fire/Healthcare assessment (0 AI tokens default)."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project not found: {project_id}")

    if payload.task_id:
        task = db.get(Task, payload.task_id)
        if task is None or task.project_id != project_id:
            raise SpecialistValidationError("task_id does not belong to this project.")

    refs_dicts, std_status = _validate_and_bind_references(
        db,
        project_id=project_id,
        refs=payload.references,
    )
    try:
        ev = evaluate_specialist_assessment(
            domain=payload.domain,
            workflow_mode=payload.workflow_mode,
            inputs=payload.inputs,
        )
    except SpecialistInputError as exc:
        raise SpecialistValidationError(str(exc)) from exc

    ai_status = "not_used"
    tokens_used = 0
    usage_dict: dict[str, Any] = TokenUsage().__dict__
    summary_txt: str | None = (
        f"{payload.domain.upper()} ({payload.workflow_mode}): "
        f"{ev.metrics.get('passed_checks_count', 0)} passed, "
        f"{ev.failed_checks_count} failed, {ev.blocked_missing_count} blocked ('not provided')."
    )

    if payload.use_ai:
        refs_text = "; ".join(r["verification_label"] for r in refs_dicts)
        prose, usage = draft_specialist_narrative_with_ai(
            db,
            secret_store,
            domain=payload.domain,
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

    row = SpecialistAssessment(
        project_id=project.id,
        task_id=payload.task_id,
        domain=payload.domain,
        workflow_mode=payload.workflow_mode,
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
        results_json=_eval_to_results_dict(ev),
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
            action="specialist_assessment_created",
            entity_type="specialist_assessment",
            entity_id=row.id,
            details_json={"domain": row.domain, "checks_passed": row.checks_passed, "tokens_used": tokens_used},
        )
    )
    db.commit()
    return get_specialist_detail(db, row.id)


def list_project_specialist_assessments(db: Session, project_id: str) -> SpecialistListResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project not found: {project_id}")
    rows = db.scalars(
        select(SpecialistAssessment)
        .options(selectinload(SpecialistAssessment.project))
        .where(SpecialistAssessment.project_id == project_id)
        .order_by(SpecialistAssessment.created_at.desc())
    ).all()
    return SpecialistListResponse(assessments=[_to_summary(r) for r in rows], total=len(rows))


def get_specialist_detail(db: Session, assessment_id: str) -> SpecialistDetailOut:
    row = db.scalars(
        select(SpecialistAssessment)
        .options(selectinload(SpecialistAssessment.project), selectinload(SpecialistAssessment.deliverables))
        .where(SpecialistAssessment.id == assessment_id)
    ).first()
    if row is None:
        raise SpecialistNotFoundError(f"Specialist assessment not found: {assessment_id}")
    return _to_detail(row)


def update_specialist_assessment(
    db: Session,
    assessment_id: str,
    payload: SpecialistAssessmentUpdateRequest,
) -> SpecialistDetailOut:
    row = db.get(SpecialistAssessment, assessment_id)
    if row is None:
        raise SpecialistNotFoundError(f"Specialist assessment not found: {assessment_id}")

    next_mode = payload.workflow_mode or row.workflow_mode
    next_inputs = payload.inputs if payload.inputs is not None else dict(row.inputs_json or {})

    if payload.references is not None:
        refs_dicts, std_status = _validate_and_bind_references(
            db,
            project_id=row.project_id,
            refs=payload.references,
        )
        row.references_json = refs_dicts
        row.standards_status = std_status

    try:
        ev = evaluate_specialist_assessment(
            domain=row.domain,  # type: ignore[arg-type]
            workflow_mode=next_mode,  # type: ignore[arg-type]
            inputs=next_inputs,
        )
    except SpecialistInputError as exc:
        raise SpecialistValidationError(str(exc)) from exc

    row.workflow_mode = next_mode
    if payload.title is not None:
        row.title = payload.title
    if payload.language is not None:
        row.language = payload.language
    if payload.classification is not None:
        row.classification = payload.classification
    if payload.revision is not None:
        row.revision = payload.revision

    row.inputs_json = next_inputs
    row.results_json = _eval_to_results_dict(ev)
    row.preliminary_assumptions_json = ev.preliminary_assumptions
    row.status = ev.status
    row.checks_passed = ev.checks_passed
    row.blocked_missing_count = ev.blocked_missing_count
    row.failed_checks_count = ev.failed_checks_count
    row.version += 1
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    return get_specialist_detail(db, row.id)


def approve_specialist_assessment(
    db: Session,
    assessment_id: str,
    payload: SpecialistApproveRequest,
) -> SpecialistDetailOut:
    row = db.get(SpecialistAssessment, assessment_id)
    if row is None:
        raise SpecialistNotFoundError(f"Specialist assessment not found: {assessment_id}")
    row.ai_draft_status = "owner_approved"
    row.owner_approved_by = payload.approved_by.strip()
    row.owner_approved_at = utc_now()
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    return get_specialist_detail(db, row.id)


def export_specialist_deliverables(
    db: Session,
    settings: Settings,
    assessment_id: str,
    *,
    language: str | None = None,
) -> SpecialistExportOut:
    """Export immutable bilingual DOCX, PDF, and live-formula XLSX deliverables into 04_Engineering_Calculations with SHA-256."""
    row = db.scalars(
        select(SpecialistAssessment)
        .options(selectinload(SpecialistAssessment.project), selectinload(SpecialistAssessment.deliverables))
        .where(SpecialistAssessment.id == assessment_id)
    ).first()
    if row is None:
        raise SpecialistNotFoundError(f"Specialist assessment not found: {assessment_id}")
    project = row.project
    if project is None:
        raise ProjectNotFoundError(f"Project not found for assessment {assessment_id}")

    lang_val = language or row.language or "ar"
    if lang_val not in {"ar", "en"}:
        raise SpecialistValidationError("Language must be 'ar' or 'en'.")

    next_export = row.export_version + 1
    short_id = row.id[:8]
    rel_docx = f"04_Engineering_Calculations/{row.domain}_{short_id}_v{row.version}_e{next_export}_{lang_val}.docx"
    rel_pdf = f"04_Engineering_Calculations/{row.domain}_{short_id}_v{row.version}_e{next_export}_{lang_val}.pdf"
    rel_xlsx = f"04_Engineering_Calculations/{row.domain}_{short_id}_v{row.version}_e{next_export}_{lang_val}.xlsx"

    p_docx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_docx)
    p_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_pdf)
    p_xlsx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_xlsx)

    res = dict(row.results_json or {})
    render_data = SpecialistRenderData(
        project_code=project.code,
        project_name=project.name,
        title=row.title,
        domain=row.domain,
        workflow_mode=row.workflow_mode,
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
    )

    generate_specialist_docx(p_docx, render_data)
    generate_specialist_pdf(p_pdf, render_data)
    generate_specialist_xlsx(p_xlsx, render_data)

    docx_deliv = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        assessment_id=row.id,
        title=f"{row.title} ({row.revision} e{next_export} — DOCX {lang_val.upper()})",
        deliverable_type=f"specialist_{row.domain}",
        discipline=row.domain,
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
        summary=f"Step 18 {row.domain.upper()} DOCX export (standards={row.standards_status})",
    )
    pdf_deliv = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        assessment_id=row.id,
        title=f"{row.title} ({row.revision} e{next_export} — PDF {lang_val.upper()})",
        deliverable_type=f"specialist_{row.domain}",
        discipline=row.domain,
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
        summary=f"Step 18 {row.domain.upper()} PDF export (standards={row.standards_status})",
    )
    xlsx_deliv = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        assessment_id=row.id,
        title=f"{row.title} ({row.revision} e{next_export} — XLSX {lang_val.upper()})",
        deliverable_type=f"specialist_{row.domain}",
        discipline=row.domain,
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
        summary=f"Step 18 {row.domain.upper()} live XLSX export (standards={row.standards_status})",
    )
    db.add_all([docx_deliv, pdf_deliv, xlsx_deliv])
    row.export_version = next_export
    if row.status == "evaluated":
        row.status = "exported"
    row.updated_at = utc_now()
    db.add(row)
    db.commit()

    return SpecialistExportOut(
        assessment=get_specialist_detail(db, row.id),
        docx_deliverable=_to_deliverable_out(docx_deliv),
        pdf_deliverable=_to_deliverable_out(pdf_deliv),
        xlsx_deliverable=_to_deliverable_out(xlsx_deliv),
    )
