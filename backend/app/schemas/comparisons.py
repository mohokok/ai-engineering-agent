"""Pydantic schemas and provenance constants for Step 15 technical comparison module."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut, ReportLanguage
from app.schemas.tasks import TaskTokenUsageOut

ComparisonScope = Literal["equipment", "material", "vendor_offer", "system_alternative"]
ComparisonCategory = Literal[
    "compliance",
    "performance",
    "safety",
    "durability",
    "energy",
    "maintainability",
    "constructability",
    "initial_cost",
    "operating_cost",
    "lifecycle_cost",
    "risks",
]
ScoringDirection = Literal["higher_better", "lower_better", "boolean_pass", "direct_score_0_100"]
ComparisonSourceKind = Literal[
    "boq_item",
    "specification",
    "calculation",
    "research_source",
    "owner_entered",
]
ComparisonDraftStatus = Literal["not_used", "unverified_ai_draft", "owner_approved"]
OwnerDecisionStatus = Literal["pending_owner_decision", "owner_selected"]
UnitCheckStatus = Literal["exact", "converted_explicitly", "flagged_mismatch", "not_applicable"]

NOT_PROVIDED_LABEL = "not provided"
VERIFY_CODE_LABEL = "verify against the locally adopted code"
ADVISORY_NOTICE_EN = (
    "Advisory Comparison Matrix Only — No recommendation is final; final technical & commercial selection rests strictly with the Owner / Licensed Engineer."
)
ADVISORY_NOTICE_AR = (
    "مصفوفة مقارنة استشارية فقط — لا تُعد أي توصية نهائية؛ القرار النهائي للاعتماد الفني والتجاري حصراً بيد المالك / المهندس المرخص."
)
AI_UNVERIFIED_DRAFT_LABEL_EN = "UNVERIFIED AI DRAFT"
AI_UNVERIFIED_DRAFT_LABEL_AR = "مسودة ذكاء اصطناعي غير مُتحقَّق منها (UNVERIFIED AI DRAFT)"


class ComparisonCriterionIn(BaseModel):
    """Weighted comparison criterion anchored to real project data or owner-defined specification basis."""

    criterion_id: str = Field(..., min_length=1, max_length=64)
    category: ComparisonCategory
    label: str = Field(..., min_length=2, max_length=255)
    weight: str | float | int = Field(..., description="Percentage weight (>0, all weights must sum strictly to 100).")
    is_mandatory: bool = False
    direction: ScoringDirection = "higher_better"
    target_unit: str = Field(default="score_0_100", min_length=1, max_length=64)
    mandatory_min: float | None = None
    mandatory_max: float | None = None
    mandatory_expected_bool: bool | None = None
    source_kind: ComparisonSourceKind = "owner_entered"
    source_ref: str = Field(..., min_length=2, max_length=1000)
    boq_item_id: str | None = Field(default=None, max_length=64)
    specification_id: str | None = Field(default=None, max_length=64)
    calculation_id: str | None = Field(default=None, max_length=64)
    research_source_id: str | None = Field(default=None, max_length=64)

    @field_validator("criterion_id", "label", "target_unit", "source_ref", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Criterion text fields must not be blank.")
        return cleaned


class ComparisonCellIn(BaseModel):
    """Single option metric value with mandatory provenance reference and engineering unit."""

    criterion_id: str = Field(..., min_length=1, max_length=64)
    value: float | int | str | bool | None = None
    unit: str | None = Field(default=None, max_length=64)
    source_kind: ComparisonSourceKind = "owner_entered"
    source_ref: str | None = Field(default=None, max_length=1000)
    boq_item_id: str | None = Field(default=None, max_length=64)
    specification_id: str | None = Field(default=None, max_length=64)
    calculation_id: str | None = Field(default=None, max_length=64)
    research_source_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)


class ComparisonOptionIn(BaseModel):
    """Single candidate equipment, material, system alternative, or vendor offer."""

    option_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=2, max_length=255)
    vendor_or_source: str = Field(default="", max_length=255)
    risks: list[str] = Field(default_factory=list, max_length=50)
    cells: list[ComparisonCellIn] = Field(default_factory=list)


class ComparisonCreateRequest(BaseModel):
    """Create and deterministically evaluate a weighted multi-criteria comparison (default 0 AI tokens)."""

    task_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    comparison_scope: ComparisonScope = "equipment"
    discipline: str = Field(default="multidisciplinary", min_length=1, max_length=64)
    language: ReportLanguage = "ar"
    classification: ProjectClassification = "Preliminary"
    revision: str = Field(default="Rev 01", min_length=1, max_length=32)
    lifecycle_years: float | None = Field(default=None, gt=0.0, le=100.0)
    criteria: list[ComparisonCriterionIn] = Field(..., min_length=1, max_length=50)
    options: list[ComparisonOptionIn] = Field(..., min_length=2, max_length=25)
    use_ai: bool = False
    complexity: TaskComplexity = "fast"

    @field_validator("task_id", "title", mode="before")
    @classmethod
    def clean_opts(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ComparisonDecideRequest(BaseModel):
    """Record explicit owner/engineer final decision (and optional approval of AI narrative)."""

    selected_option_id: str = Field(..., min_length=1, max_length=64)
    decided_by: str = Field(default="Owner", min_length=2, max_length=128)
    decision_note: str = Field(..., min_length=5, max_length=2000)
    approve_ai_draft: bool = True
    export_after_decision: bool = True


class ComparisonExportRequest(BaseModel):
    """Export immutable versioned DOCX, PDF, and XLSX comparison deliverables into 09_Comparisons."""

    language: ReportLanguage | None = None


class EvaluatedCellOut(BaseModel):
    """Deterministically scored matrix cell with unit normalization and provenance preserved."""

    criterion_id: str
    category: ComparisonCategory | str
    label: str
    weight: float
    is_mandatory: bool
    raw_value: float | int | str | bool | None = None
    display_value: str
    raw_unit: str
    target_unit: str
    converted_value: str | None = None
    unit_status: UnitCheckStatus | str
    conversion_note: str | None = None
    is_missing: bool
    mandatory_passed: bool | None = None
    normalized_score: float
    weighted_score: float
    source_kind: ComparisonSourceKind | str
    source_ref: str
    boq_item_id: str | None = None
    specification_id: str | None = None
    calculation_id: str | None = None
    research_source_id: str | None = None
    notes: str | None = None


class EvaluatedOptionOut(BaseModel):
    """Weighted score, mandatory gate verdict, lifecycle check, and risks per option."""

    option_id: str
    name: str
    vendor_or_source: str = ""
    advisory_rank: int
    total_weighted_score: float
    mandatory_passed: bool
    failed_mandatory_criteria: list[str] = Field(default_factory=list)
    missing_values_count: int = 0
    unit_mismatch_count: int = 0
    risks: list[str] = Field(default_factory=list)
    cells: list[EvaluatedCellOut] = Field(default_factory=list)


class ComparisonMatrixOut(BaseModel):
    """Complete deterministic Decimal comparison matrix output."""

    total_weight: float
    weights_sum_valid: bool
    advisory_notice: str
    leading_option_id: str | None = None
    leading_option_name: str | None = None
    unit_mismatch_flags: list[str] = Field(default_factory=list)
    missing_mandatory_flags: list[str] = Field(default_factory=list)
    options: list[EvaluatedOptionOut] = Field(default_factory=list)


class TechnicalComparisonSummaryOut(BaseModel):
    """Persisted technical comparison summary."""

    id: str
    project_id: str
    project_code: str = ""
    project_name: str = ""
    task_id: str | None = None
    title: str
    comparison_scope: ComparisonScope | str
    discipline: str
    language: ReportLanguage | str
    classification: ProjectClassification | str
    revision: str
    version: int
    export_version: int
    status: str
    use_ai: bool
    ai_draft_status: ComparisonDraftStatus | str
    ai_draft_label: str = ""
    owner_decision_status: OwnerDecisionStatus | str
    owner_selected_option_id: str | None = None
    owner_decision_note: str | None = None
    owner_decided_by: str | None = None
    owner_decided_at: datetime | None = None
    total_weight: float
    criteria_count: int
    options_count: int
    tokens_used: int = 0
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class TechnicalComparisonDetailOut(TechnicalComparisonSummaryOut):
    """Full Step 15 technical comparison output with weighted criteria, evaluated options, flags, and SHA-256 deliverables."""

    criteria: list[ComparisonCriterionIn] = Field(default_factory=list)
    matrix: ComparisonMatrixOut
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    deliverables: list[DeliverableOut] = Field(default_factory=list)


class TechnicalComparisonListResponse(BaseModel):
    """Collection of project technical comparisons."""

    comparisons: list[TechnicalComparisonSummaryOut] = Field(default_factory=list)
    total: int


class TechnicalComparisonExportOut(BaseModel):
    """Immutable versioned DOCX, PDF, and XLSX export package in 09_Comparisons."""

    comparison: TechnicalComparisonDetailOut
    docx_deliverable: DeliverableOut
    pdf_deliverable: DeliverableOut
    xlsx_deliverable: DeliverableOut


class ComparisonPresetOut(BaseModel):
    """Synthetic fixture comparison preset (0% client data)."""

    key: str
    title_en: str
    title_ar: str
    comparison_scope: ComparisonScope
    discipline: str
    lifecycle_years: float | None = None
    criteria: list[ComparisonCriterionIn] = Field(default_factory=list)
    options: list[ComparisonOptionIn] = Field(default_factory=list)


class ComparisonPresetListResponse(BaseModel):
    """Synthetic Step 15 technical comparison presets (0% client data)."""

    presets: list[ComparisonPresetOut] = Field(default_factory=list)
