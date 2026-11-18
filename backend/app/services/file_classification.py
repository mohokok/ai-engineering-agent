"""Supported engineering file extensions and workspace folder classification."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtensionSpec:
    """Metadata describing a supported file extension and its target workspace folder."""

    extension: str
    category: str
    target_folder: str
    mime_hint: str


_INPUT_DOCS = "01_Input_Documents"
_ORIGINAL_DRAWINGS = "02_Original_Drawings"

SUPPORTED_EXTENSIONS: dict[str, ExtensionSpec] = {
    # Documents -> 01_Input_Documents
    ".pdf": ExtensionSpec(".pdf", "document", _INPUT_DOCS, "application/pdf"),
    ".doc": ExtensionSpec(".doc", "document", _INPUT_DOCS, "application/msword"),
    ".docx": ExtensionSpec(
        ".docx",
        "document",
        _INPUT_DOCS,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".txt": ExtensionSpec(".txt", "document", _INPUT_DOCS, "text/plain"),
    ".rtf": ExtensionSpec(".rtf", "document", _INPUT_DOCS, "application/rtf"),
    ".html": ExtensionSpec(".html", "document", _INPUT_DOCS, "text/html"),
    ".htm": ExtensionSpec(".htm", "document", _INPUT_DOCS, "text/html"),
    ".md": ExtensionSpec(".md", "document", _INPUT_DOCS, "text/markdown"),
    # Spreadsheets -> 01_Input_Documents
    ".xls": ExtensionSpec(".xls", "spreadsheet", _INPUT_DOCS, "application/vnd.ms-excel"),
    ".xlsx": ExtensionSpec(
        ".xlsx",
        "spreadsheet",
        _INPUT_DOCS,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".csv": ExtensionSpec(".csv", "spreadsheet", _INPUT_DOCS, "text/csv"),
    ".ods": ExtensionSpec(
        ".ods",
        "spreadsheet",
        _INPUT_DOCS,
        "application/vnd.oasis.opendocument.spreadsheet",
    ),
    # Presentations -> 01_Input_Documents
    ".ppt": ExtensionSpec(".ppt", "presentation", _INPUT_DOCS, "application/vnd.ms-powerpoint"),
    ".pptx": ExtensionSpec(
        ".pptx",
        "presentation",
        _INPUT_DOCS,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    # Structured engineering data -> 01_Input_Documents
    ".xml": ExtensionSpec(".xml", "data", _INPUT_DOCS, "application/xml"),
    ".json": ExtensionSpec(".json", "data", _INPUT_DOCS, "application/json"),
    ".landxml": ExtensionSpec(".landxml", "data", _INPUT_DOCS, "application/xml"),
    # CAD / Vector drawings -> 02_Original_Drawings
    ".dwg": ExtensionSpec(".dwg", "drawing", _ORIGINAL_DRAWINGS, "application/acad"),
    ".dxf": ExtensionSpec(".dxf", "drawing", _ORIGINAL_DRAWINGS, "application/dxf"),
    ".dgn": ExtensionSpec(".dgn", "drawing", _ORIGINAL_DRAWINGS, "application/octet-stream"),
    ".dwf": ExtensionSpec(".dwf", "drawing", _ORIGINAL_DRAWINGS, "model/vnd.dwf"),
    ".svg": ExtensionSpec(".svg", "drawing", _ORIGINAL_DRAWINGS, "image/svg+xml"),
    # Raster images & drawing scans -> 02_Original_Drawings
    ".png": ExtensionSpec(".png", "image", _ORIGINAL_DRAWINGS, "image/png"),
    ".jpg": ExtensionSpec(".jpg", "image", _ORIGINAL_DRAWINGS, "image/jpeg"),
    ".jpeg": ExtensionSpec(".jpeg", "image", _ORIGINAL_DRAWINGS, "image/jpeg"),
    ".tif": ExtensionSpec(".tif", "image", _ORIGINAL_DRAWINGS, "image/tiff"),
    ".tiff": ExtensionSpec(".tiff", "image", _ORIGINAL_DRAWINGS, "image/tiff"),
    ".bmp": ExtensionSpec(".bmp", "image", _ORIGINAL_DRAWINGS, "image/bmp"),
    ".webp": ExtensionSpec(".webp", "image", _ORIGINAL_DRAWINGS, "image/webp"),
    # BIM & 3D engineering models -> 02_Original_Drawings
    ".ifc": ExtensionSpec(".ifc", "bim_3d", _ORIGINAL_DRAWINGS, "application/x-step"),
    ".rvt": ExtensionSpec(".rvt", "bim_3d", _ORIGINAL_DRAWINGS, "application/octet-stream"),
    ".rfa": ExtensionSpec(".rfa", "bim_3d", _ORIGINAL_DRAWINGS, "application/octet-stream"),
    ".rte": ExtensionSpec(".rte", "bim_3d", _ORIGINAL_DRAWINGS, "application/octet-stream"),
    ".obj": ExtensionSpec(".obj", "bim_3d", _ORIGINAL_DRAWINGS, "model/obj"),
    ".stl": ExtensionSpec(".stl", "bim_3d", _ORIGINAL_DRAWINGS, "model/stl"),
    ".step": ExtensionSpec(".step", "bim_3d", _ORIGINAL_DRAWINGS, "application/step"),
    ".stp": ExtensionSpec(".stp", "bim_3d", _ORIGINAL_DRAWINGS, "application/step"),
    ".iges": ExtensionSpec(".iges", "bim_3d", _ORIGINAL_DRAWINGS, "model/iges"),
    ".igs": ExtensionSpec(".igs", "bim_3d", _ORIGINAL_DRAWINGS, "model/iges"),
    ".gltf": ExtensionSpec(".gltf", "bim_3d", _ORIGINAL_DRAWINGS, "model/gltf+json"),
    ".glb": ExtensionSpec(".glb", "bim_3d", _ORIGINAL_DRAWINGS, "model/gltf-binary"),
}

EXPLICITLY_REJECTED_EXAMPLES: tuple[str, ...] = (
    ".exe",
    ".dll",
    ".msi",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".sh",
    ".py",
    ".zip",
    ".rar",
    ".7z",
)


def classify_extension(filename: str) -> ExtensionSpec | None:
    """Return the ExtensionSpec for a filename suffix, or None if unsupported."""
    ext = Path(filename).suffix.lower()
    if not ext:
        return None
    return SUPPORTED_EXTENSIONS.get(ext)


def list_supported_extensions() -> list[ExtensionSpec]:
    """Return all supported extensions sorted alphabetically."""
    return [SUPPORTED_EXTENSIONS[key] for key in sorted(SUPPORTED_EXTENSIONS)]
