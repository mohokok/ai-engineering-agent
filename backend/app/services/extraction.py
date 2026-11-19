"""Step 06 extraction orchestration, read-only integrity check, and versioned persistence."""

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import AuditLog, FileExtraction, FileVersion, Project, ProjectFile
from app.schemas.extraction import (
    ExtractedItem,
    ExtractionCapabilitiesOut,
    ExtractionCounts,
    FileExtractionDetailOut,
    FileExtractionRequest,
    FileExtractionSummaryOut,
    OcrCapabilityOut,
)
from app.services.extractors import (
    ExtractedPayload,
    OcrRunner,
    detect_tesseract,
    extract_csv,
    extract_docx,
    extract_image,
    extract_pdf,
    extract_plain_text,
    extract_pptx,
    extract_xlsx,
)
from app.services.files import FileRecordNotFoundError, FileVersionNotFoundError
from app.services.workspace import resolve_project_file_path

STEP06_EXTRACTABLE_EXTENSIONS: tuple[str, ...] = (
    ".bmp",
    ".csv",
    ".docx",
    ".jpeg",
    ".jpg",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".tif",
    ".tiff",
    ".txt",
    ".webp",
    ".xlsx",
)

CAD_BIM_DEFERRED_EXTENSIONS: tuple[str, ...] = (
    ".dgn",
    ".dwf",
    ".dwg",
    ".dxf",
    ".glb",
    ".gltf",
    ".ifc",
    ".iges",
    ".igs",
    ".obj",
    ".rfa",
    ".rte",
    ".rvt",
    ".step",
    ".stl",
    ".stp",
)

_IMAGE_EXTENSIONS = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
_PLAIN_TEXT_EXTENSIONS = frozenset({".md", ".txt"})


class UnsupportedExtractionFormatError(ValueError):
    """Raised when attempting Step 06 extraction on a CAD/BIM or legacy binary format."""


class ExtractionNotFoundError(LookupError):
    """Raised when a requested extraction ID or rendered page image does not exist."""


class ExtractionProcessingError(RuntimeError):
    """Raised when deterministic parsing fails on a corrupted input file."""


def _compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def get_extraction_capabilities(settings: Settings) -> ExtractionCapabilitiesOut:
    """Return runtime OCR capability status and supported Step 06 extensions."""
    return ExtractionCapabilitiesOut(
        ocr=detect_tesseract(settings.tesseract_cmd),
        supported_extensions=list(STEP06_EXTRACTABLE_EXTENSIONS),
        cad_bim_deferred_extensions=list(CAD_BIM_DEFERRED_EXTENSIONS),
    )


def _to_summary_out(
    row: FileExtraction,
    *,
    source_file: str,
    folder_name: str,
    extension: str,
) -> FileExtractionSummaryOut:
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    sha_before = str(payload.get("sha256_before") or row.source_sha256)
    sha_after = str(payload.get("sha256_after") or row.source_sha256)
    return FileExtractionSummaryOut(
        id=row.id,
        project_id=row.project_id,
        file_id=row.file_id,
        source_file=source_file,
        folder_name=folder_name,
        extension=extension,
        version_number=row.version_number,
        extraction_version=row.extraction_version,
        source_sha256=row.source_sha256,
        sha256_before=sha_before,
        sha256_after=sha_after,
        original_unchanged=sha_before == sha_after,
        status=row.status,  # type: ignore[arg-type]
        ocr_status=row.ocr_status,
        classification=row.classification,
        counts=ExtractionCounts.model_validate(row.counts_json or {}),
        warnings=list(row.warnings_json or []),
        rendered_page_images=list(row.rendered_images_json or []),
        artifact_relative_path=row.artifact_relative_path,
        error_message=row.error_message,
        created_at=row.created_at,
    )


def _to_detail_out(
    row: FileExtraction,
    *,
    source_file: str,
    folder_name: str,
    extension: str,
    settings: Settings,
) -> FileExtractionDetailOut:
    summary = _to_summary_out(
        row,
        source_file=source_file,
        folder_name=folder_name,
        extension=extension,
    )
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    raw_ocr = payload.get("ocr")
    ocr_out = (
        OcrCapabilityOut.model_validate(raw_ocr)
        if isinstance(raw_ocr, dict)
        else detect_tesseract(settings.tesseract_cmd)
    )
    raw_items = payload.get("items") or []
    items = [ExtractedItem.model_validate(item) for item in raw_items]
    return FileExtractionDetailOut(
        **summary.model_dump(),
        ocr=ocr_out,
        items=items,
    )


def _dispatch_extractor(
    ext: str,
    source_path: Path,
    *,
    pages_dir: Path,
    pages_rel_prefix: str,
    source_file: str,
    file_id: str,
    version_number: int,
    configured_tesseract_cmd: str,
    ocr_runner: OcrRunner | None,
    force_ocr: bool,
) -> ExtractedPayload:
    if ext == ".pdf":
        return extract_pdf(
            source_path,
            output_pages_dir=pages_dir,
            pages_relative_prefix=pages_rel_prefix,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
            configured_tesseract_cmd=configured_tesseract_cmd,
            ocr_runner=ocr_runner,
            force_ocr=force_ocr,
        )
    if ext == ".docx":
        return extract_docx(
            source_path,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
        )
    if ext == ".xlsx":
        return extract_xlsx(
            source_path,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
        )
    if ext == ".csv":
        return extract_csv(
            source_path,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
        )
    if ext == ".pptx":
        return extract_pptx(
            source_path,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
        )
    if ext in _IMAGE_EXTENSIONS:
        return extract_image(
            source_path,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
            configured_tesseract_cmd=configured_tesseract_cmd,
            ocr_runner=ocr_runner,
        )
    if ext in _PLAIN_TEXT_EXTENSIONS:
        return extract_plain_text(
            source_path,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
        )
    raise UnsupportedExtractionFormatError(
        f"Format '{ext or '<none>'}' is not supported by Step 06 extraction."
    )


def extract_project_file(
    db: Session,
    settings: Settings,
    file_id: str,
    *,
    request_payload: FileExtractionRequest | None = None,
    ocr_runner: OcrRunner | None = None,
) -> FileExtractionDetailOut:
    """Run deterministic read-only extraction on a project file and store versioned output."""
    opts = request_payload or FileExtractionRequest()
    pf = db.get(ProjectFile, file_id)
    if pf is None:
        raise FileRecordNotFoundError(f"Project file '{file_id}' was not found.")
    project = db.get(Project, pf.project_id)
    if project is None:
        raise FileRecordNotFoundError(f"Parent project for file '{file_id}' was not found.")

    target_version_num = opts.version_number if opts.version_number is not None else pf.current_version
    version_row = db.scalar(
        select(FileVersion).where(
            FileVersion.file_id == pf.id,
            FileVersion.version_number == target_version_num,
        )
    )
    if version_row is None:
        raise FileVersionNotFoundError(
            f"Version v{target_version_num} for file '{pf.original_filename}' was not found."
        )

    ext = (pf.extension or Path(pf.original_filename).suffix).lower()
    if ext in CAD_BIM_DEFERRED_EXTENSIONS:
        raise UnsupportedExtractionFormatError(
            f"Format '{ext}' requires CAD/BIM ingestion in Step 07; "
            "Step 06 extracts PDF, DOCX, XLSX, CSV, PPTX, TXT/MD, and raster images."
        )
    if ext not in STEP06_EXTRACTABLE_EXTENSIONS:
        raise UnsupportedExtractionFormatError(
            f"Format '{ext or '<none>'}' is not extractable natively in Step 06; "
            "convert legacy binaries (.doc/.xls/.ppt) to modern formats or PDF."
        )

    source_path = resolve_project_file_path(
        settings.workspaces_dir,
        project.workspace_slug,
        version_row.stored_relative_path,
    )
    if not source_path.is_file():
        raise FileVersionNotFoundError(
            f"Stored file bytes for '{pf.original_filename}' v{target_version_num} are missing on disk."
        )

    sha256_before = _compute_sha256(source_path)

    max_run = db.scalar(
        select(func.max(FileExtraction.extraction_version)).where(
            FileExtraction.file_id == pf.id,
            FileExtraction.version_number == target_version_num,
        )
    )
    extraction_version = int(max_run or 0) + 1
    run_rel_dir = f"03_Analysis/extractions/{pf.id}/v{target_version_num}/r{extraction_version}"
    artifact_rel_path = f"{run_rel_dir}/extraction.json"
    pages_rel_prefix = f"{run_rel_dir}/pages"

    artifact_path = resolve_project_file_path(
        settings.workspaces_dir, project.workspace_slug, artifact_rel_path
    )
    pages_dir = resolve_project_file_path(
        settings.workspaces_dir, project.workspace_slug, pages_rel_prefix
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    ocr_capability = detect_tesseract(settings.tesseract_cmd)

    extraction_id = new_uuid()
    try:
        extracted = _dispatch_extractor(
            ext,
            source_path,
            pages_dir=pages_dir,
            pages_rel_prefix=pages_rel_prefix,
            source_file=pf.original_filename,
            file_id=pf.id,
            version_number=target_version_num,
            configured_tesseract_cmd=settings.tesseract_cmd,
            ocr_runner=ocr_runner,
            force_ocr=opts.force_ocr,
        )
    except Exception as exc:
        sha256_after_err = _compute_sha256(source_path)
        error_text = f"{exc.__class__.__name__}: {exc}"
        failed_row = FileExtraction(
            id=extraction_id,
            project_id=project.id,
            file_id=pf.id,
            version_number=target_version_num,
            extraction_version=extraction_version,
            source_sha256=sha256_before,
            status="failed",
            ocr_status=ocr_capability.status,
            classification=opts.classification,
            counts_json=ExtractionCounts().model_dump(),
            warnings_json=[],
            rendered_images_json=[],
            payload_json={
                "sha256_before": sha256_before,
                "sha256_after": sha256_after_err,
                "ocr": ocr_capability.model_dump(),
                "items": [],
            },
            artifact_relative_path=None,
            error_message=error_text,
        )
        db.add(failed_row)
        db.add(
            AuditLog(
                project_id=project.id,
                action="file.extraction_failed",
                entity_type="file_extraction",
                entity_id=extraction_id,
                actor="extractor",
                details_json={
                    "file_id": pf.id,
                    "source_file": pf.original_filename,
                    "version_number": target_version_num,
                    "error": error_text,
                },
            )
        )
        db.commit()
        raise ExtractionProcessingError(
            f"Extraction failed for '{pf.original_filename}': {error_text}"
        ) from exc

    sha256_after = _compute_sha256(source_path)
    if sha256_after != sha256_before:
        raise RuntimeError(
            f"Original file '{pf.original_filename}' SHA-256 changed during extraction!"
        )

    counts_dict = extracted.counts.model_dump()
    items_list = [item.model_dump() for item in extracted.items]
    payload_dict: dict[str, Any] = {
        "extraction_id": extraction_id,
        "project_id": project.id,
        "file_id": pf.id,
        "source_file": pf.original_filename,
        "folder_name": pf.folder_name,
        "extension": ext,
        "version_number": target_version_num,
        "extraction_version": extraction_version,
        "sha256_before": sha256_before,
        "sha256_after": sha256_after,
        "original_unchanged": True,
        "classification": opts.classification,
        "status": extracted.status,
        "ocr_status": extracted.ocr_status,
        "ocr": ocr_capability.model_dump(),
        "counts": counts_dict,
        "warnings": extracted.warnings,
        "rendered_page_images": extracted.rendered_page_images,
        "items": items_list,
    }
    artifact_path.write_text(
        json.dumps(payload_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    row = FileExtraction(
        id=extraction_id,
        project_id=project.id,
        file_id=pf.id,
        version_number=target_version_num,
        extraction_version=extraction_version,
        source_sha256=sha256_before,
        status=extracted.status,
        ocr_status=extracted.ocr_status,
        classification=opts.classification,
        counts_json=counts_dict,
        warnings_json=extracted.warnings,
        rendered_images_json=extracted.rendered_page_images,
        payload_json=payload_dict,
        artifact_relative_path=artifact_rel_path,
        error_message=None,
    )
    db.add(row)
    db.add(
        AuditLog(
            project_id=project.id,
            action="file.extracted",
            entity_type="file_extraction",
            entity_id=extraction_id,
            actor="extractor",
            details_json={
                "file_id": pf.id,
                "source_file": pf.original_filename,
                "extension": ext,
                "version_number": target_version_num,
                "extraction_version": extraction_version,
                "status": extracted.status,
                "ocr_status": extracted.ocr_status,
                "counts": counts_dict,
                "artifact_relative_path": artifact_rel_path,
            },
        )
    )
    db.commit()
    db.refresh(row)

    return _to_detail_out(
        row,
        source_file=pf.original_filename,
        folder_name=pf.folder_name,
        extension=ext,
        settings=settings,
    )


def list_file_extractions(db: Session, file_id: str) -> list[FileExtractionSummaryOut]:
    """Return persisted extraction runs for a project file ordered newest first."""
    pf = db.get(ProjectFile, file_id)
    if pf is None:
        raise FileRecordNotFoundError(f"Project file '{file_id}' was not found.")
    ext = (pf.extension or Path(pf.original_filename).suffix).lower()
    rows = db.scalars(
        select(FileExtraction)
        .where(FileExtraction.file_id == pf.id)
        .order_by(FileExtraction.created_at.desc(), FileExtraction.extraction_version.desc())
    ).all()
    return [
        _to_summary_out(
            row,
            source_file=pf.original_filename,
            folder_name=pf.folder_name,
            extension=ext,
        )
        for row in rows
    ]


def get_extraction_detail(
    db: Session,
    settings: Settings,
    extraction_id: str,
) -> FileExtractionDetailOut:
    """Return full normalized extraction JSON and metadata for one extraction run."""
    row = db.get(FileExtraction, extraction_id)
    if row is None:
        raise ExtractionNotFoundError(f"Extraction '{extraction_id}' was not found.")
    pf = db.get(ProjectFile, row.file_id)
    if pf is None:
        raise ExtractionNotFoundError(f"Parent file for extraction '{extraction_id}' was not found.")
    ext = (pf.extension or Path(pf.original_filename).suffix).lower()
    return _to_detail_out(
        row,
        source_file=pf.original_filename,
        folder_name=pf.folder_name,
        extension=ext,
        settings=settings,
    )


def resolve_extraction_page_image(
    db: Session,
    workspaces_dir: Path,
    extraction_id: str,
    page_number: int,
) -> tuple[Path, str]:
    """Safely resolve a rendered PDF page PNG belonging to a persisted extraction run."""
    if page_number < 1:
        raise ExtractionNotFoundError("Page number must be >= 1.")
    row = db.get(FileExtraction, extraction_id)
    if row is None:
        raise ExtractionNotFoundError(f"Extraction '{extraction_id}' was not found.")
    project = db.get(Project, row.project_id)
    if project is None:
        raise ExtractionNotFoundError(f"Project for extraction '{extraction_id}' was not found.")

    rendered = list(row.rendered_images_json or [])
    if page_number > len(rendered):
        raise ExtractionNotFoundError(
            f"Rendered page {page_number} does not exist for extraction '{extraction_id}'."
        )
    rel_path = rendered[page_number - 1]
    disk_path = resolve_project_file_path(workspaces_dir, project.workspace_slug, rel_path)
    if not disk_path.is_file():
        raise ExtractionNotFoundError(f"Rendered page image '{disk_path.name}' is missing on disk.")
    return disk_path, disk_path.name
