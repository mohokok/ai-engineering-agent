# User Guide (English — LTR)

- **Version:** Release Candidate (`Steps 00–21`)
- **Classification:** `Preliminary` *(Every engineering output requires review and sign-off by a licensed engineer.)*

---

## 1. Windows 10/11 Installation (Clean Account Guide)

### Required Tools
1. **Python 3.12** (64-bit, check *"Add python.exe to PATH"* during installation; `Python 3.11+` supported).
2. **Node.js 20 LTS or newer** (includes `npm`).
3. **Git for Windows**.

### Optional External Engineering Tools
- **Tesseract OCR** (`ara` + `eng` language packs): Needed only when extracting scanned PDFs or images. Set `TESSERACT_CMD=` in `.env` if installed in a custom path.
- **ODA File Converter**: Needed only to convert binary `.dwg` files to `.dxf` / back to `.dwg`. Obtain directly from Open Design Alliance under your own license and optionally set `ODA_FILE_CONVERTER_PATH=` in `.env`.

### First-Time Setup Commands (PowerShell)
```powershell
git clone https://github.com/mohokok/ai-engineering-agent.git
cd ai-engineering-agent
Copy-Item .env.example .env

cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..

cd frontend
npm.cmd install
cd ..

.\scripts\start.bat
```

Open `http://127.0.0.1:5173`. Database schema migrations (`0001`–`0017`) run automatically on startup and initialize `workspaces\engineering_agent.db` plus rotating log file `workspaces\agent.log`.

---

## 2. Security Model & AI Key Setup

1. **Local-Only Binding:** The backend binds strictly to `127.0.0.1:8000` (non-loopback bindings such as `0.0.0.0` are rejected) with strict local CORS restricted to `http://127.0.0.1:5173` and `http://localhost:5173`.
2. **Gemini API Key (Optional):** Deterministic engineering tools require **zero AI tokens**. To enable natural-language Orchestrator intake or optional AI draft prose:
   - Open **Settings & System**.
   - Paste an **authorized Google AI Studio API key** (consumer Gemini web/Google One subscriptions do not include API access).
   - Click **Save Key in Windows Credential Manager**. Keys are never stored in `.env`, SQLite, logs, exports, or backups.
   - Click **Refresh Models** and **Test Connection**; configure daily/monthly token & request budgets cleanly.
3. **Zero Silent Data Egress:** External web requests occur only when clicking **Run Research** in the Research tab, and Gemini API calls occur only on explicit task/AI-button actions.
4. **Local Logs (Viewer-Free):** Operational JSONL logs with secret and client-text redaction rotate (`5 MB x 5`) at `<repo>\workspaces\agent.log`. Check this file directly on disk alongside `X-Correlation-ID` (`[ref: ...]`) shown in error messages.

---

## 3. Working Across All 15 Tabs

1. **Projects & Files:** Create Arabic or English projects (auto-creates `01_Input_Documents` .. `12_Revision_History`). Uploaded originals are SHA-256 hashed and locked read-only; re-uploads create numbered versions cleanly. Run deterministic extraction and explicitly confirm CAD drawing units (`m`, `mm`, `cm`) when prompted.
2. **New Assignment & History:** Submit natural-language instructions (Arabic, English, or mixed), attach uploaded files, set classification (`Preliminary`..`For Approval`), and inspect Orchestrator v0 structured understanding + token logs.
3. **Research & Source Log:** Run controlled searches prioritizing official regulations and standards bodies, or attach uploaded owner PDFs as `owner_provided` evidence. Unfetched snippets are never treated as technical evidence.
4. **Standards Library:** Register owner-supplied or licensed standards (upload PDF/DOCX/TXT for bounded header metadata suggestion -> **Confirm Metadata**). Maintain status (`current`, `superseded`, `withdrawn`, `unknown`), link replacements, add short owner excerpts (max 300 chars), inspect where each standard is cited, and export EN/AR DOCX/PDF/XLSX registers.
5. **HVAC / Fire / Healthcare Preflight:** Deterministic input preparation and commercial software output verification ONLY (`0` AI tokens default). Presets contain synthetic baseline inputs labelled `PRELIMINARY`. Always select a confirmed `"current"` Standard or reviewed Research Source if citing codes—otherwise outputs explicitly show `'no verified standard on file - verify against the locally adopted code'`. Missing inputs display `'not provided'` and block pass status.
6. **Structural Assessment Support:** Deterministic load takedowns, owner load combinations, and simple span beam statics (`simply_supported_udl`, `simply_supported_midspan_point`, `cantilever_udl`) input/output checking ONLY. **Never designs structural members or certifies safety.** Every output directs final code design to validated commercial software (`ETABS`, `SAP2000`, `SAFE`, `RAM Structural System`, `Robot Structural Analysis`) and a licensed structural engineer.
7. **Deliverables & Reports:** Generate bilingual RTL/LTR document/drawing review reports (`DOCX`/`PDF`) separating verified facts, calculations, unverified OCR text, and assumptions; browse and download all immutable SHA-256 deliverables.
8. **BOQ & Quantities:** Generate BOQ sheets, import confirmed DXF/IFC/XLSX/PDF quantities, enter unit rates strictly with provenance (`owner_input` or `dated_research`), run deterministic duplicate/unit/arithmetic audits, and export CSV + live-formula XLSX (`=ROUND(...)`, `=SUM(...)`).
9. **Parametric CAD:** Edit or load the synthetic 5-room clinic model (in millimetres), confirm model geometry, and compile native DXF layers/blocks/polygons + scaled PDF + Door/Window/Finish schedules with automatic round-trip DXF re-read verification.
10. **Calculations (MEP):** Run electrical load schedule, cable sizing, voltage drop, plumbing water demand, and pipe sizing calculations with full equation traces and DOCX/PDF/live XLSX exports.
11. **Technical Specs:** Generate traceable specification packages (`07_Technical_Specifications`) mapped directly to real project BOQ items, CAD drawing schedules, and verified sources. Approve optional AI draft wording explicitly when `use_ai=true`.
12. **Technical Compare:** Build weighted multi-criteria matrices using exact `Decimal` scoring, mandatory gates, and explicit unit conversions (`advisory only` banner). Record formal owner selection + decision notes and export DOCX/PDF/XLSX.
13. **Planning & Gantt:** Build owner-grounded WBS activities with `FS` + lag dependencies, pick a calendar (including Libya Fri–Sat weekend + owner holidays), inspect CPM forward/backward pass, float, critical path, baseline variance, and export Gantt PDF + live XLSX.
14. **QA & Issue Register:** Run the independent QA Agent (isolated from AI producer reasoning) to re-verify arithmetic, units, references, stale standards, `'not provided'` blocks, unapproved AI drafts, and deliverable SHA-256 hashes. Close issues with corrective notes (`>= 10` chars) and re-run QA before clicking **Verify Task**.
15. **Settings & System Backup/Restore:** View local bind/CORS status and `agent.log` location, create one-click ZIP backups (DB snapshot + workspace files + SHA-256 `manifest.json`, excluding Windows Credential Manager keys), run **Verify (Dry-Run)**, or restore cleanly. Also available offline via CLI:
    ```powershell
    cd backend
    .\.venv\Scripts\python.exe -m app.cli_backup backup --label pre_delivery
    .\.venv\Scripts\python.exe -m app.cli_backup restore --archive ..\workspaces\_backups\backup_...zip --dry-run
    ```

---

## 4. Known Limitations & Troubleshooting

- **Missing external binaries:** If Tesseract or ODA File Converter is not installed, deterministic CAD/PDF/DOCX/XLSX workflows continue operating normally, while OCR fallback and `.dwg` conversion return explicit installation guidance (`HTTP 400`).
- **Gemini HTTP 401 / 429 / 503:** Deterministic calculations, BOQ, specs, planning, standards, structural/specialist checks, exports, and QA work completely offline at `0` AI tokens if Gemini is unavailable or usage limits are reached.
- **Encrypted DB / Multi-user:** Intended for single-consultant Windows workstation use; protect Windows user login + NTFS permissions on `<repo>\workspaces\`.
