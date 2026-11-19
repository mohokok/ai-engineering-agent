"""Tests for multi-file upload, SHA-256 hashing, read-only originals, versioning, and security."""

import hashlib
from pathlib import Path
import stat
from typing import get_args

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.base import CLASSIFICATION_LABELS
from app.db.models import AuditLog, FileVersion
from app.main import create_app
from app.schemas.projects import ProjectClassification
from app.services.files import UnsafeFilenameError, validate_upload_filename


def _test_settings(
    tmp_path: Path,
    *,
    max_upload_size_bytes: int = 50 * 1024 * 1024,
    max_files_per_upload: int = 25,
) -> Settings:
    return Settings(
        workspaces_dir=tmp_path / "workspaces",
        database_url="",
        max_upload_size_bytes=max_upload_size_bytes,
        max_files_per_upload=max_files_per_upload,
    )


def _create_sample_project(client: TestClient) -> dict:
    resp = client.post(
        "/api/projects",
        json={"name": "مجمع عيادات بنغازي", "code": "CLN-03"},
    )
    assert resp.status_code == 201
    return resp.json()


def test_classification_labels_match_schema() -> None:
    """Pydantic ProjectClassification Literal stays synced with CLAUDE.md DB CHECK labels."""
    assert get_args(ProjectClassification) == CLASSIFICATION_LABELS


def test_multi_file_upload_classification_readonly_and_download(tmp_path: Path) -> None:
    """Uploading PDF, DOCX, XLSX, DXF, and PNG together classifies folders, hashes, and locks originals."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)

    payloads = {
        "brief.pdf": (b"%PDF-1.4\nSample brief content", "application/pdf", "01_Input_Documents"),
        "specs.docx": (b"PK\x03\x04DOCX_BYTES", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "01_Input_Documents"),
        "boq.xlsx": (b"PK\x03\x04XLSX_BYTES", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "01_Input_Documents"),
        "ground_floor.dxf": (b"0\nSECTION\n2\nENTITIES\n0\nEOF\n", "application/dxf", "02_Original_Drawings"),
        "site_photo.png": (b"\x89PNG\r\n\x1a\nPNGDATA", "image/png", "02_Original_Drawings"),
    }

    with TestClient(app) as client:
        project = _create_sample_project(client)
        project_id = project["id"]

        multipart = [
            ("files", (name, data, mime))
            for name, (data, mime, _) in payloads.items()
        ]
        upload_resp = client.post(f"/api/projects/{project_id}/files", files=multipart)
        assert upload_resp.status_code == 201
        body = upload_resp.json()
        assert body["created_count"] == 5
        assert body["new_version_count"] == 0
        assert body["duplicate_count"] == 0

        by_name = {item["filename"]: item for item in body["items"]}
        for name, (data, _, expected_folder) in payloads.items():
            item = by_name[name]
            assert item["outcome"] == "created"
            file_rec = item["file"]
            assert file_rec["folder_name"] == expected_folder
            assert file_rec["current_version"] == 1
            assert file_rec["is_original"] is True
            assert file_rec["classification"] == "Preliminary"
            assert file_rec["size_bytes"] == len(data)
            assert file_rec["sha256"] == hashlib.sha256(data).hexdigest()

            disk_path = (
                settings.workspaces_dir
                / project["workspace_slug"]
                / file_rec["stored_relative_path"]
            )
            assert disk_path.is_file()
            assert (disk_path.stat().st_mode & stat.S_IWRITE) == 0
            with pytest.raises(PermissionError):
                with open(disk_path, "wb") as fh:
                    fh.write(b"tamper")

            # Verify download endpoint returns exact bytes
            dl = client.get(f"/api/files/{file_rec['id']}/download")
            assert dl.status_code == 200
            assert dl.content == data

        # Originals cannot be modified or deleted via API
        sample_file_id = by_name["brief.pdf"]["file"]["id"]
        for method in ("put", "patch", "delete"):
            res = getattr(client, method)(f"/api/files/{sample_file_id}")
            assert res.status_code == 403
            res_nested = getattr(client, method)(
                f"/api/projects/{project_id}/files/{sample_file_id}"
            )
            assert res_nested.status_code == 403

        list_resp = client.get(f"/api/projects/{project_id}/files")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 5

        with app.state.session_factory() as db:
            logs = db.scalars(
                select(AuditLog).where(
                    AuditLog.project_id == project_id,
                    AuditLog.action == "file.uploaded",
                )
            ).all()
            assert len(logs) == 5


def test_duplicate_detection_and_reupload_versioning_preserves_original(tmp_path: Path) -> None:
    """Identical uploads deduplicate while changed re-uploads create v2 without touching v1."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    v1_bytes = b"%PDF-1.4\nOriginal version 1 bytes"
    v2_bytes = b"%PDF-1.4\nUpdated version 2 bytes with revisions"

    with TestClient(app) as client:
        project = _create_sample_project(client)
        project_id = project["id"]

        # Upload Arabic filename v1
        r1 = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("تقرير_تربة.pdf", v1_bytes, "application/pdf"))],
        )
        assert r1.status_code == 201
        file_id = r1.json()["items"][0]["file"]["id"]
        original_rel = r1.json()["items"][0]["file"]["stored_relative_path"]
        original_path = settings.workspaces_dir / project["workspace_slug"] / original_rel
        assert original_path.read_bytes() == v1_bytes

        # 1. Exact duplicate same filename -> skipped
        r_dup_same = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("تقرير_تربة.pdf", v1_bytes, "application/pdf"))],
        )
        assert r_dup_same.status_code == 201
        assert r_dup_same.json()["duplicate_count"] == 1
        assert r_dup_same.json()["items"][0]["outcome"] == "duplicate"

        # 2. Content duplicate under another filename -> detected and skipped
        r_dup_renamed = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("copy_soil_report.pdf", v1_bytes, "application/pdf"))],
        )
        assert r_dup_renamed.status_code == 201
        assert r_dup_renamed.json()["duplicate_count"] == 1
        assert r_dup_renamed.json()["items"][0]["duplicate_of_file_id"] == file_id

        # 3. Re-upload changed bytes -> creates v2, original v1 untouched
        r_v2 = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("تقرير_تربة.pdf", v2_bytes, "application/pdf"))],
        )
        assert r_v2.status_code == 201
        v2_body = r_v2.json()
        assert v2_body["new_version_count"] == 1
        v2_file = v2_body["items"][0]["file"]
        assert v2_file["current_version"] == 2
        assert v2_file["sha256"] == hashlib.sha256(v2_bytes).hexdigest()
        assert v2_file["stored_relative_path"].startswith("12_Revision_History/")

        # v1 on disk MUST remain completely untouched with v1 bytes and read-only mode
        assert original_path.read_bytes() == v1_bytes
        assert (original_path.stat().st_mode & stat.S_IWRITE) == 0

        # Version history endpoint lists v2 and v1
        ver_resp = client.get(f"/api/files/{file_id}/versions")
        assert ver_resp.status_code == 200
        versions = ver_resp.json()["versions"]
        assert [v["version_number"] for v in versions] == [2, 1]

        # Download both v1 original and v2 latest cleanly
        dl_v1 = client.get(f"/api/files/{file_id}/download?version=1")
        dl_v1_alt = client.get(f"/api/files/{file_id}/versions/1/download")
        dl_v2 = client.get(f"/api/files/{file_id}/download")
        assert dl_v1.status_code == 200 and dl_v1.content == v1_bytes
        assert dl_v1_alt.status_code == 200 and dl_v1_alt.content == v1_bytes
        assert dl_v2.status_code == 200 and dl_v2.content == v2_bytes


def test_malicious_filenames_unsupported_types_and_size_protections(tmp_path: Path) -> None:
    """Reject traversal names, unsupported extensions, empty files, and oversized uploads cleanly."""
    settings = _test_settings(tmp_path, max_upload_size_bytes=1024, max_files_per_upload=3)
    app = create_app(settings)

    with pytest.raises(UnsafeFilenameError):
        validate_upload_filename(r"C:\temp\bad.pdf")
    with pytest.raises(UnsafeFilenameError):
        validate_upload_filename("bad\x00file.pdf")

    with TestClient(app) as client:
        project = _create_sample_project(client)
        project_id = project["id"]

        for bad_name in (
            r"..\..\x",
            r"..\..\secret.pdf",
            "../escape.pdf",
            "subdir/plan.pdf",
            "C:bad.pdf",
            "plan.pdf:stream",
            "CON.pdf",
            ".hidden.pdf",
        ):
            resp = client.post(
                f"/api/projects/{project_id}/files",
                files=[("files", (bad_name, b"payload", "application/pdf"))],
            )
            assert resp.status_code == 400, f"Expected 400 for {bad_name!r}, got {resp.status_code}"

        # Atomic batch guard: valid + malicious filename in one batch writes nothing
        atomic_resp = client.post(
            f"/api/projects/{project_id}/files",
            files=[
                ("files", ("good.pdf", b"%PDF-1.4\nok", "application/pdf")),
                ("files", (r"..\..\x", b"bad", "application/octet-stream")),
            ],
        )
        assert atomic_resp.status_code == 400
        assert client.get(f"/api/projects/{project_id}/files").json()["total"] == 0

        # Unsupported extension rejected
        exe_resp = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("payload.exe", b"MZ...", "application/octet-stream"))],
        )
        assert exe_resp.status_code == 400

        # Empty file rejected
        empty_resp = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("empty.pdf", b"", "application/pdf"))],
        )
        assert empty_resp.status_code == 400

        # Oversized file rejected with 413 and staging cleaned
        big_resp = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("large.pdf", b"x" * 2048, "application/pdf"))],
        )
        assert big_resp.status_code == 413

        # Too many files rejected with 400
        too_many_resp = client.post(
            f"/api/projects/{project_id}/files",
            files=[
                ("files", (f"f{i}.txt", b"hello", "text/plain"))
                for i in range(4)
            ],
        )
        assert too_many_resp.status_code == 400

        # Supported extensions metadata endpoint returns expected allowlist
        ext_resp = client.get("/api/files/supported-extensions")
        assert ext_resp.status_code == 200
        ext_data = ext_resp.json()
        exts = {item["extension"]: item["target_folder"] for item in ext_data["extensions"]}
        assert exts[".pdf"] == "01_Input_Documents"
        assert exts[".dxf"] == "02_Original_Drawings"
        assert ".exe" in ext_data["explicitly_unsupported_examples"]

        # Verify staging folder has zero leftovers
        project_dir = settings.workspaces_dir / project["workspace_slug"]
        assert not (project_dir / ".upload_staging").exists() or not any(
            (project_dir / ".upload_staging").iterdir()
        )


def test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps(
    tmp_path: Path,
) -> None:
    """Verify early 413 guard, 409/400 mappings, allowlist mime_hint, and Plan Rev..A.pdf."""
    settings = _test_settings(tmp_path, max_upload_size_bytes=512, max_files_per_upload=2)
    app = create_app(settings)

    with TestClient(app) as client:
        project = _create_sample_project(client)
        project_id = project["id"]

        # 1. Early Content-Length > MAX_FILES_PER_UPLOAD * MAX_UPLOAD_SIZE_BYTES (2 * 512 = 1024)
        # Rejects before multipart parsing even touches a corrupt body.
        early_413 = client.post(
            f"/api/projects/{project_id}/files",
            headers={
                "Content-Type": "multipart/form-data; boundary=notparsed",
                "Content-Length": "1025",
            },
            content=b"unparsed-corrupt-multipart-body",
        )
        assert early_413.status_code == 413

        # 2. Double dot inside filename (not a whole '..' path segment) is allowed
        rev_resp = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("Plan Rev..A.pdf", b"%PDF-1.4\nrevA", "text/html"))],
        )
        assert rev_resp.status_code == 201
        rev_file = rev_resp.json()["items"][0]["file"]
        assert rev_file["original_filename"] == "Plan Rev..A.pdf"

        # 3. Stored and served MIME type strictly uses allowlist mime_hint, ignoring spoofed text/html
        assert rev_file["mime_type"] == "application/pdf"
        dl_rev = client.get(f"/api/files/{rev_file['id']}/download")
        assert dl_rev.status_code == 200
        assert dl_rev.headers["content-type"].startswith("application/pdf")
        assert dl_rev.content == b"%PDF-1.4\nrevA"

        # 4. FileExistsError -> HTTP 409 when target file already exists on disk unmanaged
        preexisting = (
            settings.workspaces_dir
            / project["workspace_slug"]
            / "01_Input_Documents"
            / "conflict.pdf"
        )
        preexisting.write_bytes(b"unmanaged-existing-file")
        conflict_resp = client.post(
            f"/api/projects/{project_id}/files",
            files=[("files", ("conflict.pdf", b"%PDF-1.4\nnew", "application/pdf"))],
        )
        assert conflict_resp.status_code == 409

        # 5. ValueError from resolve_project_file_path -> HTTP 400 on tampered relative path
        with app.state.session_factory() as db:
            ver_row = db.scalar(
                select(FileVersion).where(FileVersion.file_id == rev_file["id"])
            )
            assert ver_row is not None
            ver_row.stored_relative_path = "../../outside.pdf"
            db.commit()

        bad_path_dl = client.get(f"/api/files/{rev_file['id']}/download")
        assert bad_path_dl.status_code == 400

        # 6. Chunked upload without Content-Length skips early middleware and still fails per-file 413
        boundary = "chunkedboundary"
        raw_part = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="chunked_big.pdf"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode("ascii") + (b"x" * 700) + f"\r\n--{boundary}--\r\n".encode("ascii")

        def chunk_stream():
            for start in range(0, len(raw_part), 128):
                yield raw_part[start : start + 128]

        chunked_resp = client.post(
            f"/api/projects/{project_id}/files",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            content=chunk_stream(),
        )
        assert chunked_resp.status_code == 413
