"""Pydantic schemas for Step 06 deterministic file extraction and OCR capability detection."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.projects import ProjectClassification

ExtractionStatus = Literal["extracted", "partial_ocr_unavailable", "failed"]
ExtractedItemType = Literal[
    "text",
    "table",
    "cell_formula",
    "slide_note",
    "image_meta",
    "ocr_text",
]
ExtractionMethod = Literal["native", "ocr", "hybrid"]


class OcrCapabilityOut(BaseModel):
    """Runtime detection report for Tesseract OCR binary and Arabic/English language packs."""

    installed: bool
    status: str
    version: str | None = None
    languages: list[str] = Field(default_factory=list)
    ara_installed: bool = False
    eng_installed: bool = False
    install_url: str = "https://github.com/UB-Mannheim/tesseract/wiki"
    message: str


class ExtractionCapabilitiesOut(BaseModel):
    """Step 06 supported extractable extensions and runtime OCR availability."""

    ocr: OcrCapabilityOut
    supported_extensions: list[str]
    cad_bim_deferred_extensions: list[str]
    classification: ProjectClassification = "Preliminary"


class ExtractedItem(BaseModel):
    """Normalized extracted item anchored strictly to source file, page/sheet, and location."""

    item_index: int
    item_type: ExtractedItemType
    source_file: str
    file_id: str | None = None
    version_number: int = 1
    page_or_sheet: str
    location: str
    text: str | None = None
    raw_values: list[list[str]] | None = None
    formula: str | None = None
    cached_value: str | None = None
    unit_or_format: str | None = None
    extraction_method: ExtractionMethod = "native"


class ExtractionCounts(BaseModel):
    """Deterministic structural counts across pages, sheets, slides, tables, formulas, and items."""

    pages: int = 0
    sheets: int = 0
    slides: int = 0
    tables: int = 0
    formulas: int = 0
    text_items: int = 0
    ocr_items: int = 0
    rendered_page_images: int = 0
    total_items: int = 0


class FileExtractionRequest(BaseModel):
    """Optional parameters when running extraction on an uploaded project file."""

    version_number: int | None = Field(default=None, ge=1)
    force_ocr: bool = False
    classification: ProjectClassification = "Preliminary"


class FileExtractionSummaryOut(BaseModel):
    """Summary metadata for a persisted extraction run."""

    id: str
    project_id: str
    file_id: str
    source_file: str
    folder_name: str
    extension: str
    version_number: int
    extraction_version: int
    source_sha256: str
    sha256_before: str
    sha256_after: str
    original_unchanged: bool
    status: ExtractionStatus
    ocr_status: str
    classification: ProjectClassification | str
    counts: ExtractionCounts
    warnings: list[str] = Field(default_factory=list)
    rendered_page_images: list[str] = Field(default_factory=list)
    artifact_relative_path: str | None = None
    error_message: str | None = None
    created_at: datetime


class FileExtractionDetailOut(FileExtractionSummaryOut):
    """Complete normalized extraction payload including extracted items and OCR status."""

    ocr: OcrCapabilityOut
    items: list[ExtractedItem] = Field(default_factory=list)


class FileExtractionListResponse(BaseModel):
    """List of extraction runs for a project file ordered newest first."""

    file_id: str
    extractions: list[FileExtractionSummaryOut]
    total: int
    classification: ProjectClassification = "Preliminary"
