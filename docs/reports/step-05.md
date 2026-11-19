# Step 05 — Chat and Task Engine Foundation

- **Date:** 2026-11-19
- **Status:** **COMPLETE**
- **Branch:** `step-05-chat-and-task-engine`
- **Depends on:** Step 04 (`1ce4cfb`, PR `#10` squash-merged to `main` after owner `PASS step 04`)

## 1. Scope Done

### First Tasks (Before Step 05 Feature Work)
- **Completed Step 04 report (`<repo>/docs/reports/step-04.md`):** Updated status to **`COMPLETE`** and recorded all sanitized owner live Gemini results: connection OK on `gemini-3.5-flash-lite` (`585 ms`, `9 tokens`), clean invalid-key rejection (`ProviderAuthError`), structured JSON keys `classification`, `discipline`, `note` (`49 tokens`), PDF extraction `'Concrete Beam Check Span 6.0m'` (`559 tokens`), image dominant-colour blue (`1107 tokens`), `27` `generateContent` models from live refresh, and credential backend `WinVaultKeyring`.
- **Provider-layer `HTTP 503 UNAVAILABLE` retry (`<repo>/backend/app/providers/base.py`, `<repo>/backend/app/providers/gemini.py`, `<repo>/backend/app/api/settings.py`):** Added `ProviderServiceUnavailableError` (mapped to HTTP `503`) and `_call_with_503_retry(...)` with short exponential backoff (`max 3 tries`, delays `0.5s`, `1.0s`) across both `GeminiProvider.generate()` and `GeminiProvider.list_models()`, keeping logical single-request accounting in the usage ledger and adding unit + API coverage in `<repo>/backend/tests/test_providers.py`.

### Step 05 Feature Delivery
- **Database schema & migration (`<repo>/backend/alembic/versions/0004_step05_task_metadata.py`, `<repo>/backend/app/db/models.py`):** Added Alembic migration `0004` adding nullable columns on `tasks` (`complexity`, `provider_name`, `model_name`, `attached_file_ids_json`, `structured_output_json`, `token_usage_json`) while preserving Step 03 `ON DELETE RESTRICT` and `classification` `CHECK` constraints.
- **Orchestrator v0 (`<repo>/backend/app/agents/orchestrator.py`, `<repo>/backend/app/schemas/tasks.py`):**
  - Built `OrchestratorUnderstanding` structured JSON schema and `run_orchestrator_v0()` using `LLMRequest(response_schema=OrchestratorUnderstanding)`.
  - Restates the assignment preserving original quantities/constraints, identifies `language_detected` (`ar`/`en`/`mixed`), `primary_discipline` & `secondary_disciplines`, `expected_deliverables`, `input_files` (`attached`/`missing`/`referenced_in_prompt`), `applicable_standards_to_verify` (candidate names only — zero fabricated clauses/quantities/sources), `missing_information`, preliminary `assumptions`, and asks `clarifying_questions` **only when missing info materially affects the result** (`clarification_needed = true`).
  - Wraps project metadata, attached file manifests, and user prompt inside `<UNTRUSTED_PROJECT_METADATA>`, `<UNTRUSTED_ATTACHED_FILES>`, and `<UNTRUSTED_ASSIGNMENT_INPUT>` XML delimiters per Rule 10.
- **Task engine service & REST API (`<repo>/backend/app/services/tasks.py`, `<repo>/backend/app/api/tasks.py`, `<repo>/backend/app/main.py`):**
  - Added `POST /api/tasks`, `GET /api/tasks` (filtered by `project_id` and `status`, sorted newest-first), and `GET /api/tasks/{task_id}`.
  - Links task lifecycle (`task.created`, `task.completed`, `task.failed`) and provider token usage events (`provider.usage_recorded` / `provider.usage_failed`) in `audit_log`, plus ordered `task_steps` (`assignment_intake` -> `orchestrator_v0`), attached file metadata snapshots, and `token_usage` (`prompt_tokens`, `output_tokens`, `total_tokens`, `thoughts_tokens`, `cached_tokens`, `latency_ms`).
  - Persists failures cleanly (`status="failed"`, sanitized `error_message`, failed `TaskStep`, and `task.failed` audit log) without hiding failed tasks or leaking credentials.
- **Bilingual RTL/LTR UI (`<repo>/frontend/src/components/AssignmentsView.tsx`, `<repo>/frontend/src/App.tsx`, `<repo>/frontend/src/api.ts`, `<repo>/frontend/src/types.ts`, `<repo>/frontend/src/index.css`):**
  - Added **Assignments & Task History (`المهام والتكليفات`)** tab containing the **New Assignment** form (choose project, optional title, natural-language Arabic/English/mixed instructions, `fast`/`deep` model tier, classification selector, attach existing project files OR upload & attach new local files inline), structured **Orchestrator v0 JSON Inspector**, execution steps/logs/token usage panels, red failure banners when tasks fail, and filterable **Task History** list.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0004_step05_task_metadata.py`
- `<repo>/backend/app/agents/orchestrator.py`
- `<repo>/backend/app/api/tasks.py`
- `<repo>/backend/app/schemas/tasks.py`
- `<repo>/backend/app/services/tasks.py`
- `<repo>/backend/tests/test_tasks.py`
- `<repo>/docs/reports/step-05.md`
- `<repo>/frontend/src/components/AssignmentsView.tsx`

### Changed
- `<repo>/backend/app/agents/__init__.py`
- `<repo>/backend/app/api/settings.py`
- `<repo>/backend/app/db/models.py`
- `<repo>/backend/app/main.py`
- `<repo>/backend/app/providers/__init__.py`
- `<repo>/backend/app/providers/base.py`
- `<repo>/backend/app/providers/gemini.py`
- `<repo>/backend/app/services/provider_settings.py`
- `<repo>/backend/tests/test_migrations.py`
- `<repo>/backend/tests/test_providers.py`
- `<repo>/docs/DECISIONS.md` (`ADR-011`)
- `<repo>/docs/reports/step-04.md`
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/frontend/src/App.tsx`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/index.css`
- `<repo>/frontend/src/types.ts`

## 3. Tests Run (Pre-Commit Tree & Verified After Final Commit on PR Branch)

### Backend (`pytest -v` in `<repo>/backend`)
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>/backend/.venv/Scripts/python.exe
cachedir: .pytest_cache
rootdir: <repo>/backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 29 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [  3%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [  6%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 10%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 13%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 17%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 20%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 24%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 27%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 31%]
tests/test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 34%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 37%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 41%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 44%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 48%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 51%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 55%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [ 58%]
tests/test_providers.py::test_keyring_secret_store_round_trip PASSED     [ 62%]
tests/test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 65%]
tests/test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 68%]
tests/test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 72%]
tests/test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 75%]
tests/test_providers.py::test_debug_logging_never_leaks_api_key PASSED   [ 79%]
tests/test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 82%]
tests/test_providers.py::test_provider_404_model_not_found_handling PASSED [ 86%]
tests/test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 89%]
tests/test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 93%]
tests/test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 96%]
tests/test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [100%]

============================= 29 passed in 15.81s =============================
```

### Frontend (`npm test` & `npm run build` in `<repo>/frontend`)
```text
> ai-engineering-agent-frontend@0.1.0 test
> vitest run

 RUN  v2.1.9 <repo>/frontend

 ✓ src/App.test.tsx (10 tests) 22ms

 Test Files  1 passed (1)
      Tests  10 passed (10)
   Duration  472ms (transform 103ms, setup 0ms, collect 154ms, tests 22ms, environment 0ms, prepare 90ms)

> ai-engineering-agent-frontend@0.1.0 build
> tsc --noEmit && vite build

vite v6.4.6 building for production...
transforming...
✓ 32 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-VNk5qLDz.css    5.80 kB │ gzip:  1.68 kB
dist/assets/index-QJ3yTA-h.js   203.65 kB │ gzip: 61.71 kB
✓ built in 457ms
```

### Repository Hygiene (`<repo>`)
```text
node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs
✔ no committed text file leaks local user home paths (Rule 12a) (38.5209ms)
✔ no committed file (including binaries) is tracked inside /workspaces/ (Rule 12a) (24.5839ms)
✔ local user path detector catches other drive letters ([A-Za-z]:\Users\) (0.2027ms)
✔ /workspaces/ detector flags tracked binary and text workspace paths (0.1588ms)
✔ all committed text files are valid UTF-8 without BOM (37.2002ms)
✔ Arabic sample file is tracked and decodes as valid UTF-8 with Arabic script (25.093ms)
ℹ tests 6
ℹ pass 6
ℹ fail 0
```

## 4. Acceptance Tests & Sample Inputs / Outputs

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| Three sample assignments (Arabic, English, mixed) produce structured understanding | **PASS** (mocked SDK) | `test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history` (`<repo>/backend/tests/test_tasks.py`) + sample API run below |
| Task History lists tasks with status, steps, logs, and token usage | **PASS** | `GET /api/tasks` & `GET /api/tasks/{task_id}` verified across 3 tasks + UI `<AssignmentsView />` SSR tests (`App.test.tsx`) |
| Failures are logged, not hidden | **PASS** | `test_step05_failures_are_logged_not_hidden_without_secret_leaks` verifies missing key, 401 auth error, and invalid JSON persist `status="failed"` + `task.failed` audit log without leaking fake secrets |
| `HTTP 503 UNAVAILABLE` retries with short exponential backoff (max 3 tries) | **PASS** | `test_gemini_provider_503_exponential_backoff_retry_and_exhaustion` verifies delays `[0.5, 1.0]`, max 3 tries, `list_models()` retry, non-retry for `401`, and HTTP `503` API mapping |

### Sample Inputs & Structured JSON Outputs (Observed via `POST /api/tasks`, Mocked SDK Client)

#### Sample 1 — Arabic (`ar`, `attached`: `clinic_plan.pdf`)
- **Input:** `مراجعة المخطط المعماري للعيادة الطبية بمساحة 1200 م2 مع الملف المرفق.`
- **Task State:** `status = "awaiting_clarification"`, `model_name = "gemini-3.8-flash"`, `total_tokens = 290`
```json
{
  "language_detected": "ar",
  "restated_assignment": "مراجعة المخطط المعماري للعيادة الطبية (1200 م2) والتحقق من المتطلبات المبدئية.",
  "primary_discipline": "Architectural",
  "secondary_disciplines": [
    "Fire & Life Safety",
    "Healthcare Engineering"
  ],
  "expected_deliverables": [
    "تقرير ملاحظات المراجعة المعمارية"
  ],
  "input_files": [
    {
      "filename": "clinic_plan.pdf",
      "role": "المخطط المعماري المبدئي",
      "status": "attached"
    }
  ],
  "applicable_standards_to_verify": [
    "NFPA 101 Life Safety Code",
    "FGI Guidelines"
  ],
  "missing_information": [
    "السعة التصميمية للمرضى"
  ],
  "assumptions": [
    "الاستخدام المبدئي مركز رعاية نهارية"
  ],
  "clarification_needed": true,
  "clarifying_questions": [
    "كم السعة التصميمية المتوقعة للمرضى وغرف الكشف؟"
  ],
  "recommended_next_steps": [
    "استخراج النصوص والجداول من ملف clinic_plan.pdf في الخطوة 06"
  ],
  "classification": "Preliminary"
}
```

#### Sample 2 — English (`en`, `complexity="deep"`)
- **Input:** `Check primary concrete beam for a 6.0m span against structural_framing.dxf.`
- **Task State:** `status = "completed"`, `model_name = "gemini-4-argon"`, `total_tokens = 290`
```json
{
  "language_detected": "en",
  "restated_assignment": "Verify a 6.0 m span reinforced concrete beam under preliminary dead and live loads.",
  "primary_discipline": "Structural",
  "secondary_disciplines": [],
  "expected_deliverables": [
    "Structural check plan and calculation outline"
  ],
  "input_files": [
    {
      "filename": "structural_framing.dxf",
      "role": "Beam framing plan referenced in prompt",
      "status": "missing"
    }
  ],
  "applicable_standards_to_verify": [
    "ACI 318 Structural Concrete Code"
  ],
  "missing_information": [],
  "assumptions": [
    "Proceed on preliminary rectangular section assumption once loads are extracted"
  ],
  "clarification_needed": false,
  "clarifying_questions": [],
  "recommended_next_steps": [
    "Confirm beam section dimensions before deterministic calculations"
  ],
  "classification": "Preliminary"
}
```

#### Sample 3 — Mixed Arabic + English (`mixed`, `attached`: `extension_schedule.xlsx`, `classification="For Review"`)
- **Input:** `إعداد مسودة BOQ المبدئي لمشروع Extension Building B باستخدام extension_schedule.xlsx.`
- **Task State:** `status = "completed"`, `model_name = "gemini-3.8-flash"`, `total_tokens = 290`
```json
{
  "language_detected": "mixed",
  "restated_assignment": "إعداد مسودة BOQ المبدئي لمشروع Extension Building B اعتماداً على جدول الكميات المرفق.",
  "primary_discipline": "Quantity Surveying / BOQ",
  "secondary_disciplines": [
    "Civil"
  ],
  "expected_deliverables": [
    "مسودة جدول كميات أولي (Draft BOQ)"
  ],
  "input_files": [
    {
      "filename": "extension_schedule.xlsx",
      "role": "Preliminary quantity schedule",
      "status": "attached"
    }
  ],
  "applicable_standards_to_verify": [
    "POMI / CESMM Principles of Measurement"
  ],
  "missing_information": [
    "تحديد العملة المعتمدة (LYD افتراضياً)"
  ],
  "assumptions": [
    "الكميات أولية بدون أسعار وحدة مخترعة"
  ],
  "clarification_needed": false,
  "clarifying_questions": [],
  "recommended_next_steps": [
    "قراءة جدول extension_schedule.xlsx في الخطوة 06"
  ],
  "classification": "For Review"
}
```

## 5. Decisions Made (Added to `<repo>/docs/DECISIONS.md` as `ADR-011`)
- Implemented `HTTP 503` exponential-backoff retry (`max 3 tries`, delays `0.5s`, `1.0s`) inside `GeminiProvider._call_with_503_retry` rather than retrying at the budget wrapper so failed/retried upstream handshakes still count as one logical request.
- Added Alembic migration `0004_step05_task_metadata` storing nullable structured output, attached file IDs, provider/model IDs, and token usage cleanly on `tasks` alongside ordered `task_steps` and `audit_log` rows.
- Committed failed assignment runs as persisted `Task(status="failed")` records returned cleanly to callers (`status="failed"`, sanitized `error_message`) so failures are always visible in Task History and UI error banners rather than dropped on transaction rollback.

## 6. Deviations from the Plan and Why
- Orchestrator v0 sends file manifests (filename, folder classification, extension, MIME type, byte size, SHA-256 hash, version) rather than extracting full document/CAD/spreadsheet contents internally, because document/spreadsheet/OCR extraction and DXF/IFC ingestion are explicitly scoped to Steps 06 and 07.
- Included inline local file staging + upload inside the **New Assignment** form (delegating through existing `ingest_project_files`) alongside multi-select of already-uploaded project files so the owner can attach new files and assign a task in one step without losing SHA-256 read-only guarantees.

## 7. Known Limitations / Things Not Verified
- All automated Step 05 backend and frontend tests use mocked Google SDK clients and synthetic non-live test credentials; live end-to-end Orchestrator v0 JSON generation against Google Gemini API (`gemini-3.8-flash` / `gemini-4-argon`) should be exercised locally by the owner using their keyring credential.
- Interactive clarity follow-up turns / background worker async execution (rather than synchronous request-response task creation) and full document parsing belong to subsequent steps (Step 06+).

## 8. Questions or Items Needed from the Owner
- Visual check of the **المهام والتكليفات / New Assignment & History** tab locally with Arabic RTL and English LTR layouts, plus optional live run of 1–3 sample assignments against your Gemini key stored in `WinVaultKeyring`.
- Review the Step 05 pull request and reply `PASS step 05` when ready to proceed to Step 06 (document, spreadsheet, and image extraction).

## 9. How the Owner Can See / Try It
1. Launch `<repo>/scripts/start.bat` (backend runs Alembic migrations through `0004` automatically at startup).
2. Ensure your Gemini key is saved in **AI Provider Settings** (already verified in `WinVaultKeyring`).
3. Switch to the **المهام والتكليفات / New Assignment & History** tab, choose an existing project (or create one in **المشاريع والملفات**), attach existing/new project files, enter an Arabic, English, or mixed assignment, and click **إرسال التكليف وتشغيل المنسّق / Submit Assignment & Run Orchestrator v0**.
4. Inspect the structured JSON card, steps, audit logs, token usage, and filterable **Task History** panel.

## 10. Ready for Next Step?
**Yes** — Step 05 scope is complete and ready for Step 06 once the Step 05 pull request is approved (`PASS step 05`) and merged into `main`.
