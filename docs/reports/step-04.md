# Step 04 — Provider architecture and Gemini integration

Date: 2026-11-19
Status: COMPLETE
Classification: Preliminary

## 1. Scope done

### Step 04 prerequisite tasks (PR #9 review hardening, commit `81083e5`)
- **Early aggregate `Content-Length` upload limit (`backend/app/main.py`):** Added pure-ASGI `UploadSizeLimitMiddleware` rejecting `POST /api/projects/{project_id}/files` with HTTP `413` when `Content-Length > MAX_FILES_PER_UPLOAD * MAX_UPLOAD_SIZE_BYTES` before Starlette multipart parsing reads request bytes, while retaining the per-file streaming limit in `_stage_uploads`.
- **Clean HTTP error mappings (`backend/app/api/files.py`):** Mapped `FileExistsError` -> HTTP `409 Conflict` and `ValueError` (including `resolve_project_file_path` path-containment errors) -> HTTP `400 Bad Request`.
- **Allowlist `mime_hint` enforcement (`backend/app/services/files.py`):** Ignored client-supplied upload `Content-Type` headers and strictly used allowlisted `ExtensionSpec.mime_hint` when storing `ProjectFile.mime_type` and serving downloads.
- **Segment-aware `..` validation (`backend/app/services/files.py`):** Rejected `.` and `..` only when present as a whole path segment so filenames containing interior double dots such as `Plan Rev..A.pdf` upload and download cleanly while traversal payloads (`..\..\x`, `../...`) continue to return HTTP `400`.

### Step 04 core implementation
- **Swappable `LLMProvider` contract (`backend/app/providers/base.py`, `backend/app/providers/registry.py`, `backend/app/providers/__init__.py`):**
  - Implemented `LLMProvider`, `LLMRequest`, `LLMResponse`, `MediaInput`, `ToolDefinition`, `ToolCallResult`, `TokenUsage`, `ConnectionCheckResult`, and typed exceptions (`ProviderConfigError`, `ProviderAuthError`, `ProviderQuotaError`, `ProviderUsageLimitError`, `ProviderResponseError`) plus `sanitize_secret_text()` key scrubbing.
  - Added provider registry `create_provider(...)` allowing providers to be swapped via configuration without rebuilding the app.
- **`GeminiProvider` on official Google GenAI SDK (`backend/app/providers/gemini.py`):**
  - Built on `google-genai==3.6.1` (`genai.Client`), supporting plain text generation, schema-constrained JSON structured outputs (`response_mime_type="application/json"`, `response_schema`), multimodal PDF + raster image inputs (`types.Part.from_bytes`), function/tool declarations (`types.Tool`), `usage_metadata` extraction, and explicit `401/403` auth + `429` quota error translation.
  - Configured default complexity models: **`gemini-2.5-flash`** (`fast`) and **`gemini-2.5-pro`** (`deep`), with **`gemini-2.5-flash-lite`** listed and arbitrary model IDs supported in settings.
- **OS credential storage (`backend/app/providers/secrets.py`):**
  - Stored API keys solely via `keyring==25.7.0` (`WinVaultKeyring` on Windows Credential Manager under service `"ai-engineering-agent"`, account `"gemini_api_key"`). API keys are never persisted to SQLite, `.env`, logs, tests, or git, and are **never returned** by any HTTP endpoint (`GET`/`PUT`/`DELETE` expose only `api_key_configured: bool` and `credential_backend`).
- **Provider settings, daily usage caps & endpoints (`backend/app/schemas/settings.py`, `backend/app/services/provider_settings.py`, `backend/app/api/settings.py`):**
  - Added `GET /api/settings/provider`, `PUT /api/settings/provider`, `PUT /api/settings/provider/api-key`, `DELETE /api/settings/provider/api-key`, and `POST /api/settings/provider/test`, persisting non-secret model selections, daily limits (`daily_request_limit`, `daily_token_limit`, `max_output_tokens`), sanitized connection check status, and UTC daily token/request counters in `settings` + `audit_log`.
- **Settings screen UI (`frontend/src/components/ProviderSettingsView.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/index.css`):**
  - Added bilingual Arabic RTL / English LTR navigation tab **AI Provider Settings**, masked password input (`type="password"`) for local key entry, keyring status & delete-key control, consumer Gemini subscription vs API key notice, provider/model selectors (`fast`/`deep`), daily usage budget inputs & today's token/request telemetry, and **Test connection** button.

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
- `backend/app/services/{files.py,provider_settings.py}`
- `backend/app/providers/{__init__.py,base.py,gemini.py,registry.py,secrets.py}`
- `backend/app/schemas/settings.py`
- `backend/tests/{test_files.py,test_providers.py}`
- `frontend/src/{App.tsx,App.test.tsx,api.ts,index.css,types.ts}`, `frontend/src/components/ProviderSettingsView.tsx`
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
collecting ... collected 21 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [  4%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [  9%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 14%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 19%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 23%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 28%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 33%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 38%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 42%]
tests/test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 47%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 52%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 57%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 61%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 66%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 71%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 76%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [ 80%]
tests/test_providers.py::test_keyring_secret_store_round_trip PASSED     [ 85%]
tests/test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 90%]
tests/test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 95%]
tests/test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [100%]

============================= 21 passed in 6.34s ==============================
```

### C. Frontend unit tests & TypeScript/Vite build (`npm.cmd test` + `npm.cmd run build` in `frontend/`)
```text
> ai-engineering-agent-frontend@0.1.0 test
> vitest run

 RUN  v2.1.9 <repo>/frontend

 ✓ src/App.test.tsx (8 tests) 18ms

 Test Files  1 passed (1)
      Tests  8 passed (8)
   Duration  684ms

> ai-engineering-agent-frontend@0.1.0 build
> tsc --noEmit && vite build

vite v6.4.6 building for production...
transforming...
✓ 31 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-CnfG7K16.css    5.15 kB │ gzip:  1.55 kB
dist/assets/index-B49sjXl5.js   180.02 kB │ gzip: 56.13 kB
✓ built in 438ms
```

### D. Live Vite proxy + `uvicorn` non-secret settings verification
Executed against isolated `workspaces/_step04_live_smoke` (without writing to Windows Credential Manager):
```text
LIVE_SETTINGS_GET: gemini WinVaultKeyring False {'fast': 'gemini-2.5-flash', 'deep': 'gemini-2.5-pro'}
LIVE_SETTINGS_PUT: 150
LIVE_TEST_NO_KEY: 400 True
```

*(Final-head `pytest`, `vitest`, `build`, `node --test`, and `gitleaks` outputs at the exact final committed SHA are recorded in the Pull Request description.)*

## 4. Acceptance tests
1. **PR #9 first-task hardening (`Content-Length` `413`, `409`/`400` mappings, `mime_hint`, `Plan Rev..A.pdf`):** **PASS** — Verified in `test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps`.
2. **Swappable `LLMProvider` + `GeminiProvider` (text, structured JSON, PDF + PNG multimodal, tool calling, usage tracking):** **PASS (mocked SDK)** — Verified in `test_gemini_provider_text_structured_pdf_image_and_tools`.
3. **Keyring credential storage & zero key leakage (`GET`/`PUT`/`DELETE`/DB/errors):** **PASS** — Verified in `test_keyring_secret_store_round_trip` (`WinVaultKeyring` reported locally; mocked keyring round-trip), `test_provider_errors_and_secret_scrubbing`, and `test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak` confirming zero occurrence of credentials across HTTP responses, SQLite `settings`, `audit_log`, or exception strings.
4. **Invalid key, quota errors & daily usage caps:** **PASS (mocked SDK)** — Verified `401` invalid-key error with consumer-subscription warning, `429` quota error, and `429` local daily request cap enforcement before external SDK calls.
5. **Live call with the owner's real Gemini API key:** **Pending owner local verification** — Per security rules, no real API key was requested in chat or embedded in tests; owner verifies locally by entering their key in the **AI Provider Settings** UI screen.

## 5. Decisions made (also in `docs/DECISIONS.md`)
- **ADR-010:** PR #9 upload hardening, `google-genai==3.6.1` `GeminiProvider` (`gemini-2.5-flash` / `gemini-2.5-pro`), `keyring==25.7.0` (`WinVaultKeyring`) secret isolation, boolean-only API key status, and daily usage caps in SQLite `settings`.

## 6. Deviations from the plan and why
- **Boolean-only API key status instead of masked key prefix/suffix:** Rather than returning even partial characters (`prefix...suffix`), the backend strictly returns `api_key_configured: bool` so zero key characters ever cross the HTTP boundary.
- **Injectable `SecretStore` and `provider_client_factory` in `create_app()`:** Keeps automated test suites completely isolated from the owner's real Windows Credential Manager and external Google endpoints.

## 7. Known limitations / things not verified
- **Live Google Gemini API call with owner's real key & real PDF/image round-trip:** Automated tests used fake credentials and mocked `google-genai` responses; real end-to-end API authorization and latency are verified when the owner enters their key in the local Settings UI and clicks **Test connection**.
- External tools Tesseract OCR (`ara+eng`, Step 06) and ODA File Converter (Step 07) remain `not installed - pending owner`.

## 8. Questions or items needing the owner
- **Do NOT paste your Gemini API key in chat.** Instead:
  1. Pull or check out the PR branch after review and launch `scripts\start.bat`.
  2. Open `http://127.0.0.1:5173`, switch to **إعدادات Gemini والمزودين / AI Provider Settings**.
  3. Paste your authorized Google AI Studio Gemini API key into the masked password box and click **Save API Key to Keyring** (verify it stores cleanly in Windows Credential Manager).
  4. Click **Test connection** and verify your configured models (`gemini-2.5-flash` / `gemini-2.5-pro`) report connected status cleanly.
- Review and merge this Step 04 PR yourself and reply `PASS step 04` before I begin Step 05.

## 9. How the owner can see/try it
1. Run `scripts\start.bat` and open `http://127.0.0.1:5173`.
2. Open the **AI Provider Settings** tab, confirm the consumer-subscription notice, configure `fast` / `deep` models and daily limits, save your API key locally via the UI form (`keyring`), and click **Test connection**.
3. Run automated verification suites:
   - `cd backend && .\.venv\Scripts\python.exe -m pytest -v`
   - `cd frontend && npm.cmd test && npm.cmd run build`
   - `node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs`

## 10. Ready for next step?
**Yes** — Ready for owner local key verification, PR review/merge, and `PASS step 04` to proceed to Step 05.
