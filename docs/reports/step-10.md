# Step 10 — BOQ and Quantity Module (Plus Step 09 Report Leftover Fixes)

- **Date:** 2026-11-21
- **Status:** **PARTIAL** *(First small commit `e41cffe` resolved the three Step 09 report leftovers cleanly; Step 10 delivers relational `boq_sheets` / `boq_items` schema via migration `0008`, deterministic DXF/IFC quantities covering areas/lengths/counts, XLSX/PDF BOQ import, strict `Extracted-Verified` / `Extracted-Needs-Check` / `Manual` verification tagging, confirmed-unit respect & unconfirmed-unit metric block, strict owner/dated-research rate provenance blocking unsourced rates, configurable `LYD`-default currency, deterministic audit checks for duplicates/missing items/units/arithmetic, versioned live-formula XLSX + UTF-8 CSV exports in `06_BOQ`, Arabic RTL + English LTR UI (`BoqView.tsx`), `74 passed, 3 skipped` backend `pytest -v`, `3/3` opt-in real ODA/OCR/research checks, `3/3` Alembic migration round-trip checks, and `19 passed` frontend Vitest + Vite build; owner live verification in desktop Microsoft Excel / `scripts/start.bat` on real hospital project files remains `PENDING`)*
- **Branch:** `step-10-boq-quantities`
- **Depends on:** Step 09 & Step 09B (`c4a6bb5`, PRs `#16` and `#17` merged)

## 1. Scope Done

### First Commit (`e41cffe`) — Step 09 Report Leftover Fixes (`(a)`, `(b)`, `(c)`)
1. **(a) Section 3 Cited Sources Only (`backend/app/services/report_generator.py`):** Added `_collect_cited_sources()` and `_sources_scope_banner()` so DOCX and PDF Section 3 render ONLY the `N` sources actually cited across findings, verified facts, Appendix A, calculated values, OCR text, assumptions, and recommendations, stating **`"N cited of M extracted"`**, while companion `08_Reports/review_<short>_v<N>.json` preserves all `M` extracted entries.
2. **(b) DXF/DWG Unconfirmed-Unit Handling & Zero `"None"` Leakage (`backend/app/skills/review.py`):** Eliminated `Turj-fin.dwg=None m²` formatting; when one drawing has confirmed areas and its paired DXF/DWG file lacks areas only because its unit is unconfirmed (`is_doubtful`), the confirmed file's per-layer `area_bearing` areas remain shown alongside a medium finding **`"confirm the unit of the other file"`**, while the `HIGH` **`CAD Reconciliation`** (>1%) finding fires ONLY when both areas are available and differ by more than `1%`.
3. **(c) v2+ Revision Notes (`backend/app/schemas/reports.py`, `backend/app/services/review_reports.py`):** Replaced the hardcoded v1 default `"Initial extraction and research review issue"` on v2+ regenerations with **`"Regenerated from current extractions"`** (preserving any explicit custom owner change note or AI-enhancement note).

### Step 10 — Bill of Quantities (BOQ) and Quantity Module (`0` Gemini Tokens)
1. **Database Schema & Reversible Migration (`backend/app/db/models.py`, `backend/alembic/versions/0008_step10_boq_quantities.py`):**
   - Added `boq_sheets` (`classification` `CHECK` constraint, `currency` default `"LYD"`, `revision`, `version`, `export_version`, `checks_summary_json`, `source_metadata_json`) and `boq_items` (`item_no`, `description`, `unit`, `quantity`, `unit_rate`, `total`, `reported_total`, `technical_reference`, `drawing_reference`, `remarks`, `verification_status` `CHECK` constraint for `{'Extracted-Verified', 'Extracted-Needs-Check', 'Manual'}`, `rate_source_kind` `CHECK` constraint for `{'owner_input', 'dated_research'}`, `rate_source_ref`, `rate_source_date`).
   - Added nullable `boq_id` FK onto `deliverables` for unified SHA-256-verified download links from `06_BOQ/`.

2. **Deterministic Quantities from DXF/DWG & IFC (`backend/app/services/extractors/cad.py`, `bim.py`, `boq.py`):**
   - Shared `resolve_cad_unit_context()` across Step 09 and Step 10 cleanly in `cad.py`; extended DXF extraction with ModelSpace `layer_length_groups` (`LINE`, `ARC`, open `LWPOLYLINE`, open 2D `POLYLINE`) and `block_insert_groups` updated cleanly by `apply_confirmed_cad_unit()`.
   - Extracts DXF **areas** (`area_bearing` layers in `m2`), **linear lengths** (`m`), and **block insert counts** (`nos`), plus IFC **spaces** (`IfcSpace`), **wall areas/lengths** (`IfcWall`), and **element counts** (`IfcDoor`, `IfcWindow`, `IfcWall`, `IfcSlab`, etc.).
   - **Unit Confirmation Guard:** Doubtful or unconfirmed CAD/BIM drawings are NEVER silently converted via `$INSUNITS` — areas and lengths stay in raw native units explicitly labelled `unconfirmed (...) sq` / `unitless`, tagged **`Extracted-Needs-Check`**, flagged by checks, and blocked (`HTTP 422`) from pricing until the owner confirms the drawing unit via `/api/extractions/{id}/confirm-unit`.

3. **Existing BOQ Import from XLSX / PDF (`backend/app/services/boq.py`):**
   - Parses tabular BOQs from extracted `XLSX`, `CSV`, and native/OCR `PDF` tables (plus borderless tabular PDF text lines) supporting Arabic & English column headers and Arabic-Indic numerals while respecting Step 09 native-PDF reliability gating (`assess_native_pdf_text_reliability`).
   - Preserves verbatim `reported_total` from imported spreadsheets/PDFs so discrepancies vs `quantity * unit_rate` surface deterministically in audit checks.

4. **Sourced Unit Rates Gate & Configurable Currency (`backend/app/schemas/boq.py`, `backend/app/services/boq.py`):**
   - Unsourced rates, `owner_input` missing owner attribution, `dated_research` missing `rate_source_date`, or `dated_research` referencing an unreviewed/inaccessible `ResearchSource` (`reviewed=False`) are strictly blocked (`HTTP 422`).
   - Configurable ISO 3-letter currency (`LYD` default; switchable cleanly via `PATCH /api/boq-sheets/{boq_id}` and UI).

5. **Deterministic Audit Checks & Versioned 06_BOQ Exports (`backend/app/services/boq.py`, `boq_export.py`, `api/boq.py`):**
   - `run_boq_checks_on_sheet()` executes deterministic checks for **duplicates** (`item_no` collisions & description/unit/quantity signatures), **missing items** (missing item no., missing unit, zero/missing qty such as unauthored IFC room areas, missing DXF/IFC extracted coverage), **unit consistency** (unconfirmed CAD units, mixed metric/imperial/submetric systems, `'nos'` on surface descriptions), and **arithmetic totals** (`stored total` & `reported_total` vs `Decimal(quantity) * Decimal(unit_rate)`), producing explicit `flagged_items` for human verification.
   - `POST /api/boq-sheets/{boq_id}/export` writes non-overwriting versioned deliverables into **`06_BOQ/<slug>_<short>_v<N>.xlsx`** (live `=IF(ISNUMBER(E{r}),ROUND(D{r}*E{r},4),0)`, `=SUM(...)`, `=SUMIF(...)`, and `=COUNTIF(...)` Excel formulas plus a dedicated `Checks & Flagged Items` sheet) and **`06_BOQ/<slug>_<short>_v<N>.csv`** (UTF-8 without BOM), registered in `Deliverable` for SHA-256-verified download.

6. **Bilingual Arabic RTL & English LTR UI (`frontend/src/components/BoqView.tsx`, `DeliverablesView.tsx`, `App.tsx`, `api.ts`, `types.ts`):**
   - Added **جداول الكميات (BOQ) / BOQ & Quantities** tab (`App.tsx`) supporting project BOQ creation from DXF/IFC/XLSX/PDF extractions, `LYD` & multi-currency switching, color-coded `Extracted-Verified` / `Extracted-Needs-Check` / `Manual` status badges, sourced rate editor blocking unattributed inputs, manual line entry, live audit checks table + highlighted human-verification list, and `06_BOQ` XLSX/CSV exports (`06_BOQ` filter also added in `DeliverablesView.tsx`).

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0008_step10_boq_quantities.py`
- `<repo>/backend/app/api/boq.py`
- `<repo>/backend/app/schemas/boq.py`
- `<repo>/backend/app/services/boq.py`
- `<repo>/backend/app/services/boq_export.py`
- `<repo>/backend/tests/test_boq.py`
- `<repo>/frontend/src/components/BoqView.tsx`
- `<repo>/docs/reports/step-10.md`

### Changed
- `<repo>/backend/app/db/models.py` *(Step 10 `BoqSheet`, `BoqItem`, `Deliverable.boq_id`)*
- `<repo>/backend/app/main.py` *(registered `boq_router`)*
- `<repo>/backend/app/schemas/reports.py` *(Step 09 leftover `change_note` default fix + `DeliverableOut.boq_id`)*
- `<repo>/backend/app/services/extractors/bim.py` *(preserved optional `area_source` & `quantities` on `element_inventory_rows`)*
- `<repo>/backend/app/services/extractors/cad.py` *(shared `resolve_cad_unit_context`, `compute_layer_length_groups`, `LINE`/`ARC`/open polyline lengths, `block_insert_groups`)*
- `<repo>/backend/app/services/report_generator.py` *(Step 09 leftover `(a)` cited-only Section 3 + `"N cited of M extracted"`)*
- `<repo>/backend/app/services/review_reports.py` *(Step 09 leftover `(c)` `"Regenerated from current extractions"` + `DeliverableOut.boq_id`)*
- `<repo>/backend/app/skills/review.py` *(Step 09 leftover `(b)` unconfirmed paired DXF/DWG handling without `None` + shared CAD unit context)*
- `<repo>/backend/tests/test_migrations.py` *(added `boq_sheets`, `boq_items` to `EXPECTED_TABLES`)*
- `<repo>/backend/tests/test_reports.py` *(added `test_step09_leftovers_cited_sources_only_no_none_unconfirmed_other_file_and_v2_revision_note`)*
- `<repo>/docs/DECISIONS.md` *(`ADR-019`)*
- `<repo>/frontend/src/App.test.tsx` *(Step 10 `BoqView` & API Vitest tests)*
- `<repo>/frontend/src/App.tsx` *(`boq` tab integration)*
- `<repo>/frontend/src/api.ts` *(Step 10 BOQ client endpoints)*
- `<repo>/frontend/src/components/DeliverablesView.tsx` *(added `06_BOQ` folder filter option)*
- `<repo>/frontend/src/types.ts` *(Step 10 TypeScript interfaces)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized BOQ Sample Output, Checks & Items Flagged for Human Verification

Generated deterministically (`0` AI tokens) from committed synthetic fixtures (`sample_clinic_plan.dxf` + `sample_clinic_model.ifc`) with one owner-sourced unit rate on `CAD-A-01`:

```text
BOQ_HEADER: Rev 01 LYD items= 10 grand_total= 6840.0
ITEM: CAD-A-01 | Extracted-Verified | 38.0 m2 | rate= 180.0 | total= 6840.0 | ref= sample_clinic_plan.dxf | layer:جدران-معمارية | LWPOLYLINE
ITEM: CAD-C-01 | Extracted-Verified | 2.0 nos | rate= None | total= None | ref= sample_clinic_plan.dxf | layer:جدران-معمارية | block:DOOR_باب_D1
ITEM: IFC-S-01 | Extracted-Verified | 18.75 m2 | rate= None | total= None | ref= sample_clinic_model.ifc | IfcSpace:24a1T7slL93OzfW4X8ZqLl
ITEM: IFC-S-02 | Extracted-Needs-Check | 0.0 m2 | rate= None | total= None | ref= sample_clinic_model.ifc | IfcSpace:10CxPiAJP7EQD$cvc01H35
ITEM: IFC-W-01 | Extracted-Verified | 21.0 m2 | rate= None | total= None | ref= sample_clinic_model.ifc | IfcWall:area_sum
ITEM: IFC-W-02 | Extracted-Verified | 6.0 m | rate= None | total= None | ref= sample_clinic_model.ifc | IfcWall:length_sum
ITEM: IFC-C-01 | Extracted-Verified | 1.0 nos | rate= None | total= None | ref= sample_clinic_model.ifc | IfcDoor:count
ITEM: IFC-C-02 | Extracted-Verified | 1.0 nos | rate= None | total= None | ref= sample_clinic_model.ifc | IfcWindow:count
ITEM: IFC-C-03 | Extracted-Verified | 1.0 nos | rate= None | total= None | ref= sample_clinic_model.ifc | IfcWall:count
ITEM: IFC-C-04 | Extracted-Needs-Check | 1.0 nos | rate= None | total= None | ref= sample_clinic_model.ifc | IfcSlab:count

CHECKS: 2 high= 1
ISSUE: CHK-001 missing_item high IFC-S-02 Item 'IFC-S-02' (BIM IfcSpace 'غرفة الانتظار' (Storey: الطابق الأرضي - Ground Floor) — ) has zero/missing quantity (0.0).
ISSUE: CHK-002 unit_consistency medium IFC-C-04 Item 'IFC-C-04' ('BIM IfcSlab element count [sample_clinic_model.ifc]') uses count unit 'nos' for a surface/area description.

FLAGGED FOR HUMAN VERIFICATION:
FLAGGED: IFC-S-02 | Extracted-Needs-Check | Tagged Extracted-Needs-Check — human review required; Missing or zero quantity (0.0)
FLAGGED: IFC-C-04 | Extracted-Needs-Check | Tagged Extracted-Needs-Check — human review required; Unit vs description mismatch ('nos' on area description)

EXPORTED 06_BOQ FILES & LIVE FORMULAS:
FILE_XLSX: 06_BOQ/Bill_of_Quantities_(BOQ)_—_SMP-10_66a9d43d_v1.xlsx 8741 sha= 8ca2db9700141bcf
FILE_CSV: 06_BOQ/Bill_of_Quantities_(BOQ)_—_SMP-10_66a9d43d_v1.csv 2930 sha= 0ee398f39989021c
FORMULA: F6  = =IF(ISNUMBER(E6),ROUND(D6*E6,4),0)
...
FORMULA: F15 = =IF(ISNUMBER(E15),ROUND(D15*E15,4),0)
FORMULA: F16 = =SUMIF(J6:J15,"Extracted-Verified",F6:F15)
FORMULA: F17 = =SUMIF(J6:J15,"Extracted-Needs-Check",F6:F15)
FORMULA: F18 = =SUMIF(J6:J15,"Manual",F6:F15)
FORMULA: F19 = =SUM(F6:F15)
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
collecting ... collected 77 items

backend\tests\test_boq.py::test_step10_dxf_ifc_quantities_respect_confirmed_unit_and_never_silent_convert PASSED [  1%]
backend\tests\test_boq.py::test_step10_unsourced_rates_blocked_sourced_accepted_configurable_currency_and_xlsx_live_formulas PASSED [  2%]
backend\tests\test_boq.py::test_step10_import_xlsx_and_pdf_boqs_and_seeded_checks_duplicates_missing_units_arithmetic PASSED [  3%]
backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  5%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  6%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  7%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  9%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [ 10%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [ 11%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 12%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 14%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 16%]
backend\tests\test_cad_bim.py::test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area PASSED [ 18%]
backend\tests\test_cad_bim.py::test_extract_dxf_marks_area_bearing_layers_and_groups_with_non_net_label PASSED [ 19%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 20%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 22%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 23%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 24%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 25%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 27%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 28%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 29%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 31%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 32%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 33%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 35%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 36%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 37%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 38%]
backend\tests\test_extraction.py::test_arabic_native_pdf_cid_or_reversed_text_triggers_300dpi_ocr_and_never_not_needed PASSED [ 40%]
backend\tests\test_extraction.py::test_twelve_page_scanned_pdf_reconciles_all_pages_including_blank_and_failed PASSED [ 41%]
backend\tests\test_extraction.py::test_ocr_per_page_tesseract_mean_confidence_and_low_confidence_flag PASSED [ 42%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 44%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 45%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 46%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 48%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 49%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 50%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 51%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 53%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 54%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 55%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 57%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 58%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 59%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 61%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 62%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 63%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 64%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 66%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 67%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 68%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 70%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 71%]
backend\tests\test_reports.py::test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download PASSED [ 72%]
backend\tests\test_reports.py::test_step09_ai_enhance_caps_prompt_enforces_ref_links_versions_cleanly_and_checks_step04 PASSED [ 74%]
backend\tests\test_reports.py::test_step09_only_cites_reliable_text_and_excludes_failed_blank_cid_reversed_or_low_confidence PASSED [ 75%]
backend\tests\test_reports.py::test_step09b_cad_area_bearing_layers_confirmed_unit_and_no_none_unit PASSED [ 76%]
backend\tests\test_reports.py::test_step09b_dxf_vs_dwg_mismatch_raises_high_reconciliation_and_withholds_conflicting_areas PASSED [ 77%]
backend\tests\test_reports.py::test_step09b_ocr_separated_document_register_no_boilerplate_and_showing_n_of_m_appendix PASSED [ 79%]
backend\tests\test_reports.py::test_step09_leftovers_cited_sources_only_no_none_unconfirmed_other_file_and_v2_revision_note PASSED [ 80%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 81%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 83%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 84%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 85%]
backend\tests\test_research.py::test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload PASSED [ 87%]
backend\tests\test_research.py::test_research_quality_gate_bloomsbury_login_wall_cookie_wall_and_photo_archive PASSED [ 88%]
backend\tests\test_research.py::test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call PASSED [ 89%]
backend\tests\test_research.py::test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize PASSED [ 90%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 92%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 94%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 97%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

================== 74 passed, 3 skipped in 87.94s (0:01:27) ===================
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
collecting ... collected 77 items / 74 deselected / 3 selected

backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf 
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/044844a8-1516-49d3-934b-8d06061f8013/v1/r1/converted/sample_clinic_plan.dxf
PASSED
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture 
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300, mean_conf=91.86): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
ARABIC UNRELIABLE NATIVE RECOVERED (status=ocr_applied (native text unreliable), mean_conf=93.88): 'في من على إلى مشروع مستشفى طرابلس التعليمي'
PASSED
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data 
LIVE RESEARCH SAMPLE: provider=duckduckgo_lite | total=3 | accessible=1 | inaccessible=2 | est_prompt_tokens=1172 | artifact=11_References/research/b2eb81da-4a88-40ce-8a88-a89108289558/research_log.json
SOURCE tier=government rating=high_government reviewed=True url=https://www.hse.gov.uk/fireandexplosion/workplace.htm http=200 info="Work process fire safety This page provides information about HSE's role. Process fire precautions HSE is mainly concerned with process fire"
SOURCE tier=official_regulations rating=unreviewed reviewed=False url=https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37 http=403 info='UNREVIEWED — Document inaccessible: HTTP 403 response — document could not be accessed and was NOT reviewed; download the document yourself '
SOURCE tier=peer_reviewed rating=unreviewed reviewed=False url=https://doi.org/10.5040/9798400616747.ch-001 http=200 info='UNREVIEWED — Document inaccessible: login wall / paywall / cookie wall / no substantive text (registration country list / login form detecte'
PASSED

====================== 3 passed, 74 deselected in 14.34s ======================
```

### Frontend Tests & TypeScript/Vite Build

```text
> npm.cmd --prefix frontend test -- --run
 ✓ src/App.test.tsx (19 tests) 53ms
 Test Files  1 passed (1)
      Tests  19 passed (19)

> npm.cmd --prefix frontend run build
 ✓ 35 modules transformed.
dist/index.html                   0.48 kB │ gzip:  0.34 kB
dist/assets/index-VNk5qLDz.css    5.80 kB │ gzip:  1.68 kB
dist/assets/index-CZDcYkDB.js   302.59 kB │ gzip: 84.55 kB
✓ built in 522ms
```

## 5. Acceptance Criteria Table

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| First Commit Leftovers `(a)`, `(b)`, `(c)`: Section 3 lists cited sources only (`N cited of M extracted`), no `None` / confirmed per-layer areas preserved when paired file unconfirmed, v2+ revision note says `"Regenerated from current extractions"` | **PASS** | Commit `e41cffe`; `report_generator.py`, `skills/review.py`, `schemas/reports.py`, `review_reports.py`; `test_step09_leftovers_cited_sources_only_no_none_unconfirmed_other_file_and_v2_revision_note`. |
| BOQ Schema & Migration (`boq_sheets`, `boq_items`, verification tags, `LYD` configurable currency) | **PASS** | `models.py`, `0008_step10_boq_quantities.py`, `schemas/boq.py`; `test_alembic_upgrade_and_downgrade_round_trip` (`3 passed`). |
| Existing BOQ imported from XLSX / PDF preserving traceability | **PASS** | `_parse_boq_rows_from_table` & `_parse_boq_rows_from_pdf_text` in `services/boq.py`; `test_step10_import_xlsx_and_pdf_boqs_and_seeded_checks_duplicates_missing_units_arithmetic`. |
| Deterministic DXF/IFC quantities (areas, lengths, counts by layer/type) respecting owner-confirmed units | **PASS** | `layer_area_groups`, `layer_length_groups` (`LINE`, `ARC`, open polylines), `block_insert_groups`, IFC spaces/walls/counts; unconfirmed DXF kept native as `Extracted-Needs-Check` & blocked from metric conversion/pricing (`test_step10_dxf_ifc_quantities_respect_confirmed_unit_and_never_silent_convert`). |
| Unsourced rates blocked (`owner_input` or `dated_research` with date & reviewed source required) | **PASS** | `_validate_rate_source` + `_verify_research_source_date_and_review` returning `HTTP 422`; tested across 4 invalid paths + unconfirmed CAD pricing block in `test_step10_unsourced_rates_blocked_sourced_accepted_configurable_currency_and_xlsx_live_formulas`. |
| Checks (`duplicates`, `missing items`, `unit consistency`, `arithmetic totals`) + Flagged human-verification list | **PASS** | `run_boq_checks_on_sheet` catching seeded duplicate `item_no`, missing `IfcDoor` coverage & zero-qty/missing-unit rows, mixed `cm2`/`m2` units, and DB/imported arithmetic mismatches. |
| Export XLSX with live Excel formulas (`=IF(...)`, `=SUM(...)`, `=SUMIF(...)`, `=COUNTIF(...)`) + UTF-8 CSV into `06_BOQ` | **PASS** | Verified with `openpyxl` formula inspection & `csv.reader` in `test_step10_unsourced_rates_blocked_sourced_accepted_configurable_currency_and_xlsx_live_formulas` + SHA-256 download endpoint. |
| Arabic RTL and English LTR BOQ UI & zero Gemini bloat | **PASS** | `BoqView.tsx`, `DeliverablesView.tsx`, `App.tsx`, `App.test.tsx` (`19 passed`), Vite build (`35 modules`), `0` AI tokens used. |
| Live desktop Microsoft Excel formula recalculation & live UI check on real hospital DXF/IFC/BOQ files | **PENDING** | Deferred for owner verification on local PC. |

## 6. Known Limitations & Deviations
- **Desktop Microsoft Excel Live Recalculation Inspection:** Formula syntax (`=IF(ISNUMBER(E{r}),ROUND(D{r}*E{r},4),0)`, `=SUM(...)`, `=SUMIF(...)`, `=COUNTIF(...)`) is verified cleanly via `openpyxl` (`data_only=False`), while opening/editing values interactively in desktop Microsoft Excel on Windows remains `PENDING` owner verification.
- **3D IFC Volumes & Non-Tabular Unstructured PDFs:** Step 10 uses deterministically extracted Step 07 IFC `Qto_*` / `Pset_*` properties and `IfcProduct` counts without computing implicit 3D B-rep volumes; PDF BOQ import requires extractable grid tables or consistently delimited multi-column text lines.
- **Doubtful CAD Units Strategy:** Rather than deleting geometry from unconfirmed/doubtful DXF drawings silently, Step 10 keeps raw native quantities tagged `Extracted-Needs-Check` (`unconfirmed (...)`), flags `unverified_unit`, blocks silent metric conversion, and rejects pricing (`HTTP 422`) until the owner confirms the drawing unit.

## 7. How the Owner Can Try It
1. Launch `<repo>/scripts/start.bat`.
2. In **Projects & Files -> Extract Content**, extract your DXF/IFC drawings (confirming `$INSUNITS` via **Confirm CAD Unit** if doubtful) and any existing BOQ `.xlsx` or `.pdf` schedule.
3. Open **جداول الكميات (BOQ) / BOQ & Quantities**:
   - Select your project, confirm currency (`LYD` default or switch to `USD`/`EUR`/custom), select files, and click **Build BOQ (DXF / IFC / XLSX / PDF)**.
   - Confirm doubtful-unit drawings remain tagged **`Extracted-Needs-Check`** with metric conversion blocked until confirmed, verify unattributed rates are rejected, attach owner or dated reviewed-research rates, inspect **Checks & Flagged Items for Human Verification**, export **XLSX + CSV** into `06_BOQ`, and verify formula recalculation in Microsoft Excel.
4. Reply **`PASS step 10`** after PR review & merge when ready for **Step 11**.
