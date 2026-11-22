# Step 18 — HVAC, Fire Protection & Healthcare Skills (Input Preparation, Output Checks, Verified-Only Codes & QA Integration)

- **Date:** 2026-11-22
- **Status:** **PARTIAL** *(Delivers reversible migration `0016_step18_specialist_assessments` adding `specialist_assessments` (`SpecialistAssessment` ORM model) and `deliverables.assessment_id` FK; pure deterministic HVAC, Fire & Healthcare preflight calculation/checking engine (`0` AI tokens by default, strictly **prepare inputs and check outputs ONLY**, never replacing licensed engineers or validated commercial software like Carrier HAP, Trane TRACE 3D Plus, EnergyPlus, Elite Fire, SprinkCALC, or CONTAM); explicit preliminary warnings on every preset & formula assumption; verified-only WHO / FGI / NFPA / ASHRAE citation enforcement linked strictly to owner `standards_library` or reviewed `ResearchSource` log entries (emitting exact fallback `'no verified standard on file - verify against the locally adopted code'` when absent, zero invented clause numbers, editions, or limits); `'not provided'` display & branch blocking whenever required inputs/targets are omitted; optional Gemini prose summary tagged `UNVERIFIED AI DRAFT` until explicit owner/engineer approval (`POST /api/specialist-assessments/{id}/approve`); immutable Arabic RTL & English LTR DOCX, vector PDF & live-formula XLSX (`=COUNTIF(...)`) deliverables in `04_Engineering_Calculations/` with SHA-256 checksums; Step 12 QA Agent integration catching tampered/wrong results, uncited WHO/FGI/ASHRAE/NFPA codes, stale Standards Library bindings, blocked `'not provided'` inputs, unapproved AI drafts & missing deliverables; bilingual RTL/LTR **HVAC / Fire / Healthcare** UI tab; `103 passed, 4 skipped` full backend `pytest -v`, `27 passed` frontend Vitest + `tsc --noEmit` + Vite build, and clean `gitleaks` check; owner live browser walkthrough and visual inspection of exported DOCX/PDF/XLSX files remain `PENDING`.)*
- **Branch:** `step-18-hvac-fire-healthcare`
- **Depends on:** Step 17 (`8c1b7f6`, PR `#26` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`0016_step18_specialist_assessments.py`):**
   - Created `specialist_assessments` (`SpecialistAssessment` ORM model) storing `project_id`, `task_id`, `domain` (`CHECK IN ('hvac', 'fire', 'healthcare')`), `workflow_mode` (`CHECK IN ('input_preparation', 'output_check', 'full_preflight')`), `title`, `language`, `classification`, `revision`, `version`, `export_version`, `status`, `checks_passed`, `blocked_missing_count`, `failed_checks_count`, `standards_status`, `use_ai`, `ai_draft_status` (`CHECK IN ('not_used', 'unverified_ai_draft', 'owner_approved')`), `owner_approved_by`, `owner_approved_at`, `tokens_used`, `token_usage_json`, `inputs_json`, `results_json`, `references_json`, `preliminary_assumptions_json`, `software_recommendation`, and `summary`.
   - Added nullable `assessment_id` FK (`ON DELETE SET NULL`) on `deliverables` and updated `DeliverableOut` mappings across `schemas/reports.py`, `services/review_reports.py`, and `services/boq.py`.
   - Verified reversible Alembic `upgrade` / `downgrade` round-trip (`3 passed` in `test_migrations.py`).

2. **Deterministic Prepare & Check Skills (`backend/app/skills/specialist.py`, `backend/app/services/specialist.py`):**
   - **Prepare Inputs & Check Outputs ONLY (Validated Commercial Software Recommended):**
     - **HVAC:** Computes zone volume ($A \cdot H$), owner-rate outdoor air preparation ($N_{\text{occ}} R_p + A R_a$ without assuming ASHRAE defaults), and independently checks software-reported sensible load vs supply airflow ($Q_{\text{sens}} = 1.21 \cdot \dot{V}_{\text{L/s}} \cdot \Delta T$, preliminary sea-level factor), explicit discrepancy percentage, and specific $W/m^2$ / ACH ratios; recommends **Carrier HAP / Trane TRACE 3D Plus / EnergyPlus**.
     - **Fire Protection:** Computes remote-area sprinkler flow ($A_{\text{design}} \cdot d_{\text{mm/min}}$), combined demand ($Q_{\text{spr}} + Q_{\text{hose}}$), and required storage volume ($Q_{\text{tot}} \cdot t_{\text{min}} / 1000$) from owner-adopted parameters, and checks software-reported pump flow capacity, available-vs-required pressure margins (`bar`), and usable tank volume; recommends **Elite Fire / SprinkCALC / AutoSPRINK**.
     - **Healthcare:** Computes room volumes, supply/exhaust/effective/outdoor ACH ($\dot{V}_{\text{L/s}} \cdot 3.6 / V_{\text{m}^3}$), volumetric room balance offset ($+$ positive / $-$ negative / neutral), differential `Pa` checks, and medical-gas diversity demands strictly against **owner-supplied** clinical targets; recommends **Carrier HAP / CONTAM / Pipe-Flo**.
   - **No Fabrication / Missing Inputs Block Results (`'not provided'`):** Any missing parameter or owner threshold renders verbatim as `'not provided'`, emits an explicit `blocked_missing_inputs` gate, and sets `checks_passed = False`.
   - **Verified-Only Standards Citations:** Binds `standard_library_id` (confirmed `"current"` `StandardDocument` with known edition) or `research_source_id` (reviewed accessible/owner-provided `ResearchSource`). Without verified linkage, emits `'no verified standard on file - verify against the locally adopted code'` and never fabricates WHO/FGI/NFPA/ASHRAE clauses or limits.
   - **Optional AI Prose Narrative (`use_ai=false` default, `0` tokens):** Calls `draft_specialist_narrative_with_ai` only when requested, tagging output `UNVERIFIED AI DRAFT` without altering numeric results until `POST /api/specialist-assessments/{id}/approve`.

3. **Bilingual RTL/LTR DOCX, PDF & Live-Formula XLSX Exports (`backend/app/services/specialist_export.py`):**
   - Exports immutable versioned deliverables (`DOCX`, vector `PDF` via PyMuPDF `Story` + Tahoma/LRI isolates, and multi-sheet `XLSX` with `=COUNTIF(...)` summary checks & `Inputs & Provenance` sheet) into `04_Engineering_Calculations/` with SHA-256 `Deliverable` entries.

4. **Step 12 QA Agent Integration (`backend/app/agents/qa_agent.py`, `backend/app/schemas/qa.py`):**
   - Added `inspected_assessment_ids` to `QaContextIsolationReport` and isolated loader `ctx.specialist_assessments`.
   - Independently recomputes every HVAC/Fire/Healthcare assessment via `evaluate_specialist_assessment` (`arithmetic`: critical mismatch on tampered verdicts or failed checks), catches uncited `WHO`/`FGI`/`NFPA`/`ASHRAE`/standard codes absent from `standards_library` and reviewed `ResearchSource` logs (`reference`), flags `'not provided'` blocked inputs and unapproved `UNVERIFIED AI DRAFT` items (`schedule_consistency`), and checks `04_Engineering_Calculations/` DOCX/PDF/XLSX completeness & SHA-256 integrity (`missing_deliverable` / `integrity`). Also fixed `STANDARD_CODE_DETECT_RE` in `skills/standards.py` (`(?<![A-Za-z0-9-])`) so hyphenated room IDs (`HC-ISO-01`) never false-match `ISO-01`.

5. **Bilingual RTL/LTR UI (`frontend/src/components/SpecialistEngineeringView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added **تكييف / حريق / صحة (Preflight) / HVAC / Fire / Healthcare** tab (`initialTab="specialist"`) with mandatory preliminary & commercial-software notice banners, synthetic presets, domain/mode selectors, Standards Library + ResearchSource pickers, JSON inputs editor, check matrix + prepared-inputs table, AI approval control, and SHA-256 DOCX/PDF/XLSX downloads.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0016_step18_specialist_assessments.py`
- `<repo>/backend/app/api/specialist.py`
- `<repo>/backend/app/schemas/specialist.py`
- `<repo>/backend/app/services/specialist.py`
- `<repo>/backend/app/services/specialist_export.py`
- `<repo>/backend/app/skills/specialist.py`
- `<repo>/backend/tests/test_specialist.py`
- `<repo>/docs/reports/step-18.md`
- `<repo>/frontend/src/components/SpecialistEngineeringView.tsx`

### Changed
- `<repo>/backend/app/agents/qa_agent.py` *(added Step 18 isolated context, arithmetic recomputation, WHO/FGI/NFPA/ASHRAE & stale-library reference traps, `'not provided'` blocked input & unapproved AI checks, and `04_Engineering_Calculations/` deliverable checks)*
- `<repo>/backend/app/db/models.py` *(added `SpecialistAssessment` ORM model, `Project.specialist_assessments`, and `Deliverable.assessment_id`)*
- `<repo>/backend/app/main.py` *(registered `specialist_router`)*
- `<repo>/backend/app/schemas/qa.py` *(added `inspected_assessment_ids` to `QaContextIsolationReport`)*
- `<repo>/backend/app/schemas/reports.py` *(added `assessment_id` to `DeliverableOut`)*
- `<repo>/backend/app/services/boq.py` *(mapped `assessment_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/services/review_reports.py` *(mapped `assessment_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/skills/standards.py` *(refined `STANDARD_CODE_DETECT_RE` lookbehind `(?<![A-Za-z0-9-])` so room IDs like `HC-ISO-01` do not false-trigger `ISO-01`)*
- `<repo>/backend/tests/test_migrations.py` *(asserted `specialist_assessments` & `deliverables.assessment_id` across Alembic upgrade/downgrade)*
- `<repo>/docs/DECISIONS.md` *(added `ADR-027`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 18 bilingual `SpecialistEngineeringView` SSR & API wrapper Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(wired `specialist` tab & Step 18 subtitle)*
- `<repo>/frontend/src/api.ts` *(added Step 18 presets/create/list/detail/update/approve/export API wrappers)*
- `<repo>/frontend/src/types.ts` *(added Step 18 TypeScript interfaces & `assessment_id` / `inspected_assessment_ids`)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Output (`0` AI Tokens)

Deterministic output from `get_synthetic_specialist_presets()` + `evaluate_specialist_assessment()` (synthetic inputs only, `0%` client data, `0` AI tokens):

```text
PRESETS: [
  ('hvac', {'zones_count': 2, 'total_floor_area_m2': 105.0, 'total_volume_m3': 327.0, 'total_expected_supply_ls': 800.0, 'total_reported_supply_ls': 800.0, 'total_expected_oa_ls': 147.5, 'passed_checks_count': 4, 'failed_checks_count': 0, 'blocked_missing_count': 0}),
  ('fire', {'zones_count': 1, 'governing_required_flow_lpm': 1200.0, 'governing_required_tank_m3': 72.0, 'passed_checks_count': 3, 'failed_checks_count': 0, 'blocked_missing_count': 0}),
  ('healthcare', {'spaces_count': 2, 'medical_gas_items': [{'gas_name': 'Synthetic O2', 'outlet_count': 4.0, 'flow_per_outlet_lpm': 20.0, 'diversity_factor': 0.75, 'diversified_flow_lpm': 60.0}], 'total_diversified_medical_gas_lpm': 60.0, 'passed_checks_count': 8, 'failed_checks_count': 0, 'blocked_missing_count': 0})
]
BLOCKED: blocked_missing_inputs False 3 not provided
```

## 4. Tests Run (Exact Observed Results & Secret Scan)

### Targeted Step 18 Checks (`-x -q`) & Full Backend Suite (`pytest -v`)
```text
> .\backend\.venv\Scripts\pytest.exe backend/tests/test_migrations.py -x -q
...                                                                      [100%]
3 passed in 8.57s

> .\backend\.venv\Scripts\pytest.exe backend/tests/test_specialist.py -k test_step18_hand_checked_hvac_fire_healthcare_and_missing_not_provided_blocks -x -q
.                                                                        [100%]
1 passed, 2 deselected in 3.35s

> .\backend\.venv\Scripts\pytest.exe backend/tests/test_specialist.py -k test_step18_api_standards_gating_zero_tokens_exports_en_ar_and_qa_pass -x -q
.                                                                        [100%]
1 passed, 2 deselected in 4.37s

> .\backend\.venv\Scripts\pytest.exe backend/tests/test_specialist.py -k test_step18_optional_ai_and_qa_catches_wrong_result_uncited_who_fgi_and_blocked_inputs -x -q
.                                                                        [100%]
1 passed, 2 deselected in 3.94s

> .\backend\.venv\Scripts\pytest.exe backend/tests -v
================= 103 passed, 4 skipped in 218.20s (0:03:38) ==================
```
*(The 4 skipped tests are the pre-existing opt-in live tool/network tests `RUN_REAL_ODA`, `RUN_REAL_OCR`, `RUN_REAL_RESEARCH`; all 3 Step 18 test suites in `test_specialist.py` — hand-checked HVAC/Fire/Healthcare formulas & `'not provided'` blocking, verified-only code citations & AR/EN DOCX/PDF/XLSX exports, and QA defect traps catching wrong math + uncited WHO/FGI/ASHRAE + blocked inputs — passed cleanly.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)
```text
> cd frontend; npm.cmd test; npm.cmd run build
✓ src/App.test.tsx (27 tests) 98ms
Test Files  1 passed (1) | Tests  27 passed (27) | Duration  1.07s
tsc --noEmit && vite build -> 43 modules transformed -> built in 677ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across `.py/.ts/.tsx/.md/.json`: `BOM_FILES: []`.
- Local-path check across `backend`, `frontend/src`, `docs`: `0` matches.
- `gitleaks detect --source . --no-banner -v`: clean on branch commit (`0` leaks found).

## 5. Decisions Made
- Recorded **`ADR-027`** in `<repo>/docs/DECISIONS.md` covering `specialist_assessments` (`0016`), input-preparation & output-checking scope with mandatory commercial software & licensed-engineer disclaimers, verified-only WHO/FGI/NFPA/ASHRAE citation enforcement, `'not provided'` missing-input gates, bilingual DOCX/PDF/XLSX exports into `04_Engineering_Calculations/`, and Step 12 QA Agent checks.

## 6. Known Limitations & Owner Review Needed
1. **Live Browser & Deliverable Visual Walkthrough (`PENDING` owner check):** Automated tests verify hand-checked HVAC/Fire/Healthcare math, `'not provided'` blocking, verified-only code gating, DOCX/PDF/live XLSX generation, SHA-256 checksums, QA traps, and Vitest SSR rendering; opening the running UI and visually inspecting the exported DOCX/PDF/XLSX files remains for the owner.
2. **Preliminary Scope Only (Commercial Software Still Mandatory):** Step 18 prepares zone/space inputs and runs algebraic energy/flow/ACH/balance verification only; full hourly thermal loads, multi-loop Hazen-Williams hydraulics, and clinical containment commissioning remain strictly within validated commercial tools and licensed engineering sign-off.

## 7. How to Test in the Running App
1. Ensure backend + frontend are running (`scripts\start.bat`, health `GET http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`).
2. Open **تكييف / حريق / صحة (Preflight) / HVAC / Fire / Healthcare**, choose a project, pick a synthetic preset (HVAC, Fire, or Healthcare), leave Standards Library unset first to observe `'no verified standard on file - verify against the locally adopted code'`, then remove a required parameter (e.g., `required_total_ach`) to verify `'not provided'` blocking.
3. Optionally register `WHO-SYN-2024` in Step 17 Standards Library, link it on Healthcare, run checks at `0` AI tokens, export **DOCX + PDF + Live XLSX**, and run Step 12 **QA Review**.

## 8. Checklist & Ready for Next Step?
- [x] Branch `step-18-hvac-fire-healthcare` created cleanly from pulled `main` (`8c1b7f6`)
- [x] Reversible migration `0016_step18_specialist_assessments` (`down_revision = "0015"`) verified via Alembic round-trip test
- [x] Prepare-inputs & check-outputs ONLY across HVAC, Fire & Healthcare (`0` AI tokens default) + validated commercial software & preliminary engineer labels
- [x] WHO/FGI/NFPA/ASHRAE cited ONLY from verified Standards Library or reviewed ResearchSource log; otherwise `'no verified standard on file - verify against the locally adopted code'`
- [x] Missing inputs rendered as `'not provided'` & block affected result cleanly
- [x] Bilingual RTL/LTR UI tab + DOCX/PDF/live-formula XLSX in `04_Engineering_Calculations/` with SHA-256
- [x] QA Agent defect traps verified (`arithmetic` mismatch, uncited WHO/FGI/ASHRAE, `'not provided'` blocked inputs, unapproved AI draft)
- [x] `ADR-027` and `docs/reports/step-18.md` (`Status: PARTIAL`) written, tested (`103 passed, 4 skipped` backend + `27 passed` frontend), and `gitleaks` clean
- [ ] Owner visual UI & DOCX/PDF/XLSX walkthrough (**Ready for owner review & PR to `main`**; push branch only, no merge)
