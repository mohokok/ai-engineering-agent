# Local AI Engineering Consultancy Agent

Classification: Preliminary

Local Windows 10/11 AI engineering consultancy platform supporting **Arabic (RTL)** and **English (LTR)**. Built step-by-step according to [ANTIGRAVITY_BUILD_PLAN.md](ANTIGRAVITY_BUILD_PLAN.md) and governed by [CLAUDE.md](CLAUDE.md) and [docs/DECISIONS.md](docs/DECISIONS.md).

## Repository Layout

```text
/backend/app/{api,core,db,providers,agents,skills,tools,services}
/backend/tests
/frontend/src
/docs/{SPEC.md,DECISIONS.md,reports/,user-guide/}
/scripts/start.bat
/tests/                   # Repository-wide UTF-8 & Rule 12a safety tests
/workspaces/              # Runtime project data (git-ignored, created on launch)
```

## Prerequisites (Windows 10/11)

- **Python 3.11+** (verified with Python 3.12.10)
- **Node.js 20+** and **npm** (verified with Node v24.18.0, npm 11.16.0)
- **Git for Windows** (verified with 2.55.0.windows.3)
- **Tesseract OCR** with `ara` + `eng` language packs (required for OCR in Step 06)
- **ODA File Converter** (required for DWG ↔ DXF conversion in Step 07; manual download & license acceptance from Open Design Alliance)

## Quick Setup (Local Dev)

1. **Copy environment template:**
   ```powershell
   Copy-Item .env.example .env
   ```
   *(Never commit `.env`, API keys, client files, drawings, or `/workspaces/`.)*

2. **Backend setup:**
   ```powershell
   cd backend
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m pytest
   ```

3. **Frontend setup:**
   ```powershell
   cd frontend
   npm.cmd install
   npm.cmd test
   npm.cmd run build
   ```

4. **Launch both servers & open UI:**
   Run `scripts\start.bat` from the repository root (opens `http://localhost:5173`, proxying `/api/*` to `http://127.0.0.1:8000/api/*`).

## Repository Safety & Encoding Tests

```powershell
node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs
```
