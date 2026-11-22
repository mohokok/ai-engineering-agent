"""Step 09 persistence, versioning (08_Reports + 10_Final_Deliverables), and deliverable download service."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import AuditLog, Deliverable, Project, ReviewReport, Task
from app.providers.base import ProviderError, TaskComplexity, TokenUsage, sanitize_secret_text
from app.providers.secrets import SecretStore
from app.schemas.reports import (
    CategorizedStatement,
    DeliverableOut,
    DocumentRegisterEntry,
    OcrExtractedTextItem,
    ReportLanguage,
    ReviewFinding,
    ReviewReportDetailOut,
    ReviewReportGenerateRequest,
    ReviewReportSummaryOut,
    RevisionBlockOut,
    SourceLocationRef,
)
from app.schemas.tasks import TaskTokenUsageOut
from app.services.projects import ProjectNotFoundError
from app.services.provider_settings import _load_provider_config, _summarize_usage
from app.services.report_generator import (
    ReviewReportRenderData,
    generate_review_report_docx,
    generate_review_report_pdf,
)
from app.services.research import MAX_TOTAL_PROMPT_CHARS, estimate_prompt_tokens
from app.services.workspace import resolve_project_file_path, sanitize_workspace_stem
from app.skills.review import (
    CollectedEvidenceBundle,
    build_review_synthesis_prompt,
    collect_project_evidence_index,
    enhance_review_with_ai,
)


class DeliverableNotFoundError(LookupError):
    """Raised when a requested deliverable or review report ID does not exist."""


@dataclass(frozen=True)
class DeliverableDownloadFile:
    """Validated on-disk deliverable file metadata ready for streaming download."""

    deliverable: Deliverable
    path: Path
    media_type: str
    download_filename: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _safe_filename_slug(text: str, *, default: str, max_len: int = 48) -> str:
    stem = sanitize_workspace_stem(text, max_length=max_len)
    cleaned = re.sub(r"[^A-Za-z0-9\u0600-\u06FF_-]+", "_", stem).strip("_-")
    return cleaned or default


def _classification_slug(classification: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", classification).strip("_") or "Preliminary"


def _step04_remaining(db: Session | None) -> tuple[int | None, int | None]:
    if db is None:
        return None, None
    try:
        cfg = _load_provider_config(db)
        daily, monthly = _summarize_usage(db)
        return (
            max(0, cfg.usage_limits.daily_token_limit - daily.total_tokens),
            max(0, cfg.usage_limits.monthly_token_limit - monthly.total_tokens),
        )
    except Exception:
        return None, None


def _to_deliverable_out(row: Deliverable) -> DeliverableOut:
    return DeliverableOut(
        id=row.id,
        project_id=row.project_id,
        report_id=row.report_id,
        boq_id=row.boq_id,
        drawing_id=row.drawing_id,
        calculation_id=row.calculation_id,
        specification_id=row.specification_id,
        comparison_id=row.comparison_id,
        schedule_id=row.schedule_id,
        assessment_id=row.assessment_id,
        task_id=row.task_id,
        file_id=row.file_id,
        title=row.title,
        deliverable_type=row.deliverable_type,
        discipline=row.discipline,
        format=row.format,
        classification=row.classification,
        status=row.status,
        version=row.version,
        folder_name=row.folder_name,
        filename=row.filename,
        relative_path=row.relative_path,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        summary=row.summary,
        download_url=f"/api/deliverables/{row.id}/download",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_report_summary_out(
    row: ReviewReport,
    *,
    db: Session | None = None,
) -> ReviewReportSummaryOut:
    payload = row.structured_payload_json if isinstance(row.structured_payload_json, dict) else {}
    findings_raw = payload.get("findings") or []
    raw_usage = row.token_usage_json if isinstance(row.token_usage_json, dict) else {}
    usage = TokenUsage(
        prompt_tokens=int(raw_usage.get("prompt_tokens", 0) or 0),
        output_tokens=int(raw_usage.get("output_tokens", 0) or 0),
        total_tokens=int(raw_usage.get("total_tokens", 0) or 0),
        thoughts_tokens=int(raw_usage.get("thoughts_tokens", 0) or 0),
        cached_tokens=int(raw_usage.get("cached_tokens", 0) or 0),
    )
    daily_rem, monthly_rem = _step04_remaining(db)
    proj_code = row.project.code if row.project is not None else ""
    proj_name = row.project.name if row.project is not None else ""
    return ReviewReportSummaryOut(
        id=row.id,
        project_id=row.project_id,
        project_code=proj_code,
        project_name=proj_name,
        task_id=row.task_id,
        title=row.title,
        discipline=row.discipline,
        language=row.language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        status=row.status,
        summary=row.summary,
        findings_count=len(findings_raw),
        estimated_prompt_tokens=row.estimated_prompt_tokens,
        prompt_char_count=int(raw_usage.get("prompt_char_count", 0) or 0),
        prompt_char_cap=MAX_TOTAL_PROMPT_CHARS,
        step04_daily_tokens_remaining=daily_rem,
        step04_monthly_tokens_remaining=monthly_rem,
        token_usage=TaskTokenUsageOut(
            prompt_tokens=usage.prompt_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            thoughts_tokens=usage.thoughts_tokens,
            cached_tokens=usage.cached_tokens,
        ),
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_report_detail_out(row: ReviewReport, *, db: Session | None = None) -> ReviewReportDetailOut:
    summary_out = _to_report_summary_out(row, db=db)
    payload = row.structured_payload_json if isinstance(row.structured_payload_json, dict) else {}
    rev_raw = payload.get("revision_block")
    if isinstance(rev_raw, dict):
        revision_block = RevisionBlockOut.model_validate(rev_raw)
    else:
        revision_block = RevisionBlockOut(
            version=row.version,
            revision=row.revision,
            classification=row.classification,
            prepared_by="Engineering Agent (Orchestrator + Review Skill)",
            review_notice="Advisory engineering output — not construction-ready without licensed engineer sign-off.",
            issued_at_iso=row.created_at.isoformat(),
            change_note="Initial review generation",
            source_files_count=0,
            reviewed_research_count=0,
        )
    deliverables_sorted = sorted(
        list(row.deliverables),
        key=lambda d: (d.folder_name or "", d.format),
    )
    raw_vf = [CategorizedStatement.model_validate(s) for s in (payload.get("verified_facts") or [])]
    raw_all_vf = [
        CategorizedStatement.model_validate(s)
        for s in (payload.get("appendix_verified_facts") or payload.get("verified_facts") or [])
    ]
    raw_ocr = [
        OcrExtractedTextItem.model_validate(o) for o in (payload.get("ocr_text_items") or [])
    ]
    vf_total = int(payload.get("verified_facts_total", len(raw_all_vf)) or 0)
    vf_shown = int(payload.get("verified_facts_shown", len(raw_vf)) or 0)
    is_inv_only = bool(payload.get("is_inventory_only", row.status != "ai_enhanced"))
    return ReviewReportDetailOut(
        **summary_out.model_dump(),
        is_inventory_only=is_inv_only,
        revision_block=revision_block,
        document_register=[
            DocumentRegisterEntry.model_validate(r) for r in (payload.get("document_register") or [])
        ],
        findings=[ReviewFinding.model_validate(f) for f in (payload.get("findings") or [])],
        verified_facts=raw_vf,
        verified_facts_total=vf_total,
        verified_facts_shown=vf_shown,
        appendix_verified_facts=raw_all_vf,
        ocr_text_items=raw_ocr,
        ocr_text_items_total=len(raw_ocr),
        calculated_items=[
            CategorizedStatement.model_validate(s) for s in (payload.get("calculated_items") or [])
        ],
        assumptions=[
            CategorizedStatement.model_validate(s) for s in (payload.get("assumptions") or [])
        ],
        recommendations=[
            CategorizedStatement.model_validate(s) for s in (payload.get("recommendations") or [])
        ],
        gaps_or_unextracted=[str(g) for g in (payload.get("gaps_or_unextracted") or [])],
        source_registry=[
            SourceLocationRef.model_validate(r) for r in (payload.get("source_registry") or [])
        ],
        deliverables=[_to_deliverable_out(d) for d in deliverables_sorted],
    )


def _default_summary_without_ai(
    project: Project,
    bundle: CollectedEvidenceBundle,
    *,
    language: ReportLanguage,
    classification: str,
) -> str:
    if language == "ar":
        return (
            f"تقرير جرد وفحص استخراج حتمي (ليس مراجعة هندسية فنية) للمشروع [{project.code}] {project.name} (التصنيف: {classification}). "
            f"تم جرد {bundle.source_files_count} ملف(ات) و{bundle.reviewed_research_count} مصدر بحثي مراجَع بـ 0 توكن، "
            f"وتسجيل {len(bundle.findings)} ملاحظة فنية فعلية و{bundle.verified_facts_total} حقيقة حتمية ({bundle.verified_facts_shown} معروضة في الملخص و{len(bundle.ocr_text_items)} نص OCR غير مُتحقَّق منه)."
        )
    return (
        f"Deterministic extraction inventory & technical check (NOT an engineering design review) for [{project.code}] {project.name} "
        f"(Classification: {classification}). Inventoried {bundle.source_files_count} file(s) and "
        f"{bundle.reviewed_research_count} reviewed research source(s) at 0 AI tokens, flagging {len(bundle.findings)} concrete issue(s) "
        f"and {bundle.verified_facts_total} deterministic fact(s) (showing {bundle.verified_facts_shown} of {bundle.verified_facts_total}; {len(bundle.ocr_text_items)} unverified OCR segment(s))."
    )


def _write_versioned_report_files(
    db: Session,
    settings: Settings,
    *,
    project: Project,
    report_row: ReviewReport,
    render_data: ReviewReportRenderData,
    payload_dict: dict[str, Any],
) -> None:
    """Write immutable versioned DOCX, PDF, and JSON files into 08_Reports and 10_Final_Deliverables."""
    short_id = report_row.id.replace("-", "")[:8]
    ver = report_row.version
    title_slug = _safe_filename_slug(report_row.title, default="review_report")
    cls_slug = _classification_slug(report_row.classification)

    # 08_Reports working deliverables + JSON provenance log
    rel_08_docx = f"08_Reports/review_{short_id}_v{ver}.docx"
    rel_08_pdf = f"08_Reports/review_{short_id}_v{ver}.pdf"
    rel_08_json = f"08_Reports/review_{short_id}_v{ver}.json"

    # 10_Final_Deliverables client-ready deliverables
    rel_10_docx = f"10_Final_Deliverables/{title_slug}_{short_id}_v{ver}_{cls_slug}.docx"
    rel_10_pdf = f"10_Final_Deliverables/{title_slug}_{short_id}_v{ver}_{cls_slug}.pdf"

    path_08_docx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_08_docx)
    path_08_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_08_pdf)
    path_08_json = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_08_json)
    path_10_docx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_10_docx)
    path_10_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_10_pdf)

    for target in (path_08_docx, path_08_pdf, path_08_json, path_10_docx, path_10_pdf):
        if target.exists():
            raise FileExistsError(f"Deliverable version path already exists (refusing overwrite): {target.name}")

    generate_review_report_docx(path_08_docx, render_data)
    generate_review_report_pdf(path_08_pdf, render_data)
    generate_review_report_docx(path_10_docx, render_data)
    generate_review_report_pdf(path_10_pdf, render_data)
    path_08_json.parent.mkdir(parents=True, exist_ok=True)
    path_08_json.write_text(json.dumps(payload_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    mime_docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    specs = [
        ("08_Reports", "review_report_working", "docx", mime_docx, rel_08_docx, path_08_docx),
        ("08_Reports", "review_report_working", "pdf", "application/pdf", rel_08_pdf, path_08_pdf),
        ("10_Final_Deliverables", "review_report", "docx", mime_docx, rel_10_docx, path_10_docx),
        ("10_Final_Deliverables", "review_report", "pdf", "application/pdf", rel_10_pdf, path_10_pdf),
    ]
    for folder_name, deliv_type, fmt, mime, rel_path, disk_path in specs:
        db.add(
            Deliverable(
                project_id=project.id,
                task_id=report_row.task_id,
                report_id=report_row.id,
                title=f"{report_row.title} ({report_row.revision} — {folder_name})",
                deliverable_type=deliv_type,
                discipline=report_row.discipline,
                format=fmt,
                classification=report_row.classification,
                status="issued",
                version=ver,
                folder_name=folder_name,
                filename=disk_path.name,
                relative_path=rel_path,
                mime_type=mime,
                size_bytes=disk_path.stat().st_size,
                sha256=_sha256_file(disk_path),
                summary=report_row.summary,
            )
        )


def _persist_report_version(
    db: Session,
    settings: Settings,
    *,
    project: Project,
    task_id: str | None,
    title: str,
    discipline: str,
    language: ReportLanguage,
    classification: str,
    change_note: str | None,
    file_ids: list[str],
    research_run_ids: list[str],
    review_notes: str | None,
    bundle: CollectedEvidenceBundle,
    summary_text: str,
    usage: TokenUsage,
    est_tokens: int,
    prompt_char_count: int,
    status_label: str,
) -> str:
    max_ver = db.scalar(
        select(func.coalesce(func.max(ReviewReport.version), 0)).where(
            ReviewReport.project_id == project.id
        )
    )
    version = int(max_ver or 0) + 1
    revision = f"Rev {version:02d}"
    report_id = new_uuid()
    issued_at_iso = datetime.now(timezone.utc).isoformat()

    default_v1_note = "Initial extraction and research review issue"
    raw_change_note = (change_note or "").strip() if change_note is not None else ""
    if version <= 1:
        resolved_change_note = raw_change_note or default_v1_note
    elif not raw_change_note or raw_change_note == default_v1_note:
        resolved_change_note = (
            "Regenerated from current extractions (AI-enhanced)"
            if status_label == "ai_enhanced"
            else "Regenerated from current extractions"
        )
    else:
        resolved_change_note = raw_change_note

    is_inventory_only = status_label != "ai_enhanced"
    notice = (
        (
            "تقرير جرد وفحص حتمي فقط — ليس مراجعة هندسية فنية أو اعتماداً للتنفيذ."
            if is_inventory_only
            else "مخرج استشاري مدعوم بالذكاء الاصطناعي — لا يُعتمد للتنفيذ دون مراجعة وتوقيع مهندس مرخص."
        )
        if language == "ar"
        else (
            "Deterministic file inventory & automated technical check — NOT an engineering design review."
            if is_inventory_only
            else "AI-assisted advisory output — not construction-ready without licensed engineer sign-off."
        )
    )
    revision_block = RevisionBlockOut(
        version=version,
        revision=revision,
        classification=classification,
        prepared_by=(
            "Engineering Agent (Deterministic Inventory & Check — 0 AI tokens)"
            if is_inventory_only
            else "Engineering Agent (Orchestrator + Review Skill — AI Enhanced)"
        ),
        review_notice=notice,
        issued_at_iso=issued_at_iso,
        change_note=resolved_change_note,
        source_files_count=bundle.source_files_count,
        reviewed_research_count=bundle.reviewed_research_count,
    )

    payload_dict: dict[str, Any] = {
        "is_inventory_only": is_inventory_only,
        "revision_block": revision_block.model_dump(),
        "document_register": [r.model_dump() for r in bundle.document_register],
        "findings": [f.model_dump() for f in bundle.findings],
        "verified_facts": [s.model_dump() for s in bundle.verified_facts],
        "verified_facts_total": bundle.verified_facts_total,
        "verified_facts_shown": bundle.verified_facts_shown,
        "appendix_verified_facts": [s.model_dump() for s in bundle.all_verified_facts],
        "ocr_text_items": [o.model_dump() for o in bundle.ocr_text_items],
        "calculated_items": [s.model_dump() for s in bundle.calculated_items],
        "assumptions": [s.model_dump() for s in bundle.assumptions],
        "recommendations": [s.model_dump() for s in bundle.recommendations],
        "gaps_or_unextracted": list(bundle.gaps_or_unextracted),
        "source_registry": [r.model_dump() for r in bundle.source_registry],
        "input_scope": {
            "file_ids": list(file_ids),
            "research_run_ids": list(research_run_ids),
            "review_notes": review_notes,
        },
    }

    report_row = ReviewReport(
        id=report_id,
        project_id=project.id,
        task_id=task_id,
        title=title,
        discipline=discipline,
        language=language,
        classification=classification,
        revision=revision,
        version=version,
        status=status_label,
        summary=summary_text,
        structured_payload_json=payload_dict,
        token_usage_json={
            "prompt_tokens": usage.prompt_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "thoughts_tokens": usage.thoughts_tokens,
            "cached_tokens": usage.cached_tokens,
            "prompt_char_count": prompt_char_count,
        },
        estimated_prompt_tokens=est_tokens,
    )
    db.add(report_row)
    db.flush()

    render_data = ReviewReportRenderData(
        project_code=project.code,
        project_name=project.name,
        client_name=project.client_name,
        location=project.location,
        title=title,
        discipline=discipline,
        language=language,
        classification=classification,
        is_inventory_only=is_inventory_only,
        summary=summary_text,
        revision_block=revision_block,
        document_register=list(bundle.document_register),
        findings=list(bundle.findings),
        verified_facts=list(bundle.verified_facts),
        verified_facts_total=bundle.verified_facts_total,
        verified_facts_shown=bundle.verified_facts_shown,
        appendix_verified_facts=list(bundle.all_verified_facts),
        ocr_text_items=list(bundle.ocr_text_items),
        calculated_items=list(bundle.calculated_items),
        assumptions=list(bundle.assumptions),
        recommendations=list(bundle.recommendations),
        gaps_or_unextracted=list(bundle.gaps_or_unextracted),
        source_registry=list(bundle.source_registry),
    )
    _write_versioned_report_files(
        db,
        settings,
        project=project,
        report_row=report_row,
        render_data=render_data,
        payload_dict=payload_dict,
    )
    return report_id


def generate_project_review_report(
    db: Session,
    settings: Settings,
    secret_store: SecretStore,
    project_id: str,
    payload: ReviewReportGenerateRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> ReviewReportDetailOut:
    """Review extracted files & research log, separate categories, and emit versioned DOCX + PDF deliverables."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    if payload.task_id:
        task_row = db.get(Task, payload.task_id)
        if task_row is None:
            raise ProjectNotFoundError(f"Task '{payload.task_id}' was not found.")

    default_title = (
        f"تقرير المراجعة الهندسية — {project.name}"
        if payload.language == "ar"
        else f"Engineering Review Findings Report — {project.code}"
    )
    report_title = payload.title or default_title

    bundle = collect_project_evidence_index(
        db,
        settings,
        project,
        file_ids=payload.file_ids,
        research_run_ids=payload.research_run_ids,
        language=payload.language,
        review_notes=payload.review_notes,
    )
    preview_prompt = build_review_synthesis_prompt(
        project,
        bundle,
        discipline=payload.discipline,
        language=payload.language,
        review_notes=payload.review_notes,
    )
    est_tokens = estimate_prompt_tokens(preview_prompt) if bundle.source_registry else 0
    prompt_chars = len(preview_prompt) if bundle.source_registry else 0
    usage = TokenUsage()
    status_label = "generated"
    summary_text = _default_summary_without_ai(
        project,
        bundle,
        language=payload.language,
        classification=payload.classification,
    )

    if payload.use_ai:
        try:
            summary_text, bundle, usage, est_tokens, prompt_chars = enhance_review_with_ai(
                db,
                secret_store,
                project=project,
                bundle=bundle,
                discipline=payload.discipline,
                language=payload.language,
                classification=payload.classification,
                review_notes=payload.review_notes,
                complexity=payload.complexity,
                client_factory=client_factory,
                task_id=payload.task_id,
            )
            status_label = "ai_enhanced" if usage.total_tokens > 0 or bundle.source_registry else "generated"
        except ProviderError as exc:
            err_msg = sanitize_secret_text(str(exc))
            max_ver = db.scalar(
                select(func.coalesce(func.max(ReviewReport.version), 0)).where(
                    ReviewReport.project_id == project.id
                )
            )
            fail_ver = int(max_ver or 0) + 1
            fail_id = new_uuid()
            db.add(
                ReviewReport(
                    id=fail_id,
                    project_id=project.id,
                    task_id=payload.task_id,
                    title=report_title,
                    discipline=payload.discipline,
                    language=payload.language,
                    classification=payload.classification,
                    revision=f"Rev {fail_ver:02d}",
                    version=fail_ver,
                    status="failed",
                    error_message=err_msg,
                    estimated_prompt_tokens=est_tokens,
                    token_usage_json={"prompt_char_count": prompt_chars},
                )
            )
            db.add(
                AuditLog(
                    project_id=project.id,
                    action="report.failed",
                    entity_type="review_report",
                    entity_id=fail_id,
                    actor="review_skill",
                    details_json={"error": err_msg, "classification": payload.classification},
                )
            )
            db.commit()
            raise

    report_id = _persist_report_version(
        db,
        settings,
        project=project,
        task_id=payload.task_id,
        title=report_title,
        discipline=payload.discipline,
        language=payload.language,
        classification=payload.classification,
        change_note=payload.change_note,
        file_ids=payload.file_ids,
        research_run_ids=payload.research_run_ids,
        review_notes=payload.review_notes,
        bundle=bundle,
        summary_text=summary_text,
        usage=usage,
        est_tokens=est_tokens,
        prompt_char_count=prompt_chars,
        status_label=status_label,
    )
    db.add(
        AuditLog(
            project_id=project.id,
            action="report.generated",
            entity_type="review_report",
            entity_id=report_id,
            actor="review_skill",
            details_json={
                "classification": payload.classification,
                "language": payload.language,
                "findings_count": len(bundle.findings),
                "estimated_prompt_tokens": est_tokens,
                "total_tokens": usage.total_tokens,
            },
        )
    )
    db.commit()
    return get_review_report_detail(db, report_id)


def enhance_existing_report_with_ai(
    db: Session,
    settings: Settings,
    secret_store: SecretStore,
    report_id: str,
    *,
    complexity: TaskComplexity = "fast",
    client_factory: Callable[[str], Any] | None = None,
) -> ReviewReportDetailOut:
    """Create a NEW versioned DOCX+PDF revision of an existing report enhanced with capped Gemini synthesis."""
    base_row = db.scalar(
        select(ReviewReport)
        .options(selectinload(ReviewReport.project))
        .where(ReviewReport.id == report_id)
    )
    if base_row is None:
        raise DeliverableNotFoundError(f"Review report '{report_id}' was not found.")
    project = base_row.project
    payload_meta = (
        base_row.structured_payload_json.get("input_scope", {})
        if isinstance(base_row.structured_payload_json, dict)
        else {}
    )
    file_ids = list(payload_meta.get("file_ids") or [])
    research_run_ids = list(payload_meta.get("research_run_ids") or [])
    review_notes = payload_meta.get("review_notes")
    lang: ReportLanguage = "en" if base_row.language == "en" else "ar"

    bundle = collect_project_evidence_index(
        db,
        settings,
        project,
        file_ids=file_ids,
        research_run_ids=research_run_ids,
        language=lang,
        review_notes=review_notes,
    )
    summary_text, bundle, usage, est_tokens, prompt_chars = enhance_review_with_ai(
        db,
        secret_store,
        project=project,
        bundle=bundle,
        discipline=base_row.discipline,
        language=lang,
        classification=base_row.classification,
        review_notes=review_notes,
        complexity=complexity,
        client_factory=client_factory,
        task_id=base_row.task_id,
    )

    new_report_id = _persist_report_version(
        db,
        settings,
        project=project,
        task_id=base_row.task_id,
        title=base_row.title,
        discipline=base_row.discipline,
        language=lang,
        classification=base_row.classification,
        change_note=f"AI-enhanced revision derived cleanly from {base_row.revision} (strictly source-linked).",
        file_ids=file_ids,
        research_run_ids=research_run_ids,
        review_notes=review_notes,
        bundle=bundle,
        summary_text=summary_text,
        usage=usage,
        est_tokens=est_tokens,
        prompt_char_count=prompt_chars,
        status_label="ai_enhanced",
    )
    db.add(
        AuditLog(
            project_id=project.id,
            action="report.ai_enhanced",
            entity_type="review_report",
            entity_id=new_report_id,
            actor="review_skill",
            details_json={
                "source_report_id": report_id,
                "estimated_prompt_tokens": est_tokens,
                "total_tokens": usage.total_tokens,
            },
        )
    )
    db.commit()
    return get_review_report_detail(db, new_report_id)


def list_project_review_reports(db: Session, project_id: str) -> list[ReviewReportSummaryOut]:
    """List persisted review reports for a project ordered newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(ReviewReport)
        .options(selectinload(ReviewReport.project))
        .where(ReviewReport.project_id == project_id)
        .order_by(ReviewReport.version.desc(), ReviewReport.created_at.desc())
    ).all()
    return [_to_report_summary_out(r, db=db) for r in rows]


def get_review_report_detail(db: Session, report_id: str) -> ReviewReportDetailOut:
    """Return full report findings, separated categories, source links, and deliverables."""
    row = db.scalar(
        select(ReviewReport)
        .options(selectinload(ReviewReport.project), selectinload(ReviewReport.deliverables))
        .where(ReviewReport.id == report_id)
    )
    if row is None:
        raise DeliverableNotFoundError(f"Review report '{report_id}' was not found.")
    return _to_report_detail_out(row, db=db)


def list_deliverables(
    db: Session,
    *,
    project_id: str | None = None,
    folder_name: str | None = None,
    file_format: str | None = None,
) -> list[DeliverableOut]:
    """List persisted deliverables ordered newest first."""
    if project_id:
        project = db.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    stmt = select(Deliverable).order_by(Deliverable.created_at.desc(), Deliverable.version.desc())
    if project_id:
        stmt = stmt.where(Deliverable.project_id == project_id)
    if folder_name:
        stmt = stmt.where(Deliverable.folder_name == folder_name)
    if file_format:
        stmt = stmt.where(Deliverable.format == file_format)
    rows = db.scalars(stmt).all()
    return [_to_deliverable_out(r) for r in rows]


def resolve_deliverable_download(
    db: Session,
    settings: Settings,
    deliverable_id: str,
) -> DeliverableDownloadFile:
    """Resolve and verify SHA-256 integrity of a downloadable deliverable file."""
    row = db.scalar(
        select(Deliverable)
        .options(selectinload(Deliverable.project))
        .where(Deliverable.id == deliverable_id)
    )
    if row is None:
        raise DeliverableNotFoundError(f"Deliverable '{deliverable_id}' was not found.")
    if not row.relative_path or row.project is None:
        raise DeliverableNotFoundError(f"Deliverable '{deliverable_id}' has no downloadable file on disk.")

    disk_path = resolve_project_file_path(
        settings.workspaces_dir,
        row.project.workspace_slug,
        row.relative_path,
    )
    if not disk_path.is_file():
        raise DeliverableNotFoundError(f"Deliverable file is missing on disk: {row.filename or row.relative_path}")

    actual_sha = _sha256_file(disk_path)
    if row.sha256 and actual_sha != row.sha256:
        raise ValueError(
            f"Deliverable integrity mismatch for '{disk_path.name}' (expected {row.sha256[:12]}, got {actual_sha[:12]})."
        )

    db.add(
        AuditLog(
            project_id=row.project_id,
            action="deliverable.downloaded",
            entity_type="deliverable",
            entity_id=row.id,
            actor="owner",
            details_json={"filename": disk_path.name, "folder_name": row.folder_name, "version": row.version},
        )
    )
    db.commit()
    return DeliverableDownloadFile(
        deliverable=row,
        path=disk_path,
        media_type=row.mime_type or "application/octet-stream",
        download_filename=row.filename or disk_path.name,
    )
