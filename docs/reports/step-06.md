# Step 06 — Document, Spreadsheet, and Image Extraction

- **Date:** 2026-11-19
- **Status:** **COMPLETE** *(automated suite passed for all extractors, OCR fallback, immutability checks, and UI integration; interactive browser visual check noted for owner review)*
- **Branch:** `step-06-extraction-layer`
- **Depends on:** Step 05 (`966a183`, PR `#11` merged to `main` after `PASS step 05`)

## 1. Scope Done

### First Task (Before Step 06 Feature Work)
- **Tightened Orchestrator v0 assumption labelling (`<repo>/backend/app/agents/orchestrator.py`, `<repo>/backend/app/schemas/tasks.py`, `<repo>/backend/tests/test_tasks.py`):**
  - Updated `ORCHESTRATOR_V0_SYSTEM_PROMPT` and `OrchestratorUnderstanding.assumptions` so unprovided structural/engineering conditions (such as support boundary conditions like simply supported vs. continuous, material grades, occupancy type, or design defaults) are never phrased as engineering facts in `restated_assignment` or `assumptions`, and every assumption is explicitly labelled as requiring owner confirmation.
  - Added deterministic `_normalize_assumptions()` normalization inside `normalize_orchestrator_understanding()` ensuring unlabelled English or Arabic assumptions are prefixed (`"Assumption (to confirm with owner): ..."` / `"افتراض أولي يحتاج تأكيد المالك: ..."`), verified in `test_step05_assumptions_always_labelled_for_owner_confirmation`.

### Step 06 Extraction Layer
- **Installed & pinned Python extraction dependencies (`<repo>/backend/requirements.txt`):**
  - Pinned verified libraries in `backend/.venv`: `pymupdf==2.1`, `pdfplumber==0.11.10`, `python-docx==1.2.0`, `openpyxl==3.1.5`, `python-pptx==1.0.2`, `pillow==13.0.0`, `pytesseract==0.3.13`. (Did NOT auto-install any system binary.)
- **Database schema & migration (`<repo>/backend/alembic/versions/0005_step06_file_extractions.py`, `<repo>/backend/app/db/models.py`):**
  - Added `file_extractions` table (`FileExtraction` ORM model) storing versioned extraction runs (`file_id` `RESTRICT`, `project_id` `CASCADE`, `ck_file_extractions_classification_valid`, `uq_file_extractions_file_ver_run`), `counts_json`, `warnings_json`, `rendered_images_json`, `payload_json`, and `artifact_relative_path`.
- **Modular deterministic extractors (`<repo>/backend/app/services/extractors/`):**
  - **PDF (`<repo>/backend/app/services/extractors/pdf_and_image.py`):** Extracts vector text (`pdfplumber` with `pymupdf` fallback), vector tables (`pdfplumber`), renders 150 DPI page PNG previews into `03_Analysis/extractions/<file_id>/v<ver>/r<run>/pages/`, and triggers OCR fallback (`ara+eng`) automatically on scanned/low-text pages (`< 15` non-whitespace chars) or when `force_ocr=True`.
  - **Tesseract OCR detection & fallback (`<repo>/backend/app/services/extractors/ocr.py`):** Probes `TESSERACT_CMD` (`Settings.tesseract_cmd`), `PATH` (`shutil.which("tesseract")`), and standard Windows install locations without modifying the OS or installing binaries. Reports **`"not installed - pending owner"`** cleanly when absent (returning `"partial_ocr_unavailable"` with full page PNGs / image metadata rather than failing), and runs `ara+eng` `pytesseract.image_to_string` when installed.
  - **DOCX (`<repo>/backend/app/services/extractors/office.py`):** Extracts paragraphs and tables verbatim (`page_or_sheet`, `paragraph:<i>` / `table:<t>`) preserving Arabic/English text, decimals, and units.
  - **XLSX & CSV (`<repo>/backend/app/services/extractors/office.py`):** Dual-loads Excel workbooks read-only (`data_only=False` + `data_only=True`) preserving **both** exact formulas (`=B2*C2`, `=SUM(...)`) and cached values without rounding or recalculating, plus `number_format` hints (e.g., `'0.00" m3"'` preserves `"12.50"`). Decodes CSV files (`utf-8-sig`, `utf-8`, `cp1256`, `latin-1`) preserving string decimals and units verbatim.
  - **PPTX (`<repo>/backend/app/services/extractors/office.py`):** Extracts slide titles/text frames, shape tables, and speaker notes with exact `slide:<n>` and shape/table/notes locations.
  - **Images (`<repo>/backend/app/services/extractors/pdf_and_image.py`):** Extracts Pillow format/dimensions/mode/DPI metadata read-only and executes `ara+eng` OCR when available or marks `"not installed - pending owner"`.
- **Orchestration service & API (`<repo>/backend/app/services/extraction.py`, `<repo>/backend/app/api/extraction.py`, `<repo>/backend/app/schemas/extraction.py`, `<repo>/backend/app/main.py`):**
  - Added `GET /api/extraction/capabilities`, `POST /api/files/{file_id}/extract`, `GET /api/files/{file_id}/extractions`, `GET /api/extractions/{extraction_id}`, and `GET /api/extractions/{extraction_id}/pages/{page_number}`.
  - Verifies `sha256_before == sha256_after` on every extraction run, never alters read-only originals, saves immutable versioned artifacts in `03_Analysis`, and logs `file.extracted` / `file.extraction_failed` in `audit_log`.
- **Frontend UI (`<repo>/frontend/src/components/ProjectFilesPanel.tsx`, `<repo>/frontend/src/api.ts`, `<repo>/frontend/src/types.ts`, `<repo>/frontend/src/App.tsx`):**
  - Displays runtime Tesseract OCR capability status (`not installed - pending owner` vs `installed`), adds per-file **Extract Content / استخراج البيانات** action button, renders verified structural counts, SHA-256 unchanged confirmation, warnings, PNG page preview links, normalized item table, and collapsible JSON output.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0005_step06_file_extractions.py`
- `<repo>/backend/app/api/extraction.py`
- `<repo>/backend/app/schemas/extraction.py`
- `<repo>/backend/app/services/extraction.py`
- `<repo>/backend/app/services/extractors/__init__.py`
- `<repo>/backend/app/services/extractors/ocr.py`
- `<repo>/backend/app/services/extractors/office.py`
- `<repo>/backend/app/services/extractors/pdf_and_image.py`
- `<repo>/backend/tests/test_extraction.py`
- `<repo>/docs/reports/step-06.md`

### Changed
- `<repo>/backend/app/agents/orchestrator.py`
- `<repo>/backend/app/core/config.py`
- `<repo>/backend/app/db/models.py`
- `<repo>/backend/app/main.py`
- `<repo>/backend/app/schemas/tasks.py`
- `<repo>/backend/requirements.txt`
- `<repo>/backend/tests/test_migrations.py`
- `<repo>/backend/tests/test_tasks.py`
- `<repo>/docs/DECISIONS.md` (`ADR-012`)
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/frontend/src/App.tsx`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/components/ProjectFilesPanel.tsx`
- `<repo>/frontend/src/types.ts`

## 3. Tests Run

### Backend (`pytest -v` in `<repo>/backend`)
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>/backend/.venv/Scripts/python.exe
cachedir: .pytest_cache
rootdir: <repo>/backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 37 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [  2%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [  5%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [  8%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 10%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 13%]
tests/test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 16%]
tests/test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 18%]
tests/test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 21%]
tests/test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 24%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 27%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 29%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 32%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 35%]
tests/test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 37%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 40%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 43%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 45%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 48%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 51%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 54%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [ 56%]
tests/test_providers.py::test_keyring_secret_store_round_trip PASSED     [ 59%]
tests/test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 62%]
tests/test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 64%]
tests/test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 67%]
tests/test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 70%]
tests/test_providers.py::test_debug_logging_never_leaks_api_key PASSED   [ 72%]
tests/test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 75%]
tests/test_providers.py::test_provider_404_model_not_found_handling PASSED [ 78%]
tests/test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 81%]
tests/test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 83%]
tests/test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 86%]
tests/test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 89%]
tests/test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 91%]
tests/test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 94%]
tests/test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 97%]
tests/test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

============================= 37 passed in 26.74s =============================
```

### Frontend (`npm.cmd test` & `npm.cmd run build` in `<repo>/frontend`)
```text
> ai-engineering-agent-frontend@0.1.0 test
> vitest run

 RUN  v2.1.9 <repo>/frontend

 ✓ src/App.test.tsx (12 tests) 26ms

 Test Files  1 passed (1)
      Tests  12 passed (12)
   Duration  476ms (transform 116ms, setup 0ms, collect 167ms, tests 26ms, environment 0ms, prepare 84ms)

> ai-engineering-agent-frontend@0.1.0 build
> tsc --noEmit && vite build

vite v6.4.6 building for production...
transforming...
✓ 32 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-VNk5qLDz.css    5.80 kB │ gzip:  1.68 kB
dist/assets/index-CRkxhDCM.js   209.49 kB │ gzip: 63.05 kB
✓ built in 435ms
```

### Repository Hygiene (`<repo>`)
```text
node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs
✔ no committed text file leaks local user home paths (Rule 12a) (54.1895ms)
✔ no committed file (including binaries) is tracked inside /workspaces/ (Rule 12a) (26.7165ms)
✔ local user path detector catches other drive letters ([A-Za-z]:\Users\) (0.2ms)
✔ /workspaces/ detector flags tracked binary and text workspace paths (0.1675ms)
✔ all committed text files are valid UTF-8 without BOM (49.3583ms)
✔ Arabic sample file is tracked and decodes as valid UTF-8 with Arabic script (28.3915ms)
ℹ tests 6
ℹ pass 6
ℹ fail 0
```

*(Full final-head `pytest -v`, `vitest`, `node --test`, and `gitleaks` outputs on the committed head SHA are pasted in the Step 06 PR description and chat summary.)*

## 4. Acceptance Tests & Verification Evidence

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| Step 05 tightening: assumptions explicitly labelled to confirm with owner | **PASS** | `test_step05_assumptions_always_labelled_for_owner_confirmation` verifies `ORCHESTRATOR_V0_SYSTEM_PROMPT` prohibition on unstated support conditions and automatic `"Assumption (to confirm with owner):"` / `"افتراض أولي يحتاج تأكيد المالك:"` labelling |
| Test files for PDF, DOCX, XLSX, CSV, PPTX, images extracted to normalized JSON with `source_file`, `page_or_sheet`, `location` | **PASS** | `test_extract_pdf_text_tables_page_images_and_preserve_units` & `test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units` (`<repo>/backend/tests/test_extraction.py`) |
| Extracted counts match manually verified counts; numbers & units preserved verbatim | **PASS** | PDF: `pages=2, rendered_page_images=2, tables=1, text_items=2, total_items=3` (`6.00 m`, `18.50 kN/m`, `1250.00 kN`); DOCX: `text_items=2, tables=1`; XLSX: `sheets=2, tables=2, formulas=3` preserving `12.50`, `=B2*C2`, cached `3125`; CSV preserved `"6.00 m"`, `"0.005 m3"`, `1250.50`; PPTX: `slides=2, tables=1, slide_note` |
| Absent Tesseract reported cleanly (`'not installed - pending owner'`) without attempting installation; OCR fallback (`ara+eng`) checked | **PASS** | `test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract` hermetically proves absent detection returns `"not installed - pending owner"` and scanned PDFs/images return `"partial_ocr_unavailable"`; both injected `ara+eng` OCR callback and live `tesseract v5.5.3.20260724` (`ara`, `eng`, `osd`) read `"Beam Span = 6.00 m | Load = 18.50 kN/m"` + `"مشروع مستشفى طرابلس التعليمي"` verbatim |
| Extraction never alters original read-only files | **PASS** | Verified `sha256_before == sha256_after`, `original_unchanged: true`, OS read-only bit preserved, and versioned outputs saved only under `03_Analysis/extractions/...` |

## 5. Decisions Made (Recorded in `<repo>/docs/DECISIONS.md` as `ADR-012`)
- Tightened Orchestrator v0 assumption prefix normalization in code and prompt.
- Pinned Step 06 Python extraction dependencies in `requirements.txt` while strictly keeping OS binaries (Tesseract) external-only with explicit `'not installed - pending owner'` reporting when absent.
- Stored versioned normalized extraction artifacts in both `file_extractions` (`0005_step06_file_extractions`) and `03_Analysis/extractions/<file_id>/v<ver>/r<run>/` with `sha256_before == sha256_after` runtime verification.

## 6. Deviations from the Plan and Why
- In addition to `.pdf`, `.docx`, `.xlsx`, `.csv`, `.pptx`, and raster images, plain `.txt` / `.md` files are handled deterministically line-by-line via `extract_plain_text`, while CAD/BIM extensions (`.dxf`, `.dwg`, `.ifc`, etc.) explicitly return HTTP `400` citing Step 07 instead of generic failure.
- Added runtime fallback probing of standard Windows install paths (`<ProgramFiles>/Tesseract-OCR/tesseract.exe`) alongside `PATH` and `TESSERACT_CMD` because on Windows freshly installed Tesseract binaries may not yet be present on a running shell's `PATH`.

## 7. Accuracy Notes and Known Failures

### Tesseract Runtime Observation on This PC
- Initial probe reported Tesseract absent (`'not installed - pending owner'`); subsequently, `tesseract v5.5.3.20260724` (`ara`, `eng`, `osd`) appeared in `<ProgramFiles>/Tesseract-OCR/tesseract.exe` (installed externally, not on `PATH` and not installed by the agent). When invoked on a 250 DPI Tahoma-rendered bilingual engineering image, Tesseract read both `Beam Span = 6.00 m | Load = 18.50 kN/m` and `مشروع مستشفى طرابلس التعليمي` cleanly. Note that on lower-DPI (200 DPI) or tight sans-serif glyphs, OCR can misread similar characters (`B1` vs `81`), so **OCR output should always be verified for critical engineering tags and dimensions**.
- If a scanned PDF/image is extracted on a host where Tesseract is not installed, extraction does not fail; it records `status = "partial_ocr_unavailable"`, `ocr_status = "not installed - pending owner"`, preserves rendered page PNG previews and image metadata, and emits an explicit warning.

### Format-Specific Extraction Limits & Failure Handling
- **Borderless PDF tables:** `pdfplumber`'s default table extractor relies primarily on ruling lines/rects; borderless tabular text may be captured in `page:N/body` plain text rather than `item_type = "table"` (`total` table count depends on explicit table grid lines).
- **Excel uncached formulas:** `openpyxl` preserves exact formula strings (`=SUM(...)`), and reads cached values (`<v>`) when present; workbooks saved programmatically without Excel recalculation report `cached_value: null` plus a warning rather than attempting to evaluate formulas via Python.
- **Corrupted files:** Invalid/corrupt files log a `FileExtraction(status="failed")` record and `file.extraction_failed` audit event and return HTTP `422 Unprocessable Content`.
- **Legacy Office & CAD/BIM:** Binary `.doc` / `.xls` / `.ppt` and CAD/BIM (`.dxf`, `.dwg`, `.ifc`, `.rvt`) return HTTP `400` explaining conversion or Step 07 scope.

## 8. Questions or Items Needed from the Owner
- Visual check of the **Extract Content / استخراج البيانات** action button, normalized items table, PNG previews, and OCR status banner inside Project Files (`<repo>/scripts/start.bat`).
- Review the Step 06 PR and reply `PASS step 06` when ready for Step 07 (DXF, DWG via ODA File Converter, IFC, and drawing previews).

## 9. How the Owner Can See / Try It
1. Launch `<repo>/scripts/start.bat` (runs Alembic migration `0005` cleanly at startup).
2. Open any project in **المشاريع والملفات / Projects & Files**, upload sample PDF / DOCX / XLSX / CSV / PPTX / PNG files.
3. Click **استخراج البيانات / Extract Content** on any supported file row to inspect counts, verified read-only `SHA-256` badge, formulas & values, PNG page links, and full normalized JSON.

## 10. Ready for Next Step?
**Yes** — Step 06 scope is complete, tested across all target document/spreadsheet/presentation/image formats and OCR paths, and ready for Step 07 upon owner review and merge of this PR.
