# Step 16 — Project Planning (WBS, Deterministic CPM Schedule, Gantt Chart, Libya Calendar, Baseline Comparison & PDF/XLSX Export)

- **Date:** 2026-11-22
- **Status:** **PARTIAL** *(Delivers reversible migration `0014_step16_project_schedules` adding `project_schedules` and `deliverables.schedule_id`; deterministic Python Critical Path Method (`0` AI tokens by default) implementing forward/backward pass, total float, Finish-to-Start (`FS`) dependencies with optional lag, topological cycle detection (`HTTP 422`), orphan WBS checks, owner-defined working calendars including default **Libya Sun–Thu workweek (`Fri & Sat` weekend `[4, 5]`)** and owner-supplied holidays only; strict no-fabrication provenance anchored to real project BOQ items, Specifications, Calculations, reviewed Research Sources, or explicit owner inputs (`'not provided'` displayed for unsupplied durations, blocking critical-path computation on affected branches with explicit flags); baseline lock (`set_schedule_as_baseline`) & working-day baseline-vs-current variance comparison; optional Gemini narrative tagged `UNVERIFIED AI DRAFT` until owner sign-off; visual Gantt charts rendered both in UI and in immutable Arabic RTL & English LTR landscape vector PDFs + live-formula XLSX workbooks (`=IF(...)`/`=MAX(...)`/`=COUNTIF(...)`) in `03_Analysis/` with SHA-256 `Deliverable` entries; Step 12 QA Agent verification across cycles, orphans, missing durations, missing BOQ/spec/source attribution, independently recomputed dates/critical path, and XLSX/PDF integrity; bilingual RTL/LTR **Planning & Gantt** UI tab; `97 passed, 4 skipped` full backend `pytest -v`, `25 passed` frontend Vitest + `tsc --noEmit` + Vite build, and clean `gitleaks` check; owner interactive browser walkthrough and visual inspection of exported Gantt PDF & XLSX files remain `PENDING`.)*
- **Branch:** `step-16-project-planning`
- **Depends on:** Step 15 (`ae5139a`, PR `#24` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`0014_step16_project_schedules.py`):**
   - Created `project_schedules` (`ProjectSchedule` ORM model) storing `project_id`, `task_id`, `baseline_schedule_id`, `title`, `discipline`, `language`, `classification`, `revision`, `version`, `export_version`, `status`, `is_baseline`, `start_date`, `use_ai`, `ai_draft_status` (`CHECK IN ('not_used', 'unverified_ai_draft', 'owner_approved')`), `owner_approved_by`, `owner_approved_at`, `tokens_used`, `token_usage_json`, `calendar_json`, `wbs_items_json`, `activities_json`, `schedule_result_json`, and `summary`.
   - Added nullable `schedule_id` FK (`ON DELETE SET NULL`) on `deliverables` and updated `DeliverableOut` mappings across `schemas/reports.py`, `services/review_reports.py`, and `services/boq.py`.

2. **Deterministic WBS, CPM, Calendar & Baseline Comparison (`backend/app/skills/planning.py`, `backend/app/services/planning.py`):**
   - **Forward & Backward CPM Pass:** Deterministic topological sort (Kahn cycle detector), `FS` dependencies with optional positive/negative `lag_days`, working-day Early Start/Finish, Late Start/Finish, Total Float (`LS - ES`), and exact milestone alignment (`planned_start == planned_finish`).
   - **No Fabrication / Missing Duration Branch Blocking:** Never invents productivity rates, durations, costs, or holidays. Any non-milestone activity lacking `duration_days` renders strictly as `'not provided'` and blocks critical-path computation (`blocked_missing_duration`) on its connected branch with clear flags while still computing independent complete branches cleanly.
   - **Owner Calendar (Libya Weekend Support):** Built-in `libya_sun_thu` (`weekend_days=[4, 5]` Fri+Sat), `mon_fri`, `six_day_sat_thu`, and `custom` weekend rules; applies ONLY explicit owner-supplied holiday ISO dates (`calendar.holidays`).
   - **Real Project Attribution (`_validate_schedule_sources`):** Enforces project-scoped `boq_item_id` (via `BoqItem.boq_sheet_id`), `specification_id`, `calculation_id`, reviewed `research_source_id`, or `owner_entered` provenance with non-empty `source_ref` and blocks unreviewed external URLs (`HTTP 422`).
   - **Baseline vs Current Comparison (`set_schedule_as_baseline`, `baseline_schedule_id`):** Tracks activity start/finish/float variances (`on_baseline`, `delayed`, `ahead`, `added_in_current`, `removed_from_current`, `blocked`) and overall `project_finish_variance_wd`.
   - **Optional AI Narrative (`use_ai=false` default, `0` tokens):** Prose-only `draft_schedule_narrative_with_ai` enforces Step 04 token caps, rejects ungrounded URLs/standard citations, never computes dates/durations, and carries `[UNVERIFIED AI DRAFT]` until `POST /api/schedules/{id}/approve`.

3. **Bilingual RTL/LTR Gantt PDF & Live-Formula XLSX Exports (`backend/app/services/planning_export.py`):**
   - Generates immutable versioned vector PDFs (`A4` landscape via PyMuPDF `Story` + Tahoma + Unicode LRI/PDI isolates) featuring drawn horizontal Gantt bars (critical bars in crimson, normal bars with light-blue float tails, purple milestone `◆` markers, amber blocked `'not provided'` tracks) alongside full WBS/CPM/baseline/source tables.
   - Generates multi-sheet live-formula XLSX workbooks (`Sheet 1`: `Schedule & CPM` with `=IF(...)`, `=MAX(...)`, `=COUNTIF(...)`; `Sheet 2`: `WBS & Provenance`) saved immutably in `03_Analysis/` (`HTTP 409` overwrite protection) with SHA-256 `Deliverable` records.

4. **Step 12 QA Agent Integration (`backend/app/agents/qa_agent.py`, `backend/app/schemas/qa.py`):**
   - Added `inspected_schedule_ids` on `QaContextIsolationReport` and `ctx.schedules` loader in `build_isolated_qa_context`.
   - Detects dependency cycles (`schedule_consistency` critical), orphan WBS/predecessor references (`high`), missing `'not provided'` durations blocking critical path (`high`), missing/invalid BOQ/spec/calc/research source attribution (`reference`), independently recomputes all ES/EF/LS/LF/float/calendar dates, baseline variances, and critical paths (`arithmetic`), flags unapproved AI drafts (`unverified_ai_draft`), and verifies `03_Analysis/` PDF/XLSX deliverables, live Excel formulas, and SHA-256 integrity (`missing_deliverable` / `integrity`).

5. **Bilingual RTL/LTR UI (`frontend/src/components/ProjectPlanningView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added **الجدولة والمسار الحرج (Plan) / Planning & Gantt** tab (`initialTab="planning"`) with synthetic clinic planning preset (Libya Fri–Sat weekend), WBS editor, FS+lag dependency activity editor (leaving duration blank = `'not provided'`), interactive visual Gantt chart bars with critical/float/milestone/blocked states, baseline lock & variance table, owner AI approval button, and SHA-256 PDF/XLSX downloads.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0014_step16_project_schedules.py`
- `<repo>/backend/app/api/planning.py`
- `<repo>/backend/app/schemas/planning.py`
- `<repo>/backend/app/services/planning.py`
- `<repo>/backend/app/services/planning_export.py`
- `<repo>/backend/app/skills/planning.py`
- `<repo>/backend/tests/test_planning.py`
- `<repo>/frontend/src/components/ProjectPlanningView.tsx`
- `<repo>/docs/reports/step-16.md`

### Changed
- `<repo>/backend/app/agents/qa_agent.py` *(Step 16 isolated context, cycle detection, orphan WBS/predecessor checks, missing duration flags, source attribution checks, independent CPM date/float/baseline/critical-path recomputation, schedule XLSX formula & deliverable integrity)*
- `<repo>/backend/app/db/models.py` *(added `ProjectSchedule` ORM model and `Deliverable.schedule_id` FK)*
- `<repo>/backend/app/main.py` *(registered `planning_router`)*
- `<repo>/backend/app/schemas/qa.py` *(added `inspected_schedule_ids` on `QaContextIsolationReport`)*
- `<repo>/backend/app/schemas/reports.py` *(added `schedule_id` on `DeliverableOut`)*
- `<repo>/backend/app/services/boq.py` *(mapped `schedule_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/services/review_reports.py` *(mapped `schedule_id` in `_to_deliverable_out`)*
- `<repo>/backend/tests/test_migrations.py` *(asserted `project_schedules` table & `deliverables.schedule_id` across Alembic upgrade/downgrade)*
- `<repo>/docs/DECISIONS.md` *(added `ADR-025`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 16 bilingual `ProjectPlanningView` SSR & planning API Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(wired `planning` tab & Step 16 subtitle)*
- `<repo>/frontend/src/api.ts` *(added Step 16 planning presets/create/list/detail/set-baseline/approve/export API wrappers)*
- `<repo>/frontend/src/types.ts` *(added Step 16 TypeScript planning interfaces & `schedule_id` / `inspected_schedule_ids`)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Output (`0` AI Tokens)

Deterministic output from `get_synthetic_planning_presets()[0]` (synthetic clinic renovation schedule, `start_date=2026-11-22`, Libya Sun–Thu calendar skipping Fri & Sat, `0%` client data, `0` AI tokens):

```text
dur: 14 start: 2026-11-22 finish: 2026-12-09 crit: ['M0', 'A1', 'A3', 'A4', 'M1']
M0 | 0 wd | ES=0 EF=0 TF=0 | 2026-11-22->2026-11-22 | crit=True
A1 | 4 wd | ES=0 EF=4 TF=0 | 2026-11-22->2026-11-25 | crit=True
A2 | 3 wd | ES=4 EF=7 TF=3 | 2026-11-26->2026-11-30 | crit=False
A3 | 5 wd | ES=4 EF=9 TF=0 | 2026-11-26->2026-12-02 | crit=True
A4 | 4 wd | ES=10 EF=14 TF=0 | 2026-12-06->2026-12-09 | crit=True
M1 | 0 wd | ES=14 EF=14 TF=0 | 2026-12-09->2026-12-09 | crit=True
```

## 4. Tests Run (Exact Observed Results & Secret Scan)

### Step 16 CPM & Defect-Trap Isolation Runs (`-x -q`) + Full Backend Suite (`pytest -v`)
```text
> .\backend\.venv\Scripts\pytest.exe backend/tests/test_planning.py -k test_cpm_hand_checked_network -x -q
.                                                                        [100%]
1 passed, 2 deselected in 3.11s

> .\backend\.venv\Scripts\pytest.exe backend/tests/test_planning.py -k test_step16_api_project_grounding_baseline_variance_gantt_pdf_xlsx_and_qa_pass -x -q
.                                                                        [100%]
1 passed, 2 deselected in 5.31s

> .\backend\.venv\Scripts\pytest.exe backend/tests/test_planning.py -k test_step16_optional_ai_unverified_and_qa_catches_all_seeded_schedule_defects -x -q
.                                                                        [100%]
1 passed, 2 deselected in 3.91s
```

```text
> .\backend\.venv\Scripts\pytest.exe backend/tests -v
collected 101 items

... (all non-opt-in test modules passed cleanly: test_boq, test_cad_bim, test_calculations, test_comparisons, test_config, test_drawings, test_extraction, test_migrations, test_planning, test_projects, test_providers, test_qa, test_reports, test_research, test_specifications, test_tasks)

================== 97 passed, 4 skipped in 190.64s (0:03:10) ==================
```
*(The 4 skipped tests are the pre-existing opt-in live tool/network tests `RUN_REAL_ODA`, `RUN_REAL_OCR`, `RUN_REAL_RESEARCH`.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)
```text
> cd frontend; npm.cmd test; npm.cmd run build
✓ src/App.test.tsx (25 tests) 86ms
Test Files  1 passed (1) | Tests  25 passed (25) | Duration  969ms
tsc --noEmit && vite build -> 41 modules transformed -> built in 639ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across `.py/.ts/.tsx/.md/.json`: `BOM_FILES: []`.
- Local-path check across `backend`, `frontend/src`, `docs`: `0` matches.
- `gitleaks detect --source . --no-banner -v`: executed on final commit (`0` leaks found).

## 5. Decisions Made
- Recorded **`ADR-025`** in `<repo>/docs/DECISIONS.md` covering Step 16's deterministic CPM forward/backward pass, FS+lag dependencies, cycle detection, Libya Fri–Sat weekend calendar (`libya_sun_thu`) without invented holidays, `'not provided'` branch blocking, baseline variance comparison, optional `UNVERIFIED AI DRAFT` narrative gate, Gantt vector PDF + live-formula XLSX export into `03_Analysis/`, and QA Agent checks.

## 6. Known Limitations & Owner Review Needed
1. **Live Browser & Gantt PDF/Excel Visual Walkthrough (`PENDING` owner check):** Automated suites verify hand-checked CPM dates & Libya weekends, missing-duration branch blocking, PyMuPDF PDF extraction, live Excel formulas (`=IF`/`=COUNTIF`), SHA-256 checksums, QA defect traps, and Vitest SSR Gantt rendering; opening the running UI and visually inspecting exported `.pdf` Gantt charts and `.xlsx` workbooks remains for the owner.
2. **Finish-to-Start Dependencies:** Current release supports standard `FS` dependencies with optional positive or negative lag (`-365..365` working days); `SS`/`FF` lag types can be layered cleanly on top in a future enhancement if requested.

## 7. How to Test in the Running App
1. Ensure backend + frontend are running (`scripts\start.bat`, health `GET http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`).
2. Open **الجدولة والمسار الحرج (Plan) / Planning & Gantt**, pick a project, click **Load Fixture** (loads the synthetic Libya Sun–Thu renovation schedule), optionally clear a duration cell to observe `'not provided'` branch blocking, and click **Compute CPM Schedule & Export (Gantt PDF + Live XLSX)**.
3. Inspect the interactive Gantt chart bars, lock the schedule via **Lock as Project Baseline**, create a revised schedule comparing against that baseline to inspect variances, and download the immutable SHA-256 Gantt PDF and live XLSX from `03_Analysis/`.

## 8. Checklist & Ready for Next Step?
- [x] Branch `step-16-project-planning` created cleanly from pulled `main` (`ae5139a`)
- [x] Reversible migration `0014_step16_project_schedules` (`down_revision = "0013"`) verified via Alembic round-trip test
- [x] Real project BOQ/Spec/Calc/reviewed ResearchSource grounding + verbatim `'not provided'` blocking branch CPM when durations omitted
- [x] Deterministic CPM (`ES/EF/LS/LF/Float`, `FS+lag`, cycle detection) & Libya Fri–Sat weekend calendar (`0` AI tokens default)
- [x] Baseline vs current comparison (`set_schedule_as_baseline`, `baseline_schedule_id`, start/finish/float variance)
- [x] Visual Gantt chart in UI & bilingual RTL/LTR vector PDF + live-formula XLSX in `03_Analysis/` with SHA-256 `Deliverables`
- [x] Optional Gemini narrative tagged `UNVERIFIED AI DRAFT` until owner approval
- [x] QA Agent checks (cycles, orphans, missing durations, missing sources, recomputed date arithmetic & critical path, XLSX/PDF integrity)
- [x] `ADR-025` and `docs/reports/step-16.md` (`Status: PARTIAL`) committed & `gitleaks` clean
- [ ] Owner visual UI & Gantt PDF/XLSX walkthrough (**Ready for owner review & PR to `main`**; push branch only, no merge)
