"""Step 12 QA Agent orchestration, issue register lifecycle, and task verification gate (0 AI tokens)."""

from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.agents.qa_agent import (
    build_isolated_qa_context,
    build_qa_context_isolation_report,
    count_inspected_artefacts,
    evaluate_independent_qa,
)
from app.core.config import Settings
from app.db.base import new_uuid, utc_now
from app.db.models import AuditLog, Issue, Project, QaReview, Task
from app.schemas.qa import (
    IssueCreateRequest,
    IssueListResponse,
    IssueOut,
    IssueUpdateRequest,
    QaCheckMetricOut,
    QaContextIsolationReport,
    QaReviewDetailOut,
    QaReviewListResponse,
    QaReviewRunRequest,
    TaskVerifyOut,
    TaskVerifyRequest,
)
from app.services.projects import ProjectNotFoundError

_QA_NUM_RE = re.compile(r"^QA-(\d+)$", re.IGNORECASE)


class QaNotFoundError(LookupError):
    """Raised when a requested QA review or issue ID does not exist."""


class QaValidationError(ValueError):
    """Raised when a QA or issue payload violates project ownership or status rules."""


class QaVerificationBlockedError(ValueError):
    """Raised when attempting to verify a task without a passing independent QA review and zero open issues."""


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize SQLite naive datetimes and aware datetimes to UTC for safe comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _next_issue_number(db: Session, project_id: str) -> int:
    existing_nums = db.scalars(select(Issue.issue_number).where(Issue.project_id == project_id)).all()
    max_seq = 0
    for code in existing_nums:
        m = _QA_NUM_RE.match(str(code or "").strip())
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def _to_issue_out(row: Issue) -> IssueOut:
    return IssueOut(
        id=row.id,
        project_id=row.project_id,
        task_id=row.task_id,
        deliverable_id=row.deliverable_id,
        qa_review_id=row.qa_review_id,
        issue_number=row.issue_number,
        title=row.title,
        description=row.description,
        discipline=row.discipline,
        severity=row.severity,
        check_category=row.check_category,
        reference=row.reference,
        corrective_action=row.recommended_action,
        recommended_action=row.recommended_action,
        status=row.status,
        closure_note=row.closure_note,
        closed_at=row.closed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_qa_review_detail(row: QaReview, db: Session) -> QaReviewDetailOut:
    project = row.project
    task_verif: str | None = None
    if row.task_id:
        t_row = db.get(Task, row.task_id)
        task_verif = t_row.verification_status if t_row else None

    checks_raw = (row.checks_summary_json or {}).get("checks") or []
    checks = [QaCheckMetricOut.model_validate(item) for item in checks_raw]
    ctx_snap = QaContextIsolationReport.model_validate(row.qa_context_snapshot_json or {})
    sorted_issues = sorted(list(row.issues or []), key=lambda it: it.issue_number)

    return QaReviewDetailOut(
        id=row.id,
        project_id=row.project_id,
        project_code=project.code if project else "",
        project_name=project.name if project else "",
        task_id=row.task_id,
        task_verification_status=task_verif,
        classification=row.classification,
        status=row.status,
        producer_reasoning_excluded=bool(row.producer_reasoning_excluded),
        qa_context_summary=ctx_snap,
        checks=checks,
        issues_opened_count=row.issues_opened_count,
        open_issues_count=row.open_issues_count,
        tokens_used=row.tokens_used,
        issues=[_to_issue_out(it) for it in sorted_issues],
        created_at=row.created_at,
    )


def run_project_qa_review(
    db: Session,
    settings: Settings,
    project_id: str,
    payload: QaReviewRunRequest,
) -> QaReviewDetailOut:
    """Execute independent deterministic QA inspection without producer reasoning (0 AI tokens) and persist issue register items."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    task_row: Task | None = None
    if payload.task_id:
        task_row = db.get(Task, payload.task_id)
        if task_row is None or task_row.project_id != project_id:
            raise QaValidationError(f"Task '{payload.task_id}' does not belong to project '{project_id}'.")

    effective_classification = payload.classification or (
        task_row.classification if task_row is not None else project.classification
    )

    # 1. Build strictly isolated QA context (NO Task.plan_summary, NO Task.result_summary, NO producer reasoning)
    ctx = build_isolated_qa_context(db, project, task=task_row)
    isolation_report = build_qa_context_isolation_report(ctx)

    # 2. Run independent code-recomputed checks (arithmetic, units, references, schedule consistency, deliverables)
    metrics, candidate_findings = evaluate_independent_qa(
        ctx,
        settings=settings,
        workspace_slug=project.workspace_slug,
        check_arithmetic=payload.check_arithmetic,
        check_units=payload.check_units,
        check_references=payload.check_references,
        check_consistency=payload.check_consistency,
        check_missing_deliverables=payload.check_missing_deliverables,
    )

    review_id = new_uuid()
    next_seq = _next_issue_number(db, project_id)
    inspected_artefacts = count_inspected_artefacts(ctx)
    total_checked = sum(m.checked_count for m in metrics)

    max_closed_raw = db.scalar(
        select(func.max(Issue.closed_at)).where(Issue.project_id == project.id)
    )
    max_closed = _as_utc(max_closed_raw)
    review_created_at = utc_now()
    if max_closed is not None and review_created_at <= max_closed:
        review_created_at = max_closed + timedelta(microseconds=1)

    # Reuse matching already-open issues instead of duplicating rows on repeat QA runs
    existing_open_rows = db.scalars(
        select(Issue).where(Issue.project_id == project_id, Issue.status != "closed")
    ).all()
    existing_open_keys: dict[tuple[str, str, str], Issue] = {
        (it.check_category, it.description, it.reference or ""): it for it in existing_open_rows
    }

    review_row = QaReview(
        id=review_id,
        project_id=project.id,
        task_id=task_row.id if task_row else None,
        classification=effective_classification,
        status="no_evidence" if (inspected_artefacts == 0 or total_checked == 0) else "issues_found",
        producer_reasoning_excluded=True,
        checks_summary_json={"checks": [m.model_dump() for m in metrics]},
        qa_context_snapshot_json=isolation_report.model_dump(),
        issues_opened_count=0,
        open_issues_count=0,
        tokens_used=0,
        created_at=review_created_at,
    )
    db.add(review_row)
    db.flush()

    opened_count = 0
    for f in candidate_findings:
        dedupe_key = (f.check_category, f.description, f.reference or "")
        existing_match = existing_open_keys.get(dedupe_key)
        if existing_match is not None:
            existing_match.qa_review_id = review_row.id
            if task_row is not None and existing_match.task_id is None and f.task_id is None:
                existing_match.task_id = task_row.id
            continue

        issue_num = f"QA-{next_seq:03d}"
        next_seq += 1
        new_issue = Issue(
            project_id=project.id,
            task_id=f.task_id or (task_row.id if task_row else None),
            deliverable_id=f.deliverable_id,
            qa_review_id=review_row.id,
            issue_number=issue_num,
            title=f.title[:255],
            description=f.description,
            discipline=f.discipline[:64],
            severity=f.severity,
            check_category=f.check_category,
            reference=f.reference[:512] if f.reference else None,
            recommended_action=f.corrective_action,
            status="open",
        )
        db.add(new_issue)
        existing_open_keys[dedupe_key] = new_issue
        opened_count += 1

    db.flush()

    open_stmt = select(Issue).where(Issue.project_id == project.id, Issue.status != "closed")
    if task_row is not None:
        open_stmt = open_stmt.where(Issue.task_id == task_row.id)
    total_open_now = len(db.scalars(open_stmt).all())

    if inspected_artefacts == 0 or total_checked == 0:
        review_status = "no_evidence"
    elif total_open_now > 0:
        review_status = "issues_found"
    else:
        review_status = "passed"

    review_row.issues_opened_count = opened_count
    review_row.open_issues_count = total_open_now
    review_row.status = review_status

    # Never mark a task "verified" on generation alone; advance only to qa_passed (or qa_failed) on independent QA.
    if task_row is not None:
        task_row.last_qa_review_id = review_row.id
        task_row.verification_status = "qa_passed" if review_status == "passed" else "qa_failed"

    db.add(
        AuditLog(
            project_id=project.id,
            action="qa_review.executed",
            entity_type="qa_review",
            entity_id=review_row.id,
            actor="qa_agent",
            details_json={
                "task_id": task_row.id if task_row else None,
                "status": review_row.status,
                "inspected_artefacts_count": inspected_artefacts,
                "issues_opened_count": opened_count,
                "open_issues_count": total_open_now,
                "producer_reasoning_excluded": True,
                "tokens_used": 0,
            },
        )
    )
    db.commit()

    loaded = db.scalar(
        select(QaReview)
        .options(selectinload(QaReview.project), selectinload(QaReview.issues))
        .where(QaReview.id == review_row.id)
    )
    assert loaded is not None
    return _to_qa_review_detail(loaded, db)


def verify_task_after_qa(
    db: Session,
    task_id: str,
    payload: TaskVerifyRequest,
) -> TaskVerifyOut:
    """Enforce Step 12 invariant: a task cannot be marked verified by generation alone; requires passing QA with 0 open issues."""
    task = db.get(Task, task_id)
    if task is None:
        raise QaNotFoundError(f"Task '{task_id}' was not found.")

    review_id = payload.qa_review_id or task.last_qa_review_id
    if not review_id:
        raise QaVerificationBlockedError(
            "Task cannot be marked verified by generation alone — run an independent QA review first."
        )
    qa_row = db.get(QaReview, review_id)
    if qa_row is None or qa_row.project_id != task.project_id:
        raise QaVerificationBlockedError(
            "Referenced QA review does not exist for this project — run an independent QA review first."
        )
    if qa_row.task_id and qa_row.task_id != task.id:
        raise QaValidationError("Referenced QA review belongs to a different task.")

    open_issues = db.scalars(
        select(Issue).where(
            Issue.project_id == task.project_id,
            Issue.status != "closed",
        )
    ).all()
    relevant_open = [
        it for it in open_issues if it.task_id == task.id or it.qa_review_id == qa_row.id
    ]
    if relevant_open:
        task.verification_status = "qa_failed"
        db.commit()
        raise QaVerificationBlockedError(
            f"Task cannot be marked verified: {len(relevant_open)} open QA issue(s) remain unclosed "
            f"({', '.join(it.issue_number for it in relevant_open[:5])})."
        )

    snap = qa_row.qa_context_snapshot_json or {}
    inspected_total = (
        len(snap.get("inspected_boq_ids") or [])
        + len(snap.get("inspected_drawing_ids") or [])
        + len(snap.get("inspected_report_ids") or [])
        + len(snap.get("inspected_calculation_ids") or [])
        + len(snap.get("inspected_deliverable_ids") or [])
    )
    if qa_row.status == "no_evidence" or inspected_total == 0:
        if task.verification_status == "qa_passed":
            task.verification_status = "qa_failed"
            db.commit()
        raise QaVerificationBlockedError(
            "Task cannot be marked verified: the referenced QA review inspected zero artefacts "
            "(status: no_evidence). Produce deliverables and re-run independent QA first."
        )

    task_review_ids = set(
        db.scalars(
            select(QaReview.id).where(
                QaReview.project_id == task.project_id,
                QaReview.task_id == task.id,
            )
        ).all()
    )
    task_review_ids.add(qa_row.id)
    closed_issues = db.scalars(
        select(Issue).where(
            Issue.project_id == task.project_id,
            Issue.status == "closed",
            Issue.closed_at.is_not(None),
        )
    ).all()
    relevant_closed = [
        it
        for it in closed_issues
        if it.task_id == task.id or (it.qa_review_id and it.qa_review_id in task_review_ids)
    ]
    last_closed_at = max(
        (_as_utc(it.closed_at) for it in relevant_closed if it.closed_at is not None),
        default=None,
    )
    qa_created_at = _as_utc(qa_row.created_at)
    if last_closed_at is not None and qa_created_at is not None and qa_created_at <= last_closed_at:
        raise QaVerificationBlockedError(
            "Issues were closed after the last QA review — please re-run independent QA for this task "
            "before verifying."
        )

    if qa_row.status != "passed":
        raise QaVerificationBlockedError(
            f"Task cannot be marked verified because QA review status is '{qa_row.status}' — "
            "re-run independent QA until it passes."
        )

    task.verification_status = "verified"
    task.last_qa_review_id = qa_row.id
    db.add(
        AuditLog(
            project_id=task.project_id,
            action="task.qa_verified",
            entity_type="task",
            entity_id=task.id,
            actor="owner",
            details_json={
                "qa_review_id": qa_row.id,
                "verifier_note": payload.verifier_note,
            },
        )
    )
    db.commit()
    return TaskVerifyOut(
        task_id=task.id,
        verification_status=task.verification_status,
        qa_review_id=qa_row.id,
        open_issues_count=0,
        message=f"Task verified after independent QA review ({qa_row.id[:8]}) with 0 remaining open issues.",
    )


def list_project_qa_reviews(db: Session, project_id: str) -> QaReviewListResponse:
    """List independent QA review runs for a project newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(QaReview)
        .options(selectinload(QaReview.project), selectinload(QaReview.issues))
        .where(QaReview.project_id == project_id)
        .order_by(QaReview.created_at.desc())
    ).all()
    return QaReviewListResponse(
        reviews=[_to_qa_review_detail(r, db) for r in rows],
        total=len(rows),
    )


def get_qa_review_detail(db: Session, review_id: str) -> QaReviewDetailOut:
    """Return one QA review with its isolated context audit and associated issues."""
    row = db.scalar(
        select(QaReview)
        .options(selectinload(QaReview.project), selectinload(QaReview.issues))
        .where(QaReview.id == review_id)
    )
    if row is None:
        raise QaNotFoundError(f"QA review '{review_id}' was not found.")
    return _to_qa_review_detail(row, db)


def list_project_issues(
    db: Session,
    project_id: str,
    *,
    status_filter: str | None = None,
    severity_filter: str | None = None,
    task_id: str | None = None,
) -> IssueListResponse:
    """List issue register entries for a project cleanly ordered by issue number."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    all_rows = db.scalars(
        select(Issue)
        .where(Issue.project_id == project_id)
        .order_by(Issue.issue_number.asc(), Issue.created_at.asc())
    ).all()

    filtered = all_rows
    if status_filter and status_filter.strip():
        filtered = [r for r in filtered if r.status == status_filter.strip()]
    if severity_filter and severity_filter.strip():
        filtered = [r for r in filtered if r.severity == severity_filter.strip()]
    if task_id and task_id.strip():
        filtered = [r for r in filtered if r.task_id == task_id.strip()]

    open_cnt = sum(1 for r in all_rows if r.status != "closed")
    closed_cnt = sum(1 for r in all_rows if r.status == "closed")
    return IssueListResponse(
        issues=[_to_issue_out(r) for r in filtered],
        total=len(filtered),
        open_count=open_cnt,
        closed_count=closed_cnt,
    )


def create_manual_issue(
    db: Session,
    project_id: str,
    payload: IssueCreateRequest,
) -> IssueOut:
    """Create a manual QA issue register item cleanly assigned the next QA-NNN issue number."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    if payload.task_id:
        t = db.get(Task, payload.task_id)
        if t is None or t.project_id != project_id:
            raise QaValidationError(f"Task '{payload.task_id}' does not belong to project '{project_id}'.")

    issue_num = f"QA-{_next_issue_number(db, project_id):03d}"
    row = Issue(
        project_id=project.id,
        task_id=payload.task_id,
        deliverable_id=payload.deliverable_id,
        issue_number=issue_num,
        title=(payload.title or payload.description[:120]).strip(),
        description=payload.description.strip(),
        discipline=payload.discipline.strip(),
        severity=payload.severity,
        check_category=payload.check_category,
        reference=payload.reference.strip() if payload.reference else None,
        recommended_action=payload.corrective_action.strip(),
        status="open",
    )
    db.add(row)
    db.flush()
    if row.task_id:
        t_row = db.get(Task, row.task_id)
        if t_row is not None and t_row.verification_status in ("qa_passed", "verified"):
            t_row.verification_status = "qa_failed"

    db.add(
        AuditLog(
            project_id=project.id,
            action="issue.created",
            entity_type="issue",
            entity_id=row.id,
            actor="owner",
            details_json={"issue_number": issue_num, "severity": row.severity},
        )
    )
    db.commit()
    db.refresh(row)
    return _to_issue_out(row)


def update_issue(
    db: Session,
    issue_id: str,
    payload: IssueUpdateRequest,
) -> IssueOut:
    """Close, reopen, or update a QA issue register entry cleanly without promoting QA reviews to passed."""
    row = db.get(Issue, issue_id)
    if row is None:
        raise QaNotFoundError(f"QA issue '{issue_id}' was not found.")

    target_status = payload.status if payload.status is not None else row.status
    if target_status == "closed":
        if payload.closure_note is not None:
            cleaned_note = payload.closure_note.strip()
        elif row.status == "closed" and row.closure_note:
            cleaned_note = row.closure_note.strip()
        else:
            cleaned_note = ""
        if len(cleaned_note) < 10:
            raise QaValidationError(
                "Closing a QA issue requires a non-empty closure_note of at least 10 characters."
            )
        row.closure_note = cleaned_note
    elif payload.closure_note is not None:
        row.closure_note = payload.closure_note.strip() or None

    if payload.severity is not None:
        row.severity = payload.severity
    if payload.corrective_action is not None:
        row.recommended_action = payload.corrective_action.strip() or row.recommended_action

    if payload.status is not None:
        row.status = payload.status
        if payload.status == "closed":
            max_rev_raw = db.scalar(
                select(func.max(QaReview.created_at)).where(QaReview.project_id == row.project_id)
            )
            max_rev = _as_utc(max_rev_raw)
            closed_ts = utc_now()
            if max_rev is not None and closed_ts <= max_rev:
                closed_ts = max_rev + timedelta(microseconds=1)
            row.closed_at = closed_ts
            if row.task_id:
                t_row = db.get(Task, row.task_id)
                if t_row is not None and t_row.verification_status in ("qa_passed", "verified"):
                    t_row.verification_status = "qa_failed"
        else:
            row.closed_at = None
            row.closure_note = None
            if row.task_id:
                t_row = db.get(Task, row.task_id)
                if t_row is not None and t_row.verification_status in ("qa_passed", "verified"):
                    t_row.verification_status = "qa_failed"

    db.flush()

    if row.qa_review_id:
        qa_row = db.get(QaReview, row.qa_review_id)
        if qa_row is not None:
            open_for_review = len(
                db.scalars(
                    select(Issue).where(Issue.qa_review_id == qa_row.id, Issue.status != "closed")
                ).all()
            )
            qa_row.open_issues_count = open_for_review
            # Never flip qa_row.status to "passed" on closure; only a new QA re-run can pass.
            if open_for_review > 0 and qa_row.status == "passed":
                qa_row.status = "issues_found"

    db.add(
        AuditLog(
            project_id=row.project_id,
            action="issue.updated",
            entity_type="issue",
            entity_id=row.id,
            actor="owner",
            details_json={
                "issue_number": row.issue_number,
                "status": row.status,
                "closure_note": row.closure_note,
            },
        )
    )
    db.commit()
    db.refresh(row)
    return _to_issue_out(row)
