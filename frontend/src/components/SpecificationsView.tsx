import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  approveSpecificationDraft,
  exportSpecificationDeliverables,
  generateProjectSpecification,
  getDeliverableDownloadUrl,
  getSpecificationDetail,
  listProjectBoqSheets,
  listProjectParametricDrawings,
  listProjects,
  listProjectSpecifications,
  listResearchSources,
  listTasks,
} from "../api";
import type {
  BoqSheetSummaryOut,
  Lang,
  ParametricDrawingDetailOut,
  ProjectClassification,
  ProjectSummary,
  ReportLanguage,
  ResearchSourceOut,
  SpecPartKey,
  SpecificationDetailOut,
  SpecificationSummaryOut,
  TaskSummaryOut,
} from "../types";

const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const SPEC_PARTS_ORDER: SpecPartKey[] = [
  "scope",
  "standards",
  "materials",
  "execution",
  "testing",
  "acceptance",
  "submittals",
  "warranty",
];

const PART_LABELS: Record<Lang, Record<SpecPartKey, string>> = {
  ar: {
    scope: "1. نطاق الأعمال (Scope)",
    standards: "2. المعايير المعتمدة (Standards)",
    materials: "3. المواد والمنتجات (Materials)",
    execution: "4. التنفيذ والمصنعية (Execution)",
    testing: "5. الفحص والاختبارات (Testing)",
    acceptance: "6. معايير القبول (Acceptance)",
    submittals: "7. التقديمات المطلوبة (Submittals)",
    warranty: "8. الضمان والتسليم (Warranty)",
  },
  en: {
    scope: "1. Scope of Work",
    standards: "2. Applicable Standards",
    materials: "3. Materials & Products",
    execution: "4. Execution & Installation",
    testing: "5. Inspection & Testing",
    acceptance: "6. Acceptance Criteria",
    submittals: "7. Submittals",
    warranty: "8. Warranty & Closeout",
  },
};

const COPY: Record<
  Lang,
  {
    heading: string;
    subtitle: string;
    projectLabel: string;
    taskLabel: string;
    noTaskOpt: string;
    titleLabel: string;
    titlePlaceholder: string;
    disciplineLabel: string;
    classLabel: string;
    langLabel: string;
    sourcesTitle: string;
    boqHint: string;
    dwgHint: string;
    srcHint: string;
    noInputsWarn: string;
    useAiLabel: string;
    stdNotice: string;
    generateBtn: string;
    generatingBtn: string;
    approveHeading: string;
    approvedByLabel: string;
    approveBtn: string;
    approvingBtn: string;
    exportEnBtn: string;
    exportArBtn: string;
    exportingBtn: string;
    deliverablesHeading: string;
    missingStdHeading: string;
    standardsHeading: string;
    clausesHeading: string;
    tracePrefix: string;
    historyHeading: string;
    noSpecs: string;
    openBtn: string;
  }
> = {
  ar: {
    heading: "مولّد المواصفات الفنية المرتبط بجداول الكميات والمخططات (Step 14)",
    subtitle:
      "يولّد أقسام المواصفات الكاملة (النطاق، المعايير، المواد، التنفيذ، الاختبارات، القبول، التقديمات، الضمان) حصرياً من بنود جداول الكميات الفعلية وجداول المخططات البارامترية ومصادر البحث المراجَعة — بمسار حتمي افتراضي (0 توكن) أو صياغة اختيارية بالذكاء الاصطناعي تُوسَم كمسودة غير مُتحقَّق منها حتى اعتماد المالك.",
    projectLabel: "المشروع",
    taskLabel: "التكليف المرتبط (اختياري)",
    noTaskOpt: "عام للمشروع",
    titleLabel: "عنوان حزمة المواصفات (اختياري)",
    titlePlaceholder: "مثال: المواصفات الفنية للعيادة النموذجية",
    disciplineLabel: "التخصص الرئيسي",
    classLabel: "التصنيف",
    langLabel: "لغة الوثيقة (DOCX + PDF)",
    sourcesTitle: "المدخلات المرتبطة فعلياً بالمشروع",
    boqHint: "جداول الكميات (BOQ):",
    dwgHint: "المخططات البارامترية:",
    srcHint: "المصادر البحثية المراجَعة:",
    noInputsWarn: "لا توجد بنود BOQ أو مخططات بارامترية لهذا المشروع بعد — أضف BOQ أو مخططاً أولاً.",
    useAiLabel:
      "اختياري: صياغة نصوص المواصفات بالذكاء الاصطناعي (Gemini) — تُوسَم كـ مسودة غير مُتحقَّق منها حتى يعتمدها المالك، ولا يغيّر الكميات أو المعايير.",
    stdNotice:
      "تنبيه المعايير: لا تُدرج إلا المصادر المراجَعة في سجل البحث؛ وأي قسم دون معيار موثق يظهر بعبارة «no verified standard on file - verify against the locally adopted code» دون اختراع أرقام بنود أو سنوات إصدار.",
    generateBtn: "توليد وحفظ المواصفات الفنية (DOCX + PDF + SHA-256)",
    generatingBtn: "جاري التوليد والتصدير...",
    approveHeading: "اعتماد المالك لمسودة الذكاء الاصطناعي",
    approvedByLabel: "اسم المعتمد",
    approveBtn: "اعتماد المسودة وحفظ إصدار مُصدَّر جديد",
    approvingBtn: "جاري الاعتماد...",
    exportEnBtn: "تصدير إصدار إنجليزي LTR جديد",
    exportArBtn: "تصدير إصدار عربي RTL جديد",
    exportingBtn: "جاري التصدير...",
    deliverablesHeading: "ملفات المواصفات المُصدَّرة (07_Technical_Specifications + SHA-256)",
    missingStdHeading: "أقسام دون معيار موثق في سجل المصادر",
    standardsHeading: "المعايير المعتمدة للقسم",
    clausesHeading: "البنود التتبعية (8 أقسام فرعية إلزامية)",
    tracePrefix: "تتبع المصدر",
    historyHeading: "سجل إصدارات المواصفات الفنية بالمشروع",
    noSpecs: "لا توجد حزم مواصفات فنية مولَّدة لهذا المشروع بعد.",
    openBtn: "عرض التفاصيل",
  },
  en: {
    heading: "BOQ & Drawing-Linked Technical Specifications Generator (Step 14)",
    subtitle:
      "Builds complete 8-part specifications (scope, standards, materials, execution, testing, acceptance, submittals, warranty) strictly from the project's actual BOQ items, parametric drawing schedules, and reviewed research sources — deterministic 0-token template by default, with optional Gemini prose marked UNVERIFIED until owner approval.",
    projectLabel: "Project",
    taskLabel: "Linked Task (optional)",
    noTaskOpt: "Project-wide",
    titleLabel: "Specification Package Title (optional)",
    titlePlaceholder: "e.g. Clinic Architectural & MEP Specifications",
    disciplineLabel: "Primary Discipline",
    classLabel: "Classification",
    langLabel: "Output Language (DOCX + PDF)",
    sourcesTitle: "Verified Project Inputs Available for Traceability",
    boqHint: "BOQ Sheets:",
    dwgHint: "Parametric Drawings:",
    srcHint: "Reviewed Research Sources:",
    noInputsWarn: "Project has no BOQ sheets or parametric drawings yet — add a BOQ or parametric CAD drawing first.",
    useAiLabel:
      "Optional: draft prose wording with Gemini (AI output is marked UNVERIFIED AI DRAFT until owner approves; standards and numbers stay locked).",
    stdNotice:
      "Standards Rule: only reviewed ResearchSource entries are cited as verified; sections without a matching reviewed source show 'no verified standard on file - verify against the locally adopted code' with zero fabricated clause numbers or edition years.",
    generateBtn: "Generate & Save Traceable Specifications (DOCX + PDF + SHA-256)",
    generatingBtn: "Generating & Exporting...",
    approveHeading: "Owner Approval Required for AI-Drafted Specification",
    approvedByLabel: "Approved By",
    approveBtn: "Approve AI Draft & Save New Version",
    approvingBtn: "Approving...",
    exportEnBtn: "Export New English LTR Version",
    exportArBtn: "Export New Arabic RTL Version",
    exportingBtn: "Exporting...",
    deliverablesHeading: "Exported Specification Deliverables (07_Technical_Specifications + SHA-256)",
    missingStdHeading: "Sections With No Verified Standard on File",
    standardsHeading: "Section Applicable Standards",
    clausesHeading: "Traceable Clauses (All 8 Mandatory Parts)",
    tracePrefix: "Trace",
    historyHeading: "Project Technical Specifications Register",
    noSpecs: "No technical specifications generated for this project yet.",
    openBtn: "Inspect",
  },
};

export interface SpecificationsViewProps {
  lang: Lang;
  initialSpec?: SpecificationDetailOut | null;
  initialSpecs?: SpecificationSummaryOut[];
}

export function SpecificationsView({
  lang,
  initialSpec = null,
  initialSpecs,
}: SpecificationsViewProps) {
  const copy = COPY[lang];
  const partLabels = PART_LABELS[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState(initialSpec?.project_id ?? "");
  const [tasks, setTasks] = useState<TaskSummaryOut[]>([]);
  const [taskId, setTaskId] = useState("");
  const [boqSheets, setBoqSheets] = useState<BoqSheetSummaryOut[]>([]);
  const [drawings, setDrawings] = useState<ParametricDrawingDetailOut[]>([]);
  const [reviewedSources, setReviewedSources] = useState<ResearchSourceOut[]>([]);

  const [title, setTitle] = useState("");
  const [discipline, setDiscipline] = useState("multidisciplinary");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [outLang, setOutLang] = useState<ReportLanguage>(lang);
  const [useAi, setUseAi] = useState(false);

  const [selectedSpec, setSelectedSpec] = useState<SpecificationDetailOut | null>(initialSpec);
  const [specs, setSpecs] = useState<SpecificationSummaryOut[]>(initialSpecs ?? []);
  const [approvedBy, setApprovedBy] = useState("Owner");

  const [running, setRunning] = useState(false);
  const [approving, setApproving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  useEffect(() => {
    void listProjects()
      .then((res) => {
        setProjects(res.projects);
        if (!projectId && res.projects.length > 0) {
          setProjectId(res.projects[0].id);
        }
      })
      .catch(() => undefined);
  }, [projectId]);

  const refreshProjectData = useCallback(async (pid: string) => {
    if (!pid) return;
    try {
      const [taskRes, boqRes, dwgRes, srcRes, specRes] = await Promise.all([
        listTasks({ projectId: pid }),
        listProjectBoqSheets(pid),
        listProjectParametricDrawings(pid),
        listResearchSources({ project_id: pid, reviewed_only: true }),
        listProjectSpecifications(pid),
      ]);
      setTasks(taskRes.tasks);
      setBoqSheets(boqRes.sheets);
      setDrawings(dwgRes.drawings);
      setReviewedSources(srcRes.sources);
      setSpecs(specRes.specifications);
    } catch {
      // Keep UI responsive during offline unit rendering
    }
  }, []);

  useEffect(() => {
    if (projectId && !initialSpecs) {
      void refreshProjectData(projectId);
    }
  }, [projectId, initialSpecs, refreshProjectData]);

  async function handleGenerate(e: FormEvent) {
    e.preventDefault();
    if (!projectId) return;
    setRunning(true);
    setError(null);
    setStatusMsg(null);
    try {
      const created = await generateProjectSpecification(projectId, {
        task_id: taskId || null,
        title: title.trim() || null,
        discipline: discipline.trim() || "multidisciplinary",
        language: outLang,
        classification,
        use_ai: useAi,
      });
      setSelectedSpec(created);
      setStatusMsg(`${created.title} — ${created.revision} (${created.ai_draft_label})`);
      await refreshProjectData(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  async function handleApprove() {
    if (!selectedSpec) return;
    setApproving(true);
    setError(null);
    setStatusMsg(null);
    try {
      const approved = await approveSpecificationDraft(selectedSpec.id, {
        approved_by: approvedBy.trim() || "Owner",
        export_after_approval: true,
      });
      setSelectedSpec(approved);
      setStatusMsg(`${approved.title} — ${approved.ai_draft_label}`);
      if (projectId) await refreshProjectData(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApproving(false);
    }
  }

  async function handleExport(targetLang: ReportLanguage) {
    if (!selectedSpec) return;
    setExporting(true);
    setError(null);
    setStatusMsg(null);
    try {
      const res = await exportSpecificationDeliverables(selectedSpec.id, { language: targetLang });
      setSelectedSpec(res.specification);
      setStatusMsg(
        `Export #${res.specification.export_version}: ${res.docx_deliverable.filename}, ${res.pdf_deliverable.filename}`
      );
      if (projectId) await refreshProjectData(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  }

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

        <form onSubmit={(e) => void handleGenerate(e)} className="form-grid">
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
            <span>{copy.titleLabel}</span>
            <input
              type="text"
              placeholder={copy.titlePlaceholder}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="field">
            <span>{copy.disciplineLabel}</span>
            <input
              type="text"
              value={discipline}
              onChange={(e) => setDiscipline(e.target.value)}
            />
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

          <div className="status-box" style={{ gridColumn: "1 / -1" }}>
            <div>
              <strong>{copy.sourcesTitle}:</strong>{" "}
              <span>
                {copy.boqHint} <strong>{boqSheets.length}</strong> · {copy.dwgHint}{" "}
                <strong>{drawings.length}</strong> · {copy.srcHint}{" "}
                <strong>{reviewedSources.length}</strong>
              </span>
            </div>
            {projectId && boqSheets.length === 0 && drawings.length === 0 && !initialSpecs && (
              <div style={{ color: "#b45309", marginTop: "0.35rem" }}>{copy.noInputsWarn}</div>
            )}
          </div>

          <label style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
            <span>{copy.useAiLabel}</span>
          </label>

          <div className="status-box" style={{ gridColumn: "1 / -1" }}>
            {copy.stdNotice}
          </div>

          <div style={{ gridColumn: "1 / -1", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <button type="submit" className="btn" disabled={!projectId || running}>
              {running ? copy.generatingBtn : copy.generateBtn}
            </button>
          </div>
        </form>
      </section>

      {selectedSpec && (
        <section className="subpanel" aria-label={selectedSpec.title}>
          <div className="panel-header">
            <div>
              <h3 className="panel-title">
                {selectedSpec.title} ({selectedSpec.revision} · v{selectedSpec.version} · exp #{selectedSpec.export_version})
              </h3>
              <span
                className={`badge ${
                  selectedSpec.ai_draft_status === "unverified_ai_draft" ? "badge-warn" : "badge-ok"
                }`}
              >
                {selectedSpec.ai_draft_label}
              </span>{" "}
              <span className="badge">{selectedSpec.classification}</span>{" "}
              <span className="badge" dir="ltr">tokens: {selectedSpec.tokens_used}</span>
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn btn-compact btn-secondary"
                disabled={exporting}
                onClick={() => void handleExport("ar")}
              >
                {exporting ? copy.exportingBtn : copy.exportArBtn}
              </button>
              <button
                type="button"
                className="btn btn-compact btn-secondary"
                disabled={exporting}
                onClick={() => void handleExport("en")}
              >
                {exporting ? copy.exportingBtn : copy.exportEnBtn}
              </button>
            </div>
          </div>

          {selectedSpec.ai_draft_status === "unverified_ai_draft" && (
            <div
              className="status-box"
              style={{ borderColor: "#dc2626", background: "#fef2f2", color: "#991b1b" }}
              data-testid="spec-ai-unverified-banner"
            >
              <strong>{copy.approveHeading}</strong>
              <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                <label style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                  <span>{copy.approvedByLabel}:</span>
                  <input
                    type="text"
                    value={approvedBy}
                    onChange={(e) => setApprovedBy(e.target.value)}
                    style={{ maxWidth: "180px" }}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-compact"
                  disabled={approving}
                  onClick={() => void handleApprove()}
                >
                  {approving ? copy.approvingBtn : copy.approveBtn}
                </button>
              </div>
            </div>
          )}

          {selectedSpec.summary && <p dir="auto">{selectedSpec.summary}</p>}

          {selectedSpec.missing_standards_notices.length > 0 && (
            <div
              className="status-box"
              style={{ borderColor: "#d97706", background: "#fffbeb", color: "#92400e" }}
            >
              <strong>{copy.missingStdHeading}:</strong>
              <ul style={{ margin: "0.35rem 0 0" }}>
                {selectedSpec.missing_standards_notices.map((n, idx) => (
                  <li key={idx} dir="auto">{n}</li>
                ))}
              </ul>
            </div>
          )}

          {selectedSpec.deliverables.length > 0 && (
            <div>
              <h4>{copy.deliverablesHeading}</h4>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {selectedSpec.deliverables.map((d) => (
                  <a
                    key={d.id}
                    className="btn btn-compact btn-secondary"
                    href={getDeliverableDownloadUrl(d.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {d.format.toUpperCase()} v{d.version} ({d.sha256 ? d.sha256.slice(0, 10) : "sha"})
                  </a>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "grid", gap: "0.85rem", marginTop: "0.5rem" }}>
            {selectedSpec.sections.map((sec) => (
              <div key={sec.section_code} className="subpanel" style={{ padding: "0.75rem" }}>
                <h4 style={{ margin: "0 0 0.35rem" }}>
                  <code>{sec.section_code}</code> — {sec.title}{" "}
                  <span className="badge">{sec.discipline}</span>
                </h4>
                <div className="muted-hint" dir="ltr" style={{ marginBottom: "0.5rem" }}>
                  BOQ IDs: {sec.mapped_boq_item_ids.length} · Drawings: {sec.mapped_drawing_refs.join(", ") || "—"}
                </div>

                <div style={{ marginBottom: "0.5rem" }}>
                  <strong>{copy.standardsHeading}:</strong>
                  <ul style={{ margin: "0.25rem 0" }}>
                    {sec.standards.map((st, idx) => (
                      <li key={idx} dir="auto">
                        <span
                          className={`badge ${
                            st.status === "no_verified_standard_on_file" ? "badge-warn" : "badge-ok"
                          }`}
                        >
                          {st.status}
                        </span>{" "}
                        {st.citation_text}
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <strong>{copy.clausesHeading}:</strong>
                  {SPEC_PARTS_ORDER.map((pkey) => {
                    const partClauses = sec.clauses.filter((cl) => cl.part === pkey);
                    if (partClauses.length === 0) return null;
                    return (
                      <div key={pkey} style={{ marginTop: "0.4rem" }}>
                        <div style={{ fontWeight: 600 }}>{partLabels[pkey]}</div>
                        {partClauses.map((cl) => (
                          <div key={cl.clause_id} style={{ paddingLeft: "0.5rem", marginTop: "0.2rem" }}>
                            <div>
                              <code dir="ltr">[{cl.clause_id}]</code>{" "}
                              {cl.draft_origin === "ai_unverified_draft" && (
                                <span className="badge badge-warn">{cl.draft_origin}</span>
                              )}{" "}
                              <span dir="auto">{cl.text}</span>
                            </div>
                            <div className="muted-hint" dir="ltr" style={{ fontSize: "0.78rem" }}>
                              {copy.tracePrefix}: {cl.trace_refs.map((tr) => `${tr.trace_id} (${tr.label})`).join(" | ")}
                            </div>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="subpanel" aria-label={copy.historyHeading}>
        <h3 className="panel-title">{copy.historyHeading}</h3>
        {specs.length === 0 ? (
          <p className="muted-hint">{copy.noSpecs}</p>
        ) : (
          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Revision</th>
                  <th>Language</th>
                  <th>Sections / Clauses</th>
                  <th>Draft Status</th>
                  <th>Tokens</th>
                </tr>
              </thead>
              <tbody>
                {specs.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <button
                        type="button"
                        className="btn btn-compact btn-secondary"
                        onClick={() => void getSpecificationDetail(s.id).then(setSelectedSpec)}
                      >
                        {s.title}
                      </button>
                    </td>
                    <td dir="ltr">{s.revision} (v{s.version} / exp #{s.export_version})</td>
                    <td dir="ltr">{s.language}</td>
                    <td dir="ltr">{s.sections_count} / {s.clauses_count}</td>
                    <td>
                      <span
                        className={`badge ${
                          s.ai_draft_status === "unverified_ai_draft" ? "badge-warn" : "badge-ok"
                        }`}
                      >
                        {s.ai_draft_label}
                      </span>
                    </td>
                    <td dir="ltr">{s.tokens_used}</td>
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
