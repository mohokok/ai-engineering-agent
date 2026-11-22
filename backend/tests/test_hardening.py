"""Tests for Step 20 hardening: loopback binding, strict CORS, upload traversal, error envelope, redacted rotating logs, repo secret scan, and backup/restore."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace
from typing import Any
import zipfile

from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.cli_backup import main as backup_cli_main
from app.core.config import Settings
from app.core.logging import get_log_file_path, record_audit_log_event
from app.core.security import (
    SECURITY_RESPONSE_HEADERS,
    find_key_like_strings,
    redact_client_and_secrets_for_log,
    sanitize_secret_text,
)
from app.main import create_app
from app.providers.secrets import SecretStore
from app.services.backup import BackupValidationError, verify_and_restore_backup


class _InMemorySecretStore(SecretStore):
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._keys: dict[str, str] = dict(initial or {})

    @property
    def backend_name(self) -> str:
        return "InMemoryTestKeyring"

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        self._keys[provider_name] = api_key

    def get_api_key(self, provider_name: str) -> str | None:
        return self._keys.get(provider_name)

    def delete_api_key(self, provider_name: str) -> None:
        self._keys.pop(provider_name, None)


def _test_settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(workspaces_dir=tmp_path / "workspaces", database_url="", **overrides)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_step20_security_loopback_cors_headers_and_upload_traversal_validation(tmp_path: Path) -> None:
    """Verify 127.0.0.1-only bind host, strict local CORS, security response headers, and upload/download traversal defenses."""
    assert Settings(workspaces_dir=tmp_path / "ws").backend_host == "127.0.0.1"
    with pytest.raises(ValidationError):
        Settings(workspaces_dir=tmp_path / "ws", backend_host="0.0.0.0")
    with pytest.raises(ValidationError):
        Settings(workspaces_dir=tmp_path / "ws", backend_host="192.168.1.20")
    with pytest.raises(ValidationError):
        Settings(workspaces_dir=tmp_path / "ws", cors_origins="*")
    with pytest.raises(ValidationError):
        Settings(workspaces_dir=tmp_path / "ws", cors_origins="https://remote.example.com")

    app = create_app(_test_settings(tmp_path, max_upload_size_bytes=2048), secret_store=_InMemorySecretStore())
    with TestClient(app) as client:
        ok_cors = client.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"})
        assert ok_cors.status_code == 200
        assert ok_cors.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
        for hdr, val in SECURITY_RESPONSE_HEADERS.items():
            assert ok_cors.headers.get(hdr.lower()) == val
        assert ok_cors.headers.get("x-correlation-id")

        bad_cors = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
        assert bad_cors.status_code == 200
        assert "access-control-allow-origin" not in {k.lower() for k in bad_cors.headers.keys()}

        proj_res = client.post(
            "/api/projects",
            json={"name": "Hardening Synthetic Project", "project_type": "clinic", "language": "ar"},
        )
        assert proj_res.status_code == 201
        pid = proj_res.json()["id"]

        # Traversal & disallowed extension on project file upload
        trav_up = client.post(
            f"/api/projects/{pid}/files",
            files={"files": ("../../escape.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )
        assert trav_up.status_code == 400
        assert trav_up.json()["error"]["correlation_id"]

        exe_up = client.post(
            f"/api/projects/{pid}/files",
            files={"files": ("payload.exe", b"MZ-not-allowed", "application/octet-stream")},
        )
        assert exe_up.status_code == 400

        # Traversal & disallowed extension & size cap on Standards upload
        std_trav = client.post(
            "/api/standards/upload",
            files={"file": ("../bad_std.txt", b"SYN-1000 test", "text/plain")},
        )
        assert std_trav.status_code == 422

        std_ext = client.post(
            "/api/standards/upload",
            files={"file": ("bad_script.sh", b"#!/bin/sh", "text/plain")},
        )
        assert std_ext.status_code == 422

        std_big = client.post(
            "/api/standards/upload",
            files={"file": ("oversized.txt", b"X" * 4096, "text/plain")},
        )
        assert std_big.status_code == 422

        # Register & backup download traversal guards
        reg_trav = client.get("/api/standards/register-files/..%5Csecret.txt")
        assert reg_trav.status_code in (400, 404)

        bak_trav = client.get("/api/system/backups/.._evil.zip/download")
        assert bak_trav.status_code == 400


def test_step20_error_envelope_correlation_id_no_stack_trace_and_gemini_graceful_errors(tmp_path: Path) -> None:
    """Verify consistent EN/AR error envelope with correlation_id, no 500 tracebacks to UI, and graceful Gemini errors."""
    fake_key = "AIza" + "SyFakeStep20TestKey9876543210"
    secret_store = _InMemorySecretStore({"gemini": fake_key})

    def _boom_client_factory(_api_key: str) -> Any:
        class _Models:
            def list(self) -> list[Any]:
                return []

            def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
                raise RuntimeError(f"503 UNAVAILABLE upstream overloaded for key={fake_key}")

        return SimpleNamespace(models=_Models())

    app = create_app(
        _test_settings(tmp_path),
        secret_store=secret_store,
        provider_client_factory=_boom_client_factory,
    )
    extra = APIRouter()

    @extra.get("/api/test-internal-boom")
    def _internal_boom() -> dict[str, str]:
        raise RuntimeError(f"Sensitive traceback path C:\\private\\db with secret {fake_key}")

    app.include_router(extra)

    with TestClient(app, raise_server_exceptions=False) as client:
        # 500 unhandled exception returns safe EN/AR JSON + correlation_id, ZERO traceback or secret
        boom = client.get("/api/test-internal-boom", headers={"X-Correlation-ID": "corr-step20-500"})
        assert boom.status_code == 500
        assert boom.headers.get("x-correlation-id") == "corr-step20-500"
        body = boom.json()
        assert body["correlation_id"] == "corr-step20-500"
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["message_ar"]
        assert "Traceback" not in json.dumps(body)
        assert fake_key not in json.dumps(body)

        # 404 preserves detail + adds bilingual envelope & correlation_id
        missing = client.get("/api/projects/does-not-exist")
        assert missing.status_code == 404
        m_body = missing.json()
        assert m_body["detail"]
        assert m_body["error"]["code"] == "NOT_FOUND"
        assert m_body["error"]["correlation_id"] == missing.headers["x-correlation-id"]

        # Gemini 503 unavailability handled gracefully without exposing API key
        gemini_err = client.post("/api/settings/provider/test", json={"complexity": "fast"})
        assert gemini_err.status_code == 503
        g_body = gemini_err.json()
        assert g_body["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert g_body["error"]["correlation_id"]
        assert fake_key not in json.dumps(g_body)

    log_path = get_log_file_path(tmp_path / "workspaces")
    assert log_path.is_file()
    log_text = log_path.read_text(encoding="utf-8")
    assert "corr-step20-500" in log_text
    assert fake_key not in log_text
    assert "[REDACTED" in log_text


def test_step20_secret_and_client_redaction_repo_logs_exports_and_audit_events(tmp_path: Path) -> None:
    """Verify sanitize_secret_text, repo-wide zero-key scan, keyring-only storage, client-data log redaction, and audit logs."""
    fake_google = "AIza" + "SyRepoCheckFake998877665544"
    fake_sk = "sk-" + "proj-fakeUnitTestSecret1234567890"
    fake_tvly = "tvly-" + "fakeSearchToken12345678"
    assert fake_google not in sanitize_secret_text(f"https://example.test/v1?key={fake_google}")
    assert fake_sk not in sanitize_secret_text(f"Authorization: Bearer {fake_sk}")
    assert fake_tvly not in sanitize_secret_text(f"x-api-key={fake_tvly}")
    assert "[REDACTED_EMAIL]" in redact_client_and_secrets_for_log("owner@client-domain.example")

    # Repo-wide check across tracked source/test/doc directories: zero key-like strings permitted.
    repo_root = Path(__file__).resolve().parents[2]
    _SAFE_TEST_PLACEHOLDER_MARKERS = ("Synthetic", "DO-NOT-LEAK", "never-log")
    for folder in ("backend/app", "backend/alembic", "backend/tests", "frontend/src", "docs", "scripts"):
        base = repo_root / folder
        if not base.exists():
            continue
        for fp in base.rglob("*"):
            if not fp.is_file() or "__pycache__" in fp.parts:
                continue
            if fp.suffix.lower() not in {".py", ".ts", ".tsx", ".md", ".bat", ".json"}:
                continue
            for line_no, line_txt in enumerate(fp.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                hits = find_key_like_strings(line_txt)
                if hits and folder == "backend/tests" and any(m in line_txt for m in _SAFE_TEST_PLACEHOLDER_MARKERS):
                    continue
                assert not hits, f"Key-like pattern {hits} detected in {fp}:{line_no}"

    settings = _test_settings(tmp_path)
    store = _InMemorySecretStore()
    app = create_app(settings, secret_store=store)
    with TestClient(app) as client:
        # Save key into mock keyring -> never appears in DB, API response, or logs
        save_res = client.put("/api/settings/provider/api-key", json={"api_key": fake_google})
        assert save_res.status_code == 200
        assert save_res.json()["api_key_configured"] is True
        assert fake_google not in json.dumps(save_res.json())

        # Create project + BOQ delete + Structural approve/export -> verify audit log + structured audit_event
        proj = client.post(
            "/api/projects",
            json={"name": "Synthetic Confidential Client Site", "project_type": "clinic", "language": "ar"},
        ).json()
        pid = proj["id"]

        boq = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={"title": "BOQ Audit Test"},
        ).json()
        for item_payload in (
            {
                "item_no": "A-01",
                "description": "Synthetic Slab",
                "unit": "m2",
                "quantity": 10.0,
                "unit_rate": 50.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner Baseline Quote",
            },
            {
                "item_no": "A-02",
                "description": "Synthetic Beam",
                "unit": "m3",
                "quantity": 2.0,
                "unit_rate": 100.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner Baseline Quote",
            },
        ):
            boq = client.post(f"/api/boq-sheets/{boq['id']}/items", json=item_payload).json()
        del_target = boq["items"][1]["id"]
        del_res = client.delete(f"/api/boq-sheets/{boq['id']}/items/{del_target}")
        assert del_res.status_code == 200

        st = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "assessment_type": "simple_statics_beam",
                "title": "Synthetic Audit Beam",
                "language": "en",
                "inputs": {
                    "beams": [
                        {
                            "beam_id": "BM-1",
                            "support_condition": "simply_supported_udl",
                            "span_m": 4.0,
                            "factored_load_kn_or_knm": 10.0,
                        }
                    ]
                },
            },
        ).json()
        assert client.post(f"/api/structural-assessments/{st['id']}/approve", json={"approved_by": "PE"}).status_code == 200
        exp = client.post(f"/api/structural-assessments/{st['id']}/export", json={"language": "en"})
        assert exp.status_code == 201
        pdf_path = (tmp_path / "workspaces" / proj["workspace_slug"] / exp.json()["pdf_deliverable"]["relative_path"])
        assert not find_key_like_strings(pdf_path.read_bytes().decode("latin1", errors="ignore"))

        # Emit client-text extra via audit helper -> verify redacted before log file write
        record_audit_log_event(
            action="test.redaction_check",
            entity_type="test",
            entity_id="t1",
            details={"prompt": "STRICTLY CONFIDENTIAL PROMPT TEXT", "contact": "engineer@private.example"},
        )

        # Log viewer-free design: no HTTP endpoint exposes raw logs
        assert client.get("/api/system/logs").status_code == 404
        sys_info = client.get("/api/system/info").json()
        assert sys_info["log_viewer_enabled"] is False
        assert sys_info["remote_log_shipping"] is False
        assert sys_info["backup_excludes_keyring"] is True

    # Inspect SQLite DB & log file directly: key NEVER persisted; client prompt redacted; audit events logged
    db_file = tmp_path / "workspaces" / "engineering_agent.db"
    assert fake_google not in db_file.read_bytes().decode("latin1", errors="ignore")
    conn = sqlite3.connect(str(db_file))
    actions = [r[0] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    conn.close()
    assert "boq.item_deleted" in actions
    assert "structural_assessment_approved" in actions
    assert "structural_assessment_exported" in actions

    log_content = get_log_file_path(tmp_path / "workspaces").read_text(encoding="utf-8")
    assert fake_google not in log_content
    assert "STRICTLY CONFIDENTIAL PROMPT TEXT" not in log_content
    assert "[REDACTED_CLIENT_DATA]" in log_content
    assert "[REDACTED_EMAIL]" in log_content
    assert "structural_assessment_exported" in log_content


def test_step20_backup_wipe_restore_sha256_manifest_dry_run_cli_and_zip_slip_guard(tmp_path: Path) -> None:
    """Create verified ZIP+SHA-256 backup (no keyring), test dry-run + tamper + Zip Slip rejection, wipe temp workspace, restore via CLI, and match SHA-256."""
    fake_api_key = "AIza" + "SyBackupExcludeTestKey55443322"
    store = _InMemorySecretStore({"gemini": fake_api_key})
    ws_dir = tmp_path / "workspaces"
    app = create_app(_test_settings(tmp_path), secret_store=store)

    original_hashes: dict[str, str] = {}
    proj_slug = ""
    backup_filename = ""
    backup_path = Path()

    with TestClient(app) as client:
        assert client.put("/api/settings/provider/api-key", json={"api_key": fake_api_key}).status_code == 200
        proj = client.post(
            "/api/projects",
            json={"name": "Backup Restore Synthetic Project", "project_type": "clinic", "language": "en"},
        ).json()
        pid = proj["id"]
        proj_slug = proj["workspace_slug"]

        up_res = client.post(
            f"/api/projects/{pid}/files",
            files={"files": ("site_notes.txt", b"Synthetic engineering input v1", "text/plain")},
        )
        assert up_res.status_code == 201
        rel_file = up_res.json()["items"][0]["file"]["stored_relative_path"]
        orig_sha = up_res.json()["items"][0]["file"]["sha256"]
        original_hashes[rel_file] = orig_sha

        bak_res = client.post("/api/system/backup", json={"label": "step20check"})
        assert bak_res.status_code == 201
        bak_body = bak_res.json()
        assert bak_body["excludes_keyring"] is True
        assert bak_body["includes_database"] is True
        backup_filename = bak_body["backup"]["filename"]
        backup_path = ws_dir / "_backups" / backup_filename
        assert backup_path.is_file()

        # Verify keyring secret is nowhere inside archive
        with zipfile.ZipFile(backup_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert manifest["excludes_keyring"] is True
            for info in zf.infolist():
                if not info.is_dir():
                    raw = zf.read(info.filename).decode("latin1", errors="ignore")
                    assert fake_api_key not in raw

        # Dry-run verify through API
        dry_api = client.post(
            "/api/system/restore",
            json={"backup_filename": backup_filename, "dry_run": True},
        )
        assert dry_api.status_code == 200
        assert dry_api.json()["valid"] is True
        assert dry_api.json()["restored"] is False
        assert dry_api.json()["verified_files_count"] >= 2

    # Move verified archive safely outside workspace before wiping temp workspace completely
    external_archive = tmp_path / backup_filename
    external_archive.write_bytes(backup_path.read_bytes())

    # Tampers check: corrupt 1 byte inside copied archive -> dry-run reports mismatch & restore fails
    tampered_zip = tmp_path / "tampered.zip"
    with zipfile.ZipFile(external_archive, "r") as zin, zipfile.ZipFile(tampered_zip, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("workspace/") and not info.is_dir():
                data = b"CORRUPTED-" + data
            zout.writestr(info.filename, data)
    tamper_dry = verify_and_restore_backup(
        archive_path=tampered_zip,
        target_workspaces_dir=ws_dir,
        target_database_url=f"sqlite:///{(ws_dir / 'engineering_agent.db').as_posix()}",
        dry_run=True,
    )
    assert tamper_dry.valid is False
    assert len(tamper_dry.mismatched_files) == 1
    with pytest.raises(BackupValidationError):
        verify_and_restore_backup(
            archive_path=tampered_zip,
            target_workspaces_dir=ws_dir,
            target_database_url=f"sqlite:///{(ws_dir / 'engineering_agent.db').as_posix()}",
            dry_run=False,
        )

    # Zip Slip path traversal check
    slip_zip = tmp_path / "zip_slip.zip"
    with zipfile.ZipFile(slip_zip, "w") as zslip:
        zslip.writestr("../../outside.txt", b"malicious")
    with pytest.raises(BackupValidationError):
        verify_and_restore_backup(
            archive_path=slip_zip,
            target_workspaces_dir=ws_dir,
            target_database_url=f"sqlite:///{(ws_dir / 'engineering_agent.db').as_posix()}",
            dry_run=True,
        )

    # Wipe temp workspace & database completely
    for p in ws_dir.rglob("*"):
        if p.is_file():
            p.chmod(stat.S_IWRITE | stat.S_IREAD)
    import shutil
    shutil.rmtree(ws_dir)
    assert not ws_dir.exists()

    # CLI Dry-run & CLI Restore
    rc_dry = backup_cli_main(["restore", "--archive", str(external_archive), "--workspaces-dir", str(ws_dir), "--dry-run"])
    assert rc_dry == 0
    assert not ws_dir.exists()

    rc_restore = backup_cli_main(["restore", "--archive", str(external_archive), "--workspaces-dir", str(ws_dir)])
    assert rc_restore == 0

    # Compare restored workspace file SHA-256 and read-only lock + restored DB records
    for rel_path, expected_sha in original_hashes.items():
        restored_file = ws_dir / proj_slug / rel_path
        assert restored_file.is_file()
        assert _sha256_bytes(restored_file.read_bytes()) == expected_sha

    restored_app = create_app(_test_settings(tmp_path), secret_store=store)
    with TestClient(restored_app) as restored_client:
        projects = restored_client.get("/api/projects").json()["projects"]
        assert len(projects) == 1
        assert projects[0]["name"] == "Backup Restore Synthetic Project"
