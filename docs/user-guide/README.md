# Bilingual User Guide | دليل المستخدم (English & العربية)

- **Classification:** `Preliminary`
- **Applies to:** Local AI Engineering Consultancy Agent (Steps 00–21)

Choose your preferred language / اختر لغة الدليل المناسبة:

- **English User Guide:** [user-guide-en.md](user-guide-en.md) — Step-by-step Windows setup, credential storage, all 15 workspace tabs, deterministic calculations, standards verification, QA review, and SHA-256 backup/restore.
- **دليل المستخدم باللغة العربية (`RTL`):** [user-guide-ar.md](user-guide-ar.md) — دليل التشغيل الكامل باللغة العربية من التثبيت على نظام Windows، حفظ مفتاح Gemini في Windows Credential Manager، استخدام جميع التبويبات الـ 15، الضبط الحتمي للمعايير، مراجعة الجودة المستقلة، والنسخ الاحتياطي والاستعادة.

---

## Quick 5-Minute Start | التشغيل السريع خلال 5 دقائق

1. **Launch / التشغيل:** Double-click `scripts\start.bat` (or run `.\scripts\start.bat` in PowerShell) from the repository folder and wait for `Both backend and frontend are responding.`
2. **Open UI / فتح الواجهة:** Open `http://127.0.0.1:5173` in Microsoft Edge or Chrome (switch RTL/LTR using the header toggle button).
3. **Optional AI Key / مفتاح Gemini (اختياري):** Open **Settings & System (`إعدادات Gemini والمزودين والنظام`)**, paste your authorized Google AI Studio Gemini API key, and click **Save to Windows Credential Manager** (deterministic modules work at `0` AI tokens even without an API key).
4. **Create Project & Upload Files / إنشاء مشروع ورفع الملفات:** Go to **Projects & Files (`المشاريع والملفات`)** -> create project -> upload PDFs/DOCX/XLSX/DXF -> open **Review / Extraction** to extract and confirm CAD drawing units (`m`, `mm`, `cm`).
5. **Run Engineering Modules -> QA -> Backup / تشغيل الوحدات -> الجودة -> النسخ الاحتياطي:** Run BOQ, Drawings, MEP Calculations, Specs, Comparisons, Planning, Standards, HVAC/Fire/Healthcare, Structural Support -> run **QA Review (`الجودة وسجل القضايا`)** -> verify green deliverables -> create a verified ZIP + SHA-256 backup under **Settings & System**.
