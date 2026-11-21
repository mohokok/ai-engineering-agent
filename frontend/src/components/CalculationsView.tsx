import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  createCalculation,
  exportCalculationDeliverables,
  getCalculationDetail,
  getDeliverableDownloadUrl,
  listCalculationPresets,
  listProjectCalculations,
  listProjects,
  listResearchSources,
  listTasks,
} from "../api";
import type {
  CalculationDetailOut,
  CalculationPresetOut,
  CalculationReferenceKind,
  CalculationSummaryOut,
  CalculationType,
  Lang,
  ProjectClassification,
  ProjectSummary,
  ReportLanguage,
  ResearchSourceOut,
  TaskSummaryOut,
} from "../types";

const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const CALC_TYPE_LABELS: Record<Lang, Record<CalculationType, string>> = {
  ar: {
    electrical_load_schedule: "كهرباء: جدول الأحمال الكهربائية (Load Schedule)",
    electrical_cable_sizing: "كهرباء: مقاس الكابلات (Cable Sizing)",
    electrical_voltage_drop: "كهرباء: هبوط الجهد (Voltage Drop)",
    plumbing_water_demand: "سباكة: استهلاك المياه والخزان (Water Demand)",
    plumbing_pipe_sizing: "سباكة: مقاسات المواسير (Pipe Sizing)",
  },
  en: {
    electrical_load_schedule: "Electrical: Panel Load Schedule",
    electrical_cable_sizing: "Electrical: Cable Sizing",
    electrical_voltage_drop: "Electrical: Voltage Drop Check",
    plumbing_water_demand: "Plumbing: Water Demand & Storage",
    plumbing_pipe_sizing: "Plumbing: Pipe Sizing (Darcy-Weisbach)",
  },
};

interface CalcCopy {
  heading: string;
  subtitle: string;
  projectLabel: string;
  taskLabel: string;
  noTaskOpt: string;
  calcTypeLabel: string;
  titleLabel: string;
  classLabel: string;
  langLabel: string;
  loadPresetBtn: string;
  inputsJsonLabel: string;
  refKindLabel: string;
  refOwnerOpt: string;
  refVerifiedOpt: string;
  refSourceSelectLabel: string;
  refNameLabel: string;
  refValueLabel: string;
  refCodeNotice: string;
  runBtn: string;
  runningBtn: string;
  exportBtn: string;
  exportingBtn: string;
  historyHeading: string;
  noCalcs: string;
  secInputs: string;
  secUnits: string;
  secEquations: string;
  secMethod: string;
  secAssumptions: string;
  secResults: string;
  secAcceptance: string;
  secReferences: string;
  secDeliverables: string;
  passBadge: string;
  failBadge: string;
  provenanceLabel: string;
  downloadLabel: string;
}

const COPY: Record<Lang, CalcCopy> = {
  ar: {
    heading: "إطار الحسابات الهندسية الحتمية — الكهرباء والسباكة (0 توكن)",
    subtitle:
      "مكتبة حسابات بايثون حتمية (دون أي حسابات من الذكاء الاصطناعي): جداول الأحمال، مقاسات الكابلات، هبوط الجهد، استهلاك المياه، ومقاسات المواسير. كل حساب يعرض المدخلات، الوحدات، المعادلات، المنهجية، الافتراضات، النتائج، معايير القبول، والمراجع المعتمدة موسومة بعبارة «verify against the locally adopted code».",
    projectLabel: "المشروع",
    taskLabel: "التكليف المرتبط (اختياري)",
    noTaskOpt: "عام للمشروع",
    calcTypeLabel: "نوع الحساب الهندسي",
    titleLabel: "عنوان الحساب",
    classLabel: "التصنيف",
    langLabel: "لغة التقرير",
    loadPresetBtn: "تحميل مثال نموذجي (بيانات اصطناعية)",
    inputsJsonLabel: "مدخلات الحساب (JSON حتمي)",
    refKindLabel: "نوع المرجع المعتمد",
    refOwnerOpt: "مرجع مقدم من المالك (owner_supplied)",
    refVerifiedOpt: "مصدر بحثي مراجَع في السجل (verified_source_log)",
    refSourceSelectLabel: "اختر مصدراً مراجَعاً",
    refNameLabel: "اسم المرجع / المعيار",
    refValueLabel: "مرجع الوثيقة / الرابط المراجع",
    refCodeNotice:
      "تنبيه المراجع: يُسمح فقط بمصادر المالك أو سجل البحث المراجَع مع الوسم الإلزامي (verify against the locally adopted code) دون اختراع بنود.",
    runBtn: "تنفيذ الحساب الحتمي وحفظه (0 توكن)",
    runningBtn: "جاري الحساب...",
    exportBtn: "تصدير التقرير والجدول (DOCX + PDF + XLSX)",
    exportingBtn: "جاري التصدير...",
    historyHeading: "الحسابات الهندسية المسجلة بالمشروع",
    noCalcs: "لا توجد حسابات مسجلة لهذا المشروع بعد.",
    secInputs: "1. المدخلات (Inputs)",
    secUnits: "2. الوحدات (Units)",
    secEquations: "3. المعادلات (Equations)",
    secMethod: "4. المنهجية (Method)",
    secAssumptions: "5. الافتراضات (Assumptions)",
    secResults: "6. النتائج المحسوبة (Results)",
    secAcceptance: "7. معايير القبول (Acceptance Criteria)",
    secReferences: "8. المراجع المعتمدة (References)",
    secDeliverables: "الملفات المُصدَّرة (04_Engineering_Calculations)",
    passBadge: "مقبول (PASS)",
    failBadge: "غير مقبول (FAIL)",
    provenanceLabel: "مصدر البيانات (Data Provenance)",
    downloadLabel: "تنزيل",
  },
  en: {
    heading: "Deterministic MEP Calculation Framework — Electrical & Plumbing (0 AI Tokens)",
    subtitle:
      "Pure Python engineering calculation library (zero AI arithmetic): load schedules, cable sizing, voltage drop, water demand, and pipe sizing. Every record shows inputs, units, equations, method, assumptions, results, acceptance criteria, and owner/verified-log references labelled 'verify against the locally adopted code'.",
    projectLabel: "Project",
    taskLabel: "Linked Task (optional)",
    noTaskOpt: "Project-wide",
    calcTypeLabel: "Calculation Type",
    titleLabel: "Calculation Title",
    classLabel: "Classification",
    langLabel: "Report Language",
    loadPresetBtn: "Load Synthetic Example",
    inputsJsonLabel: "Calculation Inputs (Deterministic JSON)",
    refKindLabel: "Reference Source Kind",
    refOwnerOpt: "Owner-Supplied Document (owner_supplied)",
    refVerifiedOpt: "Verified Research Log Source (verified_source_log)",
    refSourceSelectLabel: "Select Reviewed Source",
    refNameLabel: "Reference / Standard Name",
    refValueLabel: "Document Ref / Reviewed URL",
    refCodeNotice:
      "Standards guard: only owner-supplied or reviewed source-log references are accepted, always labelled 'verify against the locally adopted code' with zero fabricated clauses.",
    runBtn: "Run & Save Deterministic Calculation (0 AI Tokens)",
    runningBtn: "Computing...",
    exportBtn: "Export Report & Sheet (DOCX + PDF + XLSX)",
    exportingBtn: "Exporting...",
    historyHeading: "Project Calculations Register",
    noCalcs: "No calculations recorded for this project yet.",
    secInputs: "1. Inputs",
    secUnits: "2. Units",
    secEquations: "3. Equations",
    secMethod: "4. Method",
    secAssumptions: "5. Assumptions",
    secResults: "6. Results",
    secAcceptance: "7. Acceptance Criteria",
    secReferences: "8. References",
    secDeliverables: "Exported Deliverables (04_Engineering_Calculations)",
    passBadge: "PASS",
    failBadge: "FAIL",
    provenanceLabel: "Data Provenance",
    downloadLabel: "Download",
  },
};

export interface CalculationsViewProps {
  lang: Lang;
  initialCalculation?: CalculationDetailOut | null;
  initialCalculations?: CalculationSummaryOut[];
}

export function CalculationsView({
  lang,
  initialCalculation = null,
  initialCalculations,
}: CalculationsViewProps) {
  const copy = COPY[lang];
  const typeLabels = CALC_TYPE_LABELS[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState("");
  const [tasks, setTasks] = useState<TaskSummaryOut[]>([]);
  const [taskId, setTaskId] = useState("");
  const [reviewedSources, setReviewedSources] = useState<ResearchSourceOut[]>([]);
  const [presets, setPresets] = useState<CalculationPresetOut[]>([]);

  const [calcType, setCalcType] = useState<CalculationType>("electrical_load_schedule");
  const [title, setTitle] = useState("Synthetic Clinic Panel Load Schedule (MDB-CLINIC-01)");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [outLang, setOutLang] = useState<ReportLanguage>(lang);
  const [inputsText, setInputsText] = useState("{}");

  const [refKind, setRefKind] = useState<CalculationReferenceKind>("owner_supplied");
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [refName, setRefName] = useState("Synthetic Clinic Design Basis Brief");
  const [refValue, setRefValue] = useState("Owner Synthetic Design Basis Rev 01");

  const [calculations, setCalculations] = useState<CalculationSummaryOut[]>(
    initialCalculations ?? []
  );
  const [selectedCalc, setSelectedCalc] = useState<CalculationDetailOut | null>(
    initialCalculation
  );

  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const applyPreset = useCallback(
    (targetType: CalculationType, presetList: CalculationPresetOut[]) => {
      const found = presetList.find((p) => p.calculation_type === targetType);
      if (!found) return;
      setTitle(lang === "ar" ? found.title_ar : found.title_en);
      setInputsText(JSON.stringify(found.inputs, null, 2));
      setRefKind(found.default_reference.source_kind);
      setRefName(found.default_reference.source_name);
      setRefValue(found.default_reference.source_ref);
    },
    [lang]
  );

  const refreshProjectData = useCallback(async (pid: string) => {
    if (!pid) {
      setTasks([]);
      setReviewedSources([]);
      setCalculations([]);
      return;
    }
    try {
      const [taskRes, calcRes, srcRes] = await Promise.all([
        listTasks({ projectId: pid }),
        listProjectCalculations(pid),
        listResearchSources({ project_id: pid, reviewed_only: true }),
      ]);
      setTasks(taskRes.tasks);
      setCalculations(calcRes.calculations);
      setReviewedSources(
        srcRes.sources.filter(
          (s) => s.reviewed && (s.access_status === "accessible" || s.access_status === "owner_provided")
        )
      );
      if (calcRes.calculations.length > 0) {
        const detail = await getCalculationDetail(calcRes.calculations[0].id);
        setSelectedCalc(detail);
      } else {
        setSelectedCalc(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [projRes, presetRes] = await Promise.all([
          listProjects(),
          listCalculationPresets(),
        ]);
        setProjects(projRes.projects);
        setPresets(presetRes.presets);
        if (presetRes.presets.length > 0) {
          applyPreset("electrical_load_schedule", presetRes.presets);
        }
        if (projRes.projects.length > 0) {
          setProjectId((prev) => prev || projRes.projects[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [applyPreset]);

  useEffect(() => {
    if (projectId) {
      void refreshProjectData(projectId);
    }
  }, [projectId, refreshProjectData]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!projectId) return;
    setRunning(true);
    setError(null);
    setStatusMsg(null);
    try {
      const parsedInputs = JSON.parse(inputsText) as Record<string, unknown>;
      const refPayload =
        refKind === "verified_source_log"
          ? {
              source_kind: "verified_source_log" as const,
              source_name: refName.trim(),
              source_ref: refValue.trim(),
              research_source_id: selectedSourceId || null,
            }
          : {
              source_kind: "owner_supplied" as const,
              source_name: refName.trim(),
              source_ref: refValue.trim(),
            };
      const created = await createCalculation(projectId, {
        task_id: taskId || null,
        title: title.trim(),
        calculation_type: calcType,
        language: outLang,
        classification,
        inputs: parsedInputs,
        references: [refPayload],
      });
      setSelectedCalc(created);
      const createdOutcome =
        created.acceptance_outcome_label ||
        (typeof created.results.acceptance_outcome_label === "string" && created.results.acceptance_outcome_label
          ? created.results.acceptance_outcome_label
          : created.acceptance_passed
            ? copy.passBadge
            : copy.failBadge);
      setStatusMsg(`${created.title} — ${createdOutcome}`);
      const listRes = await listProjectCalculations(projectId);
      setCalculations(listRes.calculations);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  async function handleExport() {
    if (!selectedCalc) return;
    setExporting(true);
    setError(null);
    setStatusMsg(null);
    try {
      const res = await exportCalculationDeliverables(selectedCalc.id, { language: outLang });
      setSelectedCalc(res.calculation);
      setStatusMsg(
        `Exported v${res.calculation.export_version}: ${res.docx_deliverable.filename}, ${res.pdf_deliverable.filename}, ${res.xlsx_deliverable.filename}`
      );
      if (projectId) {
        const listRes = await listProjectCalculations(projectId);
        setCalculations(listRes.calculations);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  }

  const scalarEntries = (obj: Record<string, unknown>) =>
    Object.entries(obj).filter(([, val]) => typeof val !== "object" || val === null);

  const selectedProvenance = selectedCalc
    ? selectedCalc.data_provenance ||
      (typeof selectedCalc.results.data_provenance === "string" ? selectedCalc.results.data_provenance : "")
    : "";
  const selectedOutcomeLabel = selectedCalc
    ? selectedCalc.acceptance_outcome_label ||
      (typeof selectedCalc.results.acceptance_outcome_label === "string" && selectedCalc.results.acceptance_outcome_label
        ? selectedCalc.results.acceptance_outcome_label
        : selectedCalc.acceptance_passed
          ? copy.passBadge
          : copy.failBadge)
    : "";

  const breakdownRows = selectedCalc
    ? ((selectedCalc.results.circuits as Array<Record<string, unknown>> | undefined) ??
        (selectedCalc.results.fixtures as Array<Record<string, unknown>> | undefined) ??
        (selectedCalc.results.evaluated_sizes as Array<Record<string, unknown>> | undefined) ??
        [])
    : [];

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
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

      <section className="subpanel" aria-label={copy.heading}>
        <div className="panel-header">
          <div>
            <h2 className="panel-title">{copy.heading}</h2>
            <p className="muted-hint">{copy.subtitle}</p>
          </div>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="form-grid">
          <div className="field">
            <span>{copy.projectLabel}</span>
            <select
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                setTaskId("");
              }}
            >
              <option value="">--</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  [{p.code}] {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>{copy.taskLabel}</span>
            <select value={taskId} onChange={(e) => setTaskId(e.target.value)}>
              <option value="">{copy.noTaskOpt}</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>{copy.calcTypeLabel}</span>
            <select
              value={calcType}
              onChange={(e) => {
                const nextType = e.target.value as CalculationType;
                setCalcType(nextType);
                applyPreset(nextType, presets);
              }}
            >
              {(Object.keys(typeLabels) as CalculationType[]).map((ct) => (
                <option key={ct} value={ct}>
                  {typeLabels[ct]}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>{copy.titleLabel}</span>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>

          <div className="field">
            <span>{copy.classLabel}</span>
            <select
              value={classification}
              onChange={(e) => setClassification(e.target.value as ProjectClassification)}
            >
              {CLASSIFICATIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>{copy.langLabel}</span>
            <select value={outLang} onChange={(e) => setOutLang(e.target.value as ReportLanguage)}>
              <option value="ar">العربية (RTL)</option>
              <option value="en">English (LTR)</option>
            </select>
          </div>

          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
              <span>{copy.inputsJsonLabel}</span>
              <button
                type="button"
                className="btn btn-compact btn-secondary"
                onClick={() => applyPreset(calcType, presets)}
              >
                {copy.loadPresetBtn}
              </button>
            </div>
            <textarea
              rows={7}
              dir="ltr"
              style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
              value={inputsText}
              onChange={(e) => setInputsText(e.target.value)}
              required
            />
          </div>

          <div className="status-box" style={{ gridColumn: "1 / -1" }}>
            {copy.refCodeNotice}
          </div>

          <div className="field">
            <span>{copy.refKindLabel}</span>
            <select
              value={refKind}
              onChange={(e) => setRefKind(e.target.value as CalculationReferenceKind)}
            >
              <option value="owner_supplied">{copy.refOwnerOpt}</option>
              <option value="verified_source_log">{copy.refVerifiedOpt}</option>
            </select>
          </div>

          {refKind === "verified_source_log" && (
            <div className="field">
              <span>{copy.refSourceSelectLabel}</span>
              <select
                value={selectedSourceId}
                onChange={(e) => {
                  const sid = e.target.value;
                  setSelectedSourceId(sid);
                  const found = reviewedSources.find((s) => s.id === sid);
                  if (found) {
                    setRefName(found.source_name);
                    setRefValue(found.url);
                  }
                }}
              >
                <option value="">--</option>
                {reviewedSources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.source_name} ({s.url})
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="field">
            <span>{copy.refNameLabel}</span>
            <input type="text" value={refName} onChange={(e) => setRefName(e.target.value)} required />
          </div>

          <div className="field">
            <span>{copy.refValueLabel}</span>
            <input type="text" value={refValue} onChange={(e) => setRefValue(e.target.value)} required />
          </div>

          <div style={{ gridColumn: "1 / -1", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <button type="submit" className="btn" disabled={!projectId || running}>
              {running ? copy.runningBtn : copy.runBtn}
            </button>
          </div>
        </form>
      </section>

      {selectedCalc && (
        <section className="subpanel" aria-label={selectedCalc.title}>
          <div className="panel-header">
            <div>
              <h3 className="panel-title">
                {selectedCalc.title} ({selectedCalc.revision} · v{selectedCalc.version})
              </h3>
              <span className={`badge ${selectedCalc.acceptance_passed ? "badge-ok" : "badge-warn"}`}>
                {selectedOutcomeLabel}
              </span>{" "}
              <span className="badge">{selectedCalc.classification}</span>{" "}
              <span className="badge" dir="ltr">tokens: {selectedCalc.tokens_used}</span>
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={exporting}
              onClick={() => void handleExport()}
            >
              {exporting ? copy.exportingBtn : copy.exportBtn}
            </button>
          </div>

          <div style={{ display: "grid", gap: "0.85rem" }}>
            <div
              className={`status-box ${selectedProvenance === "owner_supplied" ? "status-ok" : ""}`}
              style={
                selectedProvenance && selectedProvenance !== "owner_supplied"
                  ? { borderColor: "#d97706", background: "#fffbeb", color: "#92400e" }
                  : undefined
              }
              data-testid="calc-data-provenance"
            >
              <strong>{copy.provenanceLabel}:</strong>{" "}
              <span dir="ltr">{selectedProvenance || "—"}</span>
            </div>
            <div>
              <h4>{copy.secInputs} &amp; {copy.secUnits}</h4>
              <div className="table-wrap">
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>Parameter</th>
                      <th>Value</th>
                      <th>Unit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scalarEntries(selectedCalc.inputs).map(([k, v]) => (
                      <tr key={k}>
                        <td dir="ltr"><code>{k}</code></td>
                        <td dir="ltr">{String(v)}</td>
                        <td dir="ltr">{selectedCalc.units[k] ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <h4>{copy.secEquations}</h4>
              <pre dir="ltr" className="status-box" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {selectedCalc.equations}
              </pre>
            </div>

            <div>
              <h4>{copy.secMethod}</h4>
              <p dir="auto" style={{ margin: 0 }}>{selectedCalc.method}</p>
            </div>

            <div>
              <h4>{copy.secAssumptions}</h4>
              <ul style={{ margin: "0.25rem 0" }}>
                {selectedCalc.assumptions.map((a, idx) => (
                  <li key={idx} dir="auto">{a}</li>
                ))}
              </ul>
            </div>

            <div>
              <h4>{copy.secResults}</h4>
              <div className="table-wrap">
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>Output</th>
                      <th>Value</th>
                      <th>Unit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scalarEntries(selectedCalc.results).map(([k, v]) => (
                      <tr key={k}>
                        <td dir="ltr"><code>{k}</code></td>
                        <td dir="ltr"><strong>{v === null || v === undefined ? "—" : String(v)}</strong></td>
                        <td dir="ltr">{selectedCalc.units[k] ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {breakdownRows.length > 0 && (
                <div className="table-wrap" style={{ marginTop: "0.5rem" }}>
                  <table className="files-table">
                    <thead>
                      <tr>
                        {Object.keys(breakdownRows[0]).map((col) => (
                          <th key={col} dir="ltr">{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {breakdownRows.map((rowObj, idx) => (
                        <tr key={idx}>
                          {Object.keys(breakdownRows[0]).map((col) => (
                            <td key={col} dir="auto">
                              {rowObj[col] === null || rowObj[col] === undefined ? "—" : String(rowObj[col])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div>
              <h4>{copy.secAcceptance}</h4>
              <ul style={{ margin: "0.25rem 0" }}>
                {selectedCalc.acceptance_criteria.map((c, idx) => (
                  <li key={idx} dir="auto"><strong>{c}</strong></li>
                ))}
              </ul>
            </div>

            <div>
              <h4>{copy.secReferences}</h4>
              <div className="table-wrap">
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>Kind</th>
                      <th>Name</th>
                      <th>Reference</th>
                      <th>Code Verification</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedCalc.references.map((r, idx) => (
                      <tr key={idx}>
                        <td dir="ltr"><code>{r.source_kind}</code></td>
                        <td dir="auto">{r.source_name}</td>
                        <td dir="auto">{r.source_ref}</td>
                        <td dir="ltr">
                          <span className="badge badge-warn">{r.verification_label}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {selectedCalc.deliverables.length > 0 && (
              <div>
                <h4>{copy.secDeliverables}</h4>
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  {selectedCalc.deliverables.map((d) => (
                    <a
                      key={d.id}
                      className="btn btn-compact btn-secondary"
                      href={getDeliverableDownloadUrl(d.id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {copy.downloadLabel} {d.format.toUpperCase()} (v{d.version})
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      <section className="subpanel" aria-label={copy.historyHeading}>
        <h3 className="panel-title">{copy.historyHeading}</h3>
        {calculations.length === 0 ? (
          <p className="muted-hint">{copy.noCalcs}</p>
        ) : (
          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Discipline</th>
                  <th>Type</th>
                  <th>Version</th>
                  <th>Outcome</th>
                  <th>Classification</th>
                </tr>
              </thead>
              <tbody>
                {calculations.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <button
                        type="button"
                        className="btn btn-compact btn-secondary"
                        onClick={() => void getCalculationDetail(c.id).then(setSelectedCalc)}
                      >
                        {c.title}
                      </button>
                    </td>
                    <td dir="ltr">{c.discipline}</td>
                    <td dir="ltr"><code>{c.calculation_type}</code></td>
                    <td dir="ltr">v{c.version} (exp v{c.export_version})</td>
                    <td>
                      <span className={`badge ${c.acceptance_passed ? "badge-ok" : "badge-warn"}`}>
                        {c.acceptance_outcome_label || (c.acceptance_passed ? copy.passBadge : copy.failBadge)}
                      </span>
                    </td>
                    <td>{c.classification}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
