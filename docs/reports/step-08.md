# Step 08 — Controlled Internet Research Tool with Source Log (+ PR #14 & PR #15 Fixes)

- **Date:** 2026-11-20
- **Status:** **PARTIAL** *(automated Step 08 implementation + PR #14 & PR #15 fixes & quality/relevance/token-cap additions, database migration `0006`, content-quality gate rejecting login/paywall/cookie walls & country-list forms & photo archives, relevance gate rejecting off-topic stubs, title/metadata-free prompt & body-grounding guard, no Crossref auto-`medium_peer_reviewed`, provider-claim tier display + `"unrated"` ratings, hard prompt cap + pre-flight token estimate & `POST /runs/{id}/synthesize`, honest UA + single Referer-less retry, `owner_provided` uploaded sources, zero-LLM cost guard, best-effort DuckDuckGo/Tavily hint, Arabic UI localization + `stored_read_only` matrix row, full backend `pytest -v`, live `RUN_REAL_RESEARCH=1`, live `RUN_REAL_ODA=1`, live `RUN_REAL_OCR=1`, frontend Vitest/build, and `gitleaks` pass cleanly; interactive owner UI walkthrough in `scripts/start.bat` remains pending)*
- **Branch:** `step-08-research-tool`
- **Depends on:** Step 07b (`3719383`, PR `#14` merged after owner verified `2.040006` `m` area match and Arabic block recovery on local DWG)

## 1. Scope Done

### PR #14 Follow-Up Fixes
- **Synthetic hand-calculated closed `LWPOLYLINE` arc-bulge area & bugfix (`<repo>/backend/app/services/extractors/cad.py`, `<repo>/backend/tests/test_cad_bim.py`):**
  - Replaced invalid `.flattening()` calls on `ezdxf` `LWPOLYLINE` entities with deterministic analytical circular-segment math (`_polyline_bulge_area_and_perimeter`) shared across `LWPOLYLINE` and 2D `POLYLINE`.
  - Added `test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area` verifying `30.283185 m2` (`24.0 + 2π`), `22.283185 m`, and concave `17.716815 m2`.
  - **Honest scope note:** The owner's real local DWG drawings contained **no** closed `LWPOLYLINE` with an arc segment (bulge); therefore arc-bulge area calculation is verified strictly against this synthetic hand-calculated fixture.
- **Confirmed display unit labels beside untouched raw values (`<repo>/backend/app/services/extractors/cad.py`, `<repo>/frontend/src/components/ProjectFilesPanel.tsx`):**
  - Added `_DISPLAY_UNIT_LABELS` and `_apply_confirmed_unit_fields()` outputting `display_area`, `display_area_unit` (`"sq m"`), `display_perimeter`, `display_perimeter_unit` (`"m"`), and `raw_declared_unit` while keeping raw values untouched.

### Step 08 — Controlled Internet Research & Persisted Source Log
- **Search Provider Options & Free Zero-Key Default (`<repo>/backend/app/services/research_fetch.py`):**
  - Free zero-key `duckduckgo_lite` (explicitly best-effort, recommending a free **Tavily** API key in Settings first on rate-limit/anti-bot challenges) + scholarly `crossref`, with pluggable optional keyring adapters for `tavily`, `serper`, and `brave`. No paid search keys are required or committed.
- **Database Schema & Reversible Migration (`<repo>/backend/app/db/models.py`, `<repo>/backend/alembic/versions/0006_step08_research_runs.py`):**
  - Added `research_runs` (`ResearchRun` with classification `CHECK` constraint) and extended `research_sources` (`ResearchSource`).
- **Untrusted Page Isolation, Budget Guards & Provenance Logs (`<repo>/backend/app/services/research.py`):**
  - Search snippets are excluded completely (`SearchCandidate` holds no snippet text). HTML active/hidden/chrome nodes (`<script>`, `<style>`, `<noscript>`, `<template>`, `<iframe>`, `<svg>`, comments, `<nav>`, `<footer>`, `<aside>`, `<form>`, `<select>`) are handled cleanly and fetched prose is isolated inside `<UNTRUSTED_WEB_PAGE_CONTENT>` via `_encode_untrusted_json_block()`. Immutable `11_References/research/<run_id>/research_log.json` artifacts and `audit_log` events are persisted alongside `ResearchRun`.

### PR #15 Fixes & Evidence-Integrity Additions
1. **Content-Quality Gate (`assess_page_content_quality` in `research_fetch.py`):**
   - Rejects HTTP `200` pages BEFORE `reviewed=True` with clear reason `'login wall / paywall / cookie wall / no substantive text ...'` when text contains login/paywall/cookie patterns (`Sign in`, `Log In`, `Sign in to Your Personal Account`, `Password`, `Forgot Password`, `Accept cookies`, `Cookie preferences`, `Subscription Required`), country dropdown clusters (`Select Country`, `Afghanistan`, `Aland Islands`, `Albania`, `Algeria`, etc.), photo/media archives (`Photo archive`, `Digital Collections`), falls below minimum substantive length (`MIN_SUBSTANTIVE_CHARS = 160` / `25` words), or has a low ratio of sentence-like prose (`< 25%` prose ratio or `< 18` prose words). Verified against an exact Bloomsbury-style login boilerplate + Afghanistan country list fixture, cookie wall fixture, and Willamette photo-archive fixture.
2. **Relevance Gate (`is_text_relevant_to_query` in `research_fetch.py`):**
   - Compares only substantive body prose (`extracted_text`, never `<title>` or URL) against normalized query terms; pages whose substantive text does not address the query are marked `access_status="not_relevant"`, `reviewed=False`, `reliability_rating="unrated"`, omitted from `verified_findings`, and never cited.
3. **Titles & Metadata Are Never Evidence (`research.py`, `research_fetch.py`):**
   - Page `<title>` / metadata NEVER pads body text; `build_research_synthesis_prompt()` omits titles/metadata of unreviewed/not-relevant rows completely; `RESEARCH_SYSTEM_PROMPT` and `_claim_grounded_in_body()` require findings to overlap real body prose. Tested: titles-only + off-topic pages yield `verified_findings == []` and `0` Gemini calls.
4. **No Crossref Auto-`medium_peer_reviewed` + Provider-Claim Display (`research_fetch.py`, `research.py`, `ResearchView.tsx`):**
   - `_search_crossref` now reads Crossref `type` (`journal-article`, `proceedings-article`, `book-chapter`, `other`, etc.). Photo archives, `book-chapter` / `other` / landing stubs never receive `medium_peer_reviewed`; unverified/unreviewed/book/archive hits stay `"unrated"` (`"غير مُقيَّم"` in Arabic) or `"unreviewed"`. Both backend API (`tier_is_provider_claim`, `tier_claim_label`) and UI present the tier explicitly as a **provider/heuristic claim (not verified fact)** rather than established authority.
5. **Hard Prompt Cap, Pre-Flight Token Estimate Before Large-Run Gemini Calls & Step 04 Budget (`research.py`, `api/research.py`, `ResearchView.tsx`):**
   - Capped prompt evidence strictly (`MAX_PROMPT_CHARS_PER_SOURCE = 2_400`, `MAX_TOTAL_PROMPT_CHARS = 10_000` chars ≈ `< 3,500` tokens even across large pages).
   - Computes deterministic `estimated_prompt_tokens`, `prompt_char_count`, and Step 04 `step04_daily_tokens_remaining` / `step04_monthly_tokens_remaining` before invoking Gemini, enforces remaining Step 04 limits cleanly (HTTP `429` before calling Gemini if exceeded), and adds `POST /api/research/runs/{run_id}/synthesize`. Large runs in `ResearchView.tsx` (`maxResults >= 3` / 3+ URLs or files) run 0-token fetch & filtering first and show exact `~N est. prompt tokens` + a **Confirm & Run Gemini Synthesis** button before spending Gemini tokens.
6. **Honest Fetch Headers + Single Referer-less Retry + Zero-LLM Guard + Owner-Provided Files + Arabic UI & Format Matrix:**
   - Transparent `LocalAIEngineeringAgent/0.8` UA (no browser/`curl` spoofing) + single Referer-less `Accept: */*`, `Accept-Encoding: gzip, deflate` retry on `403`/`406`/`429`; persistent blocks stay `reviewed=False` (`"download the document yourself and upload it in Projects & Files; it will be cited as owner-provided"`); `owner_files` attaches uploaded project files (`access_status="owner_provided"`, `reviewed=True`); `0` reviewed sources skips Gemini (`0` tokens, `status="no_accessible_sources"`); Arabic UI localization across `ResearchView.tsx` (`"unranked"` / `"غير مصنّف"` instead of `#99`) and `ProjectFilesPanel.tsx` (+ `.doc .xls .ppt ...` `stored_read_only` matrix row).

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

Live network check (`synthesize_with_ai=False`, zero Gemini tokens) evaluating a real UK HSE substantive regulatory page (`https://www.hse.gov.uk/fireandexplosion/workplace.htm`), a live Bloomsbury login-wall/country-list DOI (`https://doi.org/10.5040/9798400616747.ch-001`), and a gated HTTP `403` US OSHA standard (`https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37`):

```text
> $env:RUN_REAL_RESEARCH='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests/test_research.py -k test_optin_real_live_controlled_research_no_client_data -v -s; $env:RUN_REAL_RESEARCH=''
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 9 items / 8 deselected / 1 selected

backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data 
LIVE RESEARCH SAMPLE: provider=duckduckgo_lite | total=3 | accessible=1 | inaccessible=2 | est_prompt_tokens=1172 | artifact=11_References/research/2f29492b-001f-4ba7-86ca-540789895b10/research_log.json
SOURCE tier=government rating=high_government reviewed=True url=https://www.hse.gov.uk/fireandexplosion/workplace.htm http=200 info="Work process fire safety This page provides information about HSE's role. Process fire precautions HSE is mainly concerned with process fire"
SOURCE tier=official_regulations rating=unreviewed reviewed=False url=https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37 http=403 info='UNREVIEWED — Document inaccessible: HTTP 403 response — document could not be accessed and was NOT reviewed; download the document yourself '
SOURCE tier=peer_reviewed rating=unreviewed reviewed=False url=https://doi.org/10.5040/9798400616747.ch-001 http=200 info='UNREVIEWED — Document inaccessible: login wall / paywall / cookie wall / no substantive text (registration country list / login form detecte'
PASSED

======================= 1 passed, 8 deselected in 7.03s =======================
```

- **Accepted real page:** `hse.gov.uk/fireandexplosion/workplace.htm` (`HTTP 200`, `reviewed=True`, substantive fire safety / building-regulation prose extracted; `est_prompt_tokens=1172`).
- **Rejected live Bloomsbury login wall:** `doi.org/10.5040/9798400616747.ch-001` (`HTTP 200`, rejected by content-quality gate `reviewed=False`, `rating=unreviewed` with login-form / country-list reason).
- **Rejected live `403` page:** `osha.gov/.../1910.37` (`HTTP 403`, `reviewed=False`, `rating=unreviewed` with owner manual-upload guidance).

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
collecting ... collected 63 items

backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  1%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  3%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  4%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  6%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [  7%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [  9%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 11%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 12%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 14%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area PASSED [ 17%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 19%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 20%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 22%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 23%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 25%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 26%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 28%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 30%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 31%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 33%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 34%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 36%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 38%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 39%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 41%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 42%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 44%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 46%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 47%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 49%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 50%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 52%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 53%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 55%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 57%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 58%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 60%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 61%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 63%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 65%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 66%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 68%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 69%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 71%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 73%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 74%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 76%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 77%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 79%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 80%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 82%]
backend\tests\test_research.py::test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload PASSED [ 84%]
backend\tests\test_research.py::test_research_quality_gate_bloomsbury_login_wall_cookie_wall_and_photo_archive PASSED [ 85%]
backend\tests\test_research.py::test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call PASSED [ 87%]
backend\tests\test_research.py::test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize PASSED [ 88%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 90%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 92%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 95%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

======================= 60 passed, 3 skipped in 52.60s ========================
```

### Opt-In Real External Checks (`RUN_REAL_ODA=1`, `RUN_REAL_OCR=1`, `RUN_REAL_RESEARCH=1`)

```text
> $env:RUN_REAL_ODA='1'; $env:RUN_REAL_OCR='1'; $env:RUN_REAL_RESEARCH='1'; & "backend\.venv\Scripts\pytest.exe" backend/tests -k "test_optin_real" -v -s
collecting ... collected 63 items / 60 deselected / 3 selected
```

- `test_optin_real_oda_converter_dwg_to_dxf`: PASSED (`ODA 27.10.0`)
- `test_optin_real_tesseract_ara_eng_on_committed_fixture`: PASSED (`Tesseract 5.5.3`, `['ara', 'eng', 'osd']`)
- `test_optin_real_live_controlled_research_no_client_data`: PASSED (`hse.gov.uk` accessible, `doi.org/10.5040/9798400616747.ch-001` login wall rejected, `osha.gov` 403 rejected)

### Frontend Tests & TypeScript/Vite Build

- `npm.cmd --prefix frontend test -- --run`: `16 passed` (`1 test file`, `49ms` test duration, `760ms` total).
- `npm.cmd --prefix frontend run build` (`tsc --noEmit && vite build`): exited `0` (`33 modules transformed`, built in `504ms`).

## 5. Acceptance Criteria Table

| Acceptance Criterion | Verdict | Evidence |
| --- | --- | --- |
| PR #14 (a)-(b): Arc-bulge exact test + confirmed `sq m` / `m` display alongside raw units | **PASS** | `test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area`, `test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit`, `App.test.tsx`. |
| PR #15 (1)-(6): Honest UA + Referer-less retry + `owner_provided` + DDG/Tavily hint + zero-LLM guard + Arabic UI + `stored_read_only` matrix | **PASS** | `test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload`, `test_capabilities_oda_resolution_priority_absent_dwg_and_matrix`, `App.test.tsx`. |
| PR #15 Addition (1): Content-quality gate rejects login walls, country lists, cookie banners, photo archives, and thin stubs before `reviewed=True` | **PASS** | `test_research_quality_gate_bloomsbury_login_wall_cookie_wall_and_photo_archive` + live `doi.org/10.5040/9798400616747.ch-001` rejected as `unreviewed`. |
| PR #15 Addition (2): Relevance gate marks unrelated substantive prose `'not_relevant'` (`'unrated'`) and never cites it | **PASS** | `test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call` (`access_status="not_relevant"`, `reviewed=False`, `reliability_rating="unrated"`). |
| PR #15 Addition (3): Synthesis only states facts from substantive body prose; titles/metadata alone produce `0` claims & `0` Gemini calls | **PASS** | `test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call` + `build_research_synthesis_prompt()` omitting unreviewed titles + `_claim_grounded_in_body()`. |
| PR #15 Addition (4): Crossref non-articles/landings/archives never auto-rated `medium_peer_reviewed`; keep `'unrated'` unless full text read; tier shown as provider claim | **PASS** | `test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize`, `ResearchView.tsx`, `App.test.tsx`. |
| PR #15 Addition (5): Text sent to Gemini capped (`10k` chars total / `2.4k` per source); token estimate shown before large-run synthesis + Step 04 limits enforced | **PASS** | `test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize` (`POST /runs/{id}/synthesize` + HTTP `429` budget block), `App.test.tsx` (`~620 est. prompt tokens`). |
| PR #15 Addition (6): Live `RUN_REAL_RESEARCH=1` accepts real substantive prose (`hse.gov.uk`) & rejects login walls (`doi.org/10.5040/...`) + `403` (`osha.gov`) | **PASS** | Live `RUN_REAL_RESEARCH=1` (`accessible=1`, `inaccessible=2`, `est_prompt_tokens=1172`). |

## 6. Known Limitations & Deviations
- **DuckDuckGo Lite throttling behavior:** Free `https://lite.duckduckgo.com/lite/` frequently returns `HTTP 202` (anti-bot challenge) on automated queries. The engine never bypasses challenges and recommends a free **Tavily** API key in Settings, **Crossref**, direct URLs, or owner-provided uploaded files.
- **Arc-bulge real-drawing check:** Owner's local real DWGs contain no closed `LWPOLYLINE` with an arc bulge, so curved polyline accuracy rests on exact synthetic geometry tests.
- **Interactive UI check pending:** Frontend rendering and client workflows are verified via Vitest + `tsc` + Vite build; live owner browser walkthrough in `scripts/start.bat` remains `PENDING`.

## 7. Questions & How the Owner Can Try It
1. Launch `<repo>/scripts/start.bat` and open **البحث وسجل المصادر / Research & Source Log**.
2. Try searching `bathroom` via **Crossref** (e.g., `max_results=5`, `Synthesize via Gemini AI` checked):
   - Bloomsbury / publisher login walls and photo-archive / landing stubs are automatically rejected as `unreviewed` / `unrated` rather than spending `16k` tokens on titles and country lists.
   - If `0` sources survive the quality & relevance gates, Gemini spend stays **`0` tokens**.
   - If substantive sources survive on a large run, the UI pauses cleanly and shows the capped **`~N est. prompt tokens`** and remaining Step 04 budget with a **Confirm & Run Gemini Synthesis** button before calling Gemini.
3. Reply **`PASS step 08`** after PR `#15` review & merge when ready for **Step 09**.
