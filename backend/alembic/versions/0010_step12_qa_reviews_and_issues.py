"""create_step12_qa_reviews_and_issues

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-21 13:50:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create qa_reviews table, add task verification_status gate, and enrich issues register columns."""
    op.create_table(
        "qa_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("classification", sa.String(length=32), server_default="Preliminary", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="issues_found", nullable=False),
        sa.Column("producer_reasoning_excluded", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("checks_summary_json", sa.JSON(), nullable=False),
        sa.Column("qa_context_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("issues_opened_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("open_issues_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')",
            name=op.f("ck_qa_reviews_classification_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_qa_reviews_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_qa_reviews_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qa_reviews")),
    )
    with op.batch_alter_table("qa_reviews", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_qa_reviews_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_qa_reviews_task_id"), ["task_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_qa_reviews_created_at"), ["created_at"], unique=False)

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("verification_status", sa.String(length=32), server_default="unverified", nullable=False)
        )
        batch_op.add_column(sa.Column("last_qa_review_id", sa.String(length=36), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_tasks_verification_status_valid"),
            "verification_status IN ('unverified', 'qa_passed', 'qa_failed', 'verified')",
        )

    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.add_column(sa.Column("qa_review_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("check_category", sa.String(length=64), server_default="general", nullable=False)
        )
        batch_op.add_column(sa.Column("closure_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f("ix_issues_qa_review_id"), ["qa_review_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_issues_qa_review_id_qa_reviews"),
            "qa_reviews",
            ["qa_review_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Revert Step 12 qa_reviews, task verification_status, and extra issue columns."""
    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_issues_qa_review_id_qa_reviews"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_issues_qa_review_id"))
        batch_op.drop_column("closed_at")
        batch_op.drop_column("closure_note")
        batch_op.drop_column("check_category")
        batch_op.drop_column("qa_review_id")

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_tasks_verification_status_valid"), type_="check")
        batch_op.drop_column("last_qa_review_id")
        batch_op.drop_column("verification_status")

    with op.batch_alter_table("qa_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_qa_reviews_created_at"))
        batch_op.drop_index(batch_op.f("ix_qa_reviews_task_id"))
        batch_op.drop_index(batch_op.f("ix_qa_reviews_project_id"))
    op.drop_table("qa_reviews")
