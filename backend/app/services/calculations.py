"""Step 13 deterministic engineering calculation service: validation, sourced references, persistence, and DOCX/PDF/XLSX export."""

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.base import utc_now
from app.db.models import AuditLog, Calculation, Deliverable, Project, ResearchSource, Task
from app.schemas.calculations import (
    CalculationCreateRequest,
    CalculationDetailOut,
    CalculationExportOut,
    CalculationExportRequest,
    CalculationListResponse,
    CalculationPresetListResponse,
    CalculationPresetOut,
    CalculationReferenceIn,
    CalculationReferenceOut,
    CalculationSummaryOut,
    CalculationUpdateRequest,
    VERIFY_CODE_LABEL,
)
from app.services.calc_export import (
    CalculationRenderData,
    generate_calculation_docx,
    generate_calculation_pdf,
    generate_calculation_xlsx,
    sha256_file,
)
from app.services.projects import ProjectNotFoundError
from app.services.review_reports import _to_deliverable_out
from app.services.workspace import resolve_project_file_path
from app.skills.calculations import (
    CalculationEvaluation,
    CalculationInputError,
    evaluate_calculation,
    get_synthetic_calculation_presets,
)

_URL_RE = re.compile(r"https?://[^\s,;\"')>\]]+", re.IGNORECASE)


class CalculationNotFoundError(LookupError):
    """Raised when a requested calculation ID does not exist."""


class CalculationValidationError(ValueError):
    """Raised when calculation inputs or standards references violate engineering rules."""


def _safe_filename_slug(name: str, default: str = "calculation") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name.strip()).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:48] or default


def _validate_and_normalize_references(
    db: Session,
    project_id: str,
    refs: list[CalculationReferenceIn],
) -> tuple[list[dict[str, Any]], str]:
    """Enforce Step 13 reference rule: only owner-supplied or verified source-log references, labelled 'verify against the locally adopted code'."""
    if not refs:
        raise CalculationValidationError(
            "At least one owner-supplied or verified source-log reference is required."
        )

    proj_sources = db.scalars(
        select(ResearchSource).where(ResearchSource.project_id == project_id)
    ).all()
    by_id = {s.id: s for s in proj_sources}
    reviewed_urls = {
        s.url.strip().lower(): s
        for s in proj_sources
        if s.reviewed and s.access_status in ("accessible", "owner_provided")
    }
    all_urls = {s.url.strip().lower(): s for s in proj_sources if s.url}

    normalized: list[dict[str, Any]] = []
    text_lines: list[str] = []

    for r in refs:
        s_name = r.source_name.strip()
        s_ref = r.source_ref.strip()
        if len(s_name) < 2 or len(s_ref) < 2:
            raise CalculationValidationError("Reference source_name and source_ref cannot be blank.")

        matched_rs: ResearchSource | None = None
        if r.source_kind == "verified_source_log":
            if r.research_source_id:
                matched_rs = by_id.get(r.research_source_id)
                if matched_rs is None:
                    raise CalculationValidationError(
                        f"Referenced ResearchSource ID '{r.research_source_id}' does not exist in this project."
                    )
            else:
                matched_rs = all_urls.get(s_ref.lower())
                if matched_rs is None:
                    for url_key, rs_obj in all_urls.items():
                        if url_key and url_key in s_ref.lower():
                            matched_rs = rs_obj
                            break
            if matched_rs is None:
                raise CalculationValidationError(
                    f"Reference '{s_ref}' is not present in this project's verified ResearchSource log."
                )
            if not matched_rs.reviewed or matched_rs.access_status not in ("accessible", "owner_provided"):
                raise CalculationValidationError(
                    f"Blocked unreviewed or inaccessible source '{matched_rs.source_name}' ({matched_rs.url})."
                )
            pub_date = r.publication_date or matched_rs.publication_date
            resolved_id = matched_rs.id
        else:
            # owner_supplied: block arbitrary unreviewed HTTP URLs pretending to be owner-supplied
            for found_url in _URL_RE.findall(s_ref):
                if found_url.strip().lower() not in reviewed_urls:
                    raise CalculationValidationError(
                        f"URL '{found_url}' in owner_supplied reference is not a reviewed project ResearchSource."
                    )
            pub_date = r.publication_date
            resolved_id = None

        entry = CalculationReferenceOut(
            source_kind=r.source_kind,
            source_name=s_name,
            source_ref=s_ref,
            research_source_id=resolved_id,
            publication_date=pub_date,
            notes=r.notes.strip() if r.notes else None,
            verification_label=VERIFY_CODE_LABEL,
        ).model_dump()
        normalized.append(entry)
        text_lines.append(
            f"[{r.source_kind}] {s_name}: {s_ref}"
            + (f" ({pub_date})" if pub_date else "")
            + f" — {VERIFY_CODE_LABEL}"
        )

    return normalized, "\n".join(text_lines)


def _split_lines(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _to_summary_out(row: Calculation) -> CalculationSummaryOut:
    return CalculationSummaryOut(
        id=row.id,
        project_id=row.project_id,
        project_code=row.project.code if row.project else "",
        project_name=row.project.name if row.project else "",
        task_id=row.task_id,
        title=row.title,
        discipline=row.discipline,
        calculation_type=row.calculation_type,
        language=row.language,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=row.export_version,
        status=row.status,
        acceptance_passed=bool(row.acceptance_passed),
        tokens_used=int(row.tokens_used or 0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail_out(row: Calculation) -> CalculationDetailOut:
    summary = _to_summary_out(row)
    raw_refs = list(row.references_json or [])
    refs_out = [CalculationReferenceOut.model_validate(item) for item in raw_refs]
    delivs = sorted(list(row.deliverables or []), key=lambda d: (d.version, d.format), reverse=True)
    return CalculationDetailOut(
        **summary.model_dump(),
        inputs=dict(row.inputs_json or {}),
        units={str(k): str(v) for k, v in (row.units_json or {}).items()},
        equations=row.equations or "",
        method=row.methodology or "",
        assumptions=_split_lines(row.assumptions),
        assumptions_text=row.assumptions or "",
        results=dict(row.results_json or {}),
        acceptance_criteria=_split_lines(row.acceptance_criteria),
        acceptance_criteria_text=row.acceptance_criteria or "",
        references=refs_out,
        references_text=row.references_text or "",
        deliverables=[_to_deliverable_out(d) for d in delivs],
    )


def _apply_evaluation_to_row(
    row: Calculation,
    ev: CalculationEvaluation,
    *,
    assumptions_override: list[str] | None,
) -> None:
    merged_assumptions = list(ev.assumptions)
    if assumptions_override:
        for extra in assumptions_override:
            cleaned = extra.strip()
            if cleaned and cleaned not in merged_assumptions:
                merged_assumptions.append(cleaned)

    row.discipline = ev.discipline
    row.calculation_type = ev.calculation_type
    row.inputs_json = ev.inputs
    row.units_json = ev.units
    row.equations = ev.equations
    row.methodology = ev.method
    row.assumptions = "\n".join(merged_assumptions)
    row.results_json = ev.results
    row.acceptance_criteria = "\n".join(ev.acceptance_criteria)
    row.acceptance_passed = bool(ev.acceptance_passed)
    row.tokens_used = 0


def create_calculation(
    db: Session,
    project_id: str,
    payload: CalculationCreateRequest,
) -> CalculationDetailOut:
    """Create and execute a deterministic Step 13 calculation (0 AI tokens)."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    if payload.task_id:
        task_row = db.get(Task, payload.task_id)
        if task_row is None or task_row.project_id != project_id:
            raise CalculationValidationError(
                f"Task '{payload.task_id}' does not belong to project '{project_id}'."
            )

    refs_json, refs_text = _validate_and_normalize_references(db, project_id, payload.references)

    try:
        ev = evaluate_calculation(payload.calculation_type, payload.inputs)
    except (CalculationInputError, ValueError) as exc:
        raise CalculationValidationError(str(exc)) from exc

    row = Calculation(
        project_id=project.id,
        task_id=payload.task_id,
        title=payload.title,
        discipline=ev.discipline,
        calculation_type=ev.calculation_type,
        inputs_json=ev.inputs,
        units_json=ev.units,
        equations=ev.equations,
        methodology=ev.method,
        assumptions="",
        results_json=ev.results,
        acceptance_criteria="",
        references_text=refs_text,
        references_json=refs_json,
        revision=payload.revision,
        version=1,
        export_version=0,
        language=payload.language,
        acceptance_passed=ev.acceptance_passed,
        tokens_used=0,
        classification=payload.classification,
        status="computed",
    )
    _apply_evaluation_to_row(row, ev, assumptions_override=payload.assumptions_override)
    db.add(row)
    db.flush()

    db.add(
        AuditLog(
            project_id=project.id,
            action="calculation.created",
            entity_type="calculation",
            entity_id=row.id,
            actor="calc_engine",
            details_json={
                "calculation_type": row.calculation_type,
                "discipline": row.discipline,
                "acceptance_passed": row.acceptance_passed,
                "tokens_used": 0,
            },
        )
    )
    db.commit()
    db.expire_all()
    return get_calculation_detail(db, row.id)


def update_calculation(
    db: Session,
    calculation_id: str,
    payload: CalculationUpdateRequest,
) -> CalculationDetailOut:
    """Update inputs, metadata, or references and deterministically recompute."""
    row = db.scalar(
        select(Calculation)
        .options(selectinload(Calculation.project), selectinload(Calculation.deliverables))
        .where(Calculation.id == calculation_id)
    )
    if row is None:
        raise CalculationNotFoundError(f"Calculation '{calculation_id}' was not found.")

    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.language is not None:
        row.language = payload.language
    if payload.classification is not None:
        row.classification = payload.classification
    if payload.revision is not None:
        row.revision = payload.revision.strip()
    if payload.references is not None:
        refs_json, refs_text = _validate_and_normalize_references(db, row.project_id, payload.references)
        row.references_json = refs_json
        row.references_text = refs_text

    target_inputs = payload.inputs if payload.inputs is not None else dict(row.inputs_json or {})
    try:
        ev = evaluate_calculation(row.calculation_type, target_inputs)
    except (CalculationInputError, ValueError) as exc:
        raise CalculationValidationError(str(exc)) from exc

    _apply_evaluation_to_row(row, ev, assumptions_override=payload.assumptions_override)
    row.version = int(row.version or 1) + 1
    row.status = "computed"

    db.add(
        AuditLog(
            project_id=row.project_id,
            action="calculation.updated",
            entity_type="calculation",
            entity_id=row.id,
            actor="calc_engine",
            details_json={
                "version": row.version,
                "acceptance_passed": row.acceptance_passed,
                "tokens_used": 0,
            },
        )
    )
    db.commit()
    db.expire_all()
    return get_calculation_detail(db, row.id)


def list_project_calculations(db: Session, project_id: str) -> CalculationListResponse:
    """List deterministic project calculations newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(Calculation)
        .options(selectinload(Calculation.project))
        .where(Calculation.project_id == project_id)
        .order_by(Calculation.created_at.desc())
    ).all()
    return CalculationListResponse(
        calculations=[_to_summary_out(r) for r in rows],
        total=len(rows),
    )


def get_calculation_detail(db: Session, calculation_id: str) -> CalculationDetailOut:
    """Fetch complete details for one calculation."""
    row = db.scalar(
        select(Calculation)
        .options(selectinload(Calculation.project), selectinload(Calculation.deliverables))
        .where(Calculation.id == calculation_id)
    )
    if row is None:
        raise CalculationNotFoundError(f"Calculation '{calculation_id}' was not found.")
    return _to_detail_out(row)


def list_calculation_presets() -> CalculationPresetListResponse:
    """Return all synthetic electrical & plumbing calculation examples (zero client data)."""
    raw = get_synthetic_calculation_presets()
    return CalculationPresetListResponse(
        presets=[CalculationPresetOut.model_validate(p) for p in raw]
    )


def export_calculation_deliverables(
    db: Session,
    settings: Settings,
    calculation_id: str,
    payload: CalculationExportRequest | None = None,
) -> CalculationExportOut:
    """Export immutable versioned DOCX, PDF, and XLSX calculation deliverables into 04_Engineering_Calculations."""
    opts = payload or CalculationExportRequest()
    row = db.scalar(
        select(Calculation)
        .options(selectinload(Calculation.project), selectinload(Calculation.deliverables))
        .where(Calculation.id == calculation_id)
    )
    if row is None:
        raise CalculationNotFoundError(f"Calculation '{calculation_id}' was not found.")

    next_export = int(row.export_version or 0) + 1
    export_lang = opts.language or ("en" if row.language == "en" else "ar")
    short_id = row.id.replace("-", "")[:8]
    slug = _safe_filename_slug(row.title, default="calculation")

    rel_docx = f"04_Engineering_Calculations/{slug}_{short_id}_v{next_export}.docx"
    rel_pdf = f"04_Engineering_Calculations/{slug}_{short_id}_v{next_export}.pdf"
    rel_xlsx = f"04_Engineering_Calculations/{slug}_{short_id}_v{next_export}.xlsx"
    rel_json = f"04_Engineering_Calculations/{slug}_{short_id}_v{next_export}.json"

    ws_slug = row.project.workspace_slug
    path_docx = resolve_project_file_path(settings.workspaces_dir, ws_slug, rel_docx)
    path_pdf = resolve_project_file_path(settings.workspaces_dir, ws_slug, rel_pdf)
    path_xlsx = resolve_project_file_path(settings.workspaces_dir, ws_slug, rel_xlsx)
    path_json = resolve_project_file_path(settings.workspaces_dir, ws_slug, rel_json)

    for p in (path_docx, path_pdf, path_xlsx, path_json):
        if p.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing calculation export file: {p.name}"
            )

    render_data = CalculationRenderData(
        project_code=row.project.code,
        project_name=row.project.name,
        title=row.title,
        discipline=row.discipline,
        calculation_type=row.calculation_type,
        language=export_lang,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        export_version=next_export,
        issued_at_iso=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        inputs=dict(row.inputs_json or {}),
        units={str(k): str(v) for k, v in (row.units_json or {}).items()},
        equations=row.equations or "",
        method=row.methodology or "",
        assumptions=_split_lines(row.assumptions),
        results=dict(row.results_json or {}),
        acceptance_criteria=_split_lines(row.acceptance_criteria),
        acceptance_passed=bool(row.acceptance_passed),
        references=list(row.references_json or []),
    )

    generate_calculation_docx(path_docx, render_data)
    generate_calculation_pdf(path_pdf, render_data)
    generate_calculation_xlsx(path_xlsx, render_data)
    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(
        json.dumps(
            {
                "calculation_id": row.id,
                "calculation_type": row.calculation_type,
                "discipline": row.discipline,
                "classification": row.classification,
                "version": row.version,
                "export_version": next_export,
                "inputs": render_data.inputs,
                "units": render_data.units,
                "results": render_data.results,
                "acceptance_passed": render_data.acceptance_passed,
                "references": render_data.references,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    row.export_version = next_export
    row.status = "exported"

    mime_docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    specs = (
        ("docx", mime_docx, rel_docx, path_docx),
        ("pdf", "application/pdf", rel_pdf, path_pdf),
        ("xlsx", mime_xlsx, rel_xlsx, path_xlsx),
    )
    created_delivs: dict[str, Deliverable] = {}
    for fmt, mime, rel_p, disk_p in specs:
        d_row = Deliverable(
            project_id=row.project_id,
            task_id=row.task_id,
            calculation_id=row.id,
            title=f"{row.title} (v{next_export} {fmt.upper()})",
            deliverable_type="engineering_calculation",
            discipline=row.discipline,
            format=fmt,
            classification=row.classification,
            status="issued",
            version=next_export,
            folder_name="04_Engineering_Calculations",
            filename=disk_p.name,
            relative_path=rel_p,
            mime_type=mime,
            size_bytes=disk_p.stat().st_size,
            sha256=sha256_file(disk_p),
            summary=f"{row.calculation_type} deterministic calculation export ({'PASS' if row.acceptance_passed else 'FAIL'}).",
        )
        db.add(d_row)
        created_delivs[fmt] = d_row

    db.flush()
    db.add(
        AuditLog(
            project_id=row.project_id,
            action="calculation.exported",
            entity_type="calculation",
            entity_id=row.id,
            actor="calc_engine",
            details_json={
                "export_version": next_export,
                "docx": rel_docx,
                "pdf": rel_pdf,
                "xlsx": rel_xlsx,
            },
        )
    )
    db.commit()
    db.expire_all()
    detail = get_calculation_detail(db, row.id)
    by_id = {d.id: d for d in detail.deliverables}
    return CalculationExportOut(
        calculation=detail,
        docx_deliverable=by_id[created_delivs["docx"].id],
        pdf_deliverable=by_id[created_delivs["pdf"].id],
        xlsx_deliverable=by_id[created_delivs["xlsx"].id],
    )
