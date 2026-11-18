"""Tests for Alembic initial schema migrations and SQLite pragmas."""

from pathlib import Path

from sqlalchemy import inspect, text

from app.db.migrations import downgrade_database, upgrade_database
from app.db.session import create_db_engine

EXPECTED_TABLES = {
    "projects",
    "files",
    "file_versions",
    "tasks",
    "task_steps",
    "deliverables",
    "research_sources",
    "issues",
    "calculations",
    "settings",
    "audit_log",
}


def test_alembic_upgrade_and_downgrade_round_trip(tmp_path: Path) -> None:
    """Alembic upgrade creates all 11 tables and downgrade cleanly reverts them."""
    db_path = tmp_path / "nested" / "test_migrations.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    upgrade_database(db_url, "head")
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(tables)

        with engine.connect() as conn:
            fk_enabled = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert fk_enabled == 1
    finally:
        engine.dispose()

    downgrade_database(db_url, "base")
    engine = create_db_engine(db_url)
    try:
        tables_after_downgrade = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES.isdisjoint(tables_after_downgrade)
    finally:
        engine.dispose()

    upgrade_database(db_url, "head")
    engine = create_db_engine(db_url)
    try:
        assert EXPECTED_TABLES.issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()
