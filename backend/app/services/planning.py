"""Step 16 project planning service: project entity provenance, CPM evaluation, baseline comparison, AI gating, SHA-256 PDF/XLSX exports."""

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
    ProjectSchedule,
    ResearchSource,
    Specification,
    Task,
)
from app.providers.secrets import SecretStore
from app.schemas.planning import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NOT_PROVIDED_LABEL,
    PlanningPresetListResponse,
    ProjectScheduleDetailOut,
    ProjectScheduleExportOut,
    ProjectScheduleListResponse,
    ProjectScheduleSummaryOut,
    ScheduleApproveRequest,
    ScheduleCreateRequest,
    ScheduleExportRequest,
    ScheduleResultOut,
    WbsItemIn,
    WorkCalendarIn,
)
from app.schemas.reports import ReportLanguage
from app.schemas.tasks import TaskTokenUsageOut
from app.services.calc_export import sha256_file
from app.services.planning_export import ScheduleRenderData, generate_schedule_pdf, generate_schedule_xlsx
from app.services.projects import ProjectNotFoundError
from app.services.review_reports import _to_deliverable_out
from app.services.workspace import resolve_project_file_path
from app.skills.planning import (
    PlanningInputError,
    draft_schedule_narrative_with_ai,
    evaluate_project_schedule,
    get_synthetic_planning_presets,
)

_URL_RE = re.compile(r"https?://[^\s,;\"')>\]]+", re.IGNORECASE)


class ScheduleNotFoundError(LookupError):
    """Raised when a requested project schedule ID does not exist."""


class ScheduleValidationError(ValueError):
    """Raised when WBS, dependencies, calendar, or project references violate Step 16 rules."""


class ScheduleConflictError(FileExistsError):
    """Raised when writing an immutable versioned schedule export collides on disk."""


def _ai_draft_label(ai_draft_status: str, language: str, approved_by: str | None) -> str:
    if ai_draft_status == "unverified_ai_draft":
        return AI_UNVERIFIED_DRAFT_LABEL_AR if language == "ar" else AI_UNVERIFIED_DRAFT_LABEL_EN
    if ai_draft_status == "owner_approved":
        who = approved_by or "Owner"
        return (
            f"ملخص الذكاء الاصطناعي — مُعتمَد من المالك ({who})"
            if language == "ar"
            else f"AI Summary — Owner Approved ({who})"
        )
    return (
        "حساب حتمي للمسار الحرج والتقويم (0 توكن)"
        if language == "ar"
        else "Deterministic CPM & Calendar (0 AI tokens)"
    )


def _to_summary_out(row: ProjectSchedule) -> ProjectScheduleSummaryOut:
    wbs = row.wbs_items_json if isinstance(row.wbs_items_json, list) else []
    acts = row.activities_json if isinstance(row.activities_json, list) else []
    res_raw = row.schedule_result_json if isinstance(row.schedule_result_json, dict) else {}
    return ProjectScheduleSummaryOut(
        id=row.id,
        project_id=row.project_id,
        project_code=row.project.code if row.project else "",
        project_name=row.project.name if row.project else "",
        task_id=row.task_id,
        baseline_schedule_id=row.baseline_schedule_id,
        title=row.title,
        discipline=row.discipline,
        language=row.language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=row.export_version,
        status=row.status,
        is_baseline=bool(row.is_baseline),
        start_date=row.start_date,
        use_ai=bool(row.use_ai),
        ai_draft_status=row.ai_draft_status,
        ai_draft_label=_ai_draft_label(row.ai_draft_status, row.language, row.owner_approved_by),
        owner_approved_by=row.owner_approved_by,
        owner_approved_at=row.owner_approved_at,
        wbs_count=len(wbs),
        activities_count=len(acts),
        total_duration_wd=res_raw.get("total_duration_wd"),
        critical_path_complete=bool(res_raw.get("critical_path_complete", True)),
        tokens_used=int(row.tokens_used or 0),
        summary=row.summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail_out(row: ProjectSchedule) -> ProjectScheduleDetailOut:
    summary_out = _to_summary_out(row)
    cal = WorkCalendarIn.model_validate(row.calendar_json or {})
    wbs = [WbsItemIn.model_validate(w) for w in (row.wbs_items_json or [])]
    result = ScheduleResultOut.model_validate(row.schedule_result_json or {})
    raw_usage = row.token_usage_json if isinstance(row.token_usage_json, dict) else {}
    usage = TaskTokenUsageOut(
        prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
        output_tokens=int(raw_usage.get("output_tokens") or 0),
        total_tokens=int(raw_usage.get("total_tokens") or row.tokens_used or 0),
        thoughts_tokens=int(raw_usage.get("thoughts_tokens") or 0),
        cached_tokens=int(raw_usage.get("cached_tokens") or 0),
    )
    deliverables = [_to_deliverable_out(d) for d in sorted(row.deliverables, key=lambda x: x.created_at, reverse=True)]
    return ProjectScheduleDetailOut(
        **summary_out.model_dump(),
        calendar=cal,
        wbs_items=wbs,
        schedule_result=result,
        token_usage=usage,
        deliverables=deliverables,
    )


def _validate_schedule_sources(
    db: Session,
    *,
    project_id: str,
    payload: ScheduleCreateRequest,
) -> ProjectSchedule | None:
    """Validate task, optional baseline schedule, and every activity's BOQ/Spec/Calc/ResearchSource provenance."""
    if payload.task_id:
        task = db.get(Task, payload.task_id)
        if task is None or task.project_id != project_id:
            raise ScheduleValidationError(f"Task '{payload.task_id}' does not belong to project '{project_id}'.")

    baseline_row: ProjectSchedule | None = None
    if payload.baseline_schedule_id:
        baseline_row = db.get(ProjectSchedule, payload.baseline_schedule_id)
        if baseline_row is None or baseline_row.project_id != project_id:
            raise ScheduleValidationError(
                f"Baseline schedule '{payload.baseline_schedule_id}' does not belong to project '{project_id}'."
            )

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

    for url_hit in _URL_RE.findall(payload.calendar.source_ref or ""):
        if url_hit.lower() not in reviewed_source_urls:
            raise ScheduleValidationError(
                f"Calendar source_ref URL '{url_hit}' is not registered as a reviewed ResearchSource."
            )

    for act in payload.activities:
        owner_lbl = f"Activity '{act.activity_id}'"
        if act.source_kind == "boq_item":
            if not act.boq_item_id or act.boq_item_id not in project_boq_ids:
                raise ScheduleValidationError(
                    f"{owner_lbl}: boq_item_id '{act.boq_item_id}' is missing or does not belong to project '{project_id}'."
                )
        elif act.boq_item_id and act.boq_item_id not in project_boq_ids:
            raise ScheduleValidationError(
                f"{owner_lbl}: linked boq_item_id '{act.boq_item_id}' does not belong to project '{project_id}'."
            )

        if act.source_kind == "specification":
            if not act.specification_id or act.specification_id not in project_spec_ids:
                raise ScheduleValidationError(
                    f"{owner_lbl}: specification_id '{act.specification_id}' is missing or invalid for project '{project_id}'."
                )
        elif act.specification_id and act.specification_id not in project_spec_ids:
            raise ScheduleValidationError(
                f"{owner_lbl}: linked specification_id '{act.specification_id}' does not belong to project '{project_id}'."
            )

        if act.source_kind == "calculation":
            if not act.calculation_id or act.calculation_id not in project_calc_ids:
                raise ScheduleValidationError(
                    f"{owner_lbl}: calculation_id '{act.calculation_id}' is missing or invalid for project '{project_id}'."
                )
        elif act.calculation_id and act.calculation_id not in project_calc_ids:
            raise ScheduleValidationError(
                f"{owner_lbl}: linked calculation_id '{act.calculation_id}' does not belong to project '{project_id}'."
            )

        if act.source_kind == "research_source":
            if not act.research_source_id:
                raise ScheduleValidationError(f"{owner_lbl}: source_kind='research_source' requires research_source_id.")
            rs = project_sources.get(act.research_source_id)
            if rs is None or not rs.reviewed or rs.access_status not in {"accessible", "owner_provided"}:
                raise ScheduleValidationError(
                    f"{owner_lbl}: research_source_id '{act.research_source_id}' is missing or not reviewed/accessible."
                )
        elif act.research_source_id:
            rs = project_sources.get(act.research_source_id)
            if rs is None or not rs.reviewed or rs.access_status not in {"accessible", "owner_provided"}:
                raise ScheduleValidationError(
                    f"{owner_lbl}: linked research_source_id '{act.research_source_id}' must be reviewed/accessible."
                )

        for url_hit in _URL_RE.findall(act.source_ref or ""):
            if url_hit.lower() not in reviewed_source_urls:
                raise ScheduleValidationError(
                    f"{owner_lbl}: URL '{url_hit}' is not registered as a reviewed ResearchSource for this project."
                )

    return baseline_row


def _deterministic_summary(res: ScheduleResultOut, language: ReportLanguage) -> str:
    if language == "ar":
        if res.critical_path_complete:
            return (
                f"المدة الكلية = {res.total_duration_wd} يوم عمل؛ البداية الفعالة = {res.effective_start_date} "
                f"والنهاية المتوقعة = {res.project_finish_date}. المسار الحرج: {', '.join(res.critical_path_ids)}."
            )
        return (
            f"الجدول يحتوي على {len(res.missing_duration_flags)} نشاط بمدة '{NOT_PROVIDED_LABEL}' — "
            f"تم إيقاف حساب المسار الحرج للفروع المتأثرة ({len(res.blocked_activity_ids)} نشاط متوقف)."
        )
    if res.critical_path_complete:
        return (
            f"Total project duration = {res.total_duration_wd} working days ({res.effective_start_date} -> "
            f"{res.project_finish_date}). Critical path: {', '.join(res.critical_path_ids)}."
        )
    return (
        f"Schedule contains {len(res.missing_duration_flags)} activity/activities with '{NOT_PROVIDED_LABEL}' duration — "
        f"critical path computation blocked on affected branch ({len(res.blocked_activity_ids)} blocked activities)."
    )


def _write_versioned_schedule_files(
    settings: Settings,
    *,
    project: Project,
    row: ProjectSchedule,
    language: ReportLanguage,
    export_ver: int,
) -> tuple[Deliverable, Deliverable]:
    wbs = [WbsItemIn.model_validate(w) for w in (row.wbs_items_json or [])]
    result = ScheduleResultOut.model_validate(row.schedule_result_json or {})

    short_id = row.id.replace("-", "")[:8]
    rel_pdf = f"03_Analysis/sched_{short_id}_v{row.version}_e{export_ver}_{language}.pdf"
    rel_xlsx = f"03_Analysis/sched_{short_id}_v{row.version}_e{export_ver}_{language}.xlsx"
    rel_json = f"03_Analysis/sched_{short_id}_v{row.version}_e{export_ver}_{language}.json"

    path_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_pdf)
    path_xlsx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_xlsx)
    path_json = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_json)

    for target in (path_pdf, path_xlsx, path_json):
        if target.exists():
            raise ScheduleConflictError(f"Refusing to overwrite existing schedule deliverable: {target.name}")

    render_data = ScheduleRenderData(
        project_code=project.code,
        project_name=project.name,
        title=row.title,
        discipline=row.discipline,
        language=language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=export_ver,
        is_baseline=bool(row.is_baseline),
        issued_at_iso=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        use_ai=bool(row.use_ai),
        ai_draft_status=row.ai_draft_status,
        owner_approved_by=row.owner_approved_by,
        owner_approved_at_iso=row.owner_approved_at.isoformat() if row.owner_approved_at else None,
        summary=row.summary,
        wbs_items=wbs,
        result=result,
    )

    generate_schedule_pdf(path_pdf, render_data)
    generate_schedule_xlsx(path_xlsx, render_data)
    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(
        json.dumps(
            {
                "schedule_id": row.id,
                "project_id": project.id,
                "title": row.title,
                "discipline": row.discipline,
                "language": language,
                "classification": row.classification,
                "version": row.version,
                "export_version": export_ver,
                "is_baseline": row.is_baseline,
                "baseline_schedule_id": row.baseline_schedule_id,
                "calendar": row.calendar_json,
                "wbs_items": row.wbs_items_json,
                "activities": row.activities_json,
                "schedule_result": row.schedule_result_json,
                "files": {
                    "pdf": {"relative_path": rel_pdf, "sha256": sha256_file(path_pdf)},
                    "xlsx": {"relative_path": rel_xlsx, "sha256": sha256_file(path_xlsx)},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    deliv_pdf = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        schedule_id=row.id,
        title=f"{row.title} ({row.revision} v{export_ver} — Gantt PDF {language.upper()})",
        deliverable_type="project_schedule",
        discipline=row.discipline,
        format="pdf",
        classification=row.classification,
        status="issued",
        version=export_ver,
        folder_name="03_Analysis",
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
        schedule_id=row.id,
        title=f"{row.title} ({row.revision} v{export_ver} — CPM XLSX {language.upper()})",
        deliverable_type="project_schedule",
        discipline=row.discipline,
        format="xlsx",
        classification=row.classification,
        status="issued",
        version=export_ver,
        folder_name="03_Analysis",
        filename=path_xlsx.name,
        relative_path=rel_xlsx,
        mime_type=mime_xlsx,
        size_bytes=path_xlsx.stat().st_size,
        sha256=sha256_file(path_xlsx),
        summary=row.summary,
    )
    return deliv_pdf, deliv_xlsx


def create_project_schedule(
    db: Session,
    settings: Settings,
    secret_store: SecretStore,
    project_id: str,
    payload: ScheduleCreateRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> ProjectScheduleDetailOut:
    """Create, deterministically evaluate (0 AI tokens default), optionally baseline-compare, and export Gantt PDF+XLSX."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    baseline_row = _validate_schedule_sources(db, project_id=project_id, payload=payload)
    baseline_res = (
        ScheduleResultOut.model_validate(baseline_row.schedule_result_json or {})
        if baseline_row is not None
        else None
    )

    try:
        result = evaluate_project_schedule(
            start_date=payload.start_date,
            calendar=payload.calendar,
            wbs_items=payload.wbs_items,
            activities=payload.activities,
            baseline_result=baseline_res,
            baseline_schedule_id=baseline_row.id if baseline_row else None,
            baseline_title=baseline_row.title if baseline_row else None,
            strict=True,
        )
    except PlanningInputError as exc:
        raise ScheduleValidationError(str(exc)) from exc

    title = payload.title or (
        f"الجدول الزمني للمشروع — {project.name}"
        if payload.language == "ar"
        else f"Project Master Schedule — {project.name}"
    )

    tokens_used = 0
    ai_draft_status = "not_used"
    summary_text = _deterministic_summary(result, payload.language)
    usage_dict: dict[str, Any] = {
        "prompt_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "thoughts_tokens": 0,
        "cached_tokens": 0,
    }

    if payload.use_ai:
        ai_note, token_usage, _, _ = draft_schedule_narrative_with_ai(
            db,
            secret_store,
            project_id=project.id,
            project_code=project.code,
            project_name=project.name,
            title=title,
            language=payload.language,
            result=result,
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
        select(func.coalesce(func.max(ProjectSchedule.version), 0)).where(ProjectSchedule.project_id == project.id)
    )
    next_version = int(max_ver or 0) + 1

    if payload.set_as_baseline:
        existing_baselines = db.scalars(
            select(ProjectSchedule).where(ProjectSchedule.project_id == project.id, ProjectSchedule.is_baseline.is_(True))
        ).all()
        for old_b in existing_baselines:
            old_b.is_baseline = False

    row = ProjectSchedule(
        id=new_uuid(),
        project_id=project.id,
        task_id=payload.task_id,
        baseline_schedule_id=baseline_row.id if baseline_row else None,
        title=title,
        discipline=payload.discipline,
        language=payload.language,
        classification=payload.classification,
        revision=payload.revision,
        version=next_version,
        export_version=1,
        status="scheduled",
        is_baseline=bool(payload.set_as_baseline),
        start_date=result.project_start_date,
        use_ai=bool(payload.use_ai),
        ai_draft_status=ai_draft_status,
        tokens_used=tokens_used,
        token_usage_json=usage_dict,
        calendar_json=payload.calendar.model_dump(mode="json"),
        wbs_items_json=[w.model_dump(mode="json") for w in payload.wbs_items],
        activities_json=[a.model_dump(mode="json") for a in payload.activities],
        schedule_result_json=result.model_dump(mode="json"),
        summary=summary_text,
    )
    db.add(row)
    db.flush()

    deliv_pdf, deliv_xlsx = _write_versioned_schedule_files(
        settings,
        project=project,
        row=row,
        language=payload.language,
        export_ver=1,
    )
    db.add_all([deliv_pdf, deliv_xlsx])
    db.add(
        AuditLog(
            project_id=project.id,
            actor="planning-engine" if not payload.use_ai else "planning-ai-draft",
            action="project_schedule_created",
            entity_type="project_schedule",
            entity_id=row.id,
            details_json={
                "version": row.version,
                "language": row.language,
                "is_baseline": row.is_baseline,
                "baseline_schedule_id": row.baseline_schedule_id,
                "critical_path_complete": result.critical_path_complete,
                "total_duration_wd": result.total_duration_wd,
                "tokens_used": tokens_used,
                "pdf_sha256": deliv_pdf.sha256,
                "xlsx_sha256": deliv_xlsx.sha256,
            },
        )
    )
    db.commit()
    return get_schedule_detail(db, row.id)


def list_project_schedules(db: Session, project_id: str) -> ProjectScheduleListResponse:
    """List persisted Step 16 schedules for a project ordered newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(ProjectSchedule)
        .options(selectinload(ProjectSchedule.project))
        .where(ProjectSchedule.project_id == project_id)
        .order_by(ProjectSchedule.created_at.desc(), ProjectSchedule.version.desc())
    ).all()
    items = [_to_summary_out(r) for r in rows]
    return ProjectScheduleListResponse(schedules=items, total=len(items))


def get_schedule_detail(db: Session, schedule_id: str) -> ProjectScheduleDetailOut:
    """Retrieve complete WBS, CPM dates, critical path, baseline variances, and deliverables."""
    row = db.scalar(
        select(ProjectSchedule)
        .options(selectinload(ProjectSchedule.project), selectinload(ProjectSchedule.deliverables))
        .where(ProjectSchedule.id == schedule_id)
    )
    if row is None:
        raise ScheduleNotFoundError(f"Schedule '{schedule_id}' was not found.")
    return _to_detail_out(row)


def set_schedule_as_baseline(
    db: Session,
    schedule_id: str,
) -> ProjectScheduleDetailOut:
    """Designate an existing project schedule as the active project baseline."""
    row = db.scalar(
        select(ProjectSchedule)
        .options(selectinload(ProjectSchedule.project), selectinload(ProjectSchedule.deliverables))
        .where(ProjectSchedule.id == schedule_id)
    )
    if row is None:
        raise ScheduleNotFoundError(f"Schedule '{schedule_id}' was not found.")

    others = db.scalars(
        select(ProjectSchedule).where(ProjectSchedule.project_id == row.project_id, ProjectSchedule.is_baseline.is_(True))
    ).all()
    for other in others:
        other.is_baseline = False
    row.is_baseline = True

    db.add(
        AuditLog(
            project_id=row.project_id,
            actor="owner",
            action="project_schedule_set_baseline",
            entity_type="project_schedule",
            entity_id=row.id,
            details_json={"version": row.version, "title": row.title},
        )
    )
    db.commit()
    return get_schedule_detail(db, row.id)


def approve_schedule_draft(
    db: Session,
    settings: Settings,
    schedule_id: str,
    payload: ScheduleApproveRequest,
) -> ProjectScheduleDetailOut:
    """Record explicit owner approval clearing UNVERIFIED AI DRAFT tag on schedule narrative."""
    row = db.scalar(
        select(ProjectSchedule)
        .options(selectinload(ProjectSchedule.project), selectinload(ProjectSchedule.deliverables))
        .where(ProjectSchedule.id == schedule_id)
    )
    if row is None:
        raise ScheduleNotFoundError(f"Schedule '{schedule_id}' was not found.")

    approved_by = (payload.approved_by or "Owner").strip()
    now_ts = utc_now()
    row.ai_draft_status = "owner_approved"
    row.owner_approved_by = approved_by
    row.owner_approved_at = now_ts
    row.status = "owner_approved"

    if row.summary:
        cleaned = row.summary
        for tag in (f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] ", f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] "):
            if cleaned.startswith(tag):
                cleaned = cleaned[len(tag):]
        row.summary = cleaned

    if payload.export_after_approval and row.project is not None:
        row.export_version = int(row.export_version or 0) + 1
        d_pdf, d_xlsx = _write_versioned_schedule_files(
            settings,
            project=row.project,
            row=row,
            language=row.language,  # type: ignore[arg-type]
            export_ver=row.export_version,
        )
        db.add_all([d_pdf, d_xlsx])

    db.add(
        AuditLog(
            project_id=row.project_id,
            actor=approved_by,
            action="project_schedule_ai_approved",
            entity_type="project_schedule",
            entity_id=row.id,
            details_json={"approved_by": approved_by, "export_version": row.export_version},
        )
    )
    db.commit()
    return get_schedule_detail(db, row.id)


def export_schedule_deliverables(
    db: Session,
    settings: Settings,
    schedule_id: str,
    payload: ScheduleExportRequest | None = None,
) -> ProjectScheduleExportOut:
    """Export immutable SHA-256 versioned Gantt PDF & live-formula XLSX into 03_Analysis."""
    row = db.scalar(
        select(ProjectSchedule)
        .options(selectinload(ProjectSchedule.project), selectinload(ProjectSchedule.deliverables))
        .where(ProjectSchedule.id == schedule_id)
    )
    if row is None:
        raise ScheduleNotFoundError(f"Schedule '{schedule_id}' was not found.")
    if row.project is None:
        raise ProjectNotFoundError(f"Project '{row.project_id}' was not found.")

    lang: ReportLanguage = (payload.language if payload and payload.language else row.language)  # type: ignore[assignment]
    next_export = int(row.export_version or 0) + 1
    row.export_version = next_export

    deliv_pdf, deliv_xlsx = _write_versioned_schedule_files(
        settings,
        project=row.project,
        row=row,
        language=lang,
        export_ver=next_export,
    )
    db.add_all([deliv_pdf, deliv_xlsx])
    db.add(
        AuditLog(
            project_id=row.project_id,
            actor="owner-export",
            action="project_schedule_exported",
            entity_type="project_schedule",
            entity_id=row.id,
            details_json={
                "export_version": next_export,
                "language": lang,
                "pdf_sha256": deliv_pdf.sha256,
                "xlsx_sha256": deliv_xlsx.sha256,
            },
        )
    )
    db.commit()

    detail = get_schedule_detail(db, row.id)
    return ProjectScheduleExportOut(
        schedule=detail,
        pdf_deliverable=_to_deliverable_out(deliv_pdf),
        xlsx_deliverable=_to_deliverable_out(deliv_xlsx),
    )


def list_planning_presets() -> PlanningPresetListResponse:
    """Return synthetic clinic planning fixture presets (0% client data)."""
    return PlanningPresetListResponse(presets=get_synthetic_planning_presets())
