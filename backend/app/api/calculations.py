"""Step 13 API endpoints for deterministic engineering calculation framework & electrical/plumbing calculators."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.schemas.calculations import (
    CalculationCreateRequest,
    CalculationDetailOut,
    CalculationExportOut,
    CalculationExportRequest,
    CalculationListResponse,
    CalculationPresetListResponse,
    CalculationUpdateRequest,
)
from app.services.calculations import (
    CalculationNotFoundError,
    CalculationValidationError,
    create_calculation,
    export_calculation_deliverables,
    get_calculation_detail,
    list_calculation_presets,
    list_project_calculations,
    update_calculation,
)
from app.services.projects import ProjectNotFoundError

router = APIRouter(tags=["calculations"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/calculations/presets", response_model=CalculationPresetListResponse)
def list_calculation_presets_endpoint() -> CalculationPresetListResponse:
    """Return synthetic clinic/office examples (0 client data) for all electrical & plumbing calculators."""
    return list_calculation_presets()


@router.post(
    "/projects/{project_id}/calculations",
    response_model=CalculationDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_calculation_endpoint(
    project_id: str,
    payload: CalculationCreateRequest,
    db: Session = Depends(get_db),
) -> CalculationDetailOut:
    """Create and deterministically evaluate an engineering calculation (0 AI tokens)."""
    try:
        return create_calculation(db, project_id, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CalculationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/projects/{project_id}/calculations", response_model=CalculationListResponse)
def list_project_calculations_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> CalculationListResponse:
    """List persisted calculations for one project newest first."""
    try:
        return list_project_calculations(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/calculations/{calculation_id}", response_model=CalculationDetailOut)
def get_calculation_detail_endpoint(
    calculation_id: str,
    db: Session = Depends(get_db),
) -> CalculationDetailOut:
    """Retrieve complete calculation inputs, units, equations, method, assumptions, results, acceptance, and references."""
    try:
        return get_calculation_detail(db, calculation_id)
    except CalculationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/calculations/{calculation_id}", response_model=CalculationDetailOut)
def update_calculation_endpoint(
    calculation_id: str,
    payload: CalculationUpdateRequest,
    db: Session = Depends(get_db),
) -> CalculationDetailOut:
    """Update calculation inputs/references and deterministically recompute."""
    try:
        return update_calculation(db, calculation_id, payload)
    except CalculationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CalculationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/calculations/{calculation_id}/export",
    response_model=CalculationExportOut,
    status_code=status.HTTP_201_CREATED,
)
def export_calculation_endpoint(
    calculation_id: str,
    request: Request,
    payload: CalculationExportRequest | None = None,
    db: Session = Depends(get_db),
) -> CalculationExportOut:
    """Export immutable versioned DOCX, PDF, and XLSX calculation deliverables into 04_Engineering_Calculations."""
    try:
        return export_calculation_deliverables(db, _get_settings(request), calculation_id, payload)
    except CalculationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
