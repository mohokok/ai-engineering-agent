"""Step 18 API endpoints for HVAC, Fire, and Healthcare input preparation & output checking."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.specialist import (
    SpecialistApproveRequest,
    SpecialistAssessmentCreateRequest,
    SpecialistAssessmentUpdateRequest,
    SpecialistDetailOut,
    SpecialistExportOut,
    SpecialistExportRequest,
    SpecialistListResponse,
    SpecialistPresetListResponse,
)
from app.services.projects import ProjectNotFoundError
from app.services.specialist import (
    SpecialistNotFoundError,
    SpecialistValidationError,
    approve_specialist_assessment,
    create_specialist_assessment,
    export_specialist_deliverables,
    get_specialist_detail,
    list_project_specialist_assessments,
    list_specialist_presets,
    update_specialist_assessment,
)

router = APIRouter(tags=["specialist-engineering"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("/specialist-assessments/presets", response_model=SpecialistPresetListResponse)
def list_specialist_presets_endpoint() -> SpecialistPresetListResponse:
    """Return synthetic HVAC, Fire & Healthcare presets (strictly preliminary, zero client data)."""
    return list_specialist_presets()


@router.post(
    "/projects/{project_id}/specialist-assessments",
    response_model=SpecialistDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_specialist_assessment_endpoint(
    project_id: str,
    payload: SpecialistAssessmentCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SpecialistDetailOut:
    """Create and deterministically run Step 18 input preparation / output checks (0 AI tokens default)."""
    try:
        return create_specialist_assessment(
            db,
            _get_secret_store(request),
            project_id,
            payload,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpecialistValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/projects/{project_id}/specialist-assessments", response_model=SpecialistListResponse)
def list_project_specialist_assessments_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> SpecialistListResponse:
    """List HVAC, Fire & Healthcare assessments belonging to a project."""
    try:
        return list_project_specialist_assessments(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/specialist-assessments/{assessment_id}", response_model=SpecialistDetailOut)
def get_specialist_detail_endpoint(
    assessment_id: str,
    db: Session = Depends(get_db),
) -> SpecialistDetailOut:
    """Get complete Step 18 assessment payload, checks, and linked SHA-256 deliverables."""
    try:
        return get_specialist_detail(db, assessment_id)
    except SpecialistNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/specialist-assessments/{assessment_id}", response_model=SpecialistDetailOut)
def update_specialist_endpoint(
    assessment_id: str,
    payload: SpecialistAssessmentUpdateRequest,
    db: Session = Depends(get_db),
) -> SpecialistDetailOut:
    """Update assessment inputs/references/mode and deterministically re-compute (increments version)."""
    try:
        return update_specialist_assessment(db, assessment_id, payload)
    except SpecialistNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpecialistValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/specialist-assessments/{assessment_id}/approve", response_model=SpecialistDetailOut)
def approve_specialist_endpoint(
    assessment_id: str,
    payload: SpecialistApproveRequest,
    db: Session = Depends(get_db),
) -> SpecialistDetailOut:
    """Record explicit owner / licensed engineer approval clearing UNVERIFIED AI DRAFT state."""
    try:
        return approve_specialist_assessment(db, assessment_id, payload)
    except SpecialistNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/specialist-assessments/{assessment_id}/export",
    response_model=SpecialistExportOut,
    status_code=status.HTTP_201_CREATED,
)
def export_specialist_endpoint(
    assessment_id: str,
    payload: SpecialistExportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SpecialistExportOut:
    """Export immutable bilingual DOCX, PDF, and live-formula XLSX into 04_Engineering_Calculations."""
    try:
        return export_specialist_deliverables(
            db,
            _get_settings(request),
            assessment_id,
            language=payload.language,
        )
    except (ProjectNotFoundError, SpecialistNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpecialistValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
