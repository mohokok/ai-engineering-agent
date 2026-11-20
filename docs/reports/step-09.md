# Step 09 — Document & Drawing Review -> Findings Report (DOCX + PDF, RTL/LTR, Deliverables)

- **Date:** 2026-11-20
- **Status:** **PARTIAL** *(complete Step 09 implementation — DB migration `0007`, `review` skill with mandatory `EXT-*` / `RES-*` source provenance and strict category separation, bilingual Arabic RTL / English LTR DOCX + PDF generation, versioned non-overwriting persistence into `08_Reports` and `10_Final_Deliverables`, minimal-token Step 08/04 budget enforcement, bilingual `DeliverablesView` UI + download verification, full backend `pytest -v`, opt-in real external checks, and frontend Vitest/build all pass cleanly; desktop Microsoft Word opening/printing visual review & interactive `scripts/start.bat` UI walkthrough on real owner project drawings remain `PENDING`)*
- **Branch:** `step-09-review-report`
- **Depends on:** Step 08 (`3afe6e9`, PR `#15` merged)

## 1. Scope Done

1. **Database Schema & Reversible Migration (`backend/app/db/models.py`, `backend/alembic/versions/0007_step09_review_reports.py`):**
   - Added `ReviewReport` (`review_reports`) with strict Step 02 five-label `classification` `CHECK` constraint, `version`, `revision`, `language` (`ar` | `en`), `findings_json`, `structured_payload_json`, `estimated_prompt_tokens`, `token_usage_json`, and `error_message`.
   - Extended `Deliverable` (`deliverables`) with `report_id`, `folder_name`, `filename`, `relative_path`, `mime_type`, `size_bytes`, and `sha256` for integrity-verified tracking across `08_Reports` and `10_Final_Deliverables`.

2. **Orchestrator + `review` Skill (`backend/app/skills/review.py`, `backend/app/schemas/reports.py`):**
   - Collects deterministic extractions (`FileExtraction` records including `cad_dxf`, `bim_ifc`, PDF pages/tables/OCR, DOCX/XLSX formulas & cells, CSV, PPTX, and image OCR) plus reviewed internet research logs (`ResearchSource` rows where `reviewed == True`). Inaccessible/blocked sources (`HTTP 403`, login walls, `not_relevant`) stay strictly excluded from `source_registry` and appear in `gaps_or_unextracted`.
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
- `<repo>/backend/tests/test_migrations.py`
- `<repo>/docs/DECISIONS.md` (`ADR-016`)
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/frontend/src/App.tsx`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/types.ts`

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Sample Report Output (Arabic RTL `v1` + English LTR `v2`)

Captured in an isolated scratch workspace (`use_ai=False`, `0` Gemini tokens) across 4 extracted fixtures (`spec_clinic.pdf`, `plan_metric.dxf`, `plan_doubtful.dxf` with doubtful `$INSUNITS=1`, `room_schedule.xlsx` with `=B2*C2` formula) + 2 research URLs (`1` substantive accessible, `1` blocked `403`):

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

## 4. Tests Run (Full Unedited Outputs)

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 65 items

backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  1%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  3%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  4%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  6%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [  7%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [  9%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 10%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 12%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 13%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area PASSED [ 16%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 18%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 20%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 21%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 23%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 24%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 26%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 27%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 29%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 30%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 32%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 33%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 35%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 36%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 38%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 40%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 41%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 43%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 44%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 46%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 47%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 49%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 50%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 52%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 53%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 55%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 56%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 58%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 60%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 61%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 63%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 64%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 66%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 67%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 69%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 70%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 72%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 73%]
backend\tests\test_reports.py::test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download PASSED [ 75%]
backend\tests\test_reports.py::test_step09_ai_enhance_caps_prompt_enforces_ref_links_versions_cleanly_and_checks_step04 PASSED [ 76%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 78%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 80%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 81%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 83%]
backend\tests\test_research.py::test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload PASSED [ 84%]
backend\tests\test_research.py::test_research_quality_gate_bloomsbury_login_wall_cookie_wall_and_photo_archive PASSED [ 86%]
backend\tests\test_research.py::test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call PASSED [ 87%]
backend\tests\test_research.py::test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize PASSED [ 89%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 90%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 92%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 95%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

======================= 62 passed, 3 skipped in 54.88s ========================
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
collecting ... collected 65 items / 62 deselected / 3 selected

backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf 
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/0d98b906-1c30-4cee-8269-cb593476faf1/v1/r1/converted/sample_clinic_plan.dxf
PASSED
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture 
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PASSED
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data 
LIVE RESEARCH SAMPLE: provider=duckduckgo_lite | total=3 | accessible=1 | inaccessible=2 | est_prompt_tokens=1172 | artifact=11_References/research/8fd4234d-8968-4623-9a5d-3a5e5c52aa78/research_log.json
SOURCE tier=government rating=high_government reviewed=True url=https://www.hse.gov.uk/fireandexplosion/workplace.htm http=200 info="Work process fire safety This page provides information about HSE's role. Process fire precautions HSE is mainly concerned with process fire"
SOURCE tier=official_regulations rating=unreviewed reviewed=False url=https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37 http=403 info='UNREVIEWED — Document inaccessible: HTTP 403 response — document could not be accessed and was NOT reviewed; download the document yourself '
SOURCE tier=peer_reviewed rating=unreviewed reviewed=False url=https://doi.org/10.5040/9798400616747.ch-001 http=200 info='UNREVIEWED — Document inaccessible: login wall / paywall / cookie wall / no substantive text (registration country list / login form detecte'
PASSED

====================== 3 passed, 62 deselected in 10.71s ======================
```

### Frontend Tests & TypeScript/Vite Build

```text
> npm.cmd --prefix frontend test -- --run
 ✓ src/App.test.tsx (17 tests) 58ms
 Test Files  1 passed (1)
      Tests  17 passed (17)

> npm.cmd --prefix frontend run build
 ✓ 34 modules transformed.
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-VNk5qLDz.css    5.80 kB │ gzip:  1.68 kB
dist/assets/index-C4hhBpsQ.js   271.75 kB │ gzip: 77.85 kB
✓ built in 566ms
```

## 5. Acceptance Criteria Table

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| Orchestrator + `review` skill reads extractions (`FileExtraction`) and reviewed research log (`ResearchSource`) | **PASS** | `collect_project_evidence_index` in `backend/app/skills/review.py`; `test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download` covers PDF, metric DXF, doubtful `$INSUNITS` DXF, XLSX formula, and accessible/blocked research sources. |
| Every finding & verified fact links to an exact extraction location or research log URL | **PASS** | `ReviewFinding.source_links` (`min_length=1`) in `schemas/reports.py`; post-LLM validation drops unlinked claims (`REV-FAKE-DROP`, `BAD-REF`) in `test_step09_ai_enhance_caps_prompt_enforces_ref_links_versions_cleanly_and_checks_step04`. |
| Strict separation: Verified Facts / Calculated (Python only) / Assumptions (Owner confirmation) / Recommendations | **PASS** | Distinct `verified_facts`, `calculated_items`, `assumptions`, `recommendations` lists + separate DOCX/PDF/UI sections; doubtful units keep `area_m2 = null`. |
| DOCX + PDF report with Arabic RTL, owner-locked classification label, and full revision block | **PASS** | `report_generator.py` (`w:bidi`, `w:bidiVisual`, `Tahoma` cs fonts for DOCX; `pymupdf.Story` + `Tahoma` TTF / `Noto Naskh Arabic` fallback + `\u2066...\u2069` BiDi isolates for PDF); visual inspection of rendered Page 1 & Page 2 PNGs confirmed Arabic shaping, classification banner, and revision block. |
| Versioned non-overwriting saves to `08_Reports` and `10_Final_Deliverables` | **PASS** | Saves `review_<id>_v<N>.{docx,pdf,json}` in `08_Reports` and `<slug>_<id>_v<N>_<cls>.{docx,pdf}` in `10_Final_Deliverables`; `v1` SHA-256 unchanged after `v2` creation. |
| Deliverables page in frontend with pre-flight token estimate, findings view, and working download | **PASS** | `DeliverablesView.tsx` + `GET /api/deliverables/{id}/download` with SHA-256 verification and tamper rejection (`HTTP 400`); `App.test.tsx` (`17 passed`) & Vite build clean. |
| Minimal Gemini usage via Step 08 prompt cap, pre-flight estimate, zero-source guard, and Step 04 budget | **PASS** | `use_ai=False` spends `0` tokens while reporting `estimated_prompt_tokens` (`< 10,000` char cap); `0` sources spends `0` tokens even with `use_ai=True`; Step 04 exceedance returns `HTTP 429` before calling Gemini. |
| Owner desktop opening/printing visual review in Microsoft Word & live UI walkthrough | **PENDING** | Deferred for owner review on local PC. |

## 6. Known Limitations & Deviations
- **PDF Finding Cards vs DOCX 7-Column Table:** In `pymupdf.Story`, spanning multi-page 7-column RTL HTML tables caused narrow-column overflow and repeated header artifacting across page boundaries. The DOCX export keeps the native 7-column `<w:bidiVisual/>` RTL table for editing in Microsoft Word, while the PDF renders structured full-width bordered Finding Cards (`div.fcard`) with full metadata headers, wrapped LTR source IDs/URLs (`\u2066...\u2069`), and zero column overlap. Page-break splitting can still occur across tall Finding Cards under MuPDF's HTML engine if a card exceeds remaining page height.
- **PDF Arabic Font Embedding:** Uses `tahoma.ttf` / `tahomabd.ttf` from `C:/Windows/Fonts` on Windows (resulting in ~1.98 MB font-embedded PDFs) with MuPDF built-in `Noto Naskh Arabic` fallback elsewhere.
- **AI Enhancement Test Scope:** `enhance_review_with_ai` was verified end-to-end with a mocked Gemini SDK client (testing the `10,000`-char prompt cap, untrusted delimiters, `NONEXISTENT-999` hallucination rejection, classification lock, and Step 04 `429` enforcement) to preserve API quota; live Gemini synthesis testing and opening DOCX/PDF files in Microsoft Word over real project drawings remain `PENDING`.

## 7. How the Owner Can Try It
1. Launch `<repo>/scripts/start.bat`.
2. Open a project that already has extracted files (**Extract Content** tab) and/or reviewed research sources (**Research & Source Log** tab).
3. Switch to the **المخرجات والتقارير / Deliverables & Reports** tab:
   - Lock your **Classification** (`Preliminary` / `For Review` / `For Approval`, etc.) and language (`Arabic RTL` or `English LTR`).
   - Click **Generate Review Report** (`0` Gemini tokens by default) to inspect linked `EXT-*` / `RES-*` findings, separated facts/calculations/assumptions/recommendations, and pre-flight `~N est. prompt tokens`.
   - Optionally click **Enhance Copy via AI** to create a new version (`v2`) within Step 04 limits without touching `v1`.
   - Download both `.docx` and `.pdf` directly from `08_Reports` or `10_Final_Deliverables` and confirm formatting in Microsoft Word and your PDF viewer.
4. Once satisfied after PR review & merge, reply **`PASS step 09`** when ready for **Step 10**.
