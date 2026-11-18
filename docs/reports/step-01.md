# Step 01 — Environment and repository

Date: 2026-11-18
Status: COMPLETE
Classification: Preliminary
Revision: v2 (FIX applied on `step-01-environment-and-repo`)

## 1. Scope done
- **Step 00 follow-up tasks completed before Step 01 work (`8fec9bb`):**
  - Corrected `docs/reports/step-00.md` (`2/2` → `3/3` passed) and updated §3.C to cite final PR #6 head (`fc3b1d8`) `gitleaks` output with ANSI colour codes stripped (`14 commits scanned`, `95.72 KB`, `no leaks found`, exit `0`).
  - Widened `tests/test_no_local_paths.mjs` to check all drive letters (`[A-Za-z]:[\\/]Users[\\/]`) and added a Rule 12a check for `/workspaces/` (`isWorkspaceTrackedPath`), with dedicated unit test cases.
  - Hardened `/workspaces/` check (`856ce55`): `getAllTrackedFiles()` in `tests/helpers.mjs` now scans full `git ls-files -z` including binary files, with an explicit test case for `workspaces/p/drawing.pdf` in `tests/test_no_local_paths.mjs`.
  - Recorded in `docs/DECISIONS.md` (ADR-005) and this report that PR #6 merged into `main` as a regular merge commit (`daa309a`), not a squash merge, so commit `09014b8` (containing local scratch-path strings) remains in `main`'s history with explicit owner acceptance.
- **Installed & verified local runtime tools:** Installed Python `3.12.10` (`winget` user scope) and created `backend/.venv`; verified Git (`2.55.0.windows.3`), Node (`v24.18.0`), npm (`11.16.0`), and `pytest` (`8.4.2`).
- **Created repository folder structure per plan:**
  - `/backend/app/{api,core,db,providers,agents,skills,tools,services}` and `/backend/tests`
  - `/frontend/src`
  - `/docs/{SPEC.md,DECISIONS.md,reports/,user-guide/}`
  - `/scripts/`
  - `/workspaces/` (created at runtime by `scripts/start.bat`, git-ignored)
- **Copied Master Development Prompt verbatim into `docs/SPEC.md` (`3a859f7`):** Saved as UTF-8 without BOM and verified SHA-256 matches `bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f` verbatim.
- **Built Step 01 backend & frontend placeholder + launcher (`e9f5f82`, `856ce55`):**
  - FastAPI backend (`backend/app/main.py`, `backend/app/api/health.py`, `backend/app/core/config.py`) exposing `GET /api/health` (`200 OK`, `Classification: Preliminary`) + `backend/tests/test_health.py` + `backend/tests/test_config.py`.
  - Pinned exact tested Python dependencies in `backend/requirements.txt` (`fastapi==0.164.0`, `uvicorn[standard]==0.54.0`, `pydantic-settings==2.16.3`, `pytest==8.4.2`, `httpx2==2.16.2`).
  - `Settings.workspaces_dir` resolves blank or relative `WORKSPACES_DIR` against `REPO_ROOT` (`backend/app/core/config.py`); `.env.example` leaves `WORKSPACES_DIR=` blank and omits `DATABASE_URL` until Step 02.
  - React + TypeScript + Vite frontend (`frontend/src/App.tsx`, `frontend/vite.config.ts`) with Arabic (`dir="rtl"`) default layout, English (`dir="ltr"`) toggle, live `/api/health` check via env-driven Vite proxy (`BACKEND_HOST`/`BACKEND_PORT`), unified single host `127.0.0.1`, and `frontend/src/App.test.tsx`.
  - `README.md`, `.env.example`, `scripts/start.bat`, `scripts/wait_for_servers.py`, and ADR-007 in `docs/DECISIONS.md`.

### Tool versions

| Tool / Component | Version / Status | Notes |
|---|---|---|
| Git (`git --version`) | `2.55.0.windows.3` | Installed |
| Node.js (`node --version`) | `v24.18.0` | Installed |
| npm (`npm.cmd --version`) | `11.16.0` | Installed (invoke `npm.cmd` in PowerShell/.bat) |
| Python (`backend\.venv\Scripts\python.exe --version`) | `3.12.10` | Installed via `winget` (`Python.Python.3.12`, user scope) |
| pytest (`pytest --version`) | `8.4.2` | Installed in `backend/.venv` |
| FastAPI / Starlette / Uvicorn / Pydantic-Settings / httpx2 | `0.164.0` / `1.10.0` / `0.54.0` / `2.16.3` / `2.16.2` | Pinned in `backend/requirements.txt` |
| React / Vite / TypeScript / Vitest | `18.3.1` / `6.4.6` / `5.9.3` / `2.1.9` | Locked in `frontend/package-lock.json` |
| Tesseract OCR (`ara` + `eng`) | **not installed - pending owner** | Manual install required (Step 06) |
| ODA File Converter | **not installed - pending owner** | Manual install required (Step 07) |

## 2. Files created/changed
- `README.md`, `.env.example`
- `backend/pytest.ini`, `backend/requirements.txt`
- `backend/app/{__init__,main}.py`, `backend/app/{api,core,db,providers,agents,skills,tools,services}/__init__.py`
- `backend/app/api/health.py`, `backend/app/core/config.py`
- `backend/tests/__init__.py`, `backend/tests/test_health.py`, `backend/tests/test_config.py`
- `frontend/{index.html,package.json,package-lock.json,tsconfig.json,vite.config.ts,vitest.config.ts}`
- `frontend/src/{index.css,main.tsx,App.tsx,App.test.tsx}`
- `scripts/start.bat`, `scripts/wait_for_servers.py`
- `docs/SPEC.md`, `docs/DECISIONS.md`, `docs/user-guide/README.md`, `docs/reports/step-00.md`, `docs/reports/step-01.md`
- `tests/helpers.mjs`, `tests/test_no_local_paths.mjs`

*(Did not modify `.github/` or `CLAUDE.md`.)*

## 3. Tests run (exact commands + real output)

### A. `httpx2` verification (`pip show`, `starlette/testclient.py`, PyPI metadata)
```powershell
backend\.venv\Scripts\python.exe -m pip show httpx2 starlette fastapi
```
Output (paths sanitized with `<repo>`):
```text
Name: httpx2
Version: 2.16.2
Summary: The next generation HTTP client.
Home-page: https://github.com/pydantic/httpx2
Author: 
Author-email: Tom Christie <tom@tomchristie.com>
License-Expression: BSD-3-Clause
Location: <repo>\backend\.venv\Lib\site-packages
Requires: anyio, httpcore2, idna, truststore, typing-extensions
Required-by: 
---
Name: starlette
Version: 1.10.0
Summary: The little ASGI library that shines.
Home-page: https://github.com/Kludex/starlette
Author: 
Author-email: Tom Christie <tom@tomchristie.com>
License-Expression: BSD-3-Clause
Location: <repo>\backend\.venv\Lib\site-packages
Requires: anyio, typing-extensions
Required-by: fastapi
---
Name: fastapi
Version: 0.164.0
Summary: FastAPI framework, high performance, easy to learn, fast to code, ready for production
Home-page: https://github.com/fastapi/fastapi
Author: 
Author-email: Sebastián Ramírez <tiangolo@gmail.com>
License-Expression: MIT
Location: <repo>\backend\.venv\Lib\site-packages
Requires: annotated-doc, anyio, opentelemetry-api, pydantic, starlette, typing-extensions, typing-inspection
Required-by: 
```
- **Import lines in installed `<repo>\backend\.venv\Lib\site-packages\starlette\testclient.py` (lines 25–44):**
  ```python
  if TYPE_CHECKING:
      import httpx2 as httpx
  else:
      try:
          import httpx2 as httpx
      except ModuleNotFoundError:  # pragma: no cover
          try:
              import httpx
          except ModuleNotFoundError:
              raise RuntimeError(
                  "The starlette.testclient module requires the httpx2 package to be installed.\n"
                  "You can install this with:\n"
                  "    $ pip install httpx2\n"
              ) from None
          else:
              warnings.warn(
                  "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.",
                  StarletteDeprecationWarning,
                  stacklevel=2,
              )
  ```
- **PyPI link & maintainer (verified from `https://pypi.org/pypi/httpx2/json`):**
  - PyPI project page: `https://pypi.org/project/httpx2/` (Source: `https://github.com/pydantic/httpx2`)
  - Maintainer: `"Pydantic Services Inc." <engineering@pydantic.dev>` (Author: `Tom Christie <tom@tomchristie.com>`)

### B. `docs/SPEC.md` verbatim SHA-256 and UTF-8 (no BOM) verification (`3a859f7`)
```powershell
(Get-FileHash "docs\SPEC.md" -Algorithm SHA256).Hash.ToLower()
backend\.venv\Scripts\python.exe -c "import hashlib, subprocess; data = subprocess.check_output(['git', 'cat-file', 'blob', ':docs/SPEC.md']); print('git_blob_sha256:', hashlib.sha256(data).hexdigest())"
```
Output:
```text
bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f
git_blob_sha256: bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f
```

### C. Backend `pytest` (`856ce55`)
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
```
Output (paths sanitized with `<repo>`):
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- <repo>\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: <repo>\backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 3 items

tests/test_config.py::test_blank_workspaces_dir_defaults_to_repo_root PASSED [ 33%]
tests/test_config.py::test_relative_workspaces_dir_resolves_against_repo_root PASSED [ 66%]
tests/test_health.py::test_api_health_returns_ok PASSED                  [100%]

============================== 3 passed in 0.32s ==============================
```

### D. Frontend `vitest` and TypeScript/Vite build (`856ce55`)
```powershell
cd frontend
npm.cmd test
npm.cmd run build
```
Output (paths sanitized with `<repo>`):
```text
 RUN  v2.1.9 <repo>/frontend

 ✓ src/App.test.tsx (2 tests) 4ms

 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  21:18:26
   Duration  351ms (transform 31ms, setup 0ms, collect 52ms, tests 4ms, environment 0ms, prepare 78ms)

vite v6.4.6 building for production...
✓ 27 modules transformed.
dist/index.html                   0.46 kB │ gzip:  0.33 kB
dist/assets/index-4CptX-19.css    1.11 kB │ gzip:  0.55 kB
dist/assets/index-DBswrZ6I.js   146.18 kB │ gzip: 47.35 kB
✓ built in 393ms
```

### E. End-to-end `scripts/start.bat` smoke test (`856ce55`, `NO_BROWSER=1`)
```powershell
$env:NO_BROWSER = "1"; cmd.exe /c "scripts\start.bat"
# Verified http://127.0.0.1:8000/api/health, http://127.0.0.1:5173/, and proxied http://127.0.0.1:5173/api/health
```
Output:
```text
Starting Backend on http://127.0.0.1:8000 ...
Starting Frontend on http://127.0.0.1:5173 ...
Waiting for backend and frontend to listen...
Both backend and frontend are responding.
Launched backend (http://127.0.0.1:8000/api/health) and frontend (http://127.0.0.1:5173).
{
    "direct_status":  200,
    "direct_body":  "{\"status\":\"ok\",\"service\":\"ai-engineering-agent\",\"version\":\"0.1.0\",\"environment\":\"development\",\"classification\":\"Preliminary\"}",
    "ui_status":  200,
    "ui_has_dir_rtl":  true,
    "ui_has_title":  true,
    "proxied_status":  200,
    "proxied_body":  "{\"status\":\"ok\",\"service\":\"ai-engineering-agent\",\"version\":\"0.1.0\",\"environment\":\"development\",\"classification\":\"Preliminary\"}"
}
```

### F. UTF-8 (no BOM) and Rule 12a full-tree `/workspaces/` & path checks (`856ce55`)
```powershell
node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs
```
Output:
```text
✔ no committed text file leaks local user home paths (Rule 12a) (34.1675ms)
✔ no committed file (including binaries) is tracked inside /workspaces/ (Rule 12a) (24.8521ms)
✔ local user path detector catches other drive letters ([A-Za-z]:\Users\) (0.1904ms)
✔ /workspaces/ detector flags tracked binary and text workspace paths (0.1616ms)
✔ all committed text files are valid UTF-8 without BOM (31.4661ms)
✔ Arabic sample file is tracked and decodes as valid UTF-8 with Arabic script (24.8222ms)
ℹ tests 6
ℹ suites 0
ℹ pass 6
ℹ fail 0
```
*(Fresh final-head `pytest`, `vitest`, `node --test`, and `gitleaks` outputs after committing `docs/reports/step-01.md` are pasted in the Step 01 PR description, along with the commit-count vs `gitleaks`-scanned-count explanation: `gitleaks` skips 1 merge commit `daa309a` and 1 empty commit `9af9813`, so `total_commits - 2` non-empty, non-merge commits are scanned.)*

## 4. Acceptance tests
1. **`scripts/start.bat` opens the app at `http://127.0.0.1:5173` showing a placeholder page and `/api/health` returns OK:** **PASS** (smoke test verified `200` on `http://127.0.0.1:5173/`, `http://127.0.0.1:8000/api/health`, and proxied `http://127.0.0.1:5173/api/health`, with `dir="rtl"` Arabic + English UI).
2. **`pytest` runs and passes:** **PASS** (`3 passed in 0.32s`).
3. **Tool versions listed and manual installs documented:** **PASS** (Git, Node, npm, Python, pytest, and pinned package versions listed in §1; Tesseract `ara+eng` and ODA File Converter marked `not installed - pending owner` with manual install instructions in §8).
4. **Master prompt copied verbatim into `docs/SPEC.md` (UTF-8 no BOM):** **PASS** (SHA-256 `bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f`, UTF-8 without BOM verified).
5. **Step 00 follow-ups & Rule 12a safety checks (`step-00.md` fix, full `git ls-files -z` `/workspaces/` check with `workspaces/p/drawing.pdf` test case, `[A-Za-z]:\Users\` check, `gitleaks`):** **PASS** (`6/6` Node tests passed; `gitleaks` exit `0`).

## 5. Decisions made (also in `docs/DECISIONS.md`)
- **ADR-005 update:** Recorded that PR #6 merged into `main` via regular merge commit `daa309a` (not squashed), so commit `09014b8`'s scratch-path strings remain in `main`'s history with explicit owner acceptance.
- **ADR-007:** Recorded unified single host `127.0.0.1`, env-driven Vite proxy (`BACKEND_HOST`/`BACKEND_PORT`), `REPO_ROOT`-resolved `WORKSPACES_DIR`, pinned `backend/requirements.txt` versions (`httpx2==2.16.2` verified against `starlette==1.10.0`), `npm.cmd`, and `scripts/wait_for_servers.py`.

## 6. Deviations from the plan and why
- **Tesseract OCR and ODA File Converter left un-installed (`not installed - pending owner`):** Per owner instructions, Step 01 is not blocked on these two tools; Tesseract is first needed in Step 06 and ODA File Converter is first needed in Step 07 (manual download/license acceptance).
- **Added `scripts/wait_for_servers.py`:** Windows `timeout.exe` fails under redirected stdin (`ERROR: Input redirection is not supported`), so a small HTTP readiness poller was added alongside `scripts/start.bat`.
- **Used `httpx2==2.16.2` instead of `httpx` in `backend/requirements.txt`:** `starlette 1.10.0` (pulled by `fastapi 0.164.0`) imports `httpx2` in `starlette/testclient.py:26,29` and deprecates `httpx` fallback.

## 7. Known limitations / things not verified
- **Tesseract OCR (`ara` + `eng`)** and **ODA File Converter** are `not installed - pending owner` and therefore not verified at runtime in Step 01.
- Automated `scripts/start.bat` smoke test ran with `NO_BROWSER=1`; opening the default Windows browser interactively when double-clicked is left for the owner to confirm manually.
- `docs/SPEC.md` originally uses LF (`\n`) line endings; on Windows clones with `core.autocrlf=true`, Git stores LF in the repository blob (`bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f`), while local CRLF conversion on re-checkout would alter local file bytes unless `core.autocrlf` is off or LF is preserved.
- **Merge history disclosure:** PR #6 merged into `main` via regular merge commit `daa309a` (rather than squash merge), leaving commit `09014b8`'s scratch-path strings in `main`'s history (explicitly accepted by the owner).

## 8. Questions or items needing the owner

### Owner must install manually

#### A. Tesseract OCR (`ara` + `eng`)
- **Status:** `not installed - pending owner`
- **Official download page:** `https://github.com/UB-Mannheim/tesseract/wiki`
- **Version needed:** Tesseract 5.x (64-bit Windows installer from UB-Mannheim)
- **Exact install choices:**
  1. Run the 64-bit Windows setup (`tesseract-ocr-w64-setup-*.exe`).
  2. On the **Choose Components** screen, expand **Additional language data (download)** and select **Arabic (`ara`)** alongside the default **English (`eng`)** (or download `ara.traineddata` from `https://github.com/tesseract-ocr/tessdata` and copy it into `C:\Program Files\Tesseract-OCR\tessdata\`).
  3. Add `C:\Program Files\Tesseract-OCR` to `PATH` (or set `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`).
- **Command to run afterwards to verify:**
  ```powershell
  tesseract --version
  tesseract --list-langs
  ```
  Confirm `eng` and `ara` both appear in `--list-langs`.
- **Step first needed:** **Step 06** (Document, spreadsheet and image extraction — OCR fallback).

#### B. ODA File Converter
- **Status:** `not installed - pending owner`
- **Official download page:** `https://www.opendesign.com/guestfiles/oda_file_converter`
- **Version needed:** Current official Windows 64-bit release from Open Design Alliance
- **Exact install choices:**
  1. Review and accept the Open Design Alliance license terms on the official guestfiles page and download the Windows 64-bit installer.
  2. Install using the default directory (typically `C:\Program Files\ODA\ODAFileConverter ...`).
  3. Add the installation directory to `PATH` or set `ODA_FILE_CONVERTER_PATH` in `.env`.
- **Command to run afterwards to verify:**
  ```powershell
  Get-ChildItem "C:\Program Files\ODA" -Recurse -Filter "ODAFileConverter.exe"
  ```
  Confirm `ODAFileConverter.exe` exists and launches cleanly.
- **Step first needed:** **Step 07** (Drawing and BIM ingestion — DWG ↔ DXF conversion).

### Owner checks for Step 01
- Test `scripts\start.bat` locally and confirm `http://127.0.0.1:5173` opens in your browser with the Arabic/English placeholder UI and `status: "ok"` health card.
- Review and merge this Step 01 PR yourself and reply `PASS step 01` before I begin Step 02.

## 9. How the owner can see/try it
1. Check out the PR branch or pull after merging, copy `.env.example` to `.env` if desired.
2. Run `scripts\start.bat` from the repository root (opens `http://127.0.0.1:5173`, backend at `http://127.0.0.1:8000/api/health`).
3. Run tests:
   - `cd backend && .\.venv\Scripts\python.exe -m pytest -v`
   - `cd frontend && npm.cmd test`
   - `node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs`

## 10. Ready for next step?
**Yes** — Ready for owner review, merge, and `PASS step 01` to proceed to Step 02.
