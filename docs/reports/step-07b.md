# Step 07b — CAD Unit Plausibility Verification, Owner Unit Override, and CP1256 Arabic Recovery

- **Date:** 2026-11-20
- **Status:** **PARTIAL** *(automated unit plausibility checks, null `area_m2` gating, owner unit confirmation API & UI, legacy CP1256 Arabic recovery with raw preservation, `net_subtracted_area_native` rename, full backend `pytest -v`, live `RUN_REAL_ODA=1` (`27.10.0`), live `RUN_REAL_OCR=1` (`5.5.3`), frontend Vitest/build, and `gitleaks` scan pass on synthetic committed fixtures; Step 07 overall remains `PARTIAL` pending owner UI verification, owner re-run on local real DWG drawings, and AutoCAD `AREA` comparison including arc bulges)*
- **Branch:** `step-07b-units-and-encoding`
- **Depends on:** Step 07 (`0b84590`, PR `#13` merged to `main`; Step 07 stays `PARTIAL`)

## 1. Root Causes Exposed by Real-World DWG Testing & Fixes Applied

Real-world DWG ingestion via ODA File Converter (`$INSUNITS=1` with `3.0 / 4.0 / 4.9` dimensions and `7032.67` / perimeter `412.5` closed polyline, plus legacy Windows CP1256 mojibake block/text names such as `ÔÌÑÉ ãáæäÉ`) exposed two extraction defects, alongside a schema naming cleanup:

1. **Units Plausibility Verification & Owner-Confirmed Drawing Unit Override (`backend/app/services/extractors/cad.py`, `backend/app/services/extraction.py`, `backend/app/api/extraction.py`, `backend/app/schemas/extraction.py`, `frontend/src/components/ProjectFilesPanel.tsx`):**
   - Added `_assess_cad_unit_plausibility()` executing **before** emitting metric `area_m2` values across `LWPOLYLINE`, `POLYLINE`, `CIRCLE`, and `HATCH` records.
   - Evaluates `$INSUNITS`, `DIMENSION.get_measurement()` values, numeric `DIMENSION` overrides (plus raw-vs-override divergence), and closed polygon areas & perimeters.
   - Whenever `$INSUNITS == 0` (unitless), `$INSUNITS` is unknown, or declared units are geometrically inconsistent with drawing dimensions/polygons (e.g., `$INSUNITS=1` inches while dimensions measure `3.0, 4.0, 4.9` and closed area `7032.67` with perimeter `412.5`), sets:
     - `units_doubtful = True`, `units_status = "doubtful"` (or `"unitless"` for `$INSUNITS=0`),
     - `area_m2 = None` (`null` in JSON) on all `closed_areas` entries and `cad_polyline_area` items,
     - untouched `area_native`, `area_native_unit`, and `perimeter_native`,
     - explicit warning `"units doubtful - owner must confirm drawing unit"`.
   - Added explicit per-extraction owner unit confirmation without ever altering original files or raw native numbers:
     - `POST /api/files/{file_id}/extract` accepts optional `confirmed_unit` (`mm`, `cm`, `dm`, `m`, `km`, `in`, `ft`, `yd`, `mi`, `unitless`),
     - `POST /api/extractions/{extraction_id}/confirm-unit` accepts `{"confirmed_unit": "..."}`, persists immutable `03_Analysis/extractions/<file_id>/v<ver>/r<run>/unit_confirmation_s<k>.json`, records `AuditLog(action="file.drawing_unit_confirmed")`, and computes `area_m2` deterministically using the confirmed unit's scale factor while preserving `area_native` and `area_native_unit` unchanged.
     - Updated `ProjectFilesPanel.tsx` with a clear `"units doubtful - owner must confirm drawing unit"` warning banner and unit selector/confirm action.

2. **CP1256 / ANSI Arabic Mojibake Recovery Preserving Raw Strings (`backend/app/services/extractors/cad.py`, `frontend/src/components/ProjectFilesPanel.tsx`):**
   - Added `_decode_cad_text()` decoding DXF Unicode escapes and legacy Windows CP1256 Arabic strings that arrived mangled as Latin-1 / CP1252 (`ANSI_1252` or lost `$DWGCODEPAGE`) during ODA/DXF processing (e.g., `'ÔÌÑÉ ãáæäÉ'` → `'شجرة ملونة'`, `'ÛÑÝÉ æ ãÎÒä'` → `'غرفة و مخزن'`, `'ÃÚãÏÉ_Arch'` → `'أعمدة_Arch'`).
   - Applied consistently across layer names, entity layers, block names, XREF paths, `TEXT`, `MTEXT`, `INSERT.attribs`, `DIMENSION` overrides, and `HATCH` pattern names while preserving the raw original string alongside (`raw_name` in layer/block inventories, `raw_text`, `raw_layer`, `raw_block_name`, and `raw_override_text`).
   - Verified token-context guards preserve valid Western European accented words (`Café`, `Résumé`) and engineering symbols (`Ø 20mm`, `20 m²`) untouched, and rendered raw strings beside decoded Arabic in the UI layer/block tables.

3. **HATCH Subtracted Hole Field Rename (`backend/app/services/extractors/cad.py`, `backend/tests/test_cad_bim.py`):**
   - Renamed `island_hole_area_native` to `net_subtracted_area_native` in `HATCH` quantity records and warning text, keeping `gross_area_native`, `island_count`, `area_basis`, and `area_native`.

## 2. Files Created / Changed

### Created
- `<repo>/docs/reports/step-07b.md`

### Changed
- `<repo>/backend/app/schemas/extraction.py`
- `<repo>/backend/app/services/extractors/cad.py`
- `<repo>/backend/app/services/extraction.py`
- `<repo>/backend/app/api/extraction.py`
- `<repo>/backend/tests/test_cad_bim.py`
- `<repo>/frontend/src/types.ts`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/components/ProjectFilesPanel.tsx`
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/docs/DECISIONS.md` (`ADR-014`)

*(No client drawings or proprietary files were committed to git; all new tests construct synthetic in-memory DXFs cleanly.)*

## 3. Verification Commands Run & Full Unedited Outputs

> Re-verified on the final committed code state; exact committed HEAD SHA verification output is also recorded in the Step 07b pull request.

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 53 items

backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  1%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  3%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  5%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  7%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [  9%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [ 11%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 13%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 16%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 18%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 20%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 22%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 24%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 26%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 28%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 30%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 32%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 33%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 35%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 37%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 39%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 41%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 43%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 45%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 47%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 49%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 50%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 52%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 54%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 56%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 58%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 60%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 62%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 64%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 66%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 67%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 69%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 71%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 73%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 75%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 77%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 79%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 81%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 83%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 84%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 86%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 88%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 90%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 92%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 94%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

======================= 51 passed, 2 skipped in 56.91s ========================
```

### Opt-In Real ODA File Converter Run (`RUN_REAL_ODA=1`)

```text
> $env:RUN_REAL_ODA='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests/test_cad_bim.py -k test_optin_real_oda_converter_dwg_to_dxf -v -s
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 10 items / 9 deselected / 1 selected

backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf 
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/d1c5db9b-180a-414c-b513-c6c8380e3de4/v1/r1/converted/sample_clinic_plan.dxf
PASSED

======================= 1 passed, 9 deselected in 4.99s =======================
```

### Opt-In Real Tesseract OCR Run (`RUN_REAL_OCR=1`)

```text
> $env:RUN_REAL_OCR='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests/test_extraction.py -k test_optin_real_tesseract_ara_eng_on_committed_fixture -v -s
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 10 items / 9 deselected / 1 selected

backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture 
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PASSED

======================= 1 passed, 9 deselected in 6.17s =======================
```

### Frontend Unit Tests & Production Build

```text
> npm.cmd --prefix frontend test -- --run
 ✓ src/App.test.tsx (15 tests) 28ms
 Test Files  1 passed (1)
      Tests  15 passed (15)

> npm.cmd --prefix frontend run build
✓ 32 modules transformed.
✓ built in 460ms
```

### Secret Scan (`gitleaks`)

```text
> gitleaks detect --source . -v --no-banner
6:26PM INF 41 commits scanned.
6:26PM INF no leaks found
```

## 4. Acceptance Criteria & Pending Owner Checks

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| Suspect / unitless CAD drawings never present unverified `m2` (`area_m2 = null`, native preserved, clear warning) | **PASS (Synthetic)** | `test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit` verifies `$INSUNITS=1` (`in`) with dimensions `3.0, 4.0, 4.9` and closed area `7032.67` (`perim=412.5`) flags `units_doubtful=True`, emits `"units doubtful - owner must confirm drawing unit"`, preserves `area_native=7032.67`, sets `area_m2=None`, and does **not** falsely flag valid `$INSUNITS=4` (`3000 x 4000 mm` = `12.0 m2`). |
| Per-extraction owner unit override computes `area_m2` cleanly without altering native values or originals | **PASS** | `POST /api/extractions/{id}/confirm-unit` (`confirmed_unit="m"`), `POST /api/files/{id}/extract` (`confirmed_unit="m"`), immutable `unit_confirmation_s1.json`, `file.drawing_unit_confirmed` audit log, `sha256_after == original`, plus Vitest UI test. |
| CP1256 mojibake Arabic recovered across blocks/layers/text while keeping raw values & protecting Latin/symbols | **PASS (Synthetic)** | `test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin` proves `'ÔÌÑÉ ãáæäÉ'` → `'شجرة ملونة'`, `'ÛÑÝÉ æ ãÎÒä'` → `'غرفة و مخزن'`, `'ÃÚãÏÉ_Arch'` → `'أعمدة_Arch'`, keeping raw strings beside decoded UTF-8 and preserving `'Café'`, `'Résumé'`, `'Ø 20mm'`, `'20 m²'`. |
| Rename `island_hole_area_native` → `net_subtracted_area_native` | **PASS** | `test_extract_dxf_hatch_with_island_subtracts_hole_area` verifies `net_subtracted_area_native == 20.0`, `gross_area_native == 100.0`, `area_native == 80.0`. |
| Owner local re-test on real DWG + interactive UI check + AutoCAD `AREA` comparison (including arc bulges) | **PENDING** | Awaiting owner check via `scripts/start.bat` confirming doubtful-unit warning, owner unit confirmation to `m`, decoded Arabic names, and AutoCAD `AREA` / arc-bulge comparison. *(Status stays `PARTIAL`.)* |

## 5. Questions & Next Steps for Owner
1. Pull `step-07b-units-and-encoding` locally (after reviewing PR), launch `<repo>/scripts/start.bat`, and re-extract your local `.dwg` file:
   - Confirm `area_m2` shows as `null` (`—`) alongside `"units doubtful - owner must confirm drawing unit"` and raw `area_native = 7032.67 sq_in`.
   - Confirm decoded Arabic block/layer names (`شجرة ملونة`, etc.) and raw names alongside them.
   - Select **`m (meters)`** and click **Confirm Unit / تأكيد الوحدة** to verify `area_m2 = 7032.67` updates cleanly while native values remain untouched.
2. Step 07 remains **`PARTIAL`** until owner UI verification and AutoCAD `AREA` (arc-bulge) check complete.
