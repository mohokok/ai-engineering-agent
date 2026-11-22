"""step15_technical_comparisons

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-22 00:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create technical_comparisons table and link deliverables.comparison_id."""
    op.create_table(
        "technical_comparisons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("comparison_scope", sa.String(length=64), server_default="equipment", nullable=False),
        sa.Column("discipline", sa.String(length=64), server_default="multidisciplinary", nullable=False),
        sa.Column("language", sa.String(length=16), server_default="ar", nullable=False),
        sa.Column("classification", sa.String(length=32), server_default="Preliminary", nullable=False),
        sa.Column("revision", sa.String(length=32), server_default="Rev 01", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("export_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="evaluated", nullable=False),
        sa.Column("use_ai", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ai_draft_status", sa.String(length=32), server_default="not_used", nullable=False),
        sa.Column(
            "owner_decision_status",
            sa.String(length=32),
            server_default="pending_owner_decision",
            nullable=False,
        ),
        sa.Column("owner_selected_option_id", sa.String(length=64), nullable=True),
        sa.Column("owner_decision_note", sa.Text(), nullable=True),
        sa.Column("owner_decided_by", sa.String(length=128), nullable=True),
        sa.Column("owner_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("criteria_json", sa.JSON(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("matrix_result_json", sa.JSON(), nullable=False),
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
            "ai_draft_status IN ('not_used', 'unverified_ai_draft', 'owner_approved')",
            name="ck_comparisons_ai_draft_status_valid",
        ),
        sa.CheckConstraint(
            "owner_decision_status IN ('pending_owner_decision', 'owner_selected')",
            name="ck_comparisons_owner_decision_status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_technical_comparisons_project_id", "technical_comparisons", ["project_id"], unique=False)
    op.create_index("ix_technical_comparisons_task_id", "technical_comparisons", ["task_id"], unique=False)
    op.create_index("ix_technical_comparisons_created_at", "technical_comparisons", ["created_at"], unique=False)

    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.add_column(sa.Column("comparison_id", sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f("ix_deliverables_comparison_id"), ["comparison_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_deliverables_comparison_id_technical_comparisons"),
            "technical_comparisons",
            ["comparison_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop deliverables.comparison_id link and technical_comparisons table."""
    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_deliverables_comparison_id_technical_comparisons"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_deliverables_comparison_id"))
        batch_op.drop_column("comparison_id")

    op.drop_index("ix_technical_comparisons_created_at", table_name="technical_comparisons")
    op.drop_index("ix_technical_comparisons_task_id", table_name="technical_comparisons")
    op.drop_index("ix_technical_comparisons_project_id", table_name="technical_comparisons")
    op.drop_table("technical_comparisons")
