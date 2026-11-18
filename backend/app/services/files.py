"""Project file upload, SHA-256 verification, read-only originals, and versioning service."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import unicodedata
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.base import new_uuid
from app.db.models import AuditLog, FileVersion, Project, ProjectFile
from app.schemas.files import (
    FileUploadOutcomeItem,
    FileVersionOut,
    ProjectFileOut,
    ProjectFilesUploadResponse,
)
from app.services.file_classification import ExtensionSpec, classify_extension
from app.services.workspace import resolve_project_dir, resolve_project_file_path

_STREAM_CHUNK_SIZE = 64 * 1024
_MAX_FILENAME_LENGTH = 180
_FORBIDDEN_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class UnsafeFilenameError(ValueError):
    """Raised when an uploaded filename attempts traversal or violates path rules."""


class UnsupportedFileTypeError(ValueError):
    """Raised when an uploaded file has no extension or an unsupported extension."""


class EmptyFileError(ValueError):
    """Raised when an uploaded file has zero bytes."""


class FileTooLargeError(ValueError):
    """Raised when an uploaded file exceeds max_upload_size_bytes."""


class TooManyFilesError(ValueError):
    """Raised when a batch upload exceeds max_files_per_upload or contains no files."""


class FileRecordNotFoundError(LookupError):
    """Raised when a file ID does not exist."""


class FileVersionNotFoundError(LookupError):
    """Raised when a requested version number or stored file is missing."""


@dataclass
class _StagedUpload:
    filename: str
    spec: ExtensionSpec
    mime_type: str
    size_bytes: int
    sha256: str
    temp_path: Path


def _set_read_only(path: Path) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def _unlink_even_if_readonly(path: Path) -> None:
    if not path.exists():
        return
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.unlink(missing_ok=True)


def validate_upload_filename(raw_filename: str | None) -> tuple[str, ExtensionSpec]:
    """Validate an uploaded filename strictly against traversal, control chars, and allowlist."""
    if raw_filename is None:
        raise UnsafeFilenameError("Missing filename")

    normalized = unicodedata.normalize("NFC", raw_filename.strip())
    if not normalized or normalized in {".", ".."}:
        raise UnsafeFilenameError(f"Invalid filename: {raw_filename!r}")
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise UnsafeFilenameError(f"Path traversal or directory separators rejected: {raw_filename!r}")
    if _FORBIDDEN_FILENAME_RE.search(normalized):
        raise UnsafeFilenameError(f"Forbidden characters in filename: {raw_filename!r}")
    if normalized.startswith(".") or normalized.endswith(".") or normalized.endswith(" "):
        raise UnsafeFilenameError(f"Unsafe leading/trailing characters in filename: {raw_filename!r}")
    if len(normalized) > _MAX_FILENAME_LENGTH:
        raise UnsafeFilenameError(
            f"Filename exceeds {_MAX_FILENAME_LENGTH} characters: {normalized!r}"
        )

    stem = Path(normalized).stem
    if not stem or stem.upper() in _WINDOWS_RESERVED_STEMS:
        raise UnsafeFilenameError(f"Reserved or empty filename stem rejected: {raw_filename!r}")

    spec = classify_extension(normalized)
    if spec is None:
        ext = Path(normalized).suffix.lower() or "<none>"
        raise UnsupportedFileTypeError(f"Unsupported file extension: {ext}")

    return normalized, spec


def _to_project_file_out(file_row: ProjectFile) -> ProjectFileOut:
    versions = sorted(file_row.versions, key=lambda item: item.version_number, reverse=True)
    return ProjectFileOut(
        id=file_row.id,
        project_id=file_row.project_id,
        folder_name=file_row.folder_name,
        original_filename=file_row.original_filename,
        stored_relative_path=file_row.stored_relative_path,
        mime_type=file_row.mime_type,
        extension=file_row.extension,
        size_bytes=file_row.size_bytes,
        sha256=file_row.sha256,
        is_original=file_row.is_original,
        status=file_row.status,
        classification=file_row.classification,
        current_version=file_row.current_version,
        created_at=file_row.created_at,
        updated_at=file_row.updated_at,
        versions=[FileVersionOut.model_validate(v) for v in versions],
    )


async def _stage_uploads(
    uploads: list[UploadFile],
    staging_dir: Path,
    max_upload_size_bytes: int,
    max_files_per_upload: int,
) -> list[_StagedUpload]:
    if not uploads:
        raise TooManyFilesError("At least one file must be provided")
    if len(uploads) > max_files_per_upload:
        raise TooManyFilesError(
            f"Too many files in one request ({len(uploads)} > {max_files_per_upload})"
        )

    # Reject any unsafe filename or disallowed extension before reading/writing streams.
    validated_meta: list[tuple[UploadFile, str, ExtensionSpec]] = []
    for upload in uploads:
        filename, spec = validate_upload_filename(upload.filename)
        validated_meta.append((upload, filename, spec))

    staging_dir.mkdir(parents=True, exist_ok=True)
    staged: list[_StagedUpload] = []
    for idx, (upload, filename, spec) in enumerate(validated_meta):
        temp_path = staging_dir / f"stage_{idx}_{uuid4().hex}"
        hasher = hashlib.sha256()
        total_bytes = 0
        with open(temp_path, "wb") as fh:
            while True:
                chunk = await upload.read(_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_upload_size_bytes:
                    raise FileTooLargeError(
                        f"File {filename!r} exceeds maximum allowed size ({max_upload_size_bytes} bytes)"
                    )
                hasher.update(chunk)
                fh.write(chunk)

        if total_bytes == 0:
            raise EmptyFileError(f"Uploaded file {filename!r} is empty (0 bytes)")

        mime_type = (upload.content_type or "").strip() or spec.mime_hint
        staged.append(
            _StagedUpload(
                filename=filename,
                spec=spec,
                mime_type=mime_type,
                size_bytes=total_bytes,
                sha256=hasher.hexdigest(),
                temp_path=temp_path,
            )
        )
    return staged


async def ingest_project_files(
    db: Session,
    workspaces_dir: Path,
    project_id: str,
    uploads: list[UploadFile],
    max_upload_size_bytes: int,
    max_files_per_upload: int,
) -> ProjectFilesUploadResponse:
    """Validate, hash, deduplicate, store read-only, and version uploaded project files."""
    project = db.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project not found: {project_id}")

    project_dir = resolve_project_dir(workspaces_dir, project.workspace_slug)
    staging_dir = project_dir / ".upload_staging" / uuid4().hex
    written_files: list[Path] = []
    created_count = 0
    new_version_count = 0
    duplicate_count = 0
    outcomes: list[FileUploadOutcomeItem] = []

    try:
        staged_items = await _stage_uploads(
            uploads=uploads,
            staging_dir=staging_dir,
            max_upload_size_bytes=max_upload_size_bytes,
            max_files_per_upload=max_files_per_upload,
        )

        for item in staged_items:
            existing_same_name = db.scalar(
                select(ProjectFile)
                .options(selectinload(ProjectFile.versions))
                .where(
                    ProjectFile.project_id == project.id,
                    ProjectFile.folder_name == item.spec.target_folder,
                    func.lower(ProjectFile.original_filename) == item.filename.lower(),
                )
            )

            if existing_same_name is not None:
                if existing_same_name.sha256 == item.sha256:
                    duplicate_count += 1
                    db.add(
                        AuditLog(
                            project_id=project.id,
                            action="file.duplicate_detected",
                            entity_type="file",
                            entity_id=existing_same_name.id,
                            actor="owner",
                            details_json={
                                "filename": item.filename,
                                "sha256": item.sha256,
                                "duplicate_of_file_id": existing_same_name.id,
                                "duplicate_of_filename": existing_same_name.original_filename,
                            },
                        )
                    )
                    outcomes.append(
                        FileUploadOutcomeItem(
                            filename=item.filename,
                            outcome="duplicate",
                            message="Exact duplicate content already stored at current version; skipped.",
                            duplicate_of_file_id=existing_same_name.id,
                            duplicate_of_filename=existing_same_name.original_filename,
                            file=_to_project_file_out(existing_same_name),
                        )
                    )
                    continue

                next_version = existing_same_name.current_version + 1
                version_rel = str(
                    PurePosixPath("12_Revision_History")
                    / existing_same_name.id
                    / f"v{next_version}_{item.filename}"
                )
                dest_path = resolve_project_file_path(
                    workspaces_dir, project.workspace_slug, version_rel
                )
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item.temp_path), str(dest_path))
                _set_read_only(dest_path)
                written_files.append(dest_path)

                new_version = FileVersion(
                    file_id=existing_same_name.id,
                    version_number=next_version,
                    stored_relative_path=version_rel,
                    size_bytes=item.size_bytes,
                    sha256=item.sha256,
                    change_note=f"Re-uploaded updated file (v{next_version}); original preserved",
                    created_by="owner",
                )
                db.add(new_version)
                existing_same_name.current_version = next_version
                existing_same_name.stored_relative_path = version_rel
                existing_same_name.size_bytes = item.size_bytes
                existing_same_name.sha256 = item.sha256
                existing_same_name.mime_type = item.mime_type
                db.flush()
                db.refresh(existing_same_name)

                new_version_count += 1
                db.add(
                    AuditLog(
                        project_id=project.id,
                        action="file.version_created",
                        entity_type="file",
                        entity_id=existing_same_name.id,
                        actor="owner",
                        details_json={
                            "filename": item.filename,
                            "version_number": next_version,
                            "sha256": item.sha256,
                            "size_bytes": item.size_bytes,
                        },
                    )
                )
                outcomes.append(
                    FileUploadOutcomeItem(
                        filename=item.filename,
                        outcome="new_version",
                        message=f"Created version v{next_version}; original v1 untouched.",
                        file=_to_project_file_out(existing_same_name),
                    )
                )
                continue

            # Check for identical SHA-256 already present under another filename in this project
            existing_hash_match = db.scalar(
                select(ProjectFile)
                .options(selectinload(ProjectFile.versions))
                .join(FileVersion, FileVersion.file_id == ProjectFile.id)
                .where(
                    ProjectFile.project_id == project.id,
                    (ProjectFile.sha256 == item.sha256) | (FileVersion.sha256 == item.sha256),
                )
            )
            if existing_hash_match is not None:
                duplicate_count += 1
                db.add(
                    AuditLog(
                        project_id=project.id,
                        action="file.duplicate_detected",
                        entity_type="file",
                        entity_id=existing_hash_match.id,
                        actor="owner",
                        details_json={
                            "filename": item.filename,
                            "sha256": item.sha256,
                            "duplicate_of_file_id": existing_hash_match.id,
                            "duplicate_of_filename": existing_hash_match.original_filename,
                        },
                    )
                )
                outcomes.append(
                    FileUploadOutcomeItem(
                        filename=item.filename,
                        outcome="duplicate",
                        message=(
                            f"Duplicate SHA-256 content matches existing file "
                            f"{existing_hash_match.original_filename!r}; skipped."
                        ),
                        duplicate_of_file_id=existing_hash_match.id,
                        duplicate_of_filename=existing_hash_match.original_filename,
                        file=_to_project_file_out(existing_hash_match),
                    )
                )
                continue

            # Brand-new original file -> stored read-only in classified folder
            original_rel = str(PurePosixPath(item.spec.target_folder) / item.filename)
            dest_path = resolve_project_file_path(
                workspaces_dir, project.workspace_slug, original_rel
            )
            if dest_path.exists():
                raise FileExistsError(f"Target file already exists on disk: {original_rel}")

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.temp_path), str(dest_path))
            _set_read_only(dest_path)
            written_files.append(dest_path)

            file_id = new_uuid()
            new_file = ProjectFile(
                id=file_id,
                project_id=project.id,
                folder_name=item.spec.target_folder,
                original_filename=item.filename,
                stored_relative_path=original_rel,
                mime_type=item.mime_type,
                extension=item.spec.extension,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                is_original=True,
                status="registered",
                classification="Preliminary",
                current_version=1,
            )
            db.add(new_file)
            db.flush()

            v1 = FileVersion(
                file_id=new_file.id,
                version_number=1,
                stored_relative_path=original_rel,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                change_note="Original file upload (read-only)",
                created_by="owner",
            )
            db.add(v1)
            db.flush()
            db.refresh(new_file)

            created_count += 1
            db.add(
                AuditLog(
                    project_id=project.id,
                    action="file.uploaded",
                    entity_type="file",
                    entity_id=new_file.id,
                    actor="owner",
                    details_json={
                        "filename": new_file.original_filename,
                        "folder": new_file.folder_name,
                        "sha256": new_file.sha256,
                        "size_bytes": new_file.size_bytes,
                        "version_number": 1,
                    },
                )
            )
            outcomes.append(
                FileUploadOutcomeItem(
                    filename=item.filename,
                    outcome="created",
                    message=f"Stored read-only original in {item.spec.target_folder}.",
                    file=_to_project_file_out(new_file),
                )
            )

        db.commit()
    except Exception:
        db.rollback()
        for written_path in written_files:
            _unlink_even_if_readonly(written_path)
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return ProjectFilesUploadResponse(
        project_id=project.id,
        created_count=created_count,
        new_version_count=new_version_count,
        duplicate_count=duplicate_count,
        items=outcomes,
    )


def list_project_files(db: Session, project_id: str) -> list[ProjectFileOut]:
    """Return all uploaded files and their versions for an existing project."""
    if db.get(Project, project_id) is None:
        raise LookupError(f"Project not found: {project_id}")
    rows = db.scalars(
        select(ProjectFile)
        .options(selectinload(ProjectFile.versions))
        .where(ProjectFile.project_id == project_id)
        .order_by(ProjectFile.updated_at.desc(), ProjectFile.original_filename.asc())
    ).all()
    return [_to_project_file_out(row) for row in rows]


def get_project_file(db: Session, file_id: str) -> ProjectFileOut:
    """Return metadata and version history for one project file."""
    row = db.scalar(
        select(ProjectFile)
        .options(selectinload(ProjectFile.versions))
        .where(ProjectFile.id == file_id)
    )
    if row is None:
        raise FileRecordNotFoundError(f"File not found: {file_id}")
    return _to_project_file_out(row)


def resolve_file_download(
    db: Session,
    workspaces_dir: Path,
    file_id: str,
    version_number: int | None = None,
) -> tuple[Path, str, str | None]:
    """Resolve disk path, download filename, and MIME type for a file or specific version."""
    file_row = db.scalar(
        select(ProjectFile)
        .options(selectinload(ProjectFile.versions), selectinload(ProjectFile.project))
        .where(ProjectFile.id == file_id)
    )
    if file_row is None:
        raise FileRecordNotFoundError(f"File not found: {file_id}")

    target_version = version_number or file_row.current_version
    version_row = next(
        (item for item in file_row.versions if item.version_number == target_version),
        None,
    )
    if version_row is None:
        raise FileVersionNotFoundError(
            f"Version {target_version} not found for file {file_id}"
        )

    disk_path = resolve_project_file_path(
        workspaces_dir, file_row.project.workspace_slug, version_row.stored_relative_path
    )
    if not disk_path.is_file():
        raise FileVersionNotFoundError(f"Stored artifact missing on disk for file {file_id}")

    return disk_path, file_row.original_filename, file_row.mime_type
