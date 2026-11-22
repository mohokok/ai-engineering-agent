import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  createTechnicalComparison,
  decideTechnicalComparison,
  exportTechnicalComparison,
  getComparisonDetail,
  getDeliverableDownloadUrl,
  listComparisonPresets,
  listProjectBoqSheets,
  listProjectCalculations,
  listProjectComparisons,
  listProjectSpecifications,
  listProjects,
  listResearchSources,
  listTasks,
} from "../api";
import type {
  BoqSheetSummaryOut,
  CalculationSummaryOut,
  ComparisonCategory,
  ComparisonCriterionIn,
  ComparisonOptionIn,
  ComparisonPresetOut,
  ComparisonScope,
  ComparisonSourceKind,
  Lang,
  ProjectClassification,
  ProjectSummary,
  ReportLanguage,
  ResearchSourceOut,
  ScoringDirection,
  SpecificationSummaryOut,
  TaskSummaryOut,
  TechnicalComparisonDetailOut,
  TechnicalComparisonSummaryOut,
} from "../types";

const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const CATEGORIES: ComparisonCategory[] = [
  "compliance",
  "performance",
  "safety",
  "durability",
  "energy",
  "maintainability",
  "constructability",
  "initial_cost",
  "operating_cost",
  "lifecycle_cost",
  "risks",
];

const DIRECTIONS: ScoringDirection[] = [
  "higher_better",
  "lower_better",
  "boolean_pass",
  "direct_score_0_100",
];

const SOURCE_KINDS: ComparisonSourceKind[] = [
  "owner_entered",
  "boq_item",
  "specification",
  "calculation",
  "research_source",
];

const COPY: Record<
  Lang,
  {
    heading: string;
    subtitle: string;
    presetHeading: string;
    loadPresetBtn: string;
    projectLabel: string;
    taskLabel: string;
    noTask: string;
    scopeLabel: string;
    titleLabel: string;
    titlePlaceholder: string;
    disciplineLabel: string;
    classLabel: string;
    langLabel: string;
    lifecycleLabel: string;
    useAiLabel: string;
    aiNotice: string;
    projRefsTitle: string;
    criteriaTitle: string;
    addCriterionBtn: string;
    weightSumLabel: string;
    weightInvalidMsg: string;
    optionsTitle: string;
    addOptionBtn: string;
    evaluateBtn: string;
    evaluatingBtn: string;
    savedListTitle: string;
    emptySaved: string;
    advisoryBannerPrefix: string;
    rankingTitle: string;
    matrixTitle: string;
    flagsTitle: string;
    decisionTitle: string;
    selectedOptLabel: string;
    decidedByLabel: string;
    decisionNoteLabel: string;
    approveAiCheck: string;
    saveDecisionBtn: string;
    decisionDoneLabel: string;
    exportArBtn: string;
    exportEnBtn: string;
    deliverablesTitle: string;
    mandatoryBadge: string;
    passBadge: string;
    failBadge: string;
    notProvidedBadge: string;
    mismatchBadge: string;
    convertedBadge: string;
  }
> = {
  ar: {
    heading: "المقارنات الفنية والتجارية (Step 15 — Technical Comparison)",
    subtitle:
      "تقييم حتمي موزون بـ Decimal للمعدات والمواد والعروض بالربط مع بنود الكميات والمواصفات والحسابات والمصادر المعتمدة — 0 توكن ذكاء اصطناعي افتراضياً، والقيم المفقودة تُعرض صراحةً كـ 'not provided'.",
    presetHeading: "نماذج مقارنة افتراضية للعيادة (بيانات تمثيلية Synthetic — ليست أسعاراً حقيقية):",
    loadPresetBtn: "تحميل النموذج",
    projectLabel: "المشروع",
    taskLabel: "المهمة المرتبطة (اختياري)",
    noTask: "— مقارنة على مستوى المشروع —",
    scopeLabel: "نطاق المقارنة",
    titleLabel: "عنوان المقارنة",
    titlePlaceholder: "مثال: مقارنة فنية لمولد احتياطي 150 ك.ف.أ",
    disciplineLabel: "التخصص",
    classLabel: "التصنيف الهندسي",
    langLabel: "لغة التصدير",
    lifecycleLabel: "سنوات دورة الحياة (اختياري)",
    useAiLabel: "توليد ملخص مفاضلة اختياري بالذكاء الاصطناعي (مسودة غير متحقق منها حتى اعتماد المالك)",
    aiNotice:
      "يظل القرار النهائي حصراً بيد المالك / المهندس المرخص؛ أي صياغة بالذكاء الاصطناعي تُوسم كـ UNVERIFIED AI DRAFT ولا تعدل الأوزان أو الدرجات.",
    projRefsTitle: "مراجع المشروع المتاحة للربط المباشر",
    criteriaTitle: "1. معايير التقييم الموزونة (يجب أن يكون مجموع الأوزان = 100%)",
    addCriterionBtn: "+ إضافة معيار",
    weightSumLabel: "مجموع الأوزان الحالي",
    weightInvalidMsg: "يجب أن يساوي مجموع أوزان المعايير 100.00% تماماً قبل التقييم.",
    optionsTitle: "2. الخيارات / العروض والقيم المسندة بالمصادر",
    addOptionBtn: "+ إضافة خيار",
    evaluateBtn: "تقييم المصفوفة وتصدير (DOCX / PDF / XLSX)",
    evaluatingBtn: "جاري الحساب والتصدير...",
    savedListTitle: "المقارنات الفنية المحفوظة",
    emptySaved: "لا توجد مقارنات فنية محفوظة لهذا المشروع بعد.",
    advisoryBannerPrefix: "مصفوفة استشارية — القرار للمالك",
    rankingTitle: "الترتيب الاستشاري واجتياز المتطلبات الإلزامية",
    matrixTitle: "مصفوفة الدرجات الموزونة والوحدات والمصادر",
    flagsTitle: "تنبيهات تعارض الوحدات والقيم الإلزامية المفقودة",
    decisionTitle: "قرار المالك / المهندس المرخص النهائي",
    selectedOptLabel: "الخيار المعتمد",
    decidedByLabel: "اسم المعتمد (المالك / المهندس)",
    decisionNoteLabel: "ملاحظة ومسوغ القرار",
    approveAiCheck: "اعتماد صياغة ملخص الذكاء الاصطناعي وإزالة وسم المسودة غير المتحققة",
    saveDecisionBtn: "تسجيل قرار المالك وتصدير نسخة محدثة",
    decisionDoneLabel: "تم تسجيل قرار المالك",
    exportArBtn: "تصدير حزمة عربية RTL (DOCX+PDF+XLSX)",
    exportEnBtn: "تصدير حزمة إنجليزية LTR (DOCX+PDF+XLSX)",
    deliverablesTitle: "الملفات المصدرة الموثقة بـ SHA-256 (مجلد 09_Comparisons)",
    mandatoryBadge: "إلزامي",
    passBadge: "ناجح",
    failBadge: "راسب",
    notProvidedBadge: "not provided",
    mismatchBadge: "تعارض وحدات",
    convertedBadge: "تم التحويل صراحةً",
  },
  en: {
    heading: "Technical & Offer Comparisons (Step 15 — Weighted Decimal Matrix)",
    subtitle:
      "Deterministic Decimal multi-criteria evaluation linked to project BOQs, Specifications, Calculations, and reviewed Research Sources — 0 AI tokens by default, missing values shown verbatim as 'not provided'.",
    presetHeading: "Synthetic Clinic Fixtures (Example Data Only — Zero Real Client Quotes):",
    loadPresetBtn: "Load Fixture",
    projectLabel: "Project",
    taskLabel: "Linked Task (Optional)",
    noTask: "— Project-level comparison —",
    scopeLabel: "Comparison Scope",
    titleLabel: "Comparison Title",
    titlePlaceholder: "e.g., 150 kVA Standby Diesel Generator Technical Evaluation",
    disciplineLabel: "Discipline",
    classLabel: "Classification",
    langLabel: "Export Language",
    lifecycleLabel: "Lifecycle Horizon (Years, Optional)",
    useAiLabel: "Optional Gemini executive trade-off summary (tagged UNVERIFIED AI DRAFT until owner approval)",
    aiNotice:
      "Advisory ranking only — final choice rests strictly with the Owner / Licensed Engineer. AI narrative never modifies Decimal math.",
    projRefsTitle: "Project Grounding Entities Available",
    criteriaTitle: "1. Weighted Evaluation Criteria (Weights must sum strictly to 100%)",
    addCriterionBtn: "+ Add Criterion",
    weightSumLabel: "Current Weight Sum",
    weightInvalidMsg: "Criteria weights must sum strictly to 100.00% before submitting.",
    optionsTitle: "2. Candidate Options / Vendor Offers & Attributed Cell Values",
    addOptionBtn: "+ Add Option",
    evaluateBtn: "Evaluate & Export Package (DOCX / PDF / XLSX)",
    evaluatingBtn: "Evaluating & Exporting...",
    savedListTitle: "Saved Project Technical Comparisons",
    emptySaved: "No technical comparisons have been saved for this project yet.",
    advisoryBannerPrefix: "Advisory Matrix Only — Owner Decides",
    rankingTitle: "Advisory Option Ranking & Mandatory Gate Summary",
    matrixTitle: "Weighted Evaluation Matrix, Unit Conversions & Source Provenance",
    flagsTitle: "Unit Mismatch & Missing Mandatory Flags",
    decisionTitle: "Owner / Licensed Engineer Final Decision Gate",
    selectedOptLabel: "Selected Option",
    decidedByLabel: "Decided By (Owner / Engineer)",
    decisionNoteLabel: "Decision Rationale / Engineering Note",
    approveAiCheck: "Approve AI narrative summary (clear UNVERIFIED AI DRAFT badge)",
    saveDecisionBtn: "Record Final Owner Decision & Export Revision",
    decisionDoneLabel: "Owner Decision Recorded",
    exportArBtn: "Export Arabic RTL (DOCX+PDF+XLSX)",
    exportEnBtn: "Export English LTR (DOCX+PDF+XLSX)",
    deliverablesTitle: "Immutable SHA-256 Deliverables (09_Comparisons)",
    mandatoryBadge: "MANDATORY",
    passBadge: "PASS",
    failBadge: "FAIL",
    notProvidedBadge: "not provided",
    mismatchBadge: "UNIT MISMATCH",
    convertedBadge: "CONVERTED",
  },
};

interface TechnicalComparisonsViewProps {
  lang: Lang;
  initialPresets?: ComparisonPresetOut[];
  initialComparisons?: TechnicalComparisonSummaryOut[];
  initialSelectedComparison?: TechnicalComparisonDetailOut | null;
}

export function TechnicalComparisonsView({
  lang,
  initialPresets,
  initialComparisons,
  initialSelectedComparison = null,
}: TechnicalComparisonsViewProps) {
  const t = COPY[lang];
  const isRtl = lang === "ar";

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [tasks, setTasks] = useState<TaskSummaryOut[]>([]);
  const [taskId, setTaskId] = useState<string>("");
  const [boqSheets, setBoqSheets] = useState<BoqSheetSummaryOut[]>([]);
  const [specs, setSpecs] = useState<SpecificationSummaryOut[]>([]);
  const [calcs, setCalcs] = useState<CalculationSummaryOut[]>([]);
  const [sources, setSources] = useState<ResearchSourceOut[]>([]);
  const [presets, setPresets] = useState<ComparisonPresetOut[]>(initialPresets ?? []);
  const [savedList, setSavedList] = useState<TechnicalComparisonSummaryOut[]>(initialComparisons ?? []);
  const [selectedDetail, setSelectedDetail] = useState<TechnicalComparisonDetailOut | null>(
    initialSelectedComparison
  );

  const [scope, setScope] = useState<ComparisonScope>("equipment");
  const [title, setTitle] = useState<string>("");
  const [discipline, setDiscipline] = useState<string>("electrical");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [outLang, setOutLang] = useState<ReportLanguage>(lang);
  const [lifecycleYears, setLifecycleYears] = useState<string>("10");
  const [useAi, setUseAi] = useState<boolean>(false);

  const [criteria, setCriteria] = useState<ComparisonCriterionIn[]>([
    {
      criterion_id: "compliance",
      category: "compliance",
      label: "Code / Specification Compliance",
      weight: 40,
      is_mandatory: true,
      direction: "boolean_pass",
      target_unit: "bool",
      mandatory_expected_bool: true,
      source_kind: "owner_entered",
      source_ref: "Project baseline compliance requirement",
    },
    {
      criterion_id: "performance",
      category: "performance",
      label: "Rated Duty Capacity",
      weight: 30,
      is_mandatory: false,
      direction: "higher_better",
      target_unit: "kW",
      source_kind: "owner_entered",
      source_ref: "Project duty requirement",
    },
    {
      criterion_id: "initial_cost",
      category: "initial_cost",
      label: "Supply & Install Cost",
      weight: 30,
      is_mandatory: false,
      direction: "lower_better",
      target_unit: "USD",
      source_kind: "owner_entered",
      source_ref: "Owner offer comparison sheet",
    },
  ]);

  const [options, setOptions] = useState<ComparisonOptionIn[]>([
    {
      option_id: "opt_a",
      name: "Option A",
      vendor_or_source: "Offer A",
      risks: [],
      cells: [
        {
          criterion_id: "compliance",
          value: true,
          unit: "bool",
          source_kind: "owner_entered",
          source_ref: "Vendor A submittal sheet",
        },
        {
          criterion_id: "performance",
          value: 100,
          unit: "kW",
          source_kind: "owner_entered",
          source_ref: "Vendor A datasheet",
        },
        {
          criterion_id: "initial_cost",
          value: 25000,
          unit: "USD",
          source_kind: "owner_entered",
          source_ref: "Vendor A quote",
        },
      ],
    },
    {
      option_id: "opt_b",
      name: "Option B",
      vendor_or_source: "Offer B",
      risks: [],
      cells: [
        {
          criterion_id: "compliance",
          value: true,
          unit: "bool",
          source_kind: "owner_entered",
          source_ref: "Vendor B submittal sheet",
        },
        {
          criterion_id: "performance",
          value: 95000,
          unit: "W",
          source_kind: "owner_entered",
          source_ref: "Vendor B datasheet (W->kW)",
        },
        {
          criterion_id: "initial_cost",
          value: 22000,
          unit: "USD",
          source_kind: "owner_entered",
          source_ref: "Vendor B quote",
        },
      ],
    },
  ]);

  const [decisionOptId, setDecisionOptId] = useState<string>("");
  const [decidedBy, setDecidedBy] = useState<string>("Owner / Lead Engineer");
  const [decisionNote, setDecisionNote] = useState<string>("");
  const [approveAiDraft, setApproveAiDraft] = useState<boolean>(true);

  const [running, setRunning] = useState<boolean>(false);
  const [exporting, setExporting] = useState<boolean>(false);
  const [deciding, setDeciding] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  useEffect(() => {
    setOutLang(lang);
  }, [lang]);

  useEffect(() => {
    if (!initialPresets) {
      listComparisonPresets()
        .then((res) => setPresets(res.presets))
        .catch(() => {
          // Safe offline fallback during tests
        });
    }
    listProjects()
      .then((res) => {
        setProjects(res.projects);
        if (res.projects.length > 0) {
          setProjectId((prev) => prev || res.projects[0].id);
        }
      })
      .catch(() => {
        // Safe offline fallback
      });
  }, [initialPresets]);

  const refreshProjectContext = useCallback(async (pid: string) => {
    if (!pid) return;
    try {
      const [taskRes, boqRes, specRes, calcRes, srcRes, cmpRes] = await Promise.all([
        listTasks({ projectId: pid }),
        listProjectBoqSheets(pid),
        listProjectSpecifications(pid),
        listProjectCalculations(pid),
        listResearchSources({ project_id: pid, reviewed_only: true }),
        listProjectComparisons(pid),
      ]);
      setTasks(taskRes.tasks);
      setBoqSheets(boqRes.sheets);
      setSpecs(specRes.specifications);
      setCalcs(calcRes.calculations);
      setSources(srcRes.sources);
      setSavedList(cmpRes.comparisons);
    } catch {
      // Keep UI interactive if mocked
    }
  }, []);

  useEffect(() => {
    if (projectId && !initialComparisons) {
      void refreshProjectContext(projectId);
    }
  }, [projectId, initialComparisons, refreshProjectContext]);

  useEffect(() => {
    if (selectedDetail && selectedDetail.matrix.options.length > 0) {
      setDecisionOptId(
        selectedDetail.owner_selected_option_id ||
          selectedDetail.matrix.leading_option_id ||
          selectedDetail.matrix.options[0].option_id
      );
    }
  }, [selectedDetail]);

  const totalWeight = useMemo(() => {
    return criteria.reduce((acc, c) => {
      const parsed = Number(c.weight);
      return Number.isFinite(parsed) ? acc + parsed : acc;
    }, 0);
  }, [criteria]);

  const weightsValid = Math.abs(totalWeight - 100) <= 0.001;

  function applyPreset(preset: ComparisonPresetOut) {
    setScope(preset.comparison_scope);
    setDiscipline(preset.discipline);
    setTitle(lang === "ar" ? preset.title_ar : preset.title_en);
    setLifecycleYears(preset.lifecycle_years != null ? String(preset.lifecycle_years) : "");
    setCriteria(preset.criteria.map((c) => ({ ...c })));
    setOptions(
      preset.options.map((o) => ({
        ...o,
        risks: [...o.risks],
        cells: o.cells.map((cell) => ({ ...cell })),
      }))
    );
    setStatusMsg(`${t.loadPresetBtn}: ${lang === "ar" ? preset.title_ar : preset.title_en}`);
  }

  function updateCell(optionIdx: number, criterionId: string, field: "value" | "unit" | "source_kind" | "source_ref", val: string) {
    setOptions((prev) =>
      prev.map((opt, idx) => {
        if (idx !== optionIdx) return opt;
        const existingIdx = opt.cells.findIndex((c) => c.criterion_id === criterionId);
        const crit = criteria.find((c) => c.criterion_id === criterionId);
        const nextCells = [...opt.cells];
        if (existingIdx === -1) {
          nextCells.push({
            criterion_id: criterionId,
            value: field === "value" ? (val === "" ? null : val) : null,
            unit: field === "unit" ? val : crit?.target_unit || "",
            source_kind: field === "source_kind" ? (val as ComparisonSourceKind) : "owner_entered",
            source_ref: field === "source_ref" ? val : "Owner submittal",
          });
        } else {
          const cur = { ...nextCells[existingIdx] };
          if (field === "value") {
            cur.value = val === "" ? null : val;
          } else if (field === "unit") {
            cur.unit = val;
          } else if (field === "source_kind") {
            cur.source_kind = val as ComparisonSourceKind;
          } else if (field === "source_ref") {
            cur.source_ref = val;
          }
          nextCells[existingIdx] = cur;
        }
        return { ...opt, cells: nextCells };
      })
    );
  }

  async function handleEvaluate(e: FormEvent) {
    e.preventDefault();
    if (!projectId) return;
    if (!weightsValid) {
      setError(t.weightInvalidMsg);
      return;
    }
    setRunning(true);
    setError(null);
    setStatusMsg(null);
    try {
      const yrsParsed = Number(lifecycleYears);
      const created = await createTechnicalComparison(projectId, {
        task_id: taskId || null,
        title: title.trim() || null,
        comparison_scope: scope,
        discipline: discipline.trim() || "multidisciplinary",
        language: outLang,
        classification,
        lifecycle_years: Number.isFinite(yrsParsed) && yrsParsed > 0 ? yrsParsed : null,
        criteria,
        options,
        use_ai: useAi,
      });
      setSelectedDetail(created);
      setStatusMsg(`${created.title} — v${created.version} (${created.ai_draft_label})`);
      await refreshProjectContext(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  async function handleSelectComparison(cmpId: string) {
    setError(null);
    try {
      const detail = await getComparisonDetail(cmpId);
      setSelectedDetail(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleExport(targetLang: ReportLanguage) {
    if (!selectedDetail) return;
    setExporting(true);
    setError(null);
    setStatusMsg(null);
    try {
      const res = await exportTechnicalComparison(selectedDetail.id, { language: targetLang });
      setSelectedDetail(res.comparison);
      setStatusMsg(
        `Export v${res.comparison.export_version}: ${res.docx_deliverable.filename}, ${res.pdf_deliverable.filename}, ${res.xlsx_deliverable.filename}`
      );
      if (projectId) await refreshProjectContext(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  }

  async function handleDecide(e: FormEvent) {
    e.preventDefault();
    if (!selectedDetail || !decisionOptId) return;
    setDeciding(true);
    setError(null);
    setStatusMsg(null);
    try {
      const updated = await decideTechnicalComparison(selectedDetail.id, {
        selected_option_id: decisionOptId,
        decided_by: decidedBy.trim() || "Owner",
        decision_note: decisionNote.trim() || "Approved following engineering review.",
        approve_ai_draft: approveAiDraft,
        export_after_decision: true,
      });
      setSelectedDetail(updated);
      setStatusMsg(`${t.decisionDoneLabel}: ${updated.owner_selected_option_id}`);
      if (projectId) await refreshProjectContext(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeciding(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem", direction: isRtl ? "rtl" : "ltr" }}>
      {error && (
        <div className="status-box status-err" role="alert">
          {error}
        </div>
      )}
      {statusMsg && (
        <div className="status-box status-ok" role="status">
          {statusMsg}
        </div>
      )}

      <section className="panel">
        <h2>{t.heading}</h2>
        <p style={{ margin: "0 0 0.75rem 0", color: "#475569" }}>{t.subtitle}</p>

        {presets.length > 0 && (
          <div style={{ marginBottom: "1rem", padding: "0.75rem", background: "#f8fafc", border: "1px solid #cbd5e1", borderRadius: "6px" }}>
            <strong style={{ display: "block", marginBottom: "0.4rem", fontSize: "0.9rem" }}>{t.presetHeading}</strong>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              {presets.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => applyPreset(p)}
                >
                  {t.loadPresetBtn}: {lang === "ar" ? p.title_ar : p.title_en}
                </button>
              ))}
            </div>
          </div>
        )}

        <form onSubmit={(e) => void handleEvaluate(e)} style={{ display: "grid", gap: "0.85rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "0.65rem" }}>
            <label>
              {t.projectLabel}
              <select value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
                <option value="">—</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    [{p.code}] {p.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              {t.taskLabel}
              <select value={taskId} onChange={(e) => setTaskId(e.target.value)}>
                <option value="">{t.noTask}</option>
                {tasks.map((tk) => (
                  <option key={tk.id} value={tk.id}>
                    {tk.title} ({tk.status})
                  </option>
                ))}
              </select>
            </label>

            <label>
              {t.scopeLabel}
              <select value={scope} onChange={(e) => setScope(e.target.value as ComparisonScope)}>
                <option value="equipment">equipment</option>
                <option value="material">material</option>
                <option value="vendor_offer">vendor_offer</option>
                <option value="system_alternative">system_alternative</option>
              </select>
            </label>

            <label>
              {t.titleLabel}
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t.titlePlaceholder}
              />
            </label>

            <label>
              {t.disciplineLabel}
              <input type="text" value={discipline} onChange={(e) => setDiscipline(e.target.value)} />
            </label>

            <label>
              {t.classLabel}
              <select value={classification} onChange={(e) => setClassification(e.target.value as ProjectClassification)}>
                {CLASSIFICATIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>

            <label>
              {t.langLabel}
              <select value={outLang} onChange={(e) => setOutLang(e.target.value as ReportLanguage)}>
                <option value="ar">العربية (RTL)</option>
                <option value="en">English (LTR)</option>
              </select>
            </label>

            <label>
              {t.lifecycleLabel}
              <input
                type="number"
                step="0.5"
                min="1"
                max="100"
                value={lifecycleYears}
                onChange={(e) => setLifecycleYears(e.target.value)}
              />
            </label>
          </div>

          <div style={{ fontSize: "0.85rem", color: "#334155", background: "#f1f5f9", padding: "0.5rem 0.75rem", borderRadius: "4px" }}>
            <strong>{t.projRefsTitle}:</strong>{" "}
            BOQ ({boqSheets.length}) · Specs ({specs.length}) · Calcs ({calcs.length}) · Reviewed Sources ({sources.length})
          </div>

          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 500 }}>
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
            {t.useAiLabel}
          </label>
          <div style={{ fontSize: "0.85rem", color: "#9a3412", fontWeight: 600 }}>{t.aiNotice}</div>

          {/* Criteria editor */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
              <strong>{t.criteriaTitle}</strong>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span
                  style={{
                    padding: "0.2rem 0.6rem",
                    borderRadius: "4px",
                    fontWeight: 700,
                    background: weightsValid ? "#dcfce7" : "#fee2e2",
                    color: weightsValid ? "#166534" : "#991b1b",
                  }}
                >
                  {t.weightSumLabel}: {totalWeight.toFixed(2)}%
                </span>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() =>
                    setCriteria((prev) => [
                      ...prev,
                      {
                        criterion_id: `crit_${prev.length + 1}`,
                        category: "durability",
                        label: `Criterion ${prev.length + 1}`,
                        weight: 0,
                        is_mandatory: false,
                        direction: "higher_better",
                        target_unit: "hours",
                        source_kind: "owner_entered",
                        source_ref: "Owner specification requirement",
                      },
                    ])
                  }
                >
                  {t.addCriterionBtn}
                </button>
              </div>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Category</th>
                    <th>Label</th>
                    <th>Weight %</th>
                    <th>Mandatory</th>
                    <th>Direction</th>
                    <th>Target Unit</th>
                    <th>Source Kind / Ref</th>
                  </tr>
                </thead>
                <tbody>
                  {criteria.map((c, idx) => (
                    <tr key={c.criterion_id + "_" + idx}>
                      <td>
                        <input
                          type="text"
                          style={{ width: "90px" }}
                          value={c.criterion_id}
                          onChange={(e) =>
                            setCriteria((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, criterion_id: e.target.value } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <select
                          value={c.category}
                          onChange={(e) =>
                            setCriteria((prev) =>
                              prev.map((x, i) =>
                                i === idx ? { ...x, category: e.target.value as ComparisonCategory } : x
                              )
                            )
                          }
                        >
                          {CATEGORIES.map((cat) => (
                            <option key={cat} value={cat}>
                              {cat}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          value={c.label}
                          onChange={(e) =>
                            setCriteria((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, label: e.target.value } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          step="0.5"
                          style={{ width: "70px" }}
                          value={String(c.weight)}
                          onChange={(e) =>
                            setCriteria((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, weight: e.target.value } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={c.is_mandatory}
                          onChange={(e) =>
                            setCriteria((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, is_mandatory: e.target.checked } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <select
                          value={c.direction}
                          onChange={(e) =>
                            setCriteria((prev) =>
                              prev.map((x, i) =>
                                i === idx ? { ...x, direction: e.target.value as ScoringDirection } : x
                              )
                            )
                          }
                        >
                          {DIRECTIONS.map((d) => (
                            <option key={d} value={d}>
                              {d}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          style={{ width: "80px" }}
                          value={c.target_unit}
                          onChange={(e) =>
                            setCriteria((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, target_unit: e.target.value } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: "0.25rem" }}>
                          <select
                            value={c.source_kind}
                            onChange={(e) =>
                              setCriteria((prev) =>
                                prev.map((x, i) =>
                                  i === idx ? { ...x, source_kind: e.target.value as ComparisonSourceKind } : x
                                )
                              )
                            }
                          >
                            {SOURCE_KINDS.map((sk) => (
                              <option key={sk} value={sk}>
                                {sk}
                              </option>
                            ))}
                          </select>
                          <input
                            type="text"
                            value={c.source_ref}
                            onChange={(e) =>
                              setCriteria((prev) =>
                                prev.map((x, i) => (i === idx ? { ...x, source_ref: e.target.value } : x))
                              )
                            }
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Options & values editor */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
              <strong>{t.optionsTitle}</strong>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  setOptions((prev) => [
                    ...prev,
                    {
                      option_id: `opt_${String.fromCharCode(97 + prev.length)}`,
                      name: `Option ${prev.length + 1}`,
                      vendor_or_source: "Vendor Offer",
                      risks: [],
                      cells: [],
                    },
                  ])
                }
              >
                {t.addOptionBtn}
              </button>
            </div>

            <div style={{ display: "grid", gap: "0.75rem" }}>
              {options.map((opt, oIdx) => (
                <div key={opt.option_id + "_" + oIdx} style={{ border: "1px solid #cbd5e1", borderRadius: "6px", padding: "0.65rem" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.5rem", marginBottom: "0.5rem" }}>
                    <label>
                      Option ID
                      <input
                        type="text"
                        value={opt.option_id}
                        onChange={(e) =>
                          setOptions((prev) =>
                            prev.map((x, i) => (i === oIdx ? { ...x, option_id: e.target.value } : x))
                          )
                        }
                      />
                    </label>
                    <label>
                      Name
                      <input
                        type="text"
                        value={opt.name}
                        onChange={(e) =>
                          setOptions((prev) =>
                            prev.map((x, i) => (i === oIdx ? { ...x, name: e.target.value } : x))
                          )
                        }
                      />
                    </label>
                    <label>
                      Vendor / Source
                      <input
                        type="text"
                        value={opt.vendor_or_source}
                        onChange={(e) =>
                          setOptions((prev) =>
                            prev.map((x, i) => (i === oIdx ? { ...x, vendor_or_source: e.target.value } : x))
                          )
                        }
                      />
                    </label>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: "0.45rem" }}>
                    {criteria.map((crit) => {
                      const cell = opt.cells.find((x) => x.criterion_id === crit.criterion_id);
                      const rawVal = cell?.value == null ? "" : String(cell.value);
                      return (
                        <div key={crit.criterion_id} style={{ background: "#f8fafc", padding: "0.4rem", borderRadius: "4px", fontSize: "0.82rem" }}>
                          <div style={{ fontWeight: 600 }}>{crit.label} ({crit.target_unit})</div>
                          <div style={{ display: "flex", gap: "0.25rem", marginTop: "0.2rem" }}>
                            <input
                              type="text"
                              placeholder="not provided"
                              value={rawVal}
                              onChange={(e) => updateCell(oIdx, crit.criterion_id, "value", e.target.value)}
                            />
                            <input
                              type="text"
                              style={{ width: "68px" }}
                              placeholder={crit.target_unit}
                              value={cell?.unit ?? crit.target_unit}
                              onChange={(e) => updateCell(oIdx, crit.criterion_id, "unit", e.target.value)}
                            />
                          </div>
                          <input
                            type="text"
                            style={{ width: "100%", marginTop: "0.2rem" }}
                            placeholder="Source ref"
                            value={cell?.source_ref ?? ""}
                            onChange={(e) => updateCell(oIdx, crit.criterion_id, "source_ref", e.target.value)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button type="submit" className="btn" disabled={running || !projectId || !weightsValid}>
            {running ? t.evaluatingBtn : t.evaluateBtn}
          </button>
        </form>
      </section>

      {/* Saved list */}
      <section className="panel">
        <h3>{t.savedListTitle}</h3>
        {savedList.length === 0 ? (
          <p style={{ color: "#64748b" }}>{t.emptySaved}</p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            {savedList.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`btn ${selectedDetail?.id === item.id ? "" : "btn-secondary"}`}
                onClick={() => void handleSelectComparison(item.id)}
              >
                {item.title} (v{item.version} · {item.owner_decision_status === "owner_selected" ? item.owner_selected_option_id : "Pending"})
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Detailed Matrix Output & Owner Decision Gate */}
      {selectedDetail && (
        <section className="panel" style={{ display: "grid", gap: "1rem" }}>
          <div style={{ borderBottom: "2px solid #1e3a5f", paddingBottom: "0.65rem" }}>
            <h3 style={{ margin: 0 }}>{selectedDetail.title}</h3>
            <div style={{ fontSize: "0.85rem", color: "#475569", marginTop: "0.25rem" }}>
              [{selectedDetail.project_code}] {selectedDetail.project_name} · {selectedDetail.comparison_scope} · v{selectedDetail.version} (Export v{selectedDetail.export_version}) · {selectedDetail.classification}
            </div>
            <div style={{ marginTop: "0.45rem", padding: "0.45rem 0.7rem", background: "#fff7ed", border: "1px solid #fdba74", color: "#9a3412", borderRadius: "4px", fontWeight: 700 }}>
              {t.advisoryBannerPrefix}: {selectedDetail.matrix.advisory_notice}
            </div>
            <div style={{ marginTop: "0.4rem", display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
              <span
                style={{
                  padding: "0.2rem 0.55rem",
                  borderRadius: "4px",
                  fontSize: "0.82rem",
                  fontWeight: 700,
                  background:
                    selectedDetail.ai_draft_status === "unverified_ai_draft"
                      ? "#fee2e2"
                      : selectedDetail.ai_draft_status === "owner_approved"
                      ? "#dcfce7"
                      : "#e2e8f0",
                  color:
                    selectedDetail.ai_draft_status === "unverified_ai_draft"
                      ? "#991b1b"
                      : selectedDetail.ai_draft_status === "owner_approved"
                      ? "#166534"
                      : "#1e293b",
                }}
              >
                {selectedDetail.ai_draft_label}
              </span>
              {selectedDetail.owner_decision_status === "owner_selected" && (
                <span style={{ padding: "0.2rem 0.55rem", borderRadius: "4px", background: "#dcfce7", color: "#166534", fontWeight: 700, fontSize: "0.82rem" }}>
                  {t.decisionDoneLabel}: {selectedDetail.owner_selected_option_id} ({selectedDetail.owner_decided_by})
                </span>
              )}
            </div>
            {selectedDetail.summary && <p style={{ margin: "0.5rem 0 0 0" }}>{selectedDetail.summary}</p>}
          </div>

          {/* Ranking table */}
          <div>
            <h4>{t.rankingTitle}</h4>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Option</th>
                    <th>Vendor / Source</th>
                    <th>Weighted Score (/100)</th>
                    <th>Mandatory Gate</th>
                    <th>Missing</th>
                    <th>Unit Mismatches</th>
                    <th>Risks</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedDetail.matrix.options.map((opt) => (
                    <tr key={opt.option_id}>
                      <td>#{opt.advisory_rank}</td>
                      <td>
                        <strong>[{opt.option_id}] {opt.name}</strong>
                      </td>
                      <td>{opt.vendor_or_source || t.notProvidedBadge}</td>
                      <td>
                        <strong>{opt.total_weighted_score.toFixed(4)}</strong>
                      </td>
                      <td>
                        <span
                          style={{
                            padding: "0.15rem 0.45rem",
                            borderRadius: "4px",
                            fontWeight: 700,
                            background: opt.mandatory_passed ? "#dcfce7" : "#fee2e2",
                            color: opt.mandatory_passed ? "#166534" : "#991b1b",
                          }}
                        >
                          {opt.mandatory_passed ? t.passBadge : `${t.failBadge} (${opt.failed_mandatory_criteria.join(", ")})`}
                        </span>
                      </td>
                      <td>{opt.missing_values_count}</td>
                      <td>{opt.unit_mismatch_count}</td>
                      <td>{opt.risks.length > 0 ? opt.risks.join("; ") : t.notProvidedBadge}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Matrix table */}
          <div>
            <h4>{t.matrixTitle}</h4>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Criterion</th>
                    <th>Weight</th>
                    <th>Unit</th>
                    {selectedDetail.matrix.options.map((opt) => (
                      <th key={opt.option_id}>[{opt.option_id}] {opt.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {selectedDetail.criteria.map((crit) => (
                    <tr key={crit.criterion_id}>
                      <td>
                        <strong>{crit.label}</strong> ({crit.category})
                        {crit.is_mandatory && (
                          <span style={{ marginInlineStart: "0.35rem", fontSize: "0.75rem", padding: "0.1rem 0.35rem", background: "#1e3a5f", color: "#fff", borderRadius: "3px" }}>
                            {t.mandatoryBadge}
                          </span>
                        )}
                        <div style={{ fontSize: "0.75rem", color: "#475569" }}>
                          [{crit.source_kind}] {crit.source_ref}
                        </div>
                      </td>
                      <td>{Number(crit.weight).toFixed(2)}%</td>
                      <td>{crit.target_unit}</td>
                      {selectedDetail.matrix.options.map((opt) => {
                        const c = opt.cells.find((x) => x.criterion_id === crit.criterion_id);
                        if (!c) {
                          return <td key={opt.option_id}>{t.notProvidedBadge}</td>;
                        }
                        return (
                          <td
                            key={opt.option_id}
                            style={{
                              background:
                                c.unit_status === "flagged_mismatch"
                                  ? "#fee2e2"
                                  : c.is_missing
                                  ? "#fef3c7"
                                  : undefined,
                            }}
                          >
                            <div>
                              <strong>{c.display_value} {c.raw_unit}</strong>
                              {c.unit_status === "converted_explicitly" && c.converted_value && (
                                <span style={{ fontSize: "0.78rem", color: "#0369a1", marginInlineStart: "0.25rem" }}>
                                  ({t.convertedBadge}: {c.converted_value} {c.target_unit})
                                </span>
                              )}
                              {c.unit_status === "flagged_mismatch" && (
                                <span style={{ fontSize: "0.78rem", color: "#991b1b", fontWeight: 700, marginInlineStart: "0.25rem" }}>
                                  [{t.mismatchBadge}]
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: "0.78rem", color: "#334155" }}>
                              Norm: {c.normalized_score.toFixed(2)} · Wt: {c.weighted_score.toFixed(4)}
                            </div>
                            <div style={{ fontSize: "0.73rem", color: "#64748b" }}>
                              [{c.source_kind}] {c.source_ref}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Flags */}
          {(selectedDetail.matrix.unit_mismatch_flags.length > 0 ||
            selectedDetail.matrix.missing_mandatory_flags.length > 0) && (
            <div className="status-box status-err">
              <strong>{t.flagsTitle}</strong>
              <ul style={{ margin: "0.35rem 0 0 1.1rem" }}>
                {selectedDetail.matrix.unit_mismatch_flags.map((fl, i) => (
                  <li key={"um_" + i}>{fl}</li>
                ))}
                {selectedDetail.matrix.missing_mandatory_flags.map((fl, i) => (
                  <li key={"mm_" + i}>{fl}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Owner Decision Form */}
          <form onSubmit={(e) => void handleDecide(e)} style={{ border: "1px solid #94a3b8", borderRadius: "6px", padding: "0.75rem", display: "grid", gap: "0.55rem" }}>
            <h4 style={{ margin: 0 }}>{t.decisionTitle}</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0.5rem" }}>
              <label>
                {t.selectedOptLabel}
                <select value={decisionOptId} onChange={(e) => setDecisionOptId(e.target.value)} required>
                  {selectedDetail.matrix.options.map((opt) => (
                    <option key={opt.option_id} value={opt.option_id}>
                      #{opt.advisory_rank} — [{opt.option_id}] {opt.name} ({opt.total_weighted_score.toFixed(2)} pts)
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t.decidedByLabel}
                <input type="text" value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)} required />
              </label>
            </div>
            <label>
              {t.decisionNoteLabel}
              <textarea rows={2} value={decisionNote} onChange={(e) => setDecisionNote(e.target.value)} required />
            </label>
            {selectedDetail.ai_draft_status === "unverified_ai_draft" && (
              <label style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <input type="checkbox" checked={approveAiDraft} onChange={(e) => setApproveAiDraft(e.target.checked)} />
                {t.approveAiCheck}
              </label>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              <button type="submit" className="btn" disabled={deciding}>
                {t.saveDecisionBtn}
              </button>
              <button type="button" className="btn btn-secondary" disabled={exporting} onClick={() => void handleExport("ar")}>
                {t.exportArBtn}
              </button>
              <button type="button" className="btn btn-secondary" disabled={exporting} onClick={() => void handleExport("en")}>
                {t.exportEnBtn}
              </button>
            </div>
          </form>

          {/* Versioned SHA-256 deliverables */}
          <div>
            <h4>{t.deliverablesTitle}</h4>
            {selectedDetail.deliverables.length > 0 && (
              <ul>
                {selectedDetail.deliverables.map((d) => (
                  <li key={d.id}>
                    <a href={getDeliverableDownloadUrl(d.id)} target="_blank" rel="noreferrer">
                      {d.filename} ({d.format.toUpperCase()})
                    </a>{" "}
                    — <code>sha256:{(d.sha256 ?? "").slice(0, 12)}...</code>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
