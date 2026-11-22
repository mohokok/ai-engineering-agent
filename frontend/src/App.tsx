import { useCallback, useEffect, useState } from "react";
import { fetchHealth } from "./api";
import { BRAND_IDENTITY, BRAND_LOGO_URL, CLASSIFICATION_DISCLAIMER } from "./branding";
import { AssignmentsView } from "./components/AssignmentsView";
import { BoqView } from "./components/BoqView";
import { CalculationsView } from "./components/CalculationsView";
import { DeliverablesView } from "./components/DeliverablesView";
import { ParametricDrawingView } from "./components/ParametricDrawingView";
import { ProjectPlanningView } from "./components/ProjectPlanningView";
import { ProjectWorkspaceView } from "./components/ProjectWorkspaceView";
import { ProviderSettingsView } from "./components/ProviderSettingsView";
import { QaIssuesView } from "./components/QaIssuesView";
import { ResearchView } from "./components/ResearchView";
import { SpecificationsView } from "./components/SpecificationsView";
import { SpecialistEngineeringView } from "./components/SpecialistEngineeringView";
import { StandardsLibraryView } from "./components/StandardsLibraryView";
import { StructuralView } from "./components/StructuralView";
import { TechnicalComparisonsView } from "./components/TechnicalComparisonsView";
import type { HealthPayload, Lang } from "./types";

type ActiveTab =
  | "projects"
  | "assignments"
  | "research"
  | "standards"
  | "specialist"
  | "structural"
  | "deliverables"
  | "boq"
  | "drawings"
  | "calculations"
  | "specifications"
  | "comparisons"
  | "planning"
  | "qa"
  | "settings";

const COPY: Record<
  Lang,
  {
    title: string;
    subtitle: string;
    classificationLabel: string;
    toggleLang: string;
    refreshHealth: string;
    checking: string;
    backendStatusTitle: string;
    backendHealthy: string;
    offlinePrefix: string;
    groupWorkspace: string;
    groupEngineering: string;
    groupGovernance: string;
    groupSystem: string;
    projectsTab: string;
    assignmentsTab: string;
    researchTab: string;
    standardsTab: string;
    specialistTab: string;
    structuralTab: string;
    deliverablesTab: string;
    boqTab: string;
    drawingsTab: string;
    calculationsTab: string;
    specificationsTab: string;
    comparisonsTab: string;
    planningTab: string;
    qaTab: string;
    settingsTab: string;
  }
> = {
  ar: {
    title: "الوكيل الهندسي الاستشاري المحلي",
    subtitle:
      "الخطوة 20 — الأمان ومعالجة الأخطاء والسجلات والنسخ الاحتياطي + كافة الوحدات الهندسية وضبط الجودة",
    classificationLabel: "التصنيف: أولي (Preliminary)",
    toggleLang: "English (LTR)",
    refreshHealth: "تحديث فحص الخادم",
    checking: "جاري التحقق من الخادم...",
    backendStatusTitle: "حالة الخادم الخلفي (/api/health)",
    backendHealthy: "متصل",
    offlinePrefix: "تعذر الاتصال بالخادم الخلفي: ",
    groupWorkspace: "مساحة العمل",
    groupEngineering: "الوحدات الهندسية",
    groupGovernance: "المعايير والجودة",
    groupSystem: "النظام",
    projectsTab: "المشاريع والملفات",
    assignmentsTab: "المهام والتكليفات",
    researchTab: "البحث وسجل المصادر",
    standardsTab: "مكتبة المعايير (Standards)",
    specialistTab: "تكييف / حريق / صحة (Preflight)",
    structuralTab: "الإنشائي (I/O Support)",
    deliverablesTab: "التقارير والمخرجات",
    boqTab: "جداول الكميات (BOQ)",
    drawingsTab: "الرسم الهندسي (CAD)",
    calculationsTab: "الحسابات الهندسية (MEP)",
    specificationsTab: "المواصفات الفنية (Specs)",
    comparisonsTab: "المقارنات الفنية (Compare)",
    planningTab: "الجدولة والمسار الحرج (Plan)",
    qaTab: "الجودة وسجل القضايا (QA)",
    settingsTab: "إعدادات Gemini والمزودين والنظام",
  },
  en: {
    title: "Local AI Engineering Consultancy Agent",
    subtitle:
      "Step 20 — Security Hardening, Logging & Backup/Restore + All Engineering Modules & QA",
    classificationLabel: "Classification: Preliminary",
    toggleLang: "العربية (RTL)",
    refreshHealth: "Refresh Health Check",
    checking: "Checking backend health...",
    backendStatusTitle: "Backend Health (/api/health)",
    backendHealthy: "Connected",
    offlinePrefix: "Backend unreachable: ",
    groupWorkspace: "Workspace",
    groupEngineering: "Engineering",
    groupGovernance: "QA & Governance",
    groupSystem: "System",
    projectsTab: "Projects & Files",
    assignmentsTab: "New Assignment & History",
    researchTab: "Research & Source Log",
    standardsTab: "Standards Library",
    specialistTab: "HVAC / Fire / Healthcare",
    structuralTab: "Structural Support",
    deliverablesTab: "Deliverables & Reports",
    boqTab: "BOQ & Quantities",
    drawingsTab: "Parametric CAD",
    calculationsTab: "Calculations (MEP)",
    specificationsTab: "Technical Specs",
    comparisonsTab: "Technical Compare",
    planningTab: "Planning & Gantt",
    qaTab: "QA & Issue Register",
    settingsTab: "Settings & System",
  },
};

export function App({
  initialLang = "ar",
  initialTab = "projects",
}: {
  initialLang?: Lang;
  initialTab?: ActiveTab;
}) {
  const [lang, setLang] = useState<Lang>(initialLang);
  const [activeTab, setActiveTab] = useState<ActiveTab>(initialTab);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const dir = lang === "ar" ? "rtl" : "ltr";
  const text = COPY[lang];
  const primaryCompany = BRAND_IDENTITY[lang];
  const secondaryCompany = BRAND_IDENTITY[lang === "ar" ? "en" : "ar"];

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = lang;
      document.documentElement.dir = dir;
      document.title = `${primaryCompany.fullName} — ${text.title}`;
    }
  }, [lang, dir, primaryCompany.fullName, text.title]);

  const loadHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchHealth();
      setHealth(data);
    } catch (err) {
      setHealth(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  const tabGroups: Array<{ label: string; tabs: Array<{ id: ActiveTab; label: string }> }> = [
    {
      label: text.groupWorkspace,
      tabs: [
        { id: "projects", label: text.projectsTab },
        { id: "assignments", label: text.assignmentsTab },
        { id: "deliverables", label: text.deliverablesTab },
        { id: "research", label: text.researchTab },
      ],
    },
    {
      label: text.groupEngineering,
      tabs: [
        { id: "boq", label: text.boqTab },
        { id: "drawings", label: text.drawingsTab },
        { id: "calculations", label: text.calculationsTab },
        { id: "specifications", label: text.specificationsTab },
        { id: "specialist", label: text.specialistTab },
        { id: "structural", label: text.structuralTab },
        { id: "comparisons", label: text.comparisonsTab },
        { id: "planning", label: text.planningTab },
      ],
    },
    {
      label: text.groupGovernance,
      tabs: [
        { id: "standards", label: text.standardsTab },
        { id: "qa", label: text.qaTab },
      ],
    },
    {
      label: text.groupSystem,
      tabs: [{ id: "settings", label: text.settingsTab }],
    },
  ];

  return (
    <main className="app-shell" dir={dir} lang={lang}>
      <section className="app-card">
        <header className="app-header">
          <div className="brand-lockup">
            <div className="brand-logo-frame">
              <img
                src={BRAND_LOGO_URL}
                alt={`${BRAND_IDENTITY.en.fullName} | ${BRAND_IDENTITY.ar.fullName}`}
                className="brand-logo"
              />
            </div>
            <div className="brand-identity">
              <div className="brand-company-row">
                <span className="brand-company-primary">{primaryCompany.fullName}</span>
                <span className="brand-sep" aria-hidden="true">
                  |
                </span>
                <span className="brand-company-secondary">{secondaryCompany.fullName}</span>
              </div>
              <h1 className="app-title">{text.title}</h1>
              <p className="app-subtitle">{text.subtitle}</p>
            </div>
          </div>

          <div className="header-controls">
            <span className="badge badge-prelim">{text.classificationLabel}</span>
            <div className="header-utility-row">
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                onClick={() => setLang((prev) => (prev === "ar" ? "en" : "ar"))}
              >
                {text.toggleLang}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                onClick={() => void loadHealth()}
                disabled={loading}
              >
                {loading ? text.checking : text.refreshHealth}
              </button>
            </div>
          </div>
        </header>

        <div
          className={`status-box compact-status ${
            health?.status === "ok" ? "status-ok" : error ? "status-err" : ""
          }`}
        >
          <div>
            <strong>{text.backendStatusTitle}:</strong>{" "}
            {loading && !health && !error && <span>{text.checking}</span>}
            {error && (
              <span>
                {text.offlinePrefix}
                <code>{error}</code>
              </span>
            )}
            {health && (
              <span>
                {text.backendHealthy} ({health.service} v{health.version} — {health.classification})
              </span>
            )}
          </div>
          <span className="badge badge-readonly">
            {health?.status === "ok" ? text.backendHealthy : loading ? text.checking : "Localhost"}
          </span>
        </div>

        <nav className="nav-tabs" aria-label="Main workspace navigation" role="tablist">
          {tabGroups.map((group) => (
            <div key={group.label} className="nav-group" aria-label={group.label}>
              <span className="nav-group-label">{group.label}</span>
              {group.tabs.map((tab) => {
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    className={`btn nav-tab-btn ${isActive ? "is-active" : "btn-secondary"}`}
                    onClick={() => setActiveTab(tab.id)}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        {activeTab === "projects" ? (
          <ProjectWorkspaceView lang={lang} />
        ) : activeTab === "assignments" ? (
          <AssignmentsView lang={lang} />
        ) : activeTab === "research" ? (
          <ResearchView lang={lang} />
        ) : activeTab === "standards" ? (
          <StandardsLibraryView lang={lang} />
        ) : activeTab === "specialist" ? (
          <SpecialistEngineeringView lang={lang} />
        ) : activeTab === "structural" ? (
          <StructuralView lang={lang} />
        ) : activeTab === "deliverables" ? (
          <DeliverablesView lang={lang} />
        ) : activeTab === "boq" ? (
          <BoqView lang={lang} />
        ) : activeTab === "drawings" ? (
          <ParametricDrawingView lang={lang} />
        ) : activeTab === "calculations" ? (
          <CalculationsView lang={lang} />
        ) : activeTab === "specifications" ? (
          <SpecificationsView lang={lang} />
        ) : activeTab === "comparisons" ? (
          <TechnicalComparisonsView lang={lang} />
        ) : activeTab === "planning" ? (
          <ProjectPlanningView lang={lang} />
        ) : activeTab === "qa" ? (
          <QaIssuesView lang={lang} />
        ) : (
          <ProviderSettingsView lang={lang} />
        )}

        <footer className="app-footer">
          <span className="app-footer-brand">
            {BRAND_IDENTITY.en.fullName} | {BRAND_IDENTITY.ar.fullName}
          </span>
          <span>{CLASSIFICATION_DISCLAIMER[lang]}</span>
        </footer>
      </section>
    </main>
  );
}

export default App;
