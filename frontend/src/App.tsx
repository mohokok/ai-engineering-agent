import { useCallback, useEffect, useState } from "react";

export interface HealthPayload {
  status: string;
  service: string;
  version: string;
  environment: string;
  classification: string;
}

type Lang = "ar" | "en";

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
    offlinePrefix: string;
  }
> = {
  ar: {
    title: "الوكيل الهندسي الاستشاري المحلي",
    subtitle: "الخطوة 01 — التحقق من بيئة التشغيل المحلية وواجهة البرمجة (RTL)",
    classificationLabel: "التصنيف: أولي (Preliminary)",
    toggleLang: "Switch to English (LTR)",
    refreshHealth: "تحديث فحص الخادم",
    checking: "جاري التحقق من الخادم...",
    backendStatusTitle: "حالة الخادم الخلفي (/api/health)",
    offlinePrefix: "تعذر الاتصال بالخادم الخلفي: ",
  },
  en: {
    title: "Local AI Engineering Consultancy Agent",
    subtitle: "Step 01 — Local Windows Environment & API Health Placeholder",
    classificationLabel: "Classification: Preliminary",
    toggleLang: "التبديل إلى العربية (RTL)",
    refreshHealth: "Refresh Health Check",
    checking: "Checking backend health...",
    backendStatusTitle: "Backend Health (/api/health)",
    offlinePrefix: "Backend unreachable: ",
  },
};

export function App({ initialLang = "ar" }: { initialLang?: Lang }) {
  const [lang, setLang] = useState<Lang>(initialLang);
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

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/health");
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = (await res.json()) as HealthPayload;
      setHealth(data);
    } catch (err) {
      setHealth(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchHealth();
  }, [fetchHealth]);

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
            className="btn"
            onClick={() => void fetchHealth()}
            disabled={loading}
          >
            {loading ? text.checking : text.refreshHealth}
          </button>
        </div>

        <div
          className={`status-box ${
            health?.status === "ok" ? "status-ok" : error ? "status-err" : ""
          }`}
        >
          <strong>{text.backendStatusTitle}</strong>
          {loading && !health && !error && <p>{text.checking}</p>}
          {error && (
            <p>
              {text.offlinePrefix}
              <code>{error}</code>
            </p>
          )}
          {health && (
            <pre style={{ margin: "0.5rem 0 0", direction: "ltr", textAlign: "left" }}>
              {JSON.stringify(health, null, 2)}
            </pre>
          )}
        </div>
      </section>
    </main>
  );
}

export default App;
