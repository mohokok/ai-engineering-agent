"""Step 19 API endpoints for deterministic Structural Assessment Support & I/O Checking ONLY."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.structural import (
    StructuralApproveRequest,
    StructuralAssessmentCreateRequest,
    StructuralAssessmentUpdateRequest,
    StructuralDetailOut,
    StructuralExportOut,
    StructuralExportRequest,
    StructuralListResponse,
    StructuralPresetListResponse,
)
from app.services.projects import ProjectNotFoundError
from app.services.structural import (
    StructuralNotFoundError,
    StructuralValidationError,
    approve_structural_assessment,
    create_structural_assessment,
    export_structural_deliverables,
    get_structural_detail,
    list_project_structural_assessments,
    list_structural_presets,
    update_structural_assessment,
)

router = APIRouter(tags=["structural-engineering"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("/structural-assessments/presets", response_model=StructuralPresetListResponse)
def list_structural_presets_endpoint() -> StructuralPresetListResponse:
    """Return synthetic Step 19 structural checking presets (PRELIMINARY - for review by a licensed structural engineer)."""
    return list_structural_presets()


@router.post(
    "/projects/{project_id}/structural-assessments",
    response_model=StructuralDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_structural_assessment_endpoint(
    project_id: str,
    payload: StructuralAssessmentCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> StructuralDetailOut:
    """Create and run Step 19 structural takedown/combination/statics checks (0 AI tokens default)."""
    try:
        return create_structural_assessment(
            db,
            _get_secret_store(request),
            project_id,
            payload,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StructuralValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/projects/{project_id}/structural-assessments", response_model=StructuralListResponse)
def list_project_structural_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> StructuralListResponse:
    """List Step 19 structural assessments belonging to a project."""
    try:
        return list_project_structural_assessments(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/structural-assessments/{assessment_id}", response_model=StructuralDetailOut)
def get_structural_detail_endpoint(
    assessment_id: str,
    db: Session = Depends(get_db),
) -> StructuralDetailOut:
    """Retrieve complete Step 19 structural assessment with prepared inputs, checks, references, and SHA-256 deliverables."""
    try:
        return get_structural_detail(db, assessment_id)
    except StructuralNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/structural-assessments/{assessment_id}", response_model=StructuralDetailOut)
def update_structural_endpoint(
    assessment_id: str,
    payload: StructuralAssessmentUpdateRequest,
    db: Session = Depends(get_db),
) -> StructuralDetailOut:
    """Update structural inputs/references/type and deterministically recompute checks."""
    try:
        return update_structural_assessment(db, assessment_id, payload)
    except StructuralNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StructuralValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/structural-assessments/{assessment_id}/approve", response_model=StructuralDetailOut)
def approve_structural_endpoint(
    assessment_id: str,
    payload: StructuralApproveRequest,
    db: Session = Depends(get_db),
) -> StructuralDetailOut:
    """Explicit owner / licensed structural engineer approval clearing UNVERIFIED AI DRAFT state."""
    try:
        return approve_structural_assessment(db, assessment_id, payload)
    except StructuralNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/structural-assessments/{assessment_id}/export",
    response_model=StructuralExportOut,
    status_code=status.HTTP_201_CREATED,
)
def export_structural_endpoint(
    assessment_id: str,
    payload: StructuralExportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> StructuralExportOut:
    """Export immutable bilingual DOCX, PDF, and live-formula XLSX structural deliverables into 04_Engineering_Calculations."""
    try:
        return export_structural_deliverables(
            db,
            _get_settings(request),
            assessment_id,
            language=payload.language,
        )
    except (ProjectNotFoundError, StructuralNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StructuralValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
