"""Pydantic schemas and provenance constants for Step 14 technical specifications generator."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut, ReportLanguage
from app.schemas.tasks import TaskTokenUsageOut

SpecPartKey = Literal[
    "scope",
    "standards",
    "materials",
    "execution",
    "testing",
    "acceptance",
    "submittals",
    "warranty",
]

SPEC_SECTION_PARTS: tuple[SpecPartKey, ...] = (
    "scope",
    "standards",
    "materials",
    "execution",
    "testing",
    "acceptance",
    "submittals",
    "warranty",
)

NO_VERIFIED_STANDARD_LABEL = "no verified standard on file - verify against the locally adopted code"
VERIFY_CODE_LABEL = "verify against the locally adopted code"
AI_UNVERIFIED_DRAFT_LABEL_EN = "UNVERIFIED AI DRAFT — Pending Owner Approval"
AI_UNVERIFIED_DRAFT_LABEL_AR = "مسودة ذكاء اصطناعي غير مُتحقَّق منها — بانتظار اعتماد المالك"

SpecDraftStatus = Literal["not_used", "unverified_ai_draft", "owner_approved"]
ClauseOrigin = Literal["deterministic_template", "ai_unverified_draft", "owner_approved"]


class SpecTraceRef(BaseModel):
    """Explicit source anchor linking every specification clause to a BOQ item, drawing/schedule, or verified source."""

    trace_id: str
    trace_kind: Literal["boq_item", "drawing", "drawing_schedule", "research_source"]
    boq_sheet_id: str | None = None
    boq_item_id: str | None = None
    boq_item_no: str | None = None
    drawing_id: str | None = None
    drawing_no: str | None = None
    schedule_kind: str | None = None
    research_source_id: str | None = None
    source_url: str | None = None
    label: str


class SpecClause(BaseModel):
    """Single specification clause anchored to >= 1 real BOQ item, drawing schedule, or verified research source."""

    clause_id: str
    part: SpecPartKey
    text: str
    draft_origin: ClauseOrigin = "deterministic_template"
    trace_refs: list[SpecTraceRef] = Field(..., min_length=1)


class SpecStandardCitation(BaseModel):
    """Standard citation pulled ONLY from reviewed ResearchSource entries, else explicit no-verified-standard notice."""

    research_source_id: str | None = None
    source_name: str
    url: str = ""
    publication_date: str | None = None
    status: Literal["verified_source_log", "no_verified_standard_on_file"]
    citation_text: str
    verification_label: str = NO_VERIFIED_STANDARD_LABEL


class SpecSection(BaseModel):
    """Complete CSI/engineering specification section mapped to project BOQs, drawings, and verified sources."""

    section_code: str
    title: str
    discipline: str
    mapped_boq_item_ids: list[str] = Field(default_factory=list)
    mapped_drawing_ids: list[str] = Field(default_factory=list)
    mapped_drawing_refs: list[str] = Field(default_factory=list)
    standards: list[SpecStandardCitation] = Field(default_factory=list)
    clauses: list[SpecClause] = Field(default_factory=list)
    missing_parts: list[str] = Field(default_factory=list)


class SpecificationGenerateRequest(BaseModel):
    """Request payload to generate a traceable specification package from real project BOQs, drawings, and research."""

    task_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    discipline: str = Field(default="multidisciplinary", min_length=1, max_length=64)
    language: ReportLanguage = "ar"
    classification: ProjectClassification = "Preliminary"
    boq_sheet_ids: list[str] = Field(default_factory=list, max_length=50)
    drawing_ids: list[str] = Field(default_factory=list, max_length=50)
    research_source_ids: list[str] = Field(default_factory=list, max_length=100)
    use_ai: bool = False
    complexity: TaskComplexity = "fast"
    change_note: str | None = Field(default=None, max_length=500)

    @field_validator("task_id", "title", "change_note", mode="before")
    @classmethod
    def clean_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("discipline")
    @classmethod
    def clean_discipline(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("discipline must not be blank.")
        return cleaned


class SpecificationApproveRequest(BaseModel):
    """Owner sign-off approving an AI-drafted specification prose wording (never alters deterministic mappings)."""

    approved_by: str = Field(default="Owner", min_length=2, max_length=128)
    approval_note: str | None = Field(default=None, max_length=1000)
    export_after_approval: bool = True

    @field_validator("approved_by", "approval_note", mode="before")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class SpecificationExportRequest(BaseModel):
    """Save an immutable versioned DOCX + PDF specification deliverable set in AR or EN with SHA-256."""

    language: ReportLanguage | None = None
    change_note: str | None = Field(default=None, max_length=500)


class SpecificationSummaryOut(BaseModel):
    """Persisted technical specification package summary."""

    id: str
    project_id: str
    project_code: str = ""
    project_name: str = ""
    task_id: str | None = None
    title: str
    discipline: str
    language: ReportLanguage | str
    classification: ProjectClassification | str
    revision: str
    version: int
    export_version: int
    status: str
    use_ai: bool
    ai_draft_status: SpecDraftStatus | str
    ai_draft_label: str = ""
    owner_approved_by: str | None = None
    owner_approved_at: datetime | None = None
    sections_count: int = 0
    clauses_count: int = 0
    tokens_used: int = 0
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class SpecificationDetailOut(SpecificationSummaryOut):
    """Complete Step 14 specification detail including mapped BOQ/drawing/source IDs, sections, and SHA-256 deliverables."""

    source_boq_sheet_ids: list[str] = Field(default_factory=list)
    source_drawing_ids: list[str] = Field(default_factory=list)
    source_research_ids: list[str] = Field(default_factory=list)
    missing_standards_notices: list[str] = Field(default_factory=list)
    sections: list[SpecSection] = Field(default_factory=list)
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    deliverables: list[DeliverableOut] = Field(default_factory=list)


class SpecificationListResponse(BaseModel):
    """Collection of project technical specification packages."""

    specifications: list[SpecificationSummaryOut] = Field(default_factory=list)
    total: int


class SpecificationExportOut(BaseModel):
    """Result of exporting immutable DOCX + PDF specifications into 07_Technical_Specifications."""

    specification: SpecificationDetailOut
    docx_deliverable: DeliverableOut
    pdf_deliverable: DeliverableOut


class SpecificationPresetOut(BaseModel):
    """Synthetic fixture recipe (0% client data) illustrating Step 14 specification generation."""

    key: str
    title_en: str
    title_ar: str
    description_en: str
    description_ar: str
    discipline: str
    boq_items: list[dict[str, Any]] = Field(default_factory=list)
    drawing_summary: dict[str, Any] = Field(default_factory=dict)
    reviewed_source: dict[str, Any] = Field(default_factory=dict)
    request_defaults: SpecificationGenerateRequest


class SpecificationPresetListResponse(BaseModel):
    """Synthetic Step 14 specification examples (0% client data)."""

    presets: list[SpecificationPresetOut] = Field(default_factory=list)
