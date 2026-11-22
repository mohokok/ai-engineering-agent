"""Step 17 owner-supplied / licensed standards library service: file ingestion + SHA-256, suggestion confirmation, supersession, search, and register exports."""

from pathlib import Path
import re
from typing import Any, Callable

from fastapi import UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import new_uuid, utc_now
from app.db.models import (
    AuditLog,
    Calculation,
    Project,
    ProjectSchedule,
    ReviewReport,
    Specification,
    StandardDocument,
    TechnicalComparison,
)
from app.providers.base import TaskComplexity
from app.providers.secrets import SecretStore
from app.schemas.standards import (
    AI_UNVERIFIED_SUGGESTION_LABEL_AR,
    AI_UNVERIFIED_SUGGESTION_LABEL_EN,
    MAX_EXCERPT_CHARS,
    OwnerExcerptIn,
    OwnerExcerptOut,
    StandardConfirmRequest,
    StandardCreateRequest,
    StandardDocumentOut,
    StandardListResponse,
    StandardPresetListResponse,
    StandardRegisterExportFileOut,
    StandardRegisterExportOut,
    StandardRegisterExportRequest,
    StandardSupersedeRequest,
    StandardUpdateRequest,
    UPLOADED_UNCONFIRMED_LABEL_AR,
    UPLOADED_UNCONFIRMED_LABEL_EN,
)
from app.schemas.tasks import TaskTokenUsageOut
from app.services.calc_export import sha256_file
from app.services.files import (
    EmptyFileError,
    FileTooLargeError,
    UnsafeFilenameError,
    UnsupportedFileTypeError,
    _set_read_only,
    validate_upload_filename,
)
from app.services.projects import ProjectNotFoundError
from app.services.standards_export import (
    StandardsRegisterRenderData,
    generate_standards_register_docx,
    generate_standards_register_pdf,
    generate_standards_register_xlsx,
)
from app.services.workspace import resolve_project_file_path
from app.skills.standards import (
    StandardInputError,
    extract_bounded_header_text,
    find_citations_for_standard,
    get_synthetic_standards_presets,
    resolve_supersession_chain,
    suggest_metadata_deterministically,
    suggest_metadata_with_ai,
    validate_no_supersession_cycle,
)

_ALLOWED_STANDARD_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"}


class StandardNotFoundError(LookupError):
    """Raised when a requested standards library ID does not exist."""


class StandardValidationError(ValueError):
    """Raised when excerpts, supersession links, file uploads, or project scopes violate Step 17 rules."""


def _metadata_label(metadata_status: str, ai_status: str) -> str:
    if metadata_status == "unverified_ai_suggestion" or ai_status == "unverified_ai_suggestion":
        return f"{AI_UNVERIFIED_SUGGESTION_LABEL_EN} / {AI_UNVERIFIED_SUGGESTION_LABEL_AR}"
    if metadata_status == "unverified_suggestion":
        return f"{UPLOADED_UNCONFIRMED_LABEL_EN} / {UPLOADED_UNCONFIRMED_LABEL_AR}"
    if metadata_status == "owner_confirmed":
        return "Owner Confirmed"
    return "Owner Entered"


def _normalize_excerpts(excerpts: list[OwnerExcerptIn]) -> list[dict[str, Any]]:
    now_iso = utc_now().isoformat()
    out: list[dict[str, Any]] = []
    for ex in excerpts:
        txt = ex.text.strip()
        if len(txt) > MAX_EXCERPT_CHARS:
            raise StandardValidationError(
                f"Excerpt text exceeds {MAX_EXCERPT_CHARS} characters (copyright guard)."
            )
        out.append(
            {
                "excerpt_id": ex.excerpt_id or new_uuid()[:8],
                "page_ref": ex.page_ref.strip(),
                "text": txt,
                "added_at": now_iso,
            }
        )
    return out


def _snapshot_entry(row: StandardDocument, *, note: str, actor: str) -> dict[str, Any]:
    return {
        "version": row.version,
        "timestamp": utc_now().isoformat(),
        "actor": actor,
        "note": note,
        "standard_number": row.standard_number,
        "title": row.title,
        "edition_year": row.edition_year,
        "status": row.status,
        "superseded_by_id": row.superseded_by_id,
        "adopted_locally": row.adopted_locally,
        "metadata_status": row.metadata_status,
        "file_sha256": row.file_sha256,
    }


def _load_citation_context(
    db: Session,
    *,
    project_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load real project deliverables cleanly for cross-module citation indexing."""
    q_sp = select(Specification)
    q_calc = select(Calculation)
    q_cmp = select(TechnicalComparison)
    q_rep = select(ReviewReport)
    q_sch = select(ProjectSchedule)
    if project_id:
        q_sp = q_sp.where(Specification.project_id == project_id)
        q_calc = q_calc.where(Calculation.project_id == project_id)
        q_cmp = q_cmp.where(TechnicalComparison.project_id == project_id)
        q_rep = q_rep.where(ReviewReport.project_id == project_id)
        q_sch = q_sch.where(ProjectSchedule.project_id == project_id)

    specs = [
        {
            "id": s.id,
            "project_id": s.project_id,
            "title": s.title,
            "sections": list((s.structured_payload_json or {}).get("sections") or []),
        }
        for s in db.scalars(q_sp).all()
    ]
    calcs = [
        {
            "id": c.id,
            "project_id": c.project_id,
            "title": c.title,
            "references_text": c.references_text or "",
            "references_json": list(c.references_json or []),
        }
        for c in db.scalars(q_calc).all()
    ]
    cmps = [
        {
            "id": m.id,
            "project_id": m.project_id,
            "title": m.title,
            "criteria_json": list(m.criteria_json or []),
            "options_json": list(m.options_json or []),
        }
        for m in db.scalars(q_cmp).all()
    ]
    reps = [
        {
            "id": r.id,
            "project_id": r.project_id,
            "title": r.title,
            "findings": list((r.structured_payload_json or {}).get("findings") or []),
            "verified_facts": list((r.structured_payload_json or {}).get("verified_facts") or []),
            "source_registry": list((r.structured_payload_json or {}).get("source_registry") or []),
        }
        for r in db.scalars(q_rep).all()
    ]
    scheds = [
        {
            "id": sc.id,
            "project_id": sc.project_id,
            "title": sc.title,
            "activities_json": list(sc.activities_json or []),
        }
        for sc in db.scalars(q_sch).all()
    ]
    return specs, calcs, cmps, reps, scheds


def _serialize_standards(
    db: Session,
    rows: list[StandardDocument],
    *,
    project_id_for_citations: str | None = None,
) -> list[StandardDocumentOut]:
    all_rows = db.scalars(select(StandardDocument)).all()
    docs_by_id = {
        r.id: {
            "id": r.id,
            "standard_number": r.standard_number,
            "title": r.title,
            "edition_year": r.edition_year,
            "status": r.status,
            "superseded_by_id": r.superseded_by_id,
        }
        for r in all_rows
    }

    specs, calcs, cmps, reps, scheds = _load_citation_context(db, project_id=project_id_for_citations)

    out: list[StandardDocumentOut] = []
    for row in rows:
        imm_num, imm_title, chain_sum = resolve_supersession_chain(std_id=row.id, docs_by_id=docs_by_id)
        doc_dict = {
            "id": row.id,
            "standard_number": row.standard_number,
            "status": row.status,
            "edition_year": row.edition_year,
            "metadata_status": row.metadata_status,
        }
        target_pid = row.project_id or project_id_for_citations
        sp_sub = [x for x in specs if not target_pid or x["project_id"] == target_pid]
        ca_sub = [x for x in calcs if not target_pid or x["project_id"] == target_pid]
        cm_sub = [x for x in cmps if not target_pid or x["project_id"] == target_pid]
        rp_sub = [x for x in reps if not target_pid or x["project_id"] == target_pid]
        sc_sub = [x for x in scheds if not target_pid or x["project_id"] == target_pid]

        hits, warnings = find_citations_for_standard(
            std_doc=doc_dict,
            specifications=sp_sub,
            calculations=ca_sub,
            comparisons=cm_sub,
            review_reports=rp_sub,
            schedules=sc_sub,
        )
        raw_usage = row.token_usage_json if isinstance(row.token_usage_json, dict) else {}
        usage = TaskTokenUsageOut(
            prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
            output_tokens=int(raw_usage.get("output_tokens") or 0),
            total_tokens=int(raw_usage.get("total_tokens") or row.tokens_used or 0),
            thoughts_tokens=int(raw_usage.get("thoughts_tokens") or 0),
            cached_tokens=int(raw_usage.get("cached_tokens") or 0),
        )
        out.append(
            StandardDocumentOut(
                id=row.id,
                project_id=row.project_id,
                standard_number=row.standard_number,
                title=row.title,
                issuing_body=row.issuing_body,
                edition_year=row.edition_year,
                status=row.status,
                superseded_by_id=row.superseded_by_id,
                superseded_by_number=imm_num,
                superseded_by_title=imm_title,
                replacement_chain_summary=chain_sum,
                supersession_note=row.supersession_note,
                jurisdiction=row.jurisdiction,
                adopted_locally=bool(row.adopted_locally),
                owner_notes=row.owner_notes,
                owner_excerpts=[OwnerExcerptOut.model_validate(e) for e in (row.owner_excerpts_json or [])],
                metadata_status=row.metadata_status,
                metadata_label=_metadata_label(row.metadata_status, row.ai_suggestion_status),
                suggested_metadata=row.suggested_metadata_json,
                use_ai=bool(row.use_ai),
                ai_suggestion_status=row.ai_suggestion_status,
                tokens_used=int(row.tokens_used or 0),
                token_usage=usage,
                original_filename=row.original_filename,
                file_relative_path=row.file_relative_path,
                file_sha256=row.file_sha256,
                file_size_bytes=row.file_size_bytes,
                mime_type=row.mime_type,
                version=row.version,
                history=list(row.history_json or []),
                where_cited=hits,
                citation_warnings=warnings,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return out


def _resolve_library_dir(settings: Settings, *, project: Project | None) -> Path:
    if project is not None:
        return resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, "11_References")
    root = settings.workspaces_dir / "_standards_library"
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_standard_entry(
    db: Session,
    payload: StandardCreateRequest,
) -> StandardDocumentOut:
    """Register an owner-entered standard (0 AI tokens, never recalled from model memory)."""
    if payload.project_id:
        if db.get(Project, payload.project_id) is None:
            raise ProjectNotFoundError(f"Project '{payload.project_id}' was not found.")

    links_by_id = {r.id: r.superseded_by_id for r in db.scalars(select(StandardDocument)).all()}
    new_id = new_uuid()
    if payload.superseded_by_id:
        if payload.superseded_by_id not in links_by_id:
            raise StandardValidationError(f"superseded_by_id '{payload.superseded_by_id}' does not exist.")
        try:
            validate_no_supersession_cycle(
                target_id=new_id,
                candidate_superseded_by_id=payload.superseded_by_id,
                links_by_id=links_by_id,
            )
        except StandardInputError as exc:
            raise StandardValidationError(str(exc)) from exc

    excerpts = _normalize_excerpts(payload.owner_excerpts)
    row = StandardDocument(
        id=new_id,
        project_id=payload.project_id,
        standard_number=payload.standard_number,
        title=payload.title,
        issuing_body=payload.issuing_body.strip(),
        edition_year=payload.edition_year.strip() or "unknown",
        status=payload.status,
        superseded_by_id=payload.superseded_by_id,
        supersession_note=(payload.supersession_note or "").strip() or None,
        jurisdiction=payload.jurisdiction.strip(),
        adopted_locally=bool(payload.adopted_locally),
        owner_notes=(payload.owner_notes or "").strip() or None,
        owner_excerpts_json=excerpts,
        metadata_status="owner_entered",
        use_ai=False,
        ai_suggestion_status="not_used",
        tokens_used=0,
        version=1,
        history_json=[],
    )
    row.history_json = [_snapshot_entry(row, note="Owner-entered standard created", actor="owner")]
    db.add(row)
    db.add(
        AuditLog(
            project_id=row.project_id,
            actor="owner",
            action="standard_created",
            entity_type="standard_document",
            entity_id=row.id,
            details_json={"standard_number": row.standard_number, "edition_year": row.edition_year, "status": row.status},
        )
    )
    db.commit()
    db.refresh(row)
    return _serialize_standards(db, [row])[0]


async def upload_standard_document(
    db: Session,
    settings: Settings,
    secret_store: SecretStore,
    *,
    upload: UploadFile,
    project_id: str | None = None,
    use_ai: bool = False,
    complexity: TaskComplexity = "fast",
    jurisdiction: str = "",
    adopted_locally: bool = False,
    client_factory: Callable[[str], Any] | None = None,
) -> StandardDocumentOut:
    """Upload owner/licensed PDF/DOCX/TXT standard, compute SHA-256, lock read-only original, and extract unconfirmed metadata suggestion."""
    project: Project | None = None
    if project_id:
        project = db.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    try:
        safe_name, spec = validate_upload_filename(upload.filename)
    except UnsafeFilenameError as exc:
        raise StandardValidationError(str(exc)) from exc
    if spec.extension not in _ALLOWED_STANDARD_EXTENSIONS:
        raise StandardValidationError(
            f"Unsupported standard document format '{spec.extension}'. Allowed: {sorted(_ALLOWED_STANDARD_EXTENSIONS)}"
        )

    raw_bytes = await upload.read()
    if not raw_bytes:
        raise StandardValidationError("Uploaded standard file is empty (0 bytes).")
    if len(raw_bytes) > settings.max_upload_size_bytes:
        raise StandardValidationError("Uploaded standard file exceeds configured upload size limit.")

    std_id = new_uuid()
    short_id = std_id.replace("-", "")[:8]
    target_dir = _resolve_library_dir(settings, project=project)
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"std_{short_id}_v1_{safe_name}"
    disk_path = target_dir / stored_name
    if disk_path.exists():
        raise StandardValidationError(f"Collision writing read-only standard file '{stored_name}'.")
    disk_path.write_bytes(raw_bytes)
    _set_read_only(disk_path)
    digest = sha256_file(disk_path)

    rel_path = (
        f"11_References/{stored_name}"
        if project is not None
        else f"_standards_library/{stored_name}"
    )

    header_text = extract_bounded_header_text(disk_path, spec.extension)
    suggestion = suggest_metadata_deterministically(header_text, original_filename=safe_name)

    tokens_used = 0
    ai_status = "not_used"
    meta_status = "unverified_suggestion"
    usage_dict: dict[str, Any] = {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    if use_ai:
        suggestion, usage = suggest_metadata_with_ai(
            db,
            secret_store,
            header_text=header_text,
            original_filename=safe_name,
            project_id=project_id,
            complexity=complexity,
            client_factory=client_factory,
        )
        tokens_used = int(usage.total_tokens)
        ai_status = "unverified_ai_suggestion"
        meta_status = "unverified_ai_suggestion"
        usage_dict = {
            "prompt_tokens": int(usage.prompt_tokens),
            "output_tokens": int(usage.output_tokens),
            "total_tokens": int(usage.total_tokens),
            "thoughts_tokens": int(getattr(usage, "thoughts_tokens", 0) or 0),
            "cached_tokens": int(getattr(usage, "cached_tokens", 0) or 0),
        }

    row = StandardDocument(
        id=std_id,
        project_id=project_id,
        standard_number=str(suggestion.get("suggested_number") or Path(safe_name).stem),
        title=str(suggestion.get("suggested_title") or safe_name),
        issuing_body=str(suggestion.get("suggested_issuing_body") or ""),
        edition_year=str(suggestion.get("suggested_edition_year") or "unknown") or "unknown",
        status="unknown",
        jurisdiction=jurisdiction.strip(),
        adopted_locally=bool(adopted_locally),
        owner_excerpts_json=[],
        metadata_status=meta_status,
        suggested_metadata_json=suggestion,
        use_ai=bool(use_ai),
        ai_suggestion_status=ai_status,
        tokens_used=tokens_used,
        token_usage_json=usage_dict,
        original_filename=safe_name,
        file_relative_path=rel_path,
        file_sha256=digest,
        file_size_bytes=len(raw_bytes),
        mime_type=spec.mime_hint,
        version=1,
        history_json=[],
    )
    row.history_json = [
        _snapshot_entry(
            row,
            note=f"Uploaded '{safe_name}' (sha256={digest[:12]}); metadata pending owner confirmation",
            actor="owner-upload",
        )
    ]
    db.add(row)
    db.add(
        AuditLog(
            project_id=project_id,
            actor="owner-upload",
            action="standard_document_uploaded",
            entity_type="standard_document",
            entity_id=row.id,
            details_json={"filename": safe_name, "sha256": digest, "use_ai": use_ai, "tokens_used": tokens_used},
        )
    )
    db.commit()
    db.refresh(row)
    return _serialize_standards(db, [row])[0]


def confirm_standard_metadata(
    db: Session,
    standard_id: str,
    payload: StandardConfirmRequest,
) -> StandardDocumentOut:
    """Confirm (and optionally refine) suggested metadata extracted from an uploaded standard document."""
    row = db.get(StandardDocument, standard_id)
    if row is None:
        raise StandardNotFoundError(f"Standard '{standard_id}' was not found.")

    if payload.standard_number is not None:
        row.standard_number = payload.standard_number.strip()
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.issuing_body is not None:
        row.issuing_body = payload.issuing_body.strip()
    if payload.edition_year is not None:
        row.edition_year = payload.edition_year.strip() or "unknown"
    if payload.status is not None:
        row.status = payload.status
    if payload.jurisdiction is not None:
        row.jurisdiction = payload.jurisdiction.strip()
    if payload.adopted_locally is not None:
        row.adopted_locally = bool(payload.adopted_locally)
    if payload.owner_notes is not None:
        row.owner_notes = payload.owner_notes.strip() or None
    if payload.owner_excerpts is not None:
        row.owner_excerpts_json = _normalize_excerpts(payload.owner_excerpts)

    row.metadata_status = "owner_confirmed"
    if row.ai_suggestion_status == "unverified_ai_suggestion":
        row.ai_suggestion_status = "owner_confirmed"
    row.version = int(row.version or 1) + 1
    hist = list(row.history_json or [])
    hist.append(_snapshot_entry(row, note=f"Owner confirmed metadata ({payload.confirmed_by})", actor=payload.confirmed_by))
    row.history_json = hist

    db.add(
        AuditLog(
            project_id=row.project_id,
            actor=payload.confirmed_by,
            action="standard_metadata_confirmed",
            entity_type="standard_document",
            entity_id=row.id,
            details_json={"version": row.version, "standard_number": row.standard_number, "status": row.status},
        )
    )
    db.commit()
    db.refresh(row)
    return _serialize_standards(db, [row])[0]


def update_standard_entry(
    db: Session,
    standard_id: str,
    payload: StandardUpdateRequest,
) -> StandardDocumentOut:
    """Versioned update to standard metadata, status, excerpts (<=300 chars), or supersession link."""
    row = db.get(StandardDocument, standard_id)
    if row is None:
        raise StandardNotFoundError(f"Standard '{standard_id}' was not found.")

    links_by_id = {r.id: r.superseded_by_id for r in db.scalars(select(StandardDocument)).all()}
    if payload.superseded_by_id is not None:
        clean_sup = payload.superseded_by_id.strip() or None
        if clean_sup and clean_sup not in links_by_id:
            raise StandardValidationError(f"superseded_by_id '{clean_sup}' does not exist.")
        try:
            validate_no_supersession_cycle(
                target_id=row.id,
                candidate_superseded_by_id=clean_sup,
                links_by_id=links_by_id,
            )
        except StandardInputError as exc:
            raise StandardValidationError(str(exc)) from exc
        row.superseded_by_id = clean_sup

    if payload.standard_number is not None:
        row.standard_number = payload.standard_number.strip()
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.issuing_body is not None:
        row.issuing_body = payload.issuing_body.strip()
    if payload.edition_year is not None:
        row.edition_year = payload.edition_year.strip() or "unknown"
    if payload.status is not None:
        row.status = payload.status
    if payload.supersession_note is not None:
        row.supersession_note = payload.supersession_note.strip() or None
    if payload.jurisdiction is not None:
        row.jurisdiction = payload.jurisdiction.strip()
    if payload.adopted_locally is not None:
        row.adopted_locally = bool(payload.adopted_locally)
    if payload.owner_notes is not None:
        row.owner_notes = payload.owner_notes.strip() or None
    if payload.owner_excerpts is not None:
        row.owner_excerpts_json = _normalize_excerpts(payload.owner_excerpts)

    if payload.confirm_metadata:
        row.metadata_status = "owner_confirmed"
        if row.ai_suggestion_status == "unverified_ai_suggestion":
            row.ai_suggestion_status = "owner_confirmed"

    row.version = int(row.version or 1) + 1
    hist = list(row.history_json or [])
    hist.append(_snapshot_entry(row, note=payload.change_note, actor="owner"))
    row.history_json = hist

    db.add(
        AuditLog(
            project_id=row.project_id,
            actor="owner",
            action="standard_updated",
            entity_type="standard_document",
            entity_id=row.id,
            details_json={"version": row.version, "status": row.status, "note": payload.change_note},
        )
    )
    db.commit()
    db.refresh(row)
    return _serialize_standards(db, [row])[0]


def supersede_standard_entry(
    db: Session,
    standard_id: str,
    payload: StandardSupersedeRequest,
) -> StandardDocumentOut:
    """Owner-registered supersession linking an old edition to an existing or newly supplied replacement edition."""
    old_row = db.get(StandardDocument, standard_id)
    if old_row is None:
        raise StandardNotFoundError(f"Standard '{standard_id}' was not found.")

    links_by_id = {r.id: r.superseded_by_id for r in db.scalars(select(StandardDocument)).all()}
    target_new_id: str | None = payload.superseded_by_id.strip() if payload.superseded_by_id else None

    if payload.new_standard is not None:
        created_new = create_standard_entry(db, payload.new_standard)
        target_new_id = created_new.id
        links_by_id[target_new_id] = None
    elif not target_new_id or target_new_id not in links_by_id:
        raise StandardValidationError("Must provide an existing superseded_by_id or a new_standard payload.")

    try:
        validate_no_supersession_cycle(
            target_id=old_row.id,
            candidate_superseded_by_id=target_new_id,
            links_by_id=links_by_id,
        )
    except StandardInputError as exc:
        raise StandardValidationError(str(exc)) from exc

    old_row.status = "superseded"
    old_row.superseded_by_id = target_new_id
    old_row.supersession_note = payload.supersession_note.strip()
    old_row.version = int(old_row.version or 1) + 1
    hist = list(old_row.history_json or [])
    hist.append(_snapshot_entry(old_row, note=f"Superseded: {payload.supersession_note.strip()}", actor="owner"))
    old_row.history_json = hist

    db.add(
        AuditLog(
            project_id=old_row.project_id,
            actor="owner",
            action="standard_superseded",
            entity_type="standard_document",
            entity_id=old_row.id,
            details_json={"superseded_by_id": target_new_id, "note": payload.supersession_note},
        )
    )
    db.commit()
    db.refresh(old_row)
    return _serialize_standards(db, [old_row])[0]


def list_and_search_standards(
    db: Session,
    *,
    project_id: str | None = None,
    include_global: bool = True,
    q: str | None = None,
    number: str | None = None,
    status: str | None = None,
    issuing_body: str | None = None,
    adopted_locally: bool | None = None,
) -> StandardListResponse:
    """Search owner-supplied / licensed standards ONLY by number, title, body, status, and keyword."""
    stmt = select(StandardDocument)
    if project_id:
        if include_global:
            stmt = stmt.where(or_(StandardDocument.project_id == project_id, StandardDocument.project_id.is_(None)))
        else:
            stmt = stmt.where(StandardDocument.project_id == project_id)
    if status:
        stmt = stmt.where(StandardDocument.status == status.strip())
    if adopted_locally is not None:
        stmt = stmt.where(StandardDocument.adopted_locally.is_(adopted_locally))
    if number:
        pat = f"%{number.strip()}%"
        stmt = stmt.where(StandardDocument.standard_number.ilike(pat))
    if issuing_body:
        pat_b = f"%{issuing_body.strip()}%"
        stmt = stmt.where(StandardDocument.issuing_body.ilike(pat_b))
    if q:
        pat_q = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                StandardDocument.standard_number.ilike(pat_q),
                StandardDocument.title.ilike(pat_q),
                StandardDocument.issuing_body.ilike(pat_q),
                StandardDocument.jurisdiction.ilike(pat_q),
                StandardDocument.owner_notes.ilike(pat_q),
            )
        )

    stmt = stmt.order_by(StandardDocument.standard_number.asc(), StandardDocument.edition_year.desc())
    rows = db.scalars(stmt).all()
    items = _serialize_standards(db, list(rows), project_id_for_citations=project_id)
    return StandardListResponse(standards=items, total=len(items))


def get_standard_detail(db: Session, standard_id: str) -> StandardDocumentOut:
    """Retrieve a single standard record with supersession chain, version history, and citations."""
    row = db.get(StandardDocument, standard_id)
    if row is None:
        raise StandardNotFoundError(f"Standard '{standard_id}' was not found.")
    return _serialize_standards(db, [row])[0]


def export_standards_register(
    db: Session,
    settings: Settings,
    payload: StandardRegisterExportRequest,
) -> StandardRegisterExportOut:
    """Export immutable bilingual DOCX, PDF & XLSX Standards Register with statuses and where-cited links."""
    project: Project | None = None
    if payload.project_id:
        project = db.get(Project, payload.project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project '{payload.project_id}' was not found.")

    listed = list_and_search_standards(
        db,
        project_id=payload.project_id,
        include_global=True,
    )
    standards = listed.standards
    scope_label = f"[{project.code}] {project.name} (+ Office Library)" if project else "All Standards Library"
    issued_iso = utc_now().strftime("%Y-%m-%d %H:%M UTC")
    tag = utc_now().strftime("%Y%m%d_%H%M%S") + "_" + new_uuid()[:6]

    base_dir = _resolve_library_dir(settings, project=project)
    reg_dir = base_dir if project is not None else (base_dir / "registers")
    reg_dir.mkdir(parents=True, exist_ok=True)

    render_data = StandardsRegisterRenderData(
        scope_label=scope_label,
        language=payload.language,
        classification=payload.classification,
        issued_at_iso=issued_iso,
        standards=standards,
    )

    stem = f"standards_register_{payload.language}_{tag}"
    out_docx = reg_dir / f"{stem}.docx"
    out_pdf = reg_dir / f"{stem}.pdf"
    out_xlsx = reg_dir / f"{stem}.xlsx"

    generate_standards_register_docx(out_docx, render_data)
    generate_standards_register_pdf(out_pdf, render_data)
    generate_standards_register_xlsx(out_xlsx, render_data)

    files_out: list[StandardRegisterExportFileOut] = []
    for fmt, p in (("docx", out_docx), ("pdf", out_pdf), ("xlsx", out_xlsx)):
        rel = f"11_References/{p.name}" if project else f"_standards_library/registers/{p.name}"
        qs = f"?project_id={project.id}" if project else ""
        files_out.append(
            StandardRegisterExportFileOut(
                format=fmt,
                filename=p.name,
                relative_path=rel,
                sha256=sha256_file(p),
                size_bytes=p.stat().st_size,
                download_url=f"/api/standards/register-files/{p.name}{qs}",
            )
        )

    warnings_cnt = sum(len(s.citation_warnings) for s in standards)
    db.add(
        AuditLog(
            project_id=payload.project_id,
            actor="owner-export",
            action="standards_register_exported",
            entity_type="standards_library",
            entity_id=payload.project_id,
            details_json={"language": payload.language, "count": len(standards), "files": [f.filename for f in files_out]},
        )
    )
    db.commit()

    return StandardRegisterExportOut(
        project_id=payload.project_id,
        language=payload.language,
        standards_count=len(standards),
        cited_warnings_count=warnings_cnt,
        files=files_out,
    )


def resolve_register_file_download(
    db: Session,
    settings: Settings,
    *,
    filename: str,
    project_id: str | None = None,
) -> Path:
    """Safely resolve a generated register export file inside 11_References or _standards_library/registers."""
    clean_name = Path(filename).name
    if clean_name != filename or not re.match(r"^standards_register_[A-Za-z0-9_.-]+\.(docx|pdf|xlsx)$", clean_name):
        raise StandardValidationError(f"Unsafe register filename: {filename!r}")
    if project_id:
        project = db.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
        path = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, f"11_References/{clean_name}")
    else:
        path = (settings.workspaces_dir / "_standards_library" / "registers" / clean_name).resolve()
        root = (settings.workspaces_dir / "_standards_library" / "registers").resolve()
        if not str(path).startswith(str(root)):
            raise StandardValidationError("Path traversal blocked.")
    if not path.is_file():
        raise StandardNotFoundError(f"Exported register file '{clean_name}' was not found.")
    return path


def list_standard_presets() -> StandardPresetListResponse:
    """Return synthetic SYN-* standard presets (zero copyrighted content or real standard codes)."""
    return StandardPresetListResponse(presets=get_synthetic_standards_presets())
