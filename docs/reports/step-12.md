# Step 12 — Independent QA Agent & Issue Register (`0` AI Tokens)

- **Date:** 2026-11-21
- **Status:** **PARTIAL** *(Delivers relational `qa_reviews`, extended `issues`, and `Task.verification_status` / `Task.last_qa_review_id` via reversible migration `0010`; strict producer-reasoning isolation (`PRODUCER_REASONING_EXCLUDED_FIELDS` omitted from QA context); deterministic `0`-AI-token verifiers across arithmetic (`Decimal`, XLSX live formulas, Shoelace polygon recomputation), units (incompatible/unconfirmed/mixed units), references (`ResearchSource.reviewed=True` + drawing/report `EXT-*`/`RES-*` links), drawing/BOQ/schedule consistency (`door_schedule`/`window_schedule`/floor area + CAD round-trip), and deliverable disk/SHA-256 integrity; sequential Issue Register CRUD & close/reopen lifecycle (`QA-001+`) enforcing the `POST /api/tasks/{task_id}/verify` gate (`HTTP 422` whenever unverified or open issues remain); bilingual Arabic RTL & English LTR `QaIssuesView` + `AssignmentsView` verification badge; `83 passed, 4 skipped` full backend `pytest -v`, `4 passed` opt-in real external checks (`ODAFileConverter`, `Tesseract`, live research), and `21 passed` frontend Vitest + `tsc --noEmit` + Vite production build; live desktop/browser interactive walkthrough by the owner remains `PENDING`.)*
- **Branch:** `step-12-qa-issue-register`
- **Depends on:** Step 11 (`b1fa34c`, PR `#20` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`backend/app/db/models.py`, `backend/alembic/versions/0010_step12_qa_reviews_and_issues.py`):**
   - Added `Task.verification_status` (`CHECK IN ('unverified', 'qa_passed', 'qa_failed', 'verified')`, server default `'unverified'`) and `Task.last_qa_review_id` FK onto `qa_reviews`.
   - Added `QaReview` (`qa_reviews` table) storing project/task scope, classification, status, `producer_reasoning_excluded` flag, `qa_context_snapshot_json`, `checks_summary_json`, `issues_opened_count`, `open_issues_count`, and `token_usage_json` (`tokens_used=0`).
   - Extended `Issue` (`issues` table) with `qa_review_id` FK, `check_category`, `closure_note`, and `closed_at` alongside `issue_number`, `description`, `discipline`, `severity`, `reference`, `recommended_action` (exposed as `corrective_action`), and `status`.

2. **Producer-Reasoning Isolation (`backend/app/agents/qa_agent.py`):**
   - `build_isolated_qa_context` and `serialize_isolated_qa_prompt_context` build a separate QA snapshot containing only raw project deliverables (`BoqSheet`/`BoqItem`, `ParametricDrawing`, `ReviewReport` facts/findings/registry, `Deliverable` disk metadata), `FileExtraction`, `ProjectFile`, and `ResearchSource` provenance logs.
   - Explicitly omits `PRODUCER_REASONING_EXCLUDED_FIELDS`: `Task.plan_summary`, `Task.result_summary`, `Task.structured_output_json`, `TaskStep.notes`, `TaskStep.output_payload.understanding`, and `ReviewReport.ai_reasoning`.
   - Verified in `test_step12_qa_context_excludes_producer_reasoning_and_task_never_verified_by_generation_alone`: canary string `PRODUCER_SECRET_CHAIN_OF_THOUGHT_DO_NOT_LEAK_777` injected across task plans, summaries, step notes, and reasoning never appears anywhere in the serialized QA prompt/context (`producer_reasoning_excluded=True`).

3. **Deterministic Independent Checks (`0` AI Tokens, `evaluate_independent_qa` in `backend/app/agents/qa_agent.py`):**
   - **Arithmetic (`arithmetic`):** Recomputes every BOQ item `Decimal(quantity) * Decimal(unit_rate)` against stored `total` and imported `reported_total`, checks exported `.xlsx` workbooks (`openpyxl`) for formula-missing totals, and recomputes every `ParametricDrawing` room area via Shoelace (`compute_room_metrics`) vs stored `total_area_m2` and `room_count`.
   - **Units (`unit`):** Flags unconfirmed/doubtful CAD/BOQ units, incompatible unit-to-description pairs (e.g., `m2` on countable doors/windows), mixed units across grouped BOQ sections, and unconfirmed parametric drawing units.
   - **References (`reference`):** Validates cited URLs and standard references on BOQ items (`technical_reference`, `rate_source_ref`) against project `ResearchSource` rows with `reviewed=True`, checks `drawing_reference` against issued `ParametricDrawing` sheets / uploaded CAD/PDF files, and cross-checks `ReviewReport` findings against `source_registry` + `FileExtraction` / `ResearchSource` logs (catching fabricated IDs like `EXT-999` or unreviewed HTTP 403 URLs).
   - **Consistency (`schedule_consistency`):** Cross-checks parametric drawing `door_schedule` & `window_schedule` quantities against BOQ door/window item quantities, compares drawing total room floor area against project-level floor finish quantities, and checks DXF round-trip flags.
   - **Deliverables & Integrity (`missing_deliverable` / `integrity`):** Audits expected task deliverables, checks `ReviewReport` DOCX/PDF outputs in `08_Reports` and `10_Final_Deliverables`, checks registered `Deliverable` files on disk, and verifies file `sha256` checksums cleanly.

4. **Issue Register Lifecycle & Task Verification Gate (`backend/app/services/qa.py`, `backend/app/api/qa.py`, `backend/app/schemas/qa.py`):**
   - `run_project_qa_review` (`POST /api/projects/{project_id}/qa-reviews`) assigns sequential issue codes (`QA-001`, `QA-002`, ...) to open defects, updates `Task.verification_status` to `"qa_passed"` (`0` findings & `0` open issues) or `"qa_failed"`, and records `tokens_used=0`.
   - `verify_task_after_qa` (`POST /api/tasks/{task_id}/verify`) enforces the hard gate: a newly generated or completed task starts `"unverified"`, can **never** be marked `"verified"` by generation alone, and rejects `/verify` (`HTTP 422`) until an independent passing `QaReview` exists and zero open issues remain.
   - Full Issue Register endpoints: `GET /api/projects/{project_id}/qa-reviews`, `GET /api/qa-reviews/{review_id}`, `GET /api/projects/{project_id}/issues` (filterable by `status`, `severity`, `task_id`), `POST /api/projects/{project_id}/issues` (manual issue creation), and `PATCH /api/issues/{issue_id}` (close with `closure_note` & `closed_at`, or reopen — which automatically resets an already-verified task back to `"qa_failed"`).

5. **Bilingual RTL/LTR Frontend UI (`frontend/src/components/QaIssuesView.tsx`, `AssignmentsView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added the **الجودة وسجل القضايا (QA) / QA & Issue Register** tab (`initialTab="qa"`), displaying producer-reasoning isolation confirmation, deterministic check metric breakdown (`arithmetic`, `unit`, `reference`, `schedule_consistency`, `missing_deliverable`), Issue Register table (`issue_number`, `description`, `discipline`, `severity`, `reference`, `corrective_action`, `status`, closure notes), status filtering (`All` / `Open` / `Closed`), manual issue logging form, close/reopen buttons, and the **Verify Task** gate button.
   - Added `verification_status` badge (`unverified`, `qa_passed`, `qa_failed`, `verified`) in `AssignmentsView.tsx`.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0010_step12_qa_reviews_and_issues.py`
- `<repo>/backend/app/agents/qa_agent.py`
- `<repo>/backend/app/api/qa.py`
- `<repo>/backend/app/schemas/qa.py`
- `<repo>/backend/app/services/qa.py`
- `<repo>/backend/tests/test_qa.py`
- `<repo>/frontend/src/components/QaIssuesView.tsx`
- `<repo>/docs/reports/step-12.md`

### Changed
- `<repo>/backend/app/db/models.py` *(Step 12 `Task.verification_status`, `Task.last_qa_review_id`, `QaReview`, extended `Issue`, `Project.qa_reviews`)*
- `<repo>/backend/app/main.py` *(registered `qa_router`)*
- `<repo>/backend/app/schemas/tasks.py` *(added `verification_status` and `last_qa_review_id` on `TaskSummaryOut`)*
- `<repo>/backend/app/services/tasks.py` *(defaulted new task `verification_status="unverified"` and serialized verification fields)*
- `<repo>/backend/tests/test_migrations.py` *(added `qa_reviews` to `EXPECTED_TABLES`)*
- `<repo>/docs/DECISIONS.md` *(added `ADR-021`)*
- `<repo>/frontend/src/App.test.tsx` *(Step 12 `QaIssuesView`, isolation banner, Arabic/English UI & API Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(`qa` tab wiring & Step 12 subtitle)*
- `<repo>/frontend/src/api.ts` *(Step 12 QA & Issue Register API functions)*
- `<repo>/frontend/src/components/AssignmentsView.tsx` *(`verification_status` badge display)*
- `<repo>/frontend/src/types.ts` *(Step 12 TypeScript interfaces)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Seeded-Error QA Output (`0` AI Tokens)

Executed against a synthetic project containing all five seeded defect classes (wrong totals, wrong/unconfirmed units, fake/unreviewed references, door schedule mismatch, and missing disk/report deliverables) with producer secrets stored on `Task.plan_summary` and `Task.result_summary`:

```text
QA_STATUS: issues_found TASK_VERIF: qa_failed TOKENS: 0
PRODUCER_EXCLUDED: True ['Task.plan_summary', 'Task.result_summary', 'Task.structured_output_json', 'TaskStep.notes', 'TaskStep.output_payload.understanding', 'ReviewReport.ai_reasoning']
CHECKS: [{"category": "arithmetic", "checked_count": 4, "failed_count": 3, "passed": false, "details": "Recomputed 4 BOQ/XLSX/drawing arithmetic target(s); found 3 issue(s)."}, {"category": "unit", "checked_count": 4, "failed_count": 2, "passed": false, "details": "Checked 4 BOQ items/drawings/CAD units; found 2 unit issue(s)."}, {"category": "reference", "checked_count": 7, "failed_count": 5, "passed": false, "details": "Verified 7 report/BOQ source & drawing references against project logs; found 5 issue(s)."}, {"category": "schedule_consistency", "checked_count": 2, "failed_count": 1, "passed": false, "details": "Evaluated 2 drawing/BOQ/schedule consistency cross-check(s); found 1 issue(s)."}, {"category": "missing_deliverable", "checked_count": 7, "failed_count": 2, "passed": false, "details": "Verified 7 deliverable disk/checksum/completeness expectation(s); found 2 issue(s)."}]
QA-001 [arithmetic|high|open] Arithmetic mismatch on BOQ item 'B-01' (Doors per A-101 schedule): recomputed 9.0 * 200.0 = 1800.0000 LYD, stored total = 9999.0. | ref=BOQ Seeded BOQ / Item B-01 | action=Recompute and set item total strictly to 1800.0000 LYD.
QA-002 [arithmetic|high|open] Imported BOQ item 'B-01' reported_total=8888.0 disagrees with code-recomputed 9.0 * 200.0 = 1800.0000. | ref=BOQ Seeded BOQ / Item B-01 | action=Reconcile imported spreadsheet/PDF arithmetic against quantity x rate.
QA-003 [arithmetic|high|open] Drawing A-101 stores total_area_m2=123.45, whereas independent Shoelace recomputation yields 80.00 m2. | ref=Drawing A-101 (7b53ecc2) | action=Regenerate parametric drawing metrics cleanly from coordinates.
QA-004 [unit|high|open] BOQ item 'B-02' ('Interior flush door frame') uses 'm2' instead of a count unit such as 'nos'. | ref=BOQ Seeded BOQ / Item B-02 | action=Change unit to 'nos' and verify quantity against opening schedule.
QA-005 [unit|high|open] BOQ item 'B-03' uses unconfirmed/doubtful unit 'unconfirmed (ft)'. | ref=BOQ Seeded BOQ / Item B-03 | action=Confirm drawing units via /api/extractions/{id}/confirm-unit and re-import BOQ.
QA-006 [reference|critical|open] Review Report 'Seeded Report' (findings) cites unknown reference ID 'EXT-999' which does not exist in source_registry or source logs. | ref=Report Rev 01 / EXT-999 | action=Remove fabricated citation or bind claim to an actual verified source ID.
QA-007 [reference|high|open] BOQ item 'B-02' technical_reference cites 'https://fake-source.invalid/not-in-log', which does not exist as a reviewed source in ResearchSource logs. | ref=BOQ Seeded BOQ / Item B-02 | action=Verify URL via Research tab or replace with an actual project source.
QA-008 [reference|high|open] BOQ item 'B-02' cites drawing reference 'DWG-FAKE-999' (DWG-FAKE-999), which matches no project parametric drawing or uploaded file. | ref=BOQ Seeded BOQ / Item B-02 | action=Update drawing_reference to match an issued drawing sheet or upload the missing sheet.
QA-009 [reference|high|open] BOQ item 'B-02' carries suspicious unverified reference 'DWG-FAKE-999'. | ref=BOQ Seeded BOQ / Item B-02 | action=Replace placeholder reference with an authoritative file/drawing link.
QA-010 [reference|high|open] BOQ item 'B-03' dated_research rate cites 'https://blocked.invalid/iec-60439', which is not a reviewed ResearchSource in the source log. | ref=BOQ Seeded BOQ / Item B-03 | action=Link rate_source_ref to a reviewed ResearchSource URL or convert to owner_input.
QA-011 [schedule_consistency|high|open] Schedule mismatch: Drawing A-101 Door Schedule specifies 5 door(s), whereas BOQ 'Seeded BOQ' quantifies 9 door(s). | ref=Drawing A-101 <-> BOQ Seeded BOQ | action=Reconcile BOQ door quantities to match Drawing A-101 Door Schedule (5 nos) or revise drawing.
QA-012 [missing_deliverable|critical|open] Registered deliverable file '05_Design_Drawings/A_101_7b53ecc2_v1.pdf' is missing on disk. | ref=05_Design_Drawings/A_101_7b53ecc2_v1.pdf | action=Regenerate or restore deliverable file and verify SHA-256.
QA-013 [missing_deliverable|high|open] Review Report 'Seeded Report' is missing output(s): 08_Reports:docx, 08_Reports:pdf, 10_Final_Deliverables:docx, 10_Final_Deliverables:pdf. | ref=Report Rev 01 | action=Regenerate DOCX + PDF into 08_Reports and 10_Final_Deliverables.
```

## 4. Tests Run (Unedited Summary & External Checks)

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
collected 87 items

... (all non-opt-in test modules passed cleanly, including:)
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 52%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 54%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 55%]
backend\tests\test_qa.py::test_step12_qa_context_excludes_producer_reasoning_and_task_never_verified_by_generation_alone PASSED [ 71%]
backend\tests\test_qa.py::test_step12_qa_catches_all_seeded_errors_and_manages_issue_register_lifecycle PASSED [ 72%]

================== 83 passed, 4 skipped in 124.28s (0:02:04) ==================
```

*(Note: 4 skipped tests are the opt-in live external tool/network checks executed explicitly below.)*

### Opt-In Real External Checks (`RUN_REAL_ODA=1`, `RUN_REAL_OCR=1`, `RUN_REAL_RESEARCH=1`)

```text
> $env:RUN_REAL_ODA="1"; $env:RUN_REAL_OCR="1"; $env:RUN_REAL_RESEARCH="1"; & "backend\.venv\Scripts\pytest.exe" backend/tests -k "optin_real" -v -s
collecting ... collected 87 items / 83 deselected / 4 selected

backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf PASSED
backend\tests\test_drawings.py::test_optin_real_oda_step11_parametric_dxf_roundtrip PASSED
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture PASSED
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data PASSED

====================== 4 passed, 83 deselected in 14.24s ======================
```

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)

```text
✓ src/App.test.tsx (21 tests) 61ms
Test Files 1 passed (1) | Tests 21 passed (21) | Duration 653ms
tsc --noEmit && vite build -> 37 modules transformed -> built in 540ms
```

### Repo Hygiene & Protected Files
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across `backend`, `frontend/src`, `docs`, `scripts`: `BOM_FILES: []`.
- Local-path & secret-pattern check across committed dirs: clean (no local user paths or secrets).
- `gitleaks` full git-history & tracked directory scan executed on committed branch HEAD.

## 5. Known Limits & Owner Review Needed
1. **Live Browser Interactive QA Workflow (`PENDING` owner check):** Automated Vitest + FastAPI `TestClient` suites verify rendering and API round-trips end-to-end; interactive visual review of the bilingual **QA & Issue Register** tab, issue filtering, closure notes, and task verification badge transitions in the running desktop browser remains for the owner.
2. **Deterministic Scope vs Engineering Judgment:** Step 12 independent QA deterministically verifies arithmetic formulas/totals, units, source-log & drawing references, CAD/BOQ/schedule quantities, and file integrity at `0` AI tokens; specialized structural/MEP code compliance judgment still belongs to licensed engineering reviewers supported by Research and Review Reports.

## 6. Checklist
- [x] Branch `step-12-qa-issue-register` branched cleanly from updated `main` (`b1fa34c`)
- [x] Reversible migration `0010_step12_qa_reviews_and_issues` (`Task.verification_status`, `qa_reviews`, extended `issues`)
- [x] Isolated QA context excludes all producer reasoning (`Task.plan_summary`, `Task.result_summary`, `Task.structured_output_json`, `TaskStep.notes`, `ReviewReport.ai_reasoning`)
- [x] Deterministic checks (`0` AI tokens) catch seeded wrong totals, wrong/unconfirmed units, fake/unreviewed references, drawing/BOQ schedule mismatches, and missing deliverables
- [x] Issue Register CRUD API & bilingual RTL/LTR UI (`issue_number`, `description`, `discipline`, `severity`, `reference`, `corrective_action`, `status`, close/reopen lifecycle)
- [x] Generation alone never marks tasks `"verified"`; `/verify` enforces passing QA + zero open issues (`HTTP 422` otherwise)
- [x] `ADR-021` added in `docs/DECISIONS.md`
- [x] `docs/reports/step-12.md` marked **`PARTIAL`** until owner live UI walkthrough
- [x] Pushed `step-12-qa-issue-register` only (`main` untouched, no merge)
