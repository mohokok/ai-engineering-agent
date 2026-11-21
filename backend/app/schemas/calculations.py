"""Pydantic schemas for Step 13 deterministic engineering calculation framework (electrical & plumbing)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut

VERIFY_CODE_LABEL = "verify against the locally adopted code"

CalculationDiscipline = Literal["electrical", "plumbing"]
CalculationType = Literal[
    "electrical_load_schedule",
    "electrical_cable_sizing",
    "electrical_voltage_drop",
    "plumbing_water_demand",
    "plumbing_pipe_sizing",
]
CalculationLanguage = Literal["ar", "en"]
ReferenceSourceKind = Literal["owner_supplied", "verified_source_log"]


class CalculationReferenceIn(BaseModel):
    """Owner-supplied or verified source-log reference attached to an engineering calculation."""

    source_kind: ReferenceSourceKind
    source_name: str = Field(..., min_length=2, max_length=255)
    source_ref: str = Field(..., min_length=2, max_length=1024)
    research_source_id: str | None = Field(default=None, max_length=64)
    publication_date: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=500)


class CalculationReferenceOut(BaseModel):
    """Normalized calculation reference guaranteed to carry the locally-adopted-code verification label."""

    source_kind: ReferenceSourceKind | str
    source_name: str
    source_ref: str
    research_source_id: str | None = None
    publication_date: str | None = None
    notes: str | None = None
    verification_label: str = VERIFY_CODE_LABEL


class CalculationCreateRequest(BaseModel):
    """Create and execute a deterministic Step 13 engineering calculation (0 AI tokens)."""

    task_id: str | None = Field(default=None, max_length=64)
    title: str = Field(..., min_length=2, max_length=255)
    calculation_type: CalculationType
    language: CalculationLanguage = "ar"
    classification: ProjectClassification = "Preliminary"
    revision: str = Field(default="Rev 01", min_length=1, max_length=32)
    inputs: dict[str, Any]
    assumptions_override: list[str] | None = None
    references: list[CalculationReferenceIn] = Field(..., min_length=1)

    @field_validator("title", "revision")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be blank.")
        return cleaned


class CalculationUpdateRequest(BaseModel):
    """Update inputs, title, classification, language, or references and deterministically recompute."""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    language: CalculationLanguage | None = None
    classification: ProjectClassification | None = None
    revision: str | None = Field(default=None, min_length=1, max_length=32)
    inputs: dict[str, Any] | None = None
    assumptions_override: list[str] | None = None
    references: list[CalculationReferenceIn] | None = None

    @model_validator(mode="after")
    def validate_non_empty_refs_if_supplied(self) -> "CalculationUpdateRequest":
        if self.references is not None and len(self.references) == 0:
            raise ValueError("At least one owner-supplied or verified source-log reference is required.")
        return self


class CalculationExportRequest(BaseModel):
    """Request immutable versioned DOCX, PDF, and XLSX calculation deliverables."""

    language: CalculationLanguage | None = None


class CalculationSummaryOut(BaseModel):
    """Summary row for project calculations listing."""

    id: str
    project_id: str
    project_code: str
    project_name: str
    task_id: str | None = None
    title: str
    discipline: CalculationDiscipline | str
    calculation_type: CalculationType | str
    language: CalculationLanguage | str
    classification: ProjectClassification | str
    revision: str
    version: int
    export_version: int
    status: str
    acceptance_passed: bool
    tokens_used: int = 0
    created_at: datetime
    updated_at: datetime


class CalculationDetailOut(CalculationSummaryOut):
    """Full Step 13 calculation output exposing all 8 mandatory engineering sections."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    equations: str
    method: str
    assumptions: list[str] = Field(default_factory=list)
    assumptions_text: str
    results: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: list[str] = Field(default_factory=list)
    acceptance_criteria_text: str
    references: list[CalculationReferenceOut] = Field(default_factory=list)
    references_text: str
    deliverables: list[DeliverableOut] = Field(default_factory=list)


class CalculationListResponse(BaseModel):
    """Collection of deterministic project calculations."""

    calculations: list[CalculationSummaryOut] = Field(default_factory=list)
    total: int


class CalculationExportOut(BaseModel):
    """Result of exporting calculation deliverables (DOCX, PDF, XLSX) into 04_Engineering_Calculations."""

    calculation: CalculationDetailOut
    docx_deliverable: DeliverableOut
    pdf_deliverable: DeliverableOut
    xlsx_deliverable: DeliverableOut


class CalculationPresetOut(BaseModel):
    """Synthetic example preset for one Step 13 calculation type (0 client data)."""

    calculation_type: CalculationType
    discipline: CalculationDiscipline
    title_en: str
    title_ar: str
    inputs: dict[str, Any]
    default_reference: CalculationReferenceIn


class CalculationPresetListResponse(BaseModel):
    """List of available synthetic presets for electrical and plumbing calculations."""

    presets: list[CalculationPresetOut] = Field(default_factory=list)
