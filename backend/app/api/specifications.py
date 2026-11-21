"""Step 14 API endpoints for traceable project specifications generation, owner AI approval, and DOCX/PDF export."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.specifications import (
    SpecificationApproveRequest,
    SpecificationDetailOut,
    SpecificationExportOut,
    SpecificationExportRequest,
    SpecificationGenerateRequest,
    SpecificationListResponse,
    SpecificationPresetListResponse,
)
from app.services.projects import ProjectNotFoundError
from app.services.specifications import (
    SpecificationNotFoundError,
    SpecificationValidationError,
    approve_specification_draft,
    export_specification_deliverables,
    generate_project_specification,
    get_specification_detail,
    list_project_specifications,
    list_specification_presets,
)

router = APIRouter(tags=["specifications"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("/specifications/presets", response_model=SpecificationPresetListResponse)
def list_specification_presets_endpoint() -> SpecificationPresetListResponse:
    """Return synthetic clinic specification fixture guides (0% client data)."""
    return list_specification_presets()


@router.post(
    "/projects/{project_id}/specifications",
    response_model=SpecificationDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def generate_project_specification_endpoint(
    project_id: str,
    payload: SpecificationGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SpecificationDetailOut:
    """Generate a traceable technical specification package from real BOQs, drawings & verified sources (default 0 tokens)."""
    try:
        return generate_project_specification(
            db,
            _get_settings(request),
            _get_secret_store(request),
            project_id,
            payload,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpecificationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/projects/{project_id}/specifications", response_model=SpecificationListResponse)
def list_project_specifications_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> SpecificationListResponse:
    """List persisted specifications for a project ordered newest first."""
    try:
        return list_project_specifications(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/specifications/{spec_id}", response_model=SpecificationDetailOut)
def get_specification_detail_endpoint(
    spec_id: str,
    db: Session = Depends(get_db),
) -> SpecificationDetailOut:
    """Retrieve complete specification sections, clauses, traceability anchors, and deliverables."""
    try:
        return get_specification_detail(db, spec_id)
    except SpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/specifications/{spec_id}/approve", response_model=SpecificationDetailOut)
def approve_specification_draft_endpoint(
    spec_id: str,
    payload: SpecificationApproveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SpecificationDetailOut:
    """Record explicit owner approval on an AI-drafted specification before QA/verification."""
    try:
        return approve_specification_draft(db, _get_settings(request), spec_id, payload)
    except SpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/specifications/{spec_id}/export",
    response_model=SpecificationExportOut,
    status_code=status.HTTP_201_CREATED,
)
def export_specification_endpoint(
    spec_id: str,
    request: Request,
    payload: SpecificationExportRequest | None = None,
    db: Session = Depends(get_db),
) -> SpecificationExportOut:
    """Export immutable versioned DOCX + PDF specification files into 07_Technical_Specifications with SHA-256."""
    try:
        return export_specification_deliverables(db, _get_settings(request), spec_id, payload)
    except SpecificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
