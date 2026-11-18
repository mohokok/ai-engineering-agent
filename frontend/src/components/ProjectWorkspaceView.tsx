import { FormEvent, useCallback, useEffect, useState } from "react";
import { createProject, getProject, listProjects } from "../api";
import type {
  Lang,
  ProjectClassification,
  ProjectDetail,
  ProjectSummary,
} from "../types";

interface WorkspaceCopy {
  createHeading: string;
  nameLabel: string;
  namePlaceholder: string;
  nameEnLabel: string;
  codeLabel: string;
  codePlaceholder: string;
  clientLabel: string;
  locationLabel: string;
  descriptionLabel: string;
  classificationLabel: string;
  submitCreate: string;
  creating: string;
  projectsHeading: string;
  refreshList: string;
  loadingProjects: string;
  emptyProjects: string;
  openProject: string;
  openingProject: string;
  backToList: string;
  workspaceHeading: string;
  foldersHeading: string;
  slugLabel: string;
  codeMetaLabel: string;
  clientMetaLabel: string;
  locationMetaLabel: string;
  statusMetaLabel: string;
  folderPresent: string;
  folderMissing: string;
  workspaceReady: string;
  workspaceMissing: string;
  errorPrefix: string;
}

const WORKSPACE_COPY: Record<Lang, WorkspaceCopy> = {
  ar: {
    createHeading: "إنشاء مشروع هندسي جديد",
    nameLabel: "اسم المشروع (عربي أو إنجليزي) *",
    namePlaceholder: "مثال: مستشفى طرابلس التعليمي",
    nameEnLabel: "الاسم بالإنجليزية (اختياري)",
    codeLabel: "رمز المشروع (اختياري — يُولّد تلقائياً)",
    codePlaceholder: "مثال: HOSP-01",
    clientLabel: "الجهة المالكة / العميل",
    locationLabel: "الموقع",
    descriptionLabel: "وصف المشروع ونطاق العمل",
    classificationLabel: "تصنيف المخرجات المبدئي",
    submitCreate: "إنشاء المشروع وتهيئة المجلدات",
    creating: "جاري الإنشاء...",
    projectsHeading: "المشاريع الهندسية المحفوظة",
    refreshList: "تحديث المشاريع",
    loadingProjects: "جاري تحميل المشاريع...",
    emptyProjects: "لا توجد مشاريع مسجلة حالياً. أنشئ مشروعاً جديداً أعلاه.",
    openProject: "فتح المشروع",
    openingProject: "جاري الفتح...",
    backToList: "العودة إلى قائمة المشاريع",
    workspaceHeading: "تفاصيل المشروع ومساحة العمل",
    foldersHeading: "مجلدات مساحة عمل المشروع (12 مجلداً)",
    slugLabel: "مجلد مساحة العمل",
    codeMetaLabel: "رمز المشروع",
    clientMetaLabel: "العميل",
    locationMetaLabel: "الموقع",
    statusMetaLabel: "الحالة",
    folderPresent: "موجود على القرص",
    folderMissing: "غير موجود على القرص",
    workspaceReady: "مساحة العمل مهيأة على القرص",
    workspaceMissing: "مجلد مساحة العمل مفقود",
    errorPrefix: "تعذر تنفيذ العملية: ",
  },
  en: {
    createHeading: "Create Engineering Project",
    nameLabel: "Project Name (Arabic or English) *",
    namePlaceholder: "Example: مستشفى طرابلس التعليمي",
    nameEnLabel: "English Name (optional)",
    codeLabel: "Project Code (optional — auto-generated if blank)",
    codePlaceholder: "Example: HOSP-01",
    clientLabel: "Client / Owner",
    locationLabel: "Location",
    descriptionLabel: "Scope & Description",
    classificationLabel: "Initial Classification",
    submitCreate: "Create Project & 12 Folders",
    creating: "Creating...",
    projectsHeading: "Persisted Engineering Projects",
    refreshList: "Refresh Projects",
    loadingProjects: "Loading projects...",
    emptyProjects: "No projects saved yet. Create a project above.",
    openProject: "Open Project",
    openingProject: "Opening...",
    backToList: "Back to Projects",
    workspaceHeading: "Project Overview & Workspace",
    foldersHeading: "Project Workspace Folders (12 Folders)",
    slugLabel: "Workspace Folder",
    codeMetaLabel: "Project Code",
    clientMetaLabel: "Client",
    locationMetaLabel: "Location",
    statusMetaLabel: "Status",
    folderPresent: "On disk",
    folderMissing: "Missing on disk",
    workspaceReady: "Workspace directory verified on disk",
    workspaceMissing: "Workspace directory missing on disk",
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

function readProjectHash(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const prefix = "#project/";
  if (!window.location.hash.startsWith(prefix)) {
    return null;
  }
  const id = decodeURIComponent(window.location.hash.slice(prefix.length)).trim();
  return id || null;
}

function writeProjectHash(projectId: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  const nextHash = projectId ? `#project/${encodeURIComponent(projectId)}` : "";
  if (window.location.hash !== nextHash) {
    window.history.replaceState(null, "", nextHash || window.location.pathname + window.location.search);
  }
}

export interface ProjectWorkspaceViewProps {
  lang: Lang;
  initialProjects?: ProjectSummary[];
  initialOpenedProject?: ProjectDetail | null;
}

export function ProjectWorkspaceView({
  lang,
  initialProjects = [],
  initialOpenedProject = null,
}: ProjectWorkspaceViewProps) {
  const copy = WORKSPACE_COPY[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>(initialProjects);
  const [openedProject, setOpenedProject] = useState<ProjectDetail | null>(initialOpenedProject);
  const [listLoading, setListLoading] = useState<boolean>(false);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState<string>("");
  const [nameEn, setNameEn] = useState<string>("");
  const [code, setCode] = useState<string>("");
  const [clientName, setClientName] = useState<string>("");
  const [location, setLocation] = useState<string>("");
  const [description, setDescription] = useState<string>("");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");

  const loadProjects = useCallback(async () => {
    setListLoading(true);
    setError(null);
    try {
      const response = await listProjects();
      setProjects(response.projects);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setListLoading(false);
    }
  }, []);

  const handleOpenProject = useCallback(async (projectId: string) => {
    setOpeningId(projectId);
    setError(null);
    try {
      const detail = await getProject(projectId);
      setOpenedProject(detail);
      writeProjectHash(detail.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOpeningId(null);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
    const hashedId = readProjectHash();
    if (hashedId) {
      void handleOpenProject(hashedId);
    }
  }, [loadProjects, handleOpenProject]);

  async function handleCreateSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createProject({
        name: name.trim(),
        code: code.trim() || undefined,
        name_en: nameEn.trim() || undefined,
        client_name: clientName.trim() || undefined,
        location: location.trim() || undefined,
        description: description.trim() || undefined,
        classification,
      });
      setProjects((prev) => [created, ...prev.filter((item) => item.id !== created.id)]);
      setOpenedProject(created);
      writeProjectHash(created.id);
      setName("");
      setNameEn("");
      setCode("");
      setClientName("");
      setLocation("");
      setDescription("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  function handleBackToList() {
    setOpenedProject(null);
    writeProjectHash(null);
    void loadProjects();
  }

  return (
    <div className="workspace-section">
      {error && (
        <div className="status-box status-err" role="alert">
          <strong>{copy.errorPrefix}</strong>
          <span>{error}</span>
        </div>
      )}

      {openedProject ? (
        <section className="subpanel" aria-label={copy.workspaceHeading}>
          <div className="panel-header">
            <div>
              <h2 className="panel-title">{openedProject.name}</h2>
              {openedProject.name_en && <p className="muted-line">{openedProject.name_en}</p>}
            </div>
            <div className="badge-group">
              <span className="badge">{openedProject.classification}</span>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleBackToList}
              >
                {copy.backToList}
              </button>
            </div>
          </div>

          <dl className="meta-grid">
            <div>
              <dt>{copy.codeMetaLabel}</dt>
              <dd dir="ltr">{openedProject.code}</dd>
            </div>
            <div>
              <dt>{copy.slugLabel}</dt>
              <dd dir="ltr">{openedProject.workspace_slug}</dd>
            </div>
            <div>
              <dt>{copy.statusMetaLabel}</dt>
              <dd>{openedProject.status}</dd>
            </div>
            <div>
              <dt>{copy.clientMetaLabel}</dt>
              <dd>{openedProject.client_name || "—"}</dd>
            </div>
            <div>
              <dt>{copy.locationMetaLabel}</dt>
              <dd>{openedProject.location || "—"}</dd>
            </div>
            <div>
              <dt>{copy.workspaceHeading}</dt>
              <dd>{openedProject.workspace_exists ? copy.workspaceReady : copy.workspaceMissing}</dd>
            </div>
          </dl>

          {openedProject.description && (
            <p className="project-description">{openedProject.description}</p>
          )}

          <h3 className="folders-title">{copy.foldersHeading}</h3>
          <ul className="folder-grid">
            {openedProject.folders.map((folder) => (
              <li
                key={folder.name}
                className={`folder-item ${folder.exists ? "folder-ok" : "folder-missing"}`}
              >
                <span className="folder-name" dir="ltr">
                  {folder.name}
                </span>
                <span className="folder-state">
                  {folder.exists ? copy.folderPresent : copy.folderMissing}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <>
          <section className="subpanel" aria-label={copy.createHeading}>
            <h2 className="panel-title">{copy.createHeading}</h2>
            <form className="project-form" onSubmit={(e) => void handleCreateSubmit(e)}>
              <div className="form-grid">
                <label className="field">
                  <span>{copy.nameLabel}</span>
                  <input
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={copy.namePlaceholder}
                  />
                </label>

                <label className="field">
                  <span>{copy.codeLabel}</span>
                  <input
                    type="text"
                    dir="ltr"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder={copy.codePlaceholder}
                  />
                </label>

                <label className="field">
                  <span>{copy.nameEnLabel}</span>
                  <input
                    type="text"
                    dir="ltr"
                    value={nameEn}
                    onChange={(e) => setNameEn(e.target.value)}
                  />
                </label>

                <label className="field">
                  <span>{copy.classificationLabel}</span>
                  <select
                    value={classification}
                    onChange={(e) => setClassification(e.target.value as ProjectClassification)}
                  >
                    {CLASSIFICATIONS.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field">
                  <span>{copy.clientLabel}</span>
                  <input
                    type="text"
                    value={clientName}
                    onChange={(e) => setClientName(e.target.value)}
                  />
                </label>

                <label className="field">
                  <span>{copy.locationLabel}</span>
                  <input
                    type="text"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </label>
              </div>

              <label className="field">
                <span>{copy.descriptionLabel}</span>
                <textarea
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>

              <div className="actions">
                <button type="submit" className="btn" disabled={submitting || !name.trim()}>
                  {submitting ? copy.creating : copy.submitCreate}
                </button>
              </div>
            </form>
          </section>

          <section className="subpanel" aria-label={copy.projectsHeading}>
            <div className="panel-header">
              <h2 className="panel-title">
                {copy.projectsHeading} ({projects.length})
              </h2>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void loadProjects()}
                disabled={listLoading}
              >
                {listLoading ? copy.loadingProjects : copy.refreshList}
              </button>
            </div>

            {projects.length === 0 ? (
              <p className="muted-line">{listLoading ? copy.loadingProjects : copy.emptyProjects}</p>
            ) : (
              <ul className="project-list">
                {projects.map((project) => (
                  <li key={project.id} className="project-row">
                    <div className="project-row-info">
                      <strong>{project.name}</strong>
                      <div className="project-row-meta">
                        <span dir="ltr">{project.code}</span>
                        <span>•</span>
                        <span dir="ltr">{project.workspace_slug}</span>
                        <span className="badge">{project.classification}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void handleOpenProject(project.id)}
                      disabled={openingId === project.id}
                    >
                      {openingId === project.id ? copy.openingProject : copy.openProject}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
