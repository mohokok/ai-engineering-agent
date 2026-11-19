"""Task engine service: assignment intake, Orchestrator v0 execution, history, and failure logging."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.orchestrator import run_orchestrator_v0
from app.db.base import utc_now
from app.db.models import AuditLog, Project, ProjectFile, Task, TaskStep
from app.providers.base import ProviderError, TokenUsage, sanitize_secret_text
from app.providers.secrets import SecretStore
from app.schemas.tasks import (
    AttachedFileSummary,
    OrchestratorUnderstanding,
    TaskCreateRequest,
    TaskDetailOut,
    TaskLogEntryOut,
    TaskStepOut,
    TaskSummaryOut,
    TaskTokenUsageOut,
)
from app.services.projects import ProjectNotFoundError
from app.services.provider_settings import _load_provider_config


class TaskNotFoundError(LookupError):
    """Raised when a requested task ID does not exist."""


class TaskAttachmentError(ValueError):
    """Raised when an attached file ID does not exist or belongs to a different project."""


def derive_task_title(prompt: str, explicit_title: str | None) -> str:
    """Return explicit title or derive a concise summary title from assignment prompt text."""
    if explicit_title and explicit_title.strip():
        return explicit_title.strip()[:255]
    first_line = ""
    for line in prompt.splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            first_line = cleaned
            break
    if not first_line:
        first_line = " ".join(prompt.split())
    if len(first_line) <= 90:
        return first_line
    return first_line[:87].rstrip() + "..."


def _token_usage_dict(usage: TokenUsage, latency_ms: int = 0) -> dict[str, int]:
    return {
        "prompt_tokens": int(usage.prompt_tokens),
        "output_tokens": int(usage.output_tokens),
        "total_tokens": int(usage.total_tokens),
        "thoughts_tokens": int(usage.thoughts_tokens),
        "cached_tokens": int(usage.cached_tokens),
        "latency_ms": int(latency_ms),
    }


def _to_attached_file_summary(pf: ProjectFile) -> AttachedFileSummary:
    return AttachedFileSummary(
        file_id=pf.id,
        filename=pf.original_filename,
        folder_name=pf.folder_name,
        extension=pf.extension,
        mime_type=pf.mime_type,
        size_bytes=pf.size_bytes,
        sha256=pf.sha256,
        current_version=pf.current_version,
    )


def _resolve_attached_files(
    db: Session,
    project_id: str,
    file_ids: list[str],
) -> list[AttachedFileSummary]:
    if not file_ids:
        return []
    rows = db.scalars(
        select(ProjectFile).where(ProjectFile.id.in_(file_ids))
    ).all()
    by_id = {row.id: row for row in rows}
    resolved: list[AttachedFileSummary] = []
    for file_id in file_ids:
        pf = by_id.get(file_id)
        if pf is None:
            raise TaskAttachmentError(f"Attached file '{file_id}' was not found.")
        if pf.project_id != project_id:
            raise TaskAttachmentError(
                f"Attached file '{pf.original_filename}' does not belong to the selected project."
            )
        resolved.append(_to_attached_file_summary(pf))
    return resolved


def _parse_structured_output(raw: dict | None) -> OrchestratorUnderstanding | None:
    if not isinstance(raw, dict):
        return None
    try:
        return OrchestratorUnderstanding.model_validate(raw)
    except Exception:
        return None


def _parse_token_usage(raw: dict | None) -> TaskTokenUsageOut:
    if not isinstance(raw, dict):
        return TaskTokenUsageOut()
    return TaskTokenUsageOut(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        total_tokens=int(raw.get("total_tokens") or 0),
        thoughts_tokens=int(raw.get("thoughts_tokens") or 0),
        cached_tokens=int(raw.get("cached_tokens") or 0),
        latency_ms=int(raw.get("latency_ms") or 0),
    )


def _to_task_summary(
    task: Task,
    *,
    project_code: str,
    project_name: str,
    step_count: int,
) -> TaskSummaryOut:
    return TaskSummaryOut(
        id=task.id,
        project_id=task.project_id,
        project_code=project_code,
        project_name=project_name,
        title=task.title,
        prompt=task.prompt,
        task_type=task.task_type,
        status=task.status,
        classification=task.classification,
        complexity=task.complexity,
        provider_name=task.provider_name,
        model_name=task.model_name,
        plan_summary=task.plan_summary,
        result_summary=task.result_summary,
        error_message=task.error_message,
        attached_file_ids=list(task.attached_file_ids_json or []),
        structured_output=_parse_structured_output(task.structured_output_json),
        token_usage=_parse_token_usage(task.token_usage_json),
        step_count=step_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


def _sanitize_exception_message(
    db: Session,
    secret_store: SecretStore,
    exc: Exception,
) -> str:
    active_key: str | None = None
    try:
        cfg = _load_provider_config(db)
        active_key = secret_store.get_api_key(cfg.active_provider)
    except Exception:
        active_key = None
    return sanitize_secret_text(str(exc), active_key) or exc.__class__.__name__


def create_and_run_assignment_task(
    db: Session,
    secret_store: SecretStore,
    payload: TaskCreateRequest,
    *,
    client_factory=None,
) -> TaskDetailOut:
    """Create a task record, execute Orchestrator v0 intake, and log success or failure."""
    project = db.get(Project, payload.project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{payload.project_id}' was not found.")

    attached_files = _resolve_attached_files(db, project.id, payload.attached_file_ids)
    now = utc_now()
    task_title = derive_task_title(payload.prompt, payload.title)

    task = Task(
        project_id=project.id,
        title=task_title,
        prompt=payload.prompt,
        task_type=payload.task_type,
        status="running",
        classification=payload.classification,
        complexity=payload.complexity,
        attached_file_ids_json=[item.file_id for item in attached_files],
        token_usage_json=_token_usage_dict(TokenUsage()),
    )
    db.add(task)
    db.flush()

    intake_step = TaskStep(
        task_id=task.id,
        step_order=1,
        module_name="assignment_intake",
        title="Validate assignment input & attached files",
        status="completed",
        input_payload={
            "project_id": project.id,
            "complexity": payload.complexity,
            "attached_file_ids": [item.file_id for item in attached_files],
        },
        output_payload={
            "attached_file_count": len(attached_files),
            "attached_files": [item.model_dump() for item in attached_files],
        },
        started_at=now,
        completed_at=now,
    )
    orchestrator_step = TaskStep(
        task_id=task.id,
        step_order=2,
        module_name="orchestrator_v0",
        title="Orchestrator v0: understand assignment & structure plan",
        status="running",
        input_payload={
            "complexity": payload.complexity,
            "attached_file_count": len(attached_files),
        },
        started_at=now,
    )
    db.add(intake_step)
    db.add(orchestrator_step)
    db.add(
        AuditLog(
            project_id=project.id,
            action="task.created",
            entity_type="task",
            entity_id=task.id,
            actor="owner",
            details_json={
                "title": task.title,
                "task_type": task.task_type,
                "complexity": payload.complexity,
                "attached_file_count": len(attached_files),
            },
        )
    )
    db.commit()

    try:
        understanding, response = run_orchestrator_v0(
            db,
            secret_store,
            project=project,
            task_id=task.id,
            assignment_prompt=payload.prompt,
            attached_files=attached_files,
            complexity=payload.complexity,
            classification=payload.classification,
            client_factory=client_factory,
        )
    except Exception as exc:
        safe_error = _sanitize_exception_message(db, secret_store, exc)
        usage = exc.usage if isinstance(exc, ProviderError) else TokenUsage()
        failed_at = utc_now()
        usage_dict = _token_usage_dict(usage)

        orchestrator_step.status = "failed"
        orchestrator_step.notes = safe_error
        orchestrator_step.output_payload = {
            "error_type": exc.__class__.__name__,
            "error": safe_error,
            "usage": usage_dict,
        }
        orchestrator_step.completed_at = failed_at

        task.status = "failed"
        task.error_message = safe_error
        task.token_usage_json = usage_dict
        task.completed_at = failed_at

        db.add(
            AuditLog(
                project_id=project.id,
                action="task.failed",
                entity_type="task",
                entity_id=task.id,
                actor="orchestrator_v0",
                details_json={
                    "stage": "orchestrator_v0",
                    "error_type": exc.__class__.__name__,
                    "error": safe_error,
                    "total_tokens": usage.total_tokens,
                },
            )
        )
        db.commit()
        return get_task_detail(db, task.id)

    finished_at = utc_now()
    structured_dict = understanding.model_dump()
    usage_dict = _token_usage_dict(response.usage, latency_ms=response.latency_ms)

    orchestrator_step.status = "completed"
    orchestrator_step.notes = understanding.restated_assignment
    orchestrator_step.output_payload = {
        "provider": response.provider,
        "model": response.model,
        "understanding": structured_dict,
        "usage": usage_dict,
    }
    orchestrator_step.completed_at = finished_at

    task.status = "awaiting_clarification" if understanding.clarification_needed else "completed"
    task.classification = understanding.classification
    task.provider_name = response.provider
    task.model_name = response.model
    task.structured_output_json = structured_dict
    task.token_usage_json = usage_dict
    task.plan_summary = understanding.restated_assignment
    task.result_summary = (
        f"{understanding.primary_discipline} | "
        f"{len(understanding.expected_deliverables)} deliverables | "
        f"clarification_needed={understanding.clarification_needed}"
    )
    task.completed_at = finished_at

    db.add(
        AuditLog(
            project_id=project.id,
            action="task.completed",
            entity_type="task",
            entity_id=task.id,
            actor="orchestrator_v0",
            details_json={
                "status": task.status,
                "language_detected": understanding.language_detected,
                "primary_discipline": understanding.primary_discipline,
                "deliverables_count": len(understanding.expected_deliverables),
                "clarification_needed": understanding.clarification_needed,
                "question_count": len(understanding.clarifying_questions),
                "provider": response.provider,
                "model": response.model,
                "total_tokens": response.usage.total_tokens,
            },
        )
    )
    db.commit()
    return get_task_detail(db, task.id)


def list_tasks(
    db: Session,
    *,
    project_id: str | None = None,
    status_filter: str | None = None,
) -> list[TaskSummaryOut]:
    """Return task history rows ordered newest first, with optional project/status filters."""
    stmt = (
        select(Task, Project.code, Project.name)
        .join(Project, Task.project_id == Project.id)
        .options(selectinload(Task.steps))
        .order_by(Task.created_at.desc())
    )
    if project_id and project_id.strip():
        stmt = stmt.where(Task.project_id == project_id.strip())
    if status_filter and status_filter.strip():
        stmt = stmt.where(Task.status == status_filter.strip())

    rows = db.execute(stmt).all()
    return [
        _to_task_summary(
            task,
            project_code=project_code,
            project_name=project_name,
            step_count=len(task.steps),
        )
        for task, project_code, project_name in rows
    ]


def get_task_detail(db: Session, task_id: str) -> TaskDetailOut:
    """Load one task with its ordered execution steps, attached files, and audit logs."""
    stmt = (
        select(Task, Project.code, Project.name)
        .join(Project, Task.project_id == Project.id)
        .options(selectinload(Task.steps))
        .where(Task.id == task_id)
    )
    row = db.execute(stmt).first()
    if row is None:
        raise TaskNotFoundError(f"Task '{task_id}' was not found.")
    task, project_code, project_name = row

    ordered_steps = sorted(task.steps, key=lambda item: item.step_order)
    file_ids = list(task.attached_file_ids_json or [])
    attached_files: list[AttachedFileSummary] = []
    if file_ids:
        file_rows = db.scalars(
            select(ProjectFile).where(ProjectFile.id.in_(file_ids))
        ).all()
        by_id = {pf.id: pf for pf in file_rows}
        attached_files = [
            _to_attached_file_summary(by_id[fid]) for fid in file_ids if fid in by_id
        ]

    # Collect task lifecycle logs and any provider usage ledger entries tied to this task.
    task_audits = db.scalars(
        select(AuditLog)
        .where(
            (
                (AuditLog.entity_type == "task")
                & (AuditLog.entity_id == task.id)
            )
            | (
                (AuditLog.entity_type == "provider_usage")
                & (AuditLog.project_id == task.project_id)
            )
        )
        .order_by(AuditLog.created_at.asc())
    ).all()

    filtered_logs: list[TaskLogEntryOut] = []
    for entry in task_audits:
        if entry.entity_type == "provider_usage":
            details = entry.details_json if isinstance(entry.details_json, dict) else {}
            if details.get("task_id") != task.id:
                continue
        filtered_logs.append(
            TaskLogEntryOut(
                id=entry.id,
                action=entry.action,
                entity_type=entry.entity_type,
                actor=entry.actor,
                details_json=entry.details_json,
                created_at=entry.created_at,
            )
        )

    summary = _to_task_summary(
        task,
        project_code=project_code,
        project_name=project_name,
        step_count=len(ordered_steps),
    )
    return TaskDetailOut(
        **summary.model_dump(),
        attached_files=attached_files,
        steps=[
            TaskStepOut(
                id=step.id,
                task_id=step.task_id,
                step_order=step.step_order,
                module_name=step.module_name,
                title=step.title,
                status=step.status,
                input_payload=step.input_payload,
                output_payload=step.output_payload,
                notes=step.notes,
                started_at=step.started_at,
                completed_at=step.completed_at,
                created_at=step.created_at,
            )
            for step in ordered_steps
        ],
        logs=filtered_logs,
    )
