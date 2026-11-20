# Step 09 — Document & Drawing Review -> Findings Report (DOCX + PDF, RTL/LTR, Deliverables)

- **Date:** 2026-11-20
- **Status:** **PARTIAL** *(Step 09 implementation + Step 06 Arabic PDF fix + Step 09B report-honesty fixes on `step-09b-report-honesty`; area-bearing CAD groups labelled `"geometric sum, not net building area"`, confirmed/raw unit consistency without `"None"`, doubtful CAD `area_m2=null` + `HIGH` finding, `>1%` DXF/DWG reconciliation withholding conflicting areas, unverified OCR text separated from `verified_facts`, zero deterministic boilerplate + `Document Register` + `"inventory & check, NOT an engineering review"` notice, `"Showing N of M verified facts"` + `Appendix A` + full JSON, `70 passed, 3 skipped` backend pytest, `3/3` opt-in real ODA/OCR/research checks, and `18 passed` frontend Vitest/Vite build; live owner inspection on real hospital project files and desktop Microsoft Word rendering remain `PENDING`)*
- **Branch:** `step-09b-report-honesty` *(following merged Step 09 PR `#16` at `9ab7e65`)*
- **Depends on:** Step 08 (`3afe6e9`, PR `#15` merged), Step 09 (`9ab7e65`, PR `#16` merged)

## 1. Scope Done

### Step 06 Addition Fix (Small Commit `799b5d4` — Short Note)
Real Arabic PDFs revealed two Step 06 extractor gaps fixed cleanly before continuing Step 09 (using strictly synthetic test fixtures generated in code, zero client files):
1. **Unreliable Native Arabic / `(cid:N)` Detection (`assess_native_pdf_text_reliability` in `pdf_and_image.py`):** Native PDF text containing `(cid:N)` placeholders or reversed visual-order common Arabic words (`يف`, `نم`, `ىلع`, `ىلإ`, `ىلا` outnumbering `في`, `من`, `على`, `إلى`, `الى` after NFKC/tashkeel normalization) is flagged `native_text_unreliable=True` with raw native text retained in `raw_native_text`, routed to 300 DPI `ara+eng` OCR, and reported as `ocr_status="ocr_applied (native text unreliable)"` (never `not_needed`; reports `partial_ocr_unavailable` if Tesseract is unavailable). Notice in our opt-in real OCR check below that PyMuPDF/pdfplumber turned `<p dir='rtl'>في من على إلى مشروع مستشفى</p>` into `'ىفشتسم عورشم ى(cid:452)إ ى(cid:449)ع نم يف'`, which the check caught and live Tesseract `5.5.3` recovered cleanly as `'في من على إلى مشروع مستشفى طرابلس التعليمي'` (`mean_conf=93.88`).
2. **Full Page Reconciliation & Per-Page Tesseract Confidence (`ocr.py`, `pdf_and_image.py`, `ProjectFilesPanel.tsx`):** Every page `1..N` emits a page-level item carrying an explicit `page_status` (`text`, `ocr_text`, `ocr_empty_or_blank`, `failed`) with per-page OCR exceptions caught cleanly rather than dropping blank/failed pages (`12` pages -> `12` page items reconciled in `page_reconciliation`), computes mean Tesseract word confidence via `pytesseract.image_to_data`, flags pages `< 65%` as `ocr_low_confidence=True`, and renders blank, failed, unreliable, and low-confidence pages explicitly in `ProjectFilesPanel.tsx`.

### Step 09 — Review Report & Deliverables
1. **Database Schema & Reversible Migration (`backend/app/db/models.py`, `backend/alembic/versions/0007_step09_review_reports.py`):**
   - Added `ReviewReport` (`review_reports`) with strict Step 02 five-label `classification` `CHECK` constraint, `version`, `revision`, `language` (`ar` | `en`), `findings_json`, `structured_payload_json`, `estimated_prompt_tokens`, `token_usage_json`, and `error_message`.
   - Extended `Deliverable` (`deliverables`) with `report_id`, `folder_name`, `filename`, `relative_path`, `mime_type`, `size_bytes`, and `sha256` for integrity-verified tracking across `08_Reports` and `10_Final_Deliverables`.

2. **Orchestrator + `review` Skill & Verified-Text Gate (`backend/app/skills/review.py`, `backend/app/schemas/reports.py`):**
   - Collects deterministic extractions (`FileExtraction` records including `cad_dxf`, `bim_ifc`, PDF pages/tables/OCR, DOCX/XLSX formulas & cells, CSV, PPTX, and image OCR) plus reviewed internet research logs (`ResearchSource` rows where `reviewed == True`). Inaccessible/blocked sources (`HTTP 403`, login walls, `not_relevant`) stay excluded from `source_registry` and appear in `gaps_or_unextracted`.
   - **Step 09 PDF/OCR Reliability Gate:** `collect_project_evidence_index` filters out any item with `page_status` in `{"failed", "ocr_empty_or_blank"}`, un-OCR'd `native_text_unreliable`, failing `assess_native_pdf_text_reliability(text)`, or `ocr_low_confidence=True` so Step 09 `findings`, `verified_facts`, and Gemini synthesis prompts ONLY cite text that passed the check (recording excluded/blank/failed/low-confidence pages in `gaps_or_unextracted` and a `needs_verification` Document Control finding).
   - **Mandatory Source Links:** Every `ReviewFinding` and `verified_fact` requires at least one validated `SourceLocationRef` (`EXT-*` or `RES-*`, enforced via Pydantic `min_length=1` and post-LLM filtering that drops any hallucinated finding/fact referencing non-existent IDs).
   - **Strict Category Separation:** Separates outputs cleanly into **Verified Facts**, **Calculated Values** (Python deterministic calculations and Excel formula inspection only — never LLM arithmetic; doubtful `$INSUNITS` CAD files keep `area_m2 = null` and raise a `high`-severity `needs_verification` finding), **Assumptions (To Confirm With Owner)** (always prefixed cleanly in Arabic or English), and **Recommendations**.

3. **Bilingual Arabic RTL / English LTR DOCX + PDF Generator (`backend/app/services/report_generator.py`):**
   - **Classification & Revision Block:** Renders owner-locked classification badge (`Preliminary`, `Conceptual`, `For Review`, `For Coordination`, `For Approval`), non-executable advisory engineering disclaimer, and full **Revision Block** (`version`, `revision`, `classification`, UTC ISO date, prepared-by notice, source counts, change note) at the top of both DOCX and PDF.
   - **Arabic RTL & English LTR:**
     - **DOCX (`python-docx`):** Injects OOXML `<w:bidi/>` section direction, paragraph `<w:bidi/>` + right alignment, `<w:rtl/>` run direction with `Tahoma` (`w:cs`) script font attributes, and `<w:bidiVisual/>` RTL table column ordering when `language == "ar"`, keeping `<w:bidi>` absent for English LTR.
     - **PDF (`pymupdf.Story`):** Uses already-pinned `pymupdf==2.1` embedding Windows `Tahoma` (`tahoma.ttf` / `tahomabd.ttf`) via `pymupdf.Archive` (with built-in `Noto Naskh Arabic` fallback outside Windows), Unicode LRI/PDI isolates (`\u2066...\u2069`) for technical LTR identifiers inside RTL prose, a fixed-width Revision Block table, and full-width bordered Finding Cards preventing multi-page RTL table overflow/header distortion.

4. **Versioned Persistence & Download Endpoints (`backend/app/services/review_reports.py`, `backend/app/api/reports.py`, `backend/app/main.py`):**
   - Saves non-overwriting versioned deliverables (`v1`, `v2`, ...) simultaneously to **`08_Reports/review_<short>_v<N>.{docx,pdf}`** (plus companion `review_<short>_v<N>.json`) and **`10_Final_Deliverables/<slug>_<short>_v<N>_<classification>.{docx,pdf}`**, reusing existing run-collision safeguards (`FileExistsError` -> HTTP `409`) and logging `report.generated` / `report.ai_enhanced` audit events.
   - Added endpoints:
     - `POST /api/projects/{project_id}/review-reports`
     - `GET /api/projects/{project_id}/review-reports`
     - `GET /api/review-reports/{report_id}`
     - `POST /api/review-reports/{report_id}/ai-synthesize` *(creates a NEW version `vN+1` without modifying or overwriting `vN`, preserving owner-locked `classification`)*
     - `GET /api/deliverables` & `GET /api/projects/{project_id}/deliverables`
     - `GET /api/deliverables/{deliverable_id}/download` *(streams file only after live SHA-256 verification against persisted hash, returning HTTP `400` on tampering)*

5. **Minimal Gemini Usage & Budget Enforcement (`backend/app/skills/review.py`, `backend/app/services/review_reports.py`):**
   - Deterministic default generation (`use_ai: false`) uses **`0` Gemini tokens** while still computing the exact Step 08 capped prompt size (`MAX_PROMPT_CHARS_PER_SOURCE = 2,400`, `MAX_TOTAL_PROMPT_CHARS = 10,000`) and deterministic **`estimated_prompt_tokens`** plus live Step 04 remaining daily/monthly budget.
   - Zero-evidence projects spend **`0` Gemini tokens** even when `use_ai=true`; on-demand AI synthesis (`POST /api/review-reports/{id}/ai-synthesize`) enforces remaining Step 04 token limits before calling Gemini (HTTP `429` if exceeded) and wraps extracted text inside `<UNTRUSTED_EXTRACTED_EVIDENCE>`.

6. **Deliverables & Reports Frontend UI (`frontend/src/components/DeliverablesView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added bilingual RTL/LTR **المخرجات والتقارير / Deliverables & Reports** tab (`App.tsx`) supporting project report generation (classification lock, language `ar`/`en`, discipline, review notes, `use_ai` toggle), pre-flight prompt cap & Step 04 remaining token readout, explicit **Enhance Copy via AI** action, separated category inspection, source-linked findings table, and one-click DOCX/PDF downloads scoped by `08_Reports` and `10_Final_Deliverables`.

### Step 09B Fixes (`step-09b-report-honesty` — Report Honesty Hardening)
Targeted fix pass addressing every defect exposed when running the Step 09 report against real hospital project files (synthetic tests only in repo; zero client files committed):
1. **CAD Area-Bearing Layer Grouping & Non-Net Label (`backend/app/services/extractors/cad.py`, `backend/app/skills/review.py`):**
   - Added `classify_cad_area_bearing_layer()` and `compute_layer_area_groups()` in `cad.py` to exclude non-area layers (`defpoints`, `furn`, `dim`, `grid`, `axis`, `text`, `hatch`, Arabic equivalents) and never sum all contours across the whole drawing into a single building/total area.
   - Reported CAD `calculated_items` per `(layer, entity_type)` group ONLY for `area_bearing` layers with explicit label **`"geometric sum, not net building area"`**.
2. **Active vs Raw CAD Unit Consistency, Doubtful Units & `"None"` Elimination (`backend/app/skills/review.py`):**
   - `_clean_unit_label()` strips empty/`"None"`/`"none"`/`"null"` values (never rendering `"None"` as a unit).
   - `_resolve_cad_unit_context()` resolves the active unit from owner-confirmed `confirm-unit` when set, aligns calculated area descriptions and citation locations consistently with the unit actually used in calculation, and preserves raw header units cleanly when overridden. Doubtful `$INSUNITS`/unitless drawings keep `area_m2 = null` and emit a `HIGH` `needs_verification` finding.
3. **DXF vs DWG Cross-Format Reconciliation (`backend/app/skills/review.py`):**
   - Paired DXF and DWG extractions matching normalized stem (`_normalize_cad_stem`) or overlapping layers (`Jaccard >= 0.35`) with a total closed-area divergence `> 1%` emit a `HIGH` **CAD Reconciliation** finding citing both `EXT-*` sources and withhold both conflicting area figures from `calculated_items`.
4. **OCR Separation & Unverified Category (`backend/app/schemas/reports.py`, `backend/app/skills/review.py`, `report_generator.py`, `DeliverablesView.tsx`):**
   - `ocr_text` extractions are strictly excluded from `verified_facts` and `findings`, routed instead into a dedicated **`ocr_text_items`** section labelled **"Extracted text (OCR — per-page confidence, not verified)"**, while low-confidence (`< 65%`) pages are also stripped from `source_registry` excerpts. Verified facts hold strictly deterministic native metadata (`SHA-256`, page/layer/entity counts), native extracted data, and reviewed `RES-*` records.
5. **No Deterministic Boilerplate, Document Register & Inventory-Only Notice (`backend/app/skills/review.py`, `report_generator.py`, `DeliverablesView.tsx`):**
   - Removed all templated/boilerplate deterministic findings and generic recommendations (`"match values and units..."`, `"Cross-check extracted figures..."`, `"Confirm applicability..."`, generic fallback recommendation); `findings` contain only concrete observed issues (gaps, doubtful CAD units, DXF/DWG conflicts, unreliable/blank/failed/low-confidence PDF pages).
   - Added structured **`0. Document Register`** (`file`, `type`, `pages/entities`, `extraction status`, `confidence`) and explicit **`is_inventory_only`** header banner stating clearly in deterministic mode that the output is an **inventory & check, NOT an engineering review**.
6. **Explicit Fact Count & Appendix A + Companion JSON Completeness (`backend/app/skills/review.py`, `review_reports.py`, `report_generator.py`, `DeliverablesView.tsx`):**
   - Eliminated silent fact truncation: main section displays **`"Showing N of M verified facts"`** (`MAIN_VERIFIED_FACTS_DISPLAY_LIMIT = 15`), while `Appendix A` in both DOCX & PDF plus companion `08_Reports/review_<short>_v<N>.json` (`appendix_verified_facts`) preserve all `M` verified facts.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0007_step09_review_reports.py`
- `<repo>/backend/app/api/reports.py`
- `<repo>/backend/app/schemas/reports.py`
- `<repo>/backend/app/services/report_generator.py`
- `<repo>/backend/app/services/review_reports.py`
- `<repo>/backend/app/skills/review.py`
- `<repo>/backend/tests/test_reports.py`
- `<repo>/frontend/src/components/DeliverablesView.tsx`
- `<repo>/docs/reports/step-09.md`

### Changed
- `<repo>/backend/app/db/models.py`
- `<repo>/backend/app/main.py`
- `<repo>/backend/app/schemas/extraction.py`
- `<repo>/backend/app/services/extraction.py`
- `<repo>/backend/app/services/extractors/__init__.py`
- `<repo>/backend/app/services/extractors/cad.py` *(Step 09B area-bearing layer classification & `layer_area_groups`)*
- `<repo>/backend/app/services/extractors/ocr.py`
- `<repo>/backend/app/services/extractors/office.py`
- `<repo>/backend/app/services/extractors/pdf_and_image.py`
- `<repo>/backend/tests/test_cad_bim.py` *(Step 09B area-bearing CAD group unit test)*
- `<repo>/backend/tests/test_extraction.py`
- `<repo>/backend/tests/test_migrations.py`
- `<repo>/docs/DECISIONS.md` (`ADR-016`, `ADR-017`, `ADR-018`)
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/frontend/src/App.tsx`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/components/ProjectFilesPanel.tsx`
- `<repo>/frontend/src/types.ts`

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Initial Step 09 Sanitized Sample Report Output (Baseline Snapshot Prior to Step 09B)

Captured in an isolated scratch workspace during initial Step 09 (`use_ai=False`, `0` Gemini tokens) across 4 extracted fixtures (`spec_clinic.pdf`, `plan_metric.dxf`, `plan_doubtful.dxf` with doubtful `$INSUNITS=1`, `room_schedule.xlsx` with `=B2*C2` formula) + 2 research URLs (`1` substantive accessible, `1` blocked `403`). Step 09B subsequently removed deterministic boilerplate findings/recommendations, separated OCR items into `ocr_text_items`, added `Document Register`, added `(layer, entity_type)` area-bearing groups, and added `Appendix A` (`Showing N of M verified facts`).

```text
=== AR_V1 ===
id=0e693d78-3503-4afb-a44f-03b15c6f0d5b version=v1 revision=Rev 01 lang=ar classification=For Review
tokens_used=0 est_prompt_tokens=1428 prompt_chars=4878/10000
counts: findings=5 facts=10 calc=2 assump=2 recs=4 gaps=1 sources=13
  FINDING REV-001 [info|verified_fact] loc=spec_clinic.pdf (page:1 / body) -> refs=['EXT-1:spec_clinic.pdf@body']
  FINDING REV-002 [info|verified_fact] loc=plan_metric.dxf — ModelSpace -> refs=['EXT-6:plan_metric.dxf@$INSUNITS=6 (m)']
  FINDING REV-003 [high|verified_fact] loc=plan_doubtful.dxf — $INSUNITS=1 (in) -> refs=['EXT-11:plan_doubtful.dxf@$INSUNITS=1 (in)']
  FINDING REV-004 [info|verified_fact] loc=room_schedule.xlsx (sheet:Schedule / cell:D2) -> refs=['EXT-12:room_schedule.xlsx@cell:D2']
  FINDING REV-005 [info|verified_fact] loc=Healthcare Clinical Ventilation Code (https://www.hse.gov.uk/ventilation-clinic-check) -> refs=['RES-1:Healthcare Clinical Ventilation Code@https://www.hse.gov.uk/ventilation-clinic-check']
  DELIV 08_Reports DOCX path=08_Reports/review_0e693d78_v1.docx bytes=40468 sha256=3be8b651e2feaa09...
  DELIV 08_Reports PDF path=08_Reports/review_0e693d78_v1.pdf bytes=1987980 sha256=a714070b3e54d7ed...
  DELIV 10_Final_Deliverables DOCX path=10_Final_Deliverables/تقرير_مراجعة_مخططات_ومستندات_العيادة_0e693d78_v1_For_Review.docx bytes=40468 sha256=3be8b651e2feaa09...
    DOCX_XML: paragraphs=45 tables=2 has_w_bidi=True has_w_bidiVisual=True
  DELIV 10_Final_Deliverables PDF path=10_Final_Deliverables/تقرير_مراجعة_مخططات_ومستندات_العيادة_0e693d78_v1_For_Review.pdf bytes=1987980 sha256=a714070b3e54d7ed...
    PDF_CHECK: pages=3
=== EN_V2 ===
id=ab3f9a61-ee8d-456c-90c1-65a79ec2a5df version=v2 revision=Rev 02 lang=en classification=For Coordination
tokens_used=0 est_prompt_tokens=1424 prompt_chars=4891/10000
counts: findings=5 facts=10 calc=2 assump=2 recs=4 gaps=1 sources=13
  DELIV 08_Reports DOCX path=08_Reports/review_ab3f9a61_v2.docx bytes=40067 sha256=3da7a0ea25629394...
  DELIV 08_Reports PDF path=08_Reports/review_ab3f9a61_v2.pdf bytes=1976729 sha256=9b6b576e0e7d15a6...
  DELIV 10_Final_Deliverables DOCX path=10_Final_Deliverables/Clinic_Drawings___Specifications_Review_Report_ab3f9a61_v2_For_Coordination.docx bytes=40067 sha256=3da7a0ea25629394...
  DELIV 10_Final_Deliverables PDF path=10_Final_Deliverables/Clinic_Drawings___Specifications_Review_Report_ab3f9a61_v2_For_Coordination.pdf bytes=1976729 sha256=9b6b576e0e7d15a6...
```

## 4. Tests Run (Full Unedited Outputs — Step 09B)

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 73 items

backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  1%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  2%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  4%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  5%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [  6%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [  8%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [  9%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 10%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 12%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 13%]
backend\tests\test_cad_bim.py::test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_dxf_marks_area_bearing_layers_and_groups_with_non_net_label PASSED [ 16%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 17%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 19%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 20%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 21%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 23%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 24%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 26%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 27%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 28%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 30%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 31%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 32%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 34%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 35%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 36%]
backend\tests\test_extraction.py::test_arabic_native_pdf_cid_or_reversed_text_triggers_300dpi_ocr_and_never_not_needed PASSED [ 38%]
backend\tests\test_extraction.py::test_twelve_page_scanned_pdf_reconciles_all_pages_including_blank_and_failed PASSED [ 39%]
backend\tests\test_extraction.py::test_ocr_per_page_tesseract_mean_confidence_and_low_confidence_flag PASSED [ 41%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 42%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 43%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 45%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 46%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 47%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 49%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 50%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 52%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 53%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 54%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 56%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 57%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 58%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 60%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 61%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 63%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 64%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 65%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 67%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 68%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 69%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 71%]
backend\tests\test_reports.py::test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download PASSED [ 72%]
backend\tests\test_reports.py::test_step09_ai_enhance_caps_prompt_enforces_ref_links_versions_cleanly_and_checks_step04 PASSED [ 73%]
backend\tests\test_reports.py::test_step09_only_cites_reliable_text_and_excludes_failed_blank_cid_reversed_or_low_confidence PASSED [ 75%]
backend\tests\test_reports.py::test_step09b_cad_area_bearing_layers_confirmed_unit_and_no_none_unit PASSED [ 76%]
backend\tests\test_reports.py::test_step09b_dxf_vs_dwg_mismatch_raises_high_reconciliation_and_withholds_conflicting_areas PASSED [ 78%]
backend\tests\test_reports.py::test_step09b_ocr_separated_document_register_no_boilerplate_and_showing_n_of_m_appendix PASSED [ 79%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 80%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 82%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 83%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 84%]
backend\tests\test_research.py::test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload PASSED [ 86%]
backend\tests\test_research.py::test_research_quality_gate_bloomsbury_login_wall_cookie_wall_and_photo_archive PASSED [ 87%]
backend\tests\test_research.py::test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call PASSED [ 89%]
backend\tests\test_research.py::test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize PASSED [ 90%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 91%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 94%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 95%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 97%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

================== 70 passed, 3 skipped in 80.30s (0:01:20) ===================
```

### Opt-In Real External Checks (`RUN_REAL_ODA=1`, `RUN_REAL_OCR=1`, `RUN_REAL_RESEARCH=1`)

```text
> $env:RUN_REAL_ODA='1'; $env:RUN_REAL_OCR='1'; $env:RUN_REAL_RESEARCH='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests -k "test_optin_real" -v -s
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 73 items / 70 deselected / 3 selected

backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf 
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/55f1528c-54c2-4e59-8871-e14c31b1418e/v1/r1/converted/sample_clinic_plan.dxf
PASSED
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture 
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300, mean_conf=91.86): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
ARABIC UNRELIABLE NATIVE RECOVERED (status=ocr_applied (native text unreliable), mean_conf=93.88): 'في من على إلى مشروع مستشفى طرابلس التعليمي'
PASSED
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data 
LIVE RESEARCH SAMPLE: provider=duckduckgo_lite | total=3 | accessible=1 | inaccessible=2 | est_prompt_tokens=1172 | artifact=11_References/research/a72eea2a-81cb-47a2-8fb7-442a2beb56d7/research_log.json
SOURCE tier=government rating=high_government reviewed=True url=https://www.hse.gov.uk/fireandexplosion/workplace.htm http=200 info="Work process fire safety This page provides information about HSE's role. Process fire precautions HSE is mainly concerned with process fire"
SOURCE tier=official_regulations rating=unreviewed reviewed=False url=https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37 http=403 info='UNREVIEWED — Document inaccessible: HTTP 403 response — document could not be accessed and was NOT reviewed; download the document yourself '
SOURCE tier=peer_reviewed rating=unreviewed reviewed=False url=https://doi.org/10.5040/9798400616747.ch-001 http=200 info='UNREVIEWED — Document inaccessible: login wall / paywall / cookie wall / no substantive text (registration country list / login form detecte'
PASSED

====================== 3 passed, 70 deselected in 14.59s ======================
```

### Frontend Tests & TypeScript/Vite Build

```text
> npm.cmd --prefix frontend test -- --run
 ✓ src/App.test.tsx (18 tests) 51ms
 Test Files  1 passed (1)
      Tests  18 passed (18)

> npm.cmd --prefix frontend run build
 ✓ 34 modules transformed.
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-VNk5qLDz.css    5.80 kB │ gzip:  1.68 kB
dist/assets/index-Dno9wuLz.js   278.20 kB │ gzip: 79.30 kB
✓ built in 495ms
```

## 5. Acceptance Criteria Table

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| Step 06 Fix (1): Unreliable native Arabic PDF (`(cid:N)` or reversed `يف نم ىلع ىلإ`) routes to 300 DPI `ara+eng` OCR, flags `native_text_unreliable`, shows `"ocr_applied (native text unreliable)"` / `"partial_ocr_unavailable"` | **PASS** | `assess_native_pdf_text_reliability` + `extract_pdf` in `pdf_and_image.py`; `test_arabic_native_pdf_cid_or_reversed_text_triggers_300dpi_ocr_and_never_not_needed` + live `RUN_REAL_OCR=1` recovery (`mean_conf=93.88`). |
| Step 06 Fix (2): Every page produces an item with `text`/`ocr_text`/`ocr_empty_or_blank`/`failed`; page & item counts reconcile; UI lists blank/failed pages | **PASS** | `page_reconciliation` + `page_status` in `pdf_and_image.py` & `ProjectFilesPanel.tsx`; `test_twelve_page_scanned_pdf_reconciles_all_pages_including_blank_and_failed` (`12` pages = `10` `ocr_text` + `1` blank + `1` failed) & `App.test.tsx`. |
| Step 06 Fix (3): Per-page Tesseract mean confidence stored and low-confidence pages flagged in item & UI | **PASS** | `pytesseract.image_to_data` mean word confidence + `OCR_LOW_CONFIDENCE_THRESHOLD = 65.0` in `ocr.py`; `test_ocr_per_page_tesseract_mean_confidence_and_low_confidence_flag` (`92.0%` vs `40.0%`) & `App.test.tsx`. |
| Step 09 Evidence Gate: Step 09 findings only cite text that passed sanity & OCR checks | **PASS** | `collect_project_evidence_index` in `skills/review.py`; `test_step09_only_cites_reliable_text_and_excludes_failed_blank_cid_reversed_or_low_confidence`. |
| Orchestrator + `review` skill reads extractions (`FileExtraction`) and reviewed research log (`ResearchSource`) | **PASS** | `collect_project_evidence_index` in `backend/app/skills/review.py`; `test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download`. |
| Every finding & verified fact links to an exact extraction location or research log URL | **PASS** | `ReviewFinding.source_links` (`min_length=1`) in `schemas/reports.py`; post-LLM validation drops unlinked claims (`REV-FAKE-DROP`, `BAD-REF`). |
| Strict separation: Verified Facts / Calculated (Python only) / Assumptions (Owner confirmation) / Recommendations | **PASS** | Distinct `verified_facts`, `calculated_items`, `assumptions`, `recommendations` lists + separate DOCX/PDF/UI sections; doubtful units keep `area_m2 = null`. |
| DOCX + PDF report with Arabic RTL, owner-locked classification label, and full revision block | **PASS** | `report_generator.py` (`w:bidi`, `w:bidiVisual`, `Tahoma` cs fonts for DOCX; `pymupdf.Story` + `Tahoma` TTF / `Noto Naskh Arabic` fallback + `\u2066...\u2069` BiDi isolates for PDF); visual inspection of rendered Page 1 & Page 2 PNGs. |
| Versioned non-overwriting saves to `08_Reports` and `10_Final_Deliverables` + Deliverables download UI | **PASS** | Saves `review_<id>_v<N>.{docx,pdf,json}` in `08_Reports` and `<slug>_<id>_v<N>_<cls>.{docx,pdf}` in `10_Final_Deliverables`; SHA-256 verification on download; `DeliverablesView.tsx` & `App.test.tsx` (`18 passed`). |
| Minimal Gemini usage via Step 08 prompt cap, pre-flight estimate, zero-source guard, and Step 04 budget | **PASS** | `use_ai=False` spends `0` tokens while reporting `estimated_prompt_tokens` (`< 10,000` char cap); `0` sources spends `0` tokens even with `use_ai=True`; Step 04 exceedance returns `HTTP 429` before calling Gemini. |
| Step 09B (1): CAD area-bearing `(layer, entity_type)` grouping labelled `"geometric sum, not net building area"`, active confirmed-unit consistency, doubtful `area_m2=null` + `HIGH` finding, and no `"None"` unit | **PASS** | `classify_cad_area_bearing_layer` & `compute_layer_area_groups` in `cad.py`; `_resolve_cad_unit_context` & `_clean_unit_label` in `review.py`; `test_extract_dxf_marks_area_bearing_layers_and_groups_with_non_net_label` & `test_step09b_cad_area_bearing_layers_confirmed_unit_and_no_none_unit`. |
| Step 09B (1b): Paired DXF vs DWG `> 1%` area mismatch raises `HIGH` CAD Reconciliation finding and withholds both conflicting totals | **PASS** | Stem normalization + `Jaccard >= 0.35` layer-overlap pairing in `review.py`; `test_step09b_dxf_vs_dwg_mismatch_raises_high_reconciliation_and_withholds_conflicting_areas`. |
| Step 09B (2–4): OCR separated into `ocr_text_items` (`not verified`), zero deterministic boilerplate, Document Register + inventory notice, `Showing N of M` + `Appendix A` + full JSON | **PASS** | Separated `ocr_text_items` & stripped `< 65%` low-conf excerpts, `DocumentRegisterEntry` table, `is_inventory_only` banner, `MAIN_VERIFIED_FACTS_DISPLAY_LIMIT=15` with `Appendix A` & companion JSON in `review.py` / `report_generator.py` / `DeliverablesView.tsx`; `test_step09b_ocr_separated_document_register_no_boilerplate_and_showing_n_of_m_appendix` & `App.test.tsx`. |
| Owner live inspection on real hospital drawings / scanned PDFs and Microsoft Word desktop opening/printing | **PENDING** | Deferred for owner review on local PC. |

## 6. Known Limitations & Deviations
- **PDF Finding Cards vs DOCX 7-Column Table:** In `pymupdf.Story`, spanning multi-page 7-column RTL HTML tables caused narrow-column overflow and repeated header artifacting across page boundaries. The DOCX export keeps the native 7-column `<w:bidiVisual/>` RTL table for editing in Microsoft Word, while the PDF renders structured full-width bordered Finding Cards (`div.fcard`) with full metadata headers, wrapped LTR source IDs/URLs (`\u2066...\u2069`), and zero column overlap.
- **PDF Arabic Font Embedding:** Uses `tahoma.ttf` / `tahomabd.ttf` from `C:/Windows/Fonts` on Windows (resulting in ~1.98 MB font-embedded PDFs) with MuPDF built-in `Noto Naskh Arabic` fallback elsewhere.
- **Tesseract Confidence & Partial Mocks:** `ocr.py` computes per-word mean confidence from `pytesseract.image_to_data` when a real binary (or mocked `image_to_data`) is available, leaving `ocr_confidence_mean = None` for bare `ocr_runner` strings or `image_to_string`-only mocks without invoking extra `--version` subprocess probes.
- **Area-Bearing Layer Heuristic:** `classify_cad_area_bearing_layer()` uses deterministic naming keywords (`defpoints`, `furn`, `dim`, `grid`, `axis`, `text`, `hatch`, Arabic equivalents) so custom non-standard CAD layer naming conventions still require verifying against `"geometric sum, not net building area"`.
- **AI Enhancement Test Scope:** `enhance_review_with_ai` was verified end-to-end with a mocked Gemini SDK client to preserve API quota; live Gemini synthesis testing and opening DOCX/PDF files in Microsoft Word over real hospital project drawings remain `PENDING`.

## 7. How the Owner Can Try It
1. Launch `<repo>/scripts/start.bat`.
2. In **Projects & Files -> Extract Content**, extract your DXF/DWG drawings (confirm units via **Confirm CAD Unit** if `$INSUNITS` is doubtful) and scanned/native Arabic PDFs.
3. Switch to **المخرجات والتقارير / Deliverables & Reports**, generate a review report (`use_ai=false`, `0` Gemini tokens default):
   - Verify the **Document Register** (`0.`) and **inventory & check, NOT an engineering review** disclaimer appear clearly without boilerplate recommendations or guessed findings.
   - Verify **Calculated Values** list only `area_bearing` CAD layers grouped per `(layer, entity_type)` labelled `geometric sum, not net building area`, matching your confirmed active unit (or withheld with a `HIGH` finding if `$INSUNITS` is doubtful or DXF vs DWG differs by `> 1%`).
   - Verify **OCR** text appears exclusively under **Extracted Text (OCR — per-page confidence, not verified)** and **Verified Facts** displays `Showing N of M verified facts` with all `M` facts preserved in **Appendix A** and companion `08_Reports/review_<id>_v<N>.json`.
4. Download DOCX & PDF from `08_Reports` / `10_Final_Deliverables`, inspect in Microsoft Word, and reply when ready to approve the PR and move to Step 10.
