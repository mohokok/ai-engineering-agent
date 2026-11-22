"""Database ORM models defining the core schema for the engineering agent."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, classification_check_constraint, new_uuid, utc_now


class Project(Base):
    """Engineering project record tied to an isolated workspace directory."""

    __tablename__ = "projects"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    discipline_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    workspace_slug: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    files: Mapped[list["ProjectFile"]] = relationship(
        back_populates="project", cascade="save-update, merge", passive_deletes="all"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    deliverables: Mapped[list["Deliverable"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    research_sources: Mapped[list["ResearchSource"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    research_runs: Mapped[list["ResearchRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    review_reports: Mapped[list["ReviewReport"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    boq_sheets: Mapped[list["BoqSheet"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    parametric_drawings: Mapped[list["ParametricDrawing"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    issues: Mapped[list["Issue"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    qa_reviews: Mapped[list["QaReview"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    calculations: Mapped[list["Calculation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    specifications: Mapped[list["Specification"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    technical_comparisons: Mapped[list["TechnicalComparison"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    project_schedules: Mapped[list["ProjectSchedule"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    standards: Mapped[list["StandardDocument"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    specialist_assessments: Mapped[list["SpecialistAssessment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    structural_assessments: Mapped[list["StructuralAssessment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="project")


class ProjectFile(Base):
    """Registered input, original, or generated file within a project workspace."""

    __tablename__ = "files"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    folder_name: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    is_original: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="registered", nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="files")
    versions: Mapped[list["FileVersion"]] = relationship(
        back_populates="file", cascade="save-update, merge", passive_deletes="all"
    )
    extractions: Mapped[list["FileExtraction"]] = relationship(
        back_populates="file", cascade="save-update, merge", passive_deletes="all"
    )


class FileVersion(Base):
    """Immutable version snapshot for tracked project files."""

    __tablename__ = "file_versions"
    __table_args__ = (UniqueConstraint("file_id", "version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    file: Mapped["ProjectFile"] = relationship(back_populates="versions")


class Task(Base):
    """Autonomous engineering assignment belonging to a project."""

    __tablename__ = "tasks"
    __table_args__ = (
        classification_check_constraint(),
        CheckConstraint(
            "verification_status IN ('unverified', 'qa_passed', 'qa_failed', 'verified')",
            name="ck_tasks_verification_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified", nullable=False)
    last_qa_review_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    complexity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attached_file_ids_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    structured_output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    plan_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="tasks")
    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskStep(Base):
    """Granular orchestrator or skill module step inside an engineering task."""

    __tablename__ = "task_steps"
    __table_args__ = (UniqueConstraint("task_id", "step_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    module_name: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    task: Mapped["Task"] = relationship(back_populates="steps")


class Deliverable(Base):
    """Generated consultancy deliverable with mandatory review classification and file provenance."""

    __tablename__ = "deliverables"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("review_reports.id", ondelete="SET NULL"), index=True, nullable=True
    )
    boq_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("boq_sheets.id", ondelete="SET NULL"), index=True, nullable=True
    )
    drawing_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("parametric_drawings.id", ondelete="SET NULL"), index=True, nullable=True
    )
    calculation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("calculations.id", ondelete="SET NULL"), index=True, nullable=True
    )
    specification_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("specifications.id", ondelete="SET NULL"), index=True, nullable=True
    )
    comparison_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("technical_comparisons.id", ondelete="SET NULL"), index=True, nullable=True
    )
    schedule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_schedules.id", ondelete="SET NULL"), index=True, nullable=True
    )
    assessment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("specialist_assessments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    structural_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("structural_assessments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    deliverable_type: Mapped[str] = mapped_column(String(64), nullable=False)
    discipline: Mapped[str] = mapped_column(
        String(64), default="multidisciplinary", nullable=False
    )
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    folder_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="deliverables")
    review_report: Mapped["ReviewReport | None"] = relationship(back_populates="deliverables")
    boq_sheet: Mapped["BoqSheet | None"] = relationship(back_populates="deliverables")
    parametric_drawing: Mapped["ParametricDrawing | None"] = relationship(back_populates="deliverables")
    calculation: Mapped["Calculation | None"] = relationship(back_populates="deliverables")
    specification: Mapped["Specification | None"] = relationship(back_populates="deliverables")
    technical_comparison: Mapped["TechnicalComparison | None"] = relationship(back_populates="deliverables")
    project_schedule: Mapped["ProjectSchedule | None"] = relationship(back_populates="deliverables")
    specialist_assessment: Mapped["SpecialistAssessment | None"] = relationship(
        back_populates="deliverables"
    )
    structural_assessment: Mapped["StructuralAssessment | None"] = relationship(
        back_populates="deliverables"
    )


class ParametricDrawing(Base):
    """Step 11 deterministic parametric floor plan drawing persisted with DXF/PDF deliverables and round-trip audit."""

    __tablename__ = "parametric_drawings"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    drawing_no: Mapped[str] = mapped_column(String(64), default="A-101", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scale_denominator: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    paper_size: Mapped[str] = mapped_column(String(16), default="A3", nullable=False)
    units: Mapped[str] = mapped_column(String(16), default="mm", nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="generated", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    computed_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    round_trip_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="parametric_drawings")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="parametric_drawing")


class BoqSheet(Base):
    """Structured Step 10 Bill of Quantities sheet with configurable currency and versioned exports."""

    __tablename__ = "boq_sheets"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="LYD", nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    export_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_scope: Mapped[str] = mapped_column(String(32), default="mixed", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="boq_sheets")
    items: Mapped[list["BoqItem"]] = relationship(
        back_populates="boq_sheet",
        cascade="all, delete-orphan",
        order_by="BoqItem.row_order",
    )
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="boq_sheet")


class BoqItem(Base):
    """Individual Step 10 Bill of Quantities line item with quantity verification tag and sourced rate metadata."""

    __tablename__ = "boq_items"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('Extracted-Verified', 'Extracted-Needs-Check', 'Manual')",
            name="ck_boq_items_verification_status_valid",
        ),
        CheckConstraint(
            "rate_source_kind IS NULL OR rate_source_kind IN ('owner_input', 'dated_research')",
            name="ck_boq_items_rate_source_kind_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    boq_sheet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("boq_sheets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    row_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    item_no: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    drawing_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), default="Extracted-Needs-Check", nullable=False
    )
    rate_source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rate_source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_source_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    source_extraction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("file_extractions.id", ondelete="SET NULL"), nullable=True
    )
    discipline: Mapped[str | None] = mapped_column(String(64), nullable=True)
    layer_or_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    boq_sheet: Mapped["BoqSheet"] = relationship(back_populates="items")


class ReviewReport(Base):
    """Structured Step 09 review findings report persisted with revision and provenance metadata."""

    __tablename__ = "review_reports"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    discipline: Mapped[str] = mapped_column(
        String(64), default="multidisciplinary", nullable=False
    )
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="generated", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    estimated_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="review_reports")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="review_report")


class ResearchRun(Base):
    """Persisted controlled internet research run tied optionally to a project or task."""

    __tablename__ = "research_runs"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    search_provider: Mapped[str] = mapped_column(
        String(64), default="duckduckgo_lite", nullable=False
    )
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    artifact_relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )

    project: Mapped["Project | None"] = relationship(back_populates="research_runs")
    sources: Mapped[list["ResearchSource"]] = relationship(
        back_populates="research_run", cascade="all, delete-orphan"
    )


class ResearchSource(Base):
    """Recorded technical research citation with provenance and reliability metadata."""

    __tablename__ = "research_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    research_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_runs.id", ondelete="CASCADE"), index=True, nullable=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source_name: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    publication_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevant_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    reliability_assessment: Mapped[str] = mapped_column(
        String(64), default="unverified", nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(64), default="web", nullable=False)
    source_priority_tier: Mapped[str] = mapped_column(
        String(64), default="reputable", nullable=False
    )
    priority_rank: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    access_status: Mapped[str] = mapped_column(String(32), default="accessible", nullable=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    untrusted_neutralized: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    project: Mapped["Project | None"] = relationship(back_populates="research_sources")
    research_run: Mapped["ResearchRun | None"] = relationship(back_populates="sources")


class QaReview(Base):
    """Independent Step 12 QA agent execution summary (isolated from producer reasoning)."""

    __tablename__ = "qa_reviews"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="issues_found", nullable=False)
    producer_reasoning_excluded: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    checks_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    qa_context_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    issues_opened_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_issues_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="qa_reviews")
    issues: Mapped[list["Issue"]] = relationship(back_populates="qa_review")


class Issue(Base):
    """Quality assurance issue register item associated with a project review."""

    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("project_id", "issue_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    deliverable_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("deliverables.id", ondelete="SET NULL"), nullable=True
    )
    qa_review_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("qa_reviews.id", ondelete="SET NULL"), index=True, nullable=True
    )
    issue_number: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    discipline: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    check_category: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    closure_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="issues")
    qa_review: Mapped["QaReview | None"] = relationship(back_populates="issues")


class Calculation(Base):
    """Deterministic engineering calculation record showing inputs, equations, and results."""

    __tablename__ = "calculations"
    __table_args__ = (classification_check_constraint(),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    discipline: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    units_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    equations: Mapped[str | None] = mapped_column(Text, nullable=True)
    methodology: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    results_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    export_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    acceptance_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="calculations")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="calculation")


class Specification(Base):
    """Step 14 technical specification package traced deterministically to project BOQs, drawings, and verified sources."""

    __tablename__ = "specifications"
    __table_args__ = (
        classification_check_constraint(),
        CheckConstraint(
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_specifications_ai_draft_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    discipline: Mapped[str] = mapped_column(String(64), default="multidisciplinary", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="Preliminary", nullable=False)
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    export_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="generated", nullable=False)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_draft_status: Mapped[str] = mapped_column(String(32), default="not_used", nullable=False)
    owner_approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    structured_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="specifications")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="specification")


class TechnicalComparison(Base):
    """Step 15 multi-criteria equipment/material/offer comparison with Decimal scoring, source provenance, and advisory decision gate."""

    __tablename__ = "technical_comparisons"
    __table_args__ = (
        classification_check_constraint(),
        CheckConstraint(
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_comparisons_ai_draft_status_valid",
        ),
        CheckConstraint(
            "owner_decision_status IN ('pending_owner_decision', 'owner_selected')",
            name="ck_comparisons_owner_decision_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    comparison_scope: Mapped[str] = mapped_column(String(64), default="equipment", nullable=False)
    discipline: Mapped[str] = mapped_column(String(64), default="multidisciplinary", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="Preliminary", nullable=False)
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    export_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="evaluated", nullable=False)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_draft_status: Mapped[str] = mapped_column(String(32), default="not_used", nullable=False)
    owner_decision_status: Mapped[str] = mapped_column(
        String(32), default="pending_owner_decision", nullable=False
    )
    owner_selected_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    criteria_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    options_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    matrix_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="technical_comparisons")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="technical_comparison")


class ProjectSchedule(Base):
    """Step 16 WBS, deterministic CPM schedule, calendar (incl. Libya weekend), baseline variance & Gantt exports."""

    __tablename__ = "project_schedules"
    __table_args__ = (
        classification_check_constraint(),
        CheckConstraint(
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_schedules_ai_draft_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    baseline_schedule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_schedules.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    discipline: Mapped[str] = mapped_column(String(64), default="multidisciplinary", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="Preliminary", nullable=False)
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    export_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="scheduled", nullable=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    start_date: Mapped[str] = mapped_column(String(16), nullable=False)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_draft_status: Mapped[str] = mapped_column(String(32), default="not_used", nullable=False)
    owner_approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    calendar_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    wbs_items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    activities_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    schedule_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="project_schedules")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="project_schedule")


class StandardDocument(Base):
    """Step 17 owner-supplied / licensed standards library (zero shipped standard texts or invented clauses)."""

    __tablename__ = "standards_library"
    __table_args__ = (
        CheckConstraint(
            "status IN ('current', 'superseded', 'withdrawn', 'unknown')",
            name="ck_standards_status_valid",
        ),
        CheckConstraint(
            "metadata_status IN ('owner_entered', 'unverified_suggestion', 'unverified_ai_suggestion', 'owner_confirmed')",
            name="ck_standards_metadata_status_valid",
        ),
        CheckConstraint(
            "ai_suggestion_status IN ('not_used', 'unverified_ai_suggestion', 'owner_confirmed')",
            name="ck_standards_ai_suggestion_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    standard_number: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    issuing_body: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    edition_year: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("standards_library.id", ondelete="SET NULL"), index=True, nullable=True
    )
    supersession_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    adopted_locally: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_excerpts_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    metadata_status: Mapped[str] = mapped_column(String(32), default="owner_entered", nullable=False)
    suggested_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_suggestion_status: Mapped[str] = mapped_column(String(32), default="not_used", nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    history_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project | None"] = relationship(back_populates="standards")
    superseded_by: Mapped["StandardDocument | None"] = relationship(
        remote_side=[id], foreign_keys=[superseded_by_id]
    )


class SpecialistAssessment(Base):
    """Step 18 deterministic HVAC, Fire & Healthcare preflight assessment (input preparation + output checking only)."""

    __tablename__ = "specialist_assessments"
    __table_args__ = (
        classification_check_constraint(),
        CheckConstraint(
            "domain IN ('hvac', 'fire', 'healthcare')",
            name="ck_specialist_domain_valid",
        ),
        CheckConstraint(
            "workflow_mode IN ('input_preparation', 'output_check', 'full_preflight')",
            name="ck_specialist_mode_valid",
        ),
        CheckConstraint(
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_specialist_ai_draft_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    domain: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    workflow_mode: Mapped[str] = mapped_column(String(32), default="full_preflight", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="Preliminary", nullable=False)
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    export_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="evaluated", nullable=False)
    checks_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocked_missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_checks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    standards_status: Mapped[str] = mapped_column(
        String(64), default="no_verified_standard_on_file", nullable=False
    )
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_draft_status: Mapped[str] = mapped_column(String(32), default="not_used", nullable=False)
    owner_approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    results_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    references_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    preliminary_assumptions_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    software_recommendation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="specialist_assessments")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="specialist_assessment")


class StructuralAssessment(Base):
    """Step 19 deterministic structural assessment support & I/O check ONLY (never designs members or certifies safety)."""

    __tablename__ = "structural_assessments"
    __table_args__ = (
        classification_check_constraint(),
        CheckConstraint(
            "assessment_type IN ('takedown_check', 'load_combinations', 'simple_statics_beam', 'full_structural_check')",
            name="ck_structural_type_valid",
        ),
        CheckConstraint(
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_structural_ai_draft_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    assessment_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="ar", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="Preliminary", nullable=False)
    revision: Mapped[str] = mapped_column(String(32), default="Rev 01", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    export_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="evaluated", nullable=False)
    checks_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocked_missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_checks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    standards_status: Mapped[str] = mapped_column(
        String(64), default="no_verified_standard_on_file", nullable=False
    )
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_draft_status: Mapped[str] = mapped_column(String(32), default="not_used", nullable=False)
    owner_approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    results_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    references_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    preliminary_assumptions_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    software_recommendation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="structural_assessments")
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="structural_assessment")


class FileExtraction(Base):
    """Persisted deterministic document/spreadsheet/image extraction snapshot."""

    __tablename__ = "file_extractions"
    __table_args__ = (
        classification_check_constraint(),
        UniqueConstraint(
            "file_id",
            "version_number",
            "extraction_version",
            name="uq_file_extractions_file_ver_run",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="extracted", nullable=False)
    ocr_status: Mapped[str] = mapped_column(String(64), default="not_needed", nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), default="Preliminary", nullable=False
    )
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    rendered_images_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    artifact_relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    file: Mapped["ProjectFile"] = relationship(back_populates="extractions")


class Setting(Base):
    """Non-secret persisted application configuration entry."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AuditLog(Base):
    """Append-only audit trail for project, file, and system operations."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), default="owner", nullable=False)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )

    project: Mapped["Project | None"] = relationship(back_populates="audit_logs")
