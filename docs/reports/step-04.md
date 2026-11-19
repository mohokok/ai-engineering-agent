# Step 04 Report — Provider Architecture & Gemini Integration

- **Status:** **PENDING OWNER VERIFICATION**
- **Revision:** v3 (updated default models, live `generateContent` model discovery, startup check, and `404` recovery guidance following the owner's first live check)
- **Branch:** `step-04-provider-architecture-and-gemini`
- **Pull Request:** `#10`
- **Depends on:** Step 03 (merged in PR `#9`)

## First Live Verification Note

The owner ran an initial live connection test using a real Gemini API key saved in Windows Credential Manager (`WinVaultKeyring` via `keyring`). That request reached Google cleanly — confirming end-to-end key storage and SDK transport — and failed with `404 NOT_FOUND` because Google retired **`models/gemini-2.5-flash`** for new users.

All five follow-up fixes from that live result have been applied and verified in automated tests:

1. **Updated default models & fallback catalog** (`<repo>/backend/app/providers/gemini.py`):
   - Default `fast` model: **`gemini-3.8-flash`**
   - Default `deep` model: **`gemini-4-argon`**
   - Fallback catalog also includes **`gemini-3.5-flash-lite`**, while custom manual model-ID input remains supported.
2. **Live `generateContent` model discovery + startup check** (`<repo>/backend/app/providers/gemini.py`, `<repo>/backend/app/services/provider_settings.py`, `<repo>/backend/app/api/settings.py`, `<repo>/backend/app/main.py`, `<repo>/frontend/src/components/ProviderSettingsView.tsx`):
   - Added `GeminiProvider.list_models()` calling `client.models.list()` and filtering strictly to models that support `generateContent` (case-insensitive over `supported_actions` / `supported_generation_methods`), stripping the `models/` prefix and excluding non-generation models (e.g., embeddings / image-only endpoints).
   - Added `POST /api/settings/provider/models/refresh`, a UI **`Refresh models (generateContent)`** / **`تحديث النماذج الحية (generateContent)`** control, a source badge (**Live API** vs **Fallback catalog**), a **`model_warning`** alert banner if the saved `fast`/`deep` model is absent from the latest live list, and manual text `<input>` overrides directly beneath each `<select>`.
   - Added best-effort `refresh_models_on_startup(...)` in FastAPI `lifespan` when a key is already present in `keyring`.
3. **Clean `404 NOT_FOUND` handling** (`<repo>/backend/app/providers/base.py`, `<repo>/backend/app/providers/gemini.py`, `<repo>/backend/app/api/settings.py`):
   - Added `ProviderModelNotFoundError` mapped to HTTP `400`, returning a clear sanitized error naming the configured model ID and instructing the owner to choose another model after refreshing the model list — with zero secret characters leaked.
4. **Updated script, docs, and tests**:
   - Updated `<repo>/scripts/verify_gemini_live.py` to refresh live `generateContent` models first, report `models_source`, `refreshed_generate_content_models_count`, `configured_models`, and optional `model_warning`, and test against `gemini-3.8-flash` / `gemini-4-argon`.
   - Updated `<repo>/docs/DECISIONS.md` (`ADR-010`), `<repo>/backend/tests/test_providers.py`, and `<repo>/frontend/src/App.test.tsx`, and added dedicated tests covering `HTTP 404 NOT_FOUND` handling, `generateContent` filtering, `model_warning` lifecycle, and startup model discovery.

## Configuration Summary

| Setting / Component | Value / Behavior | Notes |
| --- | --- | --- |
| Active provider | `gemini` (`Google Gemini (Official google-genai SDK)`) | Swappable via `LLMProvider` (`<repo>/backend/app/providers/registry.py`) |
| Default `fast` model | `gemini-3.8-flash` | Selectable via live list or manual text input |
| Default `deep` model | `gemini-4-argon` | Selectable via live list or manual text input |
| Fallback catalog options | `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-4-argon` | Used until live `client.models.list()` populates cached `generateContent` models |
| Secret storage backend | `keyring==25.7.0` (`WinVaultKeyring` on Windows) | Service `"ai-engineering-agent"`, account `"gemini_api_key"`; never stored in SQLite, `.env`, logs, or git |
| Usage budget ledger | Daily + monthly caps checked in `_check_usage_budget` | Append-only `AuditLog(entity_type="provider_usage")` summed per query (`ADR-010`); failed remote attempts counted |

## Scope Delivered in Step 04 (Including PR #9 Hardening)

- **PR #9 upload & file-API hardening (`<repo>/backend/app/main.py`, `<repo>/backend/app/api/files.py`, `<repo>/backend/app/services/files.py`):**
  - Added ASGI `UploadSizeLimitMiddleware` rejecting `POST /api/projects/{id}/files` early when `Content-Length > MAX_FILES_PER_UPLOAD * MAX_UPLOAD_SIZE_BYTES`. (Chunked uploads without a `Content-Length` header skip only this early pre-check and remain protected per file by the streaming size limit.)
  - Replaced broad `except ValueError` in `<repo>/backend/app/api/files.py` with explicit domain exceptions (`FileExistsError` -> HTTP `409`; `EmptyFileError`, `TooManyFilesError`, `UnsafeFilenameError`, `UnsupportedFileTypeError`, `WorkspacePathError` -> HTTP `400`).
  - Stored and served downloaded files using the allowlist `mime_hint` instead of client-supplied `Content-Type`.
  - Enforced `..` traversal rejection per whole path segment so legitimate filenames such as `Plan Rev..A.pdf` succeed.
- **Provider abstraction & Gemini integration (`<repo>/backend/app/providers/`):**
  - Defined provider-agnostic `LLMProvider`, `LLMRequest`, `LLMResponse`, `MediaInput`, `ToolDefinition`, `ModelInfo`, `ConnectionCheckResult`, `ProviderModelNotFoundError`, `SecretStore`, and `sanitize_secret_text` (`<repo>/backend/app/providers/base.py`).
  - Implemented `GeminiProvider` (`<repo>/backend/app/providers/gemini.py`) using `google-genai==3.6.1` for text, structured JSON (Pydantic schema), PDF/PNG/JPEG multimodal inputs, tool calling, live `list_models()` discovery, and connection tests.
- **Settings API, monthly/daily caps & privacy (`<repo>/backend/app/services/provider_settings.py`, `<repo>/backend/app/api/settings.py`):**
  - Implemented `GET /api/settings/provider`, `PUT /api/settings/provider`, `PUT /api/settings/provider/api-key`, `DELETE /api/settings/provider/api-key`, `POST /api/settings/provider/test`, and `POST /api/settings/provider/models/refresh`.
  - Exposed only `api_key_configured: bool` and `credential_backend` over HTTP; zero API key characters returned in responses, persisted in SQLite, or emitted even when `DEBUG` logging is enabled across root, `httpx`, `httpx2`, `google_genai`, and `uvicorn` loggers.
  - Enforced daily (`daily_request_limit`, `daily_token_limit`) and monthly (`monthly_request_limit`, `monthly_token_limit`) caps in `_check_usage_budget` before calling the provider, and recorded both successful calls and failed remote attempts (with reported tokens) via append-only `AuditLog(entity_type="provider_usage")` rows.
- **Bilingual Settings UI (`<repo>/frontend/src/components/ProviderSettingsView.tsx`, `<repo>/frontend/src/api.ts`, `<repo>/frontend/src/types.ts`):**
  - Added masked password input (`<input type="password">`) for saving/replacing or deleting the Gemini API key in `keyring`, clear consumer Gemini vs Gemini API notice, daily/monthly usage displays, **`Refresh models (generateContent)`** control with **Live API / Fallback catalog** badge, `model_warning` notice, and synced dropdown + manual model-ID text inputs for `fast` and `deep`.
- **Architecture decisions (`<repo>/docs/DECISIONS.md`):**
  - Updated `ADR-010` documenting model defaults (`gemini-3.8-flash`, `gemini-4-argon`, `gemini-3.5-flash-lite`), `POST /api/settings/provider/models/refresh`, startup discovery, `ProviderModelNotFoundError` (`404` -> `400`), `keyring` secret isolation, and append-only usage accounting.

## Verification Coverage (Mocked Provider & Fake Credentials Only)

- **Backend (`<repo>/backend`):** `26/26` `pytest -v` tests pass, including Step 04 tests for `KeyringSecretStore`, `GeminiProvider` (text, structured JSON, PDF+PNG multimodal, tools, secret redaction, `404` model-not-found mapping), Settings CRUD, daily & monthly cap blocking, failed remote attempt counting, `DEBUG` log redaction across root/`httpx`/`httpx2`/`google_genai`/`uvicorn`, `POST /api/settings/provider/models/refresh` `generateContent` filtering + `model_warning` + startup check, and mocked `scripts/verify_gemini_live.py`.
- **Frontend (`<repo>/frontend`):** `8/8` Vitest tests (`src/App.test.tsx`) and `tsc --noEmit && vite build` pass cleanly.
- **Repository hygiene (`<repo>/tests`):** UTF-8 encoding check, local-path check across tracked files, and full `gitleaks` scan over all refs are re-run on the final commit before updating PR `#10`.

## Live verification still needed

Automated tests use mocked Google SDK clients and fake non-`AIza` credentials only, so live owner verification against Google Gemini API is still required to sign off Step 04. If `gemini-2.5-flash` was previously saved into local SQLite settings before pulling v3, open **Settings**, click **`Refresh models (generateContent)`**, select **`gemini-3.8-flash`** (fast) / **`gemini-4-argon`** (deep), and click **`Save Model & Limit Preferences`** before running the live checks.

1. **Real `test-connection` with the owner's key:** Verify `POST /api/settings/provider/test` (via UI **Test Gemini Connection** or `<repo>/scripts/verify_gemini_live.py`) succeeds with the key stored only in Windows Credential Manager (`keyring`).
2. **Real invalid-key rejection:** Verify a rejected credential probe returns HTTP `401` with a clean consumer/subscription guidance message and zero key leakage.
3. **One live structured-JSON call:** Verify Pydantic JSON output parsing via `generate_structured` against Google Gemini.
4. **One live small PDF page analysis:** Verify multimodal PDF page inspection via `analyze_media` (`application/pdf`).
5. **One live image analysis:** Verify multimodal image inspection via `analyze_media` (`image/png`).

Owner local verification command (reads key only from `keyring`; prints only sanitized non-secret metadata, token counts, and short response excerpts):

```powershell
cd backend
.venv\Scripts\python.exe ..\scripts\verify_gemini_live.py
```

## Stop Condition Status

**No — PENDING OWNER VERIFICATION** until the owner completes the 5 local live verification checks above, reviews/merges PR `#10`, and replies `PASS step 04`.
