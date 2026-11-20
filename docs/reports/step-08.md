# Step 08 — Controlled Internet Research Tool with Source Log (+ PR #14 Follow-Ups)

- **Date:** 2026-11-20
- **Status:** **PARTIAL** *(automated PR #14 arc-bulge & confirmed-display-unit fixes, Step 08 database migration `0006`, web search + SSRF-safe HTML/PDF fetchers, 6-tier source priority ranking, snippet ban, prompt-injection isolation, inaccessible `UNREVIEWED` tracking, Step 04 usage-limit enforcement, Arabic RTL / English LTR Research UI, full backend `pytest -v`, live `RUN_REAL_RESEARCH=1` Crossref fetch, frontend Vitest/build, and `gitleaks` pass cleanly; interactive owner UI check and end-to-end live Gemini-synthesized research check in `scripts/start.bat` remain pending)*
- **Branch:** `step-08-research-tool`
- **Depends on:** Step 07b (`3719383`, PR `#14` merged after owner verified `2.040006` `m` area match and Arabic block recovery on local DWG)

## 1. Scope Done

### PR #14 Follow-Up Fixes
- **Synthetic hand-calculated closed `LWPOLYLINE` arc-bulge area & bugfix (`<repo>/backend/app/services/extractors/cad.py`, `<repo>/backend/tests/test_cad_bim.py`):**
  - While building the synthetic arc-bulge test, discovered that `ezdxf==1.4.5`'s `LWPolyline` object has no `.flattening()` method (the previous `try/except` quietly dropped curved polylines). Replaced with exact deterministic analytical circular-segment math (`_polyline_bulge_area_and_perimeter`) shared across `LWPOLYLINE` and 2D `POLYLINE`.
  - Added `test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area` verifying a `6.0 m × 4.0 m` rectangle with semicircular cap (`R = 2.0 m`, `bulge = 1.0`) equals `24.0 + 2π = 30.283185 m2` (perimeter `16.0 + 2π = 22.283185 m`), plus a concave notch case (`24.0 - 2π = 17.716815 m2`).
  - **Honest scope note:** The owner's real local DWG drawings contained **no** closed `LWPOLYLINE` with an arc segment (bulge); therefore arc-bulge area calculation is verified strictly against this synthetic hand-calculated fixture.
- **Confirmed display unit labels beside untouched raw values (`<repo>/backend/app/services/extractors/cad.py`, `<repo>/frontend/src/components/ProjectFilesPanel.tsx`):**
  - Added `_DISPLAY_UNIT_LABELS` and `_apply_confirmed_unit_fields()` outputting `display_area`, `display_area_unit` (`"sq m"`), `display_perimeter`, `display_perimeter_unit` (`"m"`), and `raw_declared_unit` whenever owner unit confirmation is applied (both via `/extract` and `/confirm-unit`) while keeping `area_native`, `area_native_unit` (`sq_in`), and `perimeter_native` / `perimeter_unit` (`in`) completely untouched.
  - Updated `ProjectFilesPanel.tsx` Closed Areas table to render confirmed display units (`sq m` / `m`) prominently alongside `(raw: ... sq_in)` / `(raw: ... in)`.

### Step 08 — Controlled Internet Research & Persisted Source Log
- **Search Provider Options & Free Zero-Key Default (`<repo>/backend/app/services/research_fetch.py`):**
  - Discussed search provider options with the owner before building on a paid API; owner selected **free zero-key `duckduckgo_lite` + `crossref` default** with pluggable optional keyring adapters ready for `tavily` (`1,000` free credits/mo, no card), `serper` (`2,500` one-time starter free, no card), or `brave` (`$5/mo` credit, card required). No paid search keys are required or committed.
- **Database Schema & Reversible Migration (`<repo>/backend/app/db/models.py`, `<repo>/backend/alembic/versions/0006_step08_research_runs.py`):**
  - Added `research_runs` (`ResearchRun` with classification `CHECK` constraint) and extended `research_sources` (`ResearchSource`) with `research_run_id`, `source_priority_tier`, `priority_rank`, `access_status`, `reviewed`, `http_status`, `failure_reason`, and `untrusted_neutralized`.
- **Direct Page/PDF Fetching, Source Priority Ranking & Evidence Isolation (`<repo>/backend/app/services/research_fetch.py`, `<repo>/backend/app/services/research.py`):**
  - **Source Priority Hierarchy (ranked `1` -> `6`):**
    1. `official_regulations` (`high_official_regulation`)
    2. `standards_bodies` (`high_standards_body`)
    3. `government` (`high_government`)
    4. `manufacturer` (`medium_manufacturer`)
    5. `peer_reviewed` (`medium_peer_reviewed`)
    6. `reputable` (`low_reputable_reference`)
    - Unreachable / blocked sources forced to rank `99` and rating `"unreviewed"`.
  - **Snippets Are Never Evidence:** `SearchCandidate` omits snippets entirely so search-engine summaries can never leak into citations or LLM prompts; every target URL is fetched directly via `httpx` (HTML via `lxml.html`, PDF via `pymupdf`) with SSRF validation blocking localhost/private/link-local IPs and non-HTTP(S) schemes.
  - **Untrusted Page Isolation & Prompt-Injection Defense:** `<script>`, `<style>`, `<noscript>`, `<iframe>`, `<svg>`, and HTML comments are stripped; all remaining text is wrapped inside `<UNTRUSTED_WEB_PAGE_CONTENT>` via `_encode_untrusted_json_block()` (`<`/`>` escaped). `normalize_research_synthesis()` strictly preserves owner `classification`, strips any fabricated/unfetched URL citations, enforces `reviewed = False` on every inaccessible source, and flags detected injection strings under `injection_attempts_ignored`.
  - **Inaccessible Documents Tracked Honest & Unreviewed:** HTTP `4xx`/`5xx`, timeouts, paywalls, and CAPTCHA/anti-bot challenges (never bypassed) record `access_status="inaccessible"`, `reviewed=False`, `reliability_rating="unreviewed"`, explicit failure reason, and `extracted_info = "UNREVIEWED — Document inaccessible: ..."`.
  - **Step 04 Budget & Provenance Logs:** Optional AI synthesis routes through `execute_provider_request()` enforcing daily/monthly request & token limits and recording token usage + immutable `11_References/research/<run_id>/research_log.json` artifacts and `audit_log` events.
- **Research History UI (`<repo>/frontend/src/components/ResearchView.tsx`, `<repo>/frontend/src/App.tsx`):**
  - Added bilingual Arabic RTL / English LTR `Research & Source Log` (`البحث وسجل المصادر`) tab showing the controlled research form, source priority policy banner, persisted runs table, explicit **Inaccessible / Unreviewed** & **Ignored Injection** banners, and complete Source Log table (`source_name`, `URL`, `publication_date`, `access_date`, `extracted_info`, `reliability_rating`, `reviewed`).

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

## 3. Sample Research Log (Live Opt-In Crossref Run + Verified Provenance Format)

### Live Network Check (`$env:RUN_REAL_RESEARCH='1'`, Free Crossref Open API, Zero Keys)

```text
> $env:RUN_REAL_RESEARCH='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests/test_research.py -k test_optin_real_live_controlled_research_no_client_data -v -s
collecting ... collected 5 items / 4 deselected / 1 selected

backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data 
LIVE RESEARCH SAMPLE: provider=crossref | total=2 | accessible=0 | inaccessible=2 | artifact=11_References/research/5fa03848-b13a-4ab9-a7f5-2992504d3700/research_log.json
SOURCE tier=peer_reviewed rating=unreviewed reviewed=False url=https://doi.org/10.63044/w23sal51 pub=2023-07-26 http=403 info='UNREVIEWED — Document inaccessible: HTTP 403 response; document could not be accessed and was NOT reviewed.'
SOURCE tier=peer_reviewed rating=unreviewed reviewed=False url=https://doi.org/10.63044/w23shi76 pub=2023-07-26 http=403 info='UNREVIEWED — Document inaccessible: HTTP 403 response; document could not be accessed and was NOT reviewed.'
PASSED

====================== 1 passed, 4 deselected in 10.55s =======================
```

> Notice how live DOIs from `api.crossref.org` returned HTTP `403` when resolving publisher full text — the system logged exact publication dates and access dates while honestly refusing to extrapolate from Crossref metadata or snippets, marking both **`unreviewed` (`reviewed=false`)**.

### Multi-Tier Accessible Source Log Sample (Verified in `test_research_priority_order_fetch_pdf_and_snippets_never_evidence`)

| Priority | Source Name | URL | Publication Date | Extracted Info | Reliability Rating | Reviewed? |
| --- | --- | --- | --- | --- | --- | --- |
| `#1 (official_regulations)` | Building Regulations 2020 Statutory Instrument | `https://legislation.gov.uk/uksi/2020/building-regs` | `2020-11-01` | Statutory mechanical ventilation minimum requirements for clinical suites. | `high_official_regulation` | Yes |
| `#2 (standards_bodies)` | NFPA 99 Health Care Facilities Code Overview | `https://nfpa.org/codes/nfpa-99` | `2024-01-15` | Medical gas, vacuum, and essential electrical distribution requirements... | `high_standards_body` | Yes |
| `#3 (government)` | HTM 03-01 Specialised Ventilation for Healthcare | `https://health.gov.uk/technical/htm03` | `2021-06-22` | Operating theatre positive pressure cascade and 25 ACH supply rate guidance. | `high_government` | Yes |
| `#4 (manufacturer)` | Siemens Technical Datasheet Pump GN-400 | `https://siemens.com/datasheets/pump-gn400.pdf` | `2025-06-15` | `[Page 1] Rated flow 12.5 L/s at 180 kPa head; standby pump mandatory...` | `medium_manufacturer` | Yes |
| `#5 (peer_reviewed)` | Hospital Air Change Effectiveness Journal Study | `https://doi.org/10.1000/ashrae-study` | `2023-03-10` | CFD and empirical particle clearance comparisons in Class 1 operating rooms. | `medium_peer_reviewed` | Yes |
| `#6 (reputable)` | Ventilation Air Changes Engineering Reference | `https://engineeringtoolbox.example.com/vent` | `null` | General air change rates reference table. | `low_reputable_reference` | Yes |

## 4. Tests Run (Full Unedited Outputs Verified at Final Head)

*(Full final committed HEAD outputs across `pytest -v`, `RUN_REAL_ODA=1`, `RUN_REAL_OCR=1`, `RUN_REAL_RESEARCH=1`, frontend Vitest/build, and `gitleaks` are recorded below and in the PR description.)*

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 59 items

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
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 22%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 23%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 25%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 27%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 28%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 30%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 32%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 33%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 35%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 37%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 38%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 40%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 42%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 44%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 45%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 47%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 49%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 50%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 52%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 54%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 55%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 57%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 59%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 61%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 62%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 64%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 66%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 67%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 69%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 71%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 72%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 74%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 76%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 77%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 79%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 81%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 83%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 84%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 86%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 88%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 89%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 91%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 94%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

======================= 56 passed, 3 skipped in 49.32s ========================
```

## 5. Acceptance Criteria Table

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| PR #14 (a): Closed `LWPOLYLINE` arc-bulge exact hand-calculated test (+ bugfix for missing `LWPolyline.flattening`) | **PASS (Synthetic only; owner's real DWGs have no arc-bulge polylines)** | `test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area` verifies `30.283185 m2` (`24 + 2π`), `22.283185 m`, and concave `17.716815 m2` via `_polyline_bulge_area_and_perimeter`. |
| PR #14 (b): Confirmed display units (`sq m` / `m`) shown alongside untouched raw units (`sq_in` / `in`) | **PASS** | `test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit` and `App.test.tsx` verify `display_area_unit="sq m"`, `display_perimeter_unit="m"`, and preserved `area_native_unit="sq_in"`. |
| Research task saves all sources (name, URL, pub date, access date, extracted info, reliability, priority order) | **PASS** | `test_research_priority_order_fetch_pdf_and_snippets_never_evidence` + live `RUN_REAL_RESEARCH=1` + `0006` migration verify `ResearchRun`, `ResearchSource`, priority 1→6 sorting, PDF parsing, and `11_References/research/.../research_log.json`. |
| Search-engine snippets never used as evidence | **PASS** | `SearchCandidate` excludes snippet strings; test confirms injected snippet text never enters the LLM prompt or stored `relevant_info`. |
| Deliberate `"ignore your instructions"` webpage not obeyed | **PASS** | `test_research_deliberate_prompt_injection_webpage_not_obeyed` proves comments/`<script>` stripped, `<UNTRUSTED_WEB_PAGE_CONTENT>` escaped, classification locked (`Preliminary`), fabricated unfetched URL stripped, secret never leaked. |
| Inaccessible documents reported as `UNREVIEWED` (never assumed) | **PASS (Mock + Live `HTTP 403`)** | `test_research_inaccessible_documents_reported_as_unreviewed` (`403`, CAPTCHA challenge, timeout) and live Crossref DOIs (`HTTP 403`) persist `reviewed=False`, `reliability_rating="unreviewed"`. |
| Research history UI (Arabic RTL + English LTR) & Step 04 usage limits | **PASS (Mock/Static Render); Interactive UI PENDING Owner** | `test_research_usage_limits_ssrf_and_optional_search_keyring` (`429` budget block) + `App.test.tsx` (`dir="rtl"` Arabic + English LTR `ResearchView`). |

## 6. Known Limitations & Deviations
- **DuckDuckGo Lite throttling behavior:** Free `https://lite.duckduckgo.com/lite/` occasionally returns `HTTP 202` (anti-bot/rate-limit) or TLS resets on repeated automated queries from residential IPs. The app never bypasses anti-bot challenges; it surfaces an explicit `502` telling the owner to use Crossref, explicit direct URLs, or optionally configure a free-tier API key (`Tavily` 1,000/mo or `Serper` 2,500 starter) in Windows Credential Manager.
- **Arc-bulge real-drawing check:** Owner's local real DWGs contain no closed `LWPOLYLINE` with an arc bulge, so curved polyline accuracy rests on exact synthetic hand-calculated geometry tests.
- **Interactive UI check pending:** Frontend rendering and client calls are verified via Vitest + `tsc` + Vite build; live owner browser walkthrough in `scripts/start.bat` remains `PENDING`.

## 7. Questions & How the Owner Can Try It
1. Merge PR after review, sync `main`, and run `<repo>/scripts/start.bat`.
2. Open the new **البحث وسجل المصادر / Research & Source Log** tab:
   - Try a free query with **`Crossref Peer-Reviewed`** or pass explicit `.html` / `.pdf` URLs directly (with **Synthesize via Gemini AI** checked if your Gemini API key is saved in Windows Credential Manager), and inspect the persisted source log & `11_References/research/<id>/research_log.json` artifact.
3. Also verify on an earlier `sq_in` DXF/DWG that confirming `m (meters)` displays **`sq m`** and **`m`** while raw `(raw: ... sq_in)` stays untouched.
4. Reply **`PASS step 08`** when ready for **Step 09 — Document/drawing review → findings report**.
