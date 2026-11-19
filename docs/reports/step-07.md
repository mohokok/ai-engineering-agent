# Step 07 — Drawing (DXF / DWG via ODA) and BIM (IFC) Ingestion

- **Date:** 2026-11-19
- **Status:** **PARTIAL** *(all automated backend DXF, DWG-via-ODA, IFC, Gemini Vision mock, frontend inventory UI tests, hygiene, secret scan, and opt-in real ODA File Converter checks passed against committed sanitized fixtures; awaiting owner interactive UI check and optional live run on an owner workspace DXF/DWG drawing in `start.bat`)*
- **Branch:** `step-07-cad-bim-extraction`
- **Depends on:** Step 06 (`47117cb`, PR `#12` merged to `main` after `PASS step 06`)

## 1. Scope Done

- **Pinned Step 07 Python CAD/BIM dependencies (`<repo>/backend/requirements.txt`):**
  - Pinned verified libraries in `backend/.venv`: `ezdxf==1.4.5` and `ifcopenshell==0.9.0.post1` (using existing `pymupdf==2.1` via `ezdxf.addons.drawing.pymupdf.PyMuPdfBackend` for preview PNG generation). Did **not** install any OS software or edit `PATH`.
- **ODA File Converter detection & isolated DWG conversion (`<repo>/backend/app/services/extractors/oda.py`, `<repo>/backend/app/core/config.py`):**
  - Added `Settings.oda_file_converter_path: str = ""` (`ODA_FILE_CONVERTER_PATH` in `<repo>/.env.example`).
  - `probe_oda()` / `detect_oda()` checks in strict order: (1) `ODA_FILE_CONVERTER_PATH`, (2) system `PATH` (`ODAFileConverter` / `TeighaFileConverter`), and (3) standard Program Files locations (`<ProgramFiles>/ODA/ODAFileConverter*/ODAFileConverter.exe`), reporting `"not installed - pending owner"` cleanly when absent and `"installed"` (with parsed version e.g. `27.10.0`) when present.
  - Added run-level single ODA probe inside `extract_project_file`. When a `.dwg` file is extracted:
    - Original read-only `.dwg` in `02_Original_Drawings/` is **never** passed directly to ODA or mutated; ONLY the target `.dwg` bytes are copied into an isolated temporary directory for ODA CLI execution.
    - Converted `ACAD2018` `.dxf` output writes solely into a fresh non-overwritable versioned directory `03_Analysis/extractions/<file_id>/v<ver>/r<run>/converted/` (`extraction.py` refuses HTTP `409 Conflict` if `r<run>` exists), verifies `sha256_after == sha256_before` on the original `.dwg`, and runs deterministic `extract_dxf(..., extraction_method="converted_oda")`.
    - When ODA File Converter is absent, persists `FileExtraction(status="failed", converter_status="not installed - pending owner")` + `AuditLog(action="file.extraction_failed")` and returns HTTP `422`.
- **Deterministic DXF reader (`<repo>/backend/app/services/extractors/cad.py`):**
  - Extracts `$INSUNITS` code and human unit labels (`0=unitless`, `4=mm`, `5=cm`, `6=m`, etc.) verbatim without guessing scale conversions when `$INSUNITS == 0`.
  - Inventories all layers (preserving Arabic layer names e.g. `جدران-معمارية`, color, linetype, on/frozen/locked flags, ModelSpace vs PaperSpace counts), non-anonymous blocks (`DOOR_باب_D1`, insert counts, XREF flag check via `blk.block.is_xref` + `xref_path`), `TEXT`, `MTEXT` (stripping formatting codes while keeping `raw_text`), `INSERT.attribs`, `DIMENSION` (`get_measurement()` + explicit override text separation), closed `LWPOLYLINE` / 2D `POLYLINE` / `CIRCLE` / `HATCH` areas & perimeters (computing Shoelace / path-flattened geometry matching CAD area deterministically), and ModelSpace A4 white-background PNG preview (`page_001.png`).
- **Deterministic IFC BIM reader (`<repo>/backend/app/services/extractors/bim.py`):**
  - Reads IFC schema (`IFC4`/`IFC2X3`), `IfcProject.UnitsInContext` units, `IfcBuildingStorey` hierarchy, `IfcSpace` (Name, LongName, GlobalId, Storey, explicit `Qto_*` / `Pset_*` areas or `null` + warning if omitted — **never** inventing geometry areas), `IfcWall`, `IfcDoor`, `IfcWindow` with `Pset_*` & `Qto_*`, plus summary counts across other `IfcProduct` classes (`product_counts`) and explicit known-limit warnings.
- **PDF / CAD PNG Gemini Vision drawing summary (`<repo>/backend/app/services/extraction.py`, `<repo>/backend/app/api/extraction.py`):**
  - Added `POST /api/extractions/{extraction_id}/vision-summary` routing rendered page PNGs (`150 DPI` from `03_Analysis`) through `execute_provider_request` (honoring keyring keys, Step 04 usage caps, and 503 retries).
  - Enforces structured `DrawingVisionPayload`, persists immutable `vision_page_<N>_s<k>.json` artifacts + `file.drawing_vision_summary` audit entries, and attaches mandatory `ai_interpretation_only: true` + `"AI visual interpretation only — NOT a verified engineering measurement..."` disclaimer.
- **Format Support Matrix & Drawing/BIM Inventory UI (`<repo>/frontend/src/components/ProjectFilesPanel.tsx`, `<repo>/frontend/src/types.ts`, `<repo>/frontend/src/api.ts`, `<repo>/frontend/src/App.tsx`):**
  - Displays live ODA File Converter status alongside Tesseract OCR, collapsible **Format Support Matrix** (`Native` / `Converted via ODA` / `Not Supported`), CAD/BIM counts in `.meta-grid`, dedicated **Drawing & BIM Inventory Table** (Layers, Blocks, Closed Areas, IFC Spaces & Elements), and **Gemini Vision Summary** button + prominent non-measurement warning badge.
- **Sanitized committed test fixtures (`<repo>/backend/tests/fixtures/`):**
  - `sample_clinic_plan.dxf` (sanitized Arabic+English floor plan in meters: `24.00 m2` + `14.00 m2` rooms, PaperSpace sheet note, Arabic layers/blocks/dims).
  - `sample_clinic_plan.dwg` (sanitized binary `ACAD2018` DWG generated from `sample_clinic_plan.dxf`, explicitly whitelisted in `.gitignore` while keeping all other `*.dwg` files ignored).
  - `sample_clinic_model.ifc` (sanitized `IFC4` model with Arabic `IfcProject`, `METRE`/`SQUARE_METRE` units, measured `18.75 m2` space, unmeasured waiting room `IfcSpace`, wall, door, window, slab).

## 2. Format Support Matrix (No Native DWG / RVT Claimed)

| Format | Category | Support Level | Engine / Converter | Behaviour & Limits |
| --- | --- | --- | --- | --- |
| `.dxf` | CAD Drawing | **Native** | `ezdxf` + `PyMuPDF` preview | Full layer, block, text/MTEXT/ATTRIB, dimension, closed polyline/circle/hatch area, unit & preview PNG extraction. |
| `.dwg` | CAD Drawing (Binary) | **Converted via ODA** | ODA File Converter → DXF → `ezdxf` | **Not** read natively. Staged in isolated temp folder and converted to `ACAD2018` DXF inside versioned `03_Analysis/.../converted/`. Original `.dwg` untouched. |
| `.ifc` | BIM Model | **Native** | `ifcopenshell` | Native schema, SI units, storeys, `IfcSpace`, `IfcWall`, `IfcDoor`, `IfcWindow`, `Pset_*` & `Qto_*`. Other `IfcProduct` types counted only; 3D B-rep geometry not tessellated. |
| `.pdf` | Drawing Sheet / Spec | **Native + AI Summary** | `pdfplumber`, `PyMuPDF`, Tesseract OCR, Gemini Vision | Vector text/tables, 150 DPI page PNGs, 300 DPI `ara+eng` OCR, and opt-in Vision summary flagged **AI interpretation only (not measurement)**. |
| `.docx` / `.xlsx` / `.csv` / `.pptx` / `.txt` / `.md` / Raster | Office / Images | **Native** | Step 06 extractors | Same deterministic behavior verified in Step 06. |
| `.rvt` / `.rfa` / `.rte` | Autodesk Revit | **Not supported** | None in Step 07 | Returns HTTP `400`; owner exports `.ifc`, `.dxf`, or `.pdf` from Revit first. |
| `.dgn` / `.dwf` / `.step` / `.stp` / `.iges` / `.igs` / `.obj` / `.stl` / `.gltf` / `.glb` | Deferred CAD / 3D Exchange | **Not supported** | None in Step 07 | Returns HTTP `400`; convert to `.dxf`/`.ifc`/`.pdf` before upload. |

## 3. Files Created / Changed

### Created
- `<repo>/backend/app/services/extractors/oda.py`
- `<repo>/backend/app/services/extractors/cad.py`
- `<repo>/backend/app/services/extractors/bim.py`
- `<repo>/backend/tests/fixtures/sample_clinic_plan.dxf`
- `<repo>/backend/tests/fixtures/sample_clinic_plan.dwg`
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
- `<repo>/backend/tests/test_extraction.py` *(updated Step 06 deferred-CAD test input from `plan.dxf` -> `building.rvt` and extended exact zero-CAD/BIM field equality assertion in PDF test)*
- `<repo>/docs/DECISIONS.md` (`ADR-013`)
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/frontend/src/App.tsx`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/components/ProjectFilesPanel.tsx`
- `<repo>/frontend/src/types.ts`

## 4. Tests Run

### Backend Default Suite (`.\.venv\Scripts\python.exe -m pytest -v` in `<repo>/backend`)
*(Runs hermetically without requiring external binaries; skips only the 2 opt-in external binary tests `test_optin_real_oda_converter_dwg_to_dxf` and `test_optin_real_tesseract_ara_eng_on_committed_fixture` unless opted in.)*

```text
============================= test session starts =============================
collecting ... collected 49 items

tests/test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  2%]
tests/test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  4%]
tests/test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  6%]
tests/test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED  [  8%]
tests/test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [ 10%]
tests/test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [ 12%]
... (all 42 existing config, extraction, files, health, migrations, projects, providers, tasks tests PASSED; 1 opt-in OCR test SKIPPED) ...

======================= 47 passed, 2 skipped in 40.27s ========================
```

### Opt-In Real ODA File Converter Evidence (Committed Sanitized `.dwg` Fixture)
*(ODA File Converter `27.10.0` installed externally by the owner in `<ProgramFiles>/ODA/ODAFileConverter 27.10.0`, detected without modifying OS or `PATH`.)*

```text
> cd <repo>/backend
> $env:RUN_REAL_ODA='1'; .\.venv\Scripts\python.exe -m pytest tests/test_cad_bim.py -k test_optin_real_oda_converter_dwg_to_dxf -v -s
collecting ... collected 6 items / 5 deselected / 1 selected

tests/test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/<file_id>/v1/r1/converted/sample_clinic_plan.dxf
PASSED

======================= 1 passed, 5 deselected in 3.58s =======================
```

*(Full final-head outputs for `pytest -v`, `RUN_REAL_ODA=1`, `RUN_REAL_OCR=1`, `vitest`, `node --test`, and `gitleaks` on the committed head SHA are pasted in the Step 07 PR description and chat summary.)*

## 5. Acceptance Tests & Verification Evidence

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| DXF reader inventories layers, blocks, text, dimensions, polylines, areas, units & Arabic text | **PASS** | `test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits` proves `$INSUNITS=6` (`m`), Arabic layers (`جدران-معمارية`), Arabic block `DOOR_باب_D1` (`insert_count=2`, `DOOR_TAG=D-01`), `MTEXT`/`TEXT` Arabic text, linear dimension (`6.0 m`), and ModelSpace PNG preview |
| DXF deterministic area matches CAD-reported area | **PASS** | Closed polylines in `sample_clinic_plan.dxf` compute `24.0 m2` and `14.0 m2` (`[14.0, 24.0]`), matching CAD-annotated areas `24.00 m2` & `14.00 m2` |
| DWG converts to DXF via ODA File Converter; missing converter reported cleanly; originals untouched | **PASS** | `test_capabilities_oda_resolution_priority_absent_dwg_and_matrix`, `test_dwg_conversion_pipeline_mocked_preserves_original_and_versions`, and live `test_optin_real_oda_converter_dwg_to_dxf` (`ODAFileConverter 27.10.0`) verify isolation, `sha256_before == sha256_after`, versioned `r{n}/converted/` output, and `not installed - pending owner` failure handling |
| IFC lists spaces with areas, walls, doors, windows, properties & quantities without inventing values | **PASS** | `test_extract_ifc_spaces_areas_elements_properties_and_known_limits` verifies `sample_clinic_model.ifc`: `غرفة الفحص 01` (`18.75 m2` from `Qto_SpaceBaseQuantities.NetFloorArea`), `غرفة الانتظار` kept `null` (`not_provided_in_ifc`) with explicit warning, plus wall/door/window `Pset_*`/`Qto_*` |
| PDF/DXF drawing page rendering + Gemini Vision summary labelled as AI interpretation, not measurement | **PASS** | `test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap` + Vitest UI test prove `ai_interpretation_only=True`, mandatory non-measurement disclaimer badge, immutable JSON artifact, and usage ledger logging |
| Owner check on real work DXF/DWG & interactive UI confirmation | **PENDING** | No client files were committed; awaiting owner check inside `start.bat` |

## 6. Decisions Made (Recorded in `<repo>/docs/DECISIONS.md` as `ADR-013`)
- Isolated DWG staging directory for ODA File Converter CLI so `02_Original_Drawings` is never scanned or touched directly; converted DXFs live inside fresh non-overwritable `03_Analysis/.../r{n}/converted/`.
- Reused `file_extractions` JSON columns (`payload_json`, `counts_json`, `rendered_images_json`) without forcing unnecessary SQL schema migration churn.
- Kept Gemini Vision strictly opt-in via `POST /api/extractions/{extraction_id}/vision-summary` with `ai_interpretation_only=True` and explicit non-measurement warning banners in backend & UI.

## 7. Accuracy Notes and Known Failures

### CAD / DXF / DWG Accuracy Limits
- **Units & Unitless Drawings (`$INSUNITS`):** When `$INSUNITS=0` (`Unitless`) or an unrecognized code is authored, the extractor reports `"unitless"` and omits `area_m2` conversions rather than guessing whether 1 unit represents `mm`, `cm`, `m`, `in`, or `ft` (an explicit warning is attached). Users/engineers must still verify that AutoCAD drawings authored in meters/millimeters have consistent `$INSUNITS` headers (`6=m`, `4=mm`) versus title-block scale notes.
- **External XREFs (`block.is_xref`):** External Reference (`XREF`) block definitions (`block.block.is_xref`) and their relative/saved `xref_path` strings are detected, listed in `drawing_inventory.blocks`, and flagged with a warning (`External XREF block(s) detected...; external referenced DWGs are NOT loaded or resolved`). Geometry inside external XREF target DWGs is **not** merged into layer entity counts or room areas.
- **Model-Space vs. Paper-Space & Viewports:** Entity counts, layers, text items, dimensions, and polyline areas explicitly tag `cad_space="modelspace"` vs `cad_space="paperspace"` across layouts; however, ModelSpace PNG preview rendering (`page_001.png` via `PyMuPdfBackend`) renders **ModelSpace only**, and scaled `VIEWPORT` crops, paper-space title-block clipping, or paper-space layout plot scales are **not** rendered or converted into model-space geometry. Files with PaperSpace entities emit an explicit warning.
- **3D Entities, Meshes & Proprietary Proxy Objects:** `3DSOLID`, `MESH`, `SURFACE`, `BODY`, `3DFACE`, and `3DPOLYLINE` entities are counted and flagged with a warning, NOT volume/surface-integrated deterministically; Autodesk vertical `ACAD_PROXY_ENTITY` objects (Civil 3D / MEP / Architectural Desktop objects saved without proxy graphics) are flagged as un-decomposed proxies.
- **Dynamic Blocks, Nested Transforms & Curved Hatches/Polylines:** Closed `LWPOLYLINE` bulges and `HATCH` boundaries flatten via chord tolerance `0.0005`–`0.001` drawing units; multi-loop hatches with nested cutout islands currently warn (`summed gross area without subtracting nested island holes`), and non-uniformly scaled/rotated nested `INSERT` block sub-entities are inventoried as block definitions/inserts rather than exploded into world-space polyline areas.
- **SHX Fonts & Preview Fidelity:** Rendered DXF ModelSpace PNG previews depend on `ezdxf.addons.drawing` glyph substitution when proprietary AutoCAD `.shx` shape fonts (especially custom Arabic SHX fonts) are referenced instead of TrueType (`TTF`), whereas underlying `TEXT` / `MTEXT` Unicode character strings extracted from DXF `1.4.5` are preserved verbatim in JSON.
- **DWG Conversion Timeout & ODA Versions:** Binary `.dwg` extraction shells out to `ODAFileConverter.exe` converting to `ACAD2018` DXF with a `90s` subprocess timeout; corrupted/password-protected `.dwg` files, unsupported newer DWG revisions beyond ODA `27.10.0`, or missing ODA installations fail cleanly with HTTP `422` and a persisted `FileExtraction(status="failed")` record leaving original `.dwg` bytes untouched.

### BIM / IFC Accuracy Limits
- **No Fabricated Quantities or Areas:** `extract_ifc` reads ONLY authored Property Sets (`Pset_*`) and Quantity Sets (`Qto_*` / `IfcElementQuantity`). If an `IfcSpace`, `IfcWall`, `IfcDoor`, or `IfcWindow` lacks `Qto_*` area fields (common in schematic BIM exports with "Compute Room Areas" disabled), `area` stays `null` (`not_provided_in_ifc`) with an explicit warning — it is never approximated from bounding boxes or tessellated triangles.
- **Entity Scope & 3D B-Rep Limits:** Detailed item/property extraction covers `IfcProject` units, `IfcBuildingStorey`, `IfcSpace`, `IfcWall`, `IfcDoor`, and `IfcWindow`; additional structural/MEP `IfcProduct` classes (`IfcSlab`, `IfcBeam`, `IfcColumn`, `IfcFlowTerminal`, etc.) are counted in `product_counts` + warned as summary-only in Step 07. Visual 3D IFC rendering and clash/B-rep mesh volume checks are not performed.

### PDF Drawing Vision Summary Limit
- **Strict Non-Measurement Rule:** `POST /api/extractions/{extraction_id}/vision-summary` sends a `150 DPI` rendered PNG to Gemini strictly to read legible title blocks/labels/discipline context (`ai_interpretation_only=true`). Pixel-based AI responses **cannot** measure scales, lengths, areas, or element counts reliably and carry a mandatory non-measurement disclaimer.

## 8. Questions or Items Needed from the Owner
- Open `<repo>/scripts/start.bat`, upload a real non-sensitive/local **DXF**, **DWG**, and/or **IFC** sample plus a PDF drawing page in **Projects & Files**, click **Extract Content / استخراج البيانات**, inspect the **Drawing & BIM Inventory Table**, and (if Gemini API key is saved) optionally test **Gemini Vision Summary**.
- Reply **`PASS step 07`** after reviewing the Step 07 pull request and inspecting the UI when ready for **Step 08 — Research tool with source log**.

## 9. How the Owner Can See / Try It
1. Launch `<repo>/scripts/start.bat` (auto-detects ODA File Converter `27.10.0` at default `<ProgramFiles>/ODA/...` and Tesseract `5.5.3` automatically without changing `PATH`).
2. Open any project in **المشاريع والملفات / Projects & Files** and inspect the **ODA File Converter Status** banner plus **Format Support Matrix**.
3. Upload `.dxf`, `.dwg`, `.ifc`, or `.pdf` files and click **استخراج البيانات / Extract Content** to view units, layers, blocks, closed areas, IFC spaces/properties, converted DXF path, ModelSpace PNG preview, and full normalized JSON.

## 10. Ready for Next Step?
**Pending owner UI visual confirmation & real-drawing check (`PARTIAL`)** — automated Step 07 CAD/BIM extraction, real ODA `27.10.0` conversion, IFC parsing, and Vision disclaimer checks pass cleanly; awaiting owner review and `PASS step 07` to proceed to Step 08.
