"""Project management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.schemas.projects import ProjectCreate, ProjectDetail, ProjectListResponse
from app.services.projects import (
    DuplicateProjectCodeError,
    ProjectNotFoundError,
    create_project,
    get_project_detail,
    list_projects,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def create_project_endpoint(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> ProjectDetail:
    """Create a new engineering project and initialize its 12 workspace folders."""
    settings = _get_app_settings(request)
    try:
        return create_project(db, settings.workspaces_dir, payload)
    except DuplicateProjectCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=ProjectListResponse)
def list_projects_endpoint(db: Session = Depends(get_db)) -> ProjectListResponse:
    """List all stored engineering projects."""
    projects = list_projects(db)
    return ProjectListResponse(projects=projects, total=len(projects))


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project_endpoint(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> ProjectDetail:
    """Open one project and return its metadata and 12 workspace folder statuses."""
    settings = _get_app_settings(request)
    try:
        return get_project_detail(db, settings.workspaces_dir, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
