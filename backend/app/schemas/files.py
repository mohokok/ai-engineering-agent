"""Pydantic request and response schemas for project file ingestion and versioning."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SupportedExtensionOut(BaseModel):
    """Single supported upload file extension entry."""

    extension: str
    category: str
    target_folder: str
    mime_hint: str


class SupportedExtensionsResponse(BaseModel):
    """List of supported file extensions and configured upload guardrails."""

    extensions: list[SupportedExtensionOut]
    explicitly_unsupported_examples: list[str]
    max_upload_size_bytes: int
    max_files_per_upload: int
    classification: str = "Preliminary"


class FileVersionOut(BaseModel):
    """Serialized immutable file version entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str
    version_number: int
    stored_relative_path: str
    size_bytes: int
    sha256: str
    change_note: str | None
    created_by: str
    created_at: datetime


class ProjectFileOut(BaseModel):
    """Serialized project file metadata with its full version history."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    folder_name: str
    original_filename: str
    stored_relative_path: str
    mime_type: str | None
    extension: str | None
    size_bytes: int
    sha256: str | None
    is_original: bool
    status: str
    classification: str
    current_version: int
    created_at: datetime
    updated_at: datetime
    versions: list[FileVersionOut] = []


class FileUploadOutcomeItem(BaseModel):
    """Outcome summary for one file inside a multi-file upload batch."""

    filename: str
    outcome: Literal["created", "new_version", "duplicate"]
    message: str
    duplicate_of_file_id: str | None = None
    duplicate_of_filename: str | None = None
    file: ProjectFileOut


class ProjectFilesUploadResponse(BaseModel):
    """Batch multi-file ingestion result summary."""

    project_id: str
    created_count: int
    new_version_count: int
    duplicate_count: int
    items: list[FileUploadOutcomeItem]
    classification: str = "Preliminary"


class ProjectFileListResponse(BaseModel):
    """List of project files and versions."""

    project_id: str
    files: list[ProjectFileOut]
    total: int
    classification: str = "Preliminary"


class FileVersionsResponse(BaseModel):
    """Version history response for a single project file."""

    file_id: str
    original_filename: str
    current_version: int
    is_original: bool
    versions: list[FileVersionOut]
    classification: str = "Preliminary"
