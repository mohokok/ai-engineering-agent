"""add_step05_task_metadata

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-19 12:50:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TASK_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("complexity", sa.String(length=16)),
    ("provider_name", sa.String(length=64)),
    ("model_name", sa.String(length=128)),
    ("attached_file_ids_json", sa.JSON()),
    ("structured_output_json", sa.JSON()),
    ("token_usage_json", sa.JSON()),
)


def upgrade() -> None:
    """Add nullable Step 05 orchestrator metadata columns to the tasks table."""
    for column_name, column_type in _TASK_COLUMNS:
        op.add_column("tasks", sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    """Remove Step 05 orchestrator metadata columns from the tasks table."""
    for column_name, _column_type in reversed(_TASK_COLUMNS):
        op.drop_column("tasks", column_name)
