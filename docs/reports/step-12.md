# Step 12 — Independent QA Agent & Issue Register (`0` AI Tokens)

- **Date:** 2026-11-21
- **Status:** **PARTIAL** *(Delivers relational `qa_reviews`, extended `issues`, and `Task.verification_status` / `Task.last_qa_review_id` via reversible migration `0010`; strict producer-reasoning isolation (`PRODUCER_REASONING_EXCLUDED_FIELDS` omitted from QA context); deterministic `0`-AI-token verifiers across arithmetic (`Decimal`, XLSX live formulas + `integrity` finding on corrupt/unreadable XLSX, Shoelace polygon recomputation), units (incompatible/unconfirmed/mixed units), references (`ResearchSource.reviewed=True` + drawing/report `EXT-*`/`RES-*` links), drawing/BOQ/schedule consistency (`door_schedule`/`window_schedule`/floor area + CAD round-trip), and deliverable disk/SHA-256/expected-deliverable completeness; zero-artefact QA runs marked `no_evidence` (`qa_failed`, `/verify` `HTTP 422`); sequential Issue Register CRUD & close/reopen lifecycle (`QA-001+`) enforcing `>= 10`-character `closure_note` and requiring a fresh QA re-run after the last issue closure before `POST /api/tasks/{task_id}/verify` succeeds (`HTTP 422` otherwise); bilingual Arabic RTL & English LTR `QaIssuesView` with required closure-note prompt and **Re-run QA** controls + `AssignmentsView` verification badge; `86 passed, 4 skipped` full backend `pytest -v`, `21 passed` frontend Vitest + `tsc --noEmit` + Vite production build, and `gitleaks` clean scan; live desktop/browser interactive walkthrough by the owner remains `PENDING`.)*
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
   - **Arithmetic (`arithmetic` & `integrity`):** Recomputes every BOQ item `Decimal(quantity) * Decimal(unit_rate)` against stored `total` and imported `reported_total`, inspects exported `.xlsx` workbooks (`openpyxl`) for formula-missing totals (and raises a `high`-severity `integrity` finding whenever an exported `.xlsx` is missing, corrupt, or unreadable instead of skipping silently), and recomputes every `ParametricDrawing` room area via Shoelace (`compute_room_metrics`) vs stored `total_area_m2` and `room_count`.
   - **Units (`unit`):** Flags unconfirmed/doubtful CAD/BOQ units, incompatible unit-to-description pairs (e.g., `m2` on countable doors/windows), mixed units across grouped BOQ sections, and unconfirmed parametric drawing units.
   - **References (`reference`):** Validates cited URLs and standard references on BOQ items (`technical_reference`, `rate_source_ref`) against project `ResearchSource` rows with `reviewed=True`, checks `drawing_reference` against issued `ParametricDrawing` sheets / uploaded CAD/PDF files, and cross-checks `ReviewReport` findings against `source_registry` + `FileExtraction` / `ResearchSource` logs (catching fabricated IDs like `EXT-999` or unreviewed HTTP 403 URLs).
   - **Consistency (`schedule_consistency`):** Cross-checks parametric drawing `door_schedule` & `window_schedule` quantities against BOQ door/window item quantities, compares drawing total room floor area against project-level floor finish quantities, and checks DXF round-trip flags.
   - **Deliverables, Integrity & No-Evidence Guard (`missing_deliverable` / `integrity` / `no_evidence`):** Audits expected task deliverables (both keyword-matched BOQ/drawing/report labels and generic deliverable labels), checks `ReviewReport` DOCX/PDF outputs in `08_Reports` and `10_Final_Deliverables`, checks registered `Deliverable` files on disk, and verifies file `sha256` checksums cleanly. Any QA review that inspects zero concrete artefacts (`0` BOQs, drawings, reports, or deliverables, or `0` executed check targets) is assigned `status="no_evidence"` (never `"passed"`), sets `Task.verification_status="qa_failed"`, and is blocked by `/verify` (`HTTP 422`).

4. **Issue Register Lifecycle & Task Verification Gate (`backend/app/services/qa.py`, `backend/app/api/qa.py`, `backend/app/schemas/qa.py`):**
   - `run_project_qa_review` (`POST /api/projects/{project_id}/qa-reviews`) assigns sequential issue codes (`QA-001`, `QA-002`, ...) to open defects, updates `Task.verification_status` to `"qa_passed"` only when `status == "passed"` (`0` open issues and `>= 1` inspected artefact) or `"qa_failed"` otherwise (`issues_found` / `no_evidence`), and records `tokens_used=0`.
   - `verify_task_after_qa` (`POST /api/tasks/{task_id}/verify`) enforces the hard gate: a newly generated or completed task starts `"unverified"`, can **never** be marked `"verified"` by generation alone, and rejects `/verify` (`HTTP 422`) unless `qa_row.status == "passed"`, `>= 1` artefact was inspected, zero open issues remain, AND a new passing `QaReview` created strictly after the latest issue closure timestamp (`closed_at`) exists for the task (prompting the owner to re-run QA otherwise).
   - Full Issue Register endpoints: `GET /api/projects/{project_id}/qa-reviews`, `GET /api/qa-reviews/{review_id}`, `GET /api/projects/{project_id}/issues` (filterable by `status`, `severity`, `task_id`), `POST /api/projects/{project_id}/issues` (manual issue creation), and `PATCH /api/issues/{issue_id}` (closing requires a non-empty `closure_note` of at least `10` trimmed characters — `HTTP 422` otherwise — and never flips a `QaReview` to `"passed"` without a re-run; reopening automatically resets an already-verified task back to `"qa_failed"`).

5. **Bilingual RTL/LTR Frontend UI (`frontend/src/components/QaIssuesView.tsx`, `AssignmentsView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added the **الجودة وسجل القضايا (QA) / QA & Issue Register** tab (`initialTab="qa"`), displaying producer-reasoning isolation confirmation, deterministic check metric breakdown (`arithmetic`, `unit`, `reference`, `schedule_consistency`, `missing_deliverable` with `NO EVIDENCE` badge when `checked_count === 0`), Issue Register table (`issue_number`, `description`, `discipline`, `severity`, `reference`, `corrective_action`, `status`, closure notes), status filtering (`All` / `Open` / `Closed`), manual issue logging form, required `>= 10`-character closure-note prompt (`Close Issue` -> `Confirm Close` / `Cancel`), explicit **Re-run QA** controls/banners after closures or `no_evidence` outcomes, and the **Verify Task** gate button.
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

## 4. Tests Run (Unedited Summary & Secret Scan)

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
collected 90 items

... (all non-opt-in test modules passed cleanly, including:)
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 51%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 52%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 53%]
backend\tests\test_qa.py::test_step12_qa_context_excludes_producer_reasoning_and_task_never_verified_by_generation_alone PASSED [ 68%]
backend\tests\test_qa.py::test_step12_qa_catches_all_seeded_errors_and_manages_issue_register_lifecycle PASSED [ 70%]
backend\tests\test_qa.py::test_step12_empty_project_qa_is_no_evidence_and_verify_returns_422 PASSED [ 71%]
backend\tests\test_qa.py::test_step12_issue_closure_requires_note_and_verify_requires_qa_rerun PASSED [ 72%]
backend\tests\test_qa.py::test_step12_corrupt_xlsx_raises_integrity_finding PASSED [ 73%]

================== 86 passed, 4 skipped in 153.40s (0:02:33) ==================
```

*(Note: 4 skipped tests are the opt-in live external tool/network checks (`RUN_REAL_ODA`, `RUN_REAL_OCR`, `RUN_REAL_RESEARCH`) which were not modified in this fix round.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)

```text
✓ src/App.test.tsx (21 tests) 62ms
Test Files  1 passed (1) | Tests  21 passed (21) | Duration  1.04s
tsc --noEmit && vite build -> 37 modules transformed -> built in 555ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across `backend`, `frontend/src`, `docs`, `scripts`: `BOM_FILES: []`.
- Local-path & secret-pattern check across tracked/updated dirs: clean (no local user paths or live keys).
- `gitleaks detect --source . --no-banner -v`: `no leaks found` (exit `0`).

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
- [x] `ADR-021` added & updated in `docs/DECISIONS.md`
- [x] Review Fix (1): Zero-artefact / missing-evidence QA runs return `status="no_evidence"`, mark tasks `qa_failed`, and `/verify` returns `422`
- [x] Review Fix (2): `update_issue` requires `>= 10`-character `closure_note` (`422` otherwise) without promoting review to `passed`; `/verify` requires a fresh QA re-run after last closure (`422` otherwise); `QaIssuesView` prompts for closure note and offers **Re-run QA** button
- [x] Review Fix (3): `_check_arithmetic` raises high-severity `integrity` finding on unreadable/corrupt/missing exported XLSX workbooks (tested with corrupt XLSX)
- [x] `docs/reports/step-12.md` marked **`PARTIAL`** until owner live UI walkthrough
- [x] Pushed `step-12-qa-issue-register` only (`main` untouched, no merge)
