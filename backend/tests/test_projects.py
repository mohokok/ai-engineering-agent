"""Tests for project creation, 12-folder workspace layout, and restart persistence."""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AuditLog
from app.main import create_app
from app.services.workspace import (
    PROJECT_WORKSPACE_FOLDERS,
    resolve_project_dir,
    sanitize_workspace_stem,
)


def _test_settings(tmp_path: Path) -> Settings:
    ws = tmp_path / "workspaces"
    return Settings(
        workspaces_dir=ws,
        database_url="",
    )


def test_arabic_project_creation_folders_and_restart_persistence(tmp_path: Path) -> None:
    """Creating a project with an Arabic name creates 12 folders and survives app restart."""
    settings = _test_settings(tmp_path)
    arabic_name = "مستشفى طرابلس التعليمي"

    app_first = create_app(settings)
    with TestClient(app_first) as client:
        create_resp = client.post(
            "/api/projects",
            json={
                "name": arabic_name,
                "name_en": "Tripoli Teaching Hospital",
                "client_name": "وزارة الصحة",
                "location": "طرابلس",
                "description": "مشروع تصميم ومراجعة هندسية شاملة",
                "discipline_scope": "Multidisciplinary",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        project_id = created["id"]

        assert created["name"] == arabic_name
        assert created["name_en"] == "Tripoli Teaching Hospital"
        assert created["client_name"] == "وزارة الصحة"
        assert created["classification"] == "Preliminary"
        assert created["status"] == "active"
        assert created["workspace_exists"] is True
        assert arabic_name.split()[0] in created["workspace_slug"]

        folders = created["folders"]
        assert [f["name"] for f in folders] == list(PROJECT_WORKSPACE_FOLDERS)
        assert len(folders) == 12
        assert all(f["exists"] is True for f in folders)

        project_dir = settings.workspaces_dir / created["workspace_slug"]
        assert project_dir.is_dir()
        for folder_name in PROJECT_WORKSPACE_FOLDERS:
            assert (project_dir / folder_name).is_dir()

        with app_first.state.session_factory() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.entity_id == project_id,
                    AuditLog.action == "project.created",
                )
            )
            assert audit is not None
            assert audit.details_json["name"] == arabic_name

    # Simulate a fresh application restart using a new FastAPI app instance
    app_restarted = create_app(settings)
    with TestClient(app_restarted) as restarted_client:
        list_resp = restarted_client.get("/api/projects")
        assert list_resp.status_code == 200
        listed = list_resp.json()
        assert listed["total"] == 1
        assert len(listed["projects"]) == 1
        assert listed["projects"][0]["id"] == project_id
        assert listed["projects"][0]["name"] == arabic_name

        detail_resp = restarted_client.get(f"/api/projects/{project_id}")
        assert detail_resp.status_code == 200
        opened = detail_resp.json()
        assert opened["id"] == project_id
        assert opened["name"] == arabic_name
        assert opened["workspace_exists"] is True
        assert len(opened["folders"]) == 12
        assert all(f["exists"] is True for f in opened["folders"])


def test_duplicate_code_returns_409_without_orphaned_folder(tmp_path: Path) -> None:
    """Duplicate project codes return HTTP 409 and create no extra directories."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)

    with TestClient(app) as client:
        first = client.post("/api/projects", json={"name": "مشروع 1", "code": "HOSP-01"})
        assert first.status_code == 201

        second = client.post("/api/projects", json={"name": "مشروع 2", "code": "HOSP-01"})
        assert second.status_code == 409

    subdirs = [p for p in settings.workspaces_dir.iterdir() if p.is_dir()]
    assert len(subdirs) == 1


def test_validation_not_found_and_path_safety(tmp_path: Path) -> None:
    """Blank names return 422, missing IDs return 404, and unsafe folder names sanitize cleanly."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)

    with TestClient(app) as client:
        blank_resp = client.post("/api/projects", json={"name": "   "})
        assert blank_resp.status_code == 422

        missing_resp = client.get("/api/projects/non-existent-id")
        assert missing_resp.status_code == 404

        unsafe_resp = client.post(
            "/api/projects",
            json={"name": 'مشروع: <تجربة> / المرحلة * "1"'},
        )
        assert unsafe_resp.status_code == 201
        unsafe_data = unsafe_resp.json()
        assert unsafe_data["workspace_exists"] is True
        assert len(unsafe_data["folders"]) == 12

    assert sanitize_workspace_stem("CON") == "project"
    assert sanitize_workspace_stem("...") == "project"
    with pytest.raises(ValueError):
        resolve_project_dir(settings.workspaces_dir, "../escape")
