"""Step 06 document, spreadsheet, presentation, and image extraction endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.schemas.extraction import (
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
    extract_project_file,
    get_extraction_capabilities,
    get_extraction_detail,
    list_file_extractions,
    resolve_extraction_page_image,
)
from app.services.files import FileRecordNotFoundError, FileVersionNotFoundError
from app.services.workspace import WorkspacePathError

router = APIRouter(tags=["extraction"])


def _get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/extraction/capabilities", response_model=ExtractionCapabilitiesOut)
def get_extraction_capabilities_endpoint(request: Request) -> ExtractionCapabilitiesOut:
    """Return runtime Tesseract OCR availability (or pending owner status) and formats."""
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
    """Run deterministic extraction on a read-only project file and save normalized JSON."""
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
