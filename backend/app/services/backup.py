"""Step 20 backup and restore engine for workspace files and SQLite DB with SHA-256 manifests (never includes keyring)."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Any
from urllib.parse import quote
from uuid import uuid4
import zipfile

from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.branding import build_backup_branding_metadata
from app.core.config import Settings
from app.core.logging import LOG_BACKUP_COUNT, LOG_MAX_BYTES, get_log_file_path
from app.core.security import find_key_like_strings
from app.db.models import AuditLog
from app.providers.secrets import SecretStore
from app.schemas.system import (
    BackupCreateOut,
    BackupItemOut,
    RestoreResultOut,
    SystemInfoOut,
)

_BACKUP_FILENAME_RE = re.compile(r"^backup_[A-Za-z0-9_.\-]+\.zip$")
_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_\-]+")
_READONLY_FOLDERS = frozenset({"01_Input_Documents", "02_Original_Drawings", "11_References"})


class BackupNotFoundError(LookupError):
    """Raised when a requested backup archive does not exist."""


class BackupValidationError(ValueError):
    """Raised when a backup filename, zip member path, or SHA-256 manifest verification fails."""


def get_backups_dir(workspaces_dir: Path) -> Path:
    """Return backup archive directory under configured workspaces_dir."""
    return workspaces_dir.resolve() / "_backups"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def validate_backup_filename(raw_filename: str) -> str:
    """Strictly allow single-segment timestamped backup_*.zip names."""
    clean = Path(raw_filename).name
    if clean != raw_filename or "/" in raw_filename or "\\" in raw_filename or ".." in raw_filename:
        raise BackupValidationError(f"Unsafe backup filename: {raw_filename!r}")
    if not _BACKUP_FILENAME_RE.match(clean):
        raise BackupValidationError(f"Backup filename must match backup_*.zip: {raw_filename!r}")
    return clean


def _validate_zip_member_path(raw_member: str) -> PurePosixPath:
    """Reject Zip Slip paths, Windows separators, drive letters, absolute roots, and null bytes."""
    if not raw_member or "\x00" in raw_member or "\\" in raw_member or ":" in raw_member:
        raise BackupValidationError(f"Unsafe archive entry path: {raw_member!r}")
    rel = PurePosixPath(raw_member)
    if rel.is_absolute() or ".." in rel.parts or any(part in ("", ".") for part in rel.parts):
        raise BackupValidationError(f"Path traversal blocked in archive entry: {raw_member!r}")
    return rel


def _resolve_sqlite_db_path(database_url: str) -> Path | None:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("sqlite"):
        return None
    db_name = parsed.database
    if not db_name or db_name == ":memory:" or db_name.startswith("file:"):
        return None
    return Path(db_name).resolve()


def _database_kind(database_url: str) -> str:
    parsed = make_url(database_url)
    if parsed.drivername.startswith("postgresql"):
        return "postgresql"
    if parsed.drivername.startswith("sqlite"):
        if not parsed.database or parsed.database == ":memory:":
            return "memory"
        return "sqlite"
    return "other"


def _sqlite_consistent_copy(source_db: Path, dest_db: Path) -> None:
    """Copy a SQLite database transactionally using SQLite's online backup API."""
    dest_db.parent.mkdir(parents=True, exist_ok=True)
    if dest_db.exists():
        os.chmod(dest_db, stat.S_IWRITE | stat.S_IREAD)
        dest_db.unlink(missing_ok=True)
    src_conn = sqlite3.connect(str(source_db))
    dst_conn = sqlite3.connect(str(dest_db))
    try:
        src_conn.backup(dst_conn)
        dst_conn.commit()
    finally:
        dst_conn.close()
        src_conn.close()


def _should_skip_workspace_file(rel_posix: PurePosixPath, abs_path: Path, sqlite_db_path: Path | None) -> bool:
    parts = rel_posix.parts
    if not parts:
        return True
    if parts[0] in {"_backups", "_logs", ".upload_staging"} or ".upload_staging" in parts:
        return True
    if any(p.startswith(".env") for p in parts):
        return True
    name_lower = rel_posix.name.lower()
    if (
        name_lower.endswith((".db-wal", ".db-shm", ".db-journal", ".lock"))
        or name_lower == "agent.log"
        or bool(re.match(r"^agent\.log\.\d+$", name_lower))
    ):
        return True
    if sqlite_db_path is not None and abs_path.resolve() in {
        sqlite_db_path,
        Path(f"{sqlite_db_path}-wal"),
        Path(f"{sqlite_db_path}-shm"),
    }:
        return True
    return False


def _set_read_only_if_original(path: Path, rel_parts: tuple[str, ...]) -> None:
    if len(rel_parts) >= 2 and rel_parts[1] in _READONLY_FOLDERS:
        os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def create_workspace_backup(
    db: Session | None,
    settings: Settings,
    *,
    label: str = "",
) -> BackupCreateOut:
    """Create a timestamped zip archive of DB + workspace files + SHA-256 manifest (zero keyring material)."""
    ws_root = settings.workspaces_dir.resolve()
    ws_root.mkdir(parents=True, exist_ok=True)
    backups_dir = get_backups_dir(ws_root)
    backups_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    short_uid = uuid4().hex[:6]
    clean_label = _SAFE_LABEL_RE.sub("_", (label or "").strip()).strip("_")[:24]
    suffix = f"_{clean_label}" if clean_label else ""
    archive_name = f"backup_{stamp}_{short_uid}{suffix}.zip"
    archive_path = (backups_dir / archive_name).resolve()
    if not archive_path.is_relative_to(backups_dir):
        raise BackupValidationError("Backup destination escaped _backups directory.")

    sqlite_db_path = _resolve_sqlite_db_path(settings.database_url)
    manifest_files: list[dict[str, Any]] = []
    db_archive_path: str | None = None
    db_sha256: str | None = None

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            if sqlite_db_path is not None and sqlite_db_path.is_file():
                snap_path = tmpdir / sqlite_db_path.name
                _sqlite_consistent_copy(sqlite_db_path, snap_path)
                db_archive_path = f"database/{sqlite_db_path.name}"
                db_sha256 = _sha256_file(snap_path)
                zf.write(snap_path, arcname=db_archive_path)
                manifest_files.append(
                    {
                        "archive_path": db_archive_path,
                        "kind": "database",
                        "sha256": db_sha256,
                        "size_bytes": snap_path.stat().st_size,
                    }
                )

            for item in sorted(ws_root.rglob("*")):
                if not item.is_file():
                    continue
                rel_posix = PurePosixPath(item.relative_to(ws_root).as_posix())
                if _should_skip_workspace_file(rel_posix, item, sqlite_db_path):
                    continue
                arcname = f"workspace/{rel_posix.as_posix()}"
                file_hash = _sha256_file(item)
                zf.write(item, arcname=arcname)
                manifest_files.append(
                    {
                        "archive_path": arcname,
                        "kind": "workspace_file",
                        "relative_path": rel_posix.as_posix(),
                        "sha256": file_hash,
                        "size_bytes": item.stat().st_size,
                    }
                )

            manifest_obj = {
                "schema_version": 1,
                "created_at": now.isoformat(),
                "app_version": settings.app_version,
                "branding": build_backup_branding_metadata(),
                "excludes_keyring": True,
                "includes_database": db_archive_path is not None,
                "database_archive_path": db_archive_path,
                "database_sha256": db_sha256,
                "files_count": len(manifest_files),
                "files": manifest_files,
            }
            manifest_bytes = json.dumps(manifest_obj, indent=2, ensure_ascii=False).encode("utf-8")
            if find_key_like_strings(manifest_bytes.decode("utf-8")):
                raise BackupValidationError("Blocked unexpected secret pattern from backup manifest.")
            manifest_sha = _sha256_bytes(manifest_bytes)
            zf.writestr("manifest.json", manifest_bytes)

    zip_sha = _sha256_file(archive_path)
    zip_size = archive_path.stat().st_size
    sidecar = backups_dir / f"{archive_name}.sha256"
    sidecar.write_text(f"{zip_sha} *{archive_name}\n", encoding="utf-8")

    backup_out = BackupItemOut(
        filename=archive_name,
        relative_path=f"_backups/{archive_name}",
        size_bytes=zip_size,
        sha256=zip_sha,
        created_at=now,
    )

    if db is not None:
        db.add(
            AuditLog(
                project_id=None,
                actor="owner",
                action="system.backup_created",
                entity_type="system_backup",
                entity_id=archive_name,
                details_json={
                    "filename": archive_name,
                    "sha256": zip_sha,
                    "files_count": len(manifest_files),
                    "excludes_keyring": True,
                },
            )
        )
        db.commit()

    return BackupCreateOut(
        backup=backup_out,
        files_count=len(manifest_files),
        includes_database=db_archive_path is not None,
        database_sha256=db_sha256,
        manifest_sha256=manifest_sha,
        excludes_keyring=True,
        message=(
            f"Backup created ({archive_name}) with {len(manifest_files)} verified SHA-256 entries. "
            "OS keyring / API keys are excluded."
        ),
    )


def list_workspace_backups(settings: Settings) -> list[BackupItemOut]:
    """List verified timestamped backup zips under workspaces_dir/_backups ordered newest first."""
    backups_dir = get_backups_dir(settings.workspaces_dir)
    if not backups_dir.is_dir():
        return []
    out: list[BackupItemOut] = []
    for fp in sorted(backups_dir.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not fp.is_file() or not _BACKUP_FILENAME_RE.match(fp.name):
            continue
        st = fp.stat()
        out.append(
            BackupItemOut(
                filename=fp.name,
                relative_path=f"_backups/{fp.name}",
                size_bytes=st.st_size,
                sha256=_sha256_file(fp),
                created_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            )
        )
    return out


def resolve_backup_download(settings: Settings, filename: str) -> Path:
    """Safely resolve a downloadable backup zip inside workspaces_dir/_backups."""
    clean = validate_backup_filename(filename)
    backups_dir = get_backups_dir(settings.workspaces_dir)
    target = (backups_dir / clean).resolve()
    if not target.is_relative_to(backups_dir) or not target.is_file():
        raise BackupNotFoundError(f"Backup archive not found: {clean}")
    return target


def verify_and_restore_backup(
    *,
    archive_path: Path,
    target_workspaces_dir: Path,
    target_database_url: str,
    dry_run: bool = True,
    app_engine: Engine | None = None,
    db: Session | None = None,
) -> RestoreResultOut:
    """Verify SHA-256 manifest + Zip Slip bounds, and optionally restore DB and workspace files cleanly."""
    resolved_archive = archive_path.resolve()
    if not resolved_archive.is_file():
        raise BackupNotFoundError(f"Backup archive not found: {resolved_archive.name}")

    target_ws = target_workspaces_dir.resolve()
    mismatched: list[str] = []
    missing: list[str] = []
    extra: list[str] = []
    verified_count = 0
    would_overwrite = 0
    db_verified = False
    db_restored = False
    excludes_keyring = True

    with zipfile.ZipFile(resolved_archive, mode="r") as zf:
        safe_members: dict[str, zipfile.ZipInfo] = {}
        for info in zf.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise BackupValidationError(f"Symbolic link rejected in backup archive: {info.filename!r}")
            rel_member = _validate_zip_member_path(info.filename)
            if not info.is_dir():
                safe_members[rel_member.as_posix()] = info

        if "manifest.json" not in safe_members:
            raise BackupValidationError("Backup archive missing required manifest.json.")

        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except Exception as exc:
            raise BackupValidationError(f"Corrupt backup manifest.json: {exc}") from exc

        excludes_keyring = bool(manifest.get("excludes_keyring", True))
        if not excludes_keyring:
            raise BackupValidationError("Unsupported backup manifest: excludes_keyring flag must be true.")

        entries = manifest.get("files") or []
        if not isinstance(entries, list):
            raise BackupValidationError("Invalid backup manifest 'files' list.")

        expected_paths: set[str] = {"manifest.json"}
        for entry in entries:
            arc_path = str(entry.get("archive_path") or "")
            expected_hash = str(entry.get("sha256") or "")
            expected_kind = str(entry.get("kind") or "")
            rel_arc = _validate_zip_member_path(arc_path)
            arc_norm = rel_arc.as_posix()
            expected_paths.add(arc_norm)

            if arc_norm not in safe_members:
                missing.append(arc_norm)
                continue

            data_bytes = zf.read(safe_members[arc_norm])
            actual_hash = _sha256_bytes(data_bytes)
            if actual_hash != expected_hash:
                mismatched.append(arc_norm)
                continue

            verified_count += 1
            if expected_kind == "database":
                db_verified = True
                target_db = _resolve_sqlite_db_path(target_database_url)
                if target_db is not None and target_db.exists():
                    would_overwrite += 1
            elif expected_kind == "workspace_file":
                ws_rel_raw = str(entry.get("relative_path") or "")
                ws_rel = _validate_zip_member_path(ws_rel_raw)
                dest = (target_ws / ws_rel).resolve()
                if dest == target_ws or not dest.is_relative_to(target_ws):
                    raise BackupValidationError(f"Restore target escaped workspace root: {ws_rel_raw!r}")
                if dest.exists():
                    would_overwrite += 1

        for present in sorted(safe_members.keys()):
            if present not in expected_paths:
                extra.append(present)

        is_valid = len(mismatched) == 0 and len(missing) == 0 and len(extra) == 0
        if dry_run:
            if db is not None:
                db.add(
                    AuditLog(
                        project_id=None,
                        actor="owner",
                        action="system.backup_dry_run_verified",
                        entity_type="system_backup",
                        entity_id=resolved_archive.name,
                        details_json={
                            "valid": is_valid,
                            "verified_files_count": verified_count,
                            "mismatched": mismatched,
                            "missing": missing,
                        },
                    )
                )
                db.commit()
            return RestoreResultOut(
                backup_filename=resolved_archive.name,
                dry_run=True,
                valid=is_valid,
                restored=False,
                excludes_keyring=True,
                verified_files_count=verified_count,
                restored_files_count=0,
                would_overwrite_count=would_overwrite,
                mismatched_files=mismatched,
                missing_files=missing,
                extra_files=extra,
                database_verified=db_verified,
                database_restored=False,
                target_workspaces_dir=str(target_ws),
                message=(
                    f"Dry-run verification passed: {verified_count} SHA-256 entries valid ({would_overwrite} existing paths would be replaced)."
                    if is_valid
                    else f"Verification FAILED: {len(mismatched)} mismatched, {len(missing)} missing, {len(extra)} unexpected entries."
                ),
            )

        if not is_valid:
            raise BackupValidationError(
                f"Refusing restore of tampered/incomplete archive: mismatched={mismatched}, missing={missing}, extra={extra}"
            )

        target_ws.mkdir(parents=True, exist_ok=True)
        restored_files = 0
        db_arc_path = str(manifest.get("database_archive_path") or "")

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            for entry in entries:
                arc_norm = PurePosixPath(str(entry["archive_path"])).as_posix()
                kind = str(entry.get("kind") or "")
                raw_bytes = zf.read(safe_members[arc_norm])
                if kind == "workspace_file":
                    ws_rel = _validate_zip_member_path(str(entry["relative_path"]))
                    dest = (target_ws / ws_rel).resolve()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)
                    dest.write_bytes(raw_bytes)
                    _set_read_only_if_original(dest, ws_rel.parts)
                    restored_files += 1
                elif kind == "database" and arc_norm == db_arc_path:
                    target_db = _resolve_sqlite_db_path(target_database_url)
                    if target_db is not None:
                        tmp_db = tmpdir / "restored.db"
                        tmp_db.write_bytes(raw_bytes)
                        if db is not None:
                            try:
                                db.rollback()
                                db.close()
                            except Exception:
                                pass
                        if app_engine is not None:
                            app_engine.dispose()
                        for suffix in ("-wal", "-shm"):
                            sidecar = Path(f"{target_db}{suffix}")
                            if sidecar.exists():
                                sidecar.unlink(missing_ok=True)
                        _sqlite_consistent_copy(tmp_db, target_db)
                        db_restored = True

    if db is not None:
        try:
            db.add(
                AuditLog(
                    project_id=None,
                    actor="owner",
                    action="system.backup_restored",
                    entity_type="system_backup",
                    entity_id=resolved_archive.name,
                    details_json={
                        "restored_files_count": restored_files,
                        "database_restored": db_restored,
                        "excludes_keyring": True,
                    },
                )
            )
            db.commit()
        except Exception:
            db.rollback()

    return RestoreResultOut(
        backup_filename=resolved_archive.name,
        dry_run=False,
        valid=True,
        restored=True,
        excludes_keyring=True,
        verified_files_count=verified_count,
        restored_files_count=restored_files,
        would_overwrite_count=would_overwrite,
        mismatched_files=[],
        missing_files=[],
        extra_files=[],
        database_verified=db_verified,
        database_restored=db_restored,
        target_workspaces_dir=str(target_ws),
        message=(
            f"Restore completed: {restored_files} verified files restored"
            + (" and SQLite database restored." if db_restored else ".")
        ),
    )


def get_system_info(settings: Settings, secret_store: SecretStore) -> SystemInfoOut:
    """Return non-secret hardening status, local log file path, and available backup archives."""
    log_path = get_log_file_path(settings.workspaces_dir)
    backups_dir = get_backups_dir(settings.workspaces_dir)
    return SystemInfoOut(
        app_env=settings.app_env,
        backend_host=settings.backend_host,
        cors_origins=settings.cors_origin_list(),
        workspaces_dir=str(settings.workspaces_dir.resolve()),
        log_file_path=str(log_path),
        log_rotation_policy=f"Rotating JSONL ({LOG_MAX_BYTES // (1024 * 1024)} MB x {LOG_BACKUP_COUNT} files, secrets & client data redacted)",
        log_viewer_enabled=False,
        remote_log_shipping=False,
        backup_dir=str(backups_dir),
        backup_excludes_keyring=True,
        credential_backend=secret_store.backend_name,
        database_kind=_database_kind(settings.database_url),  # type: ignore[arg-type]
        backups=list_workspace_backups(settings),
    )
