"""Step 17 API endpoints for owner-supplied / licensed standards library, upload+suggestion confirmation, supersession, search, and register exports."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError, TaskComplexity
from app.providers.secrets import SecretStore
from app.schemas.standards import (
    StandardConfirmRequest,
    StandardCreateRequest,
    StandardDocumentOut,
    StandardListResponse,
    StandardPresetListResponse,
    StandardRegisterExportOut,
    StandardRegisterExportRequest,
    StandardSupersedeRequest,
    StandardUpdateRequest,
)
from app.services.projects import ProjectNotFoundError
from app.services.standards import (
    StandardNotFoundError,
    StandardValidationError,
    confirm_standard_metadata,
    create_standard_entry,
    export_standards_register,
    get_standard_detail,
    list_and_search_standards,
    list_standard_presets,
    resolve_register_file_download,
    supersede_standard_entry,
    update_standard_entry,
    upload_standard_document,
)

router = APIRouter(tags=["standards"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("/standards/presets", response_model=StandardPresetListResponse)
def list_standard_presets_endpoint() -> StandardPresetListResponse:
    """Return synthetic SYN-* standard fixtures (0% copyrighted text)."""
    return list_standard_presets()


@router.get("/standards", response_model=StandardListResponse)
def list_standards_endpoint(
    project_id: str | None = Query(default=None),
    include_global: bool = Query(default=True),
    q: str | None = Query(default=None),
    number: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    issuing_body: str | None = Query(default=None),
    adopted_locally: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> StandardListResponse:
    """Search owner-supplied standards ONLY by number, title, body, status, and keyword."""
    return list_and_search_standards(
        db,
        project_id=project_id,
        include_global=include_global,
        q=q,
        number=number,
        status=status_filter,
        issuing_body=issuing_body,
        adopted_locally=adopted_locally,
    )


@router.post("/standards", response_model=StandardDocumentOut, status_code=status.HTTP_201_CREATED)
def create_standard_endpoint(
    payload: StandardCreateRequest,
    db: Session = Depends(get_db),
) -> StandardDocumentOut:
    """Create an owner-entered engineering standard record (0 AI tokens)."""
    try:
        return create_standard_entry(db, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StandardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/standards/upload", response_model=StandardDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_standard_endpoint(
    request: Request,
    file: UploadFile = File(...),
    project_id: str | None = Form(default=None),
    use_ai: bool = Form(default=False),
    complexity: TaskComplexity = Form(default="fast"),
    jurisdiction: str = Form(default=""),
    adopted_locally: bool = Form(default=False),
    db: Session = Depends(get_db),
) -> StandardDocumentOut:
    """Upload PDF/DOCX/TXT standard, store immutable SHA-256 file, and return unconfirmed metadata suggestion."""
    try:
        return await upload_standard_document(
            db,
            _get_settings(request),
            _get_secret_store(request),
            upload=file,
            project_id=project_id or None,
            use_ai=use_ai,
            complexity=complexity,
            jurisdiction=jurisdiction,
            adopted_locally=adopted_locally,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StandardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/standards/{standard_id}", response_model=StandardDocumentOut)
def get_standard_detail_endpoint(
    standard_id: str,
    db: Session = Depends(get_db),
) -> StandardDocumentOut:
    """Retrieve single standard metadata, version history, supersession chain, and deliverable citations."""
    try:
        return get_standard_detail(db, standard_id)
    except StandardNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/standards/{standard_id}", response_model=StandardDocumentOut)
def update_standard_endpoint(
    standard_id: str,
    payload: StandardUpdateRequest,
    db: Session = Depends(get_db),
) -> StandardDocumentOut:
    """Update standard metadata, status, <=300-char excerpts, or supersession link with version increment."""
    try:
        return update_standard_entry(db, standard_id, payload)
    except StandardNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StandardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/standards/{standard_id}/confirm", response_model=StandardDocumentOut)
def confirm_standard_endpoint(
    standard_id: str,
    payload: StandardConfirmRequest,
    db: Session = Depends(get_db),
) -> StandardDocumentOut:
    """Owner confirmation clearing UNVERIFIED AI/extracted metadata suggestion state."""
    try:
        return confirm_standard_metadata(db, standard_id, payload)
    except StandardNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StandardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/standards/{standard_id}/supersede", response_model=StandardDocumentOut)
def supersede_standard_endpoint(
    standard_id: str,
    payload: StandardSupersedeRequest,
    db: Session = Depends(get_db),
) -> StandardDocumentOut:
    """Record owner-entered supersession linking an old standard edition to its replacement."""
    try:
        return supersede_standard_entry(db, standard_id, payload)
    except StandardNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StandardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/standards/export-register", response_model=StandardRegisterExportOut, status_code=status.HTTP_201_CREATED)
def export_standards_register_endpoint(
    payload: StandardRegisterExportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> StandardRegisterExportOut:
    """Export immutable bilingual DOCX, PDF & XLSX Standards Register with status & citation links."""
    try:
        return export_standards_register(db, _get_settings(request), payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/standards/register-files/{filename}")
def download_standards_register_file_endpoint(
    filename: str,
    request: Request,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download an exported DOCX, PDF or XLSX Standards Register file."""
    try:
        disk_path = resolve_register_file_download(db, _get_settings(request), filename=filename, project_id=project_id)
        return FileResponse(path=disk_path, filename=disk_path.name)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StandardNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StandardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
