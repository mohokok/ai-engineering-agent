# Step 08 — Controlled Internet Research Tool with Source Log (+ PR #14 & PR #15 Fixes)

- **Date:** 2026-11-20
- **Status:** **PARTIAL** *(automated Step 08 implementation + PR #14 & PR #15 fixes, database migration `0006`, transparent UA + single Referer-less retry, `owner_provided` uploaded sources, zero-LLM cost guard when 0 sources are reviewed, best-effort DuckDuckGo/Tavily hint, Arabic Research UI + `"unranked"` display, `stored_read_only` matrix row + Arabic OCR/ODA status banners, full backend `pytest -v`, live `RUN_REAL_RESEARCH=1` (`accessible=1` + OSHA `403` unreviewed), live `RUN_REAL_ODA=1`, live `RUN_REAL_OCR=1`, frontend Vitest/build, and `gitleaks` pass cleanly; interactive owner UI walkthrough in `scripts/start.bat` remains pending)*
- **Branch:** `step-08-research-tool`
- **Depends on:** Step 07b (`3719383`, PR `#14` merged after owner verified `2.040006` `m` area match and Arabic block recovery on local DWG)

## 1. Scope Done

### PR #14 Follow-Up Fixes
- **Synthetic hand-calculated closed `LWPOLYLINE` arc-bulge area & bugfix (`<repo>/backend/app/services/extractors/cad.py`, `<repo>/backend/tests/test_cad_bim.py`):**
  - Replaced invalid `.flattening()` calls on `ezdxf` `LWPOLYLINE` entities with deterministic analytical circular-segment math (`_polyline_bulge_area_and_perimeter`) shared across `LWPOLYLINE` and 2D `POLYLINE`.
  - Added `test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area` verifying a `6.0 m × 4.0 m` rectangle with semicircular cap (`R = 2.0 m`, `bulge = 1.0`) equals `24.0 + 2π = 30.283185 m2` (perimeter `16.0 + 2π = 22.283185 m`), plus a concave notch case (`24.0 - 2π = 17.716815 m2`).
  - **Honest scope note:** The owner's real local DWG drawings contained **no** closed `LWPOLYLINE` with an arc segment (bulge); therefore arc-bulge area calculation is verified strictly against this synthetic hand-calculated fixture.
- **Confirmed display unit labels beside untouched raw values (`<repo>/backend/app/services/extractors/cad.py`, `<repo>/frontend/src/components/ProjectFilesPanel.tsx`):**
  - Added `_DISPLAY_UNIT_LABELS` and `_apply_confirmed_unit_fields()` outputting `display_area`, `display_area_unit` (`"sq m"`), `display_perimeter`, `display_perimeter_unit` (`"m"`), and `raw_declared_unit` whenever owner unit confirmation is applied (both via `/extract` and `/confirm-unit`) while keeping `area_native`, `area_native_unit` (`sq_in`), and `perimeter_native` / `perimeter_unit` (`in`) completely untouched.
  - Updated `ProjectFilesPanel.tsx` Closed Areas table to render confirmed display units (`sq m` / `m`) prominently alongside `(raw: ... sq_in)` / `(raw: ... in)`.

### Step 08 — Controlled Internet Research & Persisted Source Log
- **Search Provider Options & Free Zero-Key Default (`<repo>/backend/app/services/research_fetch.py`):**
  - Free zero-key `duckduckgo_lite` (explicitly marked best-effort only, recommending a free **Tavily** API key in Settings first on rate-limit/anti-bot challenge) + scholarly `crossref`, with pluggable optional keyring adapters ready for `tavily`, `serper`, and `brave`. No paid search keys are required or committed.
- **Database Schema & Reversible Migration (`<repo>/backend/app/db/models.py`, `<repo>/backend/alembic/versions/0006_step08_research_runs.py`):**
  - Added `research_runs` (`ResearchRun` with classification `CHECK` constraint) and extended `research_sources` (`ResearchSource`) with `research_run_id`, `source_priority_tier`, `priority_rank`, `access_status`, `reviewed`, `http_status`, `failure_reason`, and `untrusted_neutralized`.
- **Direct Page/PDF Fetching, Source Priority Ranking & Evidence Isolation (`<repo>/backend/app/services/research_fetch.py`, `<repo>/backend/app/services/research.py`):**
  - **Source Priority Hierarchy (ranked `1` → `6`):**
    1. `official_regulations` (`high_official_regulation`)
    2. `standards_bodies` (`high_standards_body`)
    3. `government` (`high_government`)
    4. `manufacturer` (`medium_manufacturer`)
    5. `peer_reviewed` (`medium_peer_reviewed`)
    6. `reputable` (`low_reputable_reference`)
    - Unreachable / blocked sources are stored as `reviewed=False`, `reliability_rating="unreviewed"`, `access_status="inaccessible"`, and rendered in UI as **`unranked`** (`غير مصنّف` in Arabic).
  - **Snippets Are Never Evidence:** `SearchCandidate` omits snippets entirely so search-engine summaries can never leak into citations or LLM prompts; every target URL is fetched directly via `httpx` (HTML via `lxml.html`, PDF via `pymupdf`) with SSRF validation blocking localhost/private/link-local IPs and non-HTTP(S) schemes.
  - **Untrusted Page Isolation & Prompt-Injection Defense:** `<script>`, `<style>`, `<noscript>`, `<iframe>`, `<svg>`, and HTML comments are stripped; all remaining text is wrapped inside `<UNTRUSTED_WEB_PAGE_CONTENT>` via `_encode_untrusted_json_block()` (`<`/`>` escaped). `normalize_research_synthesis()` strictly preserves owner `classification`, strips any fabricated/unfetched URL citations, enforces `reviewed = False` on every inaccessible source, and flags detected injection strings under `injection_attempts_ignored`.
  - **Step 04 Budget & Provenance Logs:** Optional AI synthesis routes through `execute_provider_request()` enforcing daily/monthly request & token limits and recording token usage + immutable `11_References/research/<run_id>/research_log.json` artifacts and `audit_log` events.

### PR #15 Review Fixes Implemented
1. **Honest Fetch Headers + Single Referer-less Retry + Owner-Provided Uploaded Files (`research_fetch.py`, `research.py`, `schemas/research.py`):**
   - Replaced `curl`/browser-spoofed User-Agents with transparent `DEFAULT_USER_AGENT = "LocalAIEngineeringAgent/0.8 (Consultancy Research Client; +local-desktop-app)"` + normal `Accept` / `Accept-Language` headers (`_PRIMARY_FETCH_HEADERS`).
   - On HTTP `403`, `406`, or `429`, retries **once** with `_RETRY_MINIMAL_HEADERS` (`Accept: */*`, `Accept-Encoding: gzip, deflate`, and no `Referer`). If still blocked, keeps `reviewed=False`, `access_status="inaccessible"`, `reliability_rating="unreviewed"`, exact `http_status`, and clear owner guidance: `'download the document yourself and upload it in Projects & Files; it will be cited as owner-provided'`.
   - Added `owner_files` (`OwnerProvidedSourceInput`: `file_id`, `priority_tier`, `publication_date`) to `POST /api/research/runs`: attaches already-uploaded project files (`access_status="owner_provided"`, `reviewed=True`, priority tier chosen by the owner, citation URI `project-file://{file_id}/v{ver}`) reading deterministic extracted text (or running `extract_project_file` cleanly if not yet extracted). Tested with mocked HTTP `403` site, retry recovery, and uploaded owner TXT file.
2. **Zero-LLM Cost Guard (`research.py`):**
   - When `accessible_sources + owner_provided_sources == 0` (`reviewed_count == 0`), Gemini is skipped completely (`generate_content` call count == `0`, `total_tokens == 0`), returning `status="no_accessible_sources"` and an honest deterministic `"no accessible sources"` summary.
3. **DuckDuckGo Lite Best-Effort Framing + Explicit Input Handling (`research_fetch.py`, `research.py`):**
   - Removed `"curl/8.0"` User-Agent from `_search_duckduckgo_lite`, updated DuckDuckGo Lite labels/errors to mark it strictly best-effort and recommend configuring a free **Tavily** API key in Settings first on non-200/anti-bot responses, and skipped background DDG discovery whenever explicit `urls` or `owner_files` are provided directly.
4. **Research UI Localization, `"unranked"` Display & Owner-File Picker (`frontend/src/components/ResearchView.tsx`):**
   - Translated provider names (`PROVIDER_LABELS`), run status labels (`RUN_STATUS_LABELS`), priority tiers (`TIER_LABELS`), and reliability ratings (`RATING_LABELS`) cleanly to Arabic (`lang === "ar"`).
   - Updated the Priority Tier column so reviewed/owner-provided sources display the tier name cleanly without `#99`, and unreviewed/inaccessible rows display **`غير مصنّف`** (Arabic) / **`unranked`** (English).
   - Added project-file selection (`owner_files`) + owner priority tier selector directly in `ResearchView.tsx`.
5. **Format Support Matrix Row & Arabic Status Banners (`backend/app/schemas/extraction.py`, `backend/app/services/extraction.py`, `frontend/src/components/ProjectFilesPanel.tsx`):**
   - Added `stored_read_only` entry for `.doc .xls .ppt .rtf .ods .html .json .xml .svg .landxml` with note `"other accepted formats (.doc .xls .ppt .rtf .ods .html .json .xml .svg .landxml): stored as read-only original, not extracted."`.
   - Translated Step 06/07 OCR & ODA status bars (`translateToolStatus`, `translateToolMessage`) and the Format Support Matrix table columns, badges (`native`, `converted_via_oda`, `stored_read_only`, `not_supported`), and descriptions cleanly to Arabic when `lang === "ar"`.

## 2. Files Created / Changed

### Created
- `<repo>/backend/alembic/versions/0006_step08_research_runs.py`
- `<repo>/backend/app/schemas/research.py`
- `<repo>/backend/app/services/research_fetch.py`
- `<repo>/backend/app/services/research.py`
- `<repo>/backend/app/api/research.py`
- `<repo>/backend/tests/test_research.py`
- `<repo>/frontend/src/components/ResearchView.tsx`
- `<repo>/docs/reports/step-08.md`

### Changed
- `<repo>/backend/app/db/models.py`
- `<repo>/backend/app/main.py`
- `<repo>/backend/app/schemas/extraction.py`
- `<repo>/backend/app/services/extraction.py`
- `<repo>/backend/app/services/extractors/cad.py`
- `<repo>/backend/pytest.ini`
- `<repo>/backend/tests/test_cad_bim.py`
- `<repo>/backend/tests/test_migrations.py`
- `<repo>/frontend/src/types.ts`
- `<repo>/frontend/src/api.ts`
- `<repo>/frontend/src/components/ProjectFilesPanel.tsx`
- `<repo>/frontend/src/App.tsx`
- `<repo>/frontend/src/App.test.tsx`
- `<repo>/docs/DECISIONS.md` (`ADR-015`)

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets or client files committed.)*

## 3. Live Controlled Research Check (`RUN_REAL_RESEARCH=1`)

Live check passing both a reachable public statutory page (`https://www.legislation.gov.uk/uksi/2010/2214/contents`) and a site returning HTTP `403` (`https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37`), with `synthesize_with_ai=False`:

```text
> $env:RUN_REAL_RESEARCH='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests/test_research.py -k test_optin_real_live_controlled_research_no_client_data -v -s; $env:RUN_REAL_RESEARCH=''
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 6 items / 5 deselected / 1 selected

backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data 
LIVE RESEARCH SAMPLE: provider=duckduckgo_lite | total=2 | accessible=1 | inaccessible=1 | artifact=11_References/research/bce78d2f-4010-46a9-a356-13c2d90a066b/research_log.json
SOURCE tier=official_regulations rating=high_official_regulation reviewed=True url=https://www.legislation.gov.uk/uksi/2010/2214/contents pub=Thu, 12 Nov 2026 17:32:01 GMT http=200 info='Skip to main contentSkip to navigationlegislation.gov.ukhttps://www.nationalarchives.gov.ukCymraegHomeExplore our collectionsResearch toolsH'
SOURCE tier=official_regulations rating=unreviewed reviewed=False url=https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37 pub=None http=403 info='UNREVIEWED — Document inaccessible: HTTP 403 response — document could not be accessed and was NOT reviewed; download the document yourself '
PASSED

======================= 1 passed, 5 deselected in 3.62s =======================
```

- Reachable statutory URL (`legislation.gov.uk`): `HTTP 200`, `accessible=1`, `reviewed=True`, `reliability_rating=high_official_regulation`.
- Blocked URL (`osha.gov`): honest UA + single Referer-less retry still returned `HTTP 403`, recorded `reviewed=False`, `reliability_rating=unreviewed`, and actionable owner guidance to download & upload in **Projects & Files** as owner-provided.

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
collecting ... collected 60 items

backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  1%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  3%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  5%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  6%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [  8%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [ 10%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 11%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 13%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 16%]
backend\tests\test_cad_bim.py::test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area PASSED [ 18%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 20%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 21%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 23%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 25%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 26%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 28%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 30%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 31%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 33%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 35%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 36%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 38%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 40%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 41%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 43%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 45%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 46%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 48%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 50%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 51%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 53%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 55%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 56%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 58%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 60%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 61%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 63%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 65%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 66%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 68%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 70%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 71%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 73%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 75%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 76%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 78%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 80%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 81%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 83%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 85%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 86%]
backend\tests\test_research.py::test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload PASSED [ 88%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 90%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 91%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 95%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

======================= 57 passed, 3 skipped in 47.66s ========================
```

### Opt-In Real External Checks (`RUN_REAL_ODA=1`, `RUN_REAL_OCR=1`)

```text
> $env:RUN_REAL_ODA='1'; $env:RUN_REAL_OCR='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests/test_cad_bim.py backend/tests/test_extraction.py -k "test_optin_real" -v -s; $env:RUN_REAL_ODA=''; $env:RUN_REAL_OCR=''
collecting ... collected 21 items / 19 deselected / 2 selected

backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf 
REAL ODA CONVERTER: version=27.10.0 | units=m ($INSUNITS=6) | layers=5 | blocks=2 | closed_areas=[14.0, 24.0] | converted=03_Analysis/extractions/507d9d26-237b-4256-ae4e-0c78955e2581/v1/r1/converted/sample_clinic_plan.dxf
PASSED
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture 
REAL OCR VERSION: tesseract v5.5.3.20260724 | LANGS: ['ara', 'eng', 'osd']
PNG OCR TEXT: 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PDF OCR TEXT (DPI=300): 'Beam Span = 6.00 m | Load = 18.50 kN/m\n\u200fمشروع مستشفى طرابلس التعليمي\u200e'
PASSED

====================== 2 passed, 19 deselected in 6.31s =======================
```

### Frontend Tests & TypeScript/Vite Build

- `npm.cmd --prefix frontend test -- --run`: `16 passed` (`1 test file`, `33ms` test duration, `565ms` total).
- `npm.cmd --prefix frontend run build` (`tsc --noEmit && vite build`): exited `0` (`33 modules transformed`, built in `489ms`).

## 5. Acceptance Criteria Table

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| PR #14 (a): Closed `LWPOLYLINE` arc-bulge exact hand-calculated test (+ bugfix for missing `LWPolyline.flattening`) | **PASS (Synthetic only; owner's real DWGs have no arc-bulge polylines)** | `test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area` verifies `30.283185 m2` (`24 + 2π`), `22.283185 m`, and concave `17.716815 m2` via `_polyline_bulge_area_and_perimeter`. |
| PR #14 (b): Confirmed display units (`sq m` / `m`) shown alongside untouched raw units (`sq_in` / `in`) | **PASS** | `test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit` and `App.test.tsx` verify `display_area_unit="sq m"`, `display_perimeter_unit="m"`, and preserved `area_native_unit="sq_in"`. |
| PR #15 (1): Honest UA + single Referer-less retry on `403`/`406`/`429` + owner action + `owner_provided` uploaded sources | **PASS** | `test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload` + live `RUN_REAL_RESEARCH=1` verify `LocalAIEngineeringAgent/0.8`, single Referer-less retry, `403` unreviewed owner upload guidance, and attaching uploaded project files (`access_status="owner_provided"`, `reviewed=True`). |
| PR #15 (2): Skip Gemini cleanly (`0` tokens) when `0` sources accessible/owner-provided | **PASS** | `test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload` asserts `generate_content` call count == `0`, `total_tokens == 0`, `status="no_accessible_sources"`, `"no accessible sources"` summary. |
| PR #15 (3): DuckDuckGo Lite best-effort (no `curl` UA) recommending Tavily first | **PASS** | `research_fetch.py` removes `"curl/8.0"`, labels DDG best-effort, and returns HTTP `502` recommending free **Tavily** key in Settings first. |
| PR #15 (4): Arabic UI labels in `ResearchView` + `"unranked"` instead of `#99` when unreviewed | **PASS (Vitest/Static Render); Interactive UI PENDING Owner** | `App.test.tsx` verifies Arabic provider/status/tier labels and `"unranked"` / `"غير مصنّف"` display with `#99` absent on unreviewed rows. |
| PR #15 (5): Format Support Matrix `stored_read_only` row + Arabic OCR/ODA & matrix translations | **PASS** | `test_capabilities_oda_resolution_priority_absent_dwg_and_matrix` and `App.test.tsx` verify `.doc .xls .ppt .rtf .ods .html .json .xml .svg .landxml` (`stored_read_only`) and Arabic translations when `lang === "ar"`. |
| PR #15 (6): Live controlled research check with `accessible >= 1` | **PASS** | `RUN_REAL_RESEARCH=1` returned `accessible=1` (`legislation.gov.uk` HTTP `200`, `reviewed=True`) alongside `inaccessible=1` (`osha.gov` HTTP `403`, `unreviewed`). |

## 6. Known Limitations & Deviations
- **DuckDuckGo Lite throttling behavior:** Free `https://lite.duckduckgo.com/lite/` frequently returns `HTTP 202` (anti-bot challenge) on automated requests. The app treats DuckDuckGo Lite as best-effort only, never bypasses anti-bot challenges, and recommends entering a free **Tavily** Search API key in Settings, using **Crossref Peer-Reviewed**, supplying direct URLs, or uploading gated documents in **Projects & Files** as `owner_provided`.
- **Arc-bulge real-drawing check:** Owner's local real DWGs contain no closed `LWPOLYLINE` with an arc bulge, so curved polyline accuracy rests on exact synthetic hand-calculated geometry tests.
- **Interactive UI check pending:** Frontend rendering and client calls are verified via Vitest + `tsc` + Vite build; live owner walkthrough in `scripts/start.bat` remains `PENDING`.

## 7. Questions & How the Owner Can Try It
1. Launch `<repo>/scripts/start.bat` and open **البحث وسجل المصادر / Research & Source Log**.
2. Try:
   - A reachable public URL such as `https://www.legislation.gov.uk/uksi/2010/2214/contents` (`accessible=1`) alongside a gated URL such as `https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37` (HTTP `403` -> **`غير مصنّف` / `unranked`** with download & upload instruction).
   - Downloading a `403`/paywalled regulation manually, uploading it in **Projects & Files**, then selecting it under **Attach Uploaded Project Files as Owner-Provided Sources** in the Research tab (`owner_provided`, `reviewed=True`, `0` Gemini spend if nothing is accessible).
3. Also verify **Projects & Files** in Arabic showing translated OCR/ODA status boxes and the new `stored_read_only` row in the Format Support Matrix.
4. Reply **`PASS step 08`** after PR `#15` review & merge when ready for **Step 09**.
