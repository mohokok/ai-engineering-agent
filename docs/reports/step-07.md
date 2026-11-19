# Step 07 — Drawing (DXF / DWG via ODA) and BIM (IFC) Ingestion

- **Date:** 2026-11-19
- **Status:** **PARTIAL** *(all automated backend DXF, DWG-via-ODA, HATCH-island net area, `409` converted-dir isolation, IFC, Gemini Vision mock, frontend UI, hygiene, secret scan, real ODA `27.10.0`, and real Tesseract `5.5.3` checks passed on committed sanitized fixtures; awaiting owner UI check, real-owner DXF/DWG inventory, and AutoCAD `AREA` comparison including arc bulges)*
- **Branch:** `step-07-cad-bim-extraction`
- **Depends on:** Step 06 (`47117cb`, PR `#12` merged to `main` after `PASS step 06`)

## 1. Scope Done

- **Pinned Step 07 Python CAD/BIM dependencies (`<repo>/backend/requirements.txt`):**
  - Pinned verified libraries in `backend/.venv`: `ezdxf==1.4.5` and `ifcopenshell==0.9.0.post1` (using existing `pymupdf==2.1` via `ezdxf.addons.drawing.pymupdf.PyMuPdfBackend` for preview PNG generation). Did **not** install any OS software or edit `PATH`.
- **ODA File Converter detection & isolated DWG conversion (`<repo>/backend/app/services/extractors/oda.py`, `<repo>/backend/app/core/config.py`, `<repo>/backend/app/services/extraction.py`):**
  - Added `Settings.oda_file_converter_path: str = ""` (`ODA_FILE_CONVERTER_PATH` in `<repo>/.env.example`).
  - `probe_oda()` / `detect_oda()` checks in strict order: (1) `ODA_FILE_CONVERTER_PATH`, (2) system `PATH` (`ODAFileConverter` / `TeighaFileConverter`), and (3) standard Program Files locations (`<ProgramFiles>/ODA/ODAFileConverter*/ODAFileConverter.exe`), reporting `"not installed - pending owner"` cleanly when absent and `"installed"` (`27.10.0` detected on this PC).
  - Original read-only `.dwg` in `02_Original_Drawings/` is **never** passed directly to ODA or mutated; ONLY the target `.dwg` bytes are copied into an isolated temporary directory for ODA CLI execution.
  - Converted `ACAD2018` `.dxf` output writes solely into a fresh non-overwritable `03_Analysis/extractions/<file_id>/v<ver>/r<run>/converted/` folder (`extraction.py` and `convert_dwg_to_dxf()` refuse HTTP `409 Conflict` / `FileExistsError` if `r<run>` or `r<run>/converted` already exists on disk, leaving pre-existing files untouched). Checks `sha256_after == sha256_before` on original `.dwg` before writing output JSON, and persists `FileExtraction(status="failed")` + `file.extraction_failed` audit events when ODA is missing (`422`).
- **Deterministic DXF reader & NET HATCH island subtraction (`<repo>/backend/app/services/extractors/cad.py`):**
  - Extracts `$INSUNITS` verbatim (`0=unitless`, `4=mm`, `5=cm`, `6=m`, etc.) without guessing scale conversions when `$INSUNITS == 0`.
  - Inventories layers (preserving Arabic names e.g. `جدران-معمارية`, color, linetype, on/frozen/locked flags, ModelSpace vs PaperSpace counts), blocks (`DOOR_باب_D1`, insert counts, XREF flag `blk.block.is_xref` + `xref_path`), `TEXT`, `MTEXT` (keeping `raw_text`), `INSERT.attribs`, `DIMENSION` (`get_measurement()` + explicit override text), closed `LWPOLYLINE` / 2D `POLYLINE` / `CIRCLE` areas & perimeters, and ModelSpace A4 PNG preview (`page_001.png`).
  - Computes **NET `HATCH` area** via `_compute_hatch_areas()` and `ezdxf.path.nesting.make_polygon_structure` + `hatch_style`: outer loop minus inner island cutout holes, explicitly recording `gross_area_native`, `island_hole_area_native`, `island_count`, `area_basis`, and `area_native` (verified on committed fixture `sample_hatch_island.dxf`: `100.0 gross - 20.0 island = 80.0 net m2`).
- **Deterministic IFC BIM reader (`<repo>/backend/app/services/extractors/bim.py`):**
  - Reads IFC schema (`IFC4`/`IFC2X3`), `IfcProject.UnitsInContext` units, `IfcBuildingStorey` hierarchy, `IfcSpace` (Name, LongName, GlobalId, Storey, explicit `Qto_*` / `Pset_*` areas or `null` + warning when unauthored — never inventing areas), `IfcWall`, `IfcDoor`, `IfcWindow` with `Pset_*` & `Qto_*`, plus `product_counts` summary and B-rep/3D limit warnings.
- **PDF / CAD PNG Gemini Vision drawing summary (`<repo>/backend/app/services/extraction.py`, `<repo>/backend/app/api/extraction.py`):**
  - `POST /api/extractions/{extraction_id}/vision-summary` routes rendered `150 DPI` page PNGs through `execute_provider_request`, persists immutable `vision_page_<N>_s<k>.json` artifacts + audit entries, and attaches mandatory `ai_interpretation_only: true` + non-measurement disclaimer.
- **Format Support Matrix & Drawing/BIM Inventory UI (`<repo>/frontend/src/components/ProjectFilesPanel.tsx`, `<repo>/frontend/src/types.ts`, `<repo>/frontend/src/api.ts`, `<repo>/frontend/src/App.tsx`):**
  - Displays ODA File Converter status alongside Tesseract OCR, collapsible **Format Support Matrix**, CAD/BIM counts in `.meta-grid`, **Drawing & BIM Inventory Table**, and **Gemini Vision Summary** button + warning banner.
- **Sanitized committed test fixtures (`<repo>/backend/tests/fixtures/`):**
  - `sample_clinic_plan.dxf` (`6x4 = 24.00 m2`, L-shape `14.00 m2`, Arabic layers/blocks/text, PaperSpace sheet text).
  - `sample_clinic_plan.dwg` (sanitized `ACAD2018` DWG compiled from `sample_clinic_plan.dxf`, explicitly whitelisted in `.gitignore`).
  - `sample_hatch_island.dxf` (`10x10 = 100.0 m2` outer hatch with `5x4 = 20.0 m2` island cutout hole -> expected net area `80.0 m2`).
  - `sample_clinic_model.ifc` (`IFC4` model with Arabic `IfcProject`, measured `18.75 m2` space, unmeasured waiting room `IfcSpace`, wall, door, window, slab).

## 2. Format Support Matrix (No Native DWG / RVT Claimed)

| Format | Category | Support Level | Engine / Converter | Behaviour & Limits |
| --- | --- | --- | --- | --- |
| `.dxf` | CAD Drawing | **Native** | `ezdxf` + `PyMuPDF` preview | Native extraction of layers, blocks, text/MTEXT/ATTRIB, dimensions, closed polyline/circle/net-hatch areas, `$INSUNITS`, and PNG preview. |
| `.dwg` | CAD Drawing (Binary) | **Converted via ODA** | ODA File Converter → DXF → `ezdxf` | **Not** read natively. Staged in isolated temp folder and converted to `ACAD2018` DXF inside fresh `03_Analysis/.../r<n>/converted/`. Original `.dwg` untouched. |
| `.ifc` | BIM Model | **Native** | `ifcopenshell` | Native schema, SI units, storeys, `IfcSpace`, `IfcWall`, `IfcDoor`, `IfcWindow`, `Pset_*` & `Qto_*`. Other `IfcProduct` types counted only; 3D B-rep geometry not tessellated. |
| `.pdf` | Drawing Sheet / Spec | **Native + AI Summary** | `pdfplumber`, `PyMuPDF`, Tesseract OCR, Gemini Vision | Vector text/tables, `150 DPI` page PNGs, `300 DPI` `ara+eng` OCR, and opt-in Vision summary flagged **AI interpretation only (not measurement)**. |
| `.docx` / `.xlsx` / `.csv` / `.pptx` / `.txt` / `.md` / Raster | Office / Images | **Native** | Step 06 extractors | Same deterministic behavior verified in Step 06. |
| `.rvt` / `.rfa` / `.rte` | Autodesk Revit | **Not supported** | None in Step 07 | Returns HTTP `400`; export `.ifc`, `.dxf`, or `.pdf` from Revit first. |
| `.dgn` / `.dwf` / `.step` / `.stp` / `.iges` / `.igs` / `.obj` / `.stl` / `.gltf` / `.glb` | Deferred CAD / 3D Exchange | **Not supported** | None in Step 07 | Returns HTTP `400`; convert to `.dxf`/`.ifc`/`.pdf` before upload. |

## 3. Files Created / Changed

### Created
- `<repo>/backend/app/services/extractors/oda.py`
- `<repo>/backend/app/services/extractors/cad.py`
- `<repo>/backend/app/services/extractors/bim.py`
- `<repo>/backend/tests/fixtures/sample_clinic_plan.dxf`
- `<repo>/backend/tests/fixtures/sample_clinic_plan.dwg`
- `<repo>/backend/tests/fixtures/sample_hatch_island.dxf`
- `<repo>/backend/tests/fixtures/sample_clinic_model.ifc`
- `<repo>/backend/tests/test_cad_bim.py`
- `<repo>/docs/reports/step-07.md`

### Changed
- `<repo>/.gitignore` *(explicit fixture exception `!backend/tests/fixtures/sample_clinic_plan.dwg` only; all other `*.dwg` remain ignored)*
- `<repo>/backend/app/api/extraction.py`
- `<repo>/backend/app/core/config.py`
- `<repo>/backend/app/schemas/extraction.py`
- `<repo>/backend/app/services/extraction.py`
- `<repo>/backend/app/services/extractors/__init__.py`
- `<repo>/backend/pytest.ini`
- `<repo>/backend/requirements.txt`
- `<repo>/backend/tests/test_extraction.py`
- `<repo>/docs/DECISIONS.md` (`ADR-013`)
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/frontend/src/App.tsx`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/components/ProjectFilesPanel.tsx`
- `<repo>/frontend/src/types.ts`

## 4. Tests Run (Full Unedited Outputs — No Elisions)

### Backend Default Suite (`cd <repo>/backend; .\.venv\Scripts\python.exe -m pytest -v`)

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>/backend/.venv/Scripts/python.exe
cachedir: .pytest_cache
rootdir: <repo>/backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 51 items

tests/test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  1%]
tests/test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  3%]
tests/test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  5%]
tests/test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED  [  7%]
tests/test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [  9%]
tests/test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [ 11%]
tests/test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 13%]
tests/test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 15%]
tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 17%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 19%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 21%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 23%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 25%]
tests/test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 27%]
tests/test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 29%]
tests/test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 31%]
tests/test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 33%]
tests/test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 35%]
tests/test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 37%]
tests/test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 39%]
tests/test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 41%]
tests/test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 43%]
tests/test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 45%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 47%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 49%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 50%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 52%]
tests/test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 54%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 56%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 58%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 60%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 62%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 64%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 66%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [ 68%]
tests/test_providers.py::test_keyring_secret_store_round_trip PASSED     [ 70%]
tests/test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 72%]
tests/test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 74%]
tests/test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 76%]
tests/test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 78%]
tests/test_providers.py::test_debug_logging_never_leaks_api_key PASSED   [ 80%]
tests/test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 82%]
tests/test_providers.py::test_provider_404_model_not_found_handling PASSED [ 84%]
tests/test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 86%]
tests/test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 88%]
tests/test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 90%]
tests/test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 92%]
tests/test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 94%]
tests/test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 96%]
tests/test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
tests/test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

======================= 49 passed, 2 skipped in 40.91s ========================
```
*(The 2 skipped tests in the default run are opt-in external binary tests `test_optin_real_oda_converter_dwg_to_dxf` and `test_optin_real_tesseract_ara_eng_on_committed_fixture`, both executed directly below on this PC.)*

### Opt-In Real ODA File Converter Run (`$env:RUN_REAL_ODA='1'`)

```text
> cd <repo>/backend
> $env:RUN_REAL_ODA='1'; .\.venv\Scripts\python.exe -m pytest tests/test_cad_bim.py -k test_optin_real_oda_converter_dwg_to_dxf -v -s
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>/backend/.venv/Scripts/python.exe
cachedir: .pytest_cache
rootdir: <repo>/backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 8 items / 7 deselected / 1 selected

tests/test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf 
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/<file_id>/v1/r1/converted/sample_clinic_plan.dxf
PASSED

======================= 1 passed, 7 deselected in 3.69s =======================
```

### Opt-In Real Tesseract OCR Run (`$env:RUN_REAL_OCR='1'`)

```text
> cd <repo>/backend
> $env:RUN_REAL_OCR='1'; .\.venv\Scripts\python.exe -m pytest tests/test_extraction.py -k test_optin_real_tesseract_ara_eng_on_committed_fixture -v -s
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>/backend/.venv/Scripts/python.exe
cachedir: .pytest_cache
rootdir: <repo>/backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 10 items / 9 deselected / 1 selected

tests/test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture 
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PASSED

======================= 1 passed, 9 deselected in 4.43s =======================
```

*(Identical unedited outputs re-verified at the exact final committed HEAD SHA are pasted in the Step 07 PR body and final response.)*

## 5. Acceptance Tests & Verification Evidence

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| DXF reader inventories layers, blocks, text, dimensions, polylines, areas, units & Arabic text (sanitized fixture) | **PASS** | `test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits` proves `$INSUNITS=6` (`m`), Arabic layers (`جدران-معمارية`), Arabic block `DOOR_باب_D1` (`insert_count=2`, `DOOR_TAG=D-01`), `MTEXT`/`TEXT` Arabic text, linear dimension (`6.0 m`), and ModelSpace PNG preview on committed `sample_clinic_plan.dxf` |
| DXF deterministic area on synthetic fixtures (closed polylines & HATCH with island hole) | **PASS (Synthetic Fixture Labels Only)** | In committed `sample_clinic_plan.dxf`, deterministic Shoelace calculations returned `24.0 m2` and `14.0 m2`, matching text labels written into our own synthetic fixture (`24.00 m2` / `14.00 m2`) — **not** an external AutoCAD `AREA` dump. In committed `sample_hatch_island.dxf`, `_compute_hatch_areas` subtracted the `20.0 m2` island cutout hole from the `100.0 m2` outer boundary to report `80.0 m2` net (`gross_area_native=100.0`, `island_hole_area_native=20.0`, `island_count=1`) |
| Real-owner DXF / DWG inventory check | **PENDING** | No client/owner drawings are in git; awaiting owner verification on a real work DXF/DWG file inside `start.bat` |
| AutoCAD `AREA` comparison (including a closed polyline with arc bulges) | **PENDING** | Awaiting owner comparison between extracted deterministic polyline/hatch area and AutoCAD `AREA` / `LIST` output on a drawing containing a curved arc-bulge polyline |
| DWG converts to DXF via ODA File Converter; missing converter reported cleanly; originals untouched; existing `r<run>/converted` refused | **PASS** | `test_capabilities_oda_resolution_priority_absent_dwg_and_matrix`, `test_dwg_conversion_pipeline_mocked_preserves_original_and_versions`, `test_dwg_refuses_existing_converted_run_dir_with_409`, and live `test_optin_real_oda_converter_dwg_to_dxf` (`ODAFileConverter 27.10.0`) verify isolation, `sha256_before == sha256_after`, versioned `r{n}/converted/` output, HTTP `409` on existing `r{n}/converted`, and `not installed - pending owner` failure handling |
| IFC lists spaces with areas, walls, doors, windows, properties & quantities without inventing values | **PASS** | `test_extract_ifc_spaces_areas_elements_properties_and_known_limits` verifies `sample_clinic_model.ifc`: `غرفة الفحص 01` (`18.75 m2` from `Qto_SpaceBaseQuantities.NetFloorArea`), `غرفة الانتظار` kept `null` (`not_provided_in_ifc`) with explicit warning, plus wall/door/window `Pset_*`/`Qto_*` |
| PDF/DXF drawing page rendering + Gemini Vision summary labelled as AI interpretation, not measurement | **PASS** | `test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap` + Vitest UI test prove `ai_interpretation_only=True`, mandatory non-measurement disclaimer badge, immutable JSON artifact, and usage ledger logging |
| Interactive owner UI check | **PENDING** | Awaiting owner visual confirmation of the Drawing & BIM Inventory UI inside `<repo>/scripts/start.bat` |

## 6. Decisions Made (Recorded in `<repo>/docs/DECISIONS.md` as `ADR-013`)
- Isolated DWG staging directory for ODA File Converter CLI so `02_Original_Drawings` is never scanned or touched directly; converted DXFs live inside fresh non-overwritable `03_Analysis/.../r{n}/converted/` (HTTP `409` when `r{n}` or `r{n}/converted` already exists).
- Computed net `HATCH` area (`outer - islands`) via `ezdxf.path.nesting.make_polygon_structure` + `hatch_style`, explicitly reporting `gross_area_native`, `island_hole_area_native`, `island_count`, and `area_basis`.
- Reused `file_extractions` JSON columns (`payload_json`, `counts_json`, `rendered_images_json`) and kept Gemini Vision strictly opt-in with `ai_interpretation_only=True`.

## 7. Accuracy Notes and Known Failures

### CAD / DXF / DWG Accuracy Limits
- **Units & Unitless Drawings (`$INSUNITS`):** When `$INSUNITS=0` (`Unitless`) or an unrecognized code is authored, the extractor reports `"unitless"` and omits `area_m2` conversions rather than guessing whether 1 unit represents `mm`, `cm`, `m`, `in`, or `ft` (an explicit warning is attached). Engineers must verify that AutoCAD drawings authored in meters/millimeters have consistent `$INSUNITS` headers (`6=m`, `4=mm`) versus title-block scale notes.
- **External XREFs (`block.is_xref`):** External Reference (`XREF`) block definitions (`block.block.is_xref`) and `xref_path` strings are detected, listed in `drawing_inventory.blocks`, and flagged with a warning (`External XREF block(s) detected...; external referenced DWGs are NOT loaded or resolved`). Geometry inside external XREF target DWGs is **not** merged into entity counts or areas.
- **Model-Space vs. Paper-Space & Viewports:** Entity counts, layers, text items, dimensions, and polyline areas explicitly tag `cad_space="modelspace"` vs `cad_space="paperspace"` across layouts; however, ModelSpace PNG preview rendering (`page_001.png` via `PyMuPdfBackend`) renders **ModelSpace only**, and scaled `VIEWPORT` crops, paper-space title-block clipping, or paper-space layout plot scales are **not** rendered or converted into model-space geometry. Files with PaperSpace entities emit an explicit warning.
- **3D Entities, Meshes & Proprietary Proxy Objects:** `3DSOLID`, `MESH`, `SURFACE`, `BODY`, `3DFACE`, and `3DPOLYLINE` entities are counted and flagged with a warning, NOT volume/surface-integrated deterministically; Autodesk vertical `ACAD_PROXY_ENTITY` objects are flagged as un-decomposed proxies.
- **HATCH Islands & Arc Bulge Flattening:** Closed `LWPOLYLINE` arc bulges (`distance=0.0005`) and `HATCH` boundaries (`distance=0.001`) flatten to polygons for area calculation; `HATCH` net area subtracts inner island holes using geometric containment (`make_polygon_structure`) and respects `hatch_style` (`0=Normal`, `1=Outer`, `2=Ignore`). Extremely tight curved arcs can introduce sub-millimeter chord approximation, hence owner AutoCAD `AREA` verification on an arc-bulge polyline remains explicitly tracked in Section 5.
- **SHX Fonts & Preview Fidelity:** Rendered DXF ModelSpace PNG previews depend on `ezdxf.addons.drawing` glyph substitution when proprietary AutoCAD `.shx` shape fonts are referenced instead of TrueType (`TTF`), whereas underlying `TEXT` / `MTEXT` Unicode character strings extracted from DXF are preserved verbatim in JSON.
- **DWG Conversion Timeout & ODA Versions:** Binary `.dwg` extraction shells out to `ODAFileConverter.exe` converting to `ACAD2018` DXF with a `90s` subprocess timeout; corrupted/password-protected `.dwg` files, unsupported newer DWG revisions beyond ODA `27.10.0`, or missing ODA installations fail cleanly with HTTP `422` leaving original `.dwg` bytes untouched.

### BIM / IFC Accuracy Limits
- **No Fabricated Quantities or Areas:** `extract_ifc` reads ONLY authored Property Sets (`Pset_*`) and Quantity Sets (`Qto_*` / `IfcElementQuantity`). When unauthored, `area` stays `null` (`not_provided_in_ifc`) with an explicit warning.
- **Entity Scope & 3D B-Rep Limits:** Detailed item/property extraction covers `IfcProject` units, `IfcBuildingStorey`, `IfcSpace`, `IfcWall`, `IfcDoor`, and `IfcWindow`; additional structural/MEP `IfcProduct` classes are counted in `product_counts` + warned as summary-only. Visual 3D IFC rendering and clash/B-rep mesh volume checks are not performed.

### PDF Drawing Vision Summary Limit
- **Strict Non-Measurement Rule:** `POST /api/extractions/{extraction_id}/vision-summary` sends a `150 DPI` rendered PNG to Gemini strictly to read legible title blocks/labels/discipline context (`ai_interpretation_only=true`). Pixel-based AI responses **cannot** measure scales, lengths, areas, or element counts reliably and carry a mandatory non-measurement disclaimer.

## 8. Questions or Items Needed from the Owner
- Run `<repo>/scripts/start.bat` and verify:
  1. Interactive **Drawing & BIM Inventory UI** in **Projects & Files**,
  2. Real-owner **DXF and/or DWG** drawing inventory accuracy,
  3. **AutoCAD `AREA` comparison** on a real polyline (including one with **arc bulges**), and optionally Gemini Vision summary if an API key is configured.
- Reply **`PASS step 07`** after reviewing PR `#13` when ready for **Step 08 — Research tool with source log**.

## 9. How the Owner Can See / Try It
1. Launch `<repo>/scripts/start.bat` (auto-detects ODA File Converter `27.10.0` at `<ProgramFiles>/ODA/...` and Tesseract `5.5.3` automatically without changing `PATH`).
2. Open any project in **المشاريع والملفات / Projects & Files** and inspect the **ODA File Converter Status** banner plus **Format Support Matrix**.
3. Upload `.dxf`, `.dwg`, `.ifc`, or `.pdf` files and click **استخراج البيانات / Extract Content** to view units, layers, blocks, closed areas (including net hatch islands), IFC spaces/properties, converted DXF path, ModelSpace PNG preview, and full normalized JSON.

## 10. Ready for Next Step?
**Pending owner UI visual confirmation, real-owner DXF/DWG check, and AutoCAD `AREA` comparison (`PARTIAL`)** — automated Step 07 CAD/BIM extraction, real ODA `27.10.0` conversion, HATCH-island net area, `409` converted-dir isolation, IFC parsing, and Vision disclaimer checks pass cleanly; awaiting owner review and `PASS step 07` to proceed to Step 08.
