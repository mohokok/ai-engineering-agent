"""Step 14 technical specifications service: deterministic BOQ/drawing mapping, optional AI draft gating, SHA-256 versioned DOCX/PDF exports."""

import json
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.base import new_uuid, utc_now
from app.db.models import AuditLog, BoqSheet, Deliverable, ParametricDrawing, Project, ResearchSource, Specification, Task
from app.providers.base import TokenUsage
from app.providers.secrets import SecretStore
from app.schemas.reports import ReportLanguage
from app.schemas.specifications import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    SpecSection,
    SpecificationApproveRequest,
    SpecificationDetailOut,
    SpecificationExportOut,
    SpecificationExportRequest,
    SpecificationGenerateRequest,
    SpecificationListResponse,
    SpecificationPresetListResponse,
    SpecificationPresetOut,
    SpecificationSummaryOut,
)
from app.schemas.tasks import TaskTokenUsageOut
from app.services.calc_export import sha256_file
from app.services.projects import ProjectNotFoundError
from app.services.review_reports import _to_deliverable_out
from app.services.spec_export import SpecificationRenderData, generate_specification_docx, generate_specification_pdf
from app.services.workspace import resolve_project_file_path
from app.skills.specifications import (
    SpecificationInputError,
    build_deterministic_specification_sections,
    draft_specification_prose_with_ai,
)


class SpecificationNotFoundError(LookupError):
    """Raised when a requested specification ID does not exist."""


class SpecificationValidationError(ValueError):
    """Raised when specification generation inputs, mappings, or sources violate rules."""


def _ai_draft_label(ai_draft_status: str, language: str, approved_by: str | None) -> str:
    if ai_draft_status == "unverified_ai_draft":
        return AI_UNVERIFIED_DRAFT_LABEL_AR if language == "ar" else AI_UNVERIFIED_DRAFT_LABEL_EN
    if ai_draft_status == "owner_approved":
        who = approved_by or "Owner"
        return (
            f"مسودة ذكاء اصطناعي مُعتمدة من المالك ({who})"
            if language == "ar"
            else f"AI Draft — Owner Approved ({who})"
        )
    return "قالب حتمي مرتبط بالمصادر (0 توكن)" if language == "ar" else "Deterministic Template Path (0 AI tokens)"


def _to_summary_out(row: Specification) -> SpecificationSummaryOut:
    payload = row.structured_payload_json if isinstance(row.structured_payload_json, dict) else {}
    raw_sections = payload.get("sections") or []
    clauses_cnt = sum(len(s.get("clauses") or []) for s in raw_sections if isinstance(s, dict))
    return SpecificationSummaryOut(
        id=row.id,
        project_id=row.project_id,
        project_code=row.project.code if row.project else "",
        project_name=row.project.name if row.project else "",
        task_id=row.task_id,
        title=row.title,
        discipline=row.discipline,
        language=row.language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=row.export_version,
        status=row.status,
        use_ai=bool(row.use_ai),
        ai_draft_status=row.ai_draft_status,
        ai_draft_label=_ai_draft_label(row.ai_draft_status, row.language, row.owner_approved_by),
        owner_approved_by=row.owner_approved_by,
        owner_approved_at=row.owner_approved_at,
        sections_count=len(raw_sections),
        clauses_count=clauses_cnt,
        tokens_used=int(row.tokens_used or 0),
        summary=row.summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail_out(row: Specification) -> SpecificationDetailOut:
    summary_out = _to_summary_out(row)
    payload = row.structured_payload_json if isinstance(row.structured_payload_json, dict) else {}
    sections = [SpecSection.model_validate(s) for s in (payload.get("sections") or [])]
    raw_usage = row.token_usage_json if isinstance(row.token_usage_json, dict) else {}
    delivs = sorted(list(row.deliverables or []), key=lambda d: (d.version, d.format), reverse=True)
    return SpecificationDetailOut(
        **summary_out.model_dump(),
        source_boq_sheet_ids=[str(x) for x in (payload.get("source_boq_sheet_ids") or [])],
        source_drawing_ids=[str(x) for x in (payload.get("source_drawing_ids") or [])],
        source_research_ids=[str(x) for x in (payload.get("source_research_ids") or [])],
        missing_standards_notices=[str(x) for x in (payload.get("missing_standards_notices") or [])],
        sections=sections,
        token_usage=TaskTokenUsageOut(
            prompt_tokens=int(raw_usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(raw_usage.get("output_tokens", 0) or 0),
            total_tokens=int(raw_usage.get("total_tokens", 0) or 0),
            thoughts_tokens=int(raw_usage.get("thoughts_tokens", 0) or 0),
            cached_tokens=int(raw_usage.get("cached_tokens", 0) or 0),
        ),
        deliverables=[_to_deliverable_out(d) for d in delivs],
    )


def _write_versioned_spec_files(
    db: Session,
    settings: Settings,
    *,
    project: Project,
    row: Specification,
    language: ReportLanguage,
    export_ver: int,
) -> tuple[Deliverable, Deliverable]:
    payload = row.structured_payload_json if isinstance(row.structured_payload_json, dict) else {}
    sections = [SpecSection.model_validate(s) for s in (payload.get("sections") or [])]

    short_id = row.id.replace("-", "")[:8]
    rel_docx = f"07_Technical_Specifications/spec_{short_id}_v{row.version}_e{export_ver}_{language}.docx"
    rel_pdf = f"07_Technical_Specifications/spec_{short_id}_v{row.version}_e{export_ver}_{language}.pdf"
    rel_json = f"07_Technical_Specifications/spec_{short_id}_v{row.version}_e{export_ver}_{language}.json"

    path_docx = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_docx)
    path_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_pdf)
    path_json = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_json)

    for target in (path_docx, path_pdf, path_json):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite existing specification deliverable: {target.name}")

    render_data = SpecificationRenderData(
        project_code=project.code,
        project_name=project.name,
        title=row.title,
        discipline=row.discipline,
        language=language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=export_ver,
        issued_at_iso=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        use_ai=bool(row.use_ai),
        ai_draft_status=row.ai_draft_status,
        owner_approved_by=row.owner_approved_by,
        owner_approved_at_iso=row.owner_approved_at.isoformat() if row.owner_approved_at else None,
        summary=row.summary or "",
        source_boq_sheet_ids=[str(x) for x in (payload.get("source_boq_sheet_ids") or [])],
        source_drawing_ids=[str(x) for x in (payload.get("source_drawing_ids") or [])],
        source_research_ids=[str(x) for x in (payload.get("source_research_ids") or [])],
        missing_standards_notices=[str(x) for x in (payload.get("missing_standards_notices") or [])],
        sections=sections,
    )

    generate_specification_docx(path_docx, render_data)
    generate_specification_pdf(path_pdf, render_data)
    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(
        json.dumps(
            {
                "specification_id": row.id,
                "project_id": project.id,
                "title": row.title,
                "discipline": row.discipline,
                "language": language,
                "classification": row.classification,
                "version": row.version,
                "export_version": export_ver,
                "use_ai": row.use_ai,
                "ai_draft_status": row.ai_draft_status,
                "owner_approved_by": row.owner_approved_by,
                "structured_payload": payload,
                "files": {
                    "docx": {"relative_path": rel_docx, "sha256": sha256_file(path_docx)},
                    "pdf": {"relative_path": rel_pdf, "sha256": sha256_file(path_pdf)},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    mime_docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    deliv_docx = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        specification_id=row.id,
        title=f"{row.title} ({row.revision} v{export_ver} — DOCX {language.upper()})",
        deliverable_type="technical_specification",
        discipline=row.discipline,
        format="docx",
        classification=row.classification,
        status="issued",
        version=export_ver,
        folder_name="07_Technical_Specifications",
        filename=path_docx.name,
        relative_path=rel_docx,
        mime_type=mime_docx,
        size_bytes=path_docx.stat().st_size,
        sha256=sha256_file(path_docx),
        summary=row.summary,
    )
    deliv_pdf = Deliverable(
        project_id=project.id,
        task_id=row.task_id,
        specification_id=row.id,
        title=f"{row.title} ({row.revision} v{export_ver} — PDF {language.upper()})",
        deliverable_type="technical_specification",
        discipline=row.discipline,
        format="pdf",
        classification=row.classification,
        status="issued",
        version=export_ver,
        folder_name="07_Technical_Specifications",
        filename=path_pdf.name,
        relative_path=rel_pdf,
        mime_type="application/pdf",
        size_bytes=path_pdf.stat().st_size,
        sha256=sha256_file(path_pdf),
        summary=row.summary,
    )
    db.add(deliv_docx)
    db.add(deliv_pdf)
    db.flush()
    return deliv_docx, deliv_pdf


def list_specification_presets() -> SpecificationPresetListResponse:
    """Return synthetic clinic specification fixture examples (0% client data)."""
    presets = [
        SpecificationPresetOut(
            key="clinic_mep_and_arch_ar",
            title_en="Synthetic Clinic Technical Specifications Package (Arabic RTL)",
            title_ar="مواصفات فنية متكاملة لمشروع العيادة النموذجي (عربي RTL)",
            description_en="Synthetic fixture blueprint connecting clinic BOQ items, A-101 parametric schedules, and reviewed source-log citations.",
            description_ar="نموذج اصطناعي يربط بنود جدول الكميات وجداول المخطط البارامتري A-101 بمصادر البحث المراجَعة.",
            discipline="multidisciplinary",
            boq_items=[
                {"item_no": "A-01", "description": "Flush HPL timber door 1000x2100mm with hydraulic closer", "unit": "nos", "quantity": 5, "drawing_reference": "A-101"},
                {"item_no": "W-01", "description": "Double-glazed thermally broken aluminum window 1500x1200mm", "unit": "nos", "quantity": 4, "drawing_reference": "A-101"},
                {"item_no": "F-01", "description": "Non-slip porcelain floor tiling 600x600mm", "unit": "m2", "quantity": 80, "drawing_reference": "A-101"},
                {"item_no": "E-01", "description": "Main distribution panel MDB-CLINIC-01 with MCCB feeders", "unit": "nos", "quantity": 1},
                {"item_no": "P-01", "description": "PPR PN20 SDR 6 cold water supply riser piping DN63", "unit": "m", "quantity": 35},
            ],
            drawing_summary={"drawing_no": "A-101", "schedules": ["door_schedule", "window_schedule", "finish_schedule"]},
            reviewed_source={"source_name": "Synthetic Electrical & Plumbing Reference Guide", "access_status": "accessible", "reviewed": True},
            request_defaults=SpecificationGenerateRequest(
                title="المواصفات الفنية لمشروع العيادة النموذجي",
                discipline="multidisciplinary",
                language="ar",
                classification="For Review",
                use_ai=False,
            ),
        ),
        SpecificationPresetOut(
            key="clinic_mep_and_arch_en",
            title_en="Synthetic Clinic Technical Specifications Package (English LTR)",
            title_ar="المواصفات الفنية لمشروع العيادة (إنجليزي LTR)",
            description_en="English LTR traceable specification template derived solely from synthetic BOQs, A-101 schedules, and source logs.",
            description_ar="قالب مواصفات إنجليزي قابل للتتبع الكامل من جدول الكميات ومخطط A-101.",
            discipline="multidisciplinary",
            boq_items=[
                {"item_no": "E-01", "description": "Main distribution panel MDB-CLINIC-01 with 400V 3-phase busbars", "unit": "nos", "quantity": 1},
                {"item_no": "P-01", "description": "PPR PN20 SDR 6 potable cold water pipe DN63", "unit": "m", "quantity": 35},
            ],
            drawing_summary={"drawing_no": "A-101", "schedules": ["door_schedule", "window_schedule", "finish_schedule"]},
            reviewed_source={"source_name": "Synthetic MEP Engineering Reference", "access_status": "accessible", "reviewed": True},
            request_defaults=SpecificationGenerateRequest(
                title="Clinic Architectural & MEP Technical Specifications",
                discipline="multidisciplinary",
                language="en",
                classification="For Review",
                use_ai=False,
            ),
        ),
    ]
    return SpecificationPresetListResponse(presets=presets)


def generate_project_specification(
    db: Session,
    settings: Settings,
    secret_store: SecretStore,
    project_id: str,
    payload: SpecificationGenerateRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> SpecificationDetailOut:
    """Generate a traceable technical specification package from project BOQ items, drawing schedules, and verified sources."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    if payload.task_id:
        task_row = db.get(Task, payload.task_id)
        if task_row is None or task_row.project_id != project_id:
            raise SpecificationValidationError(f"Task '{payload.task_id}' does not belong to project '{project_id}'.")

    # 1. Load project BOQ sheets & items
    boq_query = (
        select(BoqSheet)
        .options(selectinload(BoqSheet.items))
        .where(BoqSheet.project_id == project_id)
        .order_by(BoqSheet.created_at.desc())
    )
    all_boqs = db.scalars(boq_query).all()
    if payload.boq_sheet_ids:
        by_bid = {b.id: b for b in all_boqs}
        selected_boqs = []
        for bid in payload.boq_sheet_ids:
            b_obj = by_bid.get(bid)
            if b_obj is None:
                raise SpecificationValidationError(f"BOQ sheet '{bid}' was not found in project '{project_id}'.")
            selected_boqs.append(b_obj)
    else:
        selected_boqs = list(all_boqs)

    boq_dicts = [
        {
            "id": b.id,
            "title": b.title,
            "items": [
                {
                    "id": it.id,
                    "row_order": it.row_order,
                    "item_no": it.item_no,
                    "description": it.description,
                    "unit": it.unit,
                    "quantity": it.quantity,
                    "technical_reference": it.technical_reference,
                    "drawing_reference": it.drawing_reference,
                    "remarks": it.remarks,
                    "verification_status": it.verification_status,
                    "discipline": it.discipline,
                    "layer_or_category": it.layer_or_category,
                }
                for it in b.items
            ],
        }
        for b in selected_boqs
    ]

    # 2. Load Parametric Drawings & schedules
    all_drawings = db.scalars(
        select(ParametricDrawing)
        .where(ParametricDrawing.project_id == project_id)
        .order_by(ParametricDrawing.created_at.desc())
    ).all()
    if payload.drawing_ids:
        by_did = {d.id: d for d in all_drawings}
        selected_drawings = []
        for did in payload.drawing_ids:
            d_obj = by_did.get(did)
            if d_obj is None:
                raise SpecificationValidationError(f"Parametric drawing '{did}' was not found in project '{project_id}'.")
            selected_drawings.append(d_obj)
    else:
        selected_drawings = list(all_drawings)

    drawing_dicts = [
        {
            "id": d.id,
            "drawing_no": d.drawing_no,
            "title": d.title,
            "units": d.units,
            "computed_metrics_json": dict(d.computed_metrics_json or {}),
        }
        for d in selected_drawings
    ]

    # 3. Load reviewed ResearchSources strictly (NEVER allow unreviewed/inaccessible sources as standards)
    all_sources = db.scalars(
        select(ResearchSource).where(ResearchSource.project_id == project_id)
    ).all()
    by_sid = {s.id: s for s in all_sources}
    if payload.research_source_ids:
        chosen_sources: list[ResearchSource] = []
        for sid in payload.research_source_ids:
            rs_obj = by_sid.get(sid)
            if rs_obj is None:
                raise SpecificationValidationError(f"ResearchSource '{sid}' does not belong to project '{project_id}'.")
            if not rs_obj.reviewed or rs_obj.access_status not in ("accessible", "owner_provided"):
                raise SpecificationValidationError(
                    f"Blocked unreviewed or inaccessible ResearchSource '{rs_obj.source_name}' ({rs_obj.url}). "
                    "Only reviewed sources may back specifications."
                )
            chosen_sources.append(rs_obj)
    else:
        chosen_sources = [
            s for s in all_sources if s.reviewed and s.access_status in ("accessible", "owner_provided")
        ]

    reviewed_source_dicts = [
        {
            "id": s.id,
            "source_name": s.source_name,
            "url": s.url,
            "publication_date": s.publication_date,
            "relevant_info": s.relevant_info,
            "query_text": s.query_text,
            "source_priority_tier": s.source_priority_tier,
        }
        for s in chosen_sources
    ]

    try:
        sections, missing_notices, meta = build_deterministic_specification_sections(
            boq_sheets=boq_dicts,
            drawings=drawing_dicts,
            reviewed_sources=reviewed_source_dicts,
            language=payload.language,
        )
    except SpecificationInputError as exc:
        raise SpecificationValidationError(str(exc)) from exc

    is_ar = payload.language == "ar"
    default_title = (
        f"المواصفات الفنية للمشروع — {project.name}"
        if is_ar
        else f"Technical Specifications Package — {project.code}"
    )
    spec_title = payload.title or default_title
    summary_text = (
        f"مواصفات فنية حتمية (0 توكن) تضم {len(sections)} قسم(أقسام) مربوطة بـ "
        f"{len(meta['source_boq_sheet_ids'])} جدول كميات و{len(meta['source_drawing_ids'])} مخطط بارامتري "
        f"و{len(meta['source_research_ids'])} مصدر بحثي موثق."
        if is_ar
        else (
            f"Deterministic specification package (0 AI tokens) covering {len(sections)} section(s) mapped to "
            f"{len(meta['source_boq_sheet_ids'])} BOQ sheet(s), {len(meta['source_drawing_ids'])} parametric drawing(s), "
            f"and {len(meta['source_research_ids'])} reviewed source-log reference(s)."
        )
    )

    usage = TokenUsage()
    ai_draft_status = "not_used"
    row_status = "generated"
    if payload.use_ai:
        ai_sum, sections, usage, _est, _chars = draft_specification_prose_with_ai(
            db,
            secret_store,
            project_id=project.id,
            project_code=project.code,
            project_name=project.name,
            language=payload.language,
            sections=sections,
            reviewed_sources=reviewed_source_dicts,
            complexity=payload.complexity,
            client_factory=client_factory,
            task_id=payload.task_id,
        )
        if ai_sum:
            summary_text = ai_sum
        else:
            prefix = f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] " if is_ar else f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] "
            summary_text = f"{prefix}{summary_text}"
        ai_draft_status = "unverified_ai_draft"
        row_status = "ai_draft_unverified"

    max_ver = db.scalar(
        select(func.coalesce(func.max(Specification.version), 0)).where(
            Specification.project_id == project.id
        )
    )
    version = int(max_ver or 0) + 1
    revision = f"Rev {version:02d}"
    spec_id = new_uuid()

    payload_dict: dict[str, Any] = {
        "source_boq_sheet_ids": meta["source_boq_sheet_ids"],
        "source_drawing_ids": meta["source_drawing_ids"],
        "source_research_ids": meta["source_research_ids"],
        "reviewed_sources_available": meta["reviewed_sources_available"],
        "missing_standards_notices": missing_notices,
        "sections": [s.model_dump() for s in sections],
        "change_note": payload.change_note or ("Initial specification package" if version == 1 else "Regenerated specification package"),
    }

    row = Specification(
        id=spec_id,
        project_id=project.id,
        task_id=payload.task_id,
        title=spec_title,
        discipline=payload.discipline,
        language=payload.language,
        classification=payload.classification,
        revision=revision,
        version=version,
        export_version=1,
        status=row_status,
        use_ai=payload.use_ai,
        ai_draft_status=ai_draft_status,
        tokens_used=usage.total_tokens,
        token_usage_json={
            "prompt_tokens": usage.prompt_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "thoughts_tokens": usage.thoughts_tokens,
            "cached_tokens": usage.cached_tokens,
        },
        structured_payload_json=payload_dict,
        summary=summary_text,
    )
    db.add(row)
    db.flush()

    deliv_docx, deliv_pdf = _write_versioned_spec_files(
        db,
        settings,
        project=project,
        row=row,
        language=payload.language,
        export_ver=1,
    )

    db.add(
        AuditLog(
            project_id=project.id,
            action="spec.generated",
            entity_type="specification",
            entity_id=row.id,
            actor="specifications_skill",
            details_json={
                "version": version,
                "language": payload.language,
                "classification": payload.classification,
                "use_ai": payload.use_ai,
                "ai_draft_status": ai_draft_status,
                "tokens_used": usage.total_tokens,
                "sections_count": len(sections),
                "docx_sha256": deliv_docx.sha256,
                "pdf_sha256": deliv_pdf.sha256,
            },
        )
    )
    db.commit()
    return get_specification_detail(db, row.id)


def list_project_specifications(db: Session, project_id: str) -> SpecificationListResponse:
    """List persisted project specifications ordered newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(Specification)
        .options(selectinload(Specification.project))
        .where(Specification.project_id == project_id)
        .order_by(Specification.created_at.desc(), Specification.version.desc())
    ).all()
    items = [_to_summary_out(r) for r in rows]
    return SpecificationListResponse(specifications=items, total=len(items))


def get_specification_detail(db: Session, spec_id: str) -> SpecificationDetailOut:
    """Retrieve complete Step 14 specification sections, traces, and deliverables."""
    row = db.scalar(
        select(Specification)
        .options(selectinload(Specification.project), selectinload(Specification.deliverables))
        .where(Specification.id == spec_id)
    )
    if row is None:
        raise SpecificationNotFoundError(f"Specification '{spec_id}' was not found.")
    return _to_detail_out(row)


def approve_specification_draft(
    db: Session,
    settings: Settings,
    spec_id: str,
    payload: SpecificationApproveRequest,
) -> SpecificationDetailOut:
    """Explicit owner sign-off transitioning an unverified AI draft specification to owner_approved."""
    row = db.scalar(
        select(Specification)
        .options(selectinload(Specification.project), selectinload(Specification.deliverables))
        .where(Specification.id == spec_id)
    )
    if row is None:
        raise SpecificationNotFoundError(f"Specification '{spec_id}' was not found.")

    approved_by = (payload.approved_by or "Owner").strip()
    now_ts = utc_now()
    row.ai_draft_status = "owner_approved"
    row.owner_approved_by = approved_by
    row.owner_approved_at = now_ts
    row.status = "owner_approved"

    structured = dict(row.structured_payload_json or {})
    new_sections: list[dict[str, Any]] = []
    for raw_sec in structured.get("sections") or []:
        sec_dict = dict(raw_sec)
        new_clauses: list[dict[str, Any]] = []
        for raw_cl in sec_dict.get("clauses") or []:
            cl_dict = dict(raw_cl)
            if cl_dict.get("draft_origin") == "ai_unverified_draft":
                cl_dict["draft_origin"] = "owner_approved"
            txt = str(cl_dict.get("text") or "")
            for lbl in (f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] ", f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] "):
                if txt.startswith(lbl):
                    txt = txt[len(lbl):]
            cl_dict["text"] = txt
            new_clauses.append(cl_dict)
        sec_dict["clauses"] = new_clauses
        new_sections.append(sec_dict)
    structured["sections"] = new_sections
    if payload.approval_note:
        structured["approval_note"] = payload.approval_note
    row.structured_payload_json = structured

    sum_txt = str(row.summary or "")
    for lbl in (f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] ", f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] "):
        if sum_txt.startswith(lbl):
            sum_txt = sum_txt[len(lbl):]
    row.summary = sum_txt

    if payload.export_after_approval:
        next_export = int(row.export_version or 0) + 1
        row.export_version = next_export
        exp_lang: ReportLanguage = "ar" if row.language == "ar" else "en"
        _write_versioned_spec_files(
            db,
            settings,
            project=row.project,
            row=row,
            language=exp_lang,
            export_ver=next_export,
        )

    db.add(
        AuditLog(
            project_id=row.project_id,
            action="spec.owner_approved",
            entity_type="specification",
            entity_id=row.id,
            actor=approved_by,
            details_json={"approval_note": payload.approval_note, "export_version": row.export_version},
        )
    )
    db.commit()
    db.expire_all()
    return get_specification_detail(db, row.id)


def export_specification_deliverables(
    db: Session,
    settings: Settings,
    spec_id: str,
    payload: SpecificationExportRequest | None = None,
) -> SpecificationExportOut:
    """Export immutable versioned DOCX + PDF deliverables into 07_Technical_Specifications with SHA-256."""
    row = db.scalar(
        select(Specification)
        .options(selectinload(Specification.project), selectinload(Specification.deliverables))
        .where(Specification.id == spec_id)
    )
    if row is None:
        raise SpecificationNotFoundError(f"Specification '{spec_id}' was not found.")

    export_lang: ReportLanguage = (
        payload.language if payload and payload.language else ("ar" if row.language == "ar" else "en")
    )
    next_export = int(row.export_version or 0) + 1
    row.export_version = next_export
    if row.status == "generated":
        row.status = "exported"

    deliv_docx, deliv_pdf = _write_versioned_spec_files(
        db,
        settings,
        project=row.project,
        row=row,
        language=export_lang,
        export_ver=next_export,
    )

    db.add(
        AuditLog(
            project_id=row.project_id,
            action="spec.exported",
            entity_type="specification",
            entity_id=row.id,
            actor="specifications_skill",
            details_json={
                "export_version": next_export,
                "language": export_lang,
                "docx_sha256": deliv_docx.sha256,
                "pdf_sha256": deliv_pdf.sha256,
            },
        )
    )
    db.commit()
    db.expire_all()
    detail = get_specification_detail(db, row.id)
    return SpecificationExportOut(
        specification=detail,
        docx_deliverable=_to_deliverable_out(deliv_docx),
        pdf_deliverable=_to_deliverable_out(deliv_pdf),
    )
