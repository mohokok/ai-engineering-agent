"""Step 16 API endpoints for deterministic WBS & CPM project schedules, baseline comparison, AI approval, and Gantt PDF/XLSX exports."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.planning import (
    PlanningPresetListResponse,
    ProjectScheduleDetailOut,
    ProjectScheduleExportOut,
    ProjectScheduleListResponse,
    ScheduleApproveRequest,
    ScheduleCreateRequest,
    ScheduleExportRequest,
)
from app.services.planning import (
    ScheduleConflictError,
    ScheduleNotFoundError,
    ScheduleValidationError,
    approve_schedule_draft,
    create_project_schedule,
    export_schedule_deliverables,
    get_schedule_detail,
    list_planning_presets,
    list_project_schedules,
    set_schedule_as_baseline,
)
from app.services.projects import ProjectNotFoundError

router = APIRouter(tags=["planning"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("/planning/presets", response_model=PlanningPresetListResponse)
def list_planning_presets_endpoint() -> PlanningPresetListResponse:
    """Return synthetic clinic planning presets (0% client data, owner-supplied durations)."""
    return list_planning_presets()


@router.post(
    "/projects/{project_id}/schedules",
    response_model=ProjectScheduleDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_schedule_endpoint(
    project_id: str,
    payload: ScheduleCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ProjectScheduleDetailOut:
    """Create and deterministically evaluate a WBS & CPM schedule plus initial 03_Analysis Gantt PDF+XLSX exports (default 0 tokens)."""
    try:
        return create_project_schedule(
            db,
            _get_settings(request),
            _get_secret_store(request),
            project_id,
            payload,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ScheduleConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/projects/{project_id}/schedules", response_model=ProjectScheduleListResponse)
def list_project_schedules_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectScheduleListResponse:
    """List persisted Step 16 schedules for a project ordered newest first."""
    try:
        return list_project_schedules(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/schedules/{schedule_id}", response_model=ProjectScheduleDetailOut)
def get_schedule_detail_endpoint(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> ProjectScheduleDetailOut:
    """Retrieve complete WBS, CPM dates, critical path, blocked branches, baseline variances, and deliverables."""
    try:
        return get_schedule_detail(db, schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/schedules/{schedule_id}/set-baseline", response_model=ProjectScheduleDetailOut)
def set_schedule_baseline_endpoint(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> ProjectScheduleDetailOut:
    """Lock an evaluated schedule as the active project baseline."""
    try:
        return set_schedule_as_baseline(db, schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/schedules/{schedule_id}/approve", response_model=ProjectScheduleDetailOut)
def approve_schedule_draft_endpoint(
    schedule_id: str,
    payload: ScheduleApproveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ProjectScheduleDetailOut:
    """Owner sign-off clearing UNVERIFIED AI DRAFT narrative tag."""
    try:
        return approve_schedule_draft(db, _get_settings(request), schedule_id, payload)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScheduleConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/schedules/{schedule_id}/export",
    response_model=ProjectScheduleExportOut,
    status_code=status.HTTP_201_CREATED,
)
def export_schedule_deliverables_endpoint(
    schedule_id: str,
    request: Request,
    payload: ScheduleExportRequest | None = None,
    db: Session = Depends(get_db),
) -> ProjectScheduleExportOut:
    """Export immutable SHA-256 versioned Gantt PDF & live-formula XLSX into 03_Analysis."""
    try:
        return export_schedule_deliverables(db, _get_settings(request), schedule_id, payload)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScheduleConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
