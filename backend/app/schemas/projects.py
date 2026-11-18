"""Pydantic request and response schemas for project management endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectClassification = Literal[
    "Preliminary",
    "Conceptual",
    "For Review",
    "For Coordination",
    "For Approval",
]


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ProjectCreate(BaseModel):
    """Request payload for creating an engineering project and its workspace."""

    name: str = Field(..., min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    name_en: str | None = Field(default=None, max_length=255)
    client_name: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    discipline_scope: str | None = Field(default=None, max_length=255)
    classification: ProjectClassification = "Preliminary"

    @field_validator("name")
    @classmethod
    def validate_non_blank_name(cls, value: str) -> str:
        """Ensure project name is non-empty after stripping whitespace."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Project name must not be empty")
        return stripped

    @field_validator(
        "code",
        "name_en",
        "client_name",
        "location",
        "description",
        "discipline_scope",
        mode="before",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        """Trim optional text fields and collapse blank strings to None."""
        return _strip_optional(value)


class WorkspaceFolderOut(BaseModel):
    """On-disk representation of one project workspace subfolder."""

    name: str
    relative_path: str
    exists: bool


class ProjectSummary(BaseModel):
    """Compact project representation returned in project listings."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    name_en: str | None
    client_name: str | None
    location: str | None
    description: str | None
    discipline_scope: str | None
    status: str
    classification: str
    workspace_slug: str
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """List projects response wrapper."""

    projects: list[ProjectSummary]
    total: int
    classification: str = "Preliminary"


class ProjectDetail(ProjectSummary):
    """Detailed project view including verified workspace folder status."""

    workspace_exists: bool
    folders: list[WorkspaceFolderOut]
