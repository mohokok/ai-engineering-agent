# Step 06 — Document, Spreadsheet, and Image Extraction

- **Date:** 2026-11-19
- **Status:** **PARTIAL** *(all automated backend, frontend, hygiene, secret scan, and opt-in real Tesseract `ara+eng` OCR checks passed; awaiting owner confirmation of the interactive browser UI visual check in `start.bat`)*
- **Branch:** `step-06-extraction-layer`
- **Depends on:** Step 05 (`966a183`, PR `#11` merged to `main` after `PASS step 05`)

## 1. Scope Done

### First Task (Before Step 06 Feature Work)
- **Tightened Orchestrator v0 assumption labelling (`<repo>/backend/app/agents/orchestrator.py`, `<repo>/backend/app/schemas/tasks.py`, `<repo>/backend/tests/test_tasks.py`):**
  - Updated `ORCHESTRATOR_V0_SYSTEM_PROMPT` and `OrchestratorUnderstanding.assumptions` so unprovided structural/engineering conditions (such as support boundary conditions like simply supported vs. continuous, material grades, occupancy type, or design defaults) are never phrased as engineering facts in `restated_assignment` or `assumptions`, and every assumption is explicitly labelled as requiring owner confirmation.
  - Enforced **prefix-only matching (`startswith`)** inside `_normalize_assumptions()` so markers appearing mid-sentence cannot suppress labelling (`"Assumption (to confirm with owner): ..."` / `"افتراض أولي يحتاج تأكيد المالك: ..."`), verified in `test_step05_assumptions_always_labelled_for_owner_confirmation`.

### Step 06 Extraction Layer & PR #12 Review Hardening
- **Installed & pinned Python extraction dependencies (`<repo>/backend/requirements.txt`):**
  - Pinned verified libraries in `backend/.venv`: `pymupdf==2.1`, `pdfplumber==0.11.10`, `python-docx==1.2.0`, `openpyxl==3.1.5`, `python-pptx==1.0.2`, `pillow==13.0.0`, `pytesseract==0.3.13`. (Did NOT auto-install any system binary.)
- **Database schema & migration (`<repo>/backend/alembic/versions/0005_step06_file_extractions.py`, `<repo>/backend/app/db/models.py`):**
  - Added `file_extractions` table (`FileExtraction` ORM model) storing versioned extraction runs (`file_id` `RESTRICT`, `project_id` `CASCADE`, `ck_file_extractions_classification_valid`, `uq_file_extractions_file_ver_run`), `counts_json`, `warnings_json`, `rendered_images_json`, `payload_json`, and `artifact_relative_path`.
- **Modular deterministic extractors (`<repo>/backend/app/services/extractors/`):**
  - **PDF (`<repo>/backend/app/services/extractors/pdf_and_image.py`):** Extracts vector text (`pdfplumber` with `pymupdf` fallback), vector tables (`pdfplumber`), renders `150 DPI` page PNG previews (`PDF_PREVIEW_DPI = 150`) into `03_Analysis/extractions/<file_id>/v<ver>/r<run>/pages/`, and triggers OCR fallback (`ara+eng`) on scanned/low-text pages (`< 15` non-whitespace chars) or when `force_ocr=True`. OCR ALWAYS renders a **dedicated separate bitmap at `300 DPI` (`PDF_OCR_RENDER_DPI = 300`)** — never reusing the `150 DPI` UI preview — and records `ocr_dpi` in both top-level extraction JSON/API responses and each `ocr_text` item.
  - **Single-probe Tesseract OCR & warning de-dup (`<repo>/backend/app/services/extractors/ocr.py`):** Probes Tesseract **once per extraction run** via `probe_tesseract()` checking in strict precedence: (1) `TESSERACT_CMD` (`Settings.tesseract_cmd`), (2) `PATH` (`shutil.which("tesseract")`), and (3) default Windows install folders (`<ProgramFiles>/Tesseract-OCR/tesseract.exe`, `<ProgramFiles(x86)>/Tesseract-OCR/tesseract.exe`), reusing the run-level `TesseractProbe` across every scanned page. Reports **`"not installed - pending owner"`** cleanly when absent, de-duplicates OCR warnings across multi-page PDFs (`seen_ocr_warnings`), and runs `ara+eng` `pytesseract.image_to_string` when present.
  - **DOCX (`<repo>/backend/app/services/extractors/office.py`):** Extracts body paragraphs and tables verbatim (`page_or_sheet`, `paragraph:<i>` / `table:<t>`) preserving Arabic/English text, decimals, units, and raw values alongside any normalized text/table matrix.
  - **XLSX (`<repo>/backend/app/services/extractors/office.py`):** Dual-loads Excel workbooks read-only (`data_only=False` + `data_only=True`) via `_SafeExcelReader` (guarding against `openpyxl==3.1.5` empty-rels `Chartsheet` crashes), skips chartsheets gracefully with a warning, calls `ws.reset_dimensions()` so stale/wrong XML `<dimension>` tags cannot truncate cells, warns on `hidden`/`veryHidden` sheets while still extracting cells, preserves **both** formulas (`=B2*C2`, `=SUM(...)`) and cached values (`number_format` fixed-decimal retention like `'0.00" m3"'` -> `"12.50"`), and records exact 1-based `row_numbers`, `start_row`, `start_column`, `start_column_letter`, and Excel range `location` (e.g., `range:C4:E7`).
  - **CSV (`<repo>/backend/app/services/extractors/office.py`):** Parses with `csv.reader(io.StringIO(text_content, newline=""))` (preserving quoted multi-line Arabic+units cells verbatim without `.splitlines()` corruption), tries `utf-8-sig`, `utf-8`, `cp1256`, `latin-1`, and records exact 1-based `row_numbers`, `start_row`, `start_column`, `start_column_letter`, and `range:...` coordinates.
  - **PPTX (`<repo>/backend/app/services/extractors/office.py`):** Extracts slide text frames, recursively flattened grouped shapes (`group:<g>/shape:<idx>` via `_iter_pptx_shapes`), shape tables, and presenter notes in slide order.
  - **Images (`<repo>/backend/app/services/extractors/pdf_and_image.py`):** Extracts Pillow format/dimensions/mode/DPI metadata read-only, warns explicitly on multi-frame TIFFs (`n_frames > 1`) that only frame 1 was extracted, and executes `ara+eng` OCR when available or marks `"not installed - pending owner"`.
- **Explicit Normalization & Raw Value Traceability:**
  - Every `ExtractedItem` records `normalization_applied` (`"verbatim"`, `"outer_whitespace_trimmed"`, `"cell_whitespace_collapsed"`, or `"excel_number_format_preserving_precision"`) and preserves the untouched raw value beside modified entries (`raw_text` for trimmed text blocks, `raw_uncollapsed_values` for whitespace-collapsed/trimmed tables), summarized at top level in `payload.normalization_policy`.
- **Orchestration integrity, run-dir isolation & API (`<repo>/backend/app/services/extraction.py`, `<repo>/backend/app/api/extraction.py`):**
  - Refuses HTTP `409 Conflict` if `03_Analysis/extractions/<file_id>/v<ver>/r<run>` already exists on disk (`run_dir.exists()` check + `mkdir(exist_ok=False)`), guaranteeing existing runs are never reused or overwritten.
  - Verifies `sha256_after == sha256_before` inside the failure-tracked `try` block before writing `extraction.json`; on hash mismatch, stores `FileExtraction(status="failed")` + `AuditLog(action="file.extraction_failed")` with both digests and returns HTTP `422`.
- **Frontend UI (`<repo>/frontend/src/components/ProjectFilesPanel.tsx`, `<repo>/frontend/src/types.ts`, etc.):**
  - Displays runtime Tesseract OCR capability status (`not installed - pending owner` vs `installed`), per-file **Extract Content / استخراج البيانات** action button, verified counts, `SHA-256` unchanged badge, warnings, PNG page preview links, normalized item table, and collapsible JSON output.

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
- `<repo>/backend/tests/fixtures/bilingual_engineering_sample.png`
- `<repo>/backend/tests/test_extraction.py`
- `<repo>/docs/reports/step-06.md`

### Changed
- `<repo>/backend/app/agents/orchestrator.py`
- `<repo>/backend/app/core/config.py`
- `<repo>/backend/app/db/models.py`
- `<repo>/backend/app/main.py`
- `<repo>/backend/app/schemas/tasks.py`
- `<repo>/backend/pytest.ini`
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

### Backend Default Suite (`.\.venv\Scripts\python.exe -m pytest -v` in `<repo>/backend`)
*(Runs hermetically without requiring `RUN_REAL_OCR=1`; skips only the opt-in live-Tesseract test `test_optin_real_tesseract_ara_eng_on_committed_fixture` unless opted in below.)*

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>/backend/.venv/Scripts/python.exe
cachedir: .pytest_cache
rootdir: <repo>/backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 43 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [  2%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [  4%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [  6%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [  9%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 11%]
tests/test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 13%]
tests/test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 16%]
tests/test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 18%]
tests/test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 20%]
tests/test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 23%]
tests/test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 25%]
tests/test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 27%]
tests/test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 30%]
tests/test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 32%]
tests/test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 34%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 37%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 39%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 41%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 44%]
tests/test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 46%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 48%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 51%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 53%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 55%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 58%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 60%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [ 62%]
tests/test_providers.py::test_keyring_secret_store_round_trip PASSED     [ 65%]
tests/test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 67%]
tests/test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 69%]
tests/test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 72%]
tests/test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 74%]
tests/test_providers.py::test_debug_logging_never_leaks_api_key PASSED   [ 76%]
tests/test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 79%]
tests/test_providers.py::test_provider_404_model_not_found_handling PASSED [ 81%]
tests/test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 83%]
tests/test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 86%]
tests/test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 88%]
tests/test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 90%]
tests/test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 93%]
tests/test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 95%]
tests/test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 97%]
tests/test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

======================= 42 passed, 1 skipped in 32.62s ========================
```

### Opt-In Real Tesseract OCR Evidence (Committed Non-Client Fixture)
*(Tesseract 5.5.3 installed by the owner in `<ProgramFiles>/Tesseract-OCR`, NOT on `PATH`; verified without modifying OS/PATH.)*

```text
> "<ProgramFiles>/Tesseract-OCR/tesseract.exe" --list-langs
List of available languages in "<ProgramFiles>/Tesseract-OCR/tessdata/" (3):
ara
eng
osd

> "<ProgramFiles>/Tesseract-OCR/tesseract.exe" --version
tesseract v5.5.3.20260724
 leptonica-1.87.0
```

Exact opt-in pytest command & real output against `<repo>/backend/tests/fixtures/bilingual_engineering_sample.png` and its scanned PDF wrapper:

```text
> cd <repo>/backend
> $env:RUN_REAL_OCR='1'; .\.venv\Scripts\python.exe -m pytest tests/test_extraction.py -k test_optin_real_tesseract_ara_eng_on_committed_fixture -v -s
collecting ... collected 10 items / 9 deselected / 1 selected

tests/test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PASSED
```

*(Full final-head `pytest` default + opt-in real-OCR, `vitest`, `node --test`, and `gitleaks` outputs on the committed head SHA are pasted in the Step 06 PR description and chat summary.)*

## 4. Acceptance Tests & Verification Evidence

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| Step 05 tightening: assumptions explicitly labelled via prefix only | **PASS** | `test_step05_assumptions_always_labelled_for_owner_confirmation` verifies `startswith` prefix matching so mid-sentence phrases (`to confirm with owner`, `تحتاج تأكيد المالك`) never bypass labelling |
| Test files for PDF, DOCX, XLSX, CSV, PPTX, images extracted with full traceability | **PASS** | `test_extract_pdf_text_tables_page_images_and_preserve_units`, `test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units`, `test_extract_csv_multiline_quoted_arabic_and_offset_traceability`, `test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden`, and `test_pptx_grouped_shapes_and_multiframe_tiff_warning` (`<repo>/backend/tests/test_extraction.py`) |
| XLSX `reset_dimensions()`, chartsheet safety, hidden sheets, CSV multi-line quotes, and off-A1 cell mapping | **PASS** | `test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden` verifies `<dimension ref="A1:A1"/>` bypass, `C4:E7` mapping, hidden sheet warning, and Chartsheet skip; `test_extract_csv_multiline_quoted_arabic_and_offset_traceability` verifies quoted multi-line Arabic+units cells (`StringIO(newline='')`) |
| Single Tesseract probe per run, warning de-dup, separate 300 DPI OCR render, and real opt-in `ara+eng` OCR | **PASS** | `test_tesseract_resolution_priority_single_probe_and_300dpi_render` proves 1 `--version` + 1 `--list-langs` call across a 3-page PDF + `ocr_dpi=300` (`~2x` preview dimensions); `test_optin_real_tesseract_ara_eng_on_committed_fixture` verifies live Tesseract `5.5.3` (`ara`, `eng`, `osd`) on `<repo>/backend/tests/fixtures/bilingual_engineering_sample.png` and scanned PDF |
| Hash mismatch failure logging, non-reuse of `r{n}` folders, and immutable read-only originals | **PASS** | `test_extraction_hash_mismatch_and_refuse_existing_run_dir` verifies `sha256_after != sha256_before` stores failed `FileExtraction` + `file.extraction_failed` `AuditLog` + HTTP `422` without writing `extraction.json`, and existing `r{n}` returns `409 Conflict` cleanly |
| Interactive owner UI check | **PENDING** | Awaiting owner visual confirmation in browser (`<repo>/scripts/start.bat`) |

## 5. Decisions Made (Recorded in `<repo>/docs/DECISIONS.md` as `ADR-012`)
- Enforced prefix-only (`startswith`) assumption normalization in `orchestrator.py`.
- Pinned Step 06 Python extraction dependencies in `requirements.txt`; probed external Tesseract once per extraction run via `probe_tesseract()`, kept 150 DPI UI previews separate from dedicated 300 DPI OCR renders (`ocr_dpi=300`), and de-duplicated per-run OCR warnings.
- Preserved raw-vs-normalized traceability (`normalization_applied`, `raw_text`, `raw_uncollapsed_values`), `csv.reader(io.StringIO(..., newline=''))`, `ws.reset_dimensions()`, `_SafeExcelReader`, and off-A1 cell coordinate fields (`row_numbers`, `start_row`, `start_column`, `start_column_letter`).
- Refused existing `r{n}` run directories (`409`) and persisted atomic `FileExtraction(status="failed")` + `file.extraction_failed` `AuditLog` on SHA-256 mismatch.

## 6. Deviations from the Plan and Why
- In addition to `.pdf`, `.docx`, `.xlsx`, `.csv`, `.pptx`, and raster images, plain `.txt` / `.md` files are handled deterministically line-by-line via `extract_plain_text`, while CAD/BIM extensions (`.dxf`, `.dwg`, `.ifc`, etc.) explicitly return HTTP `400` citing Step 07 instead of generic failure.
- Added runtime fallback probing of standard Windows install paths (`<ProgramFiles>/Tesseract-OCR/tesseract.exe`) alongside `PATH` and `TESSERACT_CMD` because on Windows freshly installed Tesseract binaries are frequently absent from `PATH`.

## 7. Accuracy Notes, Normalisation Disclosure, and Known Failures

### Exact Whitespace Normalisation Applied (Raw Values Kept Beside Modified Entries)
- **PDF, DOCX, and PPTX tables:** cell text collapses internal runs of whitespace/newlines via `" ".join(cell.split())` (`normalization_applied = "cell_whitespace_collapsed"`). Whenever collapsing alters any cell relative to raw extracted strings, `raw_uncollapsed_values` stores the untouched original matrix alongside `raw_values`.
- **CSV & text blocks (DOCX paragraphs, PPTX text frames & notes, PDF native body, OCR text, plain text):** only outer leading/trailing whitespace is trimmed via `.strip()` (`normalization_applied = "outer_whitespace_trimmed"`), keeping internal newlines/spacing intact (including multi-line quoted CSV cells). When trimming modifies a string or CSV table, `raw_text` or `raw_uncollapsed_values` preserves the unmodified raw content beside it.
- **XLSX cells:** formulas (`=SUM(...)`) and string cells are preserved verbatim (`verbatim_formula` / `excel_number_format_preserving_precision`); numeric values apply only fixed-decimal trailing-zero formatting from Excel `number_format` patterns like `0.00` without rounding away stored precision.

### Tesseract Runtime & Separate 300 DPI Render Observation on This PC
- Initially, Tesseract was absent and `detect_tesseract()` cleanly reported `'not installed - pending owner'`. After the owner installed `tesseract v5.5.3.20260724` with Arabic data (`ara`, `eng`, `osd`) in `<ProgramFiles>/Tesseract-OCR` (**NOT** on `PATH`), `probe_tesseract()` resolved `<ProgramFiles>/Tesseract-OCR/tesseract.exe` once per run via default-folder fallback after checking `TESSERACT_CMD` and `PATH`, without any OS or `PATH` changes.
- **150 DPI vs 300 DPI Scanned PDF Finding:** Running OCR on a **150 DPI** PDF preview PNG captured the English line (`Beam Span = 6.00 m | Load = 18.50 kN/m`) but dropped the Arabic line (`مشروع مستشفى طرابلس التعليمي`). `extract_pdf` now ALWAYS renders a **dedicated 300 DPI bitmap (`PDF_OCR_RENDER_DPI = 300`)** separate from the `150 DPI` `page_001.png` preview PNG and records `ocr_dpi: 300` in the extraction JSON and API response, enabling clean extraction of both Arabic and English text.
- **OCR Artifacts & Review Advisory:** Mixed RTL Arabic + LTR English text in Tesseract emits bidirectional Unicode markers (`U+200F` / `U+200E`) around the Arabic span. Low-DPI source images (`<= 200 DPI`) can still confuse characters such as `B1` vs `81`, so **OCR output should always be verified for critical engineering tags and dimensions**.
- When Tesseract is absent on a host, scanned PDFs/images record `status = "partial_ocr_unavailable"`, `ocr_status = "not installed - pending owner"`, retain `150 DPI` page PNG previews / image metadata, and emit one de-duplicated warning per run.

### Format-Specific Known Failures & Limits
- **DOCX (`extract_docx`):**
  - **Block ordering:** Extracts body `doc.paragraphs` first and `doc.tables` second rather than interleaved document XML order.
  - **Unsupported DOCX containers:** Section `headers`, `footers`, footnotes, endnotes, comments, DrawingML text boxes (`w:txbxContent`), and nested sub-tables inside table cells are **not** extracted.
  - **Merged table cells:** `python-docx` row iteration repeats merged cell text across each spanned column/row index rather than deduplicating spans.
- **PPTX (`extract_pptx`):**
  - **Grouped shapes:** Nested grouped shapes (`MSO_SHAPE_TYPE.GROUP`) are recursively extracted (`group:<g>/shape:<idx>`), while SmartArt diagrams, embedded chart objects/series, and slide-master background placeholders remain unextracted.
- **PDF hybrid pages (`extract_pdf`):**
  - Automatic OCR triggers only when selectable page text has fewer than `_MIN_NATIVE_PDF_CHARS_BEFORE_OCR` (`15`) non-whitespace characters unless `force_ocr=True`. A hybrid page combining `>= 15` chars of vector text (e.g., border title block) with an embedded scanned drawing/schedule extracts only the native text unless `force_ocr=True` is requested (the `150 DPI` PNG preview still renders the full visual page).
  - **Borderless PDF tables:** `pdfplumber` table detection relies on ruling lines/rects; borderless tabular text appears inside `page:N/body` plain text rather than `item_type = "table"`.
- **Multi-page TIFF (`extract_image`):**
  - Extracts metadata and runs OCR on **frame 1 only**; when `n_frames > 1`, an explicit warning (`Multi-frame TIFF/image detected (N frames); only frame 1 was extracted.`) is recorded and frames `2..N` are not extracted.
- **XLSX chartsheets, hidden sheets & merged cells (`extract_xlsx`):**
  - **Chartsheets:** Fixed `_SafeExcelReader` avoids the `openpyxl==3.1.5` `AttributeError` (`rels = []`) and skips chartsheet tabs gracefully with a warning (`no worksheet grid cells`).
  - **Hidden sheets:** `hidden` / `veryHidden` worksheets emit an explicit warning (`sheet_state=...`) and still extract their cell values.
  - **Merged cells:** Under `read_only=True`, `openpyxl` populates merged-cell values only in the top-left coordinate (leaving spanned sibling coordinates blank `""`) without emitting merge-span geometry metadata.
  - **Uncached Excel formulas:** Formula strings (`=SUM(...)`) are always preserved verbatim, reading `<v>` cached values when stored; workbooks saved without Excel recalculation report `cached_value: null` plus a warning without evaluating formulas in Python.
- **Corrupted files, hash mismatch & legacy/CAD formats:**
  - Corrupted inputs or mid-run `SHA-256` hash changes record `FileExtraction(status="failed")` + `file.extraction_failed` in `audit_log` (without writing `extraction.json`) and return HTTP `422 Unprocessable Content`. Pre-existing `r{n}` run directories refuse reuse/overwrite with HTTP `409 Conflict`.
  - Legacy binary `.doc` / `.xls` / `.ppt` and CAD/BIM (`.dxf`, `.dwg`, `.ifc`, `.rvt`) return HTTP `400` explaining conversion or Step 07 scope.

## 8. Questions or Items Needed from the Owner
- Visual check of the **Extract Content / استخراج البيانات** action button, normalized items table, PNG previews, and OCR status banner inside Project Files (`<repo>/scripts/start.bat`).
- Review the Step 06 fixes and reply `PASS step 06` when ready for Step 07 (DXF, DWG via ODA File Converter, IFC, and drawing previews).

## 9. How the Owner Can See / Try It
1. Launch `<repo>/scripts/start.bat` (runs Alembic migration `0005` cleanly at startup).
2. Open any project in **المشاريع والملفات / Projects & Files**, upload sample PDF / DOCX / XLSX / CSV / PPTX / PNG files.
3. Click **استخراج البيانات / Extract Content** on any supported file row to inspect counts, verified read-only `SHA-256` badge, formulas & values, PNG page links, and full normalized JSON (with `ocr_dpi` and raw-vs-normalized metadata).

## 10. Ready for Next Step?
**Pending owner UI visual confirmation (`PARTIAL`)** — all automated backend, frontend, hygiene, secret scan, and opt-in real Tesseract `ara+eng` OCR checks pass; awaiting owner confirmation in the UI and `PASS step 06` to proceed to Step 07.
