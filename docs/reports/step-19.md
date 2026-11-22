# Step 19 — Structural Engineering Support (Assessment Support & Input/Output Checking ONLY)

- **Date:** 2026-11-22
- **Status:** **PARTIAL** *(Delivers reversible migration `0017_step19_structural_assessments` adding `structural_assessments` (`StructuralAssessment` ORM model) and `deliverables.structural_id` FK; pure deterministic structural assessment support & I/O checking library (`evaluate_structural_assessment`, `0` AI tokens by default — **ASSESSMENT SUPPORT & I/O CHECKING ONLY**, NEVER designs concrete/steel members, reinforcement, foundations, or connections and NEVER certifies safety); every preset and report labelled `PRELIMINARY - for review by a licensed structural engineer` with mandatory commercial structural software recommendation (`ETABS`, `SAP2000`, `SAFE`, `RAM Structural System`, `Robot Structural Analysis`); zero hardcoded ACI/Eurocode/AISC/Libyan code factors, load values, material strengths, or deflection limits; verified-only code citations linked strictly to confirmed `"current"` Step 17 `standards_library` or reviewed `ResearchSource` log entries, otherwise emitting `'no verified standard on file - verify against the locally adopted code'`; missing inputs shown as `'not provided'` and blocking affected checks cleanly (`status = "blocked_missing_inputs"`, `checks_passed = False`); optional Gemini prose summary tagged `UNVERIFIED AI DRAFT` until explicit licensed engineer / owner approval (`POST /api/structural-assessments/{id}/approve`); immutable Arabic RTL & English LTR `DOCX`, vector `PDF`, and live-formula `XLSX` (`=COUNTIF(...)`) deliverables in `04_Engineering_Calculations/` with SHA-256 checksums; Step 12 QA Agent integration catching tampered verdicts, uncited ACI/Eurocode/AISC codes, stale library bindings, `'not provided'` blocked inputs, unapproved AI drafts, and missing deliverables; bilingual RTL/LTR **Structural Assessment Support** UI tab (`frontend/src/components/StructuralView.tsx`); `106 passed, 4 skipped` full backend `pytest -v`, `28 passed` frontend Vitest + `tsc --noEmit` + Vite build (`681ms`), and clean `gitleaks` directory scans; live UI browser walkthrough & visual inspection of exported DOCX/PDF/XLSX files remain `PENDING`.)*
- **Branch:** `step-19-structural`
- **Depends on:** Step 18 (`1dae45c`, PR `#27` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`0017_step19_structural_assessments.py`):**
   - Created `structural_assessments` (`StructuralAssessment` ORM model in `backend/app/db/models.py`) storing `project_id`, `task_id`, `assessment_type` (`'takedown_check' | 'load_combinations' | 'simple_statics_beam' | 'full_structural_check'`), `title`, `language`, `classification`, `revision`, `version`, `export_version`, `status`, `checks_passed`, `blocked_missing_count`, `failed_checks_count`, `standards_status`, `use_ai`, `ai_draft_status` (`'not_used' | 'unverified_ai_draft' | 'owner_approved'`), `owner_approved_by`, `owner_approved_at`, `tokens_used`, `token_usage_json`, `inputs_json`, `results_json`, `references_json`, `preliminary_assumptions_json`, `software_recommendation`, and `summary`.
   - Added nullable `structural_id` FK (`ON DELETE SET NULL`) on `deliverables` and updated `DeliverableOut` mappings across `schemas/reports.py`, `services/review_reports.py`, and `services/boq.py`.
   - Verified reversible Alembic `upgrade` / `downgrade` round-trip in `test_migrations.py`.

2. **Deterministic Structural Assessment Support & I/O Checking (`backend/app/skills/structural.py`, `backend/app/services/structural.py`):**
   - **Never Designs Members or Certifies Safety:** Every preset, schema constant (`PRELIMINARY_STRUCTURAL_LABEL_EN` / `PRELIMINARY_STRUCTURAL_LABEL_AR`), calculation row, and export carries `PRELIMINARY - for review by a licensed structural engineer` and `STRUCTURAL_SOFTWARE_RECOMMENDATION` pointing final code design to validated commercial tools (`ETABS`, `SAP2000`, `SAFE`, `RAM Structural System`, `Robot Structural Analysis`).
   - **Tributary Area Load Takedown (`takedown_check`):** Computes unfactored dead/live loads ($N_{\text{floors}} A_{\text{trib}} q + P_{\text{add}}$), owner-factored axial load ($P_u = \gamma_D P_D + \gamma_L P_L$), demand/capacity utilization ratio against owner-supplied axial capacity, and commercial software discrepancy check within `discrepancy_tolerance_pct` (default `2.0%`).
   - **Linear Load Combinations (`load_combinations`):** Evaluates owner-defined combinations ($E_u = \sum \gamma_i S_i$) across owner-supplied unfactored actions (`D`, `L`, `W`, etc.), identifies governing demand, and cross-checks software-reported governing value and owner capacity.
   - **Closed-Form Simple Span Beam Statics (`simple_statics_beam`):** Independently computes support reactions, max shear, max bending moment, and uncracked elastic service deflection for `simply_supported_udl`, `simply_supported_midspan_point`, and `cantilever_udl` spans against owner moment/shear capacities, owner deflection limit, and commercial software outputs.
   - **Missing Inputs & Verified-Only Code Gating:** Omitted parameters render as `'not provided'`, block affected outputs (`status = "blocked_missing_inputs"`, `checks_passed = False`), and reject any unverified code claims — ACI/Eurocode/AISC/Libyan/standard references bind strictly to confirmed `"current"` Step 17 `standards_library` or reviewed `ResearchSource` log entries, otherwise showing `'no verified standard on file - verify against the locally adopted code'`.
   - **Optional AI Narrative (`use_ai = False` default):** `draft_structural_narrative_with_ai` writes optional non-numeric commentary tagged `UNVERIFIED AI DRAFT` until `POST /api/structural-assessments/{id}/approve`.

3. **Bilingual RTL/LTR DOCX, PDF & Live-Formula XLSX Exports (`backend/app/services/structural.py`, `backend/app/services/specialist_export.py`):**
   - Reused `SpecialistRenderData` parameterized with custom `report_heading` and `preliminary_notice` to generate immutable Arabic RTL & English LTR `DOCX`, vector `PDF`, and live-formula `XLSX` (`=COUNTIF(...)` + `Inputs & Provenance`) deliverables in `04_Engineering_Calculations/` with SHA-256 `Deliverable` tracking.

4. **Step 12 QA Agent Integration (`backend/app/agents/qa_agent.py`, `backend/app/schemas/qa.py`):**
   - Added `inspected_structural_ids` to `QaContextIsolationReport` and isolated loader `ctx.structural_assessments`.
   - Independently recomputes every structural assessment via `evaluate_structural_assessment` (`arithmetic` — catches tampered verdicts and failed checks), traps uncited `ACI`/`AISC`/`ASCE`/`EC2`/`EC3`/`Eurocode`/`Libyan Code`/`SYN-*` references or stale library bindings (`reference`), flags `'not provided'` blocked inputs and unapproved `UNVERIFIED AI DRAFT` narratives (`schedule_consistency`), and checks `04_Engineering_Calculations/` deliverable completeness & SHA-256 hashes (`missing_deliverable` / `integrity`).

5. **Bilingual RTL/LTR UI (`frontend/src/components/StructuralView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added **الخطوة 19: دعم التقييم الإنشائي وفحص المدخلات والمخرجات / Step 19: Structural Assessment Support** tab (`initialTab="structural"`) with mandatory preliminary & commercial-software notices, synthetic presets (`full_1`, `beam_2`), Standards Library + ResearchSource selectors, JSON inputs editor (`'not provided'` testability), check matrix + prepared items tables, licensed-engineer AI approval button, and SHA-256 DOCX/PDF/XLSX downloads.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0017_step19_structural_assessments.py`
- `<repo>/backend/app/api/structural.py`
- `<repo>/backend/app/schemas/structural.py`
- `<repo>/backend/app/services/structural.py`
- `<repo>/backend/app/skills/structural.py`
- `<repo>/backend/tests/test_structural.py`
- `<repo>/docs/reports/step-19.md`
- `<repo>/frontend/src/components/StructuralView.tsx`

### Changed
- `<repo>/backend/app/agents/qa_agent.py` *(added `ctx.structural_assessments` loader, independent `evaluate_structural_assessment` arithmetic recomputation, unified `_audit_verified_code_assessment` trapping uncited ACI/Eurocode/AISC/Libyan codes & stale library links, `_audit_assessment_consistency` for blocked `'not provided'` / unapproved AI drafts, and `delivs_by_struct` integrity checks)*
- `<repo>/backend/app/db/models.py` *(added `StructuralAssessment`, `Project.structural_assessments`, and `Deliverable.structural_id`)*
- `<repo>/backend/app/main.py` *(registered `structural_router`)*
- `<repo>/backend/app/schemas/qa.py` *(added `inspected_structural_ids` to `QaContextIsolationReport`)*
- `<repo>/backend/app/schemas/reports.py` *(added `structural_id` to `DeliverableOut`)*
- `<repo>/backend/app/services/boq.py` *(mapped `structural_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/services/review_reports.py` *(mapped `structural_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/services/specialist_export.py` *(parameterized `SpecialistRenderData` with `report_heading` and `preliminary_notice` to eliminate Step 18/19 export duplication)*
- `<repo>/backend/tests/test_migrations.py` *(asserted `structural_assessments` across Alembic upgrade/downgrade round-trip)*
- `<repo>/docs/DECISIONS.md` *(appended `ADR-028`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 19 bilingual `StructuralView` SSR & API wrapper Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(wired `structural` tab & Step 19 subtitle)*
- `<repo>/frontend/src/api.ts` *(added Step 19 presets/create/list/detail/update/approve/export wrappers)*
- `<repo>/frontend/src/types.ts` *(added Step 19 TypeScript interfaces & `structural_id` / `inspected_structural_ids`)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Output (`0` AI Tokens)

Deterministic output from `get_synthetic_structural_presets()` + `evaluate_structural_assessment()` (synthetic inputs only, `0%` client data, `0` AI tokens):

```text
PRESETS: [
  ["full_1", "full_structural_check", "evaluated", true, 0, 0, {"takedown_count": 1, "load_combinations_count": 1, "beams_count": 1, "total_takedown_factored_kn": 1080.0, "passed_checks_count": 11, "failed_checks_count": 0, "blocked_missing_count": 0}],
  ["beam_2", "simple_statics_beam", "evaluated", true, 0, 0, {"takedown_count": 0, "load_combinations_count": 0, "beams_count": 1, "total_takedown_factored_kn": "not provided", "passed_checks_count": 7, "failed_checks_count": 0, "blocked_missing_count": 0}]
]
BLOCKED: blocked_missing_inputs False 2 not provided not provided
```

Hand-checked verification highlights in `test_structural.py`:
- **Column Takedown (`COL-A1`):** $A_{\text{trib}} = 25\text{ m}^2 \times 3\text{ floors} = 75\text{ m}^2$; $D = 600\text{ kN}$, $L = 225\text{ kN}$; owner factors $(1.2, 1.6) \Rightarrow P_u = 1080.0\text{ kN} / 1200.0\text{ kN} = 0.90$ ratio (`PASS (PRELIMINARY)`).
- **Load Combinations (`FR-1`):** $1.4(100) = 140.0$, $1.2(100)+1.6(50) = 200.0$ (governing), $1.2(100)+0.5(50)+1.0(30) = 175.0\text{ kN}$.
- **Simple Span Statics (`BM-01` UDL / Point / Cantilever):** Simply supported UDL $L=6\text{ m}$, $w_u=40\text{ kN/m}$, $w_s=28\text{ kN/m}$, $EI=40000\text{ kN}\cdot\text{m}^2 \Rightarrow R = V_{\max} = 120.0\text{ kN}$, $M_{\max} = 180.0\text{ kN}\cdot\text{m}$, $\delta_{\max} = 11.8125\text{ mm}$; midspan point $L=8\text{ m}$, $P_u=50\text{ kN} \Rightarrow R=25\text{ kN}, M=100\text{ kN}\cdot\text{m}, \delta=16.0\text{ mm}$; cantilever $L=4\text{ m}$, $w_u=15\text{ kN/m} \Rightarrow R=60\text{ kN}, M=120\text{ kN}\cdot\text{m}, \delta=10.0\text{ mm}$.

## 4. Tests Run (Exact Observed Results & Hygiene Checks)

### Full Backend Suite (`pytest -v`, after final code edit) & Pre-Finalization Targeted Step 19 API Runs
```text
> .\backend\.venv\Scripts\pytest.exe backend/tests -v
================= 106 passed, 4 skipped in 231.69s (0:03:51) ==================
```
*(All 3 `test_migrations.py` tests and all 3 `test_structural.py` tests — `test_step19_hand_checked_takedown_combinations_beam_statics_and_not_provided_blocks`, `test_step19_api_verified_only_codes_zero_tokens_exports_en_ar_and_qa_pass`, and `test_step19_optional_ai_and_qa_catches_tampered_verdict_uncited_aci_ec_and_blocked_inputs` — passed after the final code edit; the 4 skipped tests are the pre-existing opt-in live tool/network tests across CAD/drawings/OCR/research. Earlier single-test `-x -q` API runs prior to renaming preset keys to low-entropy slugs also passed in `4.57s` and `4.19s`.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)
```text
> cd frontend; npm.cmd test; npm.cmd run build
 ✓ src/App.test.tsx (28 tests) 100ms
 Test Files  1 passed (1) | Tests  28 passed (28) | Duration  1.10s
 tsc --noEmit && vite build -> 44 modules transformed -> built in 681ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check: `BOM_FILES: []` (verified again before commit).
- Local-path check across `backend`, `frontend/src`, `docs`: `LOCAL_PATH_LEAKS: []`.
- `gitleaks dir` across `backend/app`, `backend/tests`, `frontend/src`, `docs`: `no leaks found` (repo git-history `gitleaks detect --source . --no-banner -v` run cleanly on commit).

## 5. Decisions Made
- Recorded **`ADR-028`** in `<repo>/docs/DECISIONS.md` covering `structural_assessments` (`0017`), assessment-support & simple statics I/O checking ONLY (never member design or safety certification), mandatory `PRELIMINARY - for review by a licensed structural engineer` and commercial software disclaimers, verified-only code gating, `'not provided'` missing-input blocking, bilingual `DOCX`/`PDF`/live `XLSX` exports into `04_Engineering_Calculations/`, Step 12 QA Agent recomputation & defect traps, and the bilingual UI tab.

## 6. Known Limitations & Owner Review Needed
1. **Live Browser & Deliverable Visual Walkthrough (`PENDING` owner check):** Automated tests verify hand-checked takedown/combination/beam statics arithmetic, `'not provided'` blocking, verified-only ACI/Eurocode/AISC gating, DOCX/PDF/live XLSX generation, SHA-256 checksums, QA defect traps, and Vitest SSR rendering; opening the running UI (`http://127.0.0.1:5173`) and visually inspecting the exported DOCX/PDF/XLSX deliverables remains for the owner.
2. **Preliminary Scope Only (Commercial FEA & Licensed Structural Engineer Mandatory):** Step 19 performs linear load-factor summation and closed-form uncracked simple-span statics checks ONLY; reinforced concrete/steel section design, cracked deflections, P-Delta second-order effects, torsion, lateral seismic/wind modal analysis, and foundation design belong strictly to validated commercial structural software and a licensed structural engineer.

## 7. How to Test in the Running App
1. Start backend & frontend via `scripts\start.bat` (confirm `GET http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`).
2. Open **الخطوة 19: دعم التقييم الإنشائي / Step 19: Structural Assessment Support**, pick a project, load synthetic preset `full_1` or `beam_2` without a Standards Library entry to confirm `'no verified standard on file - verify against the locally adopted code'`, and run checks (`0` AI tokens).
3. Delete `dead_load_kpa` or `span_m` in the JSON editor to confirm `'not provided'` display and `blocked_missing_inputs` gate; optionally link a confirmed `"current"` Step 17 standard, export **DOCX + PDF + Live XLSX**, and run Step 12 **QA Review**.

## 8. Checklist & Ready for Next Step?
- [x] Branch `step-19-structural` created cleanly from pulled `main` (`1dae45c`)
- [x] Reversible migration `0017_step19_structural_assessments` (`down_revision = "0016"`) verified via Alembic round-trip test
- [x] Assessment support & I/O checking ONLY (takedown, owner load combinations, closed-form simple span statics, capacity & software discrepancy checks, `0` AI tokens default) + mandatory `PRELIMINARY - for review by a licensed structural engineer` & commercial FEA software recommendation
- [x] ACI/Eurocode/AISC/Libyan/standard citations strictly verified from Step 17 Standards Library or reviewed ResearchSource log; otherwise `'no verified standard on file - verify against the locally adopted code'`
- [x] Missing inputs rendered as `'not provided'` and block affected checks cleanly
- [x] Bilingual RTL/LTR UI tab + DOCX/PDF/live-formula XLSX in `04_Engineering_Calculations/` with SHA-256
- [x] QA Agent defect traps verified (`arithmetic` tampered verdict, uncited ACI/Eurocode/AISC reference, `'not provided'` blocked inputs, unapproved AI draft)
- [x] `ADR-028` and `docs/reports/step-19.md` (`Status: PARTIAL`) written, full suite green (`106 passed, 4 skipped` backend + `28 passed` frontend), and `gitleaks` clean on source dirs
- [ ] Owner visual UI & DOCX/PDF/XLSX walkthrough (**Ready for owner review & PR to `main`**; push branch only, no merge)
