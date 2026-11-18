"""File ingestion, version history, and read-only download API endpoints."""

from fastapi import APIRouter, Depends, File, HTTPException, Path as ApiPath, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ProjectFile
from app.db.session import get_db
from app.schemas.files import (
    FileVersionsResponse,
    ProjectFileListResponse,
    ProjectFileOut,
    ProjectFilesUploadResponse,
    SupportedExtensionOut,
    SupportedExtensionsResponse,
)
from app.services.file_classification import (
    EXPLICITLY_REJECTED_EXAMPLES,
    list_supported_extensions,
)
from app.services.files import (
    EmptyFileError,
    FileRecordNotFoundError,
    FileTooLargeError,
    FileVersionNotFoundError,
    TooManyFilesError,
    UnsafeFilenameError,
    UnsupportedFileTypeError,
    get_project_file,
    ingest_project_files,
    list_project_files,
    resolve_file_download,
)

router = APIRouter(tags=["files"])


def _get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def _build_download_response(
    db: Session,
    settings: Settings,
    file_id: str,
    version_number: int | None,
) -> FileResponse:
    try:
        disk_path, download_name, mime_type = resolve_file_download(
            db, settings.workspaces_dir, file_id, version_number=version_number
        )
        return FileResponse(
            path=disk_path,
            media_type=mime_type or "application/octet-stream",
            filename=download_name,
        )
    except (FileRecordNotFoundError, FileVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/files/supported-extensions", response_model=SupportedExtensionsResponse)
def get_supported_extensions_endpoint(request: Request) -> SupportedExtensionsResponse:
    """Return allowed extensions grouped by folder target and upload guardrails."""
    settings = _get_app_settings(request)
    return SupportedExtensionsResponse(
        extensions=[
            SupportedExtensionOut(
                extension=spec.extension,
                category=spec.category,
                target_folder=spec.target_folder,
                mime_hint=spec.mime_hint,
            )
            for spec in list_supported_extensions()
        ],
        explicitly_unsupported_examples=list(EXPLICITLY_REJECTED_EXAMPLES),
        max_upload_size_bytes=settings.max_upload_size_bytes,
        max_files_per_upload=settings.max_files_per_upload,
    )


@router.post(
    "/projects/{project_id}/files",
    response_model=ProjectFilesUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_files_endpoint(
    project_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> ProjectFilesUploadResponse:
    """Upload one or more files into a project's classified folders with SHA-256 tracking."""
    settings = _get_app_settings(request)
    try:
        return await ingest_project_files(
            db=db,
            workspaces_dir=settings.workspaces_dir,
            project_id=project_id,
            uploads=files,
            max_upload_size_bytes=settings.max_upload_size_bytes,
            max_files_per_upload=settings.max_files_per_upload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
        ) from exc
    except (
        UnsafeFilenameError,
        UnsupportedFileTypeError,
        EmptyFileError,
        TooManyFilesError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/projects/{project_id}/files", response_model=ProjectFileListResponse)
def list_project_files_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectFileListResponse:
    """List all uploaded files and versions belonging to a project."""
    try:
        items = list_project_files(db, project_id)
        return ProjectFileListResponse(project_id=project_id, files=items, total=len(items))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/files/{file_id}", response_model=ProjectFileOut)
def get_file_endpoint(
    file_id: str,
    db: Session = Depends(get_db),
) -> ProjectFileOut:
    """Return metadata and version history for one uploaded project file."""
    try:
        return get_project_file(db, file_id)
    except FileRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/files/{file_id}/versions", response_model=FileVersionsResponse)
def get_file_versions_endpoint(
    file_id: str,
    db: Session = Depends(get_db),
) -> FileVersionsResponse:
    """Return immutable version history rows for a project file."""
    try:
        file_out = get_project_file(db, file_id)
        return FileVersionsResponse(
            file_id=file_out.id,
            original_filename=file_out.original_filename,
            current_version=file_out.current_version,
            is_original=file_out.is_original,
            versions=file_out.versions,
        )
    except FileRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/files/{file_id}/download")
def download_file_endpoint(
    file_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download the latest file version or a specific immutable version."""
    return _build_download_response(db, _get_app_settings(request), file_id, version)


@router.get("/files/{file_id}/versions/{version_number}/download")
def download_file_version_endpoint(
    file_id: str,
    request: Request,
    version_number: int = ApiPath(..., ge=1),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download a specific immutable version of a project file by path parameter."""
    return _build_download_response(db, _get_app_settings(request), file_id, version_number)


@router.api_route(
    "/files/{file_id}",
    methods=["PUT", "PATCH", "DELETE"],
)
@router.api_route(
    "/projects/{project_id}/files/{file_id}",
    methods=["PUT", "PATCH", "DELETE"],
)
def forbid_original_modification(
    file_id: str,
    project_id: str | None = None,
    db: Session = Depends(get_db),
) -> None:
    """Block API mutation or deletion attempts on tracked project files."""
    file_obj = db.get(ProjectFile, file_id)
    if file_obj is None or (project_id is not None and file_obj.project_id != project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {file_id}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Original project files are read-only and cannot be modified or deleted via the API.",
    )
