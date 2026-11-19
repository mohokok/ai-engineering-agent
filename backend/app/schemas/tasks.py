"""Pydantic schemas for Step 05 assignments, Orchestrator v0 output, and task history."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification

AssignmentLanguage = Literal["ar", "en", "mixed"]
InputFileStatus = Literal["attached", "missing", "referenced_in_prompt"]


class IdentifiedInputFile(BaseModel):
    """Input file recognized or needed for executing the engineering assignment."""

    filename: str = Field(..., min_length=1, max_length=512)
    role: str = Field(..., min_length=1, max_length=500)
    status: InputFileStatus


class OrchestratorUnderstanding(BaseModel):
    """Structured JSON output produced by Orchestrator v0 (assignment intake stage)."""

    language_detected: AssignmentLanguage
    restated_assignment: str = Field(..., min_length=1)
    primary_discipline: str = Field(..., min_length=1)
    secondary_disciplines: list[str] = Field(default_factory=list)
    expected_deliverables: list[str] = Field(default_factory=list)
    input_files: list[IdentifiedInputFile] = Field(default_factory=list)
    applicable_standards_to_verify: list[str] = Field(
        default_factory=list,
        description=(
            "Candidate codes/standards to verify later via Standards Library or Research; "
            "never fabricate verified compliance or clause numbers."
        ),
    )
    missing_information: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarification_needed: bool
    clarifying_questions: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    suggested_classification: ProjectClassification = Field(
        default="Preliminary",
        description=(
            "Advisory classification suggestion only; the owner's chosen task classification always controls."
        ),
    )


class AttachedFileSummary(BaseModel):
    """Sanitized metadata snapshot for an uploaded file attached to an assignment."""

    file_id: str
    filename: str
    folder_name: str
    extension: str | None = None
    mime_type: str | None = None
    size_bytes: int = 0
    sha256: str | None = None
    current_version: int = 1


class TaskCreateRequest(BaseModel):
    """Request payload for creating and running a natural-language assignment task."""

    project_id: str = Field(..., min_length=1, max_length=64)
    prompt: str = Field(..., min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=255)
    complexity: TaskComplexity = "fast"
    task_type: str = Field(default="assignment", min_length=1, max_length=64)
    attached_file_ids: list[str] = Field(default_factory=list, max_length=50)
    classification: ProjectClassification = "Preliminary"

    @field_validator("project_id", "prompt", "task_type")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        """Ensure required text inputs are not blank whitespace."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field must not be blank.")
        return cleaned

    @field_validator("title", mode="before")
    @classmethod
    def clean_optional_title(cls, value: str | None) -> str | None:
        """Normalize optional title strings."""
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("attached_file_ids")
    @classmethod
    def deduplicate_file_ids(cls, value: list[str]) -> list[str]:
        """Deduplicate attached file IDs while preserving input order."""
        seen: set[str] = set()
        result: list[str] = []
        for raw in value:
            cleaned = raw.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result


class TaskTokenUsageOut(BaseModel):
    """Normalized AI token usage recorded for a task execution."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0


class TaskStepOut(BaseModel):
    """Persisted step execution record belonging to a task."""

    id: str
    task_id: str
    step_order: int
    module_name: str
    title: str
    status: str
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None
    notes: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class TaskLogEntryOut(BaseModel):
    """Persisted audit log entry linked to a task lifecycle or usage event."""

    id: str
    action: str
    entity_type: str
    actor: str
    details_json: dict[str, Any] | None = None
    created_at: datetime


class TaskSummaryOut(BaseModel):
    """Task record summary returned in Task History listings and base views."""

    id: str
    project_id: str
    project_code: str
    project_name: str
    title: str
    prompt: str
    task_type: str
    status: str
    classification: ProjectClassification | str
    complexity: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    plan_summary: str | None = None
    result_summary: str | None = None
    error_message: str | None = None
    attached_file_ids: list[str] = Field(default_factory=list)
    structured_output: OrchestratorUnderstanding | None = None
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    step_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TaskDetailOut(TaskSummaryOut):
    """Complete task inspection payload including attached files, steps, and logs."""

    attached_files: list[AttachedFileSummary] = Field(default_factory=list)
    steps: list[TaskStepOut] = Field(default_factory=list)
    logs: list[TaskLogEntryOut] = Field(default_factory=list)


class TaskListResponse(BaseModel):
    """Task History collection response."""

    tasks: list[TaskSummaryOut]
    total: int
    classification: ProjectClassification = "Preliminary"
