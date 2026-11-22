"""Pydantic schemas for Step 20 local hardening status, log location, and backup/restore."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BackupItemOut(BaseModel):
    """Metadata for a timestamped workspace+DB backup archive under _backups/."""

    filename: str
    relative_path: str
    size_bytes: int
    sha256: str
    created_at: datetime


class BackupCreateRequest(BaseModel):
    """Optional label for one-click backup creation."""

    label: str = Field(default="", max_length=40)


class BackupCreateOut(BaseModel):
    """Outcome of creating a verified workspace+DB zip backup with SHA-256 manifest."""

    backup: BackupItemOut
    files_count: int
    includes_database: bool
    database_sha256: str | None = None
    manifest_sha256: str
    excludes_keyring: bool = True
    message: str


class BackupRestoreRequest(BaseModel):
    """Verify or restore a backup archive from _backups/ (dry_run defaults to True)."""

    backup_filename: str = Field(..., min_length=5, max_length=180)
    dry_run: bool = True
    confirm_overwrite: bool = False


class RestoreResultOut(BaseModel):
    """Verification & restore outcome comparing archive entries against SHA-256 manifest."""

    backup_filename: str
    dry_run: bool
    valid: bool
    restored: bool
    excludes_keyring: bool = True
    verified_files_count: int
    restored_files_count: int
    would_overwrite_count: int
    mismatched_files: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    extra_files: list[str] = Field(default_factory=list)
    database_verified: bool
    database_restored: bool
    target_workspaces_dir: str
    message: str


class SystemInfoOut(BaseModel):
    """Non-secret local system security, log location, and backup inventory (no log viewer / no remote shipping)."""

    app_env: str
    backend_host: str
    cors_origins: list[str]
    workspaces_dir: str
    log_file_path: str
    log_rotation_policy: str
    log_viewer_enabled: bool = False
    remote_log_shipping: bool = False
    backup_dir: str
    backup_excludes_keyring: bool = True
    credential_backend: str
    database_kind: Literal["sqlite", "postgresql", "memory", "other"]
    backups: list[BackupItemOut] = Field(default_factory=list)
