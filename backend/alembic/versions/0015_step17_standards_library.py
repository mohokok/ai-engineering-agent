"""step17_standards_library

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-22 04:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create standards_library table for owner-supplied and licensed engineering standards."""
    op.create_table(
        "standards_library",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("standard_number", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("issuing_body", sa.String(length=255), server_default="", nullable=False),
        sa.Column("edition_year", sa.String(length=64), server_default="unknown", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        sa.Column("supersession_note", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=255), server_default="", nullable=False),
        sa.Column("adopted_locally", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("owner_notes", sa.Text(), nullable=True),
        sa.Column("owner_excerpts_json", sa.JSON(), nullable=False),
        sa.Column("metadata_status", sa.String(length=32), server_default="owner_entered", nullable=False),
        sa.Column("suggested_metadata_json", sa.JSON(), nullable=True),
        sa.Column("use_ai", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ai_suggestion_status", sa.String(length=32), server_default="not_used", nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("file_relative_path", sa.String(length=1024), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("history_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["standards_library.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('current', 'superseded', 'withdrawn', 'unknown')",
            name="ck_standards_status_valid",
        ),
        sa.CheckConstraint(
            "metadata_status IN ('owner_entered', 'unverified_suggestion', 'unverified_ai_suggestion', 'owner_confirmed')",
            name="ck_standards_metadata_status_valid",
        ),
        sa.CheckConstraint(
            "ai_suggestion_status IN ('not_used', 'unverified_ai_suggestion', 'owner_confirmed')",
            name="ck_standards_ai_suggestion_status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_standards_library_project_id", "standards_library", ["project_id"], unique=False)
    op.create_index("ix_standards_library_standard_number", "standards_library", ["standard_number"], unique=False)
    op.create_index("ix_standards_library_superseded_by_id", "standards_library", ["superseded_by_id"], unique=False)
    op.create_index("ix_standards_library_file_sha256", "standards_library", ["file_sha256"], unique=False)
    op.create_index("ix_standards_library_created_at", "standards_library", ["created_at"], unique=False)


def downgrade() -> None:
    """Drop standards_library table cleanly."""
    op.drop_index("ix_standards_library_created_at", table_name="standards_library")
    op.drop_index("ix_standards_library_file_sha256", table_name="standards_library")
    op.drop_index("ix_standards_library_superseded_by_id", table_name="standards_library")
    op.drop_index("ix_standards_library_standard_number", table_name="standards_library")
    op.drop_index("ix_standards_library_project_id", table_name="standards_library")
    op.drop_table("standards_library")
