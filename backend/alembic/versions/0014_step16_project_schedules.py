"""step16_project_schedules

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-22 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create project_schedules table and link deliverables.schedule_id."""
    op.create_table(
        "project_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("baseline_schedule_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("discipline", sa.String(length=64), server_default="multidisciplinary", nullable=False),
        sa.Column("language", sa.String(length=16), server_default="ar", nullable=False),
        sa.Column("classification", sa.String(length=32), server_default="Preliminary", nullable=False),
        sa.Column("revision", sa.String(length=32), server_default="Rev 01", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("export_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="scheduled", nullable=False),
        sa.Column("is_baseline", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("start_date", sa.String(length=16), nullable=False),
        sa.Column("use_ai", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ai_draft_status", sa.String(length=32), server_default="not_used", nullable=False),
        sa.Column("owner_approved_by", sa.String(length=128), nullable=True),
        sa.Column("owner_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("calendar_json", sa.JSON(), nullable=False),
        sa.Column("wbs_items_json", sa.JSON(), nullable=False),
        sa.Column("activities_json", sa.JSON(), nullable=False),
        sa.Column("schedule_result_json", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["baseline_schedule_id"], ["project_schedules.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')",
            name="ck_classification_valid",
        ),
        sa.CheckConstraint(
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_schedules_ai_draft_status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_schedules_project_id", "project_schedules", ["project_id"], unique=False)
    op.create_index("ix_project_schedules_task_id", "project_schedules", ["task_id"], unique=False)
    op.create_index("ix_project_schedules_baseline_schedule_id", "project_schedules", ["baseline_schedule_id"], unique=False)
    op.create_index("ix_project_schedules_created_at", "project_schedules", ["created_at"], unique=False)

    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.add_column(sa.Column("schedule_id", sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f("ix_deliverables_schedule_id"), ["schedule_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_deliverables_schedule_id_project_schedules"),
            "project_schedules",
            ["schedule_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop deliverables.schedule_id link and project_schedules table."""
    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_deliverables_schedule_id_project_schedules"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_deliverables_schedule_id"))
        batch_op.drop_column("schedule_id")

    op.drop_index("ix_project_schedules_created_at", table_name="project_schedules")
    op.drop_index("ix_project_schedules_baseline_schedule_id", table_name="project_schedules")
    op.drop_index("ix_project_schedules_task_id", table_name="project_schedules")
    op.drop_index("ix_project_schedules_project_id", table_name="project_schedules")
    op.drop_table("project_schedules")
