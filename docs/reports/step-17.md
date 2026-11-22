# Step 17 — Standards Library (Owner-Supplied / Licensed Documents Only, Supersession Tracking, Bilingual Register & QA Audits)

- **Date:** 2026-11-22
- **Status:** **PARTIAL** *(Delivers reversible migration `0015_step17_standards_library` adding `standards_library` (`StandardDocument` ORM model); owner-supplied / licensed document storage for uploaded PDF/DOCX/TXT (`0444` read-only + SHA-256) and manually entered standards metadata (`0` AI tokens by default, never fabricating standard text, clause numbers, or edition years from model memory); strict `300`-character permitted excerpt cap (`OwnerExcerptIn`) with `page_ref` so full copyrighted text is never stored or re-exported; deterministic bounded header suggestion (`metadata_status = "unverified_suggestion"`) and optional Gemini header suggestion (`UNVERIFIED AI SUGGESTION` until explicit owner confirmation via `POST /api/standards/{id}/confirm`); cycle-free supersession chains (`validate_no_supersession_cycle`, `resolve_supersession_chain`) and `withdrawn`/`superseded` flagging across `Specifications`, `Calculations`, `TechnicalComparisons`, `ReviewReports`, and `ProjectSchedules`; Step 12 QA Agent integration catching cited superseded/withdrawn/unknown-edition/unconfirmed standards and codes absent from both `standards_library` and reviewed `ResearchSource` logs; bilingual Arabic RTL & English LTR DOCX, vector PDF, and live-formula XLSX register exports (`=COUNTIF`/`=SUM`); bilingual RTL/LTR **Standards Library** UI tab; `100 passed, 4 skipped` full backend `pytest -v`, `26 passed` frontend Vitest + `tsc --noEmit` + Vite build, and clean `gitleaks` check; owner live browser walkthrough and visual inspection of exported register files remain `PENDING`.)*
- **Branch:** `step-17-standards-library`
- **Depends on:** Step 16 (`5d6aca4`, PR `#25` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`0015_step17_standards_library.py`):**
   - Created `standards_library` (`StandardDocument` ORM model) storing `project_id` (nullable for global office library scope), `standard_number`, `title`, `issuing_body`, `edition_year` (default `"unknown"`), `status` (`CHECK IN ('current', 'superseded', 'withdrawn', 'unknown')`), `superseded_by_id` self-FK (`ON DELETE SET NULL`), `supersession_note`, `jurisdiction`, `adopted_locally`, `owner_notes`, `owner_excerpts_json`, `metadata_status`, `suggested_metadata_json`, `use_ai`, `ai_suggestion_status`, `tokens_used`, `token_usage_json`, immutable upload file metadata (`original_filename`, `file_relative_path`, `file_sha256`, `file_size_bytes`, `mime_type`), `version`, and `history_json`.
   - Verified reversible Alembic `upgrade` / `downgrade` round-trip (`3 passed` in `test_migrations.py`).

2. **Owner-Supplied Only, Excerpt Bound & Unconfirmed Suggestion Workflow (`backend/app/skills/standards.py`, `backend/app/services/standards.py`):**
   - **Zero Shipped Copyrighted Texts / Zero Model-Memory Fabrication:** No real standard texts, clause numbers, or edition years are bundled or invented; built-in presets (`GET /api/standards/presets`) use strictly synthetic `SYN-*` fixtures (`SYN-1000-2024`, `SYN-1000-2018`, `SYN-900-2010`).
   - **Strict 300-Char Excerpt Guard:** `OwnerExcerptIn` and `_normalize_excerpts` reject any excerpt exceeding `MAX_EXCERPT_CHARS = 300` (`HTTP 422`), requiring an explicit `page_ref`. Uploaded PDF/DOCX/TXT documents are saved read-only (`0444`) with verified SHA-256 hashes in `11_References/` or `_standards_library/` while transient bounded header extraction (`extract_bounded_header_text`, max `4000` chars) only reads headers via PyMuPDF / `python-docx` / UTF-8 without persisting full body prose.
   - **`0` AI Tokens Default + Explicit Owner Confirmation Gate:** Deterministic upload extraction defaults to `0` AI tokens and marks records `"unverified_suggestion"` (`UPLOADED_UNCONFIRMED_LABEL_EN/AR`); optional Gemini upload (`use_ai=true`) suggests header metadata only and tags `"unverified_ai_suggestion"` (`UNVERIFIED AI SUGGESTION`) until explicit owner sign-off (`POST /api/standards/{id}/confirm`).
   - **Search, Versioning & Supersession Chains:** Search over owner data only (`q`, `number`, `status`, `issuing_body`, `adopted_locally`); cycle-rejected supersession linking (`POST /api/standards/{id}/supersede` -> `HTTP 422` on cycles/self-links); cross-deliverable citation indexing (`find_citations_for_standard`) returning `where_cited` and `citation_warnings` wherever `superseded`, `withdrawn`, unknown-edition, or unconfirmed standards are referenced.

3. **Bilingual RTL/LTR Standards Register Export (`backend/app/services/standards_export.py`):**
   - Exports immutable versioned Arabic RTL & English LTR bundles into `11_References/` / `_standards_library/exports/` containing:
     - **DOCX:** Landscape register table, status highlights, permitted short owner excerpts (`<= 300` chars), file SHA-256 digests, and citation warnings.
     - **PDF:** Vector PDF rendered via PyMuPDF `Story` + Tahoma/LRI isolates with normalized searchable identifiers and clear copyright notice.
     - **XLSX:** Two worksheets (`Standards Register` / `سجل المعايير` with live `=COUNTIF(...)` and `=SUM(...)` summary rows + `Excerpts & Citations` / `المقتطفات والاستشهادات`), never exporting full copyrighted text.

4. **Step 12 QA Agent Integration (`backend/app/agents/qa_agent.py`, `backend/app/schemas/qa.py`):**
   - Added `inspected_standard_ids` to `QaContextIsolationReport` and `ctx.standards_library` inspection loader inside isolated QA context.
   - Flags `reference` findings whenever any deliverable (`Specifications`, `Calculations`, `TechnicalComparisons`, `ReviewReports`, `ProjectSchedules`) cites:
     1. A library standard marked `superseded` (showing replacement code when linked), `withdrawn`, `unknown` status/edition, or awaiting owner confirmation (`unconfirmed`/`unverified_ai_suggestion`); or
     2. An uppercase standard code (`STANDARD_CODE_DETECT_RE`) missing from both `standards_library` and the project's reviewed `ResearchSource` log.

5. **Bilingual RTL/LTR UI (`frontend/src/components/StandardsLibraryView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added **مكتبة المعايير (Standards) / Standards Library** tab (`initialTab="standards"`) with owner-data search & filters, synthetic `SYN-*` fixture loader, PDF/DOCX/TXT upload (`use_ai` off by default), unconfirmed metadata confirmation banner, manual standard entry, `<= 300` char excerpt editor with live counter, supersession linker & chain viewer, `where_cited` / warning table, version history, and AR/EN DOCX/PDF/XLSX register exporter.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0015_step17_standards_library.py`
- `<repo>/backend/app/api/standards.py`
- `<repo>/backend/app/schemas/standards.py`
- `<repo>/backend/app/services/standards.py`
- `<repo>/backend/app/services/standards_export.py`
- `<repo>/backend/app/skills/standards.py`
- `<repo>/backend/tests/test_standards.py`
- `<repo>/frontend/src/components/StandardsLibraryView.tsx`
- `<repo>/docs/reports/step-17.md`

### Changed
- `<repo>/backend/app/agents/qa_agent.py` *(added `ctx.standards_library` isolated loader, `inspected_standard_ids`, cited superseded/withdrawn/unknown/unconfirmed checks, and unregistered-code detection across deliverables)*
- `<repo>/backend/app/db/models.py` *(added `StandardDocument` ORM model and `Project.standards` relationship)*
- `<repo>/backend/app/main.py` *(registered `standards_router`)*
- `<repo>/backend/app/schemas/qa.py` *(added `inspected_standard_ids` to `QaContextIsolationReport`)*
- `<repo>/backend/tests/test_migrations.py` *(verified `standards_library` table & columns across Alembic upgrade/downgrade)*
- `<repo>/docs/DECISIONS.md` *(added `ADR-026`)*
- `<repo>/frontend/src/App.test.tsx` *(added Step 17 bilingual `StandardsLibraryView` SSR & API wrapper Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(wired `standards` tab & Step 17 subtitle)*
- `<repo>/frontend/src/api.ts` *(added Step 17 standards CRUD, upload, confirm, supersede, preset & export API wrappers)*
- `<repo>/frontend/src/types.ts` *(added Step 17 TypeScript interfaces & `inspected_standard_ids`)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Output (`0` AI Tokens)

Deterministic output from `app.skills.standards` using strictly fake `SYN-*` identifiers (`0` AI tokens, `0%` real standard body text or client data):

```text
PRESETS: ['SYN-1000-2024 (current)', 'SYN-1000-2018 (superseded)', 'SYN-900-2010 (withdrawn)']
CHAIN_1: ('SYN-1000-2024', 'Synthetic Electrical Distribution Panel Practice Baseline (Fake Fixture)', 'SYN-1000-2018 (2018) -> SYN-1000-2024 (2024) [current]')
DET_SUG: {'suggested_number': 'SYN-333-2022', 'suggested_title': 'Synthetic PDF Fire Pump Practice', 'suggested_issuing_body': 'Synthetic National Authority', 'suggested_edition_year': '2022', 'suggestion_origin': 'deterministic_file_header', 'requires_owner_confirmation': True}
```

## 4. Tests Run (Exact Observed Results & Secret Scan)

### Targeted Step 17 Checks (`-x -q`) & Full Backend Suite (`pytest -v`)
```text
> .\backend\.venv\Scripts\pytest.exe backend/tests/test_migrations.py -x -q
...                                                                      [100%]
3 passed in 7.99s

> .\backend\.venv\Scripts\pytest.exe backend/tests/test_standards.py -k test_step17_qa_agent_catches_cited_superseded_withdrawn_unknown_unconfirmed_and_uncited_standards -x -q
.                                                                        [100%]
1 passed, 2 deselected in 4.41s

> .\backend\.venv\Scripts\pytest.exe backend/tests/test_standards.py -k test_step17_api_upload_sha256_zero_tokens_ai_confirm_supersede_search_and_exports -x -q
.                                                                        [100%]
1 passed, 2 deselected in 4.22s

> .\backend\.venv\Scripts\pytest.exe backend/tests -v
================= 100 passed, 4 skipped in 191.41s (0:03:11) ==================
```
*(The 4 skipped tests are the pre-existing opt-in live tool/network tests `RUN_REAL_ODA`, `RUN_REAL_OCR`, `RUN_REAL_RESEARCH`; all 3 Step 17 test functions in `test_standards.py` — unit supersession/excerpt bounds/presets, TXT & PyMuPDF synthetic PDF upload + SHA-256 + 0-token/AI-confirm + copyright exclusion + EN/AR DOCX/PDF/XLSX exports, and QA reference defect traps — passed cleanly.)*

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)
```text
> cd frontend; npm.cmd test; npm.cmd run build
✓ src/App.test.tsx (26 tests) 96ms
Test Files  1 passed (1) | Tests  26 passed (26) | Duration  1.02s
tsc --noEmit && vite build -> 42 modules transformed -> built in 690ms
```

### Repo Hygiene & Secret Scan
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across `.py/.ts/.tsx/.md/.json`: `BOM_FILES: []`.
- Local-path check across `backend`, `frontend/src`, `docs`: `0` matches.
- `gitleaks detect --source . --no-banner -v`: clean on branch commit (`0` leaks found).

## 5. Decisions Made
- Recorded **`ADR-026`** in `<repo>/docs/DECISIONS.md` covering `standards_library` (`0015`), the `300`-character copyright excerpt limit, zero bundled/fabricated standard clauses or editions, deterministic/AI unconfirmed metadata suggestion gating, cycle-free supersession chains, bilingual DOCX/PDF/XLSX register exports, and Step 12 QA Agent reference audits.

## 6. Known Limitations & Owner Review Needed
1. **Live Browser & Register Visual Walkthrough (`PENDING` owner check):** Automated tests verify PyMuPDF PDF/TXT upload extraction, SHA-256 read-only storage, excerpt capping, supersession chains, QA citation traps, live Excel formulas (`=COUNTIF`/`=SUM`), zero copyright text leakage, and Vitest SSR rendering; opening the running UI and visually inspecting the exported DOCX/PDF/XLSX register files remains for the owner.
2. **Scoped Excerpt Extraction:** Uploaded PDF/DOCX/TXT documents are scanned only across initial header pages (`extract_bounded_header_text`) to propose unconfirmed metadata without indexing full copyrighted standard body text for search; full search operates solely over owner-entered metadata and short permitted excerpts (`<= 300` chars).

## 7. How to Test in the Running App
1. Ensure backend + frontend are running (`scripts\start.bat`, health `GET http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`).
2. Open **مكتبة المعايير (Standards) / Standards Library**, select a project, click **Fill Synthetic Preset** (or upload your own licensed PDF/DOCX/TXT standard with **Use AI** left off for `0` tokens), review unconfirmed metadata banners and click **Confirm Metadata**.
3. Register a supersession link between `SYN-1000-2018` (`superseded`) and `SYN-1000-2024` (`current`), cite `SYN-1000-2018` in a calculation, verify **Where Cited Across Deliverables** highlights the superseded usage and **Run QA Review** flags it under `reference`, then export the **Standards Register (DOCX + PDF + XLSX)**.

## 8. Checklist & Ready for Next Step?
- [x] Branch `step-17-standards-library` created cleanly from pulled `main` (`5d6aca4`)
- [x] Reversible migration `0015_step17_standards_library` (`down_revision = "0014"`) verified via Alembic round-trip test
- [x] Owner-supplied / licensed standards storage (PDF/DOCX/TXT read-only + SHA-256, `<= 300` char excerpts, zero shipped/fabricated clauses or editions)
- [x] Unconfirmed metadata suggestion (`0` AI tokens default) + optional `UNVERIFIED AI SUGGESTION` until explicit owner confirmation
- [x] Supersession & withdrawn flagging across all deliverable modules + cycle rejection (`422`) + QA Agent reference checks
- [x] Bilingual RTL/LTR UI tab + DOCX/PDF/live-formula XLSX register exports with SHA-256
- [x] `ADR-026` and `docs/reports/step-17.md` (`Status: PARTIAL`) written, tested (`100 passed, 4 skipped` backend + `26 passed` frontend), and `gitleaks` clean
- [ ] Owner visual UI & DOCX/PDF/XLSX register walkthrough (**Ready for owner review & PR to `main`**; push branch only, no merge)
