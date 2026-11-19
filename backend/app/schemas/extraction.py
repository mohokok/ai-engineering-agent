"""Pydantic schemas for Step 06/07 deterministic document, CAD, BIM extraction and vision summary."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification

ExtractionStatus = Literal["extracted", "partial_ocr_unavailable", "failed"]
ExtractedItemType = Literal[
    "text",
    "table",
    "cell_formula",
    "slide_note",
    "image_meta",
    "ocr_text",
    "cad_layer",
    "cad_block",
    "cad_entity",
    "cad_dimension",
    "cad_polyline_area",
    "bim_space",
    "bim_element",
    "vision_summary",
]
ExtractionMethod = Literal["native", "ocr", "converted_oda", "hybrid", "ai_vision"]
SupportLevel = Literal["native", "converted_via_oda", "not_supported"]


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


class OdaCapabilityOut(BaseModel):
    """Runtime detection report for ODA File Converter (external DWG->DXF converter)."""

    installed: bool
    status: str
    version: str | None = None
    install_url: str = "https://www.opendesign.com/guestfiles/oda_file_converter"
    message: str


class FormatSupportEntry(BaseModel):
    """Authoritative format support matrix entry (Native / Converted via ODA / Not Supported)."""

    extension: str
    category: str
    support_level: SupportLevel
    provider_or_tool: str
    notes: str


class ExtractionCapabilitiesOut(BaseModel):
    """Step 06/07 supported extensions, runtime tool availability, and format support matrix."""

    ocr: OcrCapabilityOut
    oda: OdaCapabilityOut
    format_support_matrix: list[FormatSupportEntry] = Field(default_factory=list)
    supported_extensions: list[str]
    cad_bim_deferred_extensions: list[str]
    classification: ProjectClassification = "Preliminary"


class ExtractedItem(BaseModel):
    """Normalized extracted item anchored strictly to source file, page/sheet/layer, and location."""

    item_index: int
    item_type: ExtractedItemType
    source_file: str
    file_id: str | None = None
    version_number: int = 1
    page_or_sheet: str
    location: str
    text: str | None = None
    raw_text: str | None = None
    raw_values: list[list[str]] | None = None
    raw_uncollapsed_values: list[list[str]] | None = None
    normalization_applied: str | None = None
    formula: str | None = None
    cached_value: str | None = None
    unit_or_format: str | None = None
    ocr_dpi: int | float | None = None
    start_row: int | None = None
    start_column: int | None = None
    start_column_letter: str | None = None
    row_numbers: list[int] | None = None
    layer: str | None = None
    block_name: str | None = None
    entity_handle: str | None = None
    cad_space: str | None = None
    area: float | None = None
    perimeter_or_length: float | None = None
    properties: dict[str, Any] | None = None
    quantities: dict[str, Any] | None = None
    extraction_method: ExtractionMethod = "native"


class ExtractionCounts(BaseModel):
    """Deterministic structural counts across document pages, sheets, CAD entities, and BIM elements."""

    pages: int = 0
    sheets: int = 0
    slides: int = 0
    tables: int = 0
    formulas: int = 0
    text_items: int = 0
    ocr_items: int = 0
    rendered_page_images: int = 0
    layers: int = 0
    blocks: int = 0
    block_inserts: int = 0
    entities: int = 0
    dimensions: int = 0
    polylines: int = 0
    closed_areas: int = 0
    ifc_spaces: int = 0
    ifc_walls: int = 0
    ifc_doors: int = 0
    ifc_windows: int = 0
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
    ocr_dpi: int | float | None = None
    converter_status: str | None = None
    converted_artifact_relative_path: str | None = None
    cad_units: str | None = None
    drawing_inventory: dict[str, Any] | None = None
    vision_summaries: list[dict[str, Any]] = Field(default_factory=list)
    classification: ProjectClassification | str
    counts: ExtractionCounts
    warnings: list[str] = Field(default_factory=list)
    rendered_page_images: list[str] = Field(default_factory=list)
    artifact_relative_path: str | None = None
    error_message: str | None = None
    created_at: datetime


class FileExtractionDetailOut(FileExtractionSummaryOut):
    """Complete normalized extraction payload including extracted items and tool status."""

    ocr: OcrCapabilityOut
    oda: OdaCapabilityOut | None = None
    items: list[ExtractedItem] = Field(default_factory=list)


class FileExtractionListResponse(BaseModel):
    """List of extraction runs for a project file ordered newest first."""

    file_id: str
    extractions: list[FileExtractionSummaryOut]
    total: int
    classification: ProjectClassification = "Preliminary"


class DrawingVisionPayload(BaseModel):
    """Structured schema requested from Gemini vision when summarizing a rendered drawing page."""

    drawing_title: str | None = None
    discipline_guess: str
    visible_labels_and_notes: list[str] = Field(default_factory=list)
    key_elements_observed: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class DrawingVisionSummaryRequest(BaseModel):
    """Request parameters for summarizing an extracted drawing page via Gemini vision."""

    page_number: int = Field(default=1, ge=1)
    complexity: TaskComplexity = "fast"


class DrawingVisionSummaryOut(BaseModel):
    """Persisted Gemini vision drawing summary explicitly flagged as AI interpretation, not measurement."""

    extraction_id: str
    page_number: int
    ai_interpretation_only: bool = True
    disclaimer: str
    provider_name: str
    model_name: str
    drawing_title: str | None = None
    discipline_guess: str
    visible_labels_and_notes: list[str] = Field(default_factory=list)
    key_elements_observed: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    artifact_relative_path: str
    classification: ProjectClassification = "Preliminary"
