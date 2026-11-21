import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  createManualIssue,
  listProjectIssues,
  listProjectQaReviews,
  listProjects,
  listTasks,
  runProjectQaReview,
  updateQaIssue,
  verifyTaskWithQa,
} from "../api";
import type {
  IssueOut,
  IssueSeverity,
  Lang,
  ProjectSummary,
  QaReviewDetailOut,
  TaskSummaryOut,
} from "../types";

interface QaCopy {
  heading: string;
  subtitle: string;
  projectLabel: string;
  taskLabel: string;
  allProjectDeliverablesOpt: string;
  runQaBtn: string;
  runningQaBtn: string;
  verifyTaskBtn: string;
  verifyingTaskBtn: string;
  isolationBanner: string;
  checksHeading: string;
  issuesHeading: string;
  statusFilterLabel: string;
  filterAll: string;
  filterOpen: string;
  filterClosed: string;
  noIssues: string;
  closeIssueBtn: string;
  reopenIssueBtn: string;
  closureNotePrompt: string;
  addManualHeading: string;
  descLabel: string;
  disciplineLabel: string;
  severityLabel: string;
  refLabel: string;
  actionLabel: string;
  addManualBtn: string;
  colNo: string;
  colDesc: string;
  colDisc: string;
  colSeverity: string;
  colRef: string;
  colAction: string;
  colStatus: string;
  colOps: string;
  openCountLabel: string;
  closedCountLabel: string;
}

const COPY: Record<Lang, QaCopy> = {
  ar: {
    heading: "وكيل مراجعة الجودة المستقل وسجل القضايا (QA)",
    subtitle:
      "مراجعة مستقلة تماماً عن منطق واستنتاجات المُنتِج (0 توكن ذكاء اصطناعي): إعادة حساب الكميات برمجياً، تدقيق الوحدات، التحقق من المراجع في سجل المصادر، مطابقة الجداول واللوحات، وفحص اكتمال المخرجات. لا يُعتمد أي تكليف كمُتحقَّق بمجرد التوليد.",
    projectLabel: "المشروع",
    taskLabel: "التكليف المستهدف (اختياري للتحقق)",
    allProjectDeliverablesOpt: "كافة مخرجات المشروع",
    runQaBtn: "تشغيل فحص الجودة المستقل (0 توكن)",
    runningQaBtn: "جاري تشغيل الفحص المستقل...",
    verifyTaskBtn: "اعتماد تحقق التكليف (يتطلب نجاح QA وإغلاق كل القضايا)",
    verifyingTaskBtn: "جاري التحقق...",
    isolationBanner:
      "عزل سياق الجودة المستقل مُفعَّل: تم استبعاد خطط وافتراضات ونتائج المُنتِج تماماً عن فحص QA.",
    checksHeading: "نتائج فحوصات التدقيق المستقلة",
    issuesHeading: "سجل قضايا الجودة (Issue Register)",
    statusFilterLabel: "تصفية الحالة",
    filterAll: "الكل",
    filterOpen: "مفتوحة (Open)",
    filterClosed: "مغلقة (Closed)",
    noIssues: "لا توجد قضايا مسجلة في هذا التصنيف.",
    closeIssueBtn: "إغلاق القضية",
    reopenIssueBtn: "إعادة فتح",
    closureNotePrompt: "ملاحظة الإغلاق / الإجراء التصحيحي المتخذ (اختياري):",
    addManualHeading: "إضافة قضية جودة يدوياً",
    descLabel: "الوصف الهندسي للمشكلة",
    disciplineLabel: "التخصص",
    severityLabel: "الخطورة",
    refLabel: "المرجع / اللوحة / البند",
    actionLabel: "الإجراء التصحيحي المطلوب",
    addManualBtn: "إضافة لسجل القضايا",
    colNo: "الرقم",
    colDesc: "الوصف",
    colDisc: "التخصص",
    colSeverity: "الخطورة",
    colRef: "المرجع",
    colAction: "الإجراء التصحيحي",
    colStatus: "الحالة",
    colOps: "إجراء",
    openCountLabel: "مفتوحة",
    closedCountLabel: "مغلقة",
  },
  en: {
    heading: "Independent QA Agent & Issue Register",
    subtitle:
      "Runs on an isolated context that never sees producer reasoning (0 AI tokens): recomputes arithmetic in code, verifies units, checks references against verified source logs, cross-checks drawing/BOQ/schedule consistency, and audits missing deliverables. Tasks can never be marked verified by generation alone.",
    projectLabel: "Project",
    taskLabel: "Target Task (optional Verification Gate)",
    allProjectDeliverablesOpt: "All Project Deliverables",
    runQaBtn: "Run Independent QA Review (0 AI Tokens)",
    runningQaBtn: "Running Independent QA...",
    verifyTaskBtn: "Verify Task (Requires Passing QA & 0 Open Issues)",
    verifyingTaskBtn: "Verifying...",
    isolationBanner:
      "Independent QA Isolation Verified: producer plan_summary, result_summary, and step reasoning excluded.",
    checksHeading: "Deterministic Independent QA Check Results",
    issuesHeading: "Engineering Issue Register",
    statusFilterLabel: "Status Filter",
    filterAll: "All",
    filterOpen: "Open",
    filterClosed: "Closed",
    noIssues: "No QA issues match the current filter.",
    closeIssueBtn: "Close Issue",
    reopenIssueBtn: "Reopen",
    closureNotePrompt: "Closure note / verified corrective evidence (optional):",
    addManualHeading: "Log Manual QA Issue",
    descLabel: "Issue Description",
    disciplineLabel: "Discipline",
    severityLabel: "Severity",
    refLabel: "Reference / Drawing / Item",
    actionLabel: "Required Corrective Action",
    addManualBtn: "Add Issue",
    colNo: "No.",
    colDesc: "Description",
    colDisc: "Discipline",
    colSeverity: "Severity",
    colRef: "Reference",
    colAction: "Corrective Action",
    colStatus: "Status",
    colOps: "Action",
    openCountLabel: "Open",
    closedCountLabel: "Closed",
  },
};

export interface QaIssuesViewProps {
  lang: Lang;
  initialReview?: QaReviewDetailOut | null;
  initialIssues?: IssueOut[];
}

export function QaIssuesView({
  lang,
  initialReview = null,
  initialIssues,
}: QaIssuesViewProps) {
  const copy = COPY[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [tasks, setTasks] = useState<TaskSummaryOut[]>([]);
  const [taskId, setTaskId] = useState<string>("");

  const [latestReview, setLatestReview] = useState<QaReviewDetailOut | null>(initialReview);
  const [issues, setIssues] = useState<IssueOut[]>(initialIssues ?? []);
  const [openCount, setOpenCount] = useState<number>(
    (initialIssues ?? []).filter((i) => i.status !== "closed").length
  );
  const [closedCount, setClosedCount] = useState<number>(
    (initialIssues ?? []).filter((i) => i.status === "closed").length
  );
  const [statusFilter, setStatusFilter] = useState<string>("");

  const [closureNotesById, setClosureNotesById] = useState<Record<string, string>>({});
  const [manualDesc, setManualDesc] = useState("");
  const [manualDisc, setManualDisc] = useState("multidisciplinary");
  const [manualSev, setManualSev] = useState<IssueSeverity>("medium");
  const [manualRef, setManualRef] = useState("");
  const [manualAction, setManualAction] = useState("");

  const [runningQa, setRunningQa] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshData = useCallback(
    async (pid: string, sFilter: string) => {
      if (!pid) {
        setTasks([]);
        setLatestReview(initialReview ?? null);
        setIssues(initialIssues ?? []);
        return;
      }
      try {
        const [taskRes, revRes, issRes] = await Promise.all([
          listTasks({ projectId: pid }),
          listProjectQaReviews(pid),
          listProjectIssues(pid, sFilter ? { status: sFilter } : undefined),
        ]);
        setTasks(taskRes.tasks);
        setLatestReview(revRes.reviews[0] ?? null);
        setIssues(issRes.issues);
        setOpenCount(issRes.open_count);
        setClosedCount(issRes.closed_count);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [initialIssues, initialReview]
  );

  useEffect(() => {
    void (async () => {
      try {
        const res = await listProjects();
        setProjects(res.projects);
        if (res.projects.length > 0) {
          setProjectId((prev) => prev || res.projects[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  useEffect(() => {
    if (projectId) {
      void refreshData(projectId, statusFilter);
    }
  }, [projectId, statusFilter, refreshData]);

  async function handleRunQa() {
    if (!projectId) return;
    setRunningQa(true);
    setError(null);
    setStatusMsg(null);
    try {
      const rev = await runProjectQaReview(projectId, {
        task_id: taskId || null,
      });
      setLatestReview(rev);
      await refreshData(projectId, statusFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunningQa(false);
    }
  }

  async function handleVerifyTask() {
    if (!taskId) return;
    setVerifying(true);
    setError(null);
    setStatusMsg(null);
    try {
      const res = await verifyTaskWithQa(taskId, {
        qa_review_id: latestReview?.id ?? null,
      });
      setStatusMsg(res.message);
      await refreshData(projectId, statusFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setVerifying(false);
    }
  }

  async function handleToggleIssueStatus(issue: IssueOut) {
    setError(null);
    setStatusMsg(null);
    const closing = issue.status !== "closed";
    try {
      await updateQaIssue(issue.id, {
        status: closing ? "closed" : "open",
        closure_note: closing ? (closureNotesById[issue.id] || "").trim() || "Closed in QA Register" : undefined,
      });
      await refreshData(projectId, statusFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleAddManual(e: FormEvent) {
    e.preventDefault();
    if (!projectId || !manualDesc.trim() || !manualAction.trim()) return;
    setError(null);
    setStatusMsg(null);
    try {
      await createManualIssue(projectId, {
        task_id: taskId || null,
        description: manualDesc.trim(),
        discipline: manualDisc.trim() || "multidisciplinary",
        severity: manualSev,
        reference: manualRef.trim() || null,
        corrective_action: manualAction.trim(),
      });
      setManualDesc("");
      setManualRef("");
      setManualAction("");
      await refreshData(projectId, statusFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const selectedTask = tasks.find((t) => t.id === taskId);

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

        <div className="form-grid" style={{ marginBottom: "0.75rem" }}>
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
              <option value="">{copy.allProjectDeliverablesOpt}</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title} [{t.verification_status ?? "unverified"}]
                </option>
              ))}
            </select>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
          <button
            type="button"
            className="btn"
            disabled={!projectId || runningQa}
            onClick={() => void handleRunQa()}
          >
            {runningQa ? copy.runningQaBtn : copy.runQaBtn}
          </button>

          {taskId && (
            <>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={verifying}
                onClick={() => void handleVerifyTask()}
              >
                {verifying ? copy.verifyingTaskBtn : copy.verifyTaskBtn}
              </button>
              {selectedTask && (
                <span className="badge">
                  verification: {selectedTask.verification_status ?? "unverified"}
                </span>
              )}
            </>
          )}
        </div>
      </section>

      {latestReview && (
        <section className="subpanel" aria-label={copy.checksHeading}>
          <div className="panel-header">
            <h3 className="panel-title">{copy.checksHeading}</h3>
            <span className={`badge ${latestReview.status === "passed" ? "badge-ok" : ""}`}>
              {latestReview.status} · {latestReview.open_issues_count} open
            </span>
          </div>

          {latestReview.producer_reasoning_excluded && (
            <div className="status-box status-ok" style={{ marginBottom: "0.75rem" }}>
              <strong>{copy.isolationBanner}</strong>{" "}
              <span dir="ltr">
                (Excluded: {latestReview.qa_context_summary.excluded_fields.join(", ")})
              </span>
            </div>
          )}

          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Checked</th>
                  <th>Failed</th>
                  <th>Outcome</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {latestReview.checks.map((chk) => (
                  <tr key={chk.category}>
                    <td dir="ltr">
                      <code>{chk.category}</code>
                    </td>
                    <td dir="ltr">{chk.checked_count}</td>
                    <td dir="ltr">{chk.failed_count}</td>
                    <td>
                      <span className={`badge ${chk.passed ? "badge-ok" : "badge-warn"}`}>
                        {chk.passed ? "PASS" : "FAIL"}
                      </span>
                    </td>
                    <td dir="auto">{chk.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="subpanel" aria-label={copy.issuesHeading}>
        <div className="panel-header">
          <div>
            <h3 className="panel-title">
              {copy.issuesHeading} ({openCount} {copy.openCountLabel} / {closedCount} {copy.closedCountLabel})
            </h3>
          </div>
          <label style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
            <span>{copy.statusFilterLabel}:</span>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">{copy.filterAll}</option>
              <option value="open">{copy.filterOpen}</option>
              <option value="closed">{copy.filterClosed}</option>
            </select>
          </label>
        </div>

        {issues.length === 0 ? (
          <p className="muted-hint">{copy.noIssues}</p>
        ) : (
          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>{copy.colNo}</th>
                  <th>{copy.colDesc}</th>
                  <th>{copy.colDisc}</th>
                  <th>{copy.colSeverity}</th>
                  <th>{copy.colRef}</th>
                  <th>{copy.colAction}</th>
                  <th>{copy.colStatus}</th>
                  <th>{copy.colOps}</th>
                </tr>
              </thead>
              <tbody>
                {issues.map((it) => (
                  <tr key={it.id}>
                    <td dir="ltr">
                      <strong>{it.issue_number}</strong>
                      <div className="muted-hint" style={{ fontSize: "0.75rem" }}>
                        {it.check_category}
                      </div>
                    </td>
                    <td dir="auto">{it.description}</td>
                    <td dir="auto">{it.discipline}</td>
                    <td dir="ltr">
                      <span className={`badge ${it.severity === "critical" || it.severity === "high" ? "badge-warn" : ""}`}>
                        {it.severity}
                      </span>
                    </td>
                    <td dir="auto">{it.reference || "—"}</td>
                    <td dir="auto">
                      <div>{it.corrective_action || it.recommended_action || "—"}</div>
                      {it.closure_note && (
                        <div className="muted-hint" style={{ fontSize: "0.78rem" }}>
                          {it.closure_note}
                        </div>
                      )}
                    </td>
                    <td dir="ltr">
                      <span className={`badge ${it.status === "closed" ? "badge-ok" : "badge-warn"}`}>
                        {it.status}
                      </span>
                    </td>
                    <td>
                      {it.status !== "closed" && (
                        <input
                          type="text"
                          style={{ width: "9rem", marginBottom: "0.25rem", display: "block" }}
                          placeholder={copy.closureNotePrompt}
                          value={closureNotesById[it.id] || ""}
                          onChange={(e) =>
                            setClosureNotesById((prev) => ({ ...prev, [it.id]: e.target.value }))
                          }
                        />
                      )}
                      <button
                        type="button"
                        className="btn btn-compact btn-secondary"
                        onClick={() => void handleToggleIssueStatus(it)}
                      >
                        {it.status === "closed" ? copy.reopenIssueBtn : copy.closeIssueBtn}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <form onSubmit={(e) => void handleAddManual(e)} className="form-grid" style={{ marginTop: "1rem" }}>
          <h4 style={{ gridColumn: "1 / -1", margin: "0.25rem 0" }}>{copy.addManualHeading}</h4>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <span>{copy.descLabel}</span>
            <input type="text" value={manualDesc} onChange={(e) => setManualDesc(e.target.value)} required />
          </div>
          <div className="field">
            <span>{copy.disciplineLabel}</span>
            <input type="text" value={manualDisc} onChange={(e) => setManualDisc(e.target.value)} required />
          </div>
          <div className="field">
            <span>{copy.severityLabel}</span>
            <select value={manualSev} onChange={(e) => setManualSev(e.target.value as IssueSeverity)}>
              <option value="critical">critical</option>
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
          </div>
          <div className="field">
            <span>{copy.refLabel}</span>
            <input type="text" value={manualRef} onChange={(e) => setManualRef(e.target.value)} />
          </div>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <span>{copy.actionLabel}</span>
            <input type="text" value={manualAction} onChange={(e) => setManualAction(e.target.value)} required />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <button type="submit" className="btn btn-secondary" disabled={!projectId}>
              {copy.addManualBtn}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
