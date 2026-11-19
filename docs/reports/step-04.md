# Step 04 — Provider architecture and Gemini integration

Date: 2026-11-19
Status: PENDING OWNER VERIFICATION
Classification: Preliminary
Revision: v2 (FIX applied on `step-04-provider-architecture-and-gemini`)

## 1. Scope done

### Step 04 prerequisite tasks (PR #9 review hardening, commit `81083e5` + PR #10 refinement)
- **Early aggregate `Content-Length` upload limit (`backend/app/main.py`):** Added pure-ASGI `UploadSizeLimitMiddleware` rejecting `POST /api/projects/{project_id}/files` with HTTP `413` when `Content-Length > MAX_FILES_PER_UPLOAD * MAX_UPLOAD_SIZE_BYTES` before Starlette multipart parsing reads request bytes. Chunked uploads without a `Content-Length` header skip only this early aggregate middleware check and remain strictly bounded per file in 64 KB streaming chunks by `_stage_uploads` (verified by test in `test_files.py`).
- **Explicit domain exception mappings (`backend/app/api/files.py`, `backend/app/services/workspace.py`):** Added `WorkspacePathError` in `workspace.py` and replaced broad `except ValueError` handlers in `api/files.py` with explicit catches for `UnsafeFilenameError`, `UnsupportedFileTypeError`, `EmptyFileError`, `TooManyFilesError`, and `WorkspacePathError` (`400 Bad Request`) plus `FileExistsError` (`409 Conflict`).
- **Allowlist `mime_hint` enforcement (`backend/app/services/files.py`):** Ignored client-supplied upload `Content-Type` headers and strictly used allowlisted `ExtensionSpec.mime_hint` when storing `ProjectFile.mime_type` and serving downloads.
- **Segment-aware `..` validation (`backend/app/services/files.py`):** Rejected `.` and `..` only when present as a whole path segment so filenames containing interior double dots such as `Plan Rev..A.pdf` upload and download cleanly while traversal payloads (`..\..\x`, `../...`) continue to return HTTP `400`.

### Step 04 core implementation & PR #10 fixes
- **Swappable `LLMProvider` contract (`backend/app/providers/base.py`, `backend/app/providers/registry.py`, `backend/app/providers/__init__.py`):**
  - Implemented `LLMProvider`, `LLMRequest`, `LLMResponse`, `MediaInput`, `ToolDefinition`, `ToolCallResult`, `TokenUsage`, `ConnectionCheckResult`, typed exceptions (`ProviderConfigError`, `ProviderAuthError`, `ProviderQuotaError`, `ProviderUsageLimitError`, `ProviderResponseError`) carrying any reported `TokenUsage`, and `sanitize_secret_text()` key/query-param scrubbing.
  - Added provider registry `create_provider(...)` allowing providers to be swapped via configuration without rebuilding the app.
- **`GeminiProvider` on official Google GenAI SDK (`backend/app/providers/gemini.py`):**
  - Built on `google-genai==3.6.1` (`genai.Client`), supporting plain text generation, schema-constrained JSON structured outputs (`response_mime_type="application/json"`, `response_schema`), multimodal PDF + raster image inputs (`types.Part.from_bytes`), function/tool declarations (`types.Tool`), `usage_metadata` extraction, and explicit `401/403` (plus `API key not valid`) auth and `429` quota error translation.
  - Configured default complexity models: **`gemini-2.5-flash`** (`fast`) and **`gemini-2.5-pro`** (`deep`), with **`gemini-2.5-flash-lite`** listed and arbitrary model IDs supported in settings.
- **OS credential storage (`backend/app/providers/secrets.py`):**
  - Stored API keys solely via `keyring==25.7.0` (`WinVaultKeyring` on Windows Credential Manager under service `"ai-engineering-agent"`, account `"gemini_api_key"`). API keys are never persisted to SQLite, `.env`, logs, tests, or git, and are **never returned** by any HTTP endpoint (`GET`/`PUT`/`DELETE` expose only `api_key_configured: bool` and `credential_backend`).
- **Daily & monthly cost controls + append-only usage ledger (`backend/app/schemas/settings.py`, `backend/app/services/provider_settings.py`, `backend/app/api/settings.py`):**
  - Enforced both **daily** (`daily_request_limit`, `daily_token_limit`) and **monthly** (`monthly_request_limit`, `monthly_token_limit`) limits plus `max_output_tokens` in `_check_usage_budget()` before every external provider call (`HTTP 429` / `ProviderUsageLimitError`).
  - Recorded every remote provider attempt — both successful calls and failed provider attempts that reached Google (including any reported tokens) — as **append-only rows** (`entity_type="provider_usage"`) in `audit_log`, summing rows cleanly in `_summarize_usage()` to avoid read-modify-write counter races. Local rejections before calling Google (`ProviderConfigError`, `ProviderUsageLimitError`) do not consume remote request budget.
- **Settings screen UI (`frontend/src/components/ProviderSettingsView.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/index.css`):**
  - Added bilingual Arabic RTL / English LTR navigation tab **AI Provider Settings**, masked password input (`type="password"`), keyring status & delete-key button, consumer Gemini subscription vs API key notice, provider/model selectors (`fast`/`deep`), daily **and monthly** usage budget controls & live telemetry counters, and **Test connection** button.
- **Owner-local live verification helper (`scripts/verify_gemini_live.py`):**
  - Added a standalone verification runner reading credentials strictly from Windows Credential Manager (`keyring`), never storing keys on disk, and printing only sanitized JSON results (model name, latency, token counts, short text excerpt) across the five live owner checks.

### Packages & model names used

| Component | Exact Value | Notes |
|---|---|---|
| `google-genai` | `3.6.1` (`Apache-2.0`) | Official Google GenAI Python SDK |
| `keyring` | `25.7.0` (`MIT`) | Credential storage (`WinVaultKeyring` on Windows) |
| Key storage location | `Windows Credential Manager` | `keyring` service `"ai-engineering-agent"`, account `"gemini_api_key"` |
| Default `fast` model | `gemini-2.5-flash` | Configurable in Settings UI |
| Default `deep` model | `gemini-2.5-pro` | Configurable in Settings UI |
| Additional catalog option | `gemini-2.5-flash-lite` | Selectable or overrideable with custom model ID |

## 2. Files created/changed
- `backend/requirements.txt` (pinned `google-genai==3.6.1`, `keyring==25.7.0`)
- `backend/app/main.py` (`UploadSizeLimitMiddleware`, `secret_store` / `provider_client_factory` injection hooks, mounted `settings_router`)
- `backend/app/api/{files.py,settings.py}`
- `backend/app/services/{files.py,provider_settings.py,workspace.py}`
- `backend/app/providers/{__init__.py,base.py,gemini.py,registry.py,secrets.py}`
- `backend/app/schemas/settings.py`
- `backend/tests/{test_files.py,test_providers.py}`
- `frontend/src/{App.tsx,App.test.tsx,api.ts,index.css,types.ts}`, `frontend/src/components/ProviderSettingsView.tsx`
- `scripts/verify_gemini_live.py`
- `docs/DECISIONS.md` (`ADR-010`), `docs/reports/step-04.md`

*(Did not modify `.github/` or `CLAUDE.md`.)*

## 3. Tests run (pre-commit verification on final code; mocked SDK & fake credentials only)

### A. Package metadata (`pip show google-genai keyring`)
```text
Name: google-genai
Version: 3.6.1
Summary: GenAI Python SDK
Home-page: https://github.com/googleapis/python-genai
Author: 
Author-email: Google LLC <googleapis-packages@google.com>
License-Expression: Apache-2.0
Location: <repo>\backend\.venv\Lib\site-packages
Requires: anyio, distro, google-auth, httpx2, pydantic, requests, sniffio, tenacity, typing-extensions, websockets
Required-by: 
---
Name: keyring
Version: 25.7.0
Summary: Store and access your passwords safely.
Home-page: 
Author: 
Author-email: Kang Zhang <jobo.zh@gmail.com>
License-Expression: MIT
Location: <repo>\backend\.venv\Lib\site-packages
Requires: jaraco.classes, jaraco.context, jaraco.functools, pywin32-ctypes
Required-by: 
```

### B. Backend test suite (`pytest -v` in `backend/`)
*(All provider tests run with non-key test placeholders and mocked `google-genai` clients.)*
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: <repo>\backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 24 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [  4%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [  8%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 12%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 16%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 20%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 25%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 29%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 33%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 37%]
tests/test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 41%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 45%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 50%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 54%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 58%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 62%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 66%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [ 70%]
tests/test_providers.py::test_keyring_secret_store_round_trip PASSED     [ 75%]
tests/test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 79%]
tests/test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 83%]
tests/test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 87%]
tests/test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 91%]
tests/test_providers.py::test_debug_logging_never_leaks_api_key PASSED   [ 95%]
tests/test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [100%]

============================= 24 passed in 7.22s ==============================
```

### C. Frontend unit tests & TypeScript/Vite build (`npm.cmd test` + `npm.cmd run build` in `frontend/`)
```text
> ai-engineering-agent-frontend@0.1.0 test
> vitest run

 RUN  v2.1.9 <repo>/frontend

 ✓ src/App.test.tsx (8 tests) 17ms

 Test Files  1 passed (1)
      Tests  8 passed (8)
   Duration  452ms

> ai-engineering-agent-frontend@0.1.0 build
> tsc --noEmit && vite build

vite v6.4.6 building for production...
transforming...
✓ 31 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-CnfG7K16.css    5.15 kB │ gzip:  1.55 kB
dist/assets/index-CdPTG3MZ.js   181.49 kB │ gzip: 56.33 kB
✓ built in 436ms
```

*(Final-head `pytest`, `vitest`, `build`, `node --test`, and `gitleaks` outputs at the exact final committed SHA are recorded in the Pull Request description.)*

## 4. Acceptance tests
1. **PR #9 first-task hardening (`Content-Length` `413` + chunked per-file streaming `413`, `409`/`400` domain exception mappings, `mime_hint`, `Plan Rev..A.pdf`):** **PASS** — Verified in `test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps`.
2. **Swappable `LLMProvider` + `GeminiProvider` (text, structured JSON, PDF + PNG multimodal, tool calling, usage tracking):** **PASS (mocked SDK only)** — Verified in `test_gemini_provider_text_structured_pdf_image_and_tools`.
3. **Keyring credential storage & zero key leakage (`GET`/`PUT`/`DELETE`, DB, exception messages, and `DEBUG` logging across root, `httpx`, `httpx2`, `google_genai`, `uvicorn`):** **PASS (mocked keyring/SDK)** — Verified in `test_keyring_secret_store_round_trip`, `test_provider_errors_and_secret_scrubbing`, `test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak`, and `test_debug_logging_never_leaks_api_key`.
4. **Daily & monthly usage limits (`_check_usage_budget`) + counting failed remote attempts:** **PASS (mocked SDK)** — Verified in `test_monthly_usage_limits_and_failed_attempt_counting` (both `monthly_request_limit` and `monthly_token_limit` block calls before invoking the SDK; failed remote `401` and `ProviderResponseError` calls count toward request totals and any reported tokens).
5. **Live verification with the owner's real Gemini API key:** **PENDING OWNER VERIFICATION** — Mocked tests cover all code paths, while live calls against Google's Gemini endpoint remain unverified until the owner runs the five live checks locally using their `keyring`-stored key.

## Live verification still needed
The owner must run these exact five checks locally (with their real Gemini API key saved only via Settings UI into Windows Credential Manager `keyring`) before closing Step 04 acceptance:
1. **Real `test-connection` with the owner's key** (UI **Test connection** button or `scripts/verify_gemini_live.py`).
2. **Real invalid-key response** from live Gemini servers (verifying clean auth rejection with zero leaked key characters).
3. **One live structured-JSON call** returning schema-valid JSON (`LiveStructuredCheckSchema`).
4. **One live small PDF page analysis** (`application/pdf` input via `GeminiProvider.analyze_media`).
5. **One live small image analysis** (`image/png` input via `GeminiProvider.analyze_media`).

### How the owner can run the live verification locally (never pasting keys into chat)
1. Start the app (`scripts\start.bat`) and open `http://127.0.0.1:5173`.
2. Go to **إعدادات Gemini والمزودين / AI Provider Settings**, enter your Google AI Studio Gemini API key into the masked password box, click **Save API Key to Keyring**, and click **Test connection** to verify check #1 in the UI.
3. Run the local diagnostic script (reads only from Windows Credential Manager `keyring` and prints only sanitized JSON — model name, token usage, and short text excerpt — never any key characters):
   ```powershell
   backend\.venv\Scripts\python.exe scripts\verify_gemini_live.py
   ```
   *(Verified in unit tests via `test_verify_gemini_live_script_with_mocked_provider`.)*

## 5. Decisions made (also in `docs/DECISIONS.md`)
- **ADR-010:** PR #9 upload hardening (with `WorkspacePathError` explicit mapping), `google-genai==3.6.1` `GeminiProvider` (`gemini-2.5-flash` / `gemini-2.5-pro`), `keyring==25.7.0` (`WinVaultKeyring`) secret isolation with boolean-only API key status, daily + monthly budget enforcement in `_check_usage_budget`, append-only `AuditLog(entity_type="provider_usage")` summing (covering failed remote attempts), and `scripts/verify_gemini_live.py` for owner-local live verification.

## 6. Deviations from the plan and why
- **Boolean-only API key status instead of masked key prefix/suffix:** Rather than returning even partial characters (`prefix...suffix`), the backend strictly returns `api_key_configured: bool` so zero key characters ever cross the HTTP boundary.
- **Chunked upload POSTs without `Content-Length` fallback:** Chunked requests without `Content-Length` skip only the early aggregate `UploadSizeLimitMiddleware` check and remain enforced per file in 64 KB streaming chunks by `_stage_uploads` (HTTP `413`), avoiding breaking legitimate streaming proxies (`HTTP 411`).
- **Append-only usage rows in existing `audit_log` table instead of mutating JSON counters:** Avoids lost-update races on concurrent requests and computes both daily and monthly totals without adding another Alembic migration.

## 7. Known limitations / things not verified
- **Live Google Gemini API verification:** All 5 checks listed under **Live verification still needed** remain pending owner execution with a real Google AI Studio API key stored locally in Windows Credential Manager (`keyring`).
- **Chunked multipart uploads without `Content-Length`:** Skip only the early aggregate middleware check and are rejected per file during streaming ingestion (`413`).
- External tools Tesseract OCR (`ara+eng`, Step 06) and ODA File Converter (Step 07) remain `not installed - pending owner`.

## 8. Questions or items needing the owner
- **Do NOT paste your Gemini API key in chat.** Enter it only in `http://127.0.0.1:5173` -> **AI Provider Settings**, verify **Test connection**, and run `backend\.venv\Scripts\python.exe scripts\verify_gemini_live.py` locally to complete all 5 live checks (paste the sanitized JSON summary if desired).
- Review and merge PR #10 yourself after verifying, then reply `PASS step 04` before I begin Step 05.

## 9. How the owner can see/try it
1. Run `scripts\start.bat` and open `http://127.0.0.1:5173`.
2. Open **AI Provider Settings**, enter your key locally (`keyring`), configure fast/deep models and daily/monthly limits, and click **Test connection**.
3. Run `backend\.venv\Scripts\python.exe scripts\verify_gemini_live.py` locally for all 5 live Gemini checks.
4. Run automated verification suites:
   - `cd backend && .\.venv\Scripts\python.exe -m pytest -v`
   - `cd frontend && npm.cmd test && npm.cmd run build`
   - `node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs`

## 10. Ready for next step?
**No — PENDING OWNER VERIFICATION** until the owner completes the 5 local live verification checks above, reviews/merges PR #10, and replies `PASS step 04`.
