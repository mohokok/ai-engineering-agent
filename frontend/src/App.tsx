import { useCallback, useEffect, useState } from "react";
import { fetchHealth } from "./api";
import { AssignmentsView } from "./components/AssignmentsView";
import { BoqView } from "./components/BoqView";
import { DeliverablesView } from "./components/DeliverablesView";
import { ParametricDrawingView } from "./components/ParametricDrawingView";
import { ProjectWorkspaceView } from "./components/ProjectWorkspaceView";
import { ProviderSettingsView } from "./components/ProviderSettingsView";
import { QaIssuesView } from "./components/QaIssuesView";
import { ResearchView } from "./components/ResearchView";
import type { HealthPayload, Lang } from "./types";

type ActiveTab = "projects" | "assignments" | "research" | "deliverables" | "boq" | "drawings" | "qa" | "settings";

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
    projectsTab: string;
    assignmentsTab: string;
    researchTab: string;
    deliverablesTab: string;
    boqTab: string;
    drawingsTab: string;
    qaTab: string;
    settingsTab: string;
  }
> = {
  ar: {
    title: "الوكيل الهندسي الاستشاري المحلي",
    subtitle: "الخطوة 12 — الرسم البارامتري + جداول الكميات + وكيل الجودة المستقل وسجل القضايا (QA)",
    classificationLabel: "التصنيف: أولي (Preliminary)",
    toggleLang: "Switch to English (LTR)",
    refreshHealth: "تحديث فحص الخادم",
    checking: "جاري التحقق من الخادم...",
    backendStatusTitle: "حالة الخادم الخلفي (/api/health)",
    backendHealthy: "متصل",
    offlinePrefix: "تعذر الاتصال بالخادم الخلفي: ",
    projectsTab: "المشاريع والملفات",
    assignmentsTab: "المهام والتكليفات",
    researchTab: "البحث وسجل المصادر",
    deliverablesTab: "التقارير والمخرجات",
    boqTab: "جداول الكميات (BOQ)",
    drawingsTab: "الرسم الهندسي (CAD)",
    qaTab: "الجودة وسجل القضايا (QA)",
    settingsTab: "إعدادات Gemini والمزودين",
  },
  en: {
    title: "Local AI Engineering Consultancy Agent",
    subtitle: "Step 12 — Parametric CAD, Deterministic BOQ, Independent QA Agent & Issue Register",
    classificationLabel: "Classification: Preliminary",
    toggleLang: "التبديل إلى العربية (RTL)",
    refreshHealth: "Refresh Health Check",
    checking: "Checking backend health...",
    backendStatusTitle: "Backend Health (/api/health)",
    backendHealthy: "Connected",
    offlinePrefix: "Backend unreachable: ",
    projectsTab: "Projects & Files",
    assignmentsTab: "New Assignment & History",
    researchTab: "Research & Source Log",
    deliverablesTab: "Deliverables & Reports",
    boqTab: "BOQ & Quantities",
    drawingsTab: "Parametric CAD",
    qaTab: "QA & Issue Register",
    settingsTab: "AI Provider Settings",
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

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = lang;
      document.documentElement.dir = dir;
    }
  }, [lang, dir]);

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

  return (
    <main className="app-shell" dir={dir} lang={lang}>
      <section className="app-card">
        <header className="app-header">
          <div>
            <h1 style={{ margin: 0 }}>{text.title}</h1>
            <p style={{ margin: "0.35rem 0 0", color: "#475569" }}>{text.subtitle}</p>
          </div>
          <span className="badge">{text.classificationLabel}</span>
        </header>

        <div className="actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setLang((prev) => (prev === "ar" ? "en" : "ar"))}
          >
            {text.toggleLang}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void loadHealth()}
            disabled={loading}
          >
            {loading ? text.checking : text.refreshHealth}
          </button>
        </div>

        <div
          className={`status-box compact-status ${
            health?.status === "ok" ? "status-ok" : error ? "status-err" : ""
          }`}
        >
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

        <nav className="nav-tabs" aria-label="Main workspace navigation">
          <button
            type="button"
            className={`btn ${activeTab === "projects" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("projects")}
          >
            {text.projectsTab}
          </button>
          <button
            type="button"
            className={`btn ${activeTab === "assignments" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("assignments")}
          >
            {text.assignmentsTab}
          </button>
          <button
            type="button"
            className={`btn ${activeTab === "research" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("research")}
          >
            {text.researchTab}
          </button>
          <button
            type="button"
            className={`btn ${activeTab === "deliverables" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("deliverables")}
          >
            {text.deliverablesTab}
          </button>
          <button
            type="button"
            className={`btn ${activeTab === "boq" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("boq")}
          >
            {text.boqTab}
          </button>
          <button
            type="button"
            className={`btn ${activeTab === "drawings" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("drawings")}
          >
            {text.drawingsTab}
          </button>
          <button
            type="button"
            className={`btn ${activeTab === "qa" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("qa")}
          >
            {text.qaTab}
          </button>
          <button
            type="button"
            className={`btn ${activeTab === "settings" ? "" : "btn-secondary"}`}
            onClick={() => setActiveTab("settings")}
          >
            {text.settingsTab}
          </button>
        </nav>

        {activeTab === "projects" ? (
          <ProjectWorkspaceView lang={lang} />
        ) : activeTab === "assignments" ? (
          <AssignmentsView lang={lang} />
        ) : activeTab === "research" ? (
          <ResearchView lang={lang} />
        ) : activeTab === "deliverables" ? (
          <DeliverablesView lang={lang} />
        ) : activeTab === "boq" ? (
          <BoqView lang={lang} />
        ) : activeTab === "drawings" ? (
          <ParametricDrawingView lang={lang} />
        ) : activeTab === "qa" ? (
          <QaIssuesView lang={lang} />
        ) : (
          <ProviderSettingsView lang={lang} />
        )}
      </section>
    </main>
  );
}

export default App;
