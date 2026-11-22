"""Step 15 API endpoints for deterministic Decimal technical comparisons, owner decisions, and SHA-256 DOCX/PDF/XLSX exports."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.comparisons import (
    ComparisonCreateRequest,
    ComparisonDecideRequest,
    ComparisonExportRequest,
    ComparisonPresetListResponse,
    TechnicalComparisonDetailOut,
    TechnicalComparisonExportOut,
    TechnicalComparisonListResponse,
)
from app.services.comparisons import (
    ComparisonConflictError,
    ComparisonNotFoundError,
    ComparisonValidationError,
    create_technical_comparison,
    decide_technical_comparison,
    export_technical_comparison,
    get_comparison_detail,
    list_comparison_presets,
    list_project_comparisons,
)
from app.services.projects import ProjectNotFoundError

router = APIRouter(tags=["comparisons"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("/comparisons/presets", response_model=ComparisonPresetListResponse)
def list_comparison_presets_endpoint() -> ComparisonPresetListResponse:
    """Return synthetic clinic equipment/offer comparison presets (0% client data)."""
    return list_comparison_presets()


@router.post(
    "/projects/{project_id}/comparisons",
    response_model=TechnicalComparisonDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_technical_comparison_endpoint(
    project_id: str,
    payload: ComparisonCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TechnicalComparisonDetailOut:
    """Evaluate and persist a weighted Decimal technical comparison plus initial 09_Comparisons exports (default 0 tokens)."""
    try:
        return create_technical_comparison(
            db,
            _get_settings(request),
            _get_secret_store(request),
            project_id,
            payload,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ComparisonValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ComparisonConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/projects/{project_id}/comparisons", response_model=TechnicalComparisonListResponse)
def list_project_comparisons_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> TechnicalComparisonListResponse:
    """List persisted Step 15 technical comparisons for a project ordered newest first."""
    try:
        return list_project_comparisons(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/comparisons/{comparison_id}", response_model=TechnicalComparisonDetailOut)
def get_comparison_detail_endpoint(
    comparison_id: str,
    db: Session = Depends(get_db),
) -> TechnicalComparisonDetailOut:
    """Retrieve complete weighted technical comparison matrix, provenance, flags, and deliverables."""
    try:
        return get_comparison_detail(db, comparison_id)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/comparisons/{comparison_id}/decide", response_model=TechnicalComparisonDetailOut)
def decide_technical_comparison_endpoint(
    comparison_id: str,
    payload: ComparisonDecideRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TechnicalComparisonDetailOut:
    """Record explicit Owner / Licensed Engineer final decision and optionally approve UNVERIFIED AI DRAFT narrative."""
    try:
        return decide_technical_comparison(db, _get_settings(request), comparison_id, payload)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ComparisonValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ComparisonConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/comparisons/{comparison_id}/export",
    response_model=TechnicalComparisonExportOut,
    status_code=status.HTTP_201_CREATED,
)
def export_technical_comparison_endpoint(
    comparison_id: str,
    request: Request,
    payload: ComparisonExportRequest | None = None,
    db: Session = Depends(get_db),
) -> TechnicalComparisonExportOut:
    """Generate immutable SHA-256 versioned DOCX, PDF & XLSX comparison deliverables in 09_Comparisons."""
    try:
        return export_technical_comparison(db, _get_settings(request), comparison_id, payload)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ComparisonConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
