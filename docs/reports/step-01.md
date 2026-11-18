# Step 01 — Environment and repository

Date: 2026-11-18
Status: COMPLETE
Classification: Preliminary
Revision: v1

## 1. Scope done
- **Step 00 follow-up tasks completed before Step 01 work (`8fec9bb`):**
  - Corrected `docs/reports/step-00.md` (`2/2` → `3/3` passed) and updated §3.C to cite final PR #6 head (`fc3b1d8`) `gitleaks` output with ANSI colour codes stripped (`14 commits scanned`, `95.72 KB`, `no leaks found`, exit `0`).
  - Widened `tests/test_no_local_paths.mjs` to check all drive letters (`[A-Za-z]:[\\/]Users[\\/]`) and added a Rule 12a check for `/workspaces/` (`isWorkspaceTrackedPath`), with dedicated unit test cases for both.
  - Recorded in `docs/DECISIONS.md` (ADR-005) and this report that PR #6 merged into `main` as a regular merge commit (`daa309a`), not a squash merge, so commit `09014b8` (containing local scratch-path strings) remains in `main`'s history with explicit owner acceptance.
- **Installed & verified local runtime tools:** Installed Python `3.12.10` (`winget` user scope) and created `backend/.venv`; verified Git (`2.55.0.windows.3`), Node (`v24.18.0`), npm (`11.16.0`), and `pytest` (`8.4.2`).
- **Created repository folder structure per plan:**
  - `/backend/app/{api,core,db,providers,agents,skills,tools,services}` and `/backend/tests`
  - `/frontend/src`
  - `/docs/{SPEC.md,DECISIONS.md,reports/,user-guide/}`
  - `/scripts/`
  - `/workspaces/` (created at runtime by `scripts/start.bat`, git-ignored)
- **Copied Master Development Prompt verbatim into `docs/SPEC.md` (`3a859f7`):** Saved as UTF-8 without BOM and verified SHA-256 matches `bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f` verbatim.
- **Built Step 01 backend & frontend placeholder + launcher:**
  - FastAPI backend (`backend/app/main.py`, `backend/app/api/health.py`, `backend/app/core/config.py`) exposing `GET /api/health` (`200 OK`, `Classification: Preliminary`) + `backend/tests/test_health.py`.
  - React + TypeScript + Vite frontend (`frontend/src/App.tsx`) with Arabic (`dir="rtl"`) default layout, English (`dir="ltr"`) toggle, live `/api/health` check via Vite proxy, and `frontend/src/App.test.tsx`.
  - `README.md`, `.env.example`, `scripts/start.bat`, `scripts/wait_for_servers.py`, and ADR-007 in `docs/DECISIONS.md`.

### Tool versions

| Tool / Component | Version / Status | Notes |
|---|---|---|
| Git (`git --version`) | `2.55.0.windows.3` | Installed |
| Node.js (`node --version`) | `v24.18.0` | Installed |
| npm (`npm.cmd --version`) | `11.16.0` | Installed (invoke `npm.cmd` in PowerShell/.bat) |
| Python (`backend\.venv\Scripts\python.exe --version`) | `3.12.10` | Installed via `winget` (`Python.Python.3.12`, user scope) |
| pytest (`pytest --version`) | `8.4.2` | Installed in `backend/.venv` |
| FastAPI / Uvicorn / Pydantic-Settings / httpx2 | `0.164.0` / `0.54.0` / `2.16.3` / `2.16.2` | Installed in `backend/.venv` |
| React / Vite / TypeScript / Vitest | `18.3.1` / `6.4.6` / `5.9.3` / `2.1.9` | Installed in `frontend/node_modules` |
| Tesseract OCR (`ara` + `eng`) | **not installed - pending owner** | Manual install required (Step 06) |
| ODA File Converter | **not installed - pending owner** | Manual install required (Step 07) |

## 2. Files created/changed
- `README.md`
- `.env.example`
- `backend/pytest.ini`
- `backend/requirements.txt`
- `backend/app/__init__.py`
- `backend/app/main.py`
- `backend/app/api/__init__.py`
- `backend/app/api/health.py`
- `backend/app/core/__init__.py`
- `backend/app/core/config.py`
- `backend/app/db/__init__.py`
- `backend/app/providers/__init__.py`
- `backend/app/agents/__init__.py`
- `backend/app/skills/__init__.py`
- `backend/app/tools/__init__.py`
- `backend/app/services/__init__.py`
- `backend/tests/__init__.py`
- `backend/tests/test_health.py`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
- `frontend/vitest.config.ts`
- `frontend/src/index.css`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`
- `scripts/start.bat`
- `scripts/wait_for_servers.py`
- `docs/SPEC.md`
- `docs/DECISIONS.md`
- `docs/user-guide/README.md`
- `docs/reports/step-00.md`
- `docs/reports/step-01.md`
- `tests/test_no_local_paths.mjs`

*(Did not modify `.github/` or `CLAUDE.md`.)*

## 3. Tests run (exact commands + real output)

### A. `docs/SPEC.md` verbatim SHA-256 and UTF-8 (no BOM) verification (`3a859f7`)
```powershell
(Get-FileHash "docs\SPEC.md" -Algorithm SHA256).Hash.ToLower()
backend\.venv\Scripts\python.exe -c "import hashlib, subprocess; data = subprocess.check_output(['git', 'cat-file', 'blob', ':docs/SPEC.md']); print('git_blob_sha256:', hashlib.sha256(data).hexdigest())"
```
Output:
```text
bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f
git_blob_sha256: bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f
```

### B. Backend `pytest` (`3a859f7`)
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0 -- C:\Engineering Agent\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Engineering Agent\backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 1 item

tests/test_health.py::test_api_health_returns_ok PASSED                  [100%]

============================== 1 passed in 0.34s ==============================
```

### C. Frontend `vitest` and TypeScript/Vite build (`3a859f7`)
```powershell
cd frontend
npm.cmd test
npm.cmd run build
```
Output:
```text
 ✓ src/App.test.tsx (2 tests) 4ms
 Test Files  1 passed (1)
      Tests  2 passed (2)

vite v6.4.6 building for production...
✓ 27 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.33 kB
dist/assets/index-4CptX-19.css    1.11 kB │ gzip:  0.55 kB
dist/assets/index-DBswrZ6I.js   146.18 kB │ gzip: 47.35 kB
✓ built in 393ms
```

### D. End-to-end `scripts/start.bat` smoke test (`NO_BROWSER=1`)
```powershell
$env:NO_BROWSER = "1"; cmd.exe /c "scripts\start.bat"
# Verified http://127.0.0.1:8000/api/health, http://localhost:5173/, and proxied http://localhost:5173/api/health, then stopped spawned processes
```
Output:
```text
Starting Backend on http://127.0.0.1:8000 ...
Starting Frontend on http://localhost:5173 ...
Waiting for backend and frontend to listen...
Both backend and frontend are responding.
Launched backend (http://127.0.0.1:8000/api/health) and frontend (http://localhost:5173).
{
    "direct_status":  200,
    "direct_body":  "{\"status\":\"ok\",\"service\":\"ai-engineering-agent\",\"version\":\"0.1.0\",\"environment\":\"development\",\"classification\":\"Preliminary\"}",
    "ui_status":  200,
    "ui_has_dir_rtl":  true,
    "ui_has_title":  true,
    "proxied_status":  200,
    "proxied_body":  "{\"status\":\"ok\",\"service\":\"ai-engineering-agent\",\"version\":\"0.1.0\",\"environment\":\"development\",\"classification\":\"Preliminary\"}",
    "workspaces_exists":  true
}
```

### E. UTF-8 (no BOM), Rule 12a local-path / `/workspaces/`, and `gitleaks` checks (`3a859f7`, prior to committing this report)
```powershell
node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs
& "<scratch>\gitleaks\gitleaks.exe" git . --log-opts="--all" --no-banner -v
```
Output (colour codes stripped):
```text
✔ no committed text file leaks local user home paths (Rule 12a) (35.1743ms)
✔ no committed file is tracked inside /workspaces/ (Rule 12a) (24.4563ms)
✔ local user path detector catches other drive letters ([A-Za-z]:\Users\) (0.1821ms)
✔ /workspaces/ detector flags tracked workspace paths and allows normal paths (0.0794ms)
✔ all committed text files are valid UTF-8 without BOM (32.8127ms)
✔ Arabic sample file is tracked and decodes as valid UTF-8 with Arabic script (23.4587ms)
ℹ tests 6
ℹ suites 0
ℹ pass 6
ℹ fail 0

9:06PM INF 17 commits scanned.
9:06PM INF scanned ~253047 bytes (253.05 KB) in 184ms
9:06PM INF no leaks found
gitleaks exit code: 0
```
*(Fresh final-head `gitleaks`, UTF-8, `pytest`, and `vitest` outputs after committing `docs/reports/step-01.md` are included in the Step 01 PR description.)*

## 4. Acceptance tests
1. **`scripts/start.bat` opens the app at `http://localhost:5173` showing a placeholder page and `/api/health` returns OK:** **PASS** (smoke test verified `200` on `http://localhost:5173/`, `http://127.0.0.1:8000/api/health`, and proxied `http://localhost:5173/api/health`, with `dir="rtl"` Arabic + English UI).
2. **`pytest` runs and passes:** **PASS** (`1 passed in 0.34s`).
3. **Tool versions listed and manual installs documented:** **PASS** (Git, Node, npm, Python, pytest, and package versions listed in §1; Tesseract `ara+eng` and ODA File Converter marked `not installed - pending owner` with manual install instructions in §8).
4. **Master prompt copied verbatim into `docs/SPEC.md` (UTF-8 no BOM):** **PASS** (SHA-256 `bc7a0cb1a8cb5530e90117804aabf916108fd1ad5acbf073793875abc611fe1f`, UTF-8 without BOM verified).
5. **Step 00 follow-ups & Rule 12a safety checks (`step-00.md` fix, widened `[A-Za-z]:\Users\` + `/workspaces/` tests, `gitleaks`):** **PASS** (`6/6` Node tests passed; `gitleaks` exit `0`).

## 5. Decisions made (also in `docs/DECISIONS.md`)
- **ADR-005 update:** Recorded that PR #6 merged into `main` via regular merge commit `daa309a` (not squashed), so commit `09014b8`'s scratch-path strings remain in `main`'s history with explicit owner acceptance.
- **ADR-007:** Recorded Step 01 ports (`127.0.0.1:8000` backend, `localhost:5173` Vite frontend with `/api` proxy), `npm.cmd` usage for PowerShell compatibility, and `scripts/wait_for_servers.py` replacing `timeout.exe` for non-interactive readiness polling.

## 6. Deviations from the plan and why
- **Tesseract OCR and ODA File Converter left un-installed (`not installed - pending owner`):** Per owner instructions, Step 01 is not blocked on these two tools; Tesseract is first needed in Step 06 and ODA File Converter is first needed in Step 07 (manual download/license acceptance).
- **Added `scripts/wait_for_servers.py`:** Windows `timeout.exe` fails under redirected stdin (`ERROR: Input redirection is not supported`), so a small HTTP readiness poller was added alongside `scripts/start.bat`.
- **Used `httpx2` instead of `httpx` in `backend/requirements.txt`:** `starlette 1.10.0` (pulled by `fastapi 0.164.0`) deprecates `httpx` in `TestClient` and uses `httpx2`, keeping `pytest` warning-free.

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
- Test `scripts\start.bat` locally and confirm `http://localhost:5173` opens in your browser with the Arabic/English placeholder UI and `status: "ok"` health card.
- Review and merge this Step 01 PR yourself and reply `PASS step 01` before I begin Step 02.

## 9. How the owner can see/try it
1. Check out the PR branch or pull after merging, copy `.env.example` to `.env` if desired.
2. Run `scripts\start.bat` from the repository root (opens `http://localhost:5173`, backend at `http://127.0.0.1:8000/api/health`).
3. Run tests:
   - `cd backend && .\.venv\Scripts\python.exe -m pytest -v`
   - `cd frontend && npm.cmd test`
   - `node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs`

## 10. Ready for next step?
**Yes** — Ready for owner review, merge, and `PASS step 01` to proceed to Step 02.
