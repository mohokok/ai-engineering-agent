import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  enhanceReviewReportAi,
  generateReviewReport,
  getReviewReportDetail,
  listDeliverables,
  listProjectFiles,
  listProjectReviewReports,
  listProjects,
  listResearchRuns,
} from "../api";
import type {
  CategorizedStatement,
  DeliverableOut,
  Lang,
  ProjectClassification,
  ProjectFileOut,
  ProjectSummary,
  ReportLanguage,
  ResearchRunSummaryOut,
  ReviewReportDetailOut,
  ReviewReportSummaryOut,
  SourceLocationRef,
} from "../types";

interface DeliverablesCopy {
  generatorHeading: string;
  generatorHint: string;
  projectLabel: string;
  selectProjectOpt: string;
  languageLabel: string;
  langAr: string;
  langEn: string;
  classificationLabel: string;
  disciplineLabel: string;
  titleLabel: string;
  titlePlaceholder: string;
  notesLabel: string;
  notesPlaceholder: string;
  filesLabel: string;
  researchLabel: string;
  generateBtn: string;
  generatingBtn: string;
  tokenEstimateHeading: string;
  enhanceAiBtn: string;
  enhancingBtn: string;
  reportsHistoryHeading: string;
  inspectBtn: string;
  deliverablesHeading: string;
  refreshBtn: string;
  folderFilterLabel: string;
  folderAll: string;
  emptyDeliverables: string;
  colFolder: string;
  colFile: string;
  colFormat: string;
  colVer: string;
  colClass: string;
  colIntegrity: string;
  colAction: string;
  downloadBtn: string;
  revisionBlockHeading: string;
  findingsHeading: string;
  colFindingId: string;
  colDisc: string;
  colSev: string;
  colLocRef: string;
  colEvidenceSource: string;
  colRec: string;
  colStat: string;
  sourcePrefix: string;
  factsHeading: string;
  calculatedHeading: string;
  assumptionsHeading: string;
  recommendationsHeading: string;
  gapsHeading: string;
  errorPrefix: string;
}

const COPY: Record<Lang, DeliverablesCopy> = {
  ar: {
    generatorHeading: "إصدار تقرير المراجعة الهندسية (DOCX + PDF)",
    generatorHint:
      "يقرأ المهارات المستخرجة وسجل المصادر المراجَعة ويربط كل ملاحظة بمصدرها، ويفصل الحقائق المحققة عن القيم المحسوبة برمجياً والافتراضات والتوصيات دون استهلاك توكنات Gemini تلقائياً.",
    projectLabel: "المشروع الهندسي *",
    selectProjectOpt: "اختر مشروعاً...",
    languageLabel: "لغة التقرير وتنسيق الاتجاه",
    langAr: "العربية (RTL — Word + PDF)",
    langEn: "English (LTR — DOCX + PDF)",
    classificationLabel: "تصنيف الإخراج",
    disciplineLabel: "التخصص",
    titleLabel: "عنوان التقرير (اختياري)",
    titlePlaceholder: "مثال: تقرير مراجعة المخططات والمواصفات — مرحلة أولية",
    notesLabel: "ملاحظات / نطاق المراجعة",
    notesPlaceholder: "حدد العناصر أو التخصصات المطلوب التركيز عليها",
    filesLabel: "ملفات المشروع المشمولة (افتراضي: جميع الملفات)",
    researchLabel: "سجلات الأبحاث المراجَعة المشمولة (اختياري)",
    generateBtn: "توليد تقرير المراجعة وحفظ DOCX + PDF (0 توكن مبدئياً)",
    generatingBtn: "جاري بناء التقارير (DOCX + PDF) وحفظها في 08_Reports و 10_Final_Deliverables...",
    tokenEstimateHeading: "تقدير توكنات Gemini قبل التحسين الذكي (ضمن حدود الخطوة 04 و08):",
    enhanceAiBtn: "توليد نسخة محسّنة عبر Gemini",
    enhancingBtn: "جاري التحسين المحدود بالمصادر وإصدار مراجعة جديدة...",
    reportsHistoryHeading: "سجل تقارير المراجعة للمشروع",
    inspectBtn: "عرض التفاصيل والنتائج",
    deliverablesHeading: "صفحة المخرجات النهائية والتقارير القابلة للتنزيل (08_Reports و 10_Final_Deliverables)",
    refreshBtn: "تحديث القائمة",
    folderFilterLabel: "تصفية حسب المجلد",
    folderAll: "كافة المجلدات",
    emptyDeliverables: "لا توجد مخرجات مُولّدة حتى الآن.",
    colFolder: "المجلد",
    colFile: "اسم الملف والعنوان",
    colFormat: "الصيغة",
    colVer: "الإصدار",
    colClass: "التصنيف",
    colIntegrity: "التحقق (SHA-256 والحجم)",
    colAction: "تنزيل",
    downloadBtn: "تنزيل",
    revisionBlockHeading: "جدول المراجعة والإصدار (Revision Block)",
    findingsHeading: "سجل ملاحظات المراجعة المرتبطة بالمصادر",
    colFindingId: "المعرف",
    colDisc: "التخصص",
    colSev: "الخطورة",
    colLocRef: "موقع المرجع / المخطط",
    colEvidenceSource: "الأدلة ورابط المصدر الموثّق",
    colRec: "التوصية",
    colStat: "الحالة",
    sourcePrefix: "رابط المصدر",
    factsHeading: "1. حقائق مُتحقَّق منها بمصدرها",
    calculatedHeading: "2. قيم محسوبة برمجياً فقط",
    assumptionsHeading: "3. افتراضات أولية (تحتاج تأكيد المالك)",
    recommendationsHeading: "4. التوصيات الهندسية",
    gapsHeading: "فجوات البيانات والمستندات غير المراجَعة",
    errorPrefix: "تعذر تنفيذ طلب التقرير: ",
  },
  en: {
    generatorHeading: "Generate Engineering Review Report (DOCX + PDF)",
    generatorHint:
      "Reads verified extractions and reviewed research logs, anchors every finding to exact source locations, separates verified facts / calculated values / assumptions / recommendations, and saves versioned DOCX & PDF files into 08_Reports and 10_Final_Deliverables at 0 initial Gemini tokens.",
    projectLabel: "Project *",
    selectProjectOpt: "Select project...",
    languageLabel: "Report Language & Layout Direction",
    langAr: "Arabic (RTL — Word + PDF)",
    langEn: "English (LTR — DOCX + PDF)",
    classificationLabel: "Classification",
    disciplineLabel: "Discipline",
    titleLabel: "Report Title (optional)",
    titlePlaceholder: "e.g., Multidisciplinary Drawing & Specification Review",
    notesLabel: "Review Scope Notes (optional)",
    notesPlaceholder: "Specific drawings, clauses, or coordination areas to highlight",
    filesLabel: "Project Files Included (default: all extracted/project files)",
    researchLabel: "Reviewed Research Runs Included (optional)",
    generateBtn: "Generate Review Report & Save DOCX + PDF (0 AI Tokens)",
    generatingBtn: "Generating DOCX + PDF into 08_Reports & 10_Final_Deliverables...",
    tokenEstimateHeading: "Pre-flight Gemini Token Estimate (Step 04 Budget & Step 08 Prompt Cap):",
    enhanceAiBtn: "Enhance Findings with Gemini AI",
    enhancingBtn: "Generating AI-enhanced next revision...",
    reportsHistoryHeading: "Project Review Report Revisions",
    inspectBtn: "Inspect Report & Findings",
    deliverablesHeading: "Deliverables Archive & Download (08_Reports & 10_Final_Deliverables)",
    refreshBtn: "Refresh",
    folderFilterLabel: "Folder Filter",
    folderAll: "All Folders",
    emptyDeliverables: "No deliverable files have been generated yet.",
    colFolder: "Folder",
    colFile: "Title & Filename",
    colFormat: "Format",
    colVer: "Version",
    colClass: "Classification",
    colIntegrity: "Integrity (SHA-256 / Size)",
    colAction: "Download",
    downloadBtn: "Download",
    revisionBlockHeading: "Revision & Document Control Block",
    findingsHeading: "Source-Linked Engineering Review Findings",
    colFindingId: "ID",
    colDisc: "Discipline",
    colSev: "Severity",
    colLocRef: "Location / Drawing Ref",
    colEvidenceSource: "Evidence & Linked Source",
    colRec: "Recommendation",
    colStat: "Status",
    sourcePrefix: "Source Link",
    factsHeading: "1. Verified Facts (Source-Linked)",
    calculatedHeading: "2. Calculated Quantities (Deterministic Code)",
    assumptionsHeading: "3. Assumptions (Pending Owner Confirmation)",
    recommendationsHeading: "4. Recommendations",
    gapsHeading: "Data Gaps & Unreviewed / Unextracted Sources",
    errorPrefix: "Review report error: ",
  },
};

function renderSourceLinks(links: SourceLocationRef[]) {
  return links.map((ref, idx) => (
    <span key={`${ref.ref_id}-${idx}`}>
      {idx > 0 ? " ; " : ""}
      <strong>[{ref.ref_id}]</strong> {ref.source_name} · {ref.page_or_sheet} · {ref.location}
      {ref.url ? (
        <>
          {" ("}
          <a href={ref.url} target="_blank" rel="noreferrer" dir="ltr">
            {ref.url}
          </a>
          {")"}
        </>
      ) : null}
    </span>
  ));
}

export interface DeliverablesViewProps {
  lang: Lang;
  initialProjects?: ProjectSummary[];
  initialDeliverables?: DeliverableOut[];
  initialReport?: ReviewReportDetailOut | null;
}

export function DeliverablesView({
  lang,
  initialProjects = [],
  initialDeliverables = [],
  initialReport = null,
}: DeliverablesViewProps) {
  const copy = COPY[lang];
  const [projects, setProjects] = useState<ProjectSummary[]>(initialProjects);
  const [projectId, setProjectId] = useState<string>(initialProjects[0]?.id || "");
  const [projectFiles, setProjectFiles] = useState<ProjectFileOut[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [projectRuns, setProjectRuns] = useState<ResearchRunSummaryOut[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);

  const [reportLang, setReportLang] = useState<ReportLanguage>(lang);
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [discipline, setDiscipline] = useState<string>("multidisciplinary");
  const [title, setTitle] = useState<string>("");
  const [reviewNotes, setReviewNotes] = useState<string>("");

  const [reports, setReports] = useState<ReviewReportSummaryOut[]>([]);
  const [activeReport, setActiveReport] = useState<ReviewReportDetailOut | null>(initialReport);
  const [deliverables, setDeliverables] = useState<DeliverableOut[]>(initialDeliverables);
  const [folderFilter, setFolderFilter] = useState<string>("");

  const [submitting, setSubmitting] = useState<boolean>(false);
  const [enhancing, setEnhancing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadDeliverables = useCallback(async () => {
    try {
      const res = await listDeliverables({
        project_id: projectId || undefined,
        folder_name: folderFilter || undefined,
      });
      setDeliverables(res.deliverables);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [projectId, folderFilter]);

  const loadProjectContext = useCallback(async (pid: string) => {
    if (!pid) {
      setProjectFiles([]);
      setProjectRuns([]);
      setReports([]);
      return;
    }
    try {
      const [filesRes, runsRes, repsRes] = await Promise.all([
        listProjectFiles(pid),
        listResearchRuns({ project_id: pid }),
        listProjectReviewReports(pid),
      ]);
      setProjectFiles(filesRes.files);
      setProjectRuns(runsRes.runs);
      setReports(repsRes.reports);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void listProjects()
      .then((res) => {
        setProjects(res.projects);
        setProjectId((prev) => prev || res.projects[0]?.id || "");
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setSelectedFileIds([]);
    setSelectedRunIds([]);
    if (projectId) {
      void loadProjectContext(projectId);
    }
    void loadDeliverables();
  }, [projectId, loadProjectContext, loadDeliverables]);

  async function handleGenerate(event: FormEvent) {
    event.preventDefault();
    if (!projectId) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const detail = await generateReviewReport(projectId, {
        file_ids: selectedFileIds,
        research_run_ids: selectedRunIds,
        title: title.trim() || null,
        discipline,
        language: reportLang,
        classification,
        review_notes: reviewNotes.trim() || null,
        use_ai: false,
      });
      setActiveReport(detail);
      setTitle("");
      setReviewNotes("");
      await Promise.all([loadProjectContext(projectId), loadDeliverables()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleEnhanceAi(reportId: string) {
    setEnhancing(true);
    setError(null);
    try {
      const enhanced = await enhanceReviewReportAi(reportId, "fast");
      setActiveReport(enhanced);
      if (projectId) {
        await Promise.all([loadProjectContext(projectId), loadDeliverables()]);
      } else {
        await loadDeliverables();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setEnhancing(false);
    }
  }

  async function handleInspectReport(reportId: string) {
    setError(null);
    try {
      const detail = await getReviewReportDetail(reportId);
      setActiveReport(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function renderCategoryList(heading: string, items: CategorizedStatement[]) {
    return (
      <div className="status-box" style={{ marginTop: 0 }}>
        <h5 className="folders-title" style={{ marginTop: 0 }}>
          {heading} ({items.length})
        </h5>
        {items.length === 0 ? (
          <p className="muted-hint" style={{ marginBottom: 0 }}>
            —
          </p>
        ) : (
          <ul className="outcome-list" style={{ marginBottom: 0 }}>
            {items.map((item, i) => (
              <li key={i} dir="auto">
                <div>{item.text}</div>
                {item.formula_or_method && (
                  <div className="muted-hint" style={{ fontSize: "0.82rem" }}>
                    <code>{item.formula_or_method}</code>
                  </div>
                )}
                {item.source_links.length > 0 && (
                  <div className="muted-hint" style={{ fontSize: "0.82rem" }}>
                    {copy.sourcePrefix}: {renderSourceLinks(item.source_links)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <section className="subpanel" aria-label={copy.generatorHeading}>
        <div className="panel-header">
          <div>
            <h3 className="panel-title">{copy.generatorHeading}</h3>
            <p className="muted-hint" style={{ margin: "0.25rem 0 0" }}>
              {copy.generatorHint}
            </p>
          </div>
          <span className="badge">{classification}</span>
        </div>

        <form onSubmit={(e) => void handleGenerate(e)} style={{ display: "grid", gap: "0.75rem" }}>
          <div className="form-grid">
            <label>
              <span>{copy.projectLabel}</span>
              <select
                value={projectId}
                required
                onChange={(e) => setProjectId(e.target.value)}
              >
                <option value="">{copy.selectProjectOpt}</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    [{p.code}] {p.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>{copy.languageLabel}</span>
              <select
                value={reportLang}
                onChange={(e) => setReportLang(e.target.value as ReportLanguage)}
              >
                <option value="ar">{copy.langAr}</option>
                <option value="en">{copy.langEn}</option>
              </select>
            </label>

            <label>
              <span>{copy.classificationLabel}</span>
              <select
                value={classification}
                onChange={(e) => setClassification(e.target.value as ProjectClassification)}
              >
                <option value="Preliminary">Preliminary</option>
                <option value="Conceptual">Conceptual</option>
                <option value="For Review">For Review</option>
                <option value="For Coordination">For Coordination</option>
                <option value="For Approval">For Approval</option>
              </select>
            </label>

            <label>
              <span>{copy.disciplineLabel}</span>
              <input
                type="text"
                dir="auto"
                value={discipline}
                onChange={(e) => setDiscipline(e.target.value)}
              />
            </label>
          </div>

          <div className="form-grid">
            <label>
              <span>{copy.titleLabel}</span>
              <input
                type="text"
                dir="auto"
                placeholder={copy.titlePlaceholder}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              <span>{copy.notesLabel}</span>
              <input
                type="text"
                dir="auto"
                placeholder={copy.notesPlaceholder}
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
              />
            </label>
          </div>

          {projectFiles.length > 0 && (
            <div className="status-box" style={{ marginTop: 0 }}>
              <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>{copy.filesLabel}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.65rem" }}>
                {projectFiles.map((f) => {
                  const checked = selectedFileIds.includes(f.id);
                  return (
                    <label key={f.id} style={{ display: "inline-flex", gap: "0.35rem", alignItems: "center" }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setSelectedFileIds((prev) =>
                            checked ? prev.filter((id) => id !== f.id) : [...prev, f.id]
                          )
                        }
                      />
                      <span dir="auto">{f.original_filename}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {projectRuns.length > 0 && (
            <div className="status-box" style={{ marginTop: 0 }}>
              <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>{copy.researchLabel}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.65rem" }}>
                {projectRuns.map((run) => {
                  const checked = selectedRunIds.includes(run.id);
                  return (
                    <label key={run.id} style={{ display: "inline-flex", gap: "0.35rem", alignItems: "center" }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setSelectedRunIds((prev) =>
                            checked ? prev.filter((id) => id !== run.id) : [...prev, run.id]
                          )
                        }
                      />
                      <span dir="auto">
                        {run.query} ({run.accessible_sources + (run.owner_provided_sources ?? 0)} reviewed)
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <button type="submit" className="btn" disabled={submitting || !projectId}>
              {submitting ? copy.generatingBtn : copy.generateBtn}
            </button>
          </div>
        </form>

        {error && (
          <div className="status-box status-err" style={{ marginTop: "0.75rem" }}>
            {copy.errorPrefix}
            <code>{error}</code>
          </div>
        )}
      </section>

      {reports.length > 0 && (
        <section className="subpanel" aria-label={copy.reportsHistoryHeading}>
          <h4 className="panel-title">
            {copy.reportsHistoryHeading} ({reports.length})
          </h4>
          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>{copy.colVer}</th>
                  <th>{copy.colFile}</th>
                  <th>{copy.colDisc}</th>
                  <th>{copy.colClass}</th>
                  <th>{copy.colStat}</th>
                  <th>{copy.colAction}</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((rep) => (
                  <tr key={rep.id}>
                    <td dir="ltr">
                      v{rep.version} ({rep.revision})
                    </td>
                    <td dir="auto">{rep.title}</td>
                    <td dir="auto">{rep.discipline}</td>
                    <td>
                      <span className="badge">{rep.classification}</span>
                    </td>
                    <td dir="ltr">
                      {rep.status} ({rep.findings_count})
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-compact"
                        onClick={() => void handleInspectReport(rep.id)}
                      >
                        {copy.inspectBtn}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeReport && (
        <section className="subpanel" aria-label={activeReport.title}>
          <div className="panel-header">
            <div>
              <h4 className="panel-title" dir="auto">
                {activeReport.title} — {activeReport.revision} (v{activeReport.version})
              </h4>
              <div className="muted-hint" dir="auto">
                [{activeReport.project_code}] {activeReport.project_name} · {activeReport.discipline}
              </div>
            </div>
            <div className="badge-group">
              <span className="badge">{activeReport.classification}</span>
              <span className="badge" dir="ltr">
                {activeReport.language.toUpperCase()}
              </span>
              <span className="badge" dir="ltr">
                {activeReport.token_usage.total_tokens} tokens
              </span>
            </div>
          </div>

          {activeReport.summary && (
            <p dir="auto" style={{ marginTop: 0, lineHeight: 1.6 }}>
              {activeReport.summary}
            </p>
          )}

          {activeReport.source_registry.length > 0 && activeReport.token_usage.total_tokens === 0 && (
            <div className="status-box notice-box" style={{ marginBottom: "0.75rem" }}>
              <div style={{ fontWeight: 600, marginBottom: "0.3rem" }}>{copy.tokenEstimateHeading}</div>
              <div dir="auto" style={{ marginBottom: "0.45rem" }}>
                <code>~{activeReport.estimated_prompt_tokens ?? 0} est. prompt tokens</code> (
                {activeReport.prompt_char_count ?? 0} / {activeReport.prompt_char_cap ?? 10000} chars cap)
                {activeReport.step04_daily_tokens_remaining != null && (
                  <span>
                    {" "}
                    · Step 04 daily remaining:{" "}
                    <strong>{activeReport.step04_daily_tokens_remaining.toLocaleString()}</strong> tokens
                  </span>
                )}
              </div>
              <button
                type="button"
                className="btn btn-compact"
                disabled={enhancing}
                onClick={() => void handleEnhanceAi(activeReport.id)}
              >
                {enhancing
                  ? copy.enhancingBtn
                  : `${copy.enhanceAiBtn} (~${activeReport.estimated_prompt_tokens ?? 0} est. tokens)`}
              </button>
            </div>
          )}

          <div className="status-box" style={{ marginBottom: "0.9rem" }}>
            <h5 className="folders-title" style={{ marginTop: 0 }}>
              {copy.revisionBlockHeading}
            </h5>
            <div dir="auto" style={{ display: "grid", gap: "0.25rem", fontSize: "0.9rem" }}>
              <div>
                <strong>v{activeReport.revision_block.version}</strong> ({activeReport.revision_block.revision}) ·{" "}
                <span className="badge">{activeReport.revision_block.classification}</span>
              </div>
              <div>
                {activeReport.revision_block.prepared_by} — {activeReport.revision_block.review_notice}
              </div>
              <div dir="ltr" className="muted-hint">
                {activeReport.revision_block.issued_at_iso} · Files={activeReport.revision_block.source_files_count}, Reviewed Research={activeReport.revision_block.reviewed_research_count}
              </div>
              <div dir="auto">{activeReport.revision_block.change_note}</div>
            </div>
          </div>

          <h5 className="folders-title">
            {copy.findingsHeading} ({activeReport.findings.length})
          </h5>
          <div className="table-wrap" style={{ marginBottom: "0.9rem" }}>
            <table className="files-table">
              <thead>
                <tr>
                  <th>{copy.colFindingId}</th>
                  <th>{copy.colDisc}</th>
                  <th>{copy.colSev}</th>
                  <th>{copy.colLocRef}</th>
                  <th>{copy.colEvidenceSource}</th>
                  <th>{copy.colRec}</th>
                  <th>{copy.colStat}</th>
                </tr>
              </thead>
              <tbody>
                {activeReport.findings.map((f) => (
                  <tr key={f.finding_id}>
                    <td dir="ltr">
                      <strong>{f.finding_id}</strong>
                    </td>
                    <td dir="auto">{f.discipline}</td>
                    <td>
                      <span className={`badge ${f.severity === "high" || f.severity === "critical" ? "badge-warn" : ""}`}>
                        {f.severity}
                      </span>
                    </td>
                    <td dir="auto">{f.location_or_drawing_ref}</td>
                    <td dir="auto">
                      <div>{f.evidence}</div>
                      <div className="muted-hint" style={{ fontSize: "0.8rem", marginTop: "0.2rem" }}>
                        {copy.sourcePrefix}: {renderSourceLinks(f.source_links)}
                      </div>
                    </td>
                    <td dir="auto">{f.recommendation}</td>
                    <td dir="ltr">{f.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: "grid", gap: "0.75rem", marginBottom: "0.9rem" }}>
            {renderCategoryList(copy.factsHeading, activeReport.verified_facts)}
            {renderCategoryList(copy.calculatedHeading, activeReport.calculated_items)}
            {renderCategoryList(copy.assumptionsHeading, activeReport.assumptions)}
            {renderCategoryList(copy.recommendationsHeading, activeReport.recommendations)}
          </div>

          {activeReport.gaps_or_unextracted.length > 0 && (
            <div className="status-box notice-box" style={{ marginBottom: "0.75rem" }}>
              <strong>{copy.gapsHeading}:</strong>
              <ul className="outcome-list">
                {activeReport.gaps_or_unextracted.map((gap, idx) => (
                  <li key={idx} dir="auto">
                    {gap}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <section className="subpanel" aria-label={copy.deliverablesHeading}>
        <div className="panel-header">
          <h3 className="panel-title">
            {copy.deliverablesHeading} ({deliverables.length})
          </h3>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <label style={{ display: "inline-flex", gap: "0.35rem", alignItems: "center" }}>
              <span>{copy.folderFilterLabel}:</span>
              <select value={folderFilter} onChange={(e) => setFolderFilter(e.target.value)}>
                <option value="">{copy.folderAll}</option>
                <option value="08_Reports">08_Reports</option>
                <option value="10_Final_Deliverables">10_Final_Deliverables</option>
              </select>
            </label>
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => void loadDeliverables()}
            >
              {copy.refreshBtn}
            </button>
          </div>
        </div>

        {deliverables.length === 0 ? (
          <p className="muted-hint">{copy.emptyDeliverables}</p>
        ) : (
          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>{copy.colFolder}</th>
                  <th>{copy.colFile}</th>
                  <th>{copy.colFormat}</th>
                  <th>{copy.colVer}</th>
                  <th>{copy.colClass}</th>
                  <th>{copy.colIntegrity}</th>
                  <th>{copy.colAction}</th>
                </tr>
              </thead>
              <tbody>
                {deliverables.map((d) => (
                  <tr key={d.id}>
                    <td dir="ltr">
                      <code>{d.folder_name || "—"}</code>
                    </td>
                    <td dir="auto">
                      <div>
                        <strong>{d.title}</strong>
                      </div>
                      <code dir="ltr">{d.relative_path || d.filename}</code>
                    </td>
                    <td dir="ltr">
                      <strong>{d.format.toUpperCase()}</strong>
                    </td>
                    <td dir="ltr">v{d.version}</td>
                    <td>
                      <span className="badge">{d.classification}</span>
                    </td>
                    <td dir="ltr">
                      <div>{d.size_bytes != null ? `${d.size_bytes.toLocaleString()} B` : "—"}</div>
                      {d.sha256 && <code>{d.sha256.slice(0, 12)}...</code>}
                    </td>
                    <td>
                      <a className="btn btn-compact" href={d.download_url} download={d.filename || undefined}>
                        {copy.downloadBtn} ({d.format.toUpperCase()})
                      </a>
                    </td>
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
