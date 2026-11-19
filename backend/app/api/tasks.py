"""Assignment submission, Orchestrator v0 intake, and Task History endpoints."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.providers.secrets import SecretStore
from app.schemas.tasks import TaskCreateRequest, TaskDetailOut, TaskListResponse
from app.services.projects import ProjectNotFoundError
from app.services.tasks import (
    TaskAttachmentError,
    TaskNotFoundError,
    create_and_run_assignment_task,
    get_task_detail,
    list_tasks,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.post("", response_model=TaskDetailOut, status_code=status.HTTP_201_CREATED)
def create_assignment_task_endpoint(
    payload: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailOut:
    """Create a natural-language assignment task and run Orchestrator v0 intake."""
    try:
        return create_and_run_assignment_task(
            db,
            _get_secret_store(request),
            payload,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TaskAttachmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=TaskListResponse)
def list_tasks_endpoint(
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> TaskListResponse:
    """List persisted assignment tasks ordered newest first."""
    tasks = list_tasks(db, project_id=project_id, status_filter=status_filter)
    return TaskListResponse(tasks=tasks, total=len(tasks))


@router.get("/{task_id}", response_model=TaskDetailOut)
def get_task_detail_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
) -> TaskDetailOut:
    """Return one task with its execution steps, attached file snapshots, and logs."""
    try:
        return get_task_detail(db, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
