"""step13_calculation_framework

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-21 16:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Extend calculations with Step 13 metadata/acceptance fields and link deliverables.calculation_id."""
    with op.batch_alter_table("calculations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("references_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("revision", sa.String(length=32), server_default="Rev 01", nullable=False)
        )
        batch_op.add_column(
            sa.Column("version", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("export_version", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("language", sa.String(length=16), server_default="ar", nullable=False)
        )
        batch_op.add_column(
            sa.Column("acceptance_passed", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False)
        )

    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.add_column(sa.Column("calculation_id", sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f("ix_deliverables_calculation_id"), ["calculation_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_deliverables_calculation_id_calculations"),
            "calculations",
            ["calculation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Revert Step 13 calculation metadata columns and deliverables.calculation_id."""
    with op.batch_alter_table("deliverables", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_deliverables_calculation_id_calculations"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_deliverables_calculation_id"))
        batch_op.drop_column("calculation_id")

    with op.batch_alter_table("calculations", schema=None) as batch_op:
        batch_op.drop_column("tokens_used")
        batch_op.drop_column("acceptance_passed")
        batch_op.drop_column("language")
        batch_op.drop_column("export_version")
        batch_op.drop_column("version")
        batch_op.drop_column("revision")
        batch_op.drop_column("references_json")
