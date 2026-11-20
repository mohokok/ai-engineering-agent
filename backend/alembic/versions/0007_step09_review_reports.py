"""create_step09_review_reports_and_deliverable_paths

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-20 20:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create review_reports table and extend deliverables with versioned storage metadata."""
    op.create_table(
        "review_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("discipline", sa.String(length=64), server_default="multidisciplinary", nullable=False),
        sa.Column("language", sa.String(length=16), server_default="ar", nullable=False),
        sa.Column("classification", sa.String(length=32), server_default="Preliminary", nullable=False),
        sa.Column("revision", sa.String(length=32), server_default="Rev 01", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="generated", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("structured_payload_json", sa.JSON(), nullable=True),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("estimated_prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')",
            name=op.f("ck_review_reports_classification_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_review_reports_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_review_reports_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_reports")),
    )
    with op.batch_alter_table("review_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_review_reports_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_review_reports_task_id"),
            ["task_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_review_reports_created_at"),
            ["created_at"],
            unique=False,
        )

    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.add_column(sa.Column("report_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("folder_name", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("filename", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("relative_path", sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column("mime_type", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("size_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("sha256", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_deliverables_report_id"), ["report_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_deliverables_report_id_review_reports"),
            "review_reports",
            ["report_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop Step 09 review_reports table and deliverable storage columns."""
    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("fk_deliverables_report_id_review_reports"),
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_deliverables_report_id"))
        batch_op.drop_column("sha256")
        batch_op.drop_column("size_bytes")
        batch_op.drop_column("mime_type")
        batch_op.drop_column("relative_path")
        batch_op.drop_column("filename")
        batch_op.drop_column("folder_name")
        batch_op.drop_column("report_id")

    with op.batch_alter_table("review_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_review_reports_created_at"))
        batch_op.drop_index(batch_op.f("ix_review_reports_task_id"))
        batch_op.drop_index(batch_op.f("ix_review_reports_project_id"))

    op.drop_table("review_reports")
