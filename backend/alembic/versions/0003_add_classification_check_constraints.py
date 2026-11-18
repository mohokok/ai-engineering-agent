"""add_classification_check_constraints

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19 00:01:51.392313
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CLASSIFICATION_TABLES: tuple[str, ...] = (
    "projects",
    "files",
    "tasks",
    "deliverables",
    "calculations",
)
_CLASSIFICATION_CONDITION = (
    "classification IN ('Preliminary', 'Conceptual', 'For Review', 'For Coordination', 'For Approval')"
)


def upgrade() -> None:
    """Apply CHECK constraint limiting classification to the five CLAUDE.md labels."""
    for table_name in _CLASSIFICATION_TABLES:
        with op.batch_alter_table(table_name, schema=None, recreate="always") as batch_op:
            batch_op.create_check_constraint(
                op.f(f"ck_{table_name}_classification_valid"),
                _CLASSIFICATION_CONDITION,
            )


def downgrade() -> None:
    """Remove classification CHECK constraints."""
    for table_name in reversed(_CLASSIFICATION_TABLES):
        with op.batch_alter_table(table_name, schema=None, recreate="always") as batch_op:
            batch_op.drop_constraint(
                op.f(f"ck_{table_name}_classification_valid"),
                type_="check",
            )
