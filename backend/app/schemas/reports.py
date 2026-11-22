"""Pydantic schemas for Step 09 document/drawing review findings reports and deliverables."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification
from app.schemas.tasks import TaskTokenUsageOut

ReportLanguage = Literal["ar", "en"]
FindingSeverity = Literal["critical", "high", "medium", "low", "info"]
FindingStatus = Literal["open", "needs_verification", "resolved"]
StatementCategory = Literal[
    "verified_fact",
    "calculated",
    "ocr_unverified",
    "assumption",
    "recommendation",
]


class SourceLocationRef(BaseModel):
    """Exact provenance link tying a finding or statement to an extraction item or reviewed research source."""

    ref_id: str
    source_kind: Literal["extraction", "research_source"]
    source_id: str
    file_id: str | None = None
    extraction_id: str | None = None
    research_run_id: str | None = None
    url: str | None = None
    source_name: str
    page_or_sheet: str
    location: str
    excerpt: str | None = None


class ReviewFinding(BaseModel):
    """Structured review finding anchored to >= 1 extracted or researched source location."""

    finding_id: str
    discipline: str
    severity: FindingSeverity
    location_or_drawing_ref: str
    evidence: str
    recommendation: str
    status: FindingStatus
    statement_category: StatementCategory = "verified_fact"
    source_links: list[SourceLocationRef] = Field(..., min_length=1)


class CategorizedStatement(BaseModel):
    """Single statement strictly categorized as verified_fact, calculated, assumption, or recommendation."""

    category: StatementCategory
    text: str
    formula_or_method: str | None = None
    source_links: list[SourceLocationRef] = Field(default_factory=list)


class DocumentRegisterEntry(BaseModel):
    """Plain per-file inventory row tracking extraction scope, status, and confidence."""

    file_name: str
    file_type: str
    pages_or_entities: str
    extraction_status: str
    confidence: str


class OcrExtractedTextItem(BaseModel):
    """Unverified OCR text excerpt separated strictly from deterministic Verified Facts."""

    file_id: str | None = None
    source_file: str
    page_or_sheet: str
    confidence_mean: float | None = None
    low_confidence: bool = False
    native_text_unreliable: bool = False
    status_label: str
    text: str
    source_links: list[SourceLocationRef] = Field(default_factory=list)


class RevisionBlockOut(BaseModel):
    """Mandatory document control and revision block embedded into DOCX, PDF, and UI."""

    version: int
    revision: str
    classification: ProjectClassification | str
    prepared_by: str
    review_notice: str
    issued_at_iso: str
    change_note: str
    source_files_count: int
    reviewed_research_count: int


class ReviewReportGenerateRequest(BaseModel):
    """Request payload to review project extractions & research logs and generate DOCX/PDF deliverables."""

    task_id: str | None = Field(default=None, max_length=64)
    file_ids: list[str] = Field(default_factory=list, max_length=50)
    research_run_ids: list[str] = Field(default_factory=list, max_length=20)
    title: str | None = Field(default=None, max_length=255)
    discipline: str = Field(default="multidisciplinary", min_length=1, max_length=64)
    language: ReportLanguage = "ar"
    classification: ProjectClassification = "Preliminary"
    review_notes: str | None = Field(default=None, max_length=2000)
    change_note: str | None = Field(default=None, max_length=500)
    use_ai: bool = False
    complexity: TaskComplexity = "fast"

    @field_validator("task_id", "title", "review_notes", "change_note", mode="before")
    @classmethod
    def clean_optional_strings(cls, value: str | None) -> str | None:
        """Trim blank optional text cleanly."""
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("discipline")
    @classmethod
    def strip_discipline(cls, value: str) -> str:
        """Ensure non-blank discipline string."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("discipline must not be blank.")
        return cleaned


class ReviewAiSynthesizeRequest(BaseModel):
    """Explicit confirmation payload to enhance an existing review report with capped Gemini synthesis."""

    complexity: TaskComplexity = "fast"


class DeliverableOut(BaseModel):
    """Serialized persisted deliverable file stored under 04_Engineering_Calculations, 05_Design_Drawings, 06_BOQ, 08_Reports, or 10_Final_Deliverables."""

    id: str
    project_id: str
    report_id: str | None = None
    boq_id: str | None = None
    drawing_id: str | None = None
    calculation_id: str | None = None
    specification_id: str | None = None
    comparison_id: str | None = None
    task_id: str | None = None
    file_id: str | None = None
    title: str
    deliverable_type: str
    discipline: str
    format: str
    classification: ProjectClassification | str
    status: str
    version: int
    folder_name: str | None = None
    filename: str | None = None
    relative_path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    summary: str | None = None
    download_url: str
    created_at: datetime
    updated_at: datetime


class DeliverableListResponse(BaseModel):
    """Collection of generated deliverables across or within projects."""

    deliverables: list[DeliverableOut] = Field(default_factory=list)
    total: int
    classification: ProjectClassification = "Preliminary"


class ReviewReportSummaryOut(BaseModel):
    """Summary metadata for a generated review report."""

    id: str
    project_id: str
    project_code: str
    project_name: str
    task_id: str | None = None
    title: str
    discipline: str
    language: ReportLanguage | str
    classification: ProjectClassification | str
    revision: str
    version: int
    status: str
    summary: str | None = None
    findings_count: int = 0
    estimated_prompt_tokens: int = 0
    prompt_char_count: int = 0
    prompt_char_cap: int = 10_000
    step04_daily_tokens_remaining: int | None = None
    step04_monthly_tokens_remaining: int | None = None
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ReviewReportDetailOut(ReviewReportSummaryOut):
    """Complete review report payload including document register, separated unverified OCR, findings, and deliverables."""

    is_inventory_only: bool = True
    revision_block: RevisionBlockOut
    document_register: list[DocumentRegisterEntry] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    verified_facts: list[CategorizedStatement] = Field(default_factory=list)
    verified_facts_total: int = 0
    verified_facts_shown: int = 0
    appendix_verified_facts: list[CategorizedStatement] = Field(default_factory=list)
    ocr_text_items: list[OcrExtractedTextItem] = Field(default_factory=list)
    ocr_text_items_total: int = 0
    calculated_items: list[CategorizedStatement] = Field(default_factory=list)
    assumptions: list[CategorizedStatement] = Field(default_factory=list)
    recommendations: list[CategorizedStatement] = Field(default_factory=list)
    gaps_or_unextracted: list[str] = Field(default_factory=list)
    source_registry: list[SourceLocationRef] = Field(default_factory=list)
    deliverables: list[DeliverableOut] = Field(default_factory=list)


class ReviewReportListResponse(BaseModel):
    """List of project review reports ordered newest first."""

    reports: list[ReviewReportSummaryOut] = Field(default_factory=list)
    total: int
    classification: ProjectClassification = "Preliminary"
