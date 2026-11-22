# Step 15 — Technical Comparison Module (Weighted Decimal Matrix, Source Provenance, Unit/Currency Guard, Owner Decision Gate & Bilingual Exports)

- **Date:** 2026-11-22
- **Status:** **PARTIAL** *(Delivers reversible migration `0013_step15_technical_comparisons` adding `technical_comparisons` and `deliverables.comparison_id`; deterministic `decimal.Decimal` weighted comparison engine (`0` AI tokens by default) grounded in real project BOQs, Specifications, Calculations, reviewed Research Sources, or owner-entered offers; strict `weights == 100` validation (`HTTP 422` otherwise) and mandatory pass/fail gating; explicit verified `Decimal` physical unit conversions vs strict currency/unit mismatch flagging (`flagged_mismatch`, zero silent FX conversions); verbatim `'not provided'` display for omitted values without fabricating prices, certifications, or standards; explicit owner/engineer final decision endpoint (`POST /api/comparisons/{id}/decide`) preventing any option from being presented as auto-finalized; optional prose-only Gemini narrative tagged `UNVERIFIED AI DRAFT` until owner sign-off; immutable SHA-256 versioned Arabic RTL & English LTR `DOCX`, landscape `PDF`, and live-formula `XLSX` (`=SUM(...)`/`=ROUND(...)`/`=IF(...)`) exports in `09_Comparisons/` plus `Deliverable` records; Step 12 QA Agent verification across all checks; bilingual RTL/LTR **Technical Compare** UI tab; `94 passed, 4 skipped` full backend `pytest -v`, `24 passed` frontend Vitest + `tsc --noEmit` + Vite build, and clean `gitleaks` check; owner interactive UI & exported DOCX/PDF/XLSX spreadsheet visual verification remain `PENDING`.)*
- **Branch:** `step-15-technical-comparison`
- **Depends on:** Step 14 (`6aaba5c`, PR `#23` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`0013_step15_technical_comparisons.py`):**
   - Created `technical_comparisons` (`TechnicalComparison` ORM model) storing `project_id`, `task_id`, `title`, `comparison_scope` (`equipment` / `material` / `vendor_offer` / `system_alternative`), `discipline`, `language`, `classification`, `revision`, `version`, `export_version`, `status`, `use_ai`, `ai_draft_status` (`CHECK IN ('not_used', 'unverified_ai_draft', 'owner_approved')`), `owner_decision_status` (`CHECK IN ('pending_owner_decision', 'owner_selected')`), `owner_selected_option_id`, `owner_decision_note`, `owner_decided_by`, `owner_decided_at`, `tokens_used`, `token_usage_json`, `criteria_json`, `options_json`, `matrix_result_json`, and `summary`.
   - Added nullable `comparison_id` FK (`ON DELETE SET NULL`) on `deliverables` and updated `DeliverableOut` mappings in `schemas/reports.py`, `services/review_reports.py`, and `services/boq.py`.

2. **Deterministic `Decimal` Evaluation Engine & Provenance Guards (`backend/app/skills/comparisons.py`, `backend/app/services/comparisons.py`):**
   - **Strict Weights & Mandatory Gating:** Rejects criteria sets whose positive weights do not sum strictly to `100.0` (`HTTP 422`); evaluates `boolean_pass`, `mandatory_min`, and `mandatory_max` gating per option before advisory ranking.
   - **Real Project Grounding (`_validate_comparison_sources`):** Validates every linked `boq_item_id` (via `BoqItem.boq_sheet_id`), `specification_id`, `calculation_id`, and reviewed accessible/owner-provided `research_source_id` belonging to the project, and blocks unreviewed URLs in `source_ref` (`HTTP 422`).
   - **No Fabrication / `'not provided'`:** Missing or omitted metrics render strictly as `'not provided'` with `0.0000` normalized/weighted score (and fail mandatory checks when `is_mandatory=True`). Optional `lifecycle_cost` is derived deterministically (`initial_cost + operating_cost * lifecycle_years`) ONLY when all inputs and compatible currency/units are present.
   - **Explicit Unit Conversion & Currency Guard:** Physical unit conversions (`W`/`kW`/`MW`, `L/s`/`m3/h`/`GPM`, `mm`/`cm`/`m`, `Pa`/`kPa`/`bar`, `Wh`/`kWh`/`MWh`, `g`/`kg`/`ton`, `hours`/`years`) are converted explicitly in `Decimal` (`converted_explicitly`); mixed currencies (`USD` vs `LYD`) or incompatible units are never silently converted and are flagged as `flagged_mismatch`.
   - **Advisory Notice & Owner Decision Gate (`decide_technical_comparison`):** Outputs explicitly state advisory rank only (`ADVISORY_NOTICE_EN` / `ADVISORY_NOTICE_AR`); final selection is recorded exclusively by the owner/licensed engineer via `POST /api/comparisons/{comparison_id}/decide`.
   - **Optional AI Narrative (`draft_comparison_narrative_with_ai`):** Default `use_ai=false` (`0` tokens). When enabled, checks Step 04 token limits, never modifies numeric scores/weights/rankings, blocks ungrounded URLs/standard codes, and tags text `UNVERIFIED AI DRAFT` until approved.

3. **Bilingual RTL/LTR DOCX, Landscape PDF & Live-Formula XLSX Exports (`backend/app/services/comparison_export.py`):**
   - Reuses Step 9's `python-docx` (`w:bidi`, `w:rtl`, `w:bidiVisual`, `Tahoma`) and PyMuPDF `Story` (`Tahoma` font archive + Unicode LRI/PDI isolates) helpers on landscape A4 for clean side-by-side option comparison rendering.
   - Exports live-formula `XLSX` workbooks (`Sheet 1`: criteria weights `=SUM(...)`, live weighted score formulas `=ROUND(norm*weight/100,4)`, option totals `=ROUND(SUM(...),4)`, `=IF(...)` weights-sum & mandatory checks, explicit `'not provided'` highlighting; `Sheet 2`: source provenance, unit conversion log, and risks) into `09_Comparisons/` (`HTTP 409` overwrite protection) with SHA-256 `Deliverable` rows.

4. **Step 12 QA Agent Checks (`backend/app/agents/qa_agent.py`, `backend/app/schemas/qa.py`):**
   - Extended `QaContextData` & `QaContextIsolationReport` with `inspected_comparison_ids`.
   - Independently recomputes every comparison in `Decimal` (`arithmetic`): catches non-100 weights, stored vs recomputed score/rank/mandatory discrepancies, and missing/corrupt XLSX live formulas (`integrity` / `arithmetic`).
   - Flags `flagged_mismatch` unit/currency errors (`unit`), unsourced/dangling/unreviewed metrics & URLs (`reference`), missing mandatory `'not provided'` cells & unapproved AI drafts (`schedule_consistency`), and incomplete `09_Comparisons/` DOCX/PDF/XLSX packages or SHA-256 tampering (`missing_deliverable` / `integrity`).

5. **Bilingual RTL/LTR Frontend UI (`frontend/src/components/TechnicalComparisonsView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added **المقارنات الفنية (Compare) / Technical Compare** tab (`initialTab="comparisons"`) with synthetic clinic presets loader, live `Weight Sum = 100.00%` validator, project BOQ/Spec/Calc/Source summary counter, editable multi-option matrix cells, advisory banner, unit mismatch & `'not provided'` callouts, Owner Decision form, AR/EN DOCX/PDF/XLSX export buttons, and SHA-256 download links.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0013_step15_technical_comparisons.py`
- `<repo>/backend/app/api/comparisons.py`
- `<repo>/backend/app/schemas/comparisons.py`
- `<repo>/backend/app/services/comparison_export.py`
- `<repo>/backend/app/services/comparisons.py`
- `<repo>/backend/app/skills/comparisons.py`
- `<repo>/backend/tests/test_comparisons.py`
- `<repo>/frontend/src/components/TechnicalComparisonsView.tsx`
- `<repo>/docs/reports/step-15.md`

### Changed
- `<repo>/backend/app/agents/qa_agent.py` *(Step 15 isolated context, weights == 100 & Decimal score recomputation, comparison XLSX live-formula check, unit mismatch checks, source/URL checks, missing mandatory/'not provided' & unapproved AI draft checks, deliverable completeness/SHA-256 checks)*
- `<repo>/backend/app/db/models.py` *(added `TechnicalComparison` ORM model and `Deliverable.comparison_id` FK)*
- `<repo>/backend/app/main.py` *(registered `comparisons_router`)*
- `<repo>/backend/app/schemas/qa.py` *(added `inspected_comparison_ids` on `QaContextIsolationReport`)*
- `<repo>/backend/app/schemas/reports.py` *(added `comparison_id` on `DeliverableOut`)*
- `<repo>/backend/app/services/boq.py` *(mapped `comparison_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/services/review_reports.py` *(mapped `comparison_id` in `_to_deliverable_out`)*
- `<repo>/backend/tests/test_migrations.py` *(asserted `technical_comparisons` table & `deliverables.comparison_id` across Alembic upgrade/downgrade)*
- `<repo>/docs/DECISIONS.md` *(added `ADR-024`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 15 bilingual `TechnicalComparisonsView` SSR & comparison API Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(wired `comparisons` tab & Step 15 subtitle)*
- `<repo>/frontend/src/api.ts` *(added Step 15 comparison presets/create/list/detail/decide/export API wrappers)*
- `<repo>/frontend/src/types.ts` *(added Step 15 TypeScript comparison interfaces & `comparison_id` / `inspected_comparison_ids`)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Output (`0` AI Tokens)

Deterministic output from `get_synthetic_comparison_presets()[0]` (synthetic 150 kVA clinic generator example, `0%` client data, `0` AI tokens):

```text
total_weight: 100.0 leader: Synthetic Offer A — Heavy-Duty Industrial Enclosure
#1 | opt_a | Synthetic Offer A — Heavy-Duty Industrial Enclosure | score=94.8405 | mand=True
#2 | opt_b | Synthetic Offer B — Compact Quick-Delivery Unit | score=88.7682 | mand=True
```

## 4. Tests Run (Exact Observed Results & Secret Scan)

### Step 15 Hand-Checked & API Test (`-x -q` & Full Backend Suite)
```text
> .\backend\.venv\Scripts\pytest.exe backend/tests/test_comparisons.py -k test_step15_api_project_grounding_exports_owner_decision_and_qa_pass -x -q
.                                                                        [100%]
1 passed, 2 deselected in 5.35s
```

```text
> .\backend\.venv\Scripts\pytest.exe backend/tests -v
collected 98 items

... (all non-opt-in test modules passed cleanly: test_boq, test_cad_bim, test_calculations, test_comparisons, test_config, test_drawings, test_extraction, test_migrations, test_projects, test_providers, test_qa, test_reports, test_research, test_specifications, test_tasks)

================== 94 passed, 4 skipped in 170.95s (0:02:50) ==================
```
*(The 4 skipped tests are the pre-existing opt-in live tool/network tests `RUN_REAL_ODA`, `RUN_REAL_OCR`, `RUN_REAL_RESEARCH`.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)
```text
> cd frontend; npm.cmd test; npm.cmd run build
✓ src/App.test.tsx (24 tests) 84ms
Test Files  1 passed (1) | Tests  24 passed (24) | Duration  959ms
tsc --noEmit && vite build -> 40 modules transformed -> built in 614ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across repo `.py/.ts/.tsx/.md/.json`: `BOM_FILES: []`.
- Local-path check across `backend`, `frontend/src`, `docs`: `0` matches.
- `gitleaks detect --source . --no-banner -v`: executed cleanly (`0` leaks found).

## 5. Decisions Made
- Recorded **`ADR-024`** in `<repo>/docs/DECISIONS.md` covering Step 15's Decimal comparison scoring, project source validation (`boq_item`, `specification`, `calculation`, reviewed `research_source`, `owner_entered`), explicit physical conversions vs flagged currency mismatches, verbatim `'not provided'` handling, advisory notice & explicit owner decision gate, optional `UNVERIFIED AI DRAFT` narrative, bilingual RTL/LTR DOCX/PDF/live-formula XLSX export, and QA Agent checks.

## 6. Known Limitations & Owner Review Needed
1. **Live Browser & Word/PDF/Excel Visual Walkthrough (`PENDING` owner check):** Automated suites verify Decimal scoring against hand checks, DOCX `w:bidi` XML tags, PyMuPDF PDF extraction, live Excel formulas (`=SUM`/`=ROUND`), SHA-256 checksums, QA defect traps, and Vitest SSR markup; opening the running UI and visually checking rendered `.docx`, `.pdf`, and `.xlsx` files remains for the owner.
2. **Currency Exchange Rates Never Auto-Assumed:** Differing currencies (`USD` vs `LYD`, etc.) intentionally trigger a unit mismatch flag rather than guessing exchange rates; standardize comparison options to one currency using an owner-verified FX rate when commercial normalization is desired.

## 7. How to Test in the Running App
1. Ensure backend + frontend are running (`scripts\start.bat`, health `GET http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`).
2. Open **المقارنات الفنية (Compare) / Technical Compare**, pick a project, click **Load Fixture** to inspect a synthetic generator/booster-pump comparison (or enter options linked to real BOQ/Specs/Calcs), confirm weights sum to `100.00%`, and click **Evaluate & Export Package (DOCX / PDF / XLSX)**.
3. Verify the advisory banner, `'not provided'` & unit-conversion/mismatch badges, record the Owner / Engineer selection via **Record Final Owner Decision**, and download the immutable SHA-256 DOCX, PDF, and live-formula XLSX deliverables from `09_Comparisons/`.

## 8. Checklist & Ready for Next Step?
- [x] Branch `step-15-technical-comparison` created cleanly from pulled `main` (`6aaba5c`)
- [x] Reversible migration `0013_step15_technical_comparisons` (`down_revision = "0012"`) verified via Alembic round-trip test
- [x] Weighted Decimal evaluation (`0` AI tokens by default) strictly enforces `weights == 100` & mandatory gates
- [x] Real project BOQ/Spec/Calc/reviewed ResearchSource grounding + verbatim `'not provided'` on omitted cells (zero fabricated values)
- [x] Explicit physical unit conversion vs flagged currency/unit mismatch (no silent FX assumptions)
- [x] Advisory rank only; explicit Owner / Licensed Engineer decision endpoint (`POST /api/comparisons/{id}/decide`)
- [x] Optional Gemini prose narrative tagged `UNVERIFIED AI DRAFT` until owner approval
- [x] Versioned SHA-256 DOCX + PDF + live-formula XLSX exports (Arabic RTL & English LTR) saved in `09_Comparisons/` + `Deliverables`
- [x] QA Agent checks for weights sum, arithmetic recomputation, unit mismatch, unsourced values, missing mandatory `'not provided'`, and deliverable integrity
- [x] Bilingual RTL/LTR UI tab (`TechnicalComparisonsView.tsx`)
- [x] `ADR-024` and `docs/reports/step-15.md` (`Status: PARTIAL`) committed & `gitleaks` clean
- [ ] Owner visual UI & DOCX/PDF/XLSX walkthrough (**Ready for owner review & PR to `main`**; push branch only, no merge)
