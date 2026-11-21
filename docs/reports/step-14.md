# Step 14 — Specifications Generator (BOQ & Drawing-Linked, Traceable, Bilingual RTL/LTR DOCX & PDF)

- **Date:** 2026-11-21
- **Status:** **PARTIAL** *(Delivers reversible migration `0012_step14_specifications` adding `specifications` and `deliverables.specification_id`; deterministic `0`-AI-token specification generator anchored directly to real project BOQ items, `ParametricDrawing` schedules, and reviewed `ResearchSource` log entries across all 8 required sub-sections (`scope`, `standards`, `materials`, `execution`, `testing`, `acceptance`, `submittals`, `warranty`); strict reviewed-only standards enforcement emitting `'no verified standard on file - verify against the locally adopted code'` with zero invented clause numbers or edition years; clause-level BOQ/drawing/source traceability anchors (`SpecTraceRef`); optional Gemini prose drafting labelled `UNVERIFIED AI DRAFT — Pending Owner Approval` until `POST /api/specifications/{id}/approve`; immutable versioned `07_Technical_Specifications/` `DOCX` and `PDF` exports reusing Step 9 Arabic RTL (`w:bidi`/`w:rtl`/`Tahoma`) & English LTR rendering with SHA-256 verification and `Deliverable` records; QA Agent checks catching orphan/unmapped sections, missing sub-sections, unapproved AI drafts, unsourced/orphan standards, invented code citations, and corrupt deliverables; bilingual RTL/LTR **Technical Specs** UI tab; `91 passed, 4 skipped` full backend `pytest -v`, `23 passed` frontend Vitest + `tsc --noEmit` + Vite build, and clean `gitleaks` scan; owner interactive browser walkthrough and opening exported Word/PDF deliverables remain `PENDING`.)*
- **Branch:** `step-14-specifications-generator`
- **Depends on:** Step 13 (`054338e`, PR `#22` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`0012_step14_specifications.py`):**
   - Created `specifications` (`Specification` ORM model) storing `project_id`, `task_id`, `title`, `discipline`, `language`, `classification`, `revision`, `version`, `export_version`, `status`, `use_ai`, `ai_draft_status` (`CHECK IN ('not_used', 'unverified_ai_draft', 'owner_approved')`), `owner_approved_by`, `owner_approved_at`, `tokens_used` (`0` default), `token_usage_json`, and `structured_payload_json`.
   - Added nullable `specification_id` FK (`ON DELETE SET NULL`) on `deliverables` (`DeliverableOut` mapped cleanly across `review_reports.py` and `boq.py`).

2. **Deterministic Specification Engine (`backend/app/skills/specifications.py`):**
   - Pure deterministic compilation (`build_deterministic_specification_sections`) using `0` AI tokens by default (`use_ai: bool = False`):
     - Refuses empty projects lacking BOQ items and `ParametricDrawing` schedules (`HTTP 422`).
     - Maps real project `BoqItem` rows and `ParametricDrawing` schedules (`door_schedule`, `window_schedule`, `finish_schedule`/`rooms`) cleanly into CSI/trade sections (`SPEC-01`..`SPEC-07`).
     - Populates all 8 mandatory parts per section (`scope`, `standards`, `materials`, `execution`, `testing`, `acceptance`, `submittals`, `warranty`) preserving quantities/units/schedule counts verbatim (zero AI arithmetic).
     - Attaches >= 1 `SpecTraceRef` (`boq_item_id`, `drawing_id`/`schedule_kind`, `research_source_id`) to **every single clause**.
   - **Standards Provenance Guard:**
     - Pulls standards ONLY from `ResearchSource` entries where `reviewed=True` and `access_status in ("accessible", "owner_provided")`; blocks explicit unreviewed/inaccessible `research_source_ids` (`HTTP 422`).
     - Emits exact fallback `'no verified standard on file - verify against the locally adopted code'` whenever a section has no matching reviewed source, never inventing clause numbers, edition years, or unverified requirements.

3. **Optional AI Prose Drafting & Owner Approval (`backend/app/services/specifications.py`, `backend/app/api/specifications.py`):**
   - When `use_ai=True`, `draft_specification_prose_with_ai` enforces Step 04 token limits and rewrites prose clarity ONLY for non-standards clauses while keeping `standards`, `trace_refs`, and numeric values locked; rejects any AI rewrite attempting ungrounded URLs or standard code citations (`ASTM`/`BS`/`EN`/`IEC`/etc.).
   - AI-drafted specs are persisted with `ai_draft_status = "unverified_ai_draft"`, visibly badged (`UNVERIFIED AI DRAFT — Pending Owner Approval` / `مسودة ذكاء اصطناعي غير مُتحقَّق منها — بانتظار اعتماد المالك`) across the API, UI, DOCX, and PDF until `POST /api/specifications/{id}/approve` records owner approval.
   - Endpoints: `GET /api/specifications/presets`, `POST /api/projects/{project_id}/specifications`, `GET /api/projects/{project_id}/specifications`, `GET /api/specifications/{spec_id}`, `POST /api/specifications/{spec_id}/approve`, and `POST /api/specifications/{spec_id}/export`.

4. **Bilingual Arabic RTL / English LTR DOCX & PDF Export (`backend/app/services/spec_export.py`):**
   - Reuses Step 9's exact `python-docx` RTL/LTR (`w:bidi`, `w:rtl`, `w:bidiVisual`, `Tahoma`) and PyMuPDF `Story` (`Tahoma` font archive + `\u2066...\u2069` Unicode LRI/PDI isolates) helpers.
   - Writes immutable versioned `.docx`, `.pdf`, and provenance `.json` files into `07_Technical_Specifications/` (`HTTP 409` overwrite protection) with SHA-256 checksums and registered `Deliverable` records.

5. **Step 12 QA Agent Integration (`backend/app/agents/qa_agent.py`, `backend/app/schemas/qa.py`):**
   - Extended `QaContextData` & `QaContextIsolationReport` with `inspected_specification_ids`.
   - Verifies every specification section maps to existing project BOQ items or drawings (catching orphan/unmapped sections under `schedule_consistency`), flags missing sections or missing mandatory 8 sub-sections or untraced clauses, blocks `unverified_ai_draft` specs from passing verification, catches orphan/unsourced/invented standard citations (`reference`), and checks `07_Technical_Specifications/` DOCX+PDF deliverable presence & SHA-256 (`missing_deliverable` / `integrity`).

6. **Bilingual RTL/LTR Frontend UI (`frontend/src/components/SpecificationsView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added **المواصفات الفنية (Specs) / Technical Specs** tab (`initialTab="specifications"`), displaying project BOQ sheets, parametric drawings, and reviewed research sources, deterministic (`0`-token) vs optional unverified AI generation toggle, owner approval workflow button, 8-part clause viewer with trace badges, AR/EN re-export actions, and SHA-256 deliverable links.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0012_step14_specifications.py`
- `<repo>/backend/app/api/specifications.py`
- `<repo>/backend/app/schemas/specifications.py`
- `<repo>/backend/app/services/spec_export.py`
- `<repo>/backend/app/services/specifications.py`
- `<repo>/backend/app/skills/specifications.py`
- `<repo>/backend/tests/test_specifications.py`
- `<repo>/frontend/src/components/SpecificationsView.tsx`
- `<repo>/docs/reports/step-14.md`

### Changed
- `<repo>/backend/app/agents/qa_agent.py` *(Step 14 isolated context loading, section BOQ/drawing mapping check, missing sub-sections, unapproved AI draft gate, unsourced standard checks, and deliverable integrity)*
- `<repo>/backend/app/db/models.py` *(added `Specification` ORM table and `Deliverable.specification_id` FK)*
- `<repo>/backend/app/main.py` *(registered `specifications_router`)*
- `<repo>/backend/app/schemas/qa.py` *(added `inspected_specification_ids` on `QaContextIsolationReport`)*
- `<repo>/backend/app/schemas/reports.py` *(added `specification_id` on `DeliverableOut`)*
- `<repo>/backend/app/services/boq.py` *(mapped `specification_id` in `_to_deliverable_out`)*
- `<repo>/backend/app/services/review_reports.py` *(mapped `specification_id` in `_to_deliverable_out`)*
- `<repo>/backend/tests/test_migrations.py` *(asserted `specifications` table & `deliverables.specification_id` across Alembic upgrade/downgrade)*
- `<repo>/docs/DECISIONS.md` *(added `ADR-023`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 14 bilingual `SpecificationsView` & specification API Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(wired `specifications` tab & Step 14 subtitle)*
- `<repo>/frontend/src/api.ts` *(added Step 14 specification presets/generate/list/detail/approve/export API wrappers)*
- `<repo>/frontend/src/types.ts` *(added Step 14 TypeScript interfaces)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Output (`0` AI Tokens)

Deterministic output compiled strictly from synthetic clinic BOQ (`E-01`, `P-01`), `A-101` door schedule, and one reviewed electrical guide (`0%` client data, `0` AI tokens):

```text
SPEC-01 | architecture | boq= 0 | dwg= ['A-101:door_schedule'] | std= no_verified_standard_on_file | parts= 8 | notice= no verified standard on file - verify against the locally adopted code
SPEC-02 | electrical | boq= 1 | dwg= [] | std= verified_source_log | parts= 8 | notice= verify against the locally adopted code
SPEC-03 | plumbing | boq= 1 | dwg= [] | std= no_verified_standard_on_file | parts= 8 | notice= no verified standard on file - verify against the locally adopted code
```

## 4. Tests Run (Exact Observed Results & Secret Scan)

### Step 14 Specification Tests
```text
> backend\.venv\Scripts\pytest.exe backend/tests/test_specifications.py -v
collected 2 items

backend\tests\test_specifications.py::test_step14_deterministic_spec_generation_traceability_standards_guard_and_exports PASSED [ 50%]
backend\tests\test_specifications.py::test_step14_ai_draft_unverified_until_owner_approval_and_qa_catches_spec_defects PASSED [100%]

============================== 2 passed in 7.96s ==============================
```

### Backend Full Suite (`pytest -v`)
```text
> backend\.venv\Scripts\pytest.exe backend/tests -v
collected 95 items

... (all non-opt-in test modules passed cleanly, including test_migrations.py, test_specifications.py, test_calculations.py, test_qa.py, test_boq.py, test_drawings.py, test_reports.py)

================== 91 passed, 4 skipped in 163.78s (0:02:43) ==================
```
*(The 4 skipped tests are the pre-existing opt-in live tool/network tests `RUN_REAL_ODA`, `RUN_REAL_OCR`, `RUN_REAL_RESEARCH`.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)
```text
> npm.cmd test
✓ src/App.test.tsx (23 tests) 79ms
Test Files  1 passed (1) | Tests  23 passed (23) | Duration  866ms

> npm.cmd run build
tsc --noEmit && vite build -> 39 modules transformed -> built in 581ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across `backend`, `frontend/src`, `docs`: `BOM_FILES: []`.
- Local-path check across `backend`, `frontend/src`, `docs`: `USER_PATH_HITS: []`.
- `gitleaks detect --source . --no-banner -v`: executed on final commit (`0` leaks found).

## 5. Decisions Made
- Recorded **`ADR-023`** in `<repo>/docs/DECISIONS.md` covering Step 14's BOQ/drawing-linked deterministic specification structure, reviewed-only standards fallback (`no verified standard on file - verify against the locally adopted code`), unverified AI draft gate + owner sign-off, Step 9 RTL/LTR DOCX/PDF reuse, and QA Agent checks.

## 6. Known Limitations & Owner Review Needed
1. **Live UI & Word/PDF Visual Inspection (`PENDING` owner check):** Automated suites verify DOCX bidi XML flags, PyMuPDF RTL/LTR text extraction, SHA-256 checksums, QA failure cases, and Vitest SSR markup; opening the running app in a browser and visually inspecting exported `.docx` / `.pdf` files in Word and PDF viewer remains for the owner.
2. **Standards Coverage Depends on Reviewed Research Logs:** Any section lacking a reviewed `ResearchSource` intentionally displays `no verified standard on file - verify against the locally adopted code`; populate reviewed entries via **Research & Source Log** before generating final construction specifications.

## 7. How to Test in the Running App
1. Ensure backend + frontend are running (`scripts\start.bat`, health `GET http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`).
2. Create or open a project that has a BOQ sheet and/or Parametric CAD drawing (`A-101`).
3. Open **المواصفات الفنية (Specs) / Technical Specs**, choose language (`ar` RTL or `en` LTR), keep optional AI unchecked for `0`-token deterministic output (or check it to inspect the `UNVERIFIED AI DRAFT` approval flow), click **Generate & Save Traceable Specifications**, and download the SHA-256-verified DOCX and PDF from `07_Technical_Specifications/`.

## 8. Checklist & Ready for Next Step?
- [x] Branch `step-14-specifications-generator` created cleanly from pulled `main` (`054338e`)
- [x] Reversible migration `0012_step14_specifications` (`down_revision = "0011"`) verified via Alembic round-trip test
- [x] Traceable 8-part specification generation strictly from project BOQs, drawing schedules & reviewed sources (zero client data)
- [x] Unreviewed/missing standards guarded with explicit `'no verified standard on file - verify against the locally adopted code'`
- [x] Optional Gemini prose drafting (`default use_ai=false`, `0` tokens) labelled unverified until owner approval
- [x] Versioned SHA-256 DOCX + PDF exports (Arabic RTL / English LTR) saved in `07_Technical_Specifications/` + `Deliverables`
- [x] QA Agent checks for section-to-BOQ/drawing mapping, orphan/unsourced standards, missing sub-sections & deliverable integrity
- [x] Bilingual RTL/LTR UI tab (`SpecificationsView.tsx`)
- [x] `ADR-023` and `docs/reports/step-14.md` (`Status: PARTIAL`) committed & `gitleaks` clean
- [ ] Owner visual UI & DOCX/PDF walkthrough (**Ready for owner review & PR to `main`**; hold Step 15 until approved)
