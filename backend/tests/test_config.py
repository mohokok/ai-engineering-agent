"""Tests for configuration loading and path resolution."""

from pathlib import Path

from app.core.config import REPO_ROOT, Settings


def test_blank_workspaces_dir_defaults_to_repo_root() -> None:
    """Blank WORKSPACES_DIR falls back to REPO_ROOT / 'workspaces'."""
    settings = Settings(workspaces_dir="")
    assert settings.workspaces_dir == REPO_ROOT / "workspaces"


def test_relative_workspaces_dir_resolves_against_repo_root() -> None:
    """Relative WORKSPACES_DIR resolves against REPO_ROOT, not process cwd."""
    settings = Settings(workspaces_dir="./custom_workspaces")
    assert settings.workspaces_dir == (REPO_ROOT / Path("custom_workspaces")).resolve()


def test_blank_database_url_defaults_inside_workspaces_dir(tmp_path: Path) -> None:
    """Blank DATABASE_URL defaults to sqlite:///<WORKSPACES_DIR>/engineering_agent.db."""
    ws = tmp_path / "ws"
    settings = Settings(workspaces_dir=ws, database_url="")
    assert settings.database_url == f"sqlite:///{(ws / 'engineering_agent.db').as_posix()}"


def test_relative_sqlite_database_url_resolves_against_repo_root() -> None:
    """Relative SQLite URLs resolve against REPO_ROOT instead of process cwd."""
    settings = Settings(database_url="sqlite:///./custom_data/agent.db")
    expected = (REPO_ROOT / Path("custom_data/agent.db")).resolve().as_posix()
    assert settings.database_url == f"sqlite:///{expected}"


def test_postgresql_and_memory_database_urls_pass_through() -> None:
    """PostgreSQL URLs and SQLite :memory: URLs remain unmodified."""
    pg_url = "postgresql+psycopg://engineer:secret@localhost:5432/engineering_agent"
    assert Settings(database_url=pg_url).database_url == pg_url
    assert Settings(database_url="sqlite:///:memory:").database_url == "sqlite:///:memory:"
