"""Runtime ODA File Converter detection and read-only DWG -> DXF batch conversion."""

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from app.schemas.extraction import OdaCapabilityOut

ODA_NOT_INSTALLED_STATUS = "not installed - pending owner"
ODA_INSTALL_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"

_DEFAULT_ODA_SEARCH_ROOTS: tuple[Path, ...] = (
    Path("C:/Program Files/ODA"),
    Path("C:/Program Files (x86)/ODA"),
    Path("/opt/ODAFileConverter"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
)
_ODA_VERSION_DIR_RE = re.compile(r"ODAFileConverter[\s_-]*([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE)


@dataclass(frozen=True)
class OdaProbe:
    """Result of probing ODA File Converter without mutating OS settings."""

    capability: OdaCapabilityOut
    executable: str | None


def _resolve_oda_executable(configured_cmd: str = "") -> str | None:
    """Resolve ODAFileConverter checking configured setting -> PATH -> standard install folders."""
    cleaned = configured_cmd.strip()
    if cleaned:
        candidate = Path(cleaned)
        if candidate.is_file():
            return str(candidate)
        if candidate.is_dir():
            for exe_name in ("ODAFileConverter.exe", "ODAFileConverter"):
                nested = candidate / exe_name
                if nested.is_file():
                    return str(nested)
        return shutil.which(cleaned)

    for cmd_name in ("ODAFileConverter.exe", "ODAFileConverter", "TeighaFileConverter"):
        found = shutil.which(cmd_name)
        if found:
            return found

    for root in _DEFAULT_ODA_SEARCH_ROOTS:
        if not root.exists():
            continue
        for exe_name in ("ODAFileConverter.exe", "ODAFileConverter"):
            direct = root / exe_name
            if direct.is_file():
                return str(direct)
        # Prefer newest versioned install subdirectory deterministically (e.g. ODAFileConverter 27.10.0)
        versioned_matches: list[Path] = []
        for pattern in ("ODAFileConverter*/ODAFileConverter.exe", "ODAFileConverter*/ODAFileConverter"):
            versioned_matches.extend(p for p in root.glob(pattern) if p.is_file())
        if versioned_matches:
            versioned_matches.sort(key=lambda p: p.parent.name, reverse=True)
            return str(versioned_matches[0])

    return None


def _extract_oda_version(executable_path: str) -> str | None:
    path_obj = Path(executable_path)
    match = _ODA_VERSION_DIR_RE.search(path_obj.parent.name)
    if match:
        return match.group(1)
    return None


def probe_oda(configured_cmd: str = "") -> OdaProbe:
    """Probe ODA File Converter executable without leaking local user paths."""
    executable = _resolve_oda_executable(configured_cmd)
    if not executable:
        return OdaProbe(
            executable=None,
            capability=OdaCapabilityOut(
                installed=False,
                status=ODA_NOT_INSTALLED_STATUS,
                version=None,
                install_url=ODA_INSTALL_URL,
                message=(
                    "ODA File Converter is not installed - pending owner. "
                    "Native DXF and IFC work without it; converting binary .dwg to .dxf requires ODA File Converter."
                ),
            ),
        )

    version_str = _extract_oda_version(executable)
    return OdaProbe(
        executable=executable,
        capability=OdaCapabilityOut(
            installed=True,
            status="installed",
            version=version_str,
            install_url=ODA_INSTALL_URL,
            message=(
                f"ODA File Converter available ({version_str or 'detected'}) for .dwg -> .dxf conversion."
            ),
        ),
    )


def detect_oda(configured_cmd: str = "") -> OdaCapabilityOut:
    """Detect ODA File Converter availability cleanly."""
    return probe_oda(configured_cmd).capability


def convert_dwg_to_dxf(
    source_dwg_path: Path,
    *,
    output_dxf_dir: Path,
    source_filename: str,
    oda_probe: OdaProbe,
    output_version: str = "ACAD2018",
) -> Path:
    """Convert one read-only DWG into a fresh DXF inside versioned output_dxf_dir without touching original."""
    if not oda_probe.capability.installed or not oda_probe.executable:
        raise RuntimeError(
            "ODA File Converter is not installed - pending owner; binary .dwg files require external DWG->DXF conversion."
        )

    output_dxf_dir.mkdir(parents=True, exist_ok=True)
    safe_source_name = Path(source_filename).name
    expected_stem = Path(safe_source_name).stem

    # Copy ONLY this DWG into an isolated temp input folder so ODA never scans 02_Original_Drawings directly.
    with tempfile.TemporaryDirectory(prefix="oda_dwg_in_") as tmp_in_str:
        tmp_in_dir = Path(tmp_in_str)
        staged_dwg = tmp_in_dir / safe_source_name
        staged_dwg.write_bytes(source_dwg_path.read_bytes())

        cmd = [
            oda_probe.executable,
            str(tmp_in_dir),
            str(output_dxf_dir),
            output_version,
            "DXF",
            "0",  # do not recurse
            "1",  # audit enabled during conversion
            "*.dwg",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        if proc.returncode != 0:
            err_tail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                f"ODA File Converter failed (exit {proc.returncode}) converting '{safe_source_name}': {err_tail or 'unknown error'}"
            )

    # Locate generated DXF output cleanly (handles case normalization on Windows/Linux).
    direct_target = output_dxf_dir / f"{expected_stem}.dxf"
    if direct_target.is_file() and direct_target.stat().st_size > 0:
        return direct_target

    for candidate in sorted(output_dxf_dir.iterdir()):
        if candidate.is_file() and candidate.suffix.lower() == ".dxf" and candidate.stat().st_size > 0:
            if candidate.stem.lower() == expected_stem.lower():
                return candidate

    raise RuntimeError(
        f"ODA File Converter exited cleanly but did not produce a converted DXF for '{safe_source_name}'."
    )
