"""Step 09 API endpoints for document/drawing review reports and deliverables download."""

from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.reports import (
    DeliverableListResponse,
    ReviewAiSynthesizeRequest,
    ReviewReportDetailOut,
    ReviewReportGenerateRequest,
    ReviewReportListResponse,
)
from app.services.files import FileRecordNotFoundError
from app.services.projects import ProjectNotFoundError
from app.services.review_reports import (
    DeliverableNotFoundError,
    enhance_existing_report_with_ai,
    generate_project_review_report,
    get_review_report_detail,
    list_deliverables,
    list_project_review_reports,
    resolve_deliverable_download,
)
from app.services.workspace import WorkspacePathError

router = APIRouter(tags=["reports-and-deliverables"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.post(
    "/projects/{project_id}/review-reports",
    response_model=ReviewReportDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review_report_endpoint(
    project_id: str,
    payload: ReviewReportGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewReportDetailOut:
    """Run Orchestrator + review skill on project extractions & research logs and save versioned DOCX/PDF deliverables."""
    try:
        return generate_project_review_report(
            db,
            _get_settings(request),
            _get_secret_store(request),
            project_id,
            payload,
            client_factory=_get_client_factory(request),
        )
    except (ProjectNotFoundError, FileRecordNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (ValueError, WorkspacePathError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/projects/{project_id}/review-reports", response_model=ReviewReportListResponse)
def list_project_review_reports_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> ReviewReportListResponse:
    """List generated review reports for one project ordered newest first."""
    try:
        items = list_project_review_reports(db, project_id)
        return ReviewReportListResponse(reports=items, total=len(items))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/review-reports/{report_id}", response_model=ReviewReportDetailOut)
def get_review_report_endpoint(
    report_id: str,
    db: Session = Depends(get_db),
) -> ReviewReportDetailOut:
    """Fetch complete details for one generated review report."""
    try:
        return get_review_report_detail(db, report_id)
    except DeliverableNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/review-reports/{report_id}/ai-synthesize", response_model=ReviewReportDetailOut)
def enhance_review_report_ai_endpoint(
    report_id: str,
    payload: ReviewAiSynthesizeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewReportDetailOut:
    """Enhance an existing review report using capped Gemini synthesis and save next immutable version."""
    try:
        return enhance_existing_report_with_ai(
            db,
            _get_settings(request),
            _get_secret_store(request),
            report_id,
            complexity=payload.complexity,
            client_factory=_get_client_factory(request),
        )
    except DeliverableNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/deliverables", response_model=DeliverableListResponse)
def list_deliverables_endpoint(
    project_id: str | None = Query(default=None),
    folder_name: str | None = Query(default=None),
    file_format: str | None = Query(default=None, alias="format"),
    db: Session = Depends(get_db),
) -> DeliverableListResponse:
    """List persisted DOCX/PDF deliverables across or within projects."""
    try:
        items = list_deliverables(
            db,
            project_id=project_id,
            folder_name=folder_name,
            file_format=file_format,
        )
        return DeliverableListResponse(deliverables=items, total=len(items))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/projects/{project_id}/deliverables", response_model=DeliverableListResponse)
def list_project_deliverables_endpoint(
    project_id: str,
    folder_name: str | None = Query(default=None),
    file_format: str | None = Query(default=None, alias="format"),
    db: Session = Depends(get_db),
) -> DeliverableListResponse:
    """List persisted deliverables belonging to one project."""
    try:
        items = list_deliverables(
            db,
            project_id=project_id,
            folder_name=folder_name,
            file_format=file_format,
        )
        return DeliverableListResponse(deliverables=items, total=len(items))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/deliverables/{deliverable_id}/download")
def download_deliverable_endpoint(
    deliverable_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Stream one generated DOCX or PDF deliverable with SHA-256 verification and UTF-8 filename."""
    try:
        dl = resolve_deliverable_download(db, _get_settings(request), deliverable_id)
    except DeliverableNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, WorkspacePathError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    encoded_name = quote(dl.download_filename, safe="")
    ascii_fallback = dl.download_filename.encode("ascii", errors="ignore").decode("ascii").strip() or "deliverable"
    headers = {
        "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_name}'
    }
    return FileResponse(path=dl.path, media_type=dl.media_type, headers=headers)
