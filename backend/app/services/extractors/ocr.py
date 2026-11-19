"""Runtime Tesseract OCR capability check and Arabic+English OCR fallback execution."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from typing import Callable

from PIL import Image
import pytesseract

from app.schemas.extraction import OcrCapabilityOut

TESSERACT_NOT_INSTALLED_STATUS = "not installed - pending owner"
TESSERACT_INSTALL_URL = "https://github.com/UB-Mannheim/tesseract/wiki"

OcrRunner = Callable[[bytes, str], str]

_DEFAULT_WINDOWS_TESSERACT_PATHS: tuple[Path, ...] = (
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
    Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
)


@dataclass(frozen=True)
class TesseractProbe:
    capability: OcrCapabilityOut
    executable: str | None


_TesseractProbe = TesseractProbe


def _resolve_tesseract_executable(configured_cmd: str = "") -> str | None:
    cleaned = configured_cmd.strip()
    if cleaned:
        candidate = Path(cleaned)
        if candidate.is_file():
            return str(candidate)
        located = shutil.which(cleaned)
        return located
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for win_path in _DEFAULT_WINDOWS_TESSERACT_PATHS:
        if win_path.is_file():
            return str(win_path)
    return None


def probe_tesseract(configured_cmd: str = "") -> TesseractProbe:
    executable = _resolve_tesseract_executable(configured_cmd)
    if not executable:
        return TesseractProbe(
            executable=None,
            capability=OcrCapabilityOut(
                installed=False,
                status=TESSERACT_NOT_INSTALLED_STATUS,
                version=None,
                languages=[],
                ara_installed=False,
                eng_installed=False,
                install_url=TESSERACT_INSTALL_URL,
                message=(
                    "Tesseract OCR (ara+eng) is not installed - pending owner. "
                    "PDF text/tables/page renders and Office/CSV/image metadata work without it; "
                    "install Tesseract 5.x with Arabic ('ara') data for scanned OCR fallback."
                ),
            ),
        )

    version_text: str | None = None
    languages: list[str] = []
    try:
        ver_proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        first_line = (ver_proc.stdout or ver_proc.stderr or "").splitlines()
        if first_line:
            version_text = first_line[0].strip()
    except Exception:
        version_text = None

    try:
        lang_proc = subprocess.run(
            [executable, "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        for line in (lang_proc.stdout or "").splitlines():
            token = line.strip()
            if token and not token.lower().startswith("list of available"):
                languages.append(token)
    except Exception:
        languages = []

    ara_ok = "ara" in languages
    eng_ok = "eng" in languages
    if ara_ok and eng_ok:
        status_label = "installed"
        msg = f"Tesseract OCR available ({version_text or 'detected'}) with ara+eng language packs."
    elif eng_ok:
        status_label = "installed_missing_ara"
        msg = (
            "Tesseract OCR is installed without Arabic ('ara') language data; "
            "add ara.traineddata for Arabic scanned OCR."
        )
    else:
        status_label = "installed_missing_langs"
        msg = "Tesseract OCR executable detected, but eng/ara language packs were not reported."

    return TesseractProbe(
        executable=executable,
        capability=OcrCapabilityOut(
            installed=True,
            status=status_label,
            version=version_text,
            languages=sorted(set(languages)),
            ara_installed=ara_ok,
            eng_installed=eng_ok,
            install_url=TESSERACT_INSTALL_URL,
            message=msg,
        ),
    )


_probe_tesseract = probe_tesseract


def detect_tesseract(configured_cmd: str = "") -> OcrCapabilityOut:
    """Detect Tesseract OCR installation and ara+eng packs without leaking local user paths."""
    return probe_tesseract(configured_cmd).capability


def run_ocr_on_image_bytes(
    image_bytes: bytes,
    *,
    configured_cmd: str = "",
    ocr_probe: TesseractProbe | None = None,
    ocr_runner: OcrRunner | None = None,
    requested_lang: str = "ara+eng",
) -> tuple[str | None, str | None]:
    """Run Arabic+English OCR on image bytes using a cached run-level probe when provided."""
    if ocr_runner is not None:
        raw_text = ocr_runner(image_bytes, requested_lang)
        cleaned = (raw_text or "").strip()
        return (cleaned or None), None

    probe = ocr_probe if ocr_probe is not None else probe_tesseract(configured_cmd)
    if not probe.capability.installed or not probe.executable:
        return None, (
            "Tesseract OCR is not installed - pending owner; OCR text extraction skipped."
        )

    lang_parts = []
    if probe.capability.ara_installed:
        lang_parts.append("ara")
    if probe.capability.eng_installed:
        lang_parts.append("eng")
    selected_lang = "+".join(lang_parts) if lang_parts else "eng"

    pytesseract.pytesseract.tesseract_cmd = probe.executable
    with Image.open(BytesIO(image_bytes)) as img:
        text = pytesseract.image_to_string(img, lang=selected_lang)
    warning: str | None = None
    if not probe.capability.ara_installed:
        warning = "Tesseract OCR ran without Arabic ('ara') language data."
    return (text.strip() or None), warning
