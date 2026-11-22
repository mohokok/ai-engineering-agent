import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  confirmStandardMetadata,
  createStandard,
  exportStandardsRegister,
  getStandardDetail,
  getStandardsRegisterDownloadUrl,
  listProjects,
  listStandardPresets,
  listStandards,
  supersedeStandard,
  updateStandard,
  uploadStandardDocument,
} from "../api";
import type {
  Lang,
  OwnerExcerptIn,
  ProjectClassification,
  ProjectSummary,
  ReportLanguage,
  StandardDocumentOut,
  StandardPresetOut,
  StandardRegisterExportOut,
  StandardStatus,
  TaskComplexity,
} from "../types";

const MAX_EXCERPT_CHARS = 300;
const STATUS_OPTIONS: StandardStatus[] = ["current", "superseded", "withdrawn", "unknown"];
const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const COPY: Record<
  Lang,
  {
    heading: string;
    subtitle: string;
    policyBanner: string;
    projectLabel: string;
    globalScopeOption: string;
    includeGlobalCheck: string;
    searchLabel: string;
    searchPlaceholder: string;
    filterStatusLabel: string;
    allStatuses: string;
    adoptedOnlyCheck: string;
    searchBtn: string;
    presetHeading: string;
    loadPresetBtn: string;
    uploadHeading: string;
    fileLabel: string;
    uploadJurisdictionLabel: string;
    uploadAdoptedCheck: string;
    useAiCheck: string;
    aiComplexityLabel: string;
    uploadBtn: string;
    uploadingBtn: string;
    manualHeading: string;
    numberLabel: string;
    titleLabel: string;
    issuerLabel: string;
    editionLabel: string;
    statusLabel: string;
    jurisdictionLabel: string;
    adoptedCheck: string;
    notesLabel: string;
    excerptPageLabel: string;
    excerptTextLabel: string;
    addExcerptBtn: string;
    createBtn: string;
    creatingBtn: string;
    registerHeading: string;
    emptyList: string;
    detailHeading: string;
    selectPrompt: string;
    confirmBanner: string;
    confirmedByLabel: string;
    confirmBtn: string;
    supersedeHeading: string;
    replacementSelectLabel: string;
    noReplacementSelected: string;
    supersessionNoteLabel: string;
    supersedeBtn: string;
    updateExcerptsHeading: string;
    changeNoteLabel: string;
    saveUpdateBtn: string;
    whereCitedHeading: string;
    noCitations: string;
    historyHeading: string;
    exportHeading: string;
    exportLangLabel: string;
    exportClassLabel: string;
    exportBtn: string;
    exportingBtn: string;
    shaLabel: string;
    versionLabel: string;
    tokensLabel: string;
  }
> = {
  ar: {
    heading: "الخطوة 17: مكتبة المعايير والمواصفات القياسية (الوثائق المزوّدة من المالك فقط)",
    subtitle:
      "فهرسة المعايير المرفوعة (PDF/DOCX/TXT) أو المدخلة يدوياً مع تتبع النسخ والاستبدال (Supersession) وسجل المواضع المُستشهَد بها وتنبيهات الجودة.",
    policyBanner:
      "سياسة عدم الاختلاق وحقوق النشر: لا يقوم النظام أبداً بتضمين نصوص معايير محمية أو اختلاق بنود أو طبعات من الذاكرة. تُخزَّن مقتطفات المالك فقط (بحد أقصى 300 حرف لكل مقتطف مع رقم الصفحة) وبصمة الملف SHA-256، وتبقى البيانات المستخرجة أو المقترحة بالذكاء الاصطناعي بوسم غير مؤكد حتى يؤكدها المالك.",
    projectLabel: "المشروع",
    globalScopeOption: "-- سجل عام مشترك للمكتب (بدون ربط بمشروع محدد) --",
    includeGlobalCheck: "تضمين المعايير العامة المشتركة",
    searchLabel: "بحث في بيانات المالك فقط (الرقم / العنوان / الجهة / الكلمات المفتاحية)",
    searchPlaceholder: "مثال: SYN-1000 أو Distribution...",
    filterStatusLabel: "تصفية الحالة",
    allStatuses: "كل الحالات",
    adoptedOnlyCheck: "المعتمدة محلياً فقط (Adopted Locally)",
    searchBtn: "بحث وتحديث",
    presetHeading: "نماذج تمثيلية قياسية (أكواد SYN-* غير حقيقية للاختبار فقط)",
    loadPresetBtn: "تعبئة النموذج التمثيلي",
    uploadHeading: "رفع مستند معياري مملوك أو مرخص (PDF / DOCX / TXT)",
    fileLabel: "ملف المعيار",
    uploadJurisdictionLabel: "النطاق/الاختصاص (Jurisdiction)",
    uploadAdoptedCheck: "معتمد محلياً (Adopted Locally)",
    useAiCheck: "اقتراح بيانات الغلاف بالذكاء الاصطناعي (اختياري — الافتراضي 0 توكن وبوسم غير مؤكد)",
    aiComplexityLabel: "مستوى التحليل",
    uploadBtn: "رفع وفحص الترويسة",
    uploadingBtn: "جاري الرفع...",
    manualHeading: "إدخال بيانات معيار مزوَّد من المالك يدوياً (0 توكن)",
    numberLabel: "رقم المعيار (Standard Number)",
    titleLabel: "عنوان المعيار (Title)",
    issuerLabel: "الجهة المصدرة (Issuing Body)",
    editionLabel: "الطبعة / السنة (Edition / Year)",
    statusLabel: "حالة السريان",
    jurisdictionLabel: "الاختصاص الجغرافي / النظامي",
    adoptedCheck: "معتمد محلياً (Adopted Locally)",
    notesLabel: "ملاحظات المالك",
    excerptPageLabel: "مرجع الصفحة",
    excerptTextLabel: "مقتطف مالك مسموح به (<= 300 حرف)",
    addExcerptBtn: "+ إضافة مقتطف (<=300 حرف)",
    createBtn: "حفظ في مكتبة المعايير",
    creatingBtn: "جاري الحفظ...",
    registerHeading: "سجل المعايير المسجلة",
    emptyList: "لا توجد معايير مطابقة في المكتبة حتى الآن.",
    detailHeading: "تفاصيل المعيار، سلسلة الاستبدال، ومواضع الاستشهاد",
    selectPrompt: "اختر معياراً من السجل لعرض التفاصيل والمقتطفات وسلسلة الاستبدال.",
    confirmBanner:
      "بيانات هذا المعيار المستخرجة/المقترحة لم يؤكدها المالك بعد — لن يُعتمد في الجودة حتى التأكيد الصريح.",
    confirmedByLabel: "تأكيد بواسطة",
    confirmBtn: "تأكيد البيانات الوصفية (Confirm Metadata)",
    supersedeHeading: "تسجيل الاستبدال (Register Supersession)",
    replacementSelectLabel: "المعيار البديل المسجل",
    noReplacementSelected: "-- اختر المعيار البديل --",
    supersessionNoteLabel: "ملاحظة الاستبدال",
    supersedeBtn: "ربط كمعيار مُستبدَل (Superseded)",
    updateExcerptsHeading: "تحديث الحالة أو إضافة مقتطف قصير (<= 300 حرف)",
    changeNoteLabel: "سبب التحديث",
    saveUpdateBtn: "حفظ التحديث (إصدار جديد)",
    whereCitedHeading: "أين تم الاستشهاد بهذا المعيار عبر المخرجات؟ (Where Cited)",
    noCitations: "لم يُرصد استشهاد بهذا المعيار في المواصفات أو الحسابات أو المقارنات أو التقارير أو الجداول حتى الآن.",
    historyHeading: "سجل الإصدارات (Version History)",
    exportHeading: "تصدير سجل المعايير الشامل (DOCX / PDF / XLSX بصيغ حية)",
    exportLangLabel: "لغة السجل",
    exportClassLabel: "التصنيف الهندسي",
    exportBtn: "تصدير سجل المعايير (DOCX + PDF + XLSX)",
    exportingBtn: "جاري التصدير...",
    shaLabel: "SHA-256",
    versionLabel: "الإصدار",
    tokensLabel: "التوكنات المستخدمة",
  },
  en: {
    heading: "Step 17: Standards Library (Owner-Supplied / Licensed Documents Only)",
    subtitle:
      "Index uploaded PDF/DOCX/TXT or owner-entered standards, manage edition supersessions, inspect where-cited deliverables, and trigger QA flags.",
    policyBanner:
      "Anti-Fabrication & Copyright Policy: Never ships or invents standard text, clauses, or editions from model memory. Stores ONLY short owner-selected excerpts (max 300 chars + page ref) and file SHA-256. Extracted or AI-suggested metadata remains UNVERIFIED until the owner explicitly confirms it.",
    projectLabel: "Project",
    globalScopeOption: "-- Global Library Scope (No Single Project) --",
    includeGlobalCheck: "Include global standards",
    searchLabel: "Search owner-supplied data only (number / title / body / keyword)",
    searchPlaceholder: "e.g. SYN-1000 or Distribution...",
    filterStatusLabel: "Status Filter",
    allStatuses: "All Statuses",
    adoptedOnlyCheck: "Adopted locally only",
    searchBtn: "Search / Refresh",
    presetHeading: "Synthetic Fixture Presets (Fake SYN-* Codes Only)",
    loadPresetBtn: "Fill Synthetic Preset",
    uploadHeading: "Upload Owner-Supplied / Licensed Standard (PDF / DOCX / TXT)",
    fileLabel: "Standard File",
    uploadJurisdictionLabel: "Jurisdiction",
    uploadAdoptedCheck: "Adopted Locally",
    useAiCheck: "Optional AI header suggestion (default OFF / 0 tokens; tagged UNVERIFIED AI SUGGESTION)",
    aiComplexityLabel: "AI Complexity",
    uploadBtn: "Upload & Suggest Metadata",
    uploadingBtn: "Uploading...",
    manualHeading: "Register Owner-Entered Standard Metadata (0 AI Tokens)",
    numberLabel: "Standard Number",
    titleLabel: "Standard Title",
    issuerLabel: "Issuing Body",
    editionLabel: "Edition / Year",
    statusLabel: "Lifecycle Status",
    jurisdictionLabel: "Jurisdiction",
    adoptedCheck: "Adopted Locally",
    notesLabel: "Owner Notes",
    excerptPageLabel: "Page Ref",
    excerptTextLabel: "Permitted Owner Excerpt (<= 300 chars)",
    addExcerptBtn: "+ Add Excerpt (<=300 chars)",
    createBtn: "Save Standard Entry",
    creatingBtn: "Saving...",
    registerHeading: "Registered Standards Index",
    emptyList: "No matching standards recorded in the library yet.",
    detailHeading: "Standard Inspector, Supersession Chain & Where Cited",
    selectPrompt: "Select a standard from the index to inspect metadata, short excerpts, citations, and history.",
    confirmBanner:
      "Uploaded/AI-suggested metadata is UNVERIFIED until confirmed by the owner (QA flags unconfirmed standards).",
    confirmedByLabel: "Confirmed By",
    confirmBtn: "Confirm Metadata",
    supersedeHeading: "Register Supersession",
    replacementSelectLabel: "Replacement Standard",
    noReplacementSelected: "-- Select Replacement Standard --",
    supersessionNoteLabel: "Supersession Note",
    supersedeBtn: "Mark Superseded",
    updateExcerptsHeading: "Update Status or Append Short Excerpt (<= 300 chars)",
    changeNoteLabel: "Change Note",
    saveUpdateBtn: "Save Update (New Version)",
    whereCitedHeading: "Where Cited Across Deliverables",
    noCitations: "No citations detected in specifications, calculations, comparisons, reports, or schedules.",
    historyHeading: "Version History",
    exportHeading: "Export Bilingual Standards Register (DOCX / PDF / Live-Formula XLSX)",
    exportLangLabel: "Register Language",
    exportClassLabel: "Classification",
    exportBtn: "Export Register (DOCX + PDF + XLSX)",
    exportingBtn: "Exporting...",
    shaLabel: "SHA-256",
    versionLabel: "Version",
    tokensLabel: "Tokens Used",
  },
};

function statusBadgeStyle(status: string): { backgroundColor: string; color: string; border: string } {
  if (status === "current") {
    return { backgroundColor: "#e6f4ea", color: "#137333", border: "1px solid #a8dab5" };
  }
  if (status === "superseded") {
    return { backgroundColor: "#fef7e0", color: "#9a6700", border: "1px solid #f6d57f" };
  }
  if (status === "withdrawn") {
    return { backgroundColor: "#fce8e6", color: "#c5221f", border: "1px solid #f4a9a2" };
  }
  return { backgroundColor: "#f1f3f4", color: "#444746", border: "1px solid #dadce0" };
}

export function StandardsLibraryView({
  lang,
  initialStandards = [],
  initialSelectedStd = null,
}: {
  lang: Lang;
  initialStandards?: StandardDocumentOut[];
  initialSelectedStd?: StandardDocumentOut | null;
}) {
  const t = COPY[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [includeGlobal, setIncludeGlobal] = useState<boolean>(true);

  const [presets, setPresets] = useState<StandardPresetOut[]>([]);
  const [selectedPresetKey, setSelectedPresetKey] = useState<string>("");

  const [searchQuery, setSearchQuery] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [adoptedOnly, setAdoptedOnly] = useState<boolean>(false);

  const [standards, setStandards] = useState<StandardDocumentOut[]>(initialStandards);
  const [selectedStd, setSelectedStd] = useState<StandardDocumentOut | null>(initialSelectedStd);

  // Upload state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadJurisdiction, setUploadJurisdiction] = useState<string>("");
  const [uploadAdopted, setUploadAdopted] = useState<boolean>(false);
  const [uploadUseAi, setUploadUseAi] = useState<boolean>(false);
  const [uploadComplexity, setUploadComplexity] = useState<TaskComplexity>("fast");
  const [uploading, setUploading] = useState<boolean>(false);

  // Manual create state
  const [standardNumber, setStandardNumber] = useState<string>("");
  const [title, setTitle] = useState<string>("");
  const [issuingBody, setIssuingBody] = useState<string>("");
  const [editionYear, setEditionYear] = useState<string>("unknown");
  const [statusVal, setStatusVal] = useState<StandardStatus>("current");
  const [jurisdiction, setJurisdiction] = useState<string>("");
  const [adoptedLocally, setAdoptedLocally] = useState<boolean>(false);
  const [ownerNotes, setOwnerNotes] = useState<string>("");
  const [draftExcerpts, setDraftExcerpts] = useState<OwnerExcerptIn[]>([]);
  const [excerptPageRef, setExcerptPageRef] = useState<string>("p. 1");
  const [excerptText, setExcerptText] = useState<string>("");
  const [creating, setCreating] = useState<boolean>(false);

  // Detail actions state
  const [confirmedBy, setConfirmedBy] = useState<string>("Lead Engineer");
  const [replacementId, setReplacementId] = useState<string>("");
  const [supersessionNote, setSupersessionNote] = useState<string>("");
  const [editStatus, setEditStatus] = useState<StandardStatus>("current");
  const [newExcerptPage, setNewExcerptPage] = useState<string>("p. 1");
  const [newExcerptText, setNewExcerptText] = useState<string>("");
  const [changeNote, setChangeNote] = useState<string>("Owner review update");

  // Export state
  const [exportLang, setExportLang] = useState<ReportLanguage>(lang === "ar" ? "ar" : "en");
  const [exportClass, setExportClass] = useState<ProjectClassification>("Preliminary");
  const [exporting, setExporting] = useState<boolean>(false);
  const [exportResult, setExportResult] = useState<StandardRegisterExportOut | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [infoMsg, setInfoMsg] = useState<string | null>(null);

  const refreshLibrary = useCallback(
    async (keepSelectedId?: string) => {
      try {
        const res = await listStandards({
          project_id: selectedProjectId || undefined,
          include_global: includeGlobal,
          q: searchQuery.trim() || undefined,
          status: filterStatus || undefined,
          adopted_locally: adoptedOnly ? true : undefined,
        });
        setStandards(res.standards);
        const targetId = keepSelectedId ?? selectedStd?.id;
        if (targetId) {
          const found = res.standards.find((item) => item.id === targetId);
          if (found) {
            setSelectedStd(found);
            setEditStatus((found.status as StandardStatus) || "unknown");
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [adoptedOnly, filterStatus, includeGlobal, searchQuery, selectedProjectId, selectedStd?.id]
  );

  useEffect(() => {
    void (async () => {
      try {
        const [projRes, presetRes] = await Promise.all([listProjects(), listStandardPresets()]);
        setProjects(projRes.projects);
        setPresets(presetRes.presets);
        if (presetRes.presets.length > 0) {
          setSelectedPresetKey(presetRes.presets[0].key);
        }
        if (projRes.projects.length > 0) {
          setSelectedProjectId((prev) => prev || projRes.projects[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  useEffect(() => {
    void refreshLibrary();
  }, [refreshLibrary]);

  const handleLoadPreset = () => {
    const preset = presets.find((p) => p.key === selectedPresetKey);
    if (!preset) return;
    const s = preset.standard;
    setStandardNumber(s.standard_number);
    setTitle(s.title);
    setIssuingBody(s.issuing_body || "");
    setEditionYear(s.edition_year || "unknown");
    setStatusVal(s.status || "current");
    setJurisdiction(s.jurisdiction || "");
    setAdoptedLocally(Boolean(s.adopted_locally));
    setOwnerNotes(s.owner_notes || "");
    setDraftExcerpts(s.owner_excerpts || []);
    setInfoMsg(lang === "ar" ? preset.label_ar : preset.label_en);
    setError(null);
  };

  const handleAddDraftExcerpt = () => {
    const cleaned = excerptText.trim();
    if (!cleaned || !excerptPageRef.trim()) {
      setError("Excerpt text and page reference are required.");
      return;
    }
    if (cleaned.length > MAX_EXCERPT_CHARS) {
      setError(`Excerpt exceeds ${MAX_EXCERPT_CHARS} characters (${cleaned.length}).`);
      return;
    }
    setDraftExcerpts((prev) => [...prev, { page_ref: excerptPageRef.trim(), text: cleaned }]);
    setExcerptText("");
    setError(null);
  };

  const handleUploadSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      setError("Choose a PDF, DOCX, or TXT standard file first.");
      return;
    }
    setUploading(true);
    setError(null);
    setInfoMsg(null);
    try {
      const created = await uploadStandardDocument({
        file: uploadFile,
        project_id: selectedProjectId || null,
        use_ai: uploadUseAi,
        complexity: uploadComplexity,
        jurisdiction: uploadJurisdiction,
        adopted_locally: uploadAdopted,
      });
      setSelectedStd(created);
      setEditStatus((created.status as StandardStatus) || "unknown");
      setUploadFile(null);
      setInfoMsg(
        `Uploaded ${created.original_filename || created.standard_number} (${created.metadata_label})`
      );
      await refreshLibrary(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };

  const handleManualCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!standardNumber.trim() || !title.trim()) {
      setError("Standard number and title are required.");
      return;
    }
    setCreating(true);
    setError(null);
    setInfoMsg(null);
    try {
      const created = await createStandard({
        project_id: selectedProjectId || null,
        standard_number: standardNumber.trim(),
        title: title.trim(),
        issuing_body: issuingBody.trim(),
        edition_year: editionYear.trim() || "unknown",
        status: statusVal,
        jurisdiction: jurisdiction.trim(),
        adopted_locally: adoptedLocally,
        owner_notes: ownerNotes.trim() || null,
        owner_excerpts: draftExcerpts,
      });
      setSelectedStd(created);
      setEditStatus((created.status as StandardStatus) || "unknown");
      setDraftExcerpts([]);
      setInfoMsg(`Registered ${created.standard_number} (v${created.version})`);
      await refreshLibrary(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const handleSelectStandard = async (stdId: string) => {
    setError(null);
    try {
      const full = await getStandardDetail(stdId);
      setSelectedStd(full);
      setEditStatus((full.status as StandardStatus) || "unknown");
      setReplacementId(full.superseded_by_id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleConfirmSelected = async () => {
    if (!selectedStd) return;
    setError(null);
    try {
      const updated = await confirmStandardMetadata(selectedStd.id, {
        confirmed_by: confirmedBy.trim() || "Owner",
        standard_number: selectedStd.standard_number,
        title: selectedStd.title,
        issuing_body: selectedStd.issuing_body,
        edition_year: selectedStd.edition_year,
        status: editStatus,
        adopted_locally: selectedStd.adopted_locally,
      });
      setSelectedStd(updated);
      setInfoMsg(`Confirmed metadata for ${updated.standard_number} (v${updated.version})`);
      await refreshLibrary(updated.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleSupersedeSelected = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedStd) return;
    if (!replacementId || !supersessionNote.trim()) {
      setError("Select a replacement standard and enter a supersession note.");
      return;
    }
    setError(null);
    try {
      const updated = await supersedeStandard(selectedStd.id, {
        superseded_by_id: replacementId,
        supersession_note: supersessionNote.trim(),
      });
      setSelectedStd(updated);
      setEditStatus("superseded");
      setSupersessionNote("");
      setInfoMsg(
        `Linked supersession: ${updated.standard_number} -> ${updated.superseded_by_number || replacementId}`
      );
      await refreshLibrary(updated.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleSaveUpdateAndExcerpt = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedStd) return;
    const cleanedExcerpt = newExcerptText.trim();
    if (cleanedExcerpt.length > MAX_EXCERPT_CHARS) {
      setError(`Owner excerpt exceeds ${MAX_EXCERPT_CHARS} characters (${cleanedExcerpt.length}).`);
      return;
    }
    setError(null);
    try {
      const nextExcerpts: OwnerExcerptIn[] = [
        ...selectedStd.owner_excerpts.map((ex) => ({
          excerpt_id: ex.excerpt_id,
          page_ref: ex.page_ref,
          text: ex.text,
        })),
      ];
      if (cleanedExcerpt) {
        nextExcerpts.push({
          page_ref: newExcerptPage.trim() || "p. 1",
          text: cleanedExcerpt,
        });
      }
      const updated = await updateStandard(selectedStd.id, {
        status: editStatus,
        owner_excerpts: nextExcerpts,
        change_note: changeNote.trim() || "Owner update",
      });
      setSelectedStd(updated);
      setNewExcerptText("");
      setInfoMsg(`Updated ${updated.standard_number} to v${updated.version}`);
      await refreshLibrary(updated.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleExportRegister = async () => {
    setExporting(true);
    setError(null);
    try {
      const res = await exportStandardsRegister({
        project_id: selectedProjectId || null,
        language: exportLang,
        classification: exportClass,
      });
      setExportResult(res);
      setInfoMsg(
        `Exported register (${res.standards_count} standards, ${res.cited_warnings_count} citation warning(s)).`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="panel" data-testid="standards-library-view">
      <h2>{t.heading}</h2>
      <p className="muted">{t.subtitle}</p>

      <div
        className="card"
        style={{
          marginBottom: "1rem",
          backgroundColor: "#f0f7ff",
          border: "1px solid #90caf9",
        }}
      >
        <strong>{t.policyBanner}</strong>
      </div>

      {error ? (
        <div className="alert error" role="alert">
          {error}
        </div>
      ) : null}
      {infoMsg ? (
        <div className="alert" style={{ backgroundColor: "#e8f5e9", color: "#1b5e20" }}>
          {infoMsg}
        </div>
      ) : null}

      {/* Scope, Search & Synthetic Preset Controls */}
      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="form-grid">
          <label>
            {t.projectLabel}
            <select
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
            >
              <option value="">{t.globalScopeOption}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} — {p.name}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={includeGlobal}
              onChange={(e) => setIncludeGlobal(e.target.checked)}
            />
            <span>{t.includeGlobalCheck}</span>
          </label>

          <label>
            {t.searchLabel}
            <input
              type="text"
              value={searchQuery}
              placeholder={t.searchPlaceholder}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </label>

          <label>
            {t.filterStatusLabel}
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">{t.allStatuses}</option>
              {STATUS_OPTIONS.map((st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={adoptedOnly}
              onChange={(e) => setAdoptedOnly(e.target.checked)}
            />
            <span>{t.adoptedOnlyCheck}</span>
          </label>

          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <button type="button" className="btn" onClick={() => void refreshLibrary()}>
              {t.searchBtn}
            </button>
          </div>
        </div>

        <hr style={{ margin: "1rem 0", borderColor: "#e2e8f0" }} />
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
          <strong style={{ fontSize: "0.9rem" }}>{t.presetHeading}:</strong>
          <select
            value={selectedPresetKey}
            onChange={(e) => setSelectedPresetKey(e.target.value)}
          >
            {presets.map((p) => (
              <option key={p.key} value={p.key}>
                {lang === "ar" ? p.label_ar : p.label_en}
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-secondary" onClick={handleLoadPreset}>
            {t.loadPresetBtn}
          </button>
        </div>
      </div>

      {/* Upload & Manual Registration Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: "1rem",
          marginBottom: "1rem",
        }}
      >
        <form className="card" onSubmit={handleUploadSubmit}>
          <h3>{t.uploadHeading}</h3>
          <div style={{ display: "grid", gap: "0.65rem" }}>
            <label>
              {t.fileLabel}
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <label>
              {t.uploadJurisdictionLabel}
              <input
                type="text"
                value={uploadJurisdiction}
                onChange={(e) => setUploadJurisdiction(e.target.value)}
                placeholder="e.g. Municipal / National"
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <input
                type="checkbox"
                checked={uploadAdopted}
                onChange={(e) => setUploadAdopted(e.target.checked)}
              />
              <span>{t.uploadAdoptedCheck}</span>
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <input
                type="checkbox"
                checked={uploadUseAi}
                onChange={(e) => setUploadUseAi(e.target.checked)}
              />
              <span>{t.useAiCheck}</span>
            </label>
            {uploadUseAi ? (
              <label>
                {t.aiComplexityLabel}
                <select
                  value={uploadComplexity}
                  onChange={(e) => setUploadComplexity(e.target.value as TaskComplexity)}
                >
                  <option value="fast">fast</option>
                  <option value="deep">deep</option>
                  <option value="maximum">maximum</option>
                </select>
              </label>
            ) : null}
            <button type="submit" className="btn" disabled={uploading}>
              {uploading ? t.uploadingBtn : t.uploadBtn}
            </button>
          </div>
        </form>

        <form className="card" onSubmit={handleManualCreate}>
          <h3>{t.manualHeading}</h3>
          <div style={{ display: "grid", gap: "0.55rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
              <label>
                {t.numberLabel}
                <input
                  type="text"
                  value={standardNumber}
                  onChange={(e) => setStandardNumber(e.target.value)}
                  placeholder="SYN-1000-2024"
                  required
                />
              </label>
              <label>
                {t.editionLabel}
                <input
                  type="text"
                  value={editionYear}
                  onChange={(e) => setEditionYear(e.target.value)}
                  placeholder="2024 or unknown"
                />
              </label>
            </div>
            <label>
              {t.titleLabel}
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
              <label>
                {t.issuerLabel}
                <input
                  type="text"
                  value={issuingBody}
                  onChange={(e) => setIssuingBody(e.target.value)}
                />
              </label>
              <label>
                {t.statusLabel}
                <select
                  value={statusVal}
                  onChange={(e) => setStatusVal(e.target.value as StandardStatus)}
                >
                  {STATUS_OPTIONS.map((st) => (
                    <option key={st} value={st}>
                      {st}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
              <label>
                {t.jurisdictionLabel}
                <input
                  type="text"
                  value={jurisdiction}
                  onChange={(e) => setJurisdiction(e.target.value)}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <input
                  type="checkbox"
                  checked={adoptedLocally}
                  onChange={(e) => setAdoptedLocally(e.target.checked)}
                />
                <span>{t.adoptedCheck}</span>
              </label>
            </div>
            <label>
              {t.notesLabel}
              <input
                type="text"
                value={ownerNotes}
                onChange={(e) => setOwnerNotes(e.target.value)}
              />
            </label>
            <div style={{ padding: "0.5rem", border: "1px dashed #cbd5e1", borderRadius: "6px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "90px 1fr", gap: "0.5rem" }}>
                <label>
                  {t.excerptPageLabel}
                  <input
                    type="text"
                    value={excerptPageRef}
                    onChange={(e) => setExcerptPageRef(e.target.value)}
                  />
                </label>
                <label>
                  {t.excerptTextLabel} ({excerptText.trim().length}/{MAX_EXCERPT_CHARS})
                  <input
                    type="text"
                    value={excerptText}
                    onChange={(e) => setExcerptText(e.target.value)}
                    maxLength={MAX_EXCERPT_CHARS + 20}
                  />
                </label>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ marginTop: "0.4rem" }}
                onClick={handleAddDraftExcerpt}
              >
                {t.addExcerptBtn}
              </button>
              {draftExcerpts.length > 0 ? (
                <ul style={{ margin: "0.4rem 0 0", paddingInlineStart: "1.2rem", fontSize: "0.85rem" }}>
                  {draftExcerpts.map((ex, idx) => (
                    <li key={`${ex.page_ref}-${idx}`}>
                      [{ex.page_ref}] {ex.text}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            <button type="submit" className="btn" disabled={creating}>
              {creating ? t.creatingBtn : t.createBtn}
            </button>
          </div>
        </form>
      </div>

      {/* Register Export Panel */}
      <div className="card" style={{ marginBottom: "1rem" }}>
        <h3>{t.exportHeading}</h3>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end" }}>
          <label>
            {t.exportLangLabel}
            <select
              value={exportLang}
              onChange={(e) => setExportLang(e.target.value as ReportLanguage)}
            >
              <option value="ar">العربية (RTL)</option>
              <option value="en">English (LTR)</option>
            </select>
          </label>
          <label>
            {t.exportClassLabel}
            <select
              value={exportClass}
              onChange={(e) => setExportClass(e.target.value as ProjectClassification)}
            >
              {CLASSIFICATIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn"
            disabled={exporting}
            onClick={() => void handleExportRegister()}
          >
            {exporting ? t.exportingBtn : t.exportBtn}
          </button>
        </div>
        {exportResult ? (
          <div style={{ marginTop: "0.75rem", display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
            {exportResult.files.map((f) => (
              <a
                key={f.filename}
                className="btn btn-secondary"
                href={getStandardsRegisterDownloadUrl(f.filename)}
                target="_blank"
                rel="noreferrer"
              >
                {f.format.toUpperCase()}: {f.filename} ({t.shaLabel}: {f.sha256.slice(0, 12)}...)
              </a>
            ))}
          </div>
        ) : null}
      </div>

      {/* Library Index & Detail Inspector Split */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(300px, 1fr) minmax(360px, 1.3fr)",
          gap: "1rem",
        }}
      >
        <div className="card">
          <h3>
            {t.registerHeading} ({standards.length})
          </h3>
          {standards.length === 0 ? (
            <p className="muted">{t.emptyList}</p>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {standards.map((std) => (
                <button
                  key={std.id}
                  type="button"
                  onClick={() => void handleSelectStandard(std.id)}
                  style={{
                    textAlign: lang === "ar" ? "right" : "left",
                    padding: "0.75rem",
                    borderRadius: "8px",
                    border:
                      selectedStd?.id === std.id ? "2px solid #0b57d0" : "1px solid #cbd5e1",
                    backgroundColor: selectedStd?.id === std.id ? "#f0f7ff" : "#ffffff",
                    cursor: "pointer",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: "0.5rem",
                    }}
                  >
                    <strong>
                      {std.standard_number} ({std.edition_year})
                    </strong>
                    <span
                      style={{
                        ...statusBadgeStyle(std.status),
                        padding: "0.15rem 0.5rem",
                        borderRadius: "999px",
                        fontSize: "0.78rem",
                        fontWeight: 600,
                      }}
                    >
                      {std.status}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.9rem", marginTop: "0.25rem" }}>{std.title}</div>
                  <div className="muted" style={{ fontSize: "0.78rem", marginTop: "0.25rem" }}>
                    {std.issuing_body || "-"} | {t.versionLabel} v{std.version} | Cited:{" "}
                    {std.where_cited.length}
                    {std.citation_warnings.length > 0 ? " ⚠" : ""}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3>{t.detailHeading}</h3>
          {!selectedStd ? (
            <p className="muted">{t.selectPrompt}</p>
          ) : (
            <div style={{ display: "grid", gap: "0.85rem" }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
                <strong style={{ fontSize: "1.1rem" }}>
                  {selectedStd.standard_number} — {selectedStd.title}
                </strong>
                <span
                  style={{
                    ...statusBadgeStyle(selectedStd.status),
                    padding: "0.2rem 0.55rem",
                    borderRadius: "999px",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                  }}
                >
                  {selectedStd.status}
                </span>
                <span className="badge">
                  {t.versionLabel}: v{selectedStd.version}
                </span>
                <span className="badge">
                  {t.tokensLabel}: {selectedStd.tokens_used}
                </span>
              </div>

              <div style={{ fontSize: "0.88rem" }}>
                <div>
                  Issuer: <strong>{selectedStd.issuing_body || "-"}</strong> | Edition:{" "}
                  <strong>{selectedStd.edition_year}</strong> | Jurisdiction:{" "}
                  <strong>{selectedStd.jurisdiction || "-"}</strong> | Adopted Locally:{" "}
                  <strong>{selectedStd.adopted_locally ? "Yes" : "No"}</strong>
                </div>
                {selectedStd.file_sha256 ? (
                  <div className="muted" style={{ marginTop: "0.25rem" }}>
                    File: {selectedStd.original_filename} | {t.shaLabel}:{" "}
                    <code>{selectedStd.file_sha256}</code>
                  </div>
                ) : null}
                {selectedStd.replacement_chain_summary ? (
                  <div style={{ marginTop: "0.35rem", color: "#9a6700" }}>
                    Supersession Chain: <strong>{selectedStd.replacement_chain_summary}</strong>
                  </div>
                ) : null}
              </div>

              {selectedStd.metadata_status === "unverified_suggestion" ||
              selectedStd.metadata_status === "unverified_ai_suggestion" ||
              selectedStd.ai_suggestion_status === "unverified_ai_suggestion" ? (
                <div
                  className="alert"
                  style={{
                    backgroundColor: "#fff8e1",
                    border: "1px solid #ffca28",
                    color: "#6d4c00",
                  }}
                >
                  <div>
                    <strong>{selectedStd.metadata_label}</strong>
                  </div>
                  <div style={{ marginTop: "0.25rem", fontSize: "0.88rem" }}>{t.confirmBanner}</div>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "0.5rem",
                      alignItems: "center",
                      marginTop: "0.5rem",
                    }}
                  >
                    <input
                      type="text"
                      value={confirmedBy}
                      onChange={(e) => setConfirmedBy(e.target.value)}
                      placeholder={t.confirmedByLabel}
                    />
                    <button type="button" className="btn" onClick={() => void handleConfirmSelected()}>
                      {t.confirmBtn}
                    </button>
                  </div>
                </div>
              ) : null}

              {selectedStd.citation_warnings.length > 0 ? (
                <div className="alert error">
                  {selectedStd.citation_warnings.map((w, i) => (
                    <div key={i}>⚠ {w}</div>
                  ))}
                </div>
              ) : null}

              {/* Where Cited Table */}
              <div>
                <h4>{t.whereCitedHeading}</h4>
                {selectedStd.where_cited.length === 0 ? (
                  <p className="muted">{t.noCitations}</p>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.86rem" }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Module</th>
                        <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Artifact</th>
                        <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Location</th>
                        <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Flag</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedStd.where_cited.map((hit, idx) => (
                        <tr key={`${hit.artifact_id}-${idx}`}>
                          <td style={{ padding: "0.3rem 0.2rem" }}>{hit.module}</td>
                          <td style={{ padding: "0.3rem 0.2rem" }}>{hit.artifact_title}</td>
                          <td style={{ padding: "0.3rem 0.2rem" }}>{hit.location}</td>
                          <td style={{ padding: "0.3rem 0.2rem", fontWeight: 600 }}>{hit.flagged_status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Register Supersession */}
              <form
                onSubmit={handleSupersedeSelected}
                style={{ padding: "0.65rem", border: "1px solid #e2e8f0", borderRadius: "6px" }}
              >
                <h4>{t.supersedeHeading}</h4>
                <div style={{ display: "grid", gap: "0.5rem" }}>
                  <label>
                    {t.replacementSelectLabel}
                    <select
                      value={replacementId}
                      onChange={(e) => setReplacementId(e.target.value)}
                    >
                      <option value="">{t.noReplacementSelected}</option>
                      {standards
                        .filter((cand) => cand.id !== selectedStd.id)
                        .map((cand) => (
                          <option key={cand.id} value={cand.id}>
                            {cand.standard_number} ({cand.edition_year}) [{cand.status}]
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    {t.supersessionNoteLabel}
                    <input
                      type="text"
                      value={supersessionNote}
                      onChange={(e) => setSupersessionNote(e.target.value)}
                      placeholder="Replaced by 2024 edition per owner decree..."
                    />
                  </label>
                  <button type="submit" className="btn btn-secondary">
                    {t.supersedeBtn}
                  </button>
                </div>
              </form>

              {/* Status & Bounded Excerpts Update */}
              <form
                onSubmit={handleSaveUpdateAndExcerpt}
                style={{ padding: "0.65rem", border: "1px solid #e2e8f0", borderRadius: "6px" }}
              >
                <h4>{t.updateExcerptsHeading}</h4>
                {selectedStd.owner_excerpts.length > 0 ? (
                  <ul style={{ margin: "0 0 0.5rem", paddingInlineStart: "1.2rem", fontSize: "0.86rem" }}>
                    {selectedStd.owner_excerpts.map((ex) => (
                      <li key={ex.excerpt_id}>
                        <strong>[{ex.page_ref}]</strong> {ex.text}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div style={{ display: "grid", gap: "0.5rem" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
                    <label>
                      {t.statusLabel}
                      <select
                        value={editStatus}
                        onChange={(e) => setEditStatus(e.target.value as StandardStatus)}
                      >
                        {STATUS_OPTIONS.map((st) => (
                          <option key={st} value={st}>
                            {st}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {t.changeNoteLabel}
                      <input
                        type="text"
                        value={changeNote}
                        onChange={(e) => setChangeNote(e.target.value)}
                      />
                    </label>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "90px 1fr", gap: "0.5rem" }}>
                    <label>
                      {t.excerptPageLabel}
                      <input
                        type="text"
                        value={newExcerptPage}
                        onChange={(e) => setNewExcerptPage(e.target.value)}
                      />
                    </label>
                    <label>
                      {t.excerptTextLabel} ({newExcerptText.trim().length}/{MAX_EXCERPT_CHARS})
                      <input
                        type="text"
                        value={newExcerptText}
                        onChange={(e) => setNewExcerptText(e.target.value)}
                      />
                    </label>
                  </div>
                  <button type="submit" className="btn">
                    {t.saveUpdateBtn}
                  </button>
                </div>
              </form>

              {/* Version History */}
              <div>
                <h4>{t.historyHeading}</h4>
                <ul style={{ margin: 0, paddingInlineStart: "1.2rem", fontSize: "0.82rem" }}>
                  {selectedStd.history.map((h, i) => (
                    <li key={i}>
                      v{String(h.version ?? "?")} — {String(h.action ?? "")} —{" "}
                      {String(h.note ?? "")} ({String(h.timestamp ?? "")})
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
