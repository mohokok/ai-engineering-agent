"""Programmatic Alembic migration helpers for application startup and testing."""

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_ROOT / "alembic.ini"


def build_alembic_config(database_url: str) -> Config:
    """Build an Alembic Config bound to the target database URL."""
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """Apply Alembic migrations up to the target revision."""
    command.upgrade(build_alembic_config(database_url), revision)


def downgrade_database(database_url: str, revision: str = "base") -> None:
    """Revert Alembic migrations down to the target revision."""
    command.downgrade(build_alembic_config(database_url), revision)
