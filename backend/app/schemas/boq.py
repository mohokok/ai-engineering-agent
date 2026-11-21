"""Pydantic schemas for Step 10 Bill of Quantities (BOQ) and deterministic quantity takeoffs."""

from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut, ReportLanguage

BoqVerificationStatus = Literal[
    "Extracted-Verified",
    "Extracted-Needs-Check",
    "Manual",
]
BoqRateSourceKind = Literal["owner_input", "dated_research"]
BoqCheckType = Literal[
    "duplicate_item",
    "missing_item",
    "unit_consistency",
    "arithmetic_total",
    "unverified_unit",
    "rate_provenance",
]
BoqCheckSeverity = Literal["high", "medium", "info"]

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _clean_opt_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _validate_rate_source(
    *,
    unit_rate: float | None,
    rate_source_kind: BoqRateSourceKind | None,
    rate_source_ref: str | None,
    rate_source_date: str | None,
) -> None:
    if unit_rate is None:
        return
    if rate_source_kind not in ("owner_input", "dated_research"):
        raise ValueError(
            "Unsourced unit rate blocked: set rate_source_kind to 'owner_input' or 'dated_research' with attribution."
        )
    if rate_source_kind == "owner_input":
        if not (rate_source_ref and rate_source_ref.strip()):
            raise ValueError(
                "Unsourced owner unit rate blocked: supply rate_source_ref (owner quote, baseline sheet, or owner note)."
            )
    elif rate_source_kind == "dated_research":
        if not (rate_source_ref and rate_source_ref.strip()) or not (rate_source_date and rate_source_date.strip()):
            raise ValueError(
                "Unsourced or undated research rate blocked: 'dated_research' requires BOTH rate_source_ref and rate_source_date."
            )


class BoqCheckIssue(BaseModel):
    """Single deterministic BOQ validation issue detected across quantities, units, duplicates, or arithmetic."""

    issue_id: str
    check_type: BoqCheckType
    severity: BoqCheckSeverity
    item_id: str | None = None
    item_no: str | None = None
    message: str
    recommended_action: str


class BoqChecksSummaryOut(BaseModel):
    """Deterministic BOQ audit summary highlighting discrepancies and items flagged for human verification."""

    total_items: int = 0
    verified_items_count: int = 0
    needs_check_items_count: int = 0
    manual_items_count: int = 0
    priced_items_count: int = 0
    unpriced_items_count: int = 0
    verified_priced_subtotal: float = 0.0
    needs_check_priced_subtotal: float = 0.0
    grand_total: float = 0.0
    issues_count: int = 0
    high_issues_count: int = 0
    issues: list[BoqCheckIssue] = Field(default_factory=list)
    flagged_item_ids: list[str] = Field(default_factory=list)
    flagged_items: list[dict[str, Any]] = Field(default_factory=list)


class BoqItemCreateRequest(BaseModel):
    """Add a manual or sourced BOQ line item (unsourced unit rates strictly blocked)."""

    item_no: str = Field(default="", max_length=64)
    description: str = Field(..., min_length=1, max_length=2000)
    unit: str = Field(default="", max_length=64)
    quantity: float = Field(default=0.0, ge=0.0)
    unit_rate: float | None = Field(default=None, ge=0.0)
    reported_total: float | None = Field(default=None, ge=0.0)
    technical_reference: str | None = Field(default=None, max_length=1000)
    drawing_reference: str | None = Field(default=None, max_length=1000)
    remarks: str | None = Field(default=None, max_length=2000)
    verification_status: BoqVerificationStatus = "Manual"
    rate_source_kind: BoqRateSourceKind | None = None
    rate_source_ref: str | None = Field(default=None, max_length=1000)
    rate_source_date: str | None = Field(default=None, max_length=64)
    discipline: str | None = Field(default=None, max_length=64)
    layer_or_category: str | None = Field(default=None, max_length=128)

    @field_validator(
        "item_no",
        "description",
        "unit",
        "technical_reference",
        "drawing_reference",
        "remarks",
        "rate_source_ref",
        "rate_source_date",
        "discipline",
        "layer_or_category",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        return _clean_opt_text(value) if value is not None else None

    @field_validator("item_no", "unit", mode="before")
    @classmethod
    def default_blank_str(cls, value: str | None) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def enforce_sourced_rate(self) -> "BoqItemCreateRequest":
        _validate_rate_source(
            unit_rate=self.unit_rate,
            rate_source_kind=self.rate_source_kind,
            rate_source_ref=self.rate_source_ref,
            rate_source_date=self.rate_source_date,
        )
        return self


class BoqItemUpdateRequest(BaseModel):
    """Update an existing BOQ row cleanly (strict rate provenance enforced when assigning unit_rate)."""

    item_no: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=64)
    quantity: float | None = Field(default=None, ge=0.0)
    unit_rate: float | None = Field(default=None, ge=0.0)
    clear_rate: bool = False
    reported_total: float | None = Field(default=None, ge=0.0)
    technical_reference: str | None = Field(default=None, max_length=1000)
    drawing_reference: str | None = Field(default=None, max_length=1000)
    remarks: str | None = Field(default=None, max_length=2000)
    verification_status: BoqVerificationStatus | None = None
    rate_source_kind: BoqRateSourceKind | None = None
    rate_source_ref: str | None = Field(default=None, max_length=1000)
    rate_source_date: str | None = Field(default=None, max_length=64)
    discipline: str | None = Field(default=None, max_length=64)
    layer_or_category: str | None = Field(default=None, max_length=128)

    @field_validator(
        "item_no",
        "description",
        "unit",
        "technical_reference",
        "drawing_reference",
        "remarks",
        "rate_source_ref",
        "rate_source_date",
        "discipline",
        "layer_or_category",
        mode="before",
    )
    @classmethod
    def clean_opts(cls, value: str | None) -> str | None:
        return _clean_opt_text(value)

    @model_validator(mode="after")
    def enforce_rate_when_given(self) -> "BoqItemUpdateRequest":
        if self.unit_rate is not None and not self.clear_rate:
            _validate_rate_source(
                unit_rate=self.unit_rate,
                rate_source_kind=self.rate_source_kind,
                rate_source_ref=self.rate_source_ref,
                rate_source_date=self.rate_source_date,
            )
        return self


class BoqItemOut(BaseModel):
    """Serialized BOQ line item including provenance and check status."""

    id: str
    boq_sheet_id: str
    row_order: int
    item_no: str
    description: str
    unit: str
    quantity: float
    unit_rate: float | None = None
    total: float | None = None
    reported_total: float | None = None
    technical_reference: str | None = None
    drawing_reference: str | None = None
    remarks: str | None = None
    verification_status: BoqVerificationStatus
    rate_source_kind: BoqRateSourceKind | None = None
    rate_source_ref: str | None = None
    rate_source_date: str | None = None
    source_file_id: str | None = None
    source_extraction_id: str | None = None
    discipline: str | None = None
    layer_or_category: str | None = None
    created_at: datetime
    updated_at: datetime


class BoqSheetCreateRequest(BaseModel):
    """Create a BOQ sheet and optionally populate quantities deterministically from DXF/IFC/XLSX/PDF extractions."""

    title: str | None = Field(default=None, max_length=255)
    language: ReportLanguage = "ar"
    currency: str = Field(default="LYD", min_length=3, max_length=8)
    classification: ProjectClassification = "Preliminary"
    file_ids: list[str] = Field(default_factory=list, max_length=50)
    include_dxf_ifc: bool = True
    include_boq_imports: bool = True
    task_id: str | None = Field(default=None, max_length=64)

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: str | None) -> str:
        code = (value or "LYD").strip().upper()
        if not _CURRENCY_RE.match(code):
            raise ValueError("Currency must be a 3-letter ISO currency code (e.g. LYD, USD, EUR).")
        return code

    @field_validator("title", "task_id", mode="before")
    @classmethod
    def trim_opt(cls, value: str | None) -> str | None:
        return _clean_opt_text(value)


class BoqImportExtractionsRequest(BaseModel):
    """Import/merge deterministic quantities from DXF/IFC and/or existing BOQ rows from XLSX/PDF into a BOQ sheet."""

    file_ids: list[str] = Field(default_factory=list, max_length=50)
    include_dxf_ifc: bool = True
    include_boq_imports: bool = True
    replace_extracted: bool = False


class BoqSheetUpdateRequest(BaseModel):
    """Update BOQ metadata such as configurable currency, title, classification, or language."""

    title: str | None = Field(default=None, max_length=255)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    classification: ProjectClassification | None = None
    language: ReportLanguage | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().upper()
        if not _CURRENCY_RE.match(code):
            raise ValueError("Currency must be a 3-letter ISO currency code (e.g. LYD, USD, EUR).")
        return code

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: str | None) -> str | None:
        return _clean_opt_text(value)


class BoqExportRequest(BaseModel):
    """Options for generating versioned XLSX (live Excel formulas) + CSV files inside 06_BOQ."""

    language: ReportLanguage | None = None
    include_checks_sheet: bool = True


class BoqSheetSummaryOut(BaseModel):
    """Summary metadata for a project BOQ sheet."""

    id: str
    project_id: str
    project_code: str
    project_name: str
    task_id: str | None = None
    title: str
    language: ReportLanguage | str
    currency: str
    classification: ProjectClassification | str
    revision: str
    version: int
    export_version: int
    source_scope: str
    status: str
    summary: str | None = None
    items_count: int = 0
    grand_total: float = 0.0
    issues_count: int = 0
    high_issues_count: int = 0
    created_at: datetime
    updated_at: datetime


class BoqDetailOut(BoqSheetSummaryOut):
    """Full BOQ sheet payload with line items, deterministic checks, flagged items, and exports."""

    checks: BoqChecksSummaryOut
    items: list[BoqItemOut] = Field(default_factory=list)
    deliverables: list[DeliverableOut] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class BoqListResponse(BaseModel):
    """List of BOQ sheets scoped to a project."""

    sheets: list[BoqSheetSummaryOut] = Field(default_factory=list)
    total: int
    classification: ProjectClassification = "Preliminary"


class BoqExportOut(BaseModel):
    """Outcome of exporting a BOQ sheet to versioned XLSX (with live formulas) and CSV deliverables."""

    boq: BoqDetailOut
    xlsx_deliverable: DeliverableOut
    csv_deliverable: DeliverableOut
