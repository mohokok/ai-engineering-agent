"""create_step08_research_runs_and_source_provenance

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20 18:55:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create research_runs table and extend research_sources with priority and review provenance."""
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("search_provider", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("structured_output_json", sa.JSON(), nullable=True),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("artifact_relative_path", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')",
            name=op.f("ck_research_runs_classification_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_research_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_research_runs_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_runs")),
    )
    with op.batch_alter_table("research_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_research_runs_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_research_runs_task_id"),
            ["task_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_research_runs_created_at"),
            ["created_at"],
            unique=False,
        )

    with op.batch_alter_table("research_sources", schema=None) as batch_op:
        batch_op.add_column(sa.Column("research_run_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "source_priority_tier",
                sa.String(length=64),
                server_default="reputable",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("priority_rank", sa.Integer(), server_default="6", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "access_status",
                sa.String(length=32),
                server_default="accessible",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "reviewed",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("http_status", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "untrusted_neutralized",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_research_sources_research_run_id"),
            ["research_run_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            op.f("fk_research_sources_research_run_id_research_runs"),
            "research_runs",
            ["research_run_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Remove Step 08 columns from research_sources and drop research_runs."""
    with op.batch_alter_table("research_sources", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("fk_research_sources_research_run_id_research_runs"),
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_research_sources_research_run_id"))
        batch_op.drop_column("untrusted_neutralized")
        batch_op.drop_column("failure_reason")
        batch_op.drop_column("http_status")
        batch_op.drop_column("reviewed")
        batch_op.drop_column("access_status")
        batch_op.drop_column("priority_rank")
        batch_op.drop_column("source_priority_tier")
        batch_op.drop_column("research_run_id")

    op.drop_table("research_runs")
