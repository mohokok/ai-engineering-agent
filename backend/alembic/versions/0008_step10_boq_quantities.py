"""create_step10_boq_sheets_and_items

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-21 11:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create boq_sheets and boq_items tables and link BOQ deliverables."""
    op.create_table(
        "boq_sheets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=16), server_default="ar", nullable=False),
        sa.Column("currency", sa.String(length=16), server_default="LYD", nullable=False),
        sa.Column("classification", sa.String(length=32), server_default="Preliminary", nullable=False),
        sa.Column("revision", sa.String(length=32), server_default="Rev 01", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("export_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_scope", sa.String(length=32), server_default="mixed", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("checks_summary_json", sa.JSON(), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')",
            name=op.f("ck_boq_sheets_classification_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_boq_sheets_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_boq_sheets_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_sheets")),
    )
    with op.batch_alter_table("boq_sheets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_boq_sheets_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_boq_sheets_task_id"), ["task_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_boq_sheets_created_at"), ["created_at"], unique=False)

    op.create_table(
        "boq_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("boq_sheet_id", sa.String(length=36), nullable=False),
        sa.Column("row_order", sa.Integer(), server_default="1", nullable=False),
        sa.Column("item_no", sa.String(length=64), server_default="", nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=64), server_default="", nullable=False),
        sa.Column("quantity", sa.Float(), server_default="0", nullable=False),
        sa.Column("unit_rate", sa.Float(), nullable=True),
        sa.Column("total", sa.Float(), nullable=True),
        sa.Column("reported_total", sa.Float(), nullable=True),
        sa.Column("technical_reference", sa.Text(), nullable=True),
        sa.Column("drawing_reference", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            server_default="Extracted-Needs-Check",
            nullable=False,
        ),
        sa.Column("rate_source_kind", sa.String(length=32), nullable=True),
        sa.Column("rate_source_ref", sa.Text(), nullable=True),
        sa.Column("rate_source_date", sa.String(length=64), nullable=True),
        sa.Column("source_file_id", sa.String(length=36), nullable=True),
        sa.Column("source_extraction_id", sa.String(length=36), nullable=True),
        sa.Column("discipline", sa.String(length=64), nullable=True),
        sa.Column("layer_or_category", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "verification_status IN ('Extracted-Verified', 'Extracted-Needs-Check', 'Manual')",
            name=op.f("ck_boq_items_verification_status_valid"),
        ),
        sa.CheckConstraint(
            "rate_source_kind IS NULL OR rate_source_kind IN ('owner_input', 'dated_research')",
            name=op.f("ck_boq_items_rate_source_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["boq_sheet_id"],
            ["boq_sheets.id"],
            name=op.f("fk_boq_items_boq_sheet_id_boq_sheets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["files.id"],
            name=op.f("fk_boq_items_source_file_id_files"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_extraction_id"],
            ["file_extractions.id"],
            name=op.f("fk_boq_items_source_extraction_id_file_extractions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_items")),
    )
    with op.batch_alter_table("boq_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_boq_items_boq_sheet_id"), ["boq_sheet_id"], unique=False)

    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.add_column(sa.Column("boq_id", sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f("ix_deliverables_boq_id"), ["boq_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_deliverables_boq_id_boq_sheets"),
            "boq_sheets",
            ["boq_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop Step 10 boq_items, boq_sheets, and deliverables.boq_id column."""
    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_deliverables_boq_id_boq_sheets"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_deliverables_boq_id"))
        batch_op.drop_column("boq_id")

    with op.batch_alter_table("boq_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_boq_items_boq_sheet_id"))
    op.drop_table("boq_items")

    with op.batch_alter_table("boq_sheets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_boq_sheets_created_at"))
        batch_op.drop_index(batch_op.f("ix_boq_sheets_task_id"))
        batch_op.drop_index(batch_op.f("ix_boq_sheets_project_id"))
    op.drop_table("boq_sheets")
