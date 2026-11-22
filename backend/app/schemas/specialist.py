"""Pydantic schemas and provenance constants for Step 18 HVAC, Fire, and Healthcare input preparation & output checking skills."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut
from app.schemas.tasks import TaskTokenUsageOut

SpecialistDomain = Literal["hvac", "fire", "healthcare"]
SpecialistWorkflowMode = Literal["input_preparation", "output_check", "full_preflight"]
SpecialistAiDraftStatus = Literal["not_used", "unverified_ai_draft", "owner_approved"]
SpecialistReferenceKind = Literal["standard_library", "verified_source_log", "no_verified_standard_on_file"]
SpecialistLanguage = Literal["ar", "en"]

NOT_PROVIDED_LABEL = "not provided"
NO_VERIFIED_STANDARD_LABEL = "no verified standard on file - verify against the locally adopted code"
PRELIMINARY_ENGINEER_LABEL_EN = (
    "Preliminary — assumptions, presets, and engineering thresholds must be verified by a licensed engineer"
)
PRELIMINARY_ENGINEER_LABEL_AR = (
    "أولي (Preliminary) — جميع الافتراضات والحدود الأولية يجب التحقق منها واعتمادها من مهندس مرخص"
)
AI_UNVERIFIED_DRAFT_LABEL_EN = "UNVERIFIED AI DRAFT — prose not yet verified or approved by owner"
AI_UNVERIFIED_DRAFT_LABEL_AR = "مسودة ذكاء اصطناعي غير مُتحقَّق منها (UNVERIFIED AI DRAFT) — بانتظار اعتماد المالك"


class SpecialistReferenceIn(BaseModel):
    """Reference binding to owner Standards Library or reviewed ResearchSource log ONLY (zero invented codes)."""

    source_kind: SpecialistReferenceKind = "no_verified_standard_on_file"
    standard_library_id: str | None = Field(default=None, max_length=64)
    research_source_id: str | None = Field(default=None, max_length=64)
    citation_note: str | None = Field(default=None, max_length=500)


class SpecialistReferenceOut(BaseModel):
    """Normalized standard citation showing explicit fallback when no verified standard is on file."""

    source_kind: SpecialistReferenceKind | str
    standard_library_id: str | None = None
    research_source_id: str | None = None
    code_or_source_name: str
    edition_or_date: str = "unknown"
    status: str = "no_verified_standard_on_file"
    citation_note: str | None = None
    verification_label: str = NO_VERIFIED_STANDARD_LABEL


class SpecialistAssessmentCreateRequest(BaseModel):
    """Create and execute a deterministic Step 18 HVAC, Fire, or Healthcare preparation/check assessment (0 AI tokens default)."""

    task_id: str | None = Field(default=None, max_length=64)
    domain: SpecialistDomain
    workflow_mode: SpecialistWorkflowMode = "full_preflight"
    title: str = Field(..., min_length=2, max_length=255)
    language: SpecialistLanguage = "ar"
    classification: ProjectClassification = "Preliminary"
    revision: str = Field(default="Rev 01", min_length=1, max_length=32)
    inputs: dict[str, Any] = Field(default_factory=dict)
    references: list[SpecialistReferenceIn] = Field(default_factory=list)
    use_ai: bool = False
    complexity: Literal["fast", "deep", "maximum"] = "fast"

    @field_validator("title", "revision", mode="before")
    @classmethod
    def clean_non_blank(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Title and revision must not be blank.")
        return cleaned


class SpecialistAssessmentUpdateRequest(BaseModel):
    """Update inputs, mode, references, classification, or title and deterministically re-run checks."""

    workflow_mode: SpecialistWorkflowMode | None = None
    title: str | None = Field(default=None, min_length=2, max_length=255)
    language: SpecialistLanguage | None = None
    classification: ProjectClassification | None = None
    revision: str | None = Field(default=None, min_length=1, max_length=32)
    inputs: dict[str, Any] | None = None
    references: list[SpecialistReferenceIn] | None = None


class SpecialistApproveRequest(BaseModel):
    """Explicit owner/engineer sign-off clearing UNVERIFIED AI DRAFT status."""

    approved_by: str = Field(default="Licensed Engineer / Owner", min_length=2, max_length=128)
    approval_note: str | None = Field(default=None, max_length=500)


class SpecialistExportRequest(BaseModel):
    """Request immutable Arabic RTL or English LTR DOCX + PDF + live-formula XLSX exports."""

    language: SpecialistLanguage | None = None


class SpecialistSummaryOut(BaseModel):
    """Compact summary row for Step 18 specialist assessments."""

    id: str
    project_id: str
    project_code: str = ""
    project_name: str = ""
    task_id: str | None = None
    domain: SpecialistDomain | str
    workflow_mode: SpecialistWorkflowMode | str
    title: str
    language: SpecialistLanguage | str
    classification: ProjectClassification | str
    revision: str
    version: int
    export_version: int
    status: str
    checks_passed: bool
    blocked_missing_count: int
    failed_checks_count: int
    standards_status: str
    use_ai: bool
    ai_draft_status: SpecialistAiDraftStatus | str
    ai_draft_label: str = ""
    owner_approved_by: str | None = None
    owner_approved_at: datetime | None = None
    tokens_used: int = 0
    preliminary_label: str = PRELIMINARY_ENGINEER_LABEL_EN
    software_recommendation: str = ""
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class SpecialistDetailOut(SpecialistSummaryOut):
    """Complete Step 18 assessment payload with prepared inputs, deterministic checks, provenance, and deliverables."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    references: list[SpecialistReferenceOut] = Field(default_factory=list)
    preliminary_assumptions: list[str] = Field(default_factory=list)
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    deliverables: list[DeliverableOut] = Field(default_factory=list)


class SpecialistListResponse(BaseModel):
    """Project-scoped Step 18 specialist assessments list."""

    assessments: list[SpecialistSummaryOut] = Field(default_factory=list)
    total: int


class SpecialistExportOut(BaseModel):
    """Exported immutable DOCX + PDF + XLSX bundle returned by POST /api/specialist-assessments/{id}/export."""

    assessment: SpecialistDetailOut
    docx_deliverable: DeliverableOut
    pdf_deliverable: DeliverableOut
    xlsx_deliverable: DeliverableOut


class SpecialistPresetOut(BaseModel):
    """Synthetic Step 18 fixture preset (synthetic values only, explicitly labelled preliminary)."""

    key: str
    domain: SpecialistDomain
    workflow_mode: SpecialistWorkflowMode
    label_en: str
    label_ar: str
    preliminary_warning: str = PRELIMINARY_ENGINEER_LABEL_EN
    inputs: dict[str, Any]


class SpecialistPresetListResponse(BaseModel):
    """List of synthetic HVAC, Fire, and Healthcare presets."""

    presets: list[SpecialistPresetOut] = Field(default_factory=list)
