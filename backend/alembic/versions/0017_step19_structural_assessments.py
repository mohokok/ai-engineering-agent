"""step19_structural_assessments

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-22 08:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create structural_assessments table and link deliverables.structural_id."""
    op.create_table(
        "structural_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("assessment_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=16), server_default="ar", nullable=False),
        sa.Column("classification", sa.String(length=32), server_default="Preliminary", nullable=False),
        sa.Column("revision", sa.String(length=32), server_default="Rev 01", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("export_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="evaluated", nullable=False),
        sa.Column("checks_passed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("blocked_missing_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_checks_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "standards_status",
            sa.String(length=64),
            server_default="no_verified_standard_on_file",
            nullable=False,
        ),
        sa.Column("use_ai", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ai_draft_status", sa.String(length=32), server_default="not_used", nullable=False),
        sa.Column("owner_approved_by", sa.String(length=128), nullable=True),
        sa.Column("owner_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("references_json", sa.JSON(), nullable=False),
        sa.Column("preliminary_assumptions_json", sa.JSON(), nullable=False),
        sa.Column("software_recommendation", sa.Text(), server_default="", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')",
            name="ck_classification_valid",
        ),
        sa.CheckConstraint(
            "assessment_type IN ('takedown_check', 'load_combinations', 'simple_statics_beam', 'full_structural_check')",
            name="ck_structural_type_valid",
        ),
        sa.CheckConstraint(
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_structural_ai_draft_status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_structural_assessments_project_id", "structural_assessments", ["project_id"], unique=False)
    op.create_index("ix_structural_assessments_task_id", "structural_assessments", ["task_id"], unique=False)
    op.create_index("ix_structural_assessments_assessment_type", "structural_assessments", ["assessment_type"], unique=False)
    op.create_index("ix_structural_assessments_created_at", "structural_assessments", ["created_at"], unique=False)

    with op.batch_alter_table("deliverables") as batch_op:
        batch_op.add_column(sa.Column("structural_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_deliverables_structural_id", ["structural_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_deliverables_structural_id",
            "structural_assessments",
            ["structural_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop deliverables.structural_id and structural_assessments cleanly."""
    with op.batch_alter_table("deliverables") as batch_op:
        batch_op.drop_constraint("fk_deliverables_structural_id", type_="foreignkey")
        batch_op.drop_index("ix_deliverables_structural_id")
        batch_op.drop_column("structural_id")

    op.drop_index("ix_structural_assessments_created_at", table_name="structural_assessments")
    op.drop_index("ix_structural_assessments_assessment_type", table_name="structural_assessments")
    op.drop_index("ix_structural_assessments_task_id", table_name="structural_assessments")
    op.drop_index("ix_structural_assessments_project_id", table_name="structural_assessments")
    op.drop_table("structural_assessments")
