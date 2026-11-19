# Step 05 — Chat and Task Engine Foundation

- **Date:** 2026-11-19
- **Status:** **PARTIAL** *(backend API, migrations, automated suite, and live Gemini API 3-assignment smoke check complete; pending owner visual check of the Settings/Assignments UI)*
- **Branch:** `step-05-chat-and-task-engine`
- **Pull Request:** `#11`
- **Depends on:** Step 04 (`1ce4cfb`, PR `#10` squash-merged to `main` after owner `PASS step 04`)

## 1. Scope Done

### First Tasks (Confirmed Retained)
- **Completed Step 04 report (`<repo>/docs/reports/step-04.md`):** Updated status to **`COMPLETE`** and recorded all sanitized owner live Gemini results: connection OK on `gemini-3.5-flash-lite` (`585 ms`, `9 tokens`), clean invalid-key rejection (`ProviderAuthError`), structured JSON keys `classification`, `discipline`, `note` (`49 tokens`), PDF reading `'Concrete Beam Check Span 6.0m'` (`559 tokens`), image dominant colour blue (`1107 tokens`), `27` `generateContent` models from live refresh, and credential backend `WinVaultKeyring`.
- **Provider-layer `HTTP 503 UNAVAILABLE` retry (`<repo>/backend/app/providers/base.py`, `<repo>/backend/app/providers/gemini.py`, `<repo>/backend/app/api/settings.py`):** Added `ProviderServiceUnavailableError` (mapped to HTTP `503`) and `_call_with_503_retry(...)` with short exponential backoff (`max 3 tries`, delays `0.5s`, `1.0s`) across both `GeminiProvider.generate()` and `GeminiProvider.list_models()`, keeping logical single-request accounting in the usage ledger.

### Step 05 Feature Delivery & PR #11 Review Fixes
- **Database schema & migration (`<repo>/backend/alembic/versions/0004_step05_task_metadata.py`, `<repo>/backend/app/db/models.py`):** Added Alembic migration `0004` adding nullable columns on `tasks` (`complexity`, `provider_name`, `model_name`, `attached_file_ids_json`, `structured_output_json`, `token_usage_json`) while preserving Step 03 `ON DELETE RESTRICT` and `classification` `CHECK` constraints.
- **Owner classification preservation (`<repo>/backend/app/schemas/tasks.py`, `<repo>/backend/app/services/tasks.py`, `<repo>/frontend/src/components/AssignmentsView.tsx`):** `Task.classification` always keeps the owner's selected classification label (`payload.classification`); `OrchestratorUnderstanding.suggested_classification` is stored and surfaced solely as an advisory suggestion.
- **Orchestrator v0 prompt & guards (`<repo>/backend/app/agents/orchestrator.py`):**
  - Strictly instructs `restated_assignment` to restate ONLY explicit facts/numbers/units/materials/currencies stated by the user or project metadata without inventing qualifiers (`reinforced`, `day care`, `LYD` defaults, etc.).
  - Enforces `clarification_needed = true` (both in prompt rules and deterministically in `normalize_orchestrator_understanding()`) when referenced files are missing (`status == "missing"`) or when material engineering inputs (loads, section dimensions, material grades, occupancy/capacity, currency/rate basis) are absent.
  - JSON-encodes every untrusted block (`<UNTRUSTED_PROJECT_METADATA>`, `<UNTRUSTED_ATTACHED_FILES>`, `<UNTRUSTED_ASSIGNMENT_INPUT>`) and escapes `<` and `>` as `\u003c` and `\u003e` across project fields, filenames, and prompts to neutralize delimiter injection.
- **Task engine service, startup recovery & SQL log filtering (`<repo>/backend/app/services/tasks.py`, `<repo>/backend/app/api/tasks.py`, `<repo>/backend/app/main.py`):**
  - Added `POST /api/tasks`, `GET /api/tasks` (`project_id` and `status` filters, newest-first), and `GET /api/tasks/{task_id}`.
  - Filters task-linked `provider_usage` rows directly in SQL (`AuditLog.details_json["task_id"].as_string() == task.id`).
  - Added `mark_stale_running_tasks_interrupted(session_factory)` during FastAPI `lifespan` startup so orphaned `running` tasks and steps from a crash/restart are marked `failed` (interrupted) cleanly.
  - Persists provider/budget failures cleanly (`status="failed"`, sanitized `error_message`, failed `TaskStep`, `task.failed` audit log) without hiding failed tasks or leaking credentials.
- **Bilingual RTL/LTR UI (`<repo>/frontend/src/components/AssignmentsView.tsx`, `<repo>/frontend/src/App.tsx`, `<repo>/frontend/src/api.ts`, `<repo>/frontend/src/types.ts`, `<repo>/frontend/src/index.css`):**
  - Added **المهام والتكليفات / New Assignment & History** tab with New Assignment form (choose project, optional title, Arabic/English/mixed prompt, `fast`/`deep` complexity, owner classification, attach existing files or upload new files inline), structured JSON inspector (with separate advisory suggestion badge when different), execution steps/logs/usage panels, failure banners, and filterable Task History.

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

## 3. Tests Run (Pre-Commit Tree & Verified After Final Commit on Branch)

### Backend (`pytest -v` in `<repo>/backend`)
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>/backend/.venv/Scripts/python.exe
cachedir: .pytest_cache
rootdir: <repo>/backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 32 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [  3%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [  6%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [  9%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 12%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 15%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 18%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 21%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 25%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 28%]
tests/test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 31%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 34%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 37%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 40%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 43%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 46%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 50%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [ 53%]
tests/test_providers.py::test_keyring_secret_store_round_trip PASSED     [ 56%]
tests/test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 59%]
tests/test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 62%]
tests/test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 65%]
tests/test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 68%]
tests/test_providers.py::test_debug_logging_never_leaks_api_key PASSED   [ 71%]
tests/test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 75%]
tests/test_providers.py::test_provider_404_model_not_found_handling PASSED [ 78%]
tests/test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 81%]
tests/test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 84%]
tests/test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 87%]
tests/test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 90%]
tests/test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 93%]
tests/test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 96%]
tests/test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [100%]

============================= 32 passed in 17.07s =============================
```

### Frontend (`npm test` & `npm run build` in `<repo>/frontend`)
```text
> ai-engineering-agent-frontend@0.1.0 test
> vitest run

 RUN  v2.1.9 <repo>/frontend

 ✓ src/App.test.tsx (10 tests) 20ms

 Test Files  1 passed (1)
      Tests  10 passed (10)
   Duration  684ms (transform 114ms, setup 0ms, collect 188ms, tests 20ms, environment 0ms, prepare 263ms)

> ai-engineering-agent-frontend@0.1.0 build
> tsc --noEmit && vite build

vite v6.4.6 building for production...
transforming...
✓ 32 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-VNk5qLDz.css    5.80 kB │ gzip:  1.68 kB
dist/assets/index-cnzMj8Je.js   203.88 kB │ gzip: 61.71 kB
✓ built in 434ms
```

### Repository Hygiene (`<repo>`)
```text
node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs
✔ no committed text file leaks local user home paths (Rule 12a) (41.966ms)
✔ no committed file (including binaries) is tracked inside /workspaces/ (Rule 12a) (28.129ms)
✔ local user path detector catches other drive letters ([A-Za-z]:\Users\) (0.3554ms)
✔ /workspaces/ detector flags tracked binary and text workspace paths (0.2959ms)
✔ all committed text files are valid UTF-8 without BOM (39.0134ms)
✔ Arabic sample file is tracked and decodes as valid UTF-8 with Arabic script (26.4806ms)
ℹ tests 6
ℹ pass 6
ℹ fail 0
```

## 4. Acceptance Tests & Live Sample Inputs / Outputs (`gemini-3.5-flash-lite`)

| Acceptance / Review Check | Verdict | Evidence |
| --- | --- | --- |
| Three live sample assignments (Arabic, English, mixed) through app API | **PASS** (live Gemini API via `WinVaultKeyring`) | Executed live via `create_app()` + `TestClient` against an isolated temporary workspace with synthetic `clinic_plan_synth.pdf` and `extension_schedule_synth.csv` using `gemini-3.5-flash-lite` (real sanitized outputs pasted below) |
| Owner classification never overwritten by model suggestion | **PASS** (live + unit test) | Live Sample 1 & Sample 3 preserved `"Preliminary"` / `"For Review"` while model suggested `"For Review"` / `"Preliminary"`; verified in `test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history` |
| Missing referenced files & omitted material parameters set `clarification_needed = true` cleanly with zero fabricated facts | **PASS** (live + unit test) | Live Sample 2 set `clarification_needed: true`, marked `structural_framing.dxf` as `"missing"`, avoided adding `"reinforced"`, `"day care"`, or `"LYD"`; verified in `test_step05_missing_referenced_file_triggers_clarification` |
| Untrusted delimiter neutralization (`</UNTRUSTED_`, `<UNTRUSTED_`) | **PASS** | `test_step05_untrusted_delimiter_neutralization` (`build_orchestrator_v0_prompt` escapes `<` / `>` -> `\u003c` / `\u003e` in JSON blocks) |
| Failures logged cleanly + stale `running` startup recovery + SQL task usage filter | **PASS** | `test_step05_startup_marks_stale_running_tasks_interrupted`, `test_step05_failures_are_logged_not_hidden_without_secret_leaks`, and cross-task SQL filter assertion |
| `HTTP 503 UNAVAILABLE` retry (max 3 tries, exponential backoff) | **PASS** | `test_gemini_provider_503_exponential_backoff_retry_and_exhaustion` |

### Sanitized Live Gemini API Outputs (Scratch Project `SYNTH-05`, Synthetic Attachments Only, `gemini-3.5-flash-lite` via `WinVaultKeyring`)

> All 3 requests ran live through `POST /api/tasks` without reading, logging, or exposing any API key (`History total: 3`).

#### Live Sample 1 — Arabic (with synthetic `clinic_plan_synth.pdf` attached)
- **Owner Request:** `classification = "Preliminary"`, `complexity = "fast"`, prompt: `مراجعة المخطط المعماري لمبنى عيادة بمساحة 1200 م2 في ملف clinic_plan_synth.pdf المرفق، علماً بأن عدد الطوابق والسعة التصميمية غير محددين بعد.`
- **Observed Result:** HTTP `201`, `status = "awaiting_clarification"`, `classification = "Preliminary"`, `model_name = "gemini-3.5-flash-lite"`, `token_usage = {"prompt_tokens": 1341, "output_tokens": 470, "total_tokens": 1811, "thoughts_tokens": 0, "cached_tokens": 0, "latency_ms": 2304}`
```json
{
  "language_detected": "ar",
  "restated_assignment": "مراجعة المخطط المعماري لمبنى عيادة بمساحة 1200 م2 في ملف clinic_plan_synth.pdf المرفق، علماً بأن عدد الطوابق والسعة التصميمية غير محددين بعد.",
  "primary_discipline": "Architectural",
  "secondary_disciplines": [
    "Healthcare Engineering",
    "Fire & Life Safety"
  ],
  "expected_deliverables": [
    "تقرير مراجعة المخطط المعماري",
    "تحديد الملاحظات الفنية للمساحة المعمارية"
  ],
  "input_files": [
    {
      "filename": "clinic_plan_synth.pdf",
      "role": "مخطط معماري لمبنى العيادة",
      "status": "attached"
    }
  ],
  "applicable_standards_to_verify": [
    "الكود الليبي للبناء",
    "NFPA 101"
  ],
  "missing_information": [
    "عدد الطوابق",
    "السعة التصميمية",
    "نوع النشاط الطبي الدقيق",
    "المواصفات الإنشائية والمواد المستخدمة"
  ],
  "assumptions": [
    "مساحة المبنى الإجمالية هي 1200 م2 كما وردت في نص المهمة."
  ],
  "clarification_needed": true,
  "clarifying_questions": [
    "ما هو عدد الطوابق المطلوب لمبنى العيادة؟",
    "ما هي السعة التصميمية أو العدد المتوقع للمرضى والمراجعين؟"
  ],
  "recommended_next_steps": [
    "استخراج محتوى ملف clinic_plan_synth.pdf المرفق وفحصه",
    "التواصل مع العميل لتوضيح عدد الطوابق والسعة التصميمية"
  ],
  "suggested_classification": "For Review"
}
```

#### Live Sample 2 — English (unattached missing file `structural_framing.dxf` & omitted parameters)
- **Owner Request:** `classification = "Preliminary"`, `complexity = "fast"`, prompt: `Prepare an intake review for a 6.0 m span beam referenced against structural_framing.dxf without providing section dimensions, concrete grade, or design loads.`
- **Observed Result:** HTTP `201`, `status = "awaiting_clarification"`, `classification = "Preliminary"`, `model_name = "gemini-3.5-flash-lite"`, `token_usage = {"prompt_tokens": 1134, "output_tokens": 394, "total_tokens": 1528, "thoughts_tokens": 0, "cached_tokens": 0, "latency_ms": 1951}`
```json
{
  "language_detected": "en",
  "restated_assignment": "Prepare an intake review for a 6.0 m span beam referenced against structural_framing.dxf without providing section dimensions, concrete grade, or design loads.",
  "primary_discipline": "Structural",
  "secondary_disciplines": [
    "Architectural"
  ],
  "expected_deliverables": [
    "Intake review report"
  ],
  "input_files": [
    {
      "filename": "structural_framing.dxf",
      "role": "Referenced structural framing drawing",
      "status": "missing"
    }
  ],
  "applicable_standards_to_verify": [
    "ACI 318",
    "Libyan engineering regulations"
  ],
  "missing_information": [
    "Section dimensions",
    "Concrete grade",
    "Design loads",
    "structural_framing.dxf file attachment"
  ],
  "assumptions": [
    "The 6.0 m span beam is simply supported or continuous as indicated in the missing drawing."
  ],
  "clarification_needed": true,
  "clarifying_questions": [
    "Can you please provide the structural_framing.dxf file?",
    "What are the cross-section dimensions, concrete grade, and design loads for the 6.0 m span beam?"
  ],
  "recommended_next_steps": [
    "Obtain missing input file structural_framing.dxf",
    "Collect missing structural parameters including section dimensions, concrete grade, and design loads",
    "Verify applicable design standards"
  ],
  "suggested_classification": "Preliminary"
}
```

#### Live Sample 3 — Mixed Arabic + English (with synthetic `extension_schedule_synth.csv` attached)
- **Owner Request:** `classification = "For Review"`, `complexity = "fast"`, prompt: `إعداد مسودة جدول الكميات المبدئي Draft BOQ لمشروع Extension Building B باستخدام ملف extension_schedule_synth.csv المرفق مع توضيح البيانات الناقصة دون اختراع أسعار وحدة.`
- **Observed Result:** HTTP `201`, `status = "awaiting_clarification"`, `classification = "For Review"`, `model_name = "gemini-3.5-flash-lite"`, `token_usage = {"prompt_tokens": 1334, "output_tokens": 533, "total_tokens": 1867, "thoughts_tokens": 0, "cached_tokens": 0, "latency_ms": 2417}`
```json
{
  "language_detected": "ar",
  "restated_assignment": "إعداد مسودة جدول الكميات المبدئي Draft BOQ لمشروع Extension Building B باستخدام ملف extension_schedule_synth.csv المرفق مع توضيح البيانات الناقصة دون اختراع أسعار وحدة.",
  "primary_discipline": "Quantity Surveying / BOQ",
  "secondary_disciplines": [
    "Project Planning",
    "Architectural"
  ],
  "expected_deliverables": [
    "مسودة جدول الكميات المبدئي (Draft BOQ)",
    "قائمة البيانات الناقصة"
  ],
  "input_files": [
    {
      "filename": "extension_schedule_synth.csv",
      "role": "ملف جداول كميات أو جدول زمني للمشروع",
      "status": "attached"
    }
  ],
  "applicable_standards_to_verify": [
    "Libyan standard method of measurement for civil engineering and building works",
    "Standard Quantity Surveying Practice"
  ],
  "missing_information": [
    "أسعار الوحدات",
    "تفاصيل الأبعاد والرسومات التفصيلية للمبنى Extension Building B",
    "المواصفات الفنية للمواد"
  ],
  "assumptions": [
    "الاعتماد على البيانات المتاحة في ملف extension_schedule_synth.csv المرفق فقط لحين توفر تفاصيل إضافية"
  ],
  "clarification_needed": true,
  "clarifying_questions": [
    "ما هي المواصفات الفنية ومقاسات العناصر الواردة في المشروع Extension Building B؟",
    "هل توجد رسومات أو مستندات تصميمية إضافية توضح الأبعاد والكميات بدقة؟",
    "ما هي العملة المعتمدة وأساس التسعير لأسعار الوحدات المطلوبة لاحقاً؟"
  ],
  "recommended_next_steps": [
    "استخراج محتويات ملف extension_schedule_synth.csv المرفق",
    "مراجعة الكميات المتاحة ومطابقتها مع نطاق العمل",
    "تحديد البنود التي تفتقر إلى الأسعار أو التفاصيل وإعداد قائمة بالبيانات الناقصة"
  ],
  "suggested_classification": "Preliminary"
}
```

## 5. Decisions Made (Recorded in `<repo>/docs/DECISIONS.md` as `ADR-011`)
- Retained owner `Task.classification` unconditionally (`suggested_classification` stored strictly as advisory metadata on `structured_output`).
- Neutralized untrusted XML delimiters via JSON encoding + escaping `<` and `>` as `\u003c` and `\u003e` across every untrusted input block.
- Added startup recovery (`mark_stale_running_tasks_interrupted`) to fail any orphaned `"running"` tasks/steps after restart, and SQL-level `JSON_EXTRACT` / `->>` filtering for task-specific `provider_usage` rows.
- Kept `HTTP 503 UNAVAILABLE` short exponential backoff retry (`max 3 tries`) in `GeminiProvider`.

## 6. Deviations from the Plan and Why
- Orchestrator v0 inspects attached file metadata manifests (filename, folder classification, extension, MIME type, size, SHA-256, version) rather than extracting full document/CAD/spreadsheet bodies internally, because Steps 06 and 07 implement extraction and drawing ingestion.
- Live Sample 3 (`Mixed Arabic + English`) was labeled `"language_detected": "ar"` by `gemini-3.5-flash-lite` because the matrix sentence was Arabic with English project/deliverable identifiers; both `"ar"` and `"mixed"` paths are covered.

## 7. Known Limitations / Things Not Verified
- **Marked `PARTIAL` pending owner UI inspection:** All backend endpoints, live Gemini API calls (Arabic, English, mixed on `gemini-3.5-flash-lite`), Vitest SSR component tests, and Vite production build succeeded, while interactive browser inspection of the Arabic RTL / English LTR **New Assignment & Task History** UI by the owner has not yet been completed.
- Interactive clarification answer submission and background worker queues remain outside Step 05 scope (deferred to Step 06+).

## 8. Questions or Items Needed from the Owner
- Open the running app (`<repo>/scripts/start.bat`), inspect **المهام والتكليفات / New Assignment & History** visually in Arabic RTL and English LTR (create a project task, attach a file, view structured output, test history filters), and confirm `PASS step 05` on PR `#11` when satisfied.

## 9. How the Owner Can See / Try It
1. Launch `<repo>/scripts/start.bat` (Alembic upgrades cleanly through `0004` and startup marks any stale `running` tasks as interrupted).
2. Confirm your active fast model in **AI Provider Settings** (e.g., `gemini-3.5-flash-lite` or `gemini-3.8-flash`).
3. Switch to **المهام والتكليفات / New Assignment & History**, choose a project, attach existing/new files, run an assignment, and inspect the structured JSON card, advisory classification suggestion (if different), steps, audit logs, token usage, and Task History filters.

## 10. Ready for Next Step?
**Pending owner UI check (`PARTIAL`)** — Backend, Orchestrator v0, live 3-language Gemini verification, frontend build/unit checks, and security hardening are in place; ready for Step 06 once the owner inspects the UI and approves (`PASS step 05`) + merges PR `#11`.
