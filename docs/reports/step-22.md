# Step 22 — UI Redesign & Company Branding (`ALHARAM ALDAHABY` / `الهرم الذهبي`)

- **Date:** 2026-11-22
- **Status:** **PARTIAL** *(Automated asset byte-identity `SHA-256` checks, all DOCX/PDF/XLSX/DXF/QA/Backup export branding assertions across Steps 09–19 + QA, full backend pytest suite `114 passed, 4 skipped`, frontend Vitest `33 passed` + `tsc --noEmit` + Vite production build `688ms`, Node UTF-8/no-local-path checks `6 passed`, and Gitleaks `no leaks found` completed cleanly. Live browser RTL/LTR visual sign-off and interactive desktop inspection of generated Word/PDF/Excel/CAD files remain `PENDING` for owner review.)*
- **Branch:** `step-22-ui-branding`
- **Depends on:** Step 21 (`4a007bf`, PR `#30` merged)

## 1. Scope Implemented

1. **Single Branding Source of Truth & Byte-Identical Assets:**
   - Created [backend/app/core/branding.py](../../backend/app/core/branding.py) and [frontend/src/branding.ts](../../frontend/src/branding.ts) holding exact corporate names:
     - **English:** `ALHARAM ALDAHABY` / `Engineering Consultancy`
     - **Arabic:** `الهرم الذهبي` / `للاستشارات الهندسية`
     - **Palette Tokens:** Dark brown `#5A3A1A`, deep brown `#432A12`, gold `#E0AE1B`, warm off-white `#FAF7F0`, warm surface `#F4EFE4`, warm border `#E2D6BE`.
   - Preserved the owner-supplied [frontend/public/branding/logo.jpg](../../frontend/public/branding/logo.jpg) unmodified (`1193 x 210` RGB JPEG, `53,527` bytes) and copied it byte-for-byte to [backend/app/assets/branding/logo.jpg](../../backend/app/assets/branding/logo.jpg) (`SHA-256: 6df04a1c4b4337063372d7bd3cc9ce2eb84f5f0d13cbe7410fb5858243043cca`).
2. **Whole React UI Redesign (`frontend/`):**
   - Updated [frontend/index.html](../../frontend/index.html) with corporate favicon (`/branding/logo.jpg`) and bilingual title.
   - Rebuilt [frontend/src/index.css](../../frontend/src/index.css) around one centralized `:root` CSS variable token system derived from the logo palette, local/system Arabic-readable font stacks (`"Cairo", "Tajawal", "Noto Naskh Arabic", Tahoma, "Segoe UI", Arial, sans-serif` — zero remote font CDN links), accessible gold focus rings, refined cards/tables/forms/dropzones/badges/empty/loading/error panels, responsive breakpoints, and an executive footer.
   - Upgraded [frontend/src/App.tsx](../../frontend/src/App.tsx) with directional corporate header lockup (logo rendered at inline-start: **right** in Arabic RTL, **left** in English LTR), bilingual company identity alongside page title/subtitle, prominent `Preliminary` badge, grouped horizontally scrollable `.nav-tabs` (`Workspace`, `Engineering`, `QA & Governance`, `System`), synced `document.title`, and all existing test IDs, API calls, and tab labels intact.
3. **One Shared Branding Helper Per Output Format ([backend/app/services/branding_exports.py](../../backend/app/services/branding_exports.py)):**
   - **DOCX (`apply_docx_branding`):** Adds directional header table (inline-start logo + bilingual company identity + gold `#E0AE1B` underline) and classification footer without injecting `<w:bidi>` onto English LTR documents.
   - **PDF (`write_branded_story_pdf`, `stamp_pdf_branding`):** Expands page margins above/below Story flows (`60-62pt` top, `40-42pt` bottom) and stamps reused corporate logo XObject + Tahoma/HarfBuzz-shaped Arabic & English header strip + classification and `Page X of Y` / `صفحة X من Y` footer across every page (`compact=True` outer-margin stamping for true-scale CAD 2-page PDFs).
   - **XLSX (`apply_xlsx_branding`):** Preserves existing worksheet counts, merged blocks, row indices (`A1:H4` / Row 6 BOQ formulas), and `qa_agent.py` arithmetic checks with zero upward row shifts; embeds `logo.jpg` on Row 1 right of used columns, sets `oddHeader` & `oddFooter`, writes bilingual company identity on Row 2 right column, and appends the classification footer in column 1 at `ws.max_row + 2`.
   - Wired across all existing document generators (`report_generator.py`, `boq_export.py`, `calc_export.py`, `spec_export.py`, `comparison_export.py`, `planning_export.py`, `standards_export.py`, `specialist_export.py` serving Steps 18 & 19, `parametric_cad.py` DXF + PDF) and `services/backup.py` (`manifest.json` `"branding"` bilingual company block + logo `SHA-256` + classification disclaimer).
4. **Branded Independent QA Review Export (`POST /api/qa-reviews/{review_id}/export`):**
   - Added [backend/app/services/qa_export.py](../../backend/app/services/qa_export.py), extended [backend/app/schemas/qa.py](../../backend/app/schemas/qa.py), [backend/app/services/qa.py](../../backend/app/services/qa.py), [backend/app/api/qa.py](../../backend/app/api/qa.py), and wired UI export controls (`Export Branded QA Report (DOCX + PDF)` + SHA-256 download links) into [frontend/src/components/QaIssuesView.tsx](../../frontend/src/components/QaIssuesView.tsx) reusing `Deliverable` (`08_Reports/`, `0` AI tokens, zero database schema migration).

## 2. Files Created & Changed

### Created
- `backend/app/assets/branding/logo.jpg`
- `backend/app/core/branding.py`
- `backend/app/services/branding_exports.py`
- `backend/app/services/qa_export.py`
- `backend/tests/test_branding.py`
- `frontend/public/branding/logo.jpg` *(owner-supplied pre-existing untracked asset, kept byte-identical)*
- `frontend/src/branding.ts`
- `docs/reports/step-22.md`

### Changed
- `backend/app/api/qa.py`
- `backend/app/schemas/qa.py`
- `backend/app/services/backup.py`
- `backend/app/services/boq_export.py`
- `backend/app/services/calc_export.py`
- `backend/app/services/comparison_export.py`
- `backend/app/services/parametric_cad.py`
- `backend/app/services/planning_export.py`
- `backend/app/services/qa.py`
- `backend/app/services/report_generator.py`
- `backend/app/services/spec_export.py`
- `backend/app/services/specialist_export.py`
- `backend/app/services/standards_export.py`
- `docs/DECISIONS.md` *(appended `ADR-031`)*
- `frontend/index.html`
- `frontend/src/App.test.tsx`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/components/QaIssuesView.tsx`
- `frontend/src/index.css`
- `frontend/src/types.ts`

*(Zero changes to `.github/`, `CLAUDE.md`, or `backend/alembic/`; untracked extra `frontend/branding/` left unstaged outside git history.)*

## 3. Verification Results (Observed Tool Output)

### Backend Branding Suite (`test_branding.py -x -q`)
```text
.\backend\.venv\Scripts\pytest.exe backend/tests/test_branding.py -x -q
...                                                                      [100%]
3 passed in 7.55s
```

### Full Backend Regression Suite (`pytest -v`)
```text
.\backend\.venv\Scripts\pytest.exe backend/tests -v
================= 114 passed, 4 skipped in 254.47s (0:04:14) ==================
```
- The `4` skipped tests are pre-existing opt-in external binary/network tests:
  - `test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf`
  - `test_drawings.py::test_optin_real_oda_step11_parametric_dxf_roundtrip`
  - `test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture`
  - `test_research.py::test_optin_real_live_controlled_research_no_client_data`

### Frontend Vitest, TypeScript & Vite Production Build
```text
npm.cmd --prefix frontend test -- --run
 ✓ src/App.test.tsx (33 tests) 133ms
 Test Files  1 passed (1) | Tests  33 passed (33) | Duration  1.11s

npm.cmd --prefix frontend run build
 tsc --noEmit && vite build
 ✓ 46 modules transformed -> dist/assets/index-*.css (12.12 kB) + dist/assets/index-*.js (512.10 kB) -> built in 688ms
```

### Repository Hygiene, Dependencies & Secret Scan
- `.\backend\.venv\Scripts\python.exe -m pip check`: `No broken requirements found.`
- `git diff main -- .github CLAUDE.md backend/alembic`: empty (`0` unintended edits).
- `node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs`: `6 passed, 0 failed` (and re-run cleanly right after writing docs/committing).
- `gitleaks detect --source . --no-banner -v`: executed across git history on repo after final commit (`0` leaks found).

## 4. Remaining Manual Owner Verification (`PENDING`)

1. Open `http://127.0.0.1:5173/` and visually inspect the redesigned warm-cream/brown/gold UI in both **Arabic (`RTL`)** and **English (`LTR`)** across wide desktop and narrow laptop/tablet viewports (header logo edge placement, scrollable grouped tabs, focus outlines, table contrast, favicon).
2. Export sample reports across Steps 09–19 and QA Review and visually inspect opened files in Microsoft Word, Adobe Acrobat/Edge PDF Viewer, Microsoft Excel (Confirming print preview headers/footers and live formulas), and CAD viewer (DXF title block).
