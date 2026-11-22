# Step 20 — Security Hardening, Error Handling, Structured Logging & Backup/Restore

- **Date:** 2026-11-22
- **Status:** **PARTIAL** *(Delivers Step 20 hardening across security, error handling, structured rotating local logging, and SHA-256 backup/restore with **zero new DB schema migrations** (`0017` remains head): backend binds strictly to `127.0.0.1` only with strict local `http://127.0.0.1` / `http://localhost` CORS and explicit allowed methods/headers; HTTP response security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control`, `Permissions-Policy`, `Content-Security-Policy`, `X-Correlation-ID`) on every response including 413/500 errors; upload validation & path-traversal containment across file uploads, Standards Library chunked uploads, register downloads, and backup archives; extended `sanitize_secret_text` + repo/log/export/DB zero-key test (`test_hardening.py`); bilingual EN/AR JSON error envelope (`detail` + `error` + `correlation_id`) hiding 500 stack traces from UI while logging redacted diagnostics internally; rotating UTF-8 JSONL local log `<workspaces_dir>/agent.log` (`5 MB x 5`) with secret/client-data redaction, log-viewer-free design (no HTTP log viewer or remote shipping), and automatic SQLAlchemy `AuditLog` -> `app.audit` structured log bridge (plus added missing `AuditLog` entries for BOQ deletion, Step 18/19 approvals/exports, and backup/restore); timestamped workspace+DB ZIP backups using SQLite online `backup()` + SHA-256 `manifest.json` + `--dry-run` / wipe+restore CLI (`python -m app.cli_backup`) excluding OS keyring/API keys; bilingual EN/AR RTL/LTR Settings/System panel (`SystemHardeningPanel.tsx`); report-only Python OSV (`pip`) & `npm audit` dependency audits; `110 passed, 4 skipped` full backend `pytest -v`, `30 passed` frontend Vitest + `tsc --noEmit` + Vite build (`710ms`), and clean `gitleaks` scans; live browser visual UI & manual restore walkthrough remain `PENDING`.)*
- **Branch:** `step-20-hardening`
- **Depends on:** Step 19 (`15cd89b`, PR `#28` merged)

## 1. Scope Done

1. **Security Hardening (`backend/app/core/config.py`, `core/security.py`, `main.py`, `services/standards.py`, `providers/base.py`):**
   - **Loopback-Only Binding & Strict Local CORS:** `Settings.validate_loopback_host` rejects any non-`127.0.0.1` bind host (`0.0.0.0`, LAN IPs), and `Settings.validate_strict_local_cors` restricts CORS origins strictly to explicit `http://127.0.0.1[:port]` / `http://localhost[:port]` URLs (rejecting `*` and remote hosts). Tightened `CORSMiddleware` in `backend/app/main.py` to explicit methods (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`) and headers (`Content-Type`, `Accept`, `X-Correlation-ID`, `Authorization`).
   - **Security Headers & Early 413 Guard:** `HardeningAndLoggingMiddleware` attaches `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `Permissions-Policy`, `Content-Security-Policy`, and `X-Correlation-ID` to every response. `UploadSizeLimitMiddleware` now guards both `/api/projects/{id}/files` and `/api/standards/upload` before multipart body buffering.
   - **Upload & Download Containment:** `upload_standard_document` streams in 64 KB chunks enforcing `settings.max_upload_size_bytes` and catching both `UnsafeFilenameError` and `UnsupportedFileTypeError`; `resolve_register_file_download` upgraded from prefix string checks to `path.is_relative_to(root)`.
   - **Extended Secret Redaction & Keyring Isolation:** `sanitize_secret_text` (`core/security.py`, re-exported via `providers/base.py`) scrubs query parameters (`key`, `api_key`, `token`, `secret`), headers (`Authorization`, `x-goog-api-key`, `x-api-key`), bearer tokens, `AIza*`, `sk-*`, `tvly-*`, `ghp_*`, `github_pat_*`, and PEM private key blocks. API keys remain strictly inside `SecretStore` (`Windows Credential Manager`) and never enter DB, HTTP responses, logs, exports, or backups.

2. **Bilingual Safe Error Handling (`backend/app/core/errors.py`, `backend/app/main.py`, `frontend/src/api.ts`):**
   - Registered consistent FastAPI handlers for `StarletteHTTPException`, `RequestValidationError` (via `jsonable_encoder` safely serializing Pydantic `ValueError` instances), and unhandled `Exception` (`HTTP 500`), propagating `X-Correlation-ID` across `ServerErrorMiddleware`.
   - Every error response keeps `detail` for existing clients while adding `error: {code, message, message_ar, correlation_id, status}` + `correlation_id`. Unhandled 500s return generic safe EN/AR messages with `correlation_id` and **zero** Python stack traces or file paths, logging redacted exception tracebacks only to local `agent.log`.
   - Updated `extractErrorMessage` in `frontend/src/api.ts` to format friendly Arabic/English error messages with `[ref: <correlation_id>]`, stripping any traceback lines cleanly, and preserved Step 04 Gemini 401/429/503 failure handling.

3. **Structured Rotating Local Logging & Audit Bridge (`backend/app/core/logging.py`, `db/session.py`, `services/{boq,specialist,structural}.py`):**
   - Configured `RotatingFileHandler` (`5 MB` x `5` backups, UTF-8 JSONL) at `<workspaces_dir>/agent.log` (closed cleanly in app lifespan teardown to avoid Windows temp-folder locks), scrubbed by `SecretAndClientRedactionFilter` (redacting keys, emails, and sensitive client keys like `prompt`, `raw_text`, `content`, `extracted_text`, `owner_notes`).
   - Enforced log-viewer-free design (`log_viewer_enabled: false`, `remote_log_shipping: false`, no HTTP log endpoint).
   - Bridged SQLAlchemy `after_commit` on `create_session_factory` to emit committed `AuditLog` entries via `record_audit_log_event` automatically, and added missing `AuditLog` records on `delete_boq_item` (`boq.item_deleted`), `approve_specialist_assessment` / `export_specialist_deliverables`, `approve_structural_assessment` / `export_structural_deliverables`, and backup/restore actions.

4. **Backup & Verified Restore (`backend/app/services/backup.py`, `backend/app/cli_backup.py`, `backend/app/api/system.py`, `frontend/src/components/SystemHardeningPanel.tsx`):**
   - Archives consistent transactional SQLite snapshots (`sqlite3.Connection.backup()`) + workspace project files into timestamped `<workspaces_dir>/_backups/backup_*.zip` + `.sha256` sidecars with embedded SHA-256 `manifest.json` (`excludes_keyring: true`), skipping `_backups/`, `agent.log*`, `.upload_staging/`, and `.env*`.
   - `verify_and_restore_backup` + `python -m app.cli_backup` validate Zip Slip path bounds and recompute SHA-256 of every archived entry and DB snapshot on `--dry-run` before touching disk, restoring original folders read-only cleanly.
   - Added bilingual EN/AR RTL/LTR **Step 20: System Security, Local Log Location & Backup/Restore** panel inside `ProviderSettingsView` showing bind host, strict CORS, local `agent.log` path, keyring exclusion notice, one-click backup creation, ZIP download, dry-run verify, and confirmed restore.

## 2. Files Created / Changed

### Created
- `<repo>/backend/app/api/system.py`
- `<repo>/backend/app/cli_backup.py`
- `<repo>/backend/app/core/errors.py`
- `<repo>/backend/app/core/logging.py`
- `<repo>/backend/app/core/security.py`
- `<repo>/backend/app/schemas/system.py`
- `<repo>/backend/app/services/backup.py`
- `<repo>/backend/tests/test_hardening.py`
- `<repo>/docs/reports/step-20.md`
- `<repo>/frontend/src/components/SystemHardeningPanel.tsx`

### Changed
- `<repo>/backend/app/core/config.py` *(added `validate_loopback_host` and `validate_strict_local_cors` validators)*
- `<repo>/backend/app/db/session.py` *(bridged committed `AuditLog` rows cleanly into `record_audit_log_event` via SQLAlchemy session events)*
- `<repo>/backend/app/main.py` *(added `HardeningAndLoggingMiddleware`, expanded `UploadSizeLimitMiddleware` to `/api/standards/upload`, tightened `CORSMiddleware`, wired unified EN/AR exception handlers, mounted `system_router`, and managed rotating log handle lifecycle)*
- `<repo>/backend/app/providers/base.py` *(re-exported extended `sanitize_secret_text` from `app.core.security`)*
- `<repo>/backend/app/services/boq.py` *(recorded `AuditLog` `boq.item_deleted` using `item.item_no` in `delete_boq_item`)*
- `<repo>/backend/app/services/specialist.py` *(recorded `AuditLog` entries on approve and export)*
- `<repo>/backend/app/services/standards.py` *(bounded 64 KB chunk streaming on standard uploads + `is_relative_to` containment check)*
- `<repo>/backend/app/services/structural.py` *(recorded `AuditLog` entries on approve and export)*
- `<repo>/docs/DECISIONS.md` *(appended `ADR-029`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 20 `SystemHardeningPanel` EN/AR SSR, bilingual `extractErrorMessage`, and `/api/system/*` Vitest tests)*
- `<repo>/frontend/src/App.tsx` *(updated subtitle & `settingsTab` keeping `"إعدادات Gemini والمزودين والنظام"`)*
- `<repo>/frontend/src/api.ts` *(added bilingual `extractErrorMessage` + `getSystemInfo`, `createSystemBackup`, `restoreSystemBackup`, `getBackupDownloadUrl`)*
- `<repo>/frontend/src/components/ProviderSettingsView.tsx` *(embedded `<SystemHardeningPanel />`)*
- `<repo>/frontend/src/types.ts` *(added Step 20 TypeScript interfaces)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero new Alembic migrations needed; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Dependency Vulnerability Audit (Report-Only — Zero Auto-Upgrades)

No auto-upgrades or `npm audit fix` / package bumps were applied so pinned dependency versions and passing suites remain intact:

1. **Backend Python Environment (`87` installed `.venv` packages checked via `pip check` + read-only OSV.dev PyPI batch query):**
   - `python -m pip check`: `No broken requirements found.`
   - **Production runtime libraries (`fastapi==0.164.0`, `uvicorn==0.54.0`, `sqlalchemy==2.1.9`, `alembic==1.20.1`, `pydantic-settings==2.16.3`, `google-genai==3.6.1`, `keyring==25.7.0`, `pymupdf==2.1`, `pdfplumber==0.11.10`, `python-docx==1.2.0`, `openpyxl==3.1.5`, `ezdxf==1.4.5`, `ifcopenshell==0.9.0.post1`, `cryptography==50.0.2`, `httpx2==2.16.2`, `urllib3==2.8.0`, `requests==2.34.2`):** **`0` known vulnerabilities.**
   - **Build / test tooling advisories (`14` OSV records / `7` distinct CVEs across `pip` and `pytest`):**
     - `pip==25.0.1` (packaging tool, not exposed at runtime): `CVE-2025-8869` / `GHSA-4xh5-x5gv-qwph`, `CVE-2026-3219` / `GHSA-58qw-9mgm-455v`, `CVE-2026-1703` / `GHSA-6vgw-5pg2-w6jp`, `CVE-2026-6357` / `GHSA-jp4c-xjxw-mgf9`, `CVE-2026-13346` / `GHSA-qwm4-qh6w-59xr`, `CVE-2026-8643` / `GHSA-wf93-45jw-7689`.
     - `pytest==8.4.2` (dev/test runner only): `CVE-2025-71176` / `GHSA-6w46-j5rx-g56g` (`tmpdir` handling).

2. **Frontend Node Environment (`cd frontend; npm.cmd audit --json`):**
   - **Production dependencies (`6` packages: `react`, `react-dom`, etc.):** **`0` vulnerabilities.**
   - **Dev-only tooling (`6` advisories: `3` moderate, `1` high, `2` critical):** `vitest` (`<=4.1.10`), `vite` (`<=6.4.3`), `@vitest/mocker`, `esbuild` (`<=0.24.2`), `tinypool` (`<=2.1.1`), `vite-node` (`<=2.2.0-beta.2`). All reported fixes require a breaking semver-major bump to `vitest@5.1.1`.
   - **Residual Risks & Mitigations:**
     1. Vite dev server / Vitest advisories affect local development server exposure; mitigated in part because Vite binds to `127.0.0.1` (`vite.config.ts`) and production builds emit static bundles.
     2. Built-in `pip` / `pytest` advisories are offline dev/install-time only; never expose `pip` or test runners to untrusted external inputs.
     3. SQLite `engineering_agent.db` is unencrypted on local NTFS; relied on local Windows account NTFS permissions, local `127.0.0.1` binding, and keeping all API credentials strictly outside the database inside Windows Credential Manager (`keyring`).

## 4. Tests Run (Exact Observed Results & Hygiene Checks)

### Full Backend Suite (`pytest -v`, after final code edit) & Pre-Finalization Targeted Checks
```text
> .\backend\.venv\Scripts\pytest.exe backend/tests -v
================= 110 passed, 4 skipped in 243.00s (0:04:02) ==================
```
*(All 4 new tests in `backend/tests/test_hardening.py` — `test_step20_security_loopback_cors_headers_and_upload_traversal_validation`, `test_step20_error_envelope_correlation_id_no_stack_trace_and_gemini_graceful_errors`, `test_step20_secret_and_client_redaction_repo_logs_exports_and_audit_events`, and `test_step20_backup_wipe_restore_sha256_manifest_dry_run_cli_and_zip_slip_guard` — plus all 106 prior regression tests passed without weakening any assertion; the 4 skipped are pre-existing opt-in live external tool/network tests.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`, after final edit)
```text
> cd frontend; npm.cmd test; npm.cmd run build
 ✓ src/App.test.tsx (30 tests) 106ms
 Test Files  1 passed (1) | Tests  30 passed (30) | Duration  1.10s
 tsc --noEmit && vite build -> 45 modules transformed -> built in 710ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- `.\backend\.venv\Scripts\python.exe -m pip check`: `No broken requirements found.`
- UTF-8 BOM check: `BOM_FILES: []`.
- Local-path check across `backend`, `frontend/src`, `docs`, `scripts`: `LOCAL_PATH_LEAKS: []`.
- `gitleaks dir` across `backend/app`, `backend/tests`, `frontend/src`, `docs`, `scripts`: `no leaks found` (and `gitleaks detect --source . --no-banner -v` run across git history on commit).

## 5. Decisions Made
- Recorded **`ADR-029`** in `<repo>/docs/DECISIONS.md` covering zero new migrations, `127.0.0.1`-only binding + strict local CORS + security headers + chunked upload bounds, backward-compatible bilingual `detail` + `error` + `correlation_id` error envelope, log-viewer-free `workspaces_dir/agent.log` rotating JSONL with secret/client-data redaction + `AuditLog` emission, SQLite-online-backup + workspace ZIP/SHA-256 CLI/UI backup & dry-run restore (keyring excluded), and report-only dependency audits.

## 6. Known Limitations & Owner Review Needed
1. **Live Browser & Disaster-Recovery UI Walkthrough (`PENDING` owner check):** Automated tests cover `127.0.0.1`/CORS enforcement, traversal rejection, HTTP 500 trace hiding, redacted log output, keyring isolation, tamper/Zip Slip detection, full workspace wipe + CLI restore SHA-256 verification, and Vitest SSR rendering; clicking Backup/Dry-Run/Restore live in the running UI remains for owner verification.
2. **External PostgreSQL Dump Scope:** When using SQLite (`workspaces_dir/engineering_agent.db`), backups include a transactionally consistent database snapshot automatically; if configured for an external `postgresql://` server, workspace files archive cleanly while external DB backups rely on native `pg_dump`.

## 7. How to Test in the Running App
1. Start backend + frontend via `scripts\start.bat` (`http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`).
2. Open **إعدادات Gemini والمزودين والنظام / Settings & System**, scroll to **Step 20: System Security, Local Log Location & Backup/Restore**, inspect the local `agent.log` path (`no web log viewer`), click **Create Backup (ZIP + SHA-256)**, then click **Verify (Dry-Run)** and download the archive to confirm `manifest.json` + SHA-256 hashes (with no API keys inside).
3. Test CLI verification from `<repo>\backend`: `.\.venv\Scripts\python.exe -m app.cli_backup restore --archive ..\workspaces\_backups\<file>.zip --dry-run`.

## 8. Checklist & Ready for Next Step?
- [x] Branch `step-20-hardening` created cleanly from pulled `main` (`15cd89b`)
- [x] Security: `127.0.0.1`-only bind, strict local CORS, response security headers, chunked/extension/traversal upload+download guards across all endpoints, keyring-only API keys, extended `sanitize_secret_text` + repo/log/export/DB key check, and report-only OSV/`npm` dependency audits
- [x] Error handling: bilingual EN/AR JSON error envelope with `correlation_id`, zero stack traces to UI, redacted internal error logs, frontend `extractErrorMessage`, and verified Gemini 401/429/503 handling
- [x] Logging: local rotating JSONL (`5 MB x 5`) at `<workspaces_dir>/agent.log` redacting secrets & client text, no HTTP log viewer / no remote shipping, and automatic + complete `AuditLog` coverage across exports/approvals/deletes/backups
- [x] Backup/restore: one-click UI & CLI timestamped ZIP + SHA-256 `manifest.json` using SQLite online `backup()`, verified `--dry-run`, wipe & restore hash check, tamper + Zip Slip rejection, and zero keyring inclusion
- [x] `ADR-029` and `docs/reports/step-20.md` (`Status: PARTIAL`) written, `110 passed, 4 skipped` backend + `30 passed` frontend + `gitleaks` clean
- [ ] Owner live UI walkthrough & backup/restore test (**Ready for owner review & PR to `main`**; push branch only, no merge)
