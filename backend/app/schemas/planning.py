"""Pydantic schemas and provenance constants for Step 16 project planning (WBS, CPM, Gantt, Baseline, Exports)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut, ReportLanguage
from app.schemas.tasks import TaskTokenUsageOut

NOT_PROVIDED_LABEL = "not provided"
AI_UNVERIFIED_DRAFT_LABEL_EN = "UNVERIFIED AI DRAFT"
AI_UNVERIFIED_DRAFT_LABEL_AR = "مسودة ذكاء اصطناعي غير مُتحقَّق منها (UNVERIFIED AI DRAFT)"

ScheduleSourceKind = Literal[
    "boq_item",
    "specification",
    "calculation",
    "research_source",
    "owner_entered",
]
CalendarPresetKey = Literal["libya_sun_thu", "mon_fri", "six_day_sat_thu", "custom"]
ScheduleDraftStatus = Literal["not_used", "unverified_ai_draft", "owner_approved"]
DependencyType = Literal["FS"]
CpmStatus = Literal["computed", "blocked_missing_duration"]


class WorkCalendarIn(BaseModel):
    """Owner-defined working calendar (supports Libya Fri-Sat weekend default without inventing holiday dates)."""

    preset: CalendarPresetKey = "libya_sun_thu"
    weekend_days: list[int] | None = Field(
        default=None,
        description="Python weekday indices 0=Mon..6=Sun. Auto-filled for preset unless 'custom'. Libya Fri+Sat=[4,5].",
    )
    holidays: list[str] = Field(
        default_factory=list,
        max_length=365,
        description="Owner-supplied non-working holiday ISO dates YYYY-MM-DD (never invented).",
    )
    hours_per_day: float = Field(default=8.0, gt=0.0, le=24.0)
    source_ref: str = Field(
        default="Owner-defined working calendar (Libya Fri-Sat weekend preset)",
        min_length=2,
        max_length=500,
    )


class WbsItemIn(BaseModel):
    """Hierarchical Work Breakdown Structure element."""

    wbs_code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=2, max_length=255)
    parent_code: str | None = Field(default=None, max_length=64)
    discipline: str = Field(default="multidisciplinary", min_length=1, max_length=64)

    @field_validator("wbs_code", "title", "discipline", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("WBS item fields must not be blank.")
        return cleaned


class ActivityDependencyIn(BaseModel):
    """Predecessor finish-to-start (FS) dependency with optional working-day lag."""

    predecessor_id: str = Field(..., min_length=1, max_length=64)
    dep_type: DependencyType = "FS"
    lag_days: int = Field(default=0, ge=-365, le=365)


class ScheduleActivityIn(BaseModel):
    """Single WBS activity or milestone strictly grounded in project sources or explicit owner inputs."""

    activity_id: str = Field(..., min_length=1, max_length=64)
    wbs_code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=2, max_length=255)
    is_milestone: bool = False
    duration_days: int | None = Field(
        default=None,
        ge=0,
        le=3650,
        description="Working days. Omit or pass None when not supplied by owner -> renders 'not provided' & blocks CPM branch.",
    )
    quantity: float | None = Field(default=None, ge=0.0)
    unit: str | None = Field(default=None, max_length=64)
    predecessors: list[ActivityDependencyIn] = Field(default_factory=list, max_length=50)
    source_kind: ScheduleSourceKind = "owner_entered"
    source_ref: str = Field(..., min_length=2, max_length=1000)
    boq_item_id: str | None = Field(default=None, max_length=64)
    specification_id: str | None = Field(default=None, max_length=64)
    calculation_id: str | None = Field(default=None, max_length=64)
    research_source_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("activity_id", "wbs_code", "name", "source_ref", mode="before")
    @classmethod
    def strip_act_text(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Activity text fields must not be blank.")
        return cleaned


class ScheduleCreateRequest(BaseModel):
    """Create and deterministically evaluate a WBS & CPM project schedule (0 AI tokens by default)."""

    task_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    discipline: str = Field(default="multidisciplinary", min_length=1, max_length=64)
    language: ReportLanguage = "ar"
    classification: ProjectClassification = "Preliminary"
    revision: str = Field(default="Rev 01", min_length=1, max_length=32)
    start_date: str = Field(..., min_length=10, max_length=16, description="Project start ISO date YYYY-MM-DD.")
    calendar: WorkCalendarIn = Field(default_factory=WorkCalendarIn)
    wbs_items: list[WbsItemIn] = Field(..., min_length=1, max_length=100)
    activities: list[ScheduleActivityIn] = Field(..., min_length=1, max_length=300)
    baseline_schedule_id: str | None = Field(default=None, max_length=64)
    set_as_baseline: bool = False
    use_ai: bool = False
    complexity: TaskComplexity = "fast"

    @field_validator("task_id", "title", "baseline_schedule_id", mode="before")
    @classmethod
    def strip_optional_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ScheduleApproveRequest(BaseModel):
    """Owner sign-off clearing UNVERIFIED AI DRAFT narrative tag and optionally re-exporting."""

    approved_by: str = Field(default="Owner", min_length=2, max_length=128)
    approval_note: str | None = Field(default=None, max_length=2000)
    export_after_approval: bool = True


class ScheduleExportRequest(BaseModel):
    """Export immutable SHA-256 versioned Gantt PDF & live-formula XLSX deliverables into 03_Analysis."""

    language: ReportLanguage | None = None


class EvaluatedActivityOut(BaseModel):
    """Deterministically evaluated CPM activity/milestone with dates, float, blocked state, baseline delta, and source."""

    activity_id: str
    wbs_code: str
    name: str
    is_milestone: bool
    duration_days: int | None = None
    display_duration: str
    quantity: float | None = None
    unit: str = ""
    predecessors: list[ActivityDependencyIn] = Field(default_factory=list)
    early_start_wd: int | None = None
    early_finish_wd: int | None = None
    late_start_wd: int | None = None
    late_finish_wd: int | None = None
    total_float_wd: int | None = None
    planned_start: str | None = None
    planned_finish: str | None = None
    late_start_date: str | None = None
    late_finish_date: str | None = None
    is_critical: bool = False
    cpm_status: CpmStatus | str = "computed"
    branch_block_reason: str | None = None
    baseline_duration_days: int | None = None
    baseline_start: str | None = None
    baseline_finish: str | None = None
    start_variance_wd: int | None = None
    finish_variance_wd: int | None = None
    float_variance_wd: int | None = None
    variance_status: str = "no_baseline"
    source_kind: ScheduleSourceKind | str
    source_ref: str
    boq_item_id: str | None = None
    specification_id: str | None = None
    calculation_id: str | None = None
    research_source_id: str | None = None
    notes: str | None = None


class ScheduleResultOut(BaseModel):
    """Complete deterministic CPM, working-calendar dates, blocked branches, and baseline variance package."""

    project_start_date: str
    effective_start_date: str
    project_finish_date: str | None = None
    total_duration_wd: int | None = None
    calendar_preset: CalendarPresetKey | str
    calendar_summary: str
    weekend_days: list[int] = Field(default_factory=list)
    holidays: list[str] = Field(default_factory=list)
    critical_path_complete: bool
    critical_path_ids: list[str] = Field(default_factory=list)
    blocked_activity_ids: list[str] = Field(default_factory=list)
    blocked_branch_flags: list[str] = Field(default_factory=list)
    missing_duration_flags: list[str] = Field(default_factory=list)
    milestone_summary: list[dict[str, Any]] = Field(default_factory=list)
    baseline_schedule_id: str | None = None
    baseline_title: str | None = None
    project_finish_variance_wd: int | None = None
    baseline_comparison_notes: list[str] = Field(default_factory=list)
    activities: list[EvaluatedActivityOut] = Field(default_factory=list)


class ProjectScheduleSummaryOut(BaseModel):
    """Persisted project planning schedule summary."""

    id: str
    project_id: str
    project_code: str = ""
    project_name: str = ""
    task_id: str | None = None
    baseline_schedule_id: str | None = None
    title: str
    discipline: str
    language: ReportLanguage | str
    classification: ProjectClassification | str
    revision: str
    version: int
    export_version: int
    status: str
    is_baseline: bool = False
    start_date: str
    use_ai: bool
    ai_draft_status: ScheduleDraftStatus | str
    ai_draft_label: str = ""
    owner_approved_by: str | None = None
    owner_approved_at: datetime | None = None
    wbs_count: int = 0
    activities_count: int = 0
    total_duration_wd: int | None = None
    critical_path_complete: bool = True
    tokens_used: int = 0
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectScheduleDetailOut(ProjectScheduleSummaryOut):
    """Complete Step 16 WBS, CPM dates, critical path, baseline comparison, and SHA-256 deliverables."""

    calendar: WorkCalendarIn
    wbs_items: list[WbsItemIn] = Field(default_factory=list)
    schedule_result: ScheduleResultOut
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    deliverables: list[DeliverableOut] = Field(default_factory=list)


class ProjectScheduleListResponse(BaseModel):
    """List of persisted project planning schedules."""

    schedules: list[ProjectScheduleSummaryOut] = Field(default_factory=list)
    total: int


class ProjectScheduleExportOut(BaseModel):
    """Immutable SHA-256 versioned Gantt PDF & XLSX schedule export package in 03_Analysis."""

    schedule: ProjectScheduleDetailOut
    pdf_deliverable: DeliverableOut
    xlsx_deliverable: DeliverableOut


class PlanningPresetOut(BaseModel):
    """Synthetic clinic construction planning preset (0% client data, owner-supplied durations & Libya calendar)."""

    key: str
    title_en: str
    title_ar: str
    discipline: str
    start_date: str
    calendar: WorkCalendarIn
    wbs_items: list[WbsItemIn] = Field(default_factory=list)
    activities: list[ScheduleActivityIn] = Field(default_factory=list)


class PlanningPresetListResponse(BaseModel):
    """Collection of synthetic Step 16 planning presets."""

    presets: list[PlanningPresetOut] = Field(default_factory=list)
