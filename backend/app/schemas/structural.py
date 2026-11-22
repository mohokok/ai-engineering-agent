"""Pydantic schemas and mandatory disclaimers for Step 19 structural assessment support & I/O checking skills."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut
from app.schemas.specialist import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NOT_PROVIDED_LABEL,
    NO_VERIFIED_STANDARD_LABEL,
    SpecialistReferenceIn,
    SpecialistReferenceOut,
)
from app.schemas.tasks import TaskTokenUsageOut

StructuralAssessmentType = Literal[
    "takedown_check",
    "load_combinations",
    "simple_statics_beam",
    "full_structural_check",
]
StructuralLanguage = Literal["ar", "en"]

PRELIMINARY_STRUCTURAL_LABEL_EN = "PRELIMINARY - for review by a licensed structural engineer"
PRELIMINARY_STRUCTURAL_LABEL_AR = "أولي (PRELIMINARY) — للمراجعة والاعتماد من مهندس إنشائي مرخص فقط"

STRUCTURAL_SOFTWARE_RECOMMENDATION = (
    "Assessment support & input/output checking ONLY (never designs members or certifies safety). "
    "Use validated commercial structural software for final analysis & code design "
    "(e.g., ETABS, SAP2000, SAFE, RAM Structural System, Robot Structural Analysis) reviewed by a licensed structural engineer."
)

__all__ = [
    "AI_UNVERIFIED_DRAFT_LABEL_AR",
    "AI_UNVERIFIED_DRAFT_LABEL_EN",
    "NOT_PROVIDED_LABEL",
    "NO_VERIFIED_STANDARD_LABEL",
    "PRELIMINARY_STRUCTURAL_LABEL_AR",
    "PRELIMINARY_STRUCTURAL_LABEL_EN",
    "STRUCTURAL_SOFTWARE_RECOMMENDATION",
    "SpecialistReferenceIn",
    "SpecialistReferenceOut",
]


class StructuralAssessmentCreateRequest(BaseModel):
    """Create and run a deterministic Step 19 structural takedown/combination/statics I/O check (0 AI tokens default)."""

    task_id: str | None = Field(default=None, max_length=64)
    assessment_type: StructuralAssessmentType = "full_structural_check"
    title: str = Field(..., min_length=2, max_length=255)
    language: StructuralLanguage = "ar"
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


class StructuralAssessmentUpdateRequest(BaseModel):
    """Update structural inputs, type, references, classification, or title and deterministically recompute."""

    assessment_type: StructuralAssessmentType | None = None
    title: str | None = Field(default=None, min_length=2, max_length=255)
    language: StructuralLanguage | None = None
    classification: ProjectClassification | None = None
    revision: str | None = Field(default=None, min_length=1, max_length=32)
    inputs: dict[str, Any] | None = None
    references: list[SpecialistReferenceIn] | None = None


class StructuralApproveRequest(BaseModel):
    """Explicit licensed structural engineer / owner approval clearing UNVERIFIED AI DRAFT state."""

    approved_by: str = Field(default="Licensed Structural Engineer", min_length=2, max_length=128)
    approval_note: str | None = Field(default=None, max_length=500)


class StructuralExportRequest(BaseModel):
    """Request immutable Arabic RTL or English LTR DOCX + PDF + live-formula XLSX structural report."""

    language: StructuralLanguage | None = None


class StructuralSummaryOut(BaseModel):
    """Compact listing item for Step 19 structural assessments."""

    id: str
    project_id: str
    project_code: str = ""
    project_name: str = ""
    task_id: str | None = None
    assessment_type: StructuralAssessmentType | str
    title: str
    language: StructuralLanguage | str
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
    ai_draft_status: Literal["not_used", "unverified_ai_draft", "owner_approved"] | str
    ai_draft_label: str = ""
    owner_approved_by: str | None = None
    owner_approved_at: datetime | None = None
    tokens_used: int = 0
    preliminary_label: str = PRELIMINARY_STRUCTURAL_LABEL_EN
    software_recommendation: str = STRUCTURAL_SOFTWARE_RECOMMENDATION
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class StructuralDetailOut(StructuralSummaryOut):
    """Full Step 19 structural assessment payload, prepared items, checks, references, and SHA-256 deliverables."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    references: list[SpecialistReferenceOut] = Field(default_factory=list)
    preliminary_assumptions: list[str] = Field(default_factory=list)
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    deliverables: list[DeliverableOut] = Field(default_factory=list)


class StructuralListResponse(BaseModel):
    """Project-scoped Step 19 structural assessments collection."""

    assessments: list[StructuralSummaryOut] = Field(default_factory=list)
    total: int


class StructuralExportOut(BaseModel):
    """Exported immutable DOCX + PDF + XLSX bundle returned by POST /api/structural-assessments/{id}/export."""

    assessment: StructuralDetailOut
    docx_deliverable: DeliverableOut
    pdf_deliverable: DeliverableOut
    xlsx_deliverable: DeliverableOut


class StructuralPresetOut(BaseModel):
    """Synthetic Step 19 fixture preset (synthetic inputs only, explicitly PRELIMINARY)."""

    key: str
    assessment_type: StructuralAssessmentType
    label_en: str
    label_ar: str
    preliminary_warning: str = PRELIMINARY_STRUCTURAL_LABEL_EN
    inputs: dict[str, Any]


class StructuralPresetListResponse(BaseModel):
    """List of synthetic Step 19 structural checking presets."""

    presets: list[StructuralPresetOut] = Field(default_factory=list)
