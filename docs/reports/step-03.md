# Step 03 — File upload, integrity and versioning

Date: 2026-11-19
Status: COMPLETE
Classification: Preliminary

## 1. Scope done

### Step 03 prerequisite tasks (completed before Step 03 feature work, commit `7b42384`)
- **`ON DELETE RESTRICT` integrity (`backend/app/db/models.py`, migration `0002_restrict_file_and_version_deletes.py`):**
  - Changed `files.project_id` and `file_versions.file_id` from `ondelete="CASCADE"` to `ondelete="RESTRICT"`, updated ORM relationships (`Project.files`, `ProjectFile.versions`) to `cascade="save-update, merge", passive_deletes="all"`, and added `test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions` proving both ORM and SQL deletion of projects with files or files with versions fail with `IntegrityError`.
  - Updated `backend/alembic/env.py` so SQLite batch table rebuilds temporarily disable `PRAGMA foreign_keys` outside the migration transaction and run `PRAGMA foreign_key_check` afterwards, enabling upgrades on already-populated SQLite databases.
- **`classification` `CHECK` constraints (`backend/app/db/base.py`, `backend/app/db/models.py`, migration `0003_add_classification_check_constraints.py`):**
  - Added `CLASSIFICATION_LABELS` and `classification_check_constraint()` enforcing the exact five `CLAUDE.md` labels (`Preliminary`, `Conceptual`, `For Review`, `For Coordination`, `For Approval`) across all five classified tables (`projects`, `files`, `tasks`, `deliverables`, `calculations`), verified in `test_classification_check_constraint_enforces_five_claude_labels`.
- **Rollback safety comment (`backend/app/services/projects.py`):**
  - Added an inline comment on the `shutil.rmtree(project_dir, ignore_errors=True)` fallback clarifying that `project_dir` was created with `exist_ok=False` for a fresh UUID slug, so rollback removes only the empty 12-folder tree created by the same failed request.

### Step 03 core implementation
- **Extension classification allowlist (`backend/app/services/file_classification.py`):**
  - Classified **41 supported extensions** across 7 categories into `01_Input_Documents` (17 extensions) and `02_Original_Drawings` (24 extensions) per `docs/SPEC.md` §6A, plus `GET /api/files/supported-extensions`.
- **Safe multi-file ingestion, hashing, deduplication & versioning (`backend/app/services/files.py`, `backend/app/schemas/files.py`, `backend/app/api/files.py`):**
  - Pinned `python-multipart==0.0.34` in `backend/requirements.txt` and added configurable `MAX_UPLOAD_SIZE_BYTES` (`52428800` / 50 MiB default) and `MAX_FILES_PER_UPLOAD` (`25` default) in `backend/app/core/config.py` and `.env.example`.
  - Streams uploaded files through SHA-256 calculation into an isolated `.upload_staging` workspace with atomic batch validation before moving files into `01_Input_Documents`, `02_Original_Drawings`, or `12_Revision_History`.
  - Rejects traversal payloads (`..\..\x`, `../...`), directory separators, drive prefixes (`C:...`), alternate data streams (`:`), NUL/control bytes, leading/trailing dots, Windows reserved stems (`CON`, `PRN`, `AUX`, `NUL`, `COM1–9`, `LPT1–9`), unsupported extensions, empty files (`0 B`), and oversized files (`413 Content Too Large`).
  - Sets stored files read-only (`0o444` / Windows `FILE_ATTRIBUTE_READONLY`), detects identical SHA-256 duplicates (both same filename and cross-filename), creates immutable `v2+` versions in `12_Revision_History/<file_id>/v<N>_<filename>` when changed files are re-uploaded (case-insensitive filename matching for Windows NTFS), leaves `v1` originals untouched, records all actions in `audit_log`, exposes `GET /api/projects/{id}/files`, `GET /api/files/{id}`, `GET /api/files/{id}/versions`, `GET /api/files/{id}/download` (`?version=N` and `/versions/{N}/download`), and blocks `PUT`/`PATCH`/`DELETE` file mutations with HTTP `403`.
- **Frontend drag-and-drop upload, file list & version history UI (`frontend/src/components/ProjectFilesPanel.tsx`, `frontend/src/components/ProjectWorkspaceView.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/App.tsx`, `frontend/src/index.css`):**
  - Added RTL-aware drag-and-drop + multi-file picker inside opened projects, upload outcome summary (`created` / `new_version` / `duplicate`), project file table (name, folder, type, size, SHA-256 hash, upload/update timestamp, version, classification, read-only badge, download button), and expandable immutable version history table with per-version download links.

### Package version added

| Package | Version | License | Notes |
|---|---|---|---|
| `python-multipart` | `0.0.34` | Apache-2.0 | Pinned in `backend/requirements.txt` for FastAPI multipart streaming |

### Supported vs. unsupported file extensions

#### Supported extensions (41 allowlisted formats)

| Target Folder | Category | Extensions |
|---|---|---|
| `01_Input_Documents` | Documents (`document`) | `.pdf`, `.doc`, `.docx`, `.txt`, `.rtf`, `.html`, `.htm`, `.md` |
| `01_Input_Documents` | Spreadsheets (`spreadsheet`) | `.xls`, `.xlsx`, `.csv`, `.ods` |
| `01_Input_Documents` | Presentations (`presentation`) | `.ppt`, `.pptx` |
| `01_Input_Documents` | Engineering Data (`data`) | `.xml`, `.json`, `.landxml` |
| `02_Original_Drawings` | CAD / Vector Drawings (`drawing`) | `.dwg`, `.dxf`, `.dgn`, `.dwf`, `.svg` |
| `02_Original_Drawings` | Raster Images (`image`) | `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp` |
| `02_Original_Drawings` | BIM & 3D Models (`bim_3d`) | `.ifc`, `.rvt`, `.rfa`, `.rte`, `.obj`, `.stl`, `.step`, `.stp`, `.iges`, `.igs`, `.gltf`, `.glb` |

#### Unsupported extensions (blocked with HTTP `400 Bad Request`)
- **Allowlist policy:** Any extensionless file or extension outside the 41 formats above is rejected before disk write.
- **Explicitly rejected categories/examples:** Executables, libraries, scripts, and nested archives including `.exe`, `.dll`, `.msi`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.js`, `.sh`, `.py`, `.zip`, `.rar`, and `.7z`.

## 2. Files created/changed
- `.env.example`, `backend/requirements.txt`, `backend/app/core/config.py`, `backend/app/main.py`
- `backend/app/db/{base.py,models.py}`, `backend/alembic/env.py`
- `backend/alembic/versions/{0002_restrict_file_and_version_deletes.py,0003_add_classification_check_constraints.py}`
- `backend/app/schemas/files.py`, `backend/app/services/{file_classification.py,files.py,projects.py,workspace.py}`, `backend/app/api/files.py`
- `backend/tests/{test_migrations.py,test_files.py}`
- `frontend/src/{App.tsx,App.test.tsx,api.ts,index.css,types.ts}`, `frontend/src/components/{ProjectFilesPanel.tsx,ProjectWorkspaceView.tsx}`
- `docs/DECISIONS.md` (`ADR-009`), `docs/reports/step-03.md`

*(Did not modify `.github/` or `CLAUDE.md`.)*

## 3. Tests run (pre-commit verification on final code)

### A. Dependency metadata (`pip show python-multipart`)
```text
Name: python-multipart
Version: 0.0.34
Summary: A streaming multipart parser for Python
Home-page: https://github.com/Kludex/python-multipart
Author: 
Author-email: Andrew Dunham <andrew@du.nham.ca>
License-Expression: Apache-2.0
Location: <repo>\backend\.venv\Lib\site-packages
Requires: 
Required-by: 
```

### B. Backend test suite (`pytest -v` in `backend/`)
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: <repo>\backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 16 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [  6%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 12%]
tests/test_config.py::test_blank_database_url_defaults_inside_workspaces_dir PASSED [ 18%]
tests/test_config.py::test_relative_sqlite_database_url_resolves_against_repo_root PASSED [ 25%]
tests/test_config.py::test_postgresql_and_memory_database_urls_pass_through PASSED [ 31%]
tests/test_files.py::test_classification_labels_match_schema PASSED      [ 37%]
tests/test_files.py::test_multi_file_upload_classification_readonly_and_download PASSED [ 43%]
tests/test_files.py::test_duplicate_detection_and_reupload_versioning_preserves_original PASSED [ 50%]
tests/test_files.py::test_malicious_filenames_unsupported_types_and_size_protections PASSED [ 56%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [ 62%]
tests/test_migrations.py::test_alembic_upgrade_and_downgrade_round_trip PASSED [ 68%]
tests/test_migrations.py::test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions PASSED [ 75%]
tests/test_migrations.py::test_classification_check_constraint_enforces_five_claude_labels PASSED [ 81%]
tests/test_projects.py::test_arabic_project_creation_folders_and_restart_persistence PASSED [ 87%]
tests/test_projects.py::test_duplicate_code_returns_409_without_orphaned_folder PASSED [ 93%]
tests/test_projects.py::test_validation_not_found_and_path_safety PASSED [100%]

============================= 16 passed in 4.84s ==============================
```

### C. Frontend unit tests & TypeScript/Vite build (`npm.cmd test` + `npm.cmd run build` in `frontend/`)
```text
> ai-engineering-agent-frontend@0.1.0 test
> vitest run

 RUN  v2.1.9 <repo>/frontend

 ✓ src/App.test.tsx (6 tests) 14ms

 Test Files  1 passed (1)
      Tests  6 passed (6)
   Duration  416ms

> ai-engineering-agent-frontend@0.1.0 build
> tsc --noEmit && vite build

vite v6.4.6 building for production...
transforming...
✓ 30 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.48 kB │ gzip:  0.33 kB
dist/assets/index-DyKG1074.css    4.87 kB │ gzip:  1.48 kB
dist/assets/index-1dU0GRNz.js   166.27 kB │ gzip: 52.96 kB
✓ built in 416ms
```

### D. Live Vite proxy + uvicorn upload/versioning/guard verification
Executed against an isolated temporary workspace under `workspaces/_step03_live_smoke` (removed on cleanup):
```text
LIVE_MULTI_UPLOAD: 5 ['01_Input_Documents', '01_Input_Documents', '01_Input_Documents', '02_Original_Drawings', '02_Original_Drawings']
LIVE_VERSION_V2: 1 2
LIVE_GUARDS_AND_DOWNLOADS: 403 400 True True
```

*(Final-head `pytest`, `vitest`, `build`, `node --test`, and `gitleaks` outputs at the exact final committed SHA are recorded in the Pull Request description.)*

## 4. Acceptance tests
1. **First tasks (DELETE `RESTRICT`, `classification` `CHECK` constraint, `rmtree` comment):** **PASS** — Verified in `test_migrations.py` (`test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions`, `test_classification_check_constraint_enforces_five_claude_labels`) and [projects.py](backend/app/services/projects.py).
2. **Upload PDF, DOCX, XLSX, DXF, image together:** **PASS** — Verified in `test_multi_file_upload_classification_readonly_and_download` (`created_count == 5`, `.pdf/.docx/.xlsx -> 01_Input_Documents`, `.dxf/.png -> 02_Original_Drawings`, SHA-256 & `audit_log` verified) and live HTTP proxy upload.
3. **Originals cannot be modified through the API (and read-only on disk):** **PASS** — Verified `0o444` (`stat.S_IWRITE == 0`) with `PermissionError` on direct disk write attempt plus HTTP `403` on `PUT`/`PATCH`/`DELETE` `/api/files/{id}` and `/api/projects/{pid}/files/{id}`.
4. **Re-uploading changed file creates a new version, original untouched; duplicates skipped:** **PASS** — Verified in `test_duplicate_detection_and_reupload_versioning_preserves_original`: unchanged same-name and renamed SHA-256 duplicates skipped (`duplicate_count == 1`), changed re-upload creates `v2` in `12_Revision_History/`, original `v1` remains read-only with exact original bytes/hash downloadable via `?version=1` and `/versions/1/download`.
5. **Malicious filename (`..\..\x`) rejected, plus size/type guardrails:** **PASS** — Verified in `test_malicious_filenames_unsupported_types_and_size_protections` rejecting `..\..\x`, `..\..\secret.pdf`, `../escape.pdf`, `subdir/plan.pdf`, `C:bad.pdf`, `plan.pdf:stream`, `CON.pdf`, `.hidden.pdf`, raw `C:\temp\bad.pdf` / NUL bytes, unsupported `.exe`, empty `0 B` files, atomic dirty-batch rollback, oversized uploads (`413`), and batch file-count overflow.

## 5. Decisions made (also in `docs/DECISIONS.md`)
- **ADR-009:** Applied `ON DELETE RESTRICT` + `passive_deletes="all"`, 5-label `CHECK` constraints, SQLite batch-rebuild FK handling in `alembic/env.py`, 41-extension allowlist matching `docs/SPEC.md` §6A, `0o444` read-only originals + `12_Revision_History` versioning, HTTP `403` immutability endpoints, and `python-multipart==0.0.34`.

## 6. Deviations from the plan and why
- **Dedicated `file_classification.py` module and `GET /api/files/supported-extensions`:** Kept extension-to-folder routing in a single source of truth so frontend file-picker `accept` hints stay synchronized with backend ingestion rules.
- **Explicit `PUT`/`PATCH`/`DELETE` `403` handlers on `/api/files/{file_id}`:** Instead of relying solely on missing routes (`405`), explicit `403` responses clearly enforce read-only immutability on existing original files.
- **Staging inside `<project_dir>/.upload_staging/<uuid>` before move:** Allows streaming SHA-256 verification and size enforcement within the configured workspace volume before placing files into `01_Input_Documents`, `02_Original_Drawings`, or `12_Revision_History`.

## 7. Known limitations / things not verified
- Legacy client behavior in `python-multipart` / `httpx2` strips Windows drive prefixes such as `C:\temp\` from `Content-Disposition` filenames before reaching FastAPI route handlers; raw filename validation rejecting drive paths (`C:\...`) and NUL bytes is verified directly on `validate_upload_filename`, while relative traversal payloads (`..\..\x`, `../...`, `:`) are tested through full HTTP multipart requests.
- File content extraction/OCR/CAD parsing (`pypdf`, `python-docx`, `openpyxl`, `ezdxf`, Tesseract, ODA) intentionally belongs to Step 06 and Step 07 and is not performed during Step 03 upload ingestion.
- External tools Tesseract OCR (`ara+eng`, Step 06) and ODA File Converter (Step 07) remain `not installed - pending owner`.

## 8. Questions or items needing the owner
- Start the app with `scripts\start.bat`, open a project at `http://127.0.0.1:5173`, drag and drop PDF, DOCX, XLSX, DXF, and PNG files together, re-upload a modified PDF to verify `v2` creation while downloading `v1` original intact, and confirm `workspaces\<project>\` files are read-only in Windows File Explorer.
- Review and merge this Step 03 PR yourself and reply `PASS step 03` before I begin Step 04.

## 9. How the owner can see/try it
1. Check out the PR branch or pull `main` after merging and run `scripts\start.bat`.
2. Open or create a project in `http://127.0.0.1:5173`.
3. Drag & drop multiple files (`.pdf`, `.docx`, `.xlsx`, `.dxf`, `.png`) into the upload zone and inspect the file list (type, folder, size, SHA-256, upload date, version) and **Version History** drawer.
4. Re-upload an edited copy of one file to observe `v2` created under `12_Revision_History\` while `v1` in `01_Input_Documents\` remains read-only and downloadable.
5. Run automated tests:
   - `cd backend && .\.venv\Scripts\python.exe -m pytest -v`
   - `cd frontend && npm.cmd test && npm.cmd run build`
   - `node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs`

## 10. Ready for next step?
**Yes** — Ready for owner review, merge, and `PASS step 03` to proceed to Step 04.
