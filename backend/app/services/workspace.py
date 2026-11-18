"""Project workspace folder creation and filesystem verification helpers."""

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

PROJECT_WORKSPACE_FOLDERS: tuple[str, ...] = (
    "01_Input_Documents",
    "02_Original_Drawings",
    "03_Analysis",
    "04_Engineering_Calculations",
    "05_Design_Drawings",
    "06_BOQ",
    "07_Technical_Specifications",
    "08_Reports",
    "09_Comparisons",
    "10_Final_Deliverables",
    "11_References",
    "12_Revision_History",
)

_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_SEPARATOR_RE = re.compile(r"[\s._-]+")


@dataclass(frozen=True)
class WorkspaceFolderStatus:
    """On-disk status for one numbered workspace directory inside a project."""

    name: str
    relative_path: str
    exists: bool


def sanitize_workspace_stem(project_name: str, max_length: int = 60) -> str:
    """Convert an Arabic or English project name into a Windows-safe folder stem."""
    normalized = unicodedata.normalize("NFC", project_name.strip())
    cleaned = _UNSAFE_FILENAME_RE.sub(" ", normalized)
    collapsed = _SEPARATOR_RE.sub("_", cleaned).strip("_- .")
    if len(collapsed) > max_length:
        collapsed = collapsed[:max_length].rstrip("_- .")
    if not collapsed or collapsed.upper() in _WINDOWS_RESERVED_NAMES:
        return "project"
    return collapsed


def build_workspace_slug(project_name: str, project_id: str) -> str:
    """Return a unique, NTFS-safe workspace directory name preserving Arabic text."""
    stem = sanitize_workspace_stem(project_name)
    short_id = project_id.replace("-", "")[:8]
    return f"{stem}_{short_id}"


def resolve_project_dir(workspaces_dir: Path, workspace_slug: str) -> Path:
    """Resolve and validate that a project workspace stays inside workspaces_dir."""
    if not workspace_slug or "/" in workspace_slug or "\\" in workspace_slug or ".." in workspace_slug:
        raise ValueError(f"Invalid workspace slug: {workspace_slug!r}")
    root = workspaces_dir.resolve()
    project_dir = (root / workspace_slug).resolve()
    if project_dir == root or not project_dir.is_relative_to(root):
        raise ValueError("Workspace path escaped base workspaces directory")
    return project_dir


def create_project_workspace(workspaces_dir: Path, workspace_slug: str) -> Path:
    """Create the project root workspace and all 12 standard engineering folders."""
    workspaces_dir.mkdir(parents=True, exist_ok=True)
    project_dir = resolve_project_dir(workspaces_dir, workspace_slug)
    project_dir.mkdir(parents=True, exist_ok=False)
    for folder_name in PROJECT_WORKSPACE_FOLDERS:
        (project_dir / folder_name).mkdir(exist_ok=True)
    return project_dir


def inspect_project_folders(
    workspaces_dir: Path, workspace_slug: str
) -> list[WorkspaceFolderStatus]:
    """Inspect whether all 12 numbered workspace folders exist on disk for a project."""
    project_dir = resolve_project_dir(workspaces_dir, workspace_slug)
    statuses: list[WorkspaceFolderStatus] = []
    for folder_name in PROJECT_WORKSPACE_FOLDERS:
        folder_path = project_dir / folder_name
        statuses.append(
            WorkspaceFolderStatus(
                name=folder_name,
                relative_path=f"{workspace_slug}/{folder_name}",
                exists=folder_path.is_dir(),
            )
        )
    return statuses
