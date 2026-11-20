"""Step 06/07 document, CAD (DXF/DWG), BIM (IFC), and drawing vision endpoints."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.extraction import (
    DrawingUnitConfirmRequest,
    DrawingVisionSummaryOut,
    DrawingVisionSummaryRequest,
    ExtractionCapabilitiesOut,
    FileExtractionDetailOut,
    FileExtractionListResponse,
    FileExtractionRequest,
)
from app.services.extraction import (
    ExtractionNotFoundError,
    ExtractionProcessingError,
    ExtractionRunConflictError,
    UnsupportedExtractionFormatError,
    confirm_extraction_drawing_unit,
    extract_project_file,
    get_extraction_capabilities,
    get_extraction_detail,
    list_file_extractions,
    resolve_extraction_page_image,
    summarize_drawing_page_vision,
)
from app.services.files import FileRecordNotFoundError, FileVersionNotFoundError
from app.services.workspace import WorkspacePathError

router = APIRouter(tags=["extraction"])


def _get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("/extraction/capabilities", response_model=ExtractionCapabilitiesOut)
def get_extraction_capabilities_endpoint(request: Request) -> ExtractionCapabilitiesOut:
    """Return runtime Tesseract/ODA availability, format support matrix, and supported extensions."""
    return get_extraction_capabilities(_get_app_settings(request))


@router.post(
    "/files/{file_id}/extract",
    response_model=FileExtractionDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def extract_project_file_endpoint(
    request: Request,
    file_id: str = ApiPath(..., min_length=1),
    payload: FileExtractionRequest | None = None,
    db: Session = Depends(get_db),
) -> FileExtractionDetailOut:
    """Run deterministic extraction on a read-only document, CAD drawing, or IFC model."""
    settings = _get_app_settings(request)
    try:
        return extract_project_file(
            db,
            settings,
            file_id,
            request_payload=payload,
        )
    except (FileRecordNotFoundError, FileVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (UnsupportedExtractionFormatError, WorkspacePathError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ExtractionRunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ExtractionProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(
    "/extractions/{extraction_id}/vision-summary",
    response_model=DrawingVisionSummaryOut,
    status_code=status.HTTP_201_CREATED,
)
def summarize_drawing_vision_endpoint(
    request: Request,
    extraction_id: str = ApiPath(..., min_length=1),
    payload: DrawingVisionSummaryRequest | None = None,
    db: Session = Depends(get_db),
) -> DrawingVisionSummaryOut:
    """Summarize a rendered drawing PNG via Gemini Vision (flagged strictly as AI interpretation)."""
    try:
        return summarize_drawing_page_vision(
            db,
            _get_app_settings(request),
            _get_secret_store(request),
            extraction_id,
            request_payload=payload,
            client_factory=_get_client_factory(request),
        )
    except ExtractionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExtractionRunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.post(
    "/extractions/{extraction_id}/confirm-unit",
    response_model=FileExtractionDetailOut,
)
def confirm_extraction_drawing_unit_endpoint(
    request: Request,
    payload: DrawingUnitConfirmRequest,
    extraction_id: str = ApiPath(..., min_length=1),
    db: Session = Depends(get_db),
) -> FileExtractionDetailOut:
    """Record owner-confirmed linear drawing unit per extraction and compute area_m2 without altering native values."""
    try:
        return confirm_extraction_drawing_unit(
            db,
            _get_app_settings(request),
            extraction_id,
            request_payload=payload,
        )
    except ExtractionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (UnsupportedExtractionFormatError, WorkspacePathError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ExtractionRunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/files/{file_id}/extractions", response_model=FileExtractionListResponse)
def list_file_extractions_endpoint(
    file_id: str = ApiPath(..., min_length=1),
    db: Session = Depends(get_db),
) -> FileExtractionListResponse:
    """List saved extraction runs for one project file ordered newest first."""
    try:
        extractions = list_file_extractions(db, file_id)
    except FileRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileExtractionListResponse(
        file_id=file_id,
        extractions=extractions,
        total=len(extractions),
    )


@router.get("/extractions/{extraction_id}", response_model=FileExtractionDetailOut)
def get_extraction_detail_endpoint(
    request: Request,
    extraction_id: str = ApiPath(..., min_length=1),
    db: Session = Depends(get_db),
) -> FileExtractionDetailOut:
    """Fetch complete normalized extraction output including extracted items and counts."""
    try:
        return get_extraction_detail(db, _get_app_settings(request), extraction_id)
    except ExtractionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/extractions/{extraction_id}/pages/{page_number}")
def get_extraction_page_image_endpoint(
    request: Request,
    extraction_id: str = ApiPath(..., min_length=1),
    page_number: int = ApiPath(..., ge=1),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve one rendered PNG preview page from 03_Analysis safely."""
    settings = _get_app_settings(request)
    try:
        disk_path, filename = resolve_extraction_page_image(
            db, settings.workspaces_dir, extraction_id, page_number
        )
        return FileResponse(path=disk_path, media_type="image/png", filename=filename)
    except ExtractionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
