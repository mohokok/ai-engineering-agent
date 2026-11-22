"""Step 20 System Hardening, local log-path info, and verified backup/restore API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.providers.secrets import SecretStore
from app.schemas.system import (
    BackupCreateOut,
    BackupCreateRequest,
    BackupItemOut,
    BackupRestoreRequest,
    RestoreResultOut,
    SystemInfoOut,
)
from app.services.backup import (
    BackupNotFoundError,
    BackupValidationError,
    create_workspace_backup,
    get_backups_dir,
    get_system_info,
    list_workspace_backups,
    resolve_backup_download,
    validate_backup_filename,
    verify_and_restore_backup,
)

router = APIRouter(prefix="/system", tags=["system-hardening"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


@router.get("/info", response_model=SystemInfoOut)
def get_system_info_endpoint(request: Request) -> SystemInfoOut:
    """Return local binding, strict CORS origins, local log path, and backup metadata (no remote log viewer)."""
    return get_system_info(_get_settings(request), _get_secret_store(request))


@router.get("/backups", response_model=list[BackupItemOut])
def list_backups_endpoint(request: Request) -> list[BackupItemOut]:
    """List verified backup archives created under workspaces_dir/_backups."""
    return list_workspace_backups(_get_settings(request))


@router.post("/backup", response_model=BackupCreateOut, status_code=status.HTTP_201_CREATED)
def create_backup_endpoint(
    request: Request,
    payload: BackupCreateRequest | None = None,
    db: Session = Depends(get_db),
) -> BackupCreateOut:
    """One-click backup of SQLite database + workspace files into timestamped zip with SHA-256 manifest."""
    try:
        return create_workspace_backup(
            db,
            _get_settings(request),
            label=(payload.label if payload else ""),
        )
    except BackupValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/backups/{filename}/download")
def download_backup_endpoint(filename: str, request: Request) -> FileResponse:
    """Safely download a timestamped backup zip from _backups/."""
    try:
        path = resolve_backup_download(_get_settings(request), filename)
        return FileResponse(path=path, media_type="application/zip", filename=path.name)
    except BackupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BackupValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/restore", response_model=RestoreResultOut)
def restore_backup_endpoint(
    payload: BackupRestoreRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RestoreResultOut:
    """Verify SHA-256 manifest (dry_run=True) or restore verified backup into current workspace+DB."""
    settings = _get_settings(request)
    try:
        clean_name = validate_backup_filename(payload.backup_filename)
    except BackupValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    archive_path = get_backups_dir(settings.workspaces_dir) / clean_name
    if not payload.dry_run and not payload.confirm_overwrite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Live restore requires confirm_overwrite=true (run dry_run=true first).",
        )
    try:
        return verify_and_restore_backup(
            archive_path=archive_path,
            target_workspaces_dir=settings.workspaces_dir,
            target_database_url=settings.database_url,
            dry_run=payload.dry_run,
            app_engine=request.app.state.engine,
            db=db,
        )
    except BackupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BackupValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
