import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import {
  createTask,
  getTaskDetail,
  listProjectFiles,
  listProjects,
  listTasks,
  uploadProjectFiles,
} from "../api";
import type {
  Lang,
  ProjectClassification,
  ProjectFileOut,
  ProjectSummary,
  TaskComplexity,
  TaskDetailOut,
  TaskSummaryOut,
} from "../types";

interface AssignmentsCopy {
  formHeading: string;
  formHint: string;
  projectLabel: string;
  noProjectsHint: string;
  titleLabel: string;
  titlePlaceholder: string;
  promptLabel: string;
  promptPlaceholder: string;
  complexityLabel: string;
  complexityFast: string;
  complexityDeep: string;
  classificationLabel: string;
  existingFilesLabel: string;
  noProjectFiles: string;
  uploadNewFilesLabel: string;
  selectedUploadPrefix: string;
  submitBtn: string;
  submittingBtn: string;
  submitFailedBanner: string;
  historyHeading: string;
  refreshHistoryBtn: string;
  filterProjectLabel: string;
  allProjectsOption: string;
  filterStatusLabel: string;
  allStatusesOption: string;
  loadingHistory: string;
  emptyHistory: string;
  inspectBtn: string;
  inspectingBtn: string;
  detailHeading: string;
  restatedLabel: string;
  languageLabel: string;
  disciplineLabel: string;
  deliverablesLabel: string;
  inputFilesLabel: string;
  standardsLabel: string;
  standardsNote: string;
  missingInfoLabel: string;
  assumptionsLabel: string;
  clarificationsNeededLabel: string;
  noClarificationsNeeded: string;
  nextStepsLabel: string;
  attachedFilesLabel: string;
  stepsLabel: string;
  logsLabel: string;
  usageLabel: string;
  rawJsonLabel: string;
  promptSnapshotLabel: string;
  errorPrefix: string;
}

const COPY: Record<Lang, AssignmentsCopy> = {
  ar: {
    formHeading: "تكليف هندسي جديد (Orchestrator v0)",
    formHint:
      "اكتب التكليف بالعربية أو الإنجليزية أو بشكل مختلط، واختر المشروع وأرفق الملفات ذات الصلة ليقوم المنسّق الأولي بإعادة صياغته وتحديد التخصص والمعايير الواجب التحقق منها بصيغة JSON مهيكلة.",
    projectLabel: "المشروع الهندسي *",
    noProjectsHint: "أنشئ مشروعاً أولاً من تبويب «المشاريع والملفات» ثم عد إلى هنا.",
    titleLabel: "عنوان المهمة (اختياري — يُشتق تلقائياً إذا تُرك فارغاً)",
    titlePlaceholder: "مثال: مراجعة المخطط المعماري لعيادة طرابلس",
    promptLabel: "نص التكليف الهندسي *",
    promptPlaceholder:
      "اكتب التعليمات الهندسية كاملة مع الأبعاد أو الملاحظات وأسماء الملفات المطلوب مراجعتها...",
    complexityLabel: "مستوى التحليل (Complexity)",
    complexityFast: "سريع (Fast — نماذج Flash)",
    complexityDeep: "عميق (Deep — نماذج الاستدلال العميق)",
    classificationLabel: "التصنيف المبدئي",
    existingFilesLabel: "إرفاق ملفات مرفوعة مسبقاً في المشروع",
    noProjectFiles: "لا توجد ملفات مرفوعة في هذا المشروع بعد.",
    uploadNewFilesLabel: "أو ارفع ملفات جديدة وأرفقها مع التكليف (اختياري)",
    selectedUploadPrefix: "ملفات جديدة جاهزة للرفع والإرفاق:",
    submitBtn: "إرسال التكليف وتشغيل المنسّق (Orchestrator v0)",
    submittingBtn: "جاري تسجيل المهمة وتشغيل المنسّق...",
    submitFailedBanner: "تم تسجيل فشل تنفيذ المهمة في السجل ولم يتم إخفاؤه:",
    historyHeading: "سجل المهام والتكليفات (Task History)",
    refreshHistoryBtn: "تحديث السجل",
    filterProjectLabel: "تصفية حسب المشروع",
    allProjectsOption: "جميع المشاريع",
    filterStatusLabel: "الحالة",
    allStatusesOption: "كل الحالات",
    loadingHistory: "جاري تحميل سجل المهام...",
    emptyHistory: "لا توجد مهام مسجلة تطابق الفلتر الحالي.",
    inspectBtn: "عرض التفاصيل",
    inspectingBtn: "جاري الفتح...",
    detailHeading: "تفاصيل المهمة ومخرجات المنسّق (Structured JSON)",
    restatedLabel: "إعادة صياغة التكليف",
    languageLabel: "اللغة المكتشفة",
    disciplineLabel: "التخصص الأساسي والتخصصات المساندة",
    deliverablesLabel: "المخرجات المتوقعة",
    inputFilesLabel: "ملفات الإدخال المحددة",
    standardsLabel: "المعايير والكودات المرشحة للتحقق",
    standardsNote:
      "للمراجعة لاحقاً عبر مكتبة المعايير أو البحث الموثق — لا تمثل مطابقة معتمدة بعد.",
    missingInfoLabel: "المعلومات الناقصة",
    assumptionsLabel: "الافتراضات الأولية",
    clarificationsNeededLabel: "أسئلة استيضاحية مؤثرة على النتيجة",
    noClarificationsNeeded: "لا توجد أسئلة استيضاحية معطّلة؛ يمكن المتابعة بالافتراضات المعلنة.",
    nextStepsLabel: "الخطوات التالية المقترحة",
    attachedFilesLabel: "الملفات المرفقة بالمهمة",
    stepsLabel: "خطوات التنفيذ (Task Steps)",
    logsLabel: "سجل التدقيق والأحداث (Task Logs)",
    usageLabel: "استهلاك الرموز والمزود",
    rawJsonLabel: "عرض JSON المهيكل الكامل",
    promptSnapshotLabel: "نص التكليف الأصلي",
    errorPrefix: "تعذر تنفيذ العملية: ",
  },
  en: {
    formHeading: "New Engineering Assignment (Orchestrator v0)",
    formHint:
      "Enter instructions in Arabic, English, or mixed phrasing, pick a project, and attach files. Orchestrator v0 restates the task, identifies disciplines, deliverables, files, candidate standards to verify, gaps, assumptions, and clarifying questions as structured JSON.",
    projectLabel: "Engineering Project *",
    noProjectsHint: "Create a project first in the Projects & Files tab.",
    titleLabel: "Task Title (optional — auto-derived if blank)",
    titlePlaceholder: "Example: Review outpatient clinic architectural layout",
    promptLabel: "Assignment Instructions *",
    promptPlaceholder:
      "Describe the engineering assignment, dimensions, constraints, and referenced drawings/files...",
    complexityLabel: "Model Tier (Complexity)",
    complexityFast: "Fast (Flash tier)",
    complexityDeep: "Deep (Reasoning tier)",
    classificationLabel: "Initial Classification",
    existingFilesLabel: "Attach existing files from the selected project",
    noProjectFiles: "No files uploaded in this project yet.",
    uploadNewFilesLabel: "Or upload & attach new local files with this task (optional)",
    selectedUploadPrefix: "New files staged for upload:",
    submitBtn: "Submit Assignment & Run Orchestrator v0",
    submittingBtn: "Recording task & running Orchestrator v0...",
    submitFailedBanner: "Task execution failed and was recorded in history (never hidden):",
    historyHeading: "Task History",
    refreshHistoryBtn: "Refresh History",
    filterProjectLabel: "Filter by Project",
    allProjectsOption: "All Projects",
    filterStatusLabel: "Filter by Status",
    allStatusesOption: "All Statuses",
    loadingHistory: "Loading task history...",
    emptyHistory: "No tasks recorded matching the current filters.",
    inspectBtn: "Inspect Task",
    inspectingBtn: "Loading...",
    detailHeading: "Task Details & Structured Orchestrator Output",
    restatedLabel: "Restated Assignment",
    languageLabel: "Detected Language",
    disciplineLabel: "Primary & Secondary Disciplines",
    deliverablesLabel: "Expected Deliverables",
    inputFilesLabel: "Identified Input Files",
    standardsLabel: "Applicable Standards to Verify",
    standardsNote:
      "Candidate references only — must be verified against official sources before citing compliance.",
    missingInfoLabel: "Missing Information",
    assumptionsLabel: "Preliminary Assumptions",
    clarificationsNeededLabel: "Material Clarifying Questions",
    noClarificationsNeeded:
      "No material blocking questions needed; proceed with documented assumptions.",
    nextStepsLabel: "Recommended Next Steps",
    attachedFilesLabel: "Attached Project Files",
    stepsLabel: "Execution Steps",
    logsLabel: "Audit & Failure Logs",
    usageLabel: "Provider & Token Usage",
    rawJsonLabel: "Inspect Raw Structured JSON",
    promptSnapshotLabel: "Original Assignment Prompt",
    errorPrefix: "Operation failed: ",
  },
};

const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

function statusBadgeClass(statusValue: string): string {
  if (statusValue === "completed") {
    return "badge badge-connected";
  }
  if (statusValue === "failed") {
    return "badge badge-err";
  }
  if (statusValue === "awaiting_clarification") {
    return "badge badge-warn";
  }
  return "badge";
}

function statusDisplayLabel(statusValue: string, lang: Lang): string {
  if (lang === "ar") {
    if (statusValue === "completed") return "مكتمل";
    if (statusValue === "awaiting_clarification") return "بانتظار توضيح";
    if (statusValue === "failed") return "فشل التنفيذ";
    if (statusValue === "running") return "قيد التنفيذ";
    return statusValue;
  }
  if (statusValue === "awaiting_clarification") return "Awaiting Clarification";
  if (statusValue === "completed") return "Completed";
  if (statusValue === "failed") return "Failed";
  return statusValue;
}

export interface AssignmentsViewProps {
  lang: Lang;
  initialProjects?: ProjectSummary[];
  initialTasks?: TaskSummaryOut[];
  initialSelectedTask?: TaskDetailOut | null;
}

export function AssignmentsView({
  lang,
  initialProjects,
  initialTasks,
  initialSelectedTask = null,
}: AssignmentsViewProps) {
  const copy = COPY[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>(initialProjects ?? []);
  const [selectedProjectId, setSelectedProjectId] = useState<string>(
    initialProjects?.[0]?.id ?? ""
  );
  const [projectFiles, setProjectFiles] = useState<ProjectFileOut[]>([]);
  const [attachedFileIds, setAttachedFileIds] = useState<string[]>([]);
  const [stagedUploadFiles, setStagedUploadFiles] = useState<File[]>([]);

  const [title, setTitle] = useState<string>("");
  const [prompt, setPrompt] = useState<string>("");
  const [complexity, setComplexity] = useState<TaskComplexity>("fast");
  const [classification, setClassification] =
    useState<ProjectClassification>("Preliminary");

  const [submitting, setSubmitting] = useState<boolean>(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [failedTaskNotice, setFailedTaskNotice] = useState<string | null>(null);

  const [tasks, setTasks] = useState<TaskSummaryOut[]>(initialTasks ?? []);
  const [loadingTasks, setLoadingTasks] = useState<boolean>(false);
  const [filterProjectId, setFilterProjectId] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");

  const [selectedTask, setSelectedTask] = useState<TaskDetailOut | null>(
    initialSelectedTask
  );
  const [loadingTaskId, setLoadingTaskId] = useState<string | null>(null);

  const refreshProjects = useCallback(async () => {
    try {
      const data = await listProjects();
      setProjects(data.projects);
      setSelectedProjectId((current) =>
        current && data.projects.some((p) => p.id === current)
          ? current
          : data.projects[0]?.id ?? ""
      );
    } catch {
      // Leave projects empty until created or backend recovers
    }
  }, []);

  const refreshProjectFiles = useCallback(async (projectId: string) => {
    if (!projectId) {
      setProjectFiles([]);
      setAttachedFileIds([]);
      return;
    }
    try {
      const res = await listProjectFiles(projectId);
      setProjectFiles(res.files);
      setAttachedFileIds([]);
    } catch {
      setProjectFiles([]);
      setAttachedFileIds([]);
    }
  }, []);

  const refreshHistory = useCallback(
    async (projectFilter?: string, statusFilter?: string) => {
      setLoadingTasks(true);
      try {
        const res = await listTasks({
          projectId: projectFilter || undefined,
          status: statusFilter || undefined,
        });
        setTasks(res.tasks);
      } catch (err) {
        setFormError(
          copy.errorPrefix + (err instanceof Error ? err.message : String(err))
        );
      } finally {
        setLoadingTasks(false);
      }
    },
    [copy.errorPrefix]
  );

  useEffect(() => {
    if (!initialProjects) {
      void refreshProjects();
    }
  }, [initialProjects, refreshProjects]);

  useEffect(() => {
    void refreshProjectFiles(selectedProjectId);
  }, [selectedProjectId, refreshProjectFiles]);

  useEffect(() => {
    if (!initialTasks) {
      void refreshHistory(filterProjectId, filterStatus);
    }
  }, [initialTasks, refreshHistory, filterProjectId, filterStatus]);

  function handleToggleExistingFile(fileId: string): void {
    setAttachedFileIds((prev) =>
      prev.includes(fileId)
        ? prev.filter((item) => item !== fileId)
        : [...prev, fileId]
    );
  }

  function handleStageFiles(event: ChangeEvent<HTMLInputElement>): void {
    const selected = event.target.files ? Array.from(event.target.files) : [];
    setStagedUploadFiles(selected);
  }

  async function handleInspectTask(taskId: string): Promise<void> {
    setLoadingTaskId(taskId);
    setFormError(null);
    try {
      const detail = await getTaskDetail(taskId);
      setSelectedTask(detail);
    } catch (err) {
      setFormError(
        copy.errorPrefix + (err instanceof Error ? err.message : String(err))
      );
    } finally {
      setLoadingTaskId(null);
    }
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedProjectId || !prompt.trim()) {
      return;
    }
    setSubmitting(true);
    setFormError(null);
    setFailedTaskNotice(null);

    try {
      const finalFileIds = [...attachedFileIds];
      if (stagedUploadFiles.length > 0) {
        const uploadRes = await uploadProjectFiles(selectedProjectId, stagedUploadFiles);
        for (const item of uploadRes.items) {
          if (!finalFileIds.includes(item.file.id)) {
            finalFileIds.push(item.file.id);
          }
        }
        setStagedUploadFiles([]);
        await refreshProjectFiles(selectedProjectId);
      }

      const created = await createTask({
        project_id: selectedProjectId,
        prompt: prompt.trim(),
        title: title.trim() || null,
        complexity,
        attached_file_ids: finalFileIds,
        classification,
      });

      setSelectedTask(created);
      if (created.status === "failed") {
        setFailedTaskNotice(created.error_message || "Task execution failed.");
      } else {
        setTitle("");
        setPrompt("");
        setAttachedFileIds([]);
      }
      await refreshHistory(filterProjectId, filterStatus);
    } catch (err) {
      setFormError(
        copy.errorPrefix + (err instanceof Error ? err.message : String(err))
      );
    } finally {
      setSubmitting(false);
    }
  }

  const understanding = selectedTask?.structured_output ?? null;

  return (
    <div className="workspace-section">
      <section className="subpanel" aria-label={copy.formHeading}>
        <h2 className="panel-title">{copy.formHeading}</h2>
        <p className="muted-line">{copy.formHint}</p>

        <form className="project-form" onSubmit={(e) => void handleSubmit(e)}>
          <div className="form-grid">
            <label className="field">
              <span>{copy.projectLabel}</span>
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                required
              >
                {projects.length === 0 ? (
                  <option value="">{copy.noProjectsHint}</option>
                ) : (
                  projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} — {p.name}
                    </option>
                  ))
                )}
              </select>
            </label>

            <label className="field">
              <span>{copy.titleLabel}</span>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={copy.titlePlaceholder}
              />
            </label>

            <label className="field">
              <span>{copy.complexityLabel}</span>
              <select
                value={complexity}
                onChange={(e) => setComplexity(e.target.value as TaskComplexity)}
              >
                <option value="fast">{copy.complexityFast}</option>
                <option value="deep">{copy.complexityDeep}</option>
              </select>
            </label>

            <label className="field">
              <span>{copy.classificationLabel}</span>
              <select
                value={classification}
                onChange={(e) =>
                  setClassification(e.target.value as ProjectClassification)
                }
              >
                {CLASSIFICATIONS.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="field">
            <span>{copy.promptLabel}</span>
            <textarea
              className="assignment-textarea"
              rows={4}
              dir="auto"
              required
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={copy.promptPlaceholder}
            />
          </label>

          <div className="subpanel">
            <div className="field">
              <span>{copy.existingFilesLabel}</span>
              {projectFiles.length === 0 ? (
                <p className="muted-line">{copy.noProjectFiles}</p>
              ) : (
                <div className="file-chip-list">
                  {projectFiles.map((fileItem) => (
                    <label key={fileItem.id} className="file-checkbox-chip">
                      <input
                        type="checkbox"
                        checked={attachedFileIds.includes(fileItem.id)}
                        onChange={() => handleToggleExistingFile(fileItem.id)}
                      />
                      <span dir="auto">
                        {fileItem.original_filename}{" "}
                        <span className="muted-small">({fileItem.folder_name})</span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <label className="field" style={{ marginTop: "0.75rem" }}>
              <span>{copy.uploadNewFilesLabel}</span>
              <input type="file" multiple onChange={handleStageFiles} />
            </label>
            {stagedUploadFiles.length > 0 && (
              <p className="muted-line">
                {copy.selectedUploadPrefix}{" "}
                {stagedUploadFiles.map((f) => f.name).join(", ")}
              </p>
            )}
          </div>

          <div className="actions">
            <button
              type="submit"
              className="btn"
              disabled={submitting || !selectedProjectId || !prompt.trim()}
            >
              {submitting ? copy.submittingBtn : copy.submitBtn}
            </button>
          </div>
        </form>

        {formError && (
          <div className="status-box status-err" role="alert">
            {formError}
          </div>
        )}
        {failedTaskNotice && (
          <div className="status-box status-err" role="alert">
            <strong>{copy.submitFailedBanner}</strong>{" "}
            <span dir="auto">{failedTaskNotice}</span>
          </div>
        )}
      </section>

      {selectedTask && (
        <section className="subpanel" aria-label={copy.detailHeading}>
          <div className="panel-header">
            <h2 className="panel-title">{selectedTask.title}</h2>
            <div className="badge-group">
              <span className={statusBadgeClass(selectedTask.status)}>
                {statusDisplayLabel(selectedTask.status, lang)}
              </span>
              <span className="badge">{selectedTask.classification}</span>
            </div>
          </div>

          {selectedTask.status === "failed" && selectedTask.error_message && (
            <div className="status-box status-err" role="alert" style={{ marginTop: 0 }}>
              <span dir="auto">{selectedTask.error_message}</span>
            </div>
          )}

          <dl className="meta-grid">
            <div>
              <dt>{copy.usageLabel}</dt>
              <dd dir="ltr">
                {selectedTask.model_name || "-"} ({selectedTask.token_usage.total_tokens} tokens,{" "}
                {selectedTask.token_usage.latency_ms} ms)
              </dd>
            </div>
            <div>
              <dt>{copy.languageLabel}</dt>
              <dd dir="ltr">{understanding?.language_detected ?? "-"}</dd>
            </div>
            <div>
              <dt>{copy.disciplineLabel}</dt>
              <dd dir="auto">
                {understanding?.primary_discipline ?? "-"}
                {understanding && understanding.secondary_disciplines.length > 0
                  ? ` (+ ${understanding.secondary_disciplines.join(", ")})`
                  : ""}
              </dd>
            </div>
          </dl>

          <p className="project-description" dir="auto">
            <strong>{copy.promptSnapshotLabel}:</strong> {selectedTask.prompt}
          </p>

          {selectedTask.attached_files.length > 0 && (
            <div style={{ marginBottom: "1rem" }}>
              <h3 className="folders-title">{copy.attachedFilesLabel}</h3>
              <ul className="outcome-list">
                {selectedTask.attached_files.map((fileItem) => (
                  <li key={fileItem.file_id} dir="auto">
                    <code>{fileItem.folder_name}</code> / {fileItem.filename} (v
                    {fileItem.current_version}, {fileItem.size_bytes} bytes)
                  </li>
                ))}
              </ul>
            </div>
          )}

          {understanding && (
            <div className="task-detail-grid">
              <div className="status-box" style={{ marginTop: 0 }}>
                <strong>{copy.restatedLabel}</strong>
                <p className="muted-line" dir="auto" style={{ color: "#0f172a" }}>
                  {understanding.restated_assignment}
                </p>
              </div>

              <div className="status-box" style={{ marginTop: 0 }}>
                <strong>{copy.deliverablesLabel}</strong>
                <ul className="outcome-list" dir="auto">
                  {understanding.expected_deliverables.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="status-box" style={{ marginTop: 0 }}>
                <strong>{copy.inputFilesLabel}</strong>
                <ul className="outcome-list" dir="auto">
                  {understanding.input_files.map((item, idx) => (
                    <li key={idx}>
                      <strong>{item.filename}</strong> [{item.status}] — {item.role}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="status-box" style={{ marginTop: 0 }}>
                <strong>{copy.standardsLabel}</strong>
                <p className="muted-small">{copy.standardsNote}</p>
                <ul className="outcome-list" dir="auto">
                  {understanding.applicable_standards_to_verify.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="status-box" style={{ marginTop: 0 }}>
                <strong>{copy.missingInfoLabel}</strong>
                <ul className="outcome-list" dir="auto">
                  {understanding.missing_information.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="status-box" style={{ marginTop: 0 }}>
                <strong>{copy.assumptionsLabel}</strong>
                <ul className="outcome-list" dir="auto">
                  {understanding.assumptions.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {understanding && (
            <div
              className={`status-box ${
                understanding.clarification_needed ? "notice-box" : "status-ok"
              }`}
            >
              <strong>{copy.clarificationsNeededLabel}:</strong>
              {understanding.clarification_needed &&
              understanding.clarifying_questions.length > 0 ? (
                <ul className="outcome-list" dir="auto">
                  {understanding.clarifying_questions.map((q, idx) => (
                    <li key={idx}>{q}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted-line" style={{ color: "inherit" }}>
                  {copy.noClarificationsNeeded}
                </p>
              )}
            </div>
          )}

          {understanding && understanding.recommended_next_steps.length > 0 && (
            <div className="status-box">
              <strong>{copy.nextStepsLabel}:</strong>
              <ul className="outcome-list" dir="auto">
                {understanding.recommended_next_steps.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          <div style={{ marginTop: "1rem" }}>
            <h3 className="folders-title">{copy.stepsLabel}</h3>
            <div className="table-wrap">
              <table className="files-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Module</th>
                    <th>Title</th>
                    <th>Status</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedTask.steps.map((step) => (
                    <tr key={step.id}>
                      <td>{step.step_order}</td>
                      <td dir="ltr">{step.module_name}</td>
                      <td>{step.title}</td>
                      <td>
                        <span className={statusBadgeClass(step.status)}>{step.status}</span>
                      </td>
                      <td dir="auto">{step.notes || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ marginTop: "1rem" }}>
            <h3 className="folders-title">{copy.logsLabel}</h3>
            <ul className="outcome-list">
              {selectedTask.logs.map((logItem) => (
                <li key={logItem.id} dir="ltr">
                  <code>{logItem.action}</code> ({logItem.actor}) — {logItem.created_at}
                  {logItem.details_json ? ` — ${JSON.stringify(logItem.details_json)}` : ""}
                </li>
              ))}
            </ul>
          </div>

          {understanding && (
            <details style={{ marginTop: "1rem" }}>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                {copy.rawJsonLabel}
              </summary>
              <pre className="json-preview" dir="ltr">
                {JSON.stringify(understanding, null, 2)}
              </pre>
            </details>
          )}
        </section>
      )}

      <section className="subpanel" aria-label={copy.historyHeading}>
        <div className="panel-header">
          <h2 className="panel-title">{copy.historyHeading}</h2>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void refreshHistory(filterProjectId, filterStatus)}
            disabled={loadingTasks}
          >
            {copy.refreshHistoryBtn}
          </button>
        </div>

        <div className="form-grid" style={{ marginBottom: "0.85rem" }}>
          <label className="field">
            <span>{copy.filterProjectLabel}</span>
            <select
              value={filterProjectId}
              onChange={(e) => setFilterProjectId(e.target.value)}
            >
              <option value="">{copy.allProjectsOption}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} — {p.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>{copy.filterStatusLabel}</span>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
            >
              <option value="">{copy.allStatusesOption}</option>
              <option value="completed">{statusDisplayLabel("completed", lang)}</option>
              <option value="awaiting_clarification">
                {statusDisplayLabel("awaiting_clarification", lang)}
              </option>
              <option value="failed">{statusDisplayLabel("failed", lang)}</option>
            </select>
          </label>
        </div>

        {loadingTasks && tasks.length === 0 && (
          <p className="muted-line">{copy.loadingHistory}</p>
        )}

        {!loadingTasks && tasks.length === 0 && (
          <p className="muted-line">{copy.emptyHistory}</p>
        )}

        {tasks.length > 0 && (
          <ul className="project-list">
            {tasks.map((task) => (
              <li key={task.id} className="project-row">
                <div className="project-row-info">
                  <strong dir="auto">{task.title}</strong>
                  <div className="project-row-meta">
                    <span className={statusBadgeClass(task.status)}>
                      {statusDisplayLabel(task.status, lang)}
                    </span>
                    <span className="badge">{task.classification}</span>
                    <span>
                      {task.project_code} — {task.project_name}
                    </span>
                    {task.structured_output && (
                      <span>{task.structured_output.primary_discipline}</span>
                    )}
                    <span dir="ltr">
                      {task.token_usage.total_tokens} tokens
                    </span>
                  </div>
                  {task.status === "failed" && task.error_message && (
                    <span className="muted-small" dir="auto" style={{ color: "#991b1b" }}>
                      {task.error_message}
                    </span>
                  )}
                </div>

                <button
                  type="button"
                  className="btn"
                  onClick={() => void handleInspectTask(task.id)}
                  disabled={loadingTaskId === task.id}
                >
                  {loadingTaskId === task.id ? copy.inspectingBtn : copy.inspectBtn}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
