# Step 13 — Deterministic Engineering Calculation Framework (Electrical & Plumbing Basics, `0` AI Tokens)

- **Date:** 2026-11-21
- **Status:** **PARTIAL** *(Delivers reversible migration `0011_step13_calculation_framework` extending `calculations` and linking `deliverables.calculation_id`; pure Python deterministic calculation skill library (`0` AI tokens, zero AI arithmetic) covering electrical load schedules, cable sizing, voltage drop, plumbing water demand/storage/pump duty, and Darcy-Weisbach pipe sizing on actual internal bore IDs (separating nominal DN, outer diameter OD, wall thickness, and internal diameter ID across `PPR_PN20` SDR 6, `uPVC` SDR 11, `copper`, and `galvanized_steel`, plus optional `internal_diameter_mm` override); explicit `data_provenance` (`"built-in preliminary baseline data, not from a cited source, verify against manufacturer datasheet and locally adopted code"` vs `"owner_supplied"`) and `"PRELIMINARY PASS/FAIL (built-in baseline data)"` acceptance labels surfaced across results, UI result cards, and DOCX/PDF/XLSX export headers & Excel formulas; strict reference provenance blocking missing/unreviewed/fabricated URLs (`HTTP 422`) and attaching `"verify against the locally adopted code"`; Step 12 QA Agent integration independently recomputing results, `data_provenance`, units, references, and exports; bilingual Arabic RTL & English LTR **Calculations (MEP)** UI tab using synthetic presets only; `89 passed, 4 skipped` full backend `pytest -v`, `22 passed` frontend Vitest + `tsc --noEmit` + Vite production build, and `gitleaks` clean scan; interactive desktop/browser walkthrough and visual Word/PDF/Excel inspection by the owner remain `PENDING`.)*
- **Branch:** `step-13-calculation-framework`
- **Depends on:** Step 12 (`c38d8a0`, PR `#21` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`backend/app/db/models.py`, `backend/alembic/versions/0011_step13_calculation_framework.py`):**
   - Extended `Calculation` (`calculations` table) with `references_json`, `revision`, `version`, `export_version`, `language`, `acceptance_passed`, and `tokens_used` (`0`).
   - Added nullable `calculation_id` FK (`ON DELETE SET NULL`) onto `Deliverable` (`deliverables` table) and `DeliverableOut` schema so exported `DOCX`, `PDF`, and `XLSX` calculation deliverables download cleanly with SHA-256 verification.

2. **Pure Deterministic Python Calculation Library (`backend/app/skills/calculations.py`):**
   - Zero AI arithmetic; all engineering evaluations compute deterministically in Python (`0` AI tokens):
     - **`electrical_load_schedule`**: Circuit-level `P_dem = P_conn * DF`, `S = P_dem / PF`, spare capacity scaling, 3-phase `L1/L2/L3` balancing & phase unbalance percentage, rated line current `I_des`, and feeder capacity check (`data_provenance = "owner_supplied"` since all panel/circuit inputs are owner-supplied).
     - **`electrical_cable_sizing`**: Design current `I_b`, standard protective device selection `I_n >= I_b`, ambient & grouping derating `C_total = C_a * C_g`, temperature-adjusted conductor resistance `R(T)`, ampacity coordination `I_b <= I_n <= I_z,derated`, and voltage-drop check stepping up standard metric conductor sizes (`1.5..240 mm^2`) when voltage drop governs; supports `custom_ampacity_a` (and `custom_r_ohm_per_km`/`custom_x_ohm_per_km`) to switch provenance from built-in baseline to `"owner_supplied"`.
     - **`electrical_voltage_drop`**: Steady-state 3-phase / 1-phase AC voltage drop (`V` and `%`), upstream cumulative voltage drop, receiving-end voltage, and code-limit pass/fail evaluation; supports explicit `r_ohm_per_km` & `x_ohm_per_km` for `"owner_supplied"` provenance.
     - **`plumbing_water_demand`**: Water Supply Fixture Units (WSFU) summation, piecewise-linear Hunter's-curve peak demand interpolation (`GPM`, `L/s`, `m3/h`), daily consumption & reserve tank sizing (`m3`), total dynamic head (`m`), and booster hydraulic/shaft pump power (`kW`); supports per-fixture `wsfu_per_unit` and `custom_peak_flow_lps` overrides for `"owner_supplied"` provenance.
     - **`plumbing_pipe_sizing`**: Darcy-Weisbach hydraulic pipe sizing storing `nominal_diameter_mm`, `outer_diameter_mm`, `wall_thickness_mm`, and `internal_diameter_mm` separately per material (`PPR_PN20` SDR 6, `uPVC` SDR 11, `copper`, `galvanized_steel` — all labelled preliminary) plus optional `internal_diameter_mm` override (`"owner_supplied"`). Velocity, Reynolds number, Swamee-Jain friction factor, and head loss (`m/100m`, total `m`, `kPa`) are evaluated strictly on the **internal diameter (ID)**. Verified on `PPR_PN20` at `1.5 L/s`: `DN40` (`OD=40.0 mm`, `wall=6.7 mm`, `ID=26.6 mm`) yields `v=2.6992 m/s > 1.5 m/s` (**`PRELIMINARY FAIL (built-in baseline data)`**), `DN50` (`ID=33.4 mm`) yields `v=1.7120 m/s` (**`PRELIMINARY FAIL`**), and the auto-selector advances to **`DN63`** (`OD=63.0 mm`, `wall=10.5 mm`, `ID=42.0 mm`, `v=1.0827 m/s`, `hf_100=3.041 m/100m` -> **`PRELIMINARY PASS (built-in baseline data)`**).
   - **Data Provenance & Preliminary Acceptance Wording:** Whenever any built-in baseline table (`_BASELINE_AMPACITY_A`, default resistance physics, `DEFAULT_WSFU_WEIGHTS`, `_HUNTER_CURVE_GPM`, or `_PRELIMINARY_PIPE_DIMENSIONS`) is used, `results["data_provenance"]` is set to `"built-in preliminary baseline data, not from a cited source, verify against manufacturer datasheet and locally adopted code"` and acceptance labels read `"PRELIMINARY PASS (built-in baseline data)"` / `"PRELIMINARY FAIL (built-in baseline data)"`. When built-in tables are bypassed/overridden with owner values, `data_provenance` is `"owner_supplied"` and verdict labels read `"PASS"` / `"FAIL"`.
   - Every calculation output populates all 8 required fields (`inputs`, `units`, `equations`, `method`, `assumptions`, `results`, `acceptance_criteria`, `references`) and ships 5 synthetic clinic/office presets (`0%` client data).

3. **Strict Sourced References & Service Endpoints (`backend/app/services/calculations.py`, `backend/app/api/calculations.py`, `backend/app/schemas/calculations.py`):**
   - Enforces that every calculation provides at least one reference from `owner_supplied` or `verified_source_log` (pointing to a `ResearchSource` with `reviewed=True` and `accessible` / `owner_provided` status); rejects missing, unreviewed (`HTTP 403`), or unlogged URLs (`HTTP 422`), never invents code clauses, and guarantees every reference carries the `"verify against the locally adopted code"` label.
   - Endpoints: `GET /api/calculations/presets`, `POST /api/projects/{project_id}/calculations`, `GET /api/projects/{project_id}/calculations`, `GET /api/calculations/{calculation_id}`, `PATCH /api/calculations/{calculation_id}`, and `POST /api/calculations/{calculation_id}/export`.

4. **Bilingual DOCX / PDF / Live-Formula XLSX Export (`backend/app/services/calc_export.py`):**
   - `POST /api/calculations/{calculation_id}/export` writes immutable versioned (`_v1`, `_v2`, `HTTP 409` overwrite protection) `DOCX` (RTL/LTR), `PDF` (PyMuPDF `Story` + embedded `Tahoma` Arabic RTL/LTR), and `XLSX` (live Excel `=ROUND(...)`, `=SUM(...)`, `=SQRT(3)`, `=PI()*POWER(B<id_row>/1000,2)/4`, `=IF(...)` formulas on Sheet 1 + Documentation & References on Sheet 2) into `04_Engineering_Calculations/` and registers all 3 deliverables. All 3 formats display `data_provenance` and `"PRELIMINARY PASS/FAIL (built-in baseline data)"` wording in headers and Excel verdict formulas, plus `evaluated_sizes` breakdowns showing OD, wall, ID, velocity, and pass/fail status.

5. **Step 12 QA Agent Integration (`backend/app/agents/qa_agent.py`, `backend/app/services/qa.py`, `backend/app/schemas/qa.py`):**
   - Extended isolated `QaContextData` & `QaContextIsolationReport` with `inspected_calculation_ids`.
   - QA Agent independently recomputes every stored `Calculation` at `0` AI tokens via `evaluate_calculation`, catching tampered numeric outputs or mismatched `data_provenance`/`acceptance_outcome_label` (`arithmetic`), non-standard/missing units (`unit`), missing/unreviewed/unlabelled references (`reference`), failed acceptance criteria or missing mandatory sections (`schedule_consistency`), and incomplete/corrupt calculation exports (`missing_deliverable` / `integrity`).

6. **Bilingual RTL/LTR Frontend UI (`frontend/src/components/CalculationsView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added the **الحسابات الهندسية (MEP) / Calculations (MEP)** tab (`initialTab="calculations"`), supporting project/task selection, synthetic preset loading, input JSON editing, owner/verified-source reference selection with mandatory `"verify against the locally adopted code"` notice, full 8-section inspection, prominent **`Data Provenance`** banner and `"PRELIMINARY PASS/FAIL (built-in baseline data)"` or `"PASS"/"FAIL"` badges on the result card, `evaluated_sizes` pipe OD/wall/ID breakdown table, `DOCX + PDF + XLSX` export, and deliverable downloads.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0011_step13_calculation_framework.py`
- `<repo>/backend/app/api/calculations.py`
- `<repo>/backend/app/schemas/calculations.py`
- `<repo>/backend/app/services/calc_export.py`
- `<repo>/backend/app/services/calculations.py`
- `<repo>/backend/app/skills/calculations.py`
- `<repo>/backend/tests/test_calculations.py`
- `<repo>/frontend/src/components/CalculationsView.tsx`
- `<repo>/docs/reports/step-13.md`

### Changed
- `<repo>/backend/app/agents/qa_agent.py` *(isolated calculation inspection, recomputation, unit/reference/acceptance/export checks)*
- `<repo>/backend/app/db/models.py` *(added `Deliverable.calculation_id` and Step 13 `Calculation` metadata/acceptance columns)*
- `<repo>/backend/app/main.py` *(registered `calculations_router`)*
- `<repo>/backend/app/schemas/qa.py` *(added `inspected_calculation_ids` to `QaContextIsolationReport`)*
- `<repo>/backend/app/schemas/reports.py` *(added `calculation_id` on `DeliverableOut`)*
- `<repo>/backend/app/services/boq.py` *(mapped `calculation_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/services/qa.py` *(counted `inspected_calculation_ids` in verification gate)*
- `<repo>/backend/app/services/review_reports.py` *(mapped `calculation_id` in `_to_deliverable_out`)*
- `<repo>/backend/tests/test_migrations.py` *(asserted Step 13 columns on `calculations` and `deliverables` across upgrade/downgrade)*
- `<repo>/docs/DECISIONS.md` *(added `ADR-022`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 13 bilingual `CalculationsView` & calculation API Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(wired `calculations` tab & Step 13 subtitle)*
- `<repo>/frontend/src/api.ts` *(added Step 13 calculation preset/CRUD/export API wrappers)*
- `<repo>/frontend/src/types.ts` *(added Step 13 TypeScript interfaces)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Calculation Output (`0` AI Tokens)

Executed deterministically across all 5 synthetic clinic/office presets (`0%` client data, `0` AI tokens):

```text
[electrical] electrical_load_schedule | passed=True | {'total_connected_kw': 39.5, 'total_demand_kw': 32.3, 'overall_demand_factor': 0.8177, 'effective_power_factor': 0.85, 'total_apparent_kva': 37.9999, 'design_load_kw': 38.76, 'design_apparent_kva': 45.5999, 'design_current_a': 65.8178, 'phase_l1_kw': 10.5, 'phase_l2_kw': 10.7, 'phase_l3_kw': 11.1, 'phase_unbalance_pct': 5.5728, 'data_provenance': 'owner_supplied', 'acceptance_outcome_label': 'PASS', 'acceptance_passed': True}
[electrical] electrical_cable_sizing | passed=True | {'design_current_a': 30.5656, 'breaker_rating_a': 32.0, 'total_derating_factor': 0.696, 'required_tabulated_ampacity_a': 45.977, 'selected_cable_size_mm2': 6.0, 'tabulated_ampacity_a': 54.0, 'derated_ampacity_a': 37.584, 'ampacity_margin_pct': 17.45, 'resistance_ohm_per_km': 3.664, 'reactance_ohm_per_km': 0.08, 'voltage_drop_v': 7.52, 'voltage_drop_pct': 1.88, 'governing_criterion': 'ampacity', 'data_provenance': 'built-in preliminary baseline data, not from a cited source, verify against manufacturer datasheet and locally adopted code', 'acceptance_outcome_label': 'PRELIMINARY PASS (built-in baseline data)', 'acceptance_passed': True}
[electrical] electrical_voltage_drop | passed=True | {'effective_current_a': 45.0, 'resistance_ohm_per_km': 1.2893, 'reactance_ohm_per_km': 0.08, 'voltage_drop_v': 7.0962, 'circuit_voltage_drop_pct': 1.774, 'upstream_drop_pct': 1.0, 'total_voltage_drop_pct': 2.774, 'receiving_voltage_v': 388.904, 'data_provenance': 'built-in preliminary baseline data, not from a cited source, verify against manufacturer datasheet and locally adopted code', 'acceptance_outcome_label': 'PRELIMINARY PASS (built-in baseline data)', 'acceptance_passed': True}
[plumbing] plumbing_water_demand | passed=True | {'total_fixture_count': 13, 'total_wsfu': 21.5, 'peak_flow_gpm': 17.675, 'peak_flow_lps': 1.1151, 'peak_flow_m3_h': 4.0144, 'daily_demand_l': 3600.0, 'daily_demand_m3': 3.6, 'storage_tank_m3': 3.6, 'total_dynamic_head_m': 30.0, 'hydraulic_power_kw': 0.3281, 'pump_shaft_power_kw': 0.5048, 'data_provenance': 'built-in preliminary baseline data, not from a cited source, verify against manufacturer datasheet and locally adopted code', 'acceptance_outcome_label': 'PRELIMINARY PASS (built-in baseline data)', 'acceptance_passed': True}
[plumbing] plumbing_pipe_sizing | passed=True | {'flow_rate_m3_s': 0.0015, 'selected_nominal_diameter_mm': 63.0, 'outer_diameter_mm': 63.0, 'wall_thickness_mm': 10.5, 'internal_diameter_mm': 42.0, 'velocity_mps': 1.0827, 'reynolds_number': 45291.6742, 'darcy_friction_factor': 0.02137, 'head_loss_m_per_100m': 3.041, 'total_head_loss_m': 1.224, 'pressure_drop_kpa': 11.9816, 'data_provenance': 'built-in preliminary baseline data, not from a cited source, verify against manufacturer datasheet and locally adopted code', 'acceptance_outcome_label': 'PRELIMINARY PASS (built-in baseline data)', 'acceptance_passed': True}
```

And for `PPR_PN20` DN40 at `1.5 L/s` (`nominal_diameter_mm=40.0` forced check):
`OD = 40.0 mm`, `wall = 6.7 mm`, `ID = 26.6 mm`, `velocity_mps = 2.6992 m/s > 1.5 m/s` -> `acceptance_passed = False`, `acceptance_outcome_label = "PRELIMINARY FAIL (built-in baseline data)"`; supplying explicit `internal_diameter_mm = 40.0` yields `velocity_mps = 1.1937 m/s`, `data_provenance = "owner_supplied"`, `acceptance_outcome_label = "PASS"`.

## 4. Tests Run (Unedited Summary & Secret Scan)

### Backend Full Suite (`pytest -v`)

```text
> backend\.venv\Scripts\pytest.exe backend/tests -v
collected 93 items

... (all non-opt-in test modules passed cleanly, including:)
backend\tests\test_calculations.py::test_step13_hand_checked_electrical_and_plumbing_unit_calculations PASSED [ 18%]
backend\tests\test_calculations.py::test_step13_owner_supplied_overrides_and_data_provenance PASSED [ 19%]
backend\tests\test_calculations.py::test_step13_reference_validation_exports_docx_pdf_xlsx_and_qa_checks PASSED [ 20%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 52%]
backend\tests\test_qa.py::test_step12_qa_context_excludes_producer_reasoning_and_task_never_verified_by_generation_alone PASSED [ 69%]
backend\tests\test_qa.py::test_step12_qa_catches_all_seeded_errors_and_manages_issue_register_lifecycle PASSED [ 70%]

================== 89 passed, 4 skipped in 122.96s (0:02:02) ==================
```

*(Note: 4 skipped tests are the opt-in live external tool/network checks (`RUN_REAL_ODA`, `RUN_REAL_OCR`, `RUN_REAL_RESEARCH`) not modified in Step 13.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)

```text
✓ src/App.test.tsx (22 tests) 69ms
Test Files  1 passed (1) | Tests  22 passed (22) | Duration  1.01s
tsc --noEmit && vite build -> 38 modules transformed -> built in 584ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across `backend`, `frontend/src`, `docs`: `BOM_FILES: []`.
- Local-path & secret-pattern check across tracked/updated dirs: `USER_PATH_HITS: []`.
- `gitleaks detect --source . --no-banner -v` executed on committed branch HEAD.

## 5. Known Limits & Owner Review Needed
1. **Live Browser UI & Word/PDF/Excel Visual Inspection (`PENDING` owner check):** Automated suites verify deterministic calculations, API reference checks, XLSX live formulas (including `internal_diameter_mm` area reference and preliminary verdict formula), DOCX/PDF generation, QA recomputation, and Vitest SSR markup; visual review of the bilingual **Calculations (MEP)** tab in the running app and opening exported `.docx`, `.pdf`, and `.xlsx` deliverables in Microsoft Word, PDF viewer, and Excel remains for the owner.
2. **Preliminary Baseline Tables (`built-in preliminary baseline data` vs `owner_supplied`):** Cable baseline ampacities (`_BASELINE_AMPACITY_A`), default conductor resistance parameters, Hunter's-curve WSFU weights/curves (`DEFAULT_WSFU_WEIGHTS`, `_HUNTER_CURVE_GPM`), and per-material SDR/schedule pipe dimension tables (`_PRELIMINARY_PIPE_DIMENSIONS`) are built-in preliminary planning baselines (`data_provenance = "built-in preliminary baseline data, not from a cited source, verify against manufacturer datasheet and locally adopted code"`) that label outcomes as `PRELIMINARY PASS/FAIL (built-in baseline data)` until overridden with owner-supplied parameters (`custom_ampacity_a`, `r_ohm_per_km`, `wsfu_per_unit` + `custom_peak_flow_lps`, or `internal_diameter_mm`). Final construction-issue engineering calculations always require licensed engineer review against locally adopted codes and manufacturer datasheets.

## 6. Checklist
- [x] Branch `step-13-calculation-framework` branched cleanly from updated `main` (`c38d8a0`)
- [x] Reversible migration `0011_step13_calculation_framework` (`down_revision = "0010"`)
- [x] Pure Python deterministic calculators (`0` AI tokens, no AI arithmetic) for load schedules, cable sizing, voltage drop, water demand, and pipe sizing unit-tested against hand-checked examples
- [x] Every calculation shows inputs, units, equations, method, assumptions, results, acceptance criteria, and references
- [x] Standards references restricted to owner-supplied or verified `ResearchSource` log, labelled `"verify against the locally adopted code"`, with zero invented clauses
- [x] Versioned `DOCX`, `PDF`, and live-formula `XLSX` calculation exports into `04_Engineering_Calculations/`
- [x] QA-agent checks integrated for calculations (arithmetic recomputation, units, references, acceptance criteria, and export integrity)
- [x] Bilingual RTL/LTR **Calculations (MEP)** UI tab with synthetic examples only
- [x] `ADR-022` added in `docs/DECISIONS.md`
- [x] `docs/reports/step-13.md` marked **`PARTIAL`** until owner live UI & document review
- [x] Pushed `step-13-calculation-framework` only (`main` untouched, no merge)
