import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  approveScheduleDraft,
  createProjectSchedule,
  exportScheduleDeliverables,
  getDeliverableDownloadUrl,
  getScheduleDetail,
  listPlanningPresets,
  listProjectBoqSheets,
  listProjectCalculations,
  listProjectSchedules,
  listProjectSpecifications,
  listProjects,
  listResearchSources,
  listTasks,
  setScheduleAsBaseline,
} from "../api";
import type {
  BoqSheetSummaryOut,
  CalculationSummaryOut,
  CalendarPresetKey,
  Lang,
  PlanningPresetOut,
  ProjectClassification,
  ProjectScheduleDetailOut,
  ProjectScheduleSummaryOut,
  ProjectSummary,
  ReportLanguage,
  ResearchSourceOut,
  ScheduleActivityIn,
  ScheduleSourceKind,
  SpecificationSummaryOut,
  TaskSummaryOut,
  WbsItemIn,
} from "../types";

const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const SOURCE_KINDS: ScheduleSourceKind[] = [
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
    presetLabel: string;
    loadPresetBtn: string;
    projectLabel: string;
    taskLabel: string;
    noTask: string;
    baselineCompareLabel: string;
    noBaselineOpt: string;
    titleLabel: string;
    startDateLabel: string;
    calendarPresetLabel: string;
    holidaysLabel: string;
    hoursPerDayLabel: string;
    setBaselineCheck: string;
    useAiLabel: string;
    aiNotice: string;
    refsHeading: string;
    wbsTitle: string;
    addWbsBtn: string;
    activitiesTitle: string;
    addActBtn: string;
    submitBtn: string;
    submittingBtn: string;
    savedHeading: string;
    emptySaved: string;
    ganttTitle: string;
    wbsTableTitle: string;
    flagsTitle: string;
    approveBtn: string;
    setAsBaselineBtn: string;
    exportArBtn: string;
    exportEnBtn: string;
    deliverablesTitle: string;
    criticalBadge: string;
    blockedBadge: string;
    baselineBadge: string;
  }
> = {
  ar: {
    heading: "التخطيط والجدولة الزمنية (Step 16 — WBS, CPM, Gantt & Libya Calendar)",
    subtitle:
      "بناء هيكل تجزئة العمل (WBS) وحساب المسار الحرج (CPM Forward/Backward Pass) وتواريخ العمل بتقويم ليبيا (عطلة الجمعة والسبت) بدون اختلاق معدلات إنتاجية — أي مدة غير مزودة تُعرض كـ 'not provided' وتوقف المسار الحرج لفرعها.",
    presetLabel: "نموذج جدولة تمثيلي للعيادة (بيانات افتراضية — عطلة الجمعة والسبت):",
    loadPresetBtn: "تحميل النموذج",
    projectLabel: "المشروع",
    taskLabel: "المهمة المرتبطة (اختياري)",
    noTask: "— جدول عام للمشروع —",
    baselineCompareLabel: "مقارنة بالجدول المرجعي (Baseline)",
    noBaselineOpt: "— بدون مقارنة مرجعية —",
    titleLabel: "عنوان الجدول الزمني",
    startDateLabel: "تاريخ بداية المشروع",
    calendarPresetLabel: "التقويم المعتمد",
    holidaysLabel: "عطل رسمية مضافة من المالك (YYYY-MM-DD مفصولة بفاصلة)",
    hoursPerDayLabel: "ساعات العمل اليومية",
    setBaselineCheck: "اعتماد هذا الإصدار كجدول مرجعي أساسي (Set as Baseline)",
    useAiLabel: "توليد ملخص تنفيذي اختياري بالذكاء الاصطناعي (موسوم UNVERIFIED AI DRAFT حتى اعتماد المالك)",
    aiNotice:
      "0 توكن ذكاء اصطناعي افتراضياً؛ الذكاء الاصطناعي لا يحسب تواريخ أو مدد أو مسار حرج مطلقاً.",
    refsHeading: "مصادر المشروع المتاحة للإسناد",
    wbsTitle: "1. هيكل تجزئة العمل (WBS)",
    addWbsBtn: "+ إضافة عنصر WBS",
    activitiesTitle: "2. الأنشطة والمعالم والاعتماديات (FS + Lag) والمصادر",
    addActBtn: "+ إضافة نشاط",
    submitBtn: "حساب المسار الحرج وتصدير (Gantt PDF + Live XLSX)",
    submittingBtn: "جاري الحساب والتصدير...",
    savedHeading: "الجداول الزمنية المحفوظة للمشروع",
    emptySaved: "لا توجد جداول زمنية محفوظة لهذا المشروع بعد.",
    ganttTitle: "مخطط جانت التفاعلي والمسار الحرج (Visual Gantt Chart)",
    wbsTableTitle: "جدول CPM المفصل، الفائض الكلي (Float)، والانحراف عن المرجع (Baseline Variance)",
    flagsTitle: "تنبيهات المدد غير المزودة والفروع المتوقفة",
    approveBtn: "اعتماد المالك لمسودة الذكاء الاصطناعي",
    setAsBaselineBtn: "تثبيت كجدول مرجعي (Baseline)",
    exportArBtn: "تصدير Gantt PDF + XLSX (عربي RTL)",
    exportEnBtn: "تصدير Gantt PDF + XLSX (إنجليزي LTR)",
    deliverablesTitle: "الملفات المصدرة الموثقة بـ SHA-256 (مجلد 03_Analysis)",
    criticalBadge: "حرج (CRITICAL)",
    blockedBadge: "متوقف (not provided)",
    baselineBadge: "مرجعي (BASELINE)",
  },
  en: {
    heading: "Project Planning, WBS, CPM & Gantt (Step 16)",
    subtitle:
      "Deterministic Critical Path Method (forward/backward pass, float, FS dependencies + lag) grounded in real project BOQs/Specs/Calcs/Sources with configurable Libya Sun-Thu calendar (Fri-Sat weekend). Missing durations display 'not provided' and block that branch cleanly.",
    presetLabel: "Synthetic Clinic Renovation Schedule Fixture (0% client data, Libya calendar):",
    loadPresetBtn: "Load Fixture",
    projectLabel: "Project",
    taskLabel: "Linked Task (Optional)",
    noTask: "— Project-level schedule —",
    baselineCompareLabel: "Compare Against Baseline",
    noBaselineOpt: "— No baseline comparison —",
    titleLabel: "Schedule Title",
    startDateLabel: "Project Start Date",
    calendarPresetLabel: "Working Calendar Preset",
    holidaysLabel: "Owner-Supplied Holidays (comma-separated YYYY-MM-DD, never invented)",
    hoursPerDayLabel: "Hours / Workday",
    setBaselineCheck: "Set this schedule as active Project Baseline",
    useAiLabel: "Optional Gemini narrative summary (tagged UNVERIFIED AI DRAFT until owner approval)",
    aiNotice: "0 AI tokens by default; Gemini never computes dates, floats, or critical paths.",
    refsHeading: "Project Grounding Entities Available",
    wbsTitle: "1. Work Breakdown Structure (WBS)",
    addWbsBtn: "+ Add WBS Node",
    activitiesTitle: "2. Activities, Milestones, FS Dependencies & Provenance",
    addActBtn: "+ Add Activity",
    submitBtn: "Compute CPM Schedule & Export (Gantt PDF + Live XLSX)",
    submittingBtn: "Computing & Exporting...",
    savedHeading: "Saved Project Schedules",
    emptySaved: "No project schedules saved yet.",
    ganttTitle: "Interactive Gantt Chart & Critical Path Bar Timeline",
    wbsTableTitle: "CPM Dates, Total Float, Baseline Variance & Source Attribution",
    flagsTitle: "Missing Duration ('not provided') & Blocked Branch Flags",
    approveBtn: "Owner Approve AI Draft Summary",
    setAsBaselineBtn: "Lock as Project Baseline",
    exportArBtn: "Export Arabic RTL (PDF+XLSX)",
    exportEnBtn: "Export English LTR (PDF+XLSX)",
    deliverablesTitle: "Immutable SHA-256 Deliverables (03_Analysis)",
    criticalBadge: "CRITICAL",
    blockedBadge: "BLOCKED ('not provided')",
    baselineBadge: "BASELINE",
  },
};

function formatPredecessorsInput(preds: ScheduleActivityIn["predecessors"]): string {
  return preds
    .map((p) => (p.lag_days ? `${p.predecessor_id}:${p.lag_days}` : p.predecessor_id))
    .join(", ");
}

function parsePredecessorsInput(raw: string): ScheduleActivityIn["predecessors"] {
  return raw
    .split(",")
    .map((tok) => tok.trim())
    .filter(Boolean)
    .map((tok) => {
      const [idPart, lagPart] = tok.split(":");
      const lag = lagPart !== undefined && Number.isFinite(Number(lagPart)) ? parseInt(lagPart, 10) : 0;
      return { predecessor_id: idPart.trim(), dep_type: "FS" as const, lag_days: lag };
    })
    .filter((d) => d.predecessor_id.length > 0);
}

interface ProjectPlanningViewProps {
  lang: Lang;
  initialPresets?: PlanningPresetOut[];
  initialSchedules?: ProjectScheduleSummaryOut[];
  initialSelectedSchedule?: ProjectScheduleDetailOut | null;
}

export function ProjectPlanningView({
  lang,
  initialPresets,
  initialSchedules,
  initialSelectedSchedule = null,
}: ProjectPlanningViewProps) {
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
  const [presets, setPresets] = useState<PlanningPresetOut[]>(initialPresets ?? []);
  const [savedList, setSavedList] = useState<ProjectScheduleSummaryOut[]>(initialSchedules ?? []);
  const [selectedDetail, setSelectedDetail] = useState<ProjectScheduleDetailOut | null>(
    initialSelectedSchedule
  );

  const [baselineId, setBaselineId] = useState<string>("");
  const [title, setTitle] = useState<string>("");
  const [discipline, setDiscipline] = useState<string>("multidisciplinary");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [outLang, setOutLang] = useState<ReportLanguage>(lang);
  const [startDate, setStartDate] = useState<string>("2026-11-22");
  const [calPreset, setCalPreset] = useState<CalendarPresetKey>("libya_sun_thu");
  const [holidaysRaw, setHolidaysRaw] = useState<string>("");
  const [hoursPerDay, setHoursPerDay] = useState<string>("8");
  const [setAsBaseline, setSetAsBaseline] = useState<boolean>(false);
  const [useAi, setUseAi] = useState<boolean>(false);
  const [approvedBy, setApprovedBy] = useState<string>("Owner / Project Manager");

  const [wbsItems, setWbsItems] = useState<WbsItemIn[]>([
    { wbs_code: "1", title: "Master Project WBS", discipline: "multidisciplinary" },
    { wbs_code: "1.1", title: "Site & Substructure", parent_code: "1", discipline: "civil" },
  ]);

  const [activities, setActivities] = useState<ScheduleActivityIn[]>([
    {
      activity_id: "M0",
      wbs_code: "1",
      name: "Site Mobilization Kickoff",
      is_milestone: true,
      duration_days: 0,
      predecessors: [],
      source_kind: "owner_entered",
      source_ref: "Owner kickoff notice",
    },
    {
      activity_id: "A1",
      wbs_code: "1.1",
      name: "Foundation Works",
      is_milestone: false,
      duration_days: 5,
      predecessors: [{ predecessor_id: "M0", dep_type: "FS", lag_days: 0 }],
      source_kind: "owner_entered",
      source_ref: "Owner contractor schedule estimate",
    },
  ]);

  const [running, setRunning] = useState<boolean>(false);
  const [exporting, setExporting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  useEffect(() => {
    setOutLang(lang);
  }, [lang]);

  useEffect(() => {
    if (!initialPresets) {
      listPlanningPresets()
        .then((res) => setPresets(res.presets))
        .catch(() => {});
    }
    listProjects()
      .then((res) => {
        setProjects(res.projects);
        if (res.projects.length > 0) {
          setProjectId((prev) => prev || res.projects[0].id);
        }
      })
      .catch(() => {});
  }, [initialPresets]);

  const refreshProjectContext = useCallback(async (pid: string) => {
    if (!pid) return;
    try {
      const [taskRes, boqRes, specRes, calcRes, srcRes, schRes] = await Promise.all([
        listTasks({ projectId: pid }),
        listProjectBoqSheets(pid),
        listProjectSpecifications(pid),
        listProjectCalculations(pid),
        listResearchSources({ project_id: pid, reviewed_only: true }),
        listProjectSchedules(pid),
      ]);
      setTasks(taskRes.tasks);
      setBoqSheets(boqRes.sheets);
      setSpecs(specRes.specifications);
      setCalcs(calcRes.calculations);
      setSources(srcRes.sources);
      setSavedList(schRes.schedules);
      const base = schRes.schedules.find((s) => s.is_baseline);
      if (base) {
        setBaselineId((prev) => prev || base.id);
      }
    } catch {
      // Safe offline fallback during tests
    }
  }, []);

  useEffect(() => {
    if (projectId && !initialSchedules) {
      void refreshProjectContext(projectId);
    }
  }, [projectId, initialSchedules, refreshProjectContext]);

  function applyPreset(preset: PlanningPresetOut) {
    setTitle(lang === "ar" ? preset.title_ar : preset.title_en);
    setDiscipline(preset.discipline);
    setStartDate(preset.start_date);
    setCalPreset(preset.calendar.preset);
    setHolidaysRaw(preset.calendar.holidays.join(", "));
    setHoursPerDay(String(preset.calendar.hours_per_day));
    setWbsItems(preset.wbs_items.map((w) => ({ ...w })));
    setActivities(preset.activities.map((a) => ({ ...a, predecessors: [...a.predecessors] })));
    setStatusMsg(`${t.loadPresetBtn}: ${lang === "ar" ? preset.title_ar : preset.title_en}`);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!projectId) return;
    setRunning(true);
    setError(null);
    setStatusMsg(null);
    try {
      const holidays = holidaysRaw
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
      const created = await createProjectSchedule(projectId, {
        task_id: taskId || null,
        title: title.trim() || null,
        discipline: discipline.trim() || "multidisciplinary",
        language: outLang,
        classification,
        start_date: startDate,
        calendar: {
          preset: calPreset,
          holidays,
          hours_per_day: Number(hoursPerDay) || 8,
          source_ref: `Owner-selected calendar preset (${calPreset})`,
        },
        wbs_items: wbsItems,
        activities,
        baseline_schedule_id: baselineId || null,
        set_as_baseline: setAsBaseline,
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

  async function handleSelectSchedule(schedId: string) {
    setError(null);
    try {
      const detail = await getScheduleDetail(schedId);
      setSelectedDetail(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSetBaseline() {
    if (!selectedDetail) return;
    setError(null);
    try {
      const updated = await setScheduleAsBaseline(selectedDetail.id);
      setSelectedDetail(updated);
      setBaselineId(updated.id);
      if (projectId) await refreshProjectContext(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleApproveAi() {
    if (!selectedDetail) return;
    setError(null);
    try {
      const approved = await approveScheduleDraft(selectedDetail.id, {
        approved_by: approvedBy.trim() || "Owner",
        export_after_approval: true,
      });
      setSelectedDetail(approved);
      if (projectId) await refreshProjectContext(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleExport(targetLang: ReportLanguage) {
    if (!selectedDetail) return;
    setExporting(true);
    setError(null);
    try {
      const res = await exportScheduleDeliverables(selectedDetail.id, { language: targetLang });
      setSelectedDetail(res.schedule);
      setStatusMsg(`Export v${res.schedule.export_version}: ${res.pdf_deliverable.filename}, ${res.xlsx_deliverable.filename}`);
      if (projectId) await refreshProjectContext(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  }

  const ganttSpan = useMemo(() => {
    if (!selectedDetail) return 1;
    const maxEf = selectedDetail.schedule_result.activities.reduce(
      (acc, a) => Math.max(acc, a.early_finish_wd ?? 0),
      1
    );
    return Math.max(1, maxEf);
  }, [selectedDetail]);

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
          <div style={{ marginBottom: "0.9rem", padding: "0.7rem", background: "#f8fafc", border: "1px solid #cbd5e1", borderRadius: "6px" }}>
            <strong style={{ display: "block", marginBottom: "0.4rem", fontSize: "0.9rem" }}>{t.presetLabel}</strong>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              {presets.map((p) => (
                <button key={p.key} type="button" className="btn btn-secondary" onClick={() => applyPreset(p)}>
                  {t.loadPresetBtn}: {lang === "ar" ? p.title_ar : p.title_en}
                </button>
              ))}
            </div>
          </div>
        )}

        <form onSubmit={(e) => void handleSubmit(e)} style={{ display: "grid", gap: "0.85rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(205px, 1fr))", gap: "0.65rem" }}>
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
                    {tk.title}
                  </option>
                ))}
              </select>
            </label>

            <label>
              {t.baselineCompareLabel}
              <select value={baselineId} onChange={(e) => setBaselineId(e.target.value)}>
                <option value="">{t.noBaselineOpt}</option>
                {savedList.map((s) => (
                  <option key={s.id} value={s.id}>
                    v{s.version}: {s.title} {s.is_baseline ? "(BASELINE)" : ""}
                  </option>
                ))}
              </select>
            </label>

            <label>
              {t.titleLabel}
              <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Master Construction Schedule" />
            </label>

            <label>
              {t.startDateLabel}
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required />
            </label>

            <label>
              {t.calendarPresetLabel}
              <select value={calPreset} onChange={(e) => setCalPreset(e.target.value as CalendarPresetKey)}>
                <option value="libya_sun_thu">Libya Sun–Thu (Fri & Sat Weekend)</option>
                <option value="mon_fri">Mon–Fri (Sat & Sun Weekend)</option>
                <option value="six_day_sat_thu">6-Day Sat–Thu (Fri Weekend only)</option>
              </select>
            </label>

            <label>
              {t.hoursPerDayLabel}
              <input type="number" step="0.5" min="1" max="24" value={hoursPerDay} onChange={(e) => setHoursPerDay(e.target.value)} />
            </label>

            <label>
              Classification
              <select value={classification} onChange={(e) => setClassification(e.target.value as ProjectClassification)}>
                {CLASSIFICATIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0.65rem" }}>
            <label>
              {t.holidaysLabel}
              <input
                type="text"
                value={holidaysRaw}
                onChange={(e) => setHolidaysRaw(e.target.value)}
                placeholder="e.g. 2026-12-24"
              />
            </label>
            <label>
              Export Language
              <select value={outLang} onChange={(e) => setOutLang(e.target.value as ReportLanguage)}>
                <option value="ar">العربية (RTL)</option>
                <option value="en">English (LTR)</option>
              </select>
            </label>
          </div>

          <div style={{ fontSize: "0.85rem", color: "#334155", background: "#f1f5f9", padding: "0.45rem 0.7rem", borderRadius: "4px" }}>
            <strong>{t.refsHeading}:</strong> BOQ ({boqSheets.length}) · Specs ({specs.length}) · Calcs ({calcs.length}) · Reviewed Sources ({sources.length})
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <input type="checkbox" checked={setAsBaseline} onChange={(e) => setSetAsBaseline(e.target.checked)} />
              {t.setBaselineCheck}
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
              {t.useAiLabel}
            </label>
          </div>
          <div style={{ fontSize: "0.83rem", color: "#9a3412", fontWeight: 600 }}>{t.aiNotice}</div>

          {/* WBS items */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.35rem" }}>
              <strong>{t.wbsTitle}</strong>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  setWbsItems((prev) => [
                    ...prev,
                    { wbs_code: `1.${prev.length}`, title: `WBS Element ${prev.length}`, parent_code: "1", discipline },
                  ])
                }
              >
                {t.addWbsBtn}
              </button>
            </div>
            <table>
              <thead>
                <tr>
                  <th>WBS Code</th>
                  <th>Title</th>
                  <th>Parent</th>
                  <th>Discipline</th>
                </tr>
              </thead>
              <tbody>
                {wbsItems.map((w, i) => (
                  <tr key={i}>
                    <td>
                      <input
                        type="text"
                        style={{ width: "80px" }}
                        value={w.wbs_code}
                        onChange={(e) =>
                          setWbsItems((prev) => prev.map((x, idx) => (idx === i ? { ...x, wbs_code: e.target.value } : x)))
                        }
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={w.title}
                        onChange={(e) =>
                          setWbsItems((prev) => prev.map((x, idx) => (idx === i ? { ...x, title: e.target.value } : x)))
                        }
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        style={{ width: "80px" }}
                        value={w.parent_code ?? ""}
                        onChange={(e) =>
                          setWbsItems((prev) =>
                            prev.map((x, idx) => (idx === i ? { ...x, parent_code: e.target.value || null } : x))
                          )
                        }
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={w.discipline}
                        onChange={(e) =>
                          setWbsItems((prev) => prev.map((x, idx) => (idx === i ? { ...x, discipline: e.target.value } : x)))
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Activities */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.35rem" }}>
              <strong>{t.activitiesTitle}</strong>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  setActivities((prev) => [
                    ...prev,
                    {
                      activity_id: `A${prev.length + 1}`,
                      wbs_code: wbsItems[0]?.wbs_code ?? "1",
                      name: `Activity ${prev.length + 1}`,
                      is_milestone: false,
                      duration_days: null,
                      predecessors: [],
                      source_kind: "owner_entered",
                      source_ref: "Owner input pending duration",
                    },
                  ])
                }
              >
                {t.addActBtn}
              </button>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>WBS</th>
                    <th>Activity</th>
                    <th>Milestone</th>
                    <th>Duration (wd, blank='not provided')</th>
                    <th>Predecessors (A1, A2:1)</th>
                    <th>Source Kind / Ref</th>
                  </tr>
                </thead>
                <tbody>
                  {activities.map((a, idx) => (
                    <tr key={idx}>
                      <td>
                        <input
                          type="text"
                          style={{ width: "65px" }}
                          value={a.activity_id}
                          onChange={(e) =>
                            setActivities((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, activity_id: e.target.value } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          style={{ width: "65px" }}
                          value={a.wbs_code}
                          onChange={(e) =>
                            setActivities((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, wbs_code: e.target.value } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={a.name}
                          onChange={(e) =>
                            setActivities((prev) =>
                              prev.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x))
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={a.is_milestone}
                          onChange={(e) =>
                            setActivities((prev) =>
                              prev.map((x, i) =>
                                i === idx
                                  ? { ...x, is_milestone: e.target.checked, duration_days: e.target.checked ? 0 : x.duration_days }
                                  : x
                              )
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          style={{ width: "90px" }}
                          placeholder="not provided"
                          value={a.duration_days == null ? "" : String(a.duration_days)}
                          onChange={(e) => {
                            const raw = e.target.value.trim();
                            setActivities((prev) =>
                              prev.map((x, i) =>
                                i === idx ? { ...x, duration_days: raw === "" ? null : parseInt(raw, 10) } : x
                              )
                            );
                          }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          placeholder="e.g. A1, A2:1"
                          value={formatPredecessorsInput(a.predecessors)}
                          onChange={(e) =>
                            setActivities((prev) =>
                              prev.map((x, i) =>
                                i === idx ? { ...x, predecessors: parsePredecessorsInput(e.target.value) } : x
                              )
                            )
                          }
                        />
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: "0.25rem" }}>
                          <select
                            value={a.source_kind}
                            onChange={(e) =>
                              setActivities((prev) =>
                                prev.map((x, i) =>
                                  i === idx ? { ...x, source_kind: e.target.value as ScheduleSourceKind } : x
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
                            value={a.source_ref}
                            onChange={(e) =>
                              setActivities((prev) =>
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

          <button type="submit" className="btn" disabled={running || !projectId}>
            {running ? t.submittingBtn : t.submitBtn}
          </button>
        </form>
      </section>

      {/* Saved list */}
      <section className="panel">
        <h3>{t.savedHeading}</h3>
        {savedList.length === 0 ? (
          <p style={{ color: "#64748b" }}>{t.emptySaved}</p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            {savedList.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`btn ${selectedDetail?.id === s.id ? "" : "btn-secondary"}`}
                onClick={() => void handleSelectSchedule(s.id)}
              >
                {s.title} (v{s.version} · {s.total_duration_wd != null ? `${s.total_duration_wd} wd` : "blocked"}
                {s.is_baseline ? " · BASELINE" : ""})
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Selected schedule inspector with visual Gantt chart */}
      {selectedDetail && (
        <section className="panel" style={{ display: "grid", gap: "1rem" }}>
          <div style={{ borderBottom: "2px solid #1e3a5f", paddingBottom: "0.6rem" }}>
            <h3 style={{ margin: 0 }}>{selectedDetail.title}</h3>
            <div style={{ fontSize: "0.85rem", color: "#475569", marginTop: "0.25rem" }}>
              [{selectedDetail.project_code}] {selectedDetail.project_name} · v{selectedDetail.version} (Export v{selectedDetail.export_version}) ·{" "}
              {selectedDetail.classification} · {selectedDetail.schedule_result.calendar_summary}
            </div>
            <div style={{ marginTop: "0.35rem", display: "flex", flexWrap: "wrap", gap: "0.45rem", alignItems: "center" }}>
              <span
                style={{
                  padding: "0.2rem 0.55rem",
                  borderRadius: "4px",
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  background: selectedDetail.ai_draft_status === "unverified_ai_draft" ? "#fee2e2" : "#e2e8f0",
                  color: selectedDetail.ai_draft_status === "unverified_ai_draft" ? "#991b1b" : "#1e293b",
                }}
              >
                {selectedDetail.ai_draft_label}
              </span>
              {selectedDetail.is_baseline && (
                <span style={{ padding: "0.2rem 0.55rem", borderRadius: "4px", background: "#dcfce7", color: "#166534", fontWeight: 700, fontSize: "0.8rem" }}>
                  {t.baselineBadge}
                </span>
              )}
              <span>
                Effective: <strong>{selectedDetail.schedule_result.effective_start_date}</strong> →{" "}
                <strong>{selectedDetail.schedule_result.project_finish_date ?? "not provided"}</strong> (
                {selectedDetail.schedule_result.total_duration_wd != null
                  ? `${selectedDetail.schedule_result.total_duration_wd} wd`
                  : "not provided / branch blocked"}
                )
              </span>
            </div>
            {selectedDetail.summary && <p style={{ margin: "0.45rem 0 0 0" }}>{selectedDetail.summary}</p>}
          </div>

          {/* Interactive Gantt Chart Bar Renderer */}
          <div>
            <h4>{t.ganttTitle}</h4>
            <div style={{ border: "1px solid #cbd5e1", borderRadius: "6px", padding: "0.65rem", background: "#f8fafc", display: "grid", gap: "0.4rem" }}>
              {selectedDetail.schedule_result.activities.map((act) => {
                const blocked = act.cpm_status !== "computed" || act.early_start_wd == null || act.early_finish_wd == null;
                const es = act.early_start_wd ?? 0;
                const ef = act.early_finish_wd ?? 0;
                const leftPct = (es / ganttSpan) * 100;
                const widthPct = Math.max(act.is_milestone ? 2 : 3, ((Math.max(0.5, ef - es)) / ganttSpan) * 100);
                const floatPct = !blocked && (act.total_float_wd ?? 0) > 0 ? ((act.total_float_wd ?? 0) / ganttSpan) * 100 : 0;

                return (
                  <div
                    key={act.activity_id}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "220px 105px 1fr",
                      gap: "0.5rem",
                      alignItems: "center",
                      fontSize: "0.82rem",
                    }}
                  >
                    <div>
                      <strong>[{act.activity_id}]</strong> {act.name}
                    </div>
                    <div style={{ color: "#475569" }}>
                      {act.display_duration}{act.duration_days != null ? " wd" : ""}
                    </div>
                    {blocked ? (
                      <div style={{ background: "#fef3c7", border: "1px dashed #d97706", color: "#92400e", padding: "0.2rem 0.5rem", borderRadius: "4px", fontWeight: 600 }}>
                        {t.blockedBadge}
                      </div>
                    ) : (
                      <div style={{ position: "relative", height: "22px", background: "#e2e8f0", borderRadius: "4px", direction: "ltr" }}>
                        {floatPct > 0 && (
                          <div
                            title={`Total Float: ${act.total_float_wd} wd`}
                            style={{
                              position: "absolute",
                              left: `${Math.min(100, leftPct + widthPct)}%`,
                              width: `${Math.min(100 - (leftPct + widthPct), floatPct)}%`,
                              top: "7px",
                              height: "8px",
                              background: "#93c5fd",
                              borderRadius: "2px",
                            }}
                          />
                        )}
                        <div
                          title={`${act.planned_start ?? ""} -> ${act.planned_finish ?? ""}`}
                          style={{
                            position: "absolute",
                            left: `${Math.min(98, leftPct)}%`,
                            width: `${Math.min(100 - Math.min(98, leftPct), widthPct)}%`,
                            top: "2px",
                            height: "18px",
                            background: act.is_milestone ? "#7c3aed" : act.is_critical ? "#dc2626" : "#2563eb",
                            color: "#ffffff",
                            fontSize: "0.7rem",
                            fontWeight: 700,
                            borderRadius: "3px",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            overflow: "hidden",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {act.is_milestone ? "◆" : act.is_critical ? `${act.duration_days}d CRIT` : `${act.duration_days}d`}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* CPM & Variance Table */}
          <div>
            <h4>{t.wbsTableTitle}</h4>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>ID / WBS</th>
                    <th>Activity</th>
                    <th>Dur (wd)</th>
                    <th>ES / EF</th>
                    <th>LS / LF</th>
                    <th>Float</th>
                    <th>Planned Start → Finish</th>
                    <th>Status</th>
                    <th>Baseline Var</th>
                    <th>Source Ref</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedDetail.schedule_result.activities.map((a) => (
                    <tr key={a.activity_id}>
                      <td>
                        <strong>{a.activity_id}</strong> ({a.wbs_code})
                      </td>
                      <td>{a.name}</td>
                      <td>{a.display_duration}</td>
                      <td>{a.early_start_wd != null ? `${a.early_start_wd} / ${a.early_finish_wd}` : "not provided"}</td>
                      <td>{a.late_start_wd != null ? `${a.late_start_wd} / ${a.late_finish_wd}` : "blocked"}</td>
                      <td>{a.total_float_wd != null ? `${a.total_float_wd} wd` : "blocked"}</td>
                      <td>{a.planned_start ? `${a.planned_start} → ${a.planned_finish}` : "not provided"}</td>
                      <td>
                        {a.is_critical ? (
                          <span style={{ color: "#991b1b", fontWeight: 700 }}>{t.criticalBadge}</span>
                        ) : a.cpm_status !== "computed" ? (
                          <span style={{ color: "#92400e", fontWeight: 700 }}>{t.blockedBadge}</span>
                        ) : (
                          "Normal"
                        )}
                      </td>
                      <td>
                        {a.finish_variance_wd != null
                          ? `${a.finish_variance_wd >= 0 ? "+" : ""}${a.finish_variance_wd} wd (${a.variance_status})`
                          : a.variance_status}
                      </td>
                      <td>[{a.source_kind}] {a.source_ref}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Flags */}
          {(selectedDetail.schedule_result.missing_duration_flags.length > 0 ||
            selectedDetail.schedule_result.blocked_branch_flags.length > 0) && (
            <div className="status-box status-err">
              <strong>{t.flagsTitle}</strong>
              <ul style={{ margin: "0.35rem 0 0 1.1rem" }}>
                {selectedDetail.schedule_result.missing_duration_flags.map((fl, i) => (
                  <li key={"md_" + i}>{fl}</li>
                ))}
                {selectedDetail.schedule_result.blocked_branch_flags.map((fl, i) => (
                  <li key={"bb_" + i}>{fl}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Actions & Exports */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
            {!selectedDetail.is_baseline && (
              <button type="button" className="btn btn-secondary" onClick={() => void handleSetBaseline()}>
                {t.setAsBaselineBtn}
              </button>
            )}
            {selectedDetail.ai_draft_status === "unverified_ai_draft" && (
              <>
                <input type="text" style={{ width: "170px" }} value={approvedBy} onChange={(e) => setApprovedBy(e.target.value)} />
                <button type="button" className="btn" onClick={() => void handleApproveAi()}>
                  {t.approveBtn}
                </button>
              </>
            )}
            <button type="button" className="btn btn-secondary" disabled={exporting} onClick={() => void handleExport("ar")}>
              {t.exportArBtn}
            </button>
            <button type="button" className="btn btn-secondary" disabled={exporting} onClick={() => void handleExport("en")}>
              {t.exportEnBtn}
            </button>
          </div>

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
