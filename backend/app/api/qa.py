"""Step 12 API endpoints for independent QA Agent reviews, issue register management, and task verification gating."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.schemas.qa import (
    IssueCreateRequest,
    IssueListResponse,
    IssueOut,
    IssueUpdateRequest,
    QaReviewDetailOut,
    QaReviewListResponse,
    QaReviewRunRequest,
    TaskVerifyOut,
    TaskVerifyRequest,
)
from app.services.projects import ProjectNotFoundError
from app.services.qa import (
    QaNotFoundError,
    QaValidationError,
    QaVerificationBlockedError,
    create_manual_issue,
    get_qa_review_detail,
    list_project_issues,
    list_project_qa_reviews,
    run_project_qa_review,
    update_issue,
    verify_task_after_qa,
)

router = APIRouter(tags=["qa-and-issue-register"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post(
    "/projects/{project_id}/qa-reviews",
    response_model=QaReviewDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def run_project_qa_review_endpoint(
    project_id: str,
    payload: QaReviewRunRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> QaReviewDetailOut:
    """Run an independent QA inspection (isolated from producer reasoning, 0 AI tokens) and populate issues."""
    try:
        return run_project_qa_review(db, _get_settings(request), project_id, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except QaValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/qa-reviews",
    response_model=QaReviewListResponse,
)
def list_project_qa_reviews_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> QaReviewListResponse:
    """List independent QA review runs for a project newest first."""
    try:
        return list_project_qa_reviews(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/qa-reviews/{review_id}",
    response_model=QaReviewDetailOut,
)
def get_qa_review_detail_endpoint(
    review_id: str,
    db: Session = Depends(get_db),
) -> QaReviewDetailOut:
    """Retrieve QA review details, excluded producer fields proof, check counts, and issues."""
    try:
        return get_qa_review_detail(db, review_id)
    except QaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/tasks/{task_id}/verify",
    response_model=TaskVerifyOut,
)
def verify_task_endpoint(
    task_id: str,
    payload: TaskVerifyRequest,
    db: Session = Depends(get_db),
) -> TaskVerifyOut:
    """Verify a task only after an independent passing QA review with zero open issues."""
    try:
        return verify_task_after_qa(db, task_id, payload)
    except QaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (QaVerificationBlockedError, QaValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/issues",
    response_model=IssueListResponse,
)
def list_project_issues_endpoint(
    project_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> IssueListResponse:
    """List project QA issue register entries filterable by status, severity, and task_id."""
    try:
        return list_project_issues(
            db,
            project_id,
            status_filter=status_filter,
            severity_filter=severity,
            task_id=task_id,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/issues",
    response_model=IssueOut,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_issue_endpoint(
    project_id: str,
    payload: IssueCreateRequest,
    db: Session = Depends(get_db),
) -> IssueOut:
    """Manually record a new QA issue register entry under a project."""
    try:
        return create_manual_issue(db, project_id, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except QaValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.patch(
    "/issues/{issue_id}",
    response_model=IssueOut,
)
def update_issue_endpoint(
    issue_id: str,
    payload: IssueUpdateRequest,
    db: Session = Depends(get_db),
) -> IssueOut:
    """Close, reopen, or update a QA issue register entry cleanly."""
    try:
        return update_issue(db, issue_id, payload)
    except QaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except QaValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
