"""create_step11_parametric_drawings

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-21 12:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create parametric_drawings table and link deliverables.drawing_id."""
    op.create_table(
        "parametric_drawings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("drawing_no", sa.String(length=64), server_default="A-101", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("scale_denominator", sa.Integer(), server_default="100", nullable=False),
        sa.Column("paper_size", sa.String(length=16), server_default="A3", nullable=False),
        sa.Column("units", sa.String(length=16), server_default="mm", nullable=False),
        sa.Column("classification", sa.String(length=32), server_default="Preliminary", nullable=False),
        sa.Column("revision", sa.String(length=32), server_default="Rev 01", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="generated", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("model_json", sa.JSON(), nullable=False),
        sa.Column("computed_metrics_json", sa.JSON(), nullable=False),
        sa.Column("round_trip_passed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ai_suggested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')",
            name=op.f("ck_parametric_drawings_classification_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_parametric_drawings_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_parametric_drawings_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parametric_drawings")),
    )
    with op.batch_alter_table("parametric_drawings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_parametric_drawings_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_parametric_drawings_task_id"), ["task_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_parametric_drawings_created_at"), ["created_at"], unique=False)

    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.add_column(sa.Column("drawing_id", sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f("ix_deliverables_drawing_id"), ["drawing_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_deliverables_drawing_id_parametric_drawings"),
            "parametric_drawings",
            ["drawing_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop Step 11 parametric_drawings table and deliverables.drawing_id."""
    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_deliverables_drawing_id_parametric_drawings"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_deliverables_drawing_id"))
        batch_op.drop_column("drawing_id")

    with op.batch_alter_table("parametric_drawings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_parametric_drawings_created_at"))
        batch_op.drop_index(batch_op.f("ix_parametric_drawings_task_id"))
        batch_op.drop_index(batch_op.f("ix_parametric_drawings_project_id"))
    op.drop_table("parametric_drawings")
