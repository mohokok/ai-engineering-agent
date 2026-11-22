"""Pydantic schemas and provenance constants for Step 17 owner-supplied standards library."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification
from app.schemas.reports import ReportLanguage
from app.schemas.tasks import TaskTokenUsageOut

StandardStatus = Literal["current", "superseded", "withdrawn", "unknown"]
MetadataStatus = Literal[
    "owner_entered",
    "unverified_suggestion",
    "unverified_ai_suggestion",
    "owner_confirmed",
]
AiSuggestionStatus = Literal["not_used", "unverified_ai_suggestion", "owner_confirmed"]

MAX_EXCERPT_CHARS = 300
AI_UNVERIFIED_SUGGESTION_LABEL_EN = "UNVERIFIED AI SUGGESTION"
AI_UNVERIFIED_SUGGESTION_LABEL_AR = "اقتراح ذكاء اصطناعي غير مُتحقَّق منه (UNVERIFIED AI SUGGESTION)"
UPLOADED_UNCONFIRMED_LABEL_EN = "UNVERIFIED SUGGESTION — Owner confirmation required"
UPLOADED_UNCONFIRMED_LABEL_AR = "اقتراح مستخرج غير مؤكد — يتطلب تأكيد المالك"


class OwnerExcerptIn(BaseModel):
    """Short owner-selected excerpt strictly capped at 300 chars with page reference (never full copyrighted text)."""

    excerpt_id: str | None = Field(default=None, max_length=64)
    page_ref: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=MAX_EXCERPT_CHARS)

    @field_validator("page_ref", "text", mode="before")
    @classmethod
    def check_excerpt_bounds(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Excerpt page_ref and text must not be blank.")
        if len(cleaned) > MAX_EXCERPT_CHARS:
            raise ValueError(
                f"Permitted owner excerpt exceeds maximum {MAX_EXCERPT_CHARS} characters (got {len(cleaned)})."
            )
        return cleaned


class OwnerExcerptOut(BaseModel):
    """Persisted short owner excerpt."""

    excerpt_id: str
    page_ref: str
    text: str
    added_at: str = ""


class StandardCitationHitOut(BaseModel):
    """Cross-module location where a registered standard is cited across project deliverables."""

    module: Literal["specification", "calculation", "comparison", "review_report", "schedule"] | str
    artifact_id: str
    artifact_title: str
    location: str
    flagged_status: str = "ok"


class StandardCreateRequest(BaseModel):
    """Register an owner-entered engineering standard (0 AI tokens, never from model memory)."""

    project_id: str | None = Field(default=None, max_length=64)
    standard_number: str = Field(..., min_length=2, max_length=128)
    title: str = Field(..., min_length=2, max_length=512)
    issuing_body: str = Field(default="", max_length=255)
    edition_year: str = Field(default="unknown", max_length=64)
    status: StandardStatus = "unknown"
    superseded_by_id: str | None = Field(default=None, max_length=64)
    supersession_note: str | None = Field(default=None, max_length=1000)
    jurisdiction: str = Field(default="", max_length=255)
    adopted_locally: bool = False
    owner_notes: str | None = Field(default=None, max_length=2000)
    owner_excerpts: list[OwnerExcerptIn] = Field(default_factory=list, max_length=25)

    @field_validator("standard_number", "title", mode="before")
    @classmethod
    def clean_required_txt(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("standard_number and title must not be blank.")
        return cleaned

    @field_validator("project_id", "superseded_by_id", mode="before")
    @classmethod
    def clean_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("edition_year", mode="before")
    @classmethod
    def clean_edition(cls, value: str | None) -> str:
        cleaned = str(value or "").strip()
        return cleaned or "unknown"


class StandardUpdateRequest(BaseModel):
    """Update owner standard metadata, versioned history, short excerpts, or supersession link."""

    standard_number: str | None = Field(default=None, min_length=2, max_length=128)
    title: str | None = Field(default=None, min_length=2, max_length=512)
    issuing_body: str | None = Field(default=None, max_length=255)
    edition_year: str | None = Field(default=None, max_length=64)
    status: StandardStatus | None = None
    superseded_by_id: str | None = Field(default=None, max_length=64)
    supersession_note: str | None = Field(default=None, max_length=1000)
    jurisdiction: str | None = Field(default=None, max_length=255)
    adopted_locally: bool | None = None
    owner_notes: str | None = Field(default=None, max_length=2000)
    owner_excerpts: list[OwnerExcerptIn] | None = None
    confirm_metadata: bool = False
    change_note: str = Field(default="Owner metadata update", max_length=500)


class StandardConfirmRequest(BaseModel):
    """Explicit owner confirmation (and optional edits) for uploaded standard metadata suggestions."""

    standard_number: str | None = Field(default=None, min_length=2, max_length=128)
    title: str | None = Field(default=None, min_length=2, max_length=512)
    issuing_body: str | None = Field(default=None, max_length=255)
    edition_year: str | None = Field(default=None, max_length=64)
    status: StandardStatus | None = None
    jurisdiction: str | None = Field(default=None, max_length=255)
    adopted_locally: bool | None = None
    owner_notes: str | None = Field(default=None, max_length=2000)
    owner_excerpts: list[OwnerExcerptIn] | None = None
    confirmed_by: str = Field(default="Owner", min_length=2, max_length=128)


class StandardSupersedeRequest(BaseModel):
    """Owner-registered supersession link replacing an older edition with a newer registered standard."""

    superseded_by_id: str | None = Field(default=None, max_length=64)
    new_standard: StandardCreateRequest | None = None
    supersession_note: str = Field(..., min_length=3, max_length=1000)


class StandardDocumentOut(BaseModel):
    """Serialized owner-supplied / licensed standard record with citations and version history."""

    id: str
    project_id: str | None = None
    standard_number: str
    title: str
    issuing_body: str = ""
    edition_year: str = "unknown"
    status: StandardStatus | str
    superseded_by_id: str | None = None
    superseded_by_number: str | None = None
    superseded_by_title: str | None = None
    replacement_chain_summary: str | None = None
    supersession_note: str | None = None
    jurisdiction: str = ""
    adopted_locally: bool = False
    owner_notes: str | None = None
    owner_excerpts: list[OwnerExcerptOut] = Field(default_factory=list)
    metadata_status: MetadataStatus | str
    metadata_label: str = ""
    suggested_metadata: dict[str, Any] | None = None
    use_ai: bool = False
    ai_suggestion_status: AiSuggestionStatus | str
    tokens_used: int = 0
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    original_filename: str | None = None
    file_relative_path: str | None = None
    file_sha256: str | None = None
    file_size_bytes: int | None = None
    mime_type: str | None = None
    version: int
    history: list[dict[str, Any]] = Field(default_factory=list)
    where_cited: list[StandardCitationHitOut] = Field(default_factory=list)
    citation_warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class StandardListResponse(BaseModel):
    """Searchable list of owner-supplied / licensed standards."""

    standards: list[StandardDocumentOut] = Field(default_factory=list)
    total: int


class StandardRegisterExportRequest(BaseModel):
    """Export standards register (DOCX, PDF, XLSX in Arabic RTL or English LTR) with statuses and citations."""

    project_id: str | None = Field(default=None, max_length=64)
    language: ReportLanguage = "ar"
    classification: ProjectClassification = "Preliminary"


class StandardRegisterExportFileOut(BaseModel):
    """Generated immutable standards register file descriptor with SHA-256."""

    format: Literal["docx", "pdf", "xlsx"]
    filename: str
    relative_path: str
    sha256: str
    size_bytes: int
    download_url: str


class StandardRegisterExportOut(BaseModel):
    """Immutable exported standards register bundle (DOCX, PDF, XLSX)."""

    project_id: str | None = None
    language: ReportLanguage | str
    standards_count: int
    cited_warnings_count: int
    files: list[StandardRegisterExportFileOut] = Field(default_factory=list)


class StandardPresetOut(BaseModel):
    """Synthetic fixture standard metadata (strictly fake SYN-* numbers, 0% real standard texts or client data)."""

    key: str
    label_en: str
    label_ar: str
    standard: StandardCreateRequest


class StandardPresetListResponse(BaseModel):
    """List of synthetic Step 17 presets (SYN-* fake identifiers only)."""

    presets: list[StandardPresetOut] = Field(default_factory=list)
