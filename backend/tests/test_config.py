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
