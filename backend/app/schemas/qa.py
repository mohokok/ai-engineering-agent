"""Pydantic schemas for Step 12 independent QA reviews, issue register CRUD, and task verification gating."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.projects import ProjectClassification

IssueSeverity = Literal["critical", "high", "medium", "low", "info"]
IssueStatus = Literal["open", "in_review", "closed"]
IssueCategory = Literal[
    "arithmetic",
    "unit",
    "reference",
    "schedule_consistency",
    "missing_deliverable",
    "integrity",
    "manual",
    "general",
]


class QaCheckMetricOut(BaseModel):
    """Per-category deterministic QA verification count and status."""

    category: IssueCategory
    checked_count: int = 0
    failed_count: int = 0
    passed: bool = True
    details: str = ""


class QaReviewRunRequest(BaseModel):
    """Request to run an independent Step 12 QA inspection on project/task deliverables (0 AI tokens)."""

    task_id: str | None = Field(default=None, max_length=64)
    classification: ProjectClassification | None = None
    check_arithmetic: bool = True
    check_units: bool = True
    check_references: bool = True
    check_consistency: bool = True
    check_missing_deliverables: bool = True


class IssueCreateRequest(BaseModel):
    """Manual engineering QA issue creation payload."""

    task_id: str | None = Field(default=None, max_length=64)
    deliverable_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    description: str = Field(..., min_length=3, max_length=3000)
    discipline: str = Field(default="multidisciplinary", min_length=1, max_length=64)
    severity: IssueSeverity = "medium"
    check_category: IssueCategory = "manual"
    reference: str | None = Field(default=None, max_length=512)
    corrective_action: str = Field(..., min_length=3, max_length=2000)


class IssueUpdateRequest(BaseModel):
    """Close, reopen, or amend an engineering QA issue with an optional closure note."""

    status: IssueStatus | None = None
    severity: IssueSeverity | None = None
    corrective_action: str | None = Field(default=None, max_length=2000)
    closure_note: str | None = Field(default=None, max_length=2000)


class IssueOut(BaseModel):
    """Serialized issue register item displaying number, description, discipline, severity, reference, corrective action, and status."""

    id: str
    project_id: str
    task_id: str | None = None
    deliverable_id: str | None = None
    qa_review_id: str | None = None
    issue_number: str
    title: str | None = None
    description: str
    discipline: str
    severity: IssueSeverity | str
    check_category: IssueCategory | str = "general"
    reference: str | None = None
    corrective_action: str | None = None
    recommended_action: str | None = None
    status: IssueStatus | str
    closure_note: str | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IssueListResponse(BaseModel):
    """Filtered project issue register response with counts."""

    issues: list[IssueOut] = Field(default_factory=list)
    total: int
    open_count: int
    closed_count: int


class QaContextIsolationReport(BaseModel):
    """Explicit proof that independent QA inspection omitted producer reasoning fields."""

    producer_reasoning_excluded: bool = True
    excluded_fields: list[str] = Field(
        default_factory=lambda: [
            "Task.plan_summary",
            "Task.result_summary",
            "Task.structured_output_json",
            "TaskStep.notes",
            "TaskStep.output_payload.understanding",
            "ReviewReport.ai_reasoning",
        ]
    )
    inspected_boq_ids: list[str] = Field(default_factory=list)
    inspected_drawing_ids: list[str] = Field(default_factory=list)
    inspected_report_ids: list[str] = Field(default_factory=list)
    inspected_calculation_ids: list[str] = Field(default_factory=list)
    inspected_specification_ids: list[str] = Field(default_factory=list)
    inspected_comparison_ids: list[str] = Field(default_factory=list)
    inspected_schedule_ids: list[str] = Field(default_factory=list)
    inspected_deliverable_ids: list[str] = Field(default_factory=list)
    inspected_extraction_ids: list[str] = Field(default_factory=list)
    inspected_research_source_count: int = 0
    expected_task_deliverables: list[str] = Field(default_factory=list)


class QaReviewDetailOut(BaseModel):
    """Complete independent QA review outcome, isolated context summary, check metrics, and opened issues."""

    id: str
    project_id: str
    project_code: str
    project_name: str
    task_id: str | None = None
    task_verification_status: str | None = None
    classification: ProjectClassification | str
    status: str
    producer_reasoning_excluded: bool = True
    qa_context_summary: QaContextIsolationReport
    checks: list[QaCheckMetricOut] = Field(default_factory=list)
    issues_opened_count: int = 0
    open_issues_count: int = 0
    tokens_used: int = 0
    issues: list[IssueOut] = Field(default_factory=list)
    created_at: datetime


class QaReviewListResponse(BaseModel):
    """List of project QA reviews ordered newest first."""

    reviews: list[QaReviewDetailOut] = Field(default_factory=list)
    total: int


class TaskVerifyRequest(BaseModel):
    """Attempt to mark a task verified (always blocked unless independent QA ran and zero open issues remain)."""

    qa_review_id: str | None = None
    verifier_note: str | None = Field(default=None, max_length=1000)


class TaskVerifyOut(BaseModel):
    """Result of task verification gate check."""

    task_id: str
    verification_status: str
    qa_review_id: str
    open_issues_count: int
    message: str
