# Step 08B — Research Source Quality, Domain Allowlists, Long Owner File Page Search & UI Honesty

- **Date:** 2026-11-21
- **Status:** **PARTIAL** *(Implemented strict allowlist-only priority classification eliminating URL/title keyword tier inflation, AI/SEO generation artifact detection & downgrade (` ``` ` code fences and bare `[n]` citations without reference lists), vendor product caps (`<= low_reputable_reference`), explicit `"URL/domain heuristic claim - unverified"` labeling on all non-owner tiers, full-document search across ALL extracted pages & tables for long owner-provided files with `project-file://<id>/v<N>#page:<n>` per-page citations and honest `not_relevant` reporting, UI clarity for `"Link to Project"` owner-file picker reveal, and dynamic `"Last modified (HTTP)"` column relabeling when no real publication date exists; verified with `76 passed, 3 skipped` full backend `pytest -v`, opt-in live research check, `19 passed` frontend Vitest + Vite production build, and zero `gitleaks` leaks; live owner re-verification on the real 145-page spec and live web queries in the UI remains `PENDING`)*
- **Branch:** `step-08b-research-source-quality`
- **Depends on:** `main` (`bc3cf49`, independent of Step 11 PR)

## 1. Scope Done

1. **Allowlist-Only Tier & Reliability Classification (`backend/app/services/research_fetch.py`):**
   - Removed ALL URL-path and `<title>` keyword heuristics (`"iec "`, `"iso "`, `"nfpa "`, `"standard specification"`, `"/regulation"`, `"datasheet"`, `"catalog"`, etc.) from `classify_source_priority()`.
   - Restricted `"official_regulations"` (`high_official_regulation`), `"standards_bodies"` (`high_standards_body` — `iec.ch`, `webstore.iec.ch`, `iso.org`, `bsigroup.com`, `astm.org`, `nfpa.org`, `ieee.org`, `standards.ieee.org`, `ashrae.org`, `concrete.org`, `cen.eu`, `cenelec.eu`, `etsi.org`, `din.de`, `who.int`, `fgiguidelines.org`, `iccsafe.org`, `saso.gov.sa`, `ansi.org`, `ul.com`, `cibse.org`, `istructe.org`, `eurocodes.jrc.ec.europa.eu`, `iaea.org`, `itu.int`, `asme.org`, `aami.org`), `"government"` (`high_government` — explicit `.gov` / `.gov.*` / `.gouv.fr` / `.gob.es` / official agency hosts, no `.edu` auto-escalation), `"manufacturer"` (`medium_manufacturer` — explicit OEM allowlist only), and `"peer_reviewed"` (`medium_peer_reviewed`) strictly to explicit domain allowlists (and verified Crossref full-text `journal-article` / `proceedings-article` hits).
   - Unknown commercial domains default to `"reputable"` / `"low_reputable_reference"` (or `"unrated"`), and vendor product HTML pages (`is_vendor_product_page()`) are capped at most at `"low_reputable_reference"`.
   - Every non-owner source carries **`"URL/domain heuristic claim - unverified"`** cleanly in `tier_claim_label` ([research.py](file:///c:/Engineering%20Agent/backend/app/services/research.py), [research_fetch.py](file:///c:/Engineering%20Agent/backend/app/services/research_fetch.py)).

2. **Generation Artifact Detection & Downgrade (`backend/app/services/research_fetch.py`):**
   - Added `detect_generation_artifacts()` flagging pages whose visible body contains literal markdown code fences (` ```html `, ` ``` `) or bare numeric citations (`[1][3][5]`, multiple `[n]`) without an accompanying references/bibliography list.
   - Downgrades affected pages to **`source_priority_tier="unverified"`** (`priority_rank=99`), **`reliability_rating="unrated"`**, `source_type="generation_artifact_downgraded"`, and prefixes an explicit `[DOWNGRADED — generation artifacts detected ...]` warning banner into extracted text and Verified Findings so vendor/SEO blogs never show `[standards_bodies]`.

3. **Full Multi-Page & Table Search for Long Owner Files (`backend/app/services/research.py`):**
   - Replaced `_load_owner_provided_source()` (which truncated at the first `12,000` characters) with `load_owner_provided_sources()`.
   - Scans **ALL** extracted pages (`page:1 .. page:N`) and **ALL** serialized extracted tables (`raw_values` & spreadsheet formulas/values, skipping unreliable native or blank/failed pages).
   - Scores every page against query terms (including alphanumeric code matches like `60439` <-> `60439-1`), selects the top-matching pages capped within `MAX_TOTAL_PROMPT_CHARS` (`10,000` chars) with match-centered windows, and cites each used page individually as **`project-file://<id>/v<N>#page:<n>`**.
   - Reports **`access_status="not_relevant"`** (`reviewed=False`, `reliability_rating="unrated"`) honestly when no page or table across the entire document matches the query.

4. **HTTP `Last-Modified` vs Publication Date & UI Clarity (`research_fetch.py`, `schemas/research.py`, `types.ts`, `ResearchView.tsx`):**
   - Removed `"last-modified"` from `_DATE_META_NAMES` so HTTP `Last-Modified` headers are never silently presented as real publication dates; tagged HTTP-derived dates as `"Last modified (HTTP): <value>"` with `publication_date_kind="http_last_modified"` (`PublicationDateKind` in [schemas/research.py](file:///c:/Engineering%20Agent/backend/app/schemas/research.py)).
   - Updated [ResearchView.tsx](file:///c:/Engineering%20Agent/frontend/src/components/ResearchView.tsx) (`ar` & `en`) to relabel the `Published` column dynamically as **`"Last modified (HTTP)"`** (`"آخر تعديل (HTTP)"`) whenever no real publication date exists in the run, and made the **`Link to Project`** dropdown and always-visible placeholder hint explicitly state that the uploaded owner-file picker appears only after a project is selected.

## 2. Files Created / Changed

### Created
- `<repo>/docs/reports/step-08b.md`

### Changed
- `<repo>/backend/app/schemas/research.py` *(added `PublicationDateKind` and `ResearchSourceOut.publication_date_kind`)*
- `<repo>/backend/app/services/research.py` *(replaced 12k-char truncated loader with `load_owner_provided_sources()` scanning all pages & tables with `#page:<n>` citations and `not_relevant` reporting; unified `"URL/domain heuristic claim - unverified"` & `publication_date_kind`)*
- `<repo>/backend/app/services/research_fetch.py` *(removed URL/title keyword tier inflation, enforced domain allowlists, added `detect_generation_artifacts()` & `is_vendor_product_page()`, distinguished HTTP `Last-Modified` cleanly)*
- `<repo>/backend/tests/test_research.py` *(added synthetic tests `test_step08b_no_keyword_tier_inflation_ai_artifact_downgrade_vendor_cap_and_last_modified` and `test_step08b_long_owner_145_page_pdf_searches_all_pages_tables_and_cites_page_fragments`)*
- `<repo>/docs/DECISIONS.md` *(added Step 08B clause 6 under `ADR-015` without colliding with Step 11 PR)*
- `<repo>/frontend/src/types.ts` *(added `PublicationDateKind` & `publication_date_kind`)*
- `<repo>/frontend/src/components/ResearchView.tsx` *(explicit Link-to-Project owner-file picker hint & `"Last modified (HTTP)"` column relabeling)*
- `<repo>/frontend/src/App.test.tsx` *(Vitest assertions for Link-to-Project hint & `"Last modified (HTTP)"` in EN/AR)*

*(Zero edits to `.github/` or `CLAUDE.md`; zero secrets, BOM bytes, local user paths, or client files committed.)*

## 3. Tests Run (Full Unedited Summary & Real Opt-In Check)

### Backend Full Suite (`pytest -v`)

```text
> & "backend\.venv\Scripts\pytest.exe" backend/tests -v
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
plugins: anyio-4.16.0
collecting ... collected 79 items

backend\tests\test_boq.py::test_step10_dxf_ifc_quantities_respect_confirmed_unit_and_never_silent_convert PASSED [  1%]
backend\tests\test_boq.py::test_step10_unsourced_rates_blocked_sourced_accepted_configurable_currency_and_xlsx_live_formulas PASSED [  2%]
backend\tests\test_boq.py::test_step10_import_xlsx_and_pdf_boqs_and_seeded_checks_duplicates_missing_units_arithmetic PASSED [  3%]
backend\tests\test_cad_bim.py::test_capabilities_oda_resolution_priority_absent_dwg_and_matrix PASSED [  5%]
backend\tests\test_cad_bim.py::test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits PASSED [  6%]
backend\tests\test_cad_bim.py::test_dwg_conversion_pipeline_mocked_preserves_original_and_versions PASSED [  7%]
backend\tests\test_cad_bim.py::test_optin_real_oda_converter_dwg_to_dxf SKIPPED [  8%]
backend\tests\test_cad_bim.py::test_extract_ifc_spaces_areas_elements_properties_and_known_limits PASSED [ 10%]
backend\tests\test_cad_bim.py::test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap PASSED [ 11%]
backend\tests\test_cad_bim.py::test_extract_dxf_hatch_with_island_subtracts_hole_area PASSED [ 12%]
backend\tests\test_cad_bim.py::test_dwg_refuses_existing_converted_run_dir_with_409 PASSED [ 13%]
backend\tests\test_cad_bim.py::test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit PASSED [ 15%]
backend\tests\test_cad_bim.py::test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin PASSED [ 16%]
backend\tests\test_cad_bim.py::test_extract_closed_lwpolyline_with_semicircular_arc_bulge_exact_area PASSED [ 17%]
backend\tests\test_cad_bim.py::test_extract_dxf_marks_area_bearing_layers_and_groups_with_non_net_label PASSED [ 18%]
backend\tests\test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 20%]
backend\tests\test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 21%]
backend\tests\test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 22%]
backend\tests\test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 24%]
backend\tests\test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 25%]
backend\tests\test_extraction.py::test_extract_pdf_text_tables_page_images_and_preserve_units PASSED [ 26%]
backend\tests\test_extraction.py::test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract PASSED [ 27%]
backend\tests\test_extraction.py::test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units PASSED [ 29%]
backend\tests\test_extraction.py::test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures PASSED [ 30%]
backend\tests\test_extraction.py::test_tesseract_resolution_priority_single_probe_and_300dpi_render PASSED [ 31%]
backend\tests\test_extraction.py::test_optin_real_tesseract_ara_eng_on_committed_fixture SKIPPED [ 32%]
backend\tests\test_extraction.py::test_extract_csv_multiline_quoted_arabic_and_offset_traceability PASSED [ 34%]
backend\tests\test_extraction.py::test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden PASSED [ 35%]
backend\tests\test_extraction.py::test_extraction_hash_mismatch_and_refuse_existing_run_dir PASSED [ 36%]
backend\tests\test_extraction.py::test_pptx_grouped_shapes_and_multiframe_tiff_warning PASSED [ 37%]
backend\tests\test_extraction.py::test_arabic_native_pdf_cid_or_reversed_text_triggers_300dpi_ocr_and_never_not_needed PASSED [ 39%]
backend\tests\test_extraction.py::test_twelve_page_scanned_pdf_reconciles_all_pages_including_blank_and_failed PASSED [ 40%]
backend\tests\test_extraction.py::test_ocr_per_page_tesseract_mean_confidence_and_low_confidence_flag PASSED [ 41%]
backend\tests\test_files.py::test_classification_labels_match_schema PASSED [ 43%]
backend\tests\test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 44%]
backend\tests\test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 45%]
backend\tests\test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 46%]
backend\tests\test_files.py::test_pr9_hardening_early_content_length_mime_hint_double_dot_and_error_maps PASSED [ 48%]
backend\tests\test_health.py::test_api_health_returns_ok PASSED          [ 49%]
backend\tests\test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 50%]
backend\tests\test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 51%]
backend\tests\test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 53%]
backend\tests\test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 54%]
backend\tests\test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 55%]
backend\tests\test_projects.py::test_validation_not_found_and_path_safety PASSED [ 56%]
backend\tests\test_providers.py::test_keyring_secret_store_round_trip PASSED [ 58%]
backend\tests\test_providers.py::test_gemini_provider_text_structured_pdf_image_and_tools PASSED [ 59%]
backend\tests\test_providers.py::test_provider_errors_and_secret_scrubbing PASSED [ 60%]
backend\tests\test_providers.py::test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak PASSED [ 62%]
backend\tests\test_providers.py::test_monthly_usage_limits_and_failed_attempt_counting PASSED [ 63%]
backend\tests\test_providers.py::test_debug_logging_never_leaks_api_key PASSED [ 64%]
backend\tests\test_providers.py::test_verify_gemini_live_script_with_mocked_provider PASSED [ 65%]
backend\tests\test_providers.py::test_provider_404_model_not_found_handling PASSED [ 67%]
backend\tests\test_providers.py::test_refresh_models_filters_generate_content_and_startup_check PASSED [ 68%]
backend\tests\test_providers.py::test_gemini_provider_503_exponential_backoff_retry_and_exhaustion PASSED [ 69%]
backend\tests\test_reports.py::test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download PASSED [ 70%]
backend\tests\test_reports.py::test_step09_ai_enhance_caps_prompt_enforces_ref_links_versions_cleanly_and_checks_step04 PASSED [ 72%]
backend\tests\test_reports.py::test_step09_only_cites_reliable_text_and_excludes_failed_blank_cid_reversed_or_low_confidence PASSED [ 73%]
backend\tests\test_reports.py::test_step09b_cad_area_bearing_layers_confirmed_unit_and_no_none_unit PASSED [ 74%]
backend\tests\test_reports.py::test_step09b_dxf_vs_dwg_mismatch_raises_high_reconciliation_and_withholds_conflicting_areas PASSED [ 75%]
backend\tests\test_reports.py::test_step09b_ocr_separated_document_register_no_boilerplate_and_showing_n_of_m_appendix PASSED [ 77%]
backend\tests\test_reports.py::test_step09_leftovers_cited_sources_only_no_none_unconfirmed_other_file_and_v2_revision_note PASSED [ 78%]
backend\tests\test_research.py::test_research_priority_order_fetch_pdf_and_snippets_never_evidence PASSED [ 79%]
backend\tests\test_research.py::test_research_deliberate_prompt_injection_webpage_not_obeyed PASSED [ 81%]
backend\tests\test_research.py::test_research_inaccessible_documents_reported_as_unreviewed PASSED [ 82%]
backend\tests\test_research.py::test_research_usage_limits_ssrf_and_optional_search_keyring PASSED [ 83%]
backend\tests\test_research.py::test_research_403_refererless_retry_zero_accessible_skips_gemini_and_owner_provided_upload PASSED [ 84%]
backend\tests\test_research.py::test_research_quality_gate_bloomsbury_login_wall_cookie_wall_and_photo_archive PASSED [ 86%]
backend\tests\test_research.py::test_research_relevance_gate_and_titles_only_never_evidence_no_gemini_call PASSED [ 87%]
backend\tests\test_research.py::test_research_crossref_no_auto_peer_reviewed_provider_claim_and_token_cap_synthesize PASSED [ 88%]
backend\tests\test_research.py::test_step08b_no_keyword_tier_inflation_ai_artifact_downgrade_vendor_cap_and_last_modified PASSED [ 89%]
backend\tests\test_research.py::test_step08b_long_owner_145_page_pdf_searches_all_pages_tables_and_cites_page_fragments PASSED [ 91%]
backend\tests\test_research.py::test_optin_real_live_controlled_research_no_client_data SKIPPED [ 92%]
backend\tests\test_tasks.py::test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history PASSED [ 93%]
backend\tests\test_tasks.py::test_step05_missing_referenced_file_triggers_clarification PASSED [ 94%]
backend\tests\test_tasks.py::test_step05_untrusted_delimiter_neutralization PASSED [ 96%]
backend\tests\test_tasks.py::test_step05_startup_marks_stale_running_tasks_interrupted PASSED [ 97%]
backend\tests\test_tasks.py::test_step05_failures_are_logged_not_hidden_without_secret_leaks PASSED [ 98%]
backend\tests\test_tasks.py::test_step05_assumptions_always_labelled_for_owner_confirmation PASSED [100%]

================== 76 passed, 3 skipped in 94.24s (0:01:34) ===================
```

### Opt-In Live Research Check (`RUN_REAL_RESEARCH=1`)

```text
> $env:RUN_REAL_RESEARCH="1"; & "backend\.venv\Scripts\pytest.exe" backend/tests/test_research.py -k "optin_real" -v -s
LIVE RESEARCH SAMPLE: provider=duckduckgo_lite | total=3 | accessible=1 | inaccessible=2 | est_prompt_tokens=1178 | artifact=11_References/research/.../research_log.json
SOURCE tier=government rating=high_government reviewed=True url=https://www.hse.gov.uk/fireandexplosion/workplace.htm http=200
SOURCE tier=official_regulations rating=unreviewed reviewed=False url=https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37 http=403
SOURCE tier=peer_reviewed rating=unreviewed reviewed=False url=https://doi.org/10.5040/9798400616747.ch-001 http=200
====================== 1 passed, 10 deselected in 6.46s =======================
```

### Frontend (`vitest` + `tsc --noEmit` + `vite build`) & Security Hygiene
- `vitest`: `19 passed (19)` (`617ms`)
- `tsc --noEmit && vite build`: `built in 523ms`
- `gitleaks` & BOM/protected-paths checks: re-verified cleanly at final commit SHA.

## 4. Known Limits & Owner Re-Verification Needed
1. **Live UI Re-Test on Real 145-Page Spec & Real Web Query (`PENDING`):** Synthetic 145-page PDF (`#page:87` prose & `#page:118` table) and synthetic `ecalpro.com`/`power-panels.net`/`powerdistributionpanels.net` fixtures pass automated checks; live UI verification with the owner's real 145-page hospital/electrical specification PDF and real `"power center panel TTA IEC EN 60439"` search results remains with the owner before changing Status from **`PARTIAL`** to `PASS`.
2. **Allowlist Maintenance:** Only explicit domains in `_REGULATION_HOST_MARKERS`, `_STANDARDS_HOSTS`, `_GOVERNMENT_ALLOWLIST_HOSTS`/`.gov*`, `_MANUFACTURER_HOSTS`, and `_PEER_REVIEWED_HOSTS` receive elevated tiers; reputable regional standards bodies not yet listed default conservatively to `"reputable"` (`low_reputable_reference`) until explicitly added.
