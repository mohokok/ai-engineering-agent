"""Format-specific deterministic extractors (PDF, Office, CSV, images, OCR, CAD/DXF/DWG, BIM/IFC)."""

from app.services.extractors.bim import extract_ifc
from app.services.extractors.cad import extract_dxf
from app.services.extractors.ocr import (
    TESSERACT_NOT_INSTALLED_STATUS,
    OcrRunner,
    TesseractProbe,
    detect_tesseract,
    probe_tesseract,
    run_ocr_on_image_bytes,
)
from app.services.extractors.oda import (
    ODA_NOT_INSTALLED_STATUS,
    OdaProbe,
    convert_dwg_to_dxf,
    detect_oda,
    probe_oda,
)
from app.services.extractors.office import (
    ExtractedPayload,
    extract_csv,
    extract_docx,
    extract_plain_text,
    extract_pptx,
    extract_xlsx,
)
from app.services.extractors.pdf_and_image import extract_image, extract_pdf

__all__ = [
    "ExtractedPayload",
    "ODA_NOT_INSTALLED_STATUS",
    "OcrRunner",
    "OdaProbe",
    "TESSERACT_NOT_INSTALLED_STATUS",
    "TesseractProbe",
    "convert_dwg_to_dxf",
    "detect_oda",
    "detect_tesseract",
    "extract_csv",
    "extract_docx",
    "extract_dxf",
    "extract_ifc",
    "extract_image",
    "extract_pdf",
    "extract_plain_text",
    "extract_pptx",
    "extract_xlsx",
    "probe_oda",
    "probe_tesseract",
    "run_ocr_on_image_bytes",
]
