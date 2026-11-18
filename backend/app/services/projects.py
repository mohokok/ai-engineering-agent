"""Project service handling persistence, workspace folder creation, and audit logging."""

from datetime import datetime, timezone
from pathlib import Path
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import new_uuid
from app.db.models import AuditLog, Project
from app.schemas.projects import ProjectCreate, ProjectDetail, ProjectSummary, WorkspaceFolderOut
from app.services.workspace import (
    build_workspace_slug,
    create_project_workspace,
    inspect_project_folders,
    resolve_project_dir,
)


class DuplicateProjectCodeError(ValueError):
    """Raised when attempting to create a project with an existing project code."""


class ProjectNotFoundError(LookupError):
    """Raised when a requested project ID does not exist."""


def _generate_project_code(project_id: str) -> str:
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"PRJ-{date_part}-{project_id.replace('-', '')[:6].upper()}"


def _to_project_detail(project: Project, workspaces_dir: Path) -> ProjectDetail:
    project_dir = resolve_project_dir(workspaces_dir, project.workspace_slug)
    folders = inspect_project_folders(workspaces_dir, project.workspace_slug)
    summary = ProjectSummary.model_validate(project)
    return ProjectDetail(
        **summary.model_dump(),
        workspace_exists=project_dir.is_dir(),
        folders=[
            WorkspaceFolderOut(
                name=folder.name,
                relative_path=folder.relative_path,
                exists=folder.exists,
            )
            for folder in folders
        ],
    )


def create_project(
    db: Session,
    workspaces_dir: Path,
    payload: ProjectCreate,
) -> ProjectDetail:
    """Create a project database record, 12-folder workspace, and audit log entry."""
    project_id = new_uuid()
    code = payload.code or _generate_project_code(project_id)

    existing = db.scalar(select(Project.id).where(Project.code == code))
    if existing is not None:
        raise DuplicateProjectCodeError(f"Project code already exists: {code}")

    workspace_slug = build_workspace_slug(payload.name, project_id)
    project_dir = create_project_workspace(workspaces_dir, workspace_slug)

    try:
        project = Project(
            id=project_id,
            code=code,
            name=payload.name,
            name_en=payload.name_en,
            client_name=payload.client_name,
            location=payload.location,
            description=payload.description,
            discipline_scope=payload.discipline_scope,
            classification=payload.classification,
            status="active",
            workspace_slug=workspace_slug,
        )
        db.add(project)
        db.flush()

        db.add(
            AuditLog(
                project_id=project.id,
                action="project.created",
                entity_type="project",
                entity_id=project.id,
                actor="owner",
                details_json={
                    "code": project.code,
                    "name": project.name,
                    "workspace_slug": project.workspace_slug,
                },
            )
        )
        db.commit()
        db.refresh(project)
    except Exception:
        db.rollback()
        # Safe rollback: project_dir was just created with exist_ok=False for a new UUID slug,
        # so this only removes the empty 12-folder tree created by the same failed request.
        shutil.rmtree(project_dir, ignore_errors=True)
        raise

    return _to_project_detail(project, workspaces_dir)


def list_projects(db: Session) -> list[ProjectSummary]:
    """Return all projects ordered from newest to oldest."""
    rows = db.scalars(select(Project).order_by(Project.created_at.desc(), Project.id.asc())).all()
    return [ProjectSummary.model_validate(row) for row in rows]


def get_project_detail(
    db: Session,
    workspaces_dir: Path,
    project_id: str,
) -> ProjectDetail:
    """Load a project by ID along with live on-disk workspace folder status."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project not found: {project_id}")
    return _to_project_detail(project, workspaces_dir)
