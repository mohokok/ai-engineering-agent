# Step 11 — Parametric Drawing Engine (DXF + True-Scale PDF) & BOQ Honesty Fixes

- **Date:** 2026-11-21
- **Status:** **PARTIAL** *(First small commit `fd4ce35` landed both BOQ honesty fixes before Step 11; Step 11 delivers relational `parametric_drawings` persistence via reversible migration `0009`, strict millimetre coordinate validation (`units="mm"`), code-only Shoelace room area & perimeter computation ignoring user/AI-typed areas, standard-layer `ezdxf` output (`$INSUNITS=4`, `$MEASUREMENT=1`, Windows `tahoma.ttf` `"ARABIC_TTF"` with zero `.shx` fonts, split wall openings, `BLOCK`/`INSERT` door & window symbols, `ARCH_MM` dimensions, North Arrow, Legend, ModelSpace schedules + Title Block, PaperSpace `ISO_SHEET_PLAN` viewport), true-scale 2-page vector PDF (`(72/25.4)/scale_denominator` pt/mm with embedded Tahoma Arabic RTL & English LTR labels and model-matched Door/Window/Finishes schedules), mandatory automatic Step 07 `extract_dxf` round-trip verification, non-overwriting versioned saves in `05_Design_Drawings` with `409` overwrite guard, optional Gemini JSON draft requiring explicit `owner_confirmed_model=True` confirmation before drawing, bilingual RTL/LTR frontend tab (`Parametric CAD` / `الرسم الهندسي (CAD)`), `79 passed, 4 skipped` full backend `pytest -v`, `4 passed` opt-in real ODA/OCR/research checks including real `ODAFileConverter 27.10.0` Step 11 `DXF -> ACAD2018 DWG -> DXF` round-trip, and `20 passed` frontend Vitest + Vite production build; visual opening/measuring in desktop AutoCAD via `DIST`/`AREA` and desktop PDF scale ruler check by the owner remain `PENDING`)*
- **Branch:** `step-11-parametric-drawing`
- **Depends on:** Step 10 (`bc3cf49`, PR `#18` merged)

## 1. Scope Done

### First Commit (`fd4ce35`) — Step 10 BOQ Honesty Fixes (`(a)`, `(b)`)
1. **(a) Default CAD Geometric Contour/Linear Sums to `Extracted-Needs-Check` (`backend/app/services/boq.py`, `backend/tests/test_boq.py`, `frontend/src/components/BoqView.tsx`):**
   - Kept `Extracted-Verified` strictly for deterministic block insert counts (`block_insert`) and items/rows explicitly marked verified by the owner; defaulted CAD contour area sums and linear length sums (which warn *"not net building area; verify openings/overlaps"*) cleanly to `Extracted-Needs-Check`.
2. **(b) Block Insert Real Entity Layer Grouping + `"N of M"` Omission Disclosure (`backend/app/services/extractors/cad.py`, `boq.py`, `boq_export.py`, `tests/test_boq.py`):**
   - Updated `block_insert_groups` to group deterministically by `(block_name, entity.dxf.layer)` (preserving real DXF layer names instead of `'ModelSpace'`, and recovering legacy CP1256 Arabic block/layer names via Step 07B mojibake recovery).
   - Recorded `omission_summary` metadata whenever extracted CAD/BIM items/groups are filtered or omitted, surfacing an explicit `"Included N of M extracted items/groups"` note in BOQ audit checks and XLSX/CSV headers/summaries.

### Step 11 — Parametric Drawing Engine (`0` AI Tokens for Geometry, Drafting & Schedules)
1. **Database Schema & Reversible Migration (`backend/app/db/models.py`, `backend/alembic/versions/0009_step11_parametric_drawings.py`):**
   - Added `parametric_drawings` table storing drawing metadata (`drawing_no`, `title`, `scale_denominator`, `paper_size`, `units="mm"`, `classification`, `revision`, `version`, `status`, `round_trip_passed`, `ai_suggested`, `model_json`, `computed_metrics_json`, `token_usage_json`) with canonical 5-label `classification` `CHECK` constraint.
   - Added nullable `drawing_id` FK onto `deliverables` and serialized it in `DeliverableOut` (`schemas/reports.py`, `review_reports.py`, `boq.py`, `parametric_drawings.py`).
2. **Code-Only Shoelace Room Computation (`backend/app/schemas/drawings.py`, `backend/app/services/parametric_cad.py`):**
   - Configured `RoomSpec` with `extra="ignore"` so any manually injected or AI-hallucinated `area` / `area_m2` fields are discarded cleanly upon validation.
   - `compute_room_metrics()` computes exact 2D polygon area (`mm²` and `m²`), perimeter (`m`), and centroid (`mm`) deterministically in Python for both orthogonal bounding rooms and arbitrary `polygon_mm` shapes (such as L-shaped halls).
3. **Standard-Layer `ezdxf` Millimetre DXF Engine (`backend/app/services/parametric_cad.py`):**
   - Header sets `$INSUNITS = 4` (Millimetres) and `$MEASUREMENT = 1` (Metric).
   - Creates standard CAD layers: `A-WALL`, `A-AREA`, `A-DOOR`, `A-WIND`, `A-ANNO-TEXT`, `A-ANNO-DIMS`, `A-ANNO-SYMB`, `A-ANNO-TTLB`.
   - Splits wall spans around intersecting door and window openings (`_split_walls_around_openings`), creates reusable door swing & double-glazed window `BLOCK` definitions and places `INSERT` references on `A-DOOR` / `A-WIND`.
   - Configures `"ARABIC_TTF"` and `"Standard"` text styles exclusively with Windows TrueType **`tahoma.ttf`** (zero `.shx` fonts) preserving logical UTF-8 Arabic room names + English room labels and computed areas (`m²`).
   - Adds associative `ARCH_MM` linear dimensions, North Arrow (`A-ANNO-SYMB`), Legend, ModelSpace schedules/title block, and PaperSpace `ISO_SHEET_PLAN` scaled layout viewport + Title Block (`Rev`, `Classification`, `Scale`, `Units=mm`, `Notes`).
4. **True-Scale 2-Page Vector PDF + Model-Matched Schedules (`backend/app/services/parametric_cad.py`):**
   - Page 1 draws exact vector walls, room polygons, door arcs, window mullions, dimension lines, calibration scale bar, North Arrow, Legend, and Title Block on ISO sheet sizes (`A3` default, `A4`/`A2`/`A1`) using exact coordinate factor `(72.0 / 25.4) / scale_denominator` (`pt` per real `mm`).
   - Page 2 renders model-matched **Door Schedule**, **Window Schedule**, and **Room Areas & Finishes Schedule** with embedded `Tahoma` Arabic RTL (`dir="rtl"`) and English LTR HTML tables via `pymupdf.Archive`.
5. **Automatic Step 07 Round-Trip Verification & Non-Overwriting `05_Design_Drawings` Saves (`parametric_cad.py`, `parametric_drawings.py`, `api/drawings.py`):**
   - Immediately after saving `.dxf`, `verify_dxf_round_trip()` re-reads the file through Step 07 `extract_dxf()`, checking `$INSUNITS == 4`, `units_doubtful == False`, TrueType styles present with `uses_shx_font == False`, room polygon count & total `m²` (`abs(diff) <= 0.01 m²`), and exact `A-DOOR` / `A-WIND` `INSERT` counts.
   - Writes versioned files to `05_Design_Drawings/<slug>_<short>_v<N>.{dxf,pdf}` with `FileExistsError -> HTTP 409 Conflict` overwrite guard and registers SHA-256 checksums in `Deliverable`.
6. **Optional AI Draft Guard (`0` Tokens Default) & Bilingual UI (`parametric_drawings.py`, `ParametricDrawingView.tsx`, `DeliverablesView.tsx`, `App.tsx`):**
   - `/api/parametric-drawings/clinic-preset` provides the synthetic 5-room clinic preset (`80.00 m²`, 8 walls, 5 doors `D1/D2/D3`, 4 windows `W1/W2`).
   - Optional `/api/projects/{id}/parametric-drawings/suggest-model` uses Step 04-tracked `execute_provider_request` to draft JSON only; `generate_parametric_drawing` rejects (`HTTP 422`) any `ai_suggested=True` payload unless `owner_confirmed_model=True`, spending `0` AI tokens on CAD/PDF generation.
   - Added bilingual Arabic RTL & English LTR **الرسم الهندسي (CAD) / Parametric CAD** tab (`ParametricDrawingView.tsx`) and `05_Design_Drawings` filter option (`DeliverablesView.tsx`).

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0009_step11_parametric_drawings.py`
- `<repo>/backend/app/api/drawings.py`
- `<repo>/backend/app/schemas/drawings.py`
- `<repo>/backend/app/services/parametric_cad.py`
- `<repo>/backend/app/services/parametric_drawings.py`
- `<repo>/backend/tests/test_drawings.py`
- `<repo>/frontend/src/components/ParametricDrawingView.tsx`
- `<repo>/docs/reports/step-11.md`

### Changed
- `<repo>/backend/app/db/models.py` *(Step 11 `ParametricDrawing`, `Deliverable.drawing_id`, `Project.parametric_drawings`)*
- `<repo>/backend/app/main.py` *(registered `drawings_router`)*
- `<repo>/backend/app/schemas/reports.py` *(added `DeliverableOut.drawing_id`)*
- `<repo>/backend/app/services/boq.py` *(BOQ honesty fixes + `DeliverableOut.drawing_id`)*
- `<repo>/backend/app/services/boq_export.py` *(omission summary `"N of M"` disclosure in XLSX/CSV exports)*
- `<repo>/backend/app/services/extractors/cad.py` *(block insert `(block_name, real_layer)` grouping + omission counts)*
- `<repo>/backend/app/services/review_reports.py` *(`DeliverableOut.drawing_id`)*
- `<repo>/backend/tests/test_boq.py` *(added `test_step10_honesty_fixes_geometric_needs_check_real_block_layer_and_n_of_m`)*
- `<repo>/backend/tests/test_cad_bim.py` *(updated for real entity-layer block grouping)*
- `<repo>/backend/tests/test_migrations.py` *(added `parametric_drawings` to `EXPECTED_TABLES`)*
- `<repo>/docs/DECISIONS.md` *(`ADR-020`)*
- `<repo>/frontend/src/App.test.tsx` *(Step 11 `ParametricDrawingView`, `05_Design_Drawings`, and API Vitest coverage)*
- `<repo>/frontend/src/App.tsx` *(`drawings` tab integration)*
- `<repo>/frontend/src/api.ts` *(Step 11 parametric drawing endpoints)*
- `<repo>/frontend/src/components/BoqView.tsx` *(label alignment for BOQ honesty fixes)*
- `<repo>/frontend/src/components/DeliverablesView.tsx` *(added `05_Design_Drawings` folder filter option)*
- `<repo>/frontend/src/types.ts` *(Step 11 TypeScript interfaces)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Sanitized Synthetic Clinic Sample Output (`0` AI Tokens)

Generated directly from `build_synthetic_clinic_preset()` (`10000 x 8000 mm` layout at `1:100` on `ISO A3`):

```text
ROOM: R-01 | Reception & Waiting | 24.00 m2 | perim=20.00 m
ROOM: R-02 | Consultation Room 1 | 16.00 m2 | perim=16.00 m
ROOM: R-03 | Medical Corridor | 12.00 m2 | perim=22.40 m
ROOM: R-04 | Consultation Room 2 | 14.00 m2 | perim=15.60 m
ROOM: R-05 | Sterilization & WC | 14.00 m2 | perim=15.60 m
DOOR: D1 | 1200x2200 mm | qty=1 | right
DOOR: D2 | 900x2100 mm | qty=3 | left / right
DOOR: D3 | 800x2100 mm | qty=1 | right
WIN: W1 | 1800x1200 sill=900 mm | qty=3
WIN: W2 | 800x600 sill=1600 mm | qty=1
PDF_META: {"pt_per_model_mm": 0.02834646, "plan_width_pt": 289.1339, "plan_height_pt": 232.4409}
ROUND_TRIP: {"passed": true, "insunits_code": 4, "units": "mm", "units_doubtful": false, "ttf_font_styles": ["Standard:tahoma.ttf", ..., "ARABIC_TTF:tahoma.ttf"], "uses_shx_font": false, "expected_room_count": 5, "extracted_area_contour_count": 5, "expected_total_area_m2": 80.0, "extracted_total_area_m2": 80.0, "area_diff_m2": 0.0, "expected_doors_count": 5, "extracted_doors_count": 5, "expected_windows_count": 4, "extracted_windows_count": 4, "mismatches": []}
```

Additionally verified in `test_step11_synthetic_clinic_parametric_dxf_pdf_schedules_and_roundtrip`:
- Vector PDF spans measured via `pymupdf` `page.get_drawings()`: `10000 mm` corridor span at `1:100` equals `283.4646 pt` (`100.0 * 72 / 25.4`), and at `1:50` (`v2`) equals `566.9291 pt` (`200.0 * 72 / 25.4`), confirming exact vector scaling.

## 4. Tests Run (Unedited Summary & Real External Output)

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 83 items

backend\tests\test_boq.py::test_step10_dxf_ifc_quantities_respect_confirmed_unit_and_never_silent_convert PASSED [  1%]
backend\tests\test_boq.py::test_step10_unsourced_rates_blocked_sourced_accepted_configurable_currency_and_xlsx_live_formulas PASSED [  2%]
backend\tests\test_boq.py::test_step10_import_xlsx_and_pdf_boqs_and_seeded_checks_duplicates_missing_units_arithmetic PASSED [  3%]
backend\tests\test_boq.py::test_step10_honesty_fixes_geometric_needs_check_real_block_layer_and_n_of_m PASSED [  4%]
backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  6%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  7%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  8%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  9%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [ 10%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [ 12%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 13%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 14%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 16%]
backend\tests\test_cad_bim.py::test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area PASSED [ 18%]
backend\tests\test_cad_bim.py::test_extract_dxf_marks_area_bearing_layers_and_groups_with_non_net_label PASSED [ 19%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 20%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 21%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 22%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 24%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 25%]
backend\tests\test_drawings.py::test_step11_synthetic_clinic_parametric_dxf_pdf_schedules_and_roundtrip PASSED [ 26%]
backend\tests\test_drawings.py::test_step11_ai_suggest_requires_owner_confirmation_and_strips_ai_areas PASSED [ 27%]
backend\tests\test_drawings.py::test_step11_l_shaped_polygon_shoelace_area_and_roundtrip PASSED [ 28%]
backend\tests\test_drawings.py::test_step11_existing_version_path_returns_409_and_leaves_file_untouched PASSED [ 30%]
backend\tests\test_drawings.py::test_optin_real_oda_step11_parametric_dxf_roundtrip SKIPPED [ 31%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 32%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 33%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 34%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 36%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 37%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 38%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 39%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 40%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 42%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 43%]
backend\tests\test_extraction.py::test_arabic_native_pdf_cid_or_reversed_text_triggers_300dpi_ocr_and_never_not_needed PASSED [ 44%]
backend\tests\test_extraction.py::test_twelve_page_scanned_pdf_reconciles_all_pages_including_blank_and_failed PASSED [ 45%]
backend\tests\test_extraction.py::test_ocr_per_page_tesseract_mean_confidence_and_low_confidence_flag PASSED [ 46%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 48%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 49%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 50%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 51%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 53%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 54%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 55%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 56%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 57%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 59%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 60%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 61%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 62%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 63%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 65%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 66%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 67%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 68%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 69%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 71%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 72%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 73%]
backend\tests\test_reports.py::test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download PASSED [ 74%]
backend\tests\test_reports.py::test_step09_ai_enhance_caps_prompt_enforces_ref_links_versions_cleanly_and_checks_step04 PASSED [ 75%]
backend\tests\test_reports.py::test_step09_only_cites_reliable_text_and_excludes_failed_blank_cid_reversed_or_low_confidence PASSED [ 77%]
backend\tests\test_reports.py::test_step09b_cad_area_bearing_layers_confirmed_unit_and_no_none_unit PASSED [ 78%]
backend\tests\test_reports.py::test_step09b_dxf_vs_dwg_mismatch_raises_high_reconciliation_and_withholds_conflicting_areas PASSED [ 79%]
backend\tests\test_reports.py::test_step09b_ocr_separated_document_register_no_boilerplate_and_showing_n_of_m_appendix PASSED [ 80%]
backend\tests\test_reports.py::test_step09_leftovers_cited_sources_only_no_none_unconfirmed_other_file_and_v2_revision_note PASSED [ 81%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 83%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 84%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 85%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 86%]
backend\tests\test_research.py::test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload PASSED [ 87%]
backend\tests\test_research.py::test_research_quality_gate_bloomsbury_login_wall_cookie_wall_and_photo_archive PASSED [ 89%]
backend\tests\test_research.py::test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call PASSED [ 90%]
backend\tests\test_research.py::test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize PASSED [ 91%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 92%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 95%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 97%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

================== 79 passed, 4 skipped in 136.78s (0:02:16) ===================
```

### Opt-In Real External Checks (`RUN_REAL_ODA=1`, `RUN_REAL_OCR=1`, `RUN_REAL_RESEARCH=1`)

```text
> $env:RUN_REAL_ODA="1"; $env:RUN_REAL_OCR="1"; $env:RUN_REAL_RESEARCH="1"; & "backend\.venv\Scripts\pytest.exe" backend/tests -k "optin_real" -v -s
============================= test session starts =============================
collecting ... collected 83 items / 79 deselected / 4 selected

backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/.../v1/r1/converted/sample_clinic_plan.dxf
PASSED
backend\tests\test_drawings.py::test_optin_real_oda_step11_parametric_dxf_roundtrip
STEP 11 REAL ODA ROUND-TRIP: version=27.10.0 | dwg_bytes=24556 | insunits=4 (mm) | area=80.0 m2 | doors=5 | windows=4
PASSED
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300, mean_conf=91.86): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
ARABIC UNRELIABLE NATIVE RECOVERED (status=ocr_applied (native text unreliable), mean_conf=93.88): 'في من على إلى مشروع مستشفى طرابلس التعليمي'
PASSED
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data
LIVE RESEARCH SAMPLE: provider=duckduckgo_lite | total=3 | accessible=1 | inaccessible=2 | est_prompt_tokens=1172 | ...
PASSED

====================== 4 passed, 79 deselected in 16.75s ======================
```

### Frontend Suite (`vitest` + `tsc --noEmit` + `vite build`)

```text
✓ src/App.test.tsx (20 tests) 59ms
Test Files 1 passed (1) | Tests 20 passed (20) | Duration 673ms
tsc --noEmit && vite build -> 36 modules transformed -> built in 537ms
```

### Secret Scan & Repo Hygiene
- `gitleaks detect --source . --log-opts="--all"` across `57 commits`: `no leaks found`.
- `gitleaks dir` across `backend/app`, `backend/alembic`, `backend/tests`, `frontend/src`, `docs`, `scripts`: `no leaks found`.
- `git diff main -- .github CLAUDE.md`: empty (protected files untouched).
- UTF-8 BOM check across all changed/created files: `BOM_FILES: []`.

## 5. Known Limits & Owner Visual Review Needed
1. **Desktop AutoCAD / Viewer Visual & Command Inspection (`PENDING` owner check):** While programmatic `ezdxf` checks and real `ODAFileConverter 27.10.0` `DXF -> ACAD2018 DWG -> DXF` round-trip (`$INSUNITS=4`, `80.0 m2`, `5` doors, `4` windows) pass cleanly, the generated `.dxf` has not yet been visually inspected in desktop AutoCAD using native `DIST` and `AREA` commands and visual Arabic TrueType `Tahoma` glyph rendering inspection.
2. **True-Scale Vector PDF Physical Print / Viewer Calibration (`PENDING` owner check):** Vector PDF coordinates are verified mathematically (`10000 mm` @ `1:100` = `283.4646 pt` and @ `1:50` = `566.9291 pt`), yet opening in Adobe/Edge viewer and measuring printed ISO A3 (`100% Actual Size`) output with a physical scale ruler awaits the owner.
3. **2D Orthogonal & Polygonal Model Scope:** Step 11 generates 2D parametric architectural plans (rooms, thick walls cleanly split around openings, door/window blocks, dimensions, schedules, title block). Curved arc walls, structural column grids, MEP ducting layers, and multi-storey elevations/sections are outside Step 11 scope and remain future extensions.
4. **Windows TrueType Font Dependency:** TrueType style `"ARABIC_TTF"` references Windows system font `tahoma.ttf` (`C:/Windows/Fonts/tahoma.ttf`). If run in a headless Linux container without Microsoft core fonts installed, PDF HTML rendering falls back to sans-serif unless `tahoma.ttf` or an equivalent Arabic TrueType font is supplied.

## 6. Checklist
- [x] BOQ honesty fixes `(a)` (`Extracted-Needs-Check` for geometric sums) and `(b)` (real entity layer grouping + `"N of M"` omission note) landed in commit `fd4ce35`
- [x] Room/wall/door/window millimetre JSON model (`units="mm"`) with Python-computed Shoelace areas (typed/AI areas stripped/ignored)
- [x] Standard-layer `ezdxf` DXF (`$INSUNITS=4`, `tahoma.ttf` Arabic, zero `.shx`, blocks, dimensions, North Arrow, Legend, ModelSpace + PaperSpace `ISO_SHEET_PLAN`)
- [x] True-scale vector PDF + model-matched Door, Window, and Finishes Schedules
- [x] Automatic Step 07 `extract_dxf` round-trip verification (`round_trip_passed == True`)
- [x] Non-overwriting versioned saves in `05_Design_Drawings` (`v1`, `v2`, `409` overwrite guard, SHA-256 download)
- [x] Optional AI draft endpoint requires explicit `owner_confirmed_model=True` before drawing (`0` tokens for normal CAD generation)
- [x] `ADR-020` added in `docs/DECISIONS.md`
- [x] Branch pushed without touching `main` (Step 11 status marked **`PARTIAL`** until owner desktop CAD/PDF visual inspection)
