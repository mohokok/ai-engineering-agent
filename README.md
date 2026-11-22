# Local AI Engineering Consultancy Agent / الوكيل الهندسي الاستشاري المحلي

- **Status:** **Preliminary / Phase F Release Candidate (Steps 00–21 Built)**
- **Target Platform:** Windows 10 / Windows 11 (local workstation, `127.0.0.1` loopback binding only)
- **Languages:** Arabic (**RTL**) and English (**LTR**)
- **Governance:** Built incrementally per [ANTIGRAVITY_BUILD_PLAN.md](ANTIGRAVITY_BUILD_PLAN.md), [docs/SPEC.md](docs/SPEC.md), [docs/DECISIONS.md](docs/DECISIONS.md), and [CLAUDE.md](CLAUDE.md)

---

## Overview | نظرة عامة

A locally hosted, deterministic-first engineering consultancy assistant supporting Arabic RTL and English LTR workflows. Every safety-critical calculation, BOQ total, schedule CPM pass, technical weighted comparison, standards citation check, parametric CAD measurement, and QA verification executes deterministically in Python (`0` AI tokens by default). Optional Gemini AI assistance operates only on explicit request, uses an API key stored strictly in **Windows Credential Manager (`keyring`)**, and stays clearly tagged `UNVERIFIED AI DRAFT` / `UNVERIFIED AI SUGGESTION` until reviewed and approved by the owner or a licensed engineer.

وكيل هندسي استشاري محلي يدعم اللغتين العربية (`RTL`) والإنجليزية (`LTR`) على نظام Windows. تُنفَّذ كافة الحسابات الهندسية وجداول الكميات والمسار الحرج والمقارنات وفحص المعايير وضبط الجودة برمجياً بشكل حتمي (`0` توكن افتراضياً)، مع إبقاء الذكاء الاصطناعي الاختياري عبر Gemini مقيداً بمفتاح محفوظ حصراً في مدير بيانات اعتماد Windows (`keyring`) وبحالة مسودة غير معتمدة حتى مراجعة المهندس المرخص / المالك.

---

## 15 Implemented Application Modules (UI Tabs)

1. **Projects & Files (`المشاريع والملفات`):** Arabic/English project creation, automatic 12-folder engineering directory structure (`01_Input_Documents` .. `12_Revision_History`), SHA-256 checksums, immutable read-only originals, file versioning, traversal/extension/size validation.
2. **New Assignment & History (`المهام والتكليفات`):** Natural-language task intake, attached file tracking, Orchestrator v0 structured understanding, owner classification lock (`Preliminary`, `Conceptual`, `For Review`, `For Coordination`, `For Approval`).
3. **Research & Source Log (`البحث وسجل المصادر`):** Controlled research source log ranking official/standards sources, prompt-injection delimiter isolation, `owner_provided` uploads, full-document search, unverified-source gating.
4. **Standards Library (`مكتبة المعايير`):** Owner-supplied/licensed standards metadata & uploaded PDF/DOCX/TXT storage (max ~300-char owner excerpts only), edition/status tracking (`current`, `superseded`, `withdrawn`, `unknown`), supersession cycle detection, where-cited impact tracking, EN/AR DOCX/PDF/XLSX register export.
5. **HVAC / Fire / Healthcare Preflight (`تكييف / حريق / صحة`):** Deterministic input preparation & software output checking ONLY; mandatory handoff warnings (`Carrier HAP`, `Trane TRACE`, `Elite Fire`, `SprinkCALC`, `CONTAM`); WHO/FGI/NFPA/ASHRAE cited strictly from verified library/source log else `'no verified standard on file - verify against the locally adopted code'`; missing inputs block via `'not provided'`.
6. **Structural Assessment Support (`الإنشائي`):** Tributary column takedown, owner-factored load combinations, closed-form simple span beam statics, capacity ratio & FEA discrepancy checks ONLY (**never designs members or certifies safety**; recommends `ETABS` / `SAP2000` / `SAFE` / verified licensed engineer).
7. **Deliverables & Reports (`التقارير والمخرجات`):** Bilingual Arabic RTL / English LTR review reports (`DOCX` & vector `PDF`) distinguishing verified facts, calculated outputs, unverified OCR excerpts, assumptions, and versioned SHA-256 download register.
8. **BOQ & Quantities (`جداول الكميات`):** Deterministic DXF/IFC/XLSX/PDF quantity extraction with explicit confirmed units, unsourced-rate blocking, configurable currency, audit checks, and live Excel formula `XLSX` + `CSV` exports.
9. **Parametric CAD (`الرسم الهندسي`):** Millimetre-coordinate parametric floor plans compiled to native DXF (layers, blocks, dimensions, room polygons) + scaled true-size PDF + Door/Window/Finish schedules + round-trip DXF re-extraction verification (`oda-optional`).
10. **Calculations (MEP) (`الحسابات الهندسية`):** Deterministic electrical load schedule, cable sizing, voltage drop, plumbing water demand, and pipe sizing with equations, assumptions, provenance tags, and DOCX/PDF/live XLSX exports.
11. **Technical Specifications (`المواصفات الفنية`):** Traceable engineering specification packages linked back to real BOQ items, drawing schedules, and verified research sources, with EN/AR DOCX/PDF exports.
12. **Technical Compare (`المقارنات الفنية`):** `Decimal`-exact weighted multi-criteria comparisons (`cost`, `lifecycle`, `safety`, `performance`, etc.), mandatory gate evaluation, unit checks, owner decision recording, advisory notice, and DOCX/PDF/XLSX exports.
13. **Planning & Gantt (`الجدولة والمسار الحرج`):** WBS & Critical Path Method (forward/backward pass, float, FS + lag, cycle detection, Libya Fri–Sat weekend + owner holiday calendar), `'not provided'` missing-duration blocking, baseline comparison, Gantt UI & PDF/XLSX export.
14. **QA & Issue Register (`الجودة وسجل القضايا`):** Independent QA Agent running in an isolated context (producer reasoning excluded), cross-checking arithmetic, units, references, missing deliverables, SHA-256 integrity, seeded defect checks across all modules, and verification gating.
15. **Settings & System (`إعدادات Gemini والمزودين والنظام`):** Swappable provider architecture (`GeminiProvider` via official `google-genai`), OS keyring secret management, token/request daily+monthly usage limits, local `127.0.0.1` binding status, local `workspaces/agent.log` path display (log-viewer-free / no remote shipping), and one-click + CLI SHA-256 workspace & SQLite ZIP backup/restore with `--dry-run`.

---

## Clean Windows 10/11 Install & Run Instructions

### Prerequisites (Verified Versions)
1. **Python 3.11+** (verified: `Python 3.12.10` with `py` launcher / `venv`)
2. **Node.js 20+ & npm** (verified: `Node v24.18.0`, `npm 11.16.0`)
3. **Git for Windows** (verified: `2.55.0.windows.3`)
4. **Optional — Tesseract OCR** (`ara` + `eng` language data): required only for OCR fallback on scanned PDFs/images (`TESSERACT_CMD` in `.env` or installed under default Program Files / PATH).
5. **Optional — Open Design Alliance (ODA) File Converter**: required only for `.dwg` <-> `.dxf` conversion (`ODA_FILE_CONVERTER_PATH` in `.env` or installed cleanly after accepting ODA license).

### Fresh Install from Scratch (Clean Windows Account)
```powershell
# 1. Clone repository into a clean local folder (avoid OneDrive-synced paths if locking occurs)
git clone https://github.com/mohokok/ai-engineering-agent.git
cd ai-engineering-agent

# 2. Copy local environment template (NEVER commit .env)
Copy-Item .env.example .env

# 3. Create Python virtual environment & install pinned backend dependencies
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..

# 4. Install frontend dependencies
cd frontend
npm.cmd install
cd ..

# 5. Start backend (127.0.0.1:8000) and frontend (127.0.0.1:5173)
.\scripts\start.bat
```

Wait until both servers respond (`http://127.0.0.1:8000/api/health` -> `200`, UI at `http://127.0.0.1:5173`). Database migrations (`0001`–`0017`) run automatically on startup, creating `<repo>\workspaces\engineering_agent.db` and `<repo>\workspaces\agent.log`.

---

## Running Automated Verification Suites

```powershell
# Full backend suite (111+ tests across Alembic migrations, deterministic skills, exports, QA, hardening & E2E)
.\backend\.venv\Scripts\pytest.exe backend/tests -v

# Step 21 15-tab synthetic E2E smoke test alone
.\backend\.venv\Scripts\pytest.exe backend/tests/test_e2e_smoke.py -v

# Frontend tests (Vitest) + TypeScript check + production Vite build
cd frontend
npm.cmd test
npm.cmd run build
cd ..

# Repository UTF-8 (no BOM) & Rule 12a no-personal-path / no-tracked-workspaces checks
node --test tests/test_utf8_encoding.mjs tests/test_no_local_paths.mjs

# CLI Backup & Dry-Run Restore verification
cd backend
.\.venv\Scripts\python.exe -m app.cli_backup backup --label manual_check
.\.venv\Scripts\python.exe -m app.cli_backup restore --archive ..\workspaces\_backups\<backup_filename>.zip --dry-run
cd ..
```

---

## Documentation Index

- **Bilingual User Guide Hub:** [docs/user-guide/README.md](docs/user-guide/README.md)
  - **English User Guide:** [docs/user-guide/user-guide-en.md](docs/user-guide/user-guide-en.md)
  - **دليل المستخدم العربي (Arabic Guide):** [docs/user-guide/user-guide-ar.md](docs/user-guide/user-guide-ar.md)
- **Specification & Build Plan:** [docs/SPEC.md](docs/SPEC.md) | [ANTIGRAVITY_BUILD_PLAN.md](ANTIGRAVITY_BUILD_PLAN.md)
- **Architecture Decision Log (ADRs 001–030):** [docs/DECISIONS.md](docs/DECISIONS.md)
- **Step Reports (`step-00` through `step-21`):** [docs/reports/step-21.md](docs/reports/step-21.md)

---

## Key Safety Rules & Known Limitations

- **Preliminary Only:** Every calculation, drawing, specification, BOQ, comparison, schedule, HVAC/fire/healthcare check, structural check, and report requires review and sign-off by a licensed engineer before construction or regulatory submission.
- **No Fabricated Codes/Rates:** Standards, clause numbers, editions, load factors, unit rates, and durations are never fabricated; unlinked standards explicitly display `'no verified standard on file - verify against the locally adopted code'` and missing engineering inputs display `'not provided'` while blocking pass verdicts.
- **Local-Only Security:** Backend binds strictly to `127.0.0.1`; API keys reside solely in Windows Credential Manager (`keyring`); rotating local logs redact secrets and client content with zero remote shipping; SHA-256 backups exclude API keys/keyring.
- **Known Limitations:** Live visual inspection of rendered CAD DXFs / Word / PDF / Excel sheets and clean-PC installation remain manual owner verification steps; `.dwg` conversion requires separately installed ODA File Converter; OCR on scanned pages requires separately installed Tesseract (`ara+eng`); multi-user auth/HTTPS reverse-proxy is intentionally omitted for single-workstation local deployment.
