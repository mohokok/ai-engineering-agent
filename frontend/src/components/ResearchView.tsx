import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  getResearchCapabilities,
  getResearchRunDetail,
  listProjects,
  listResearchRuns,
  runControlledResearch,
} from "../api";
import type {
  Lang,
  ProjectClassification,
  ProjectSummary,
  ResearchCapabilitiesOut,
  ResearchRunDetailOut,
  ResearchRunSummaryOut,
  SearchProviderName,
  TaskComplexity,
} from "../types";

interface ResearchCopy {
  heading: string;
  hint: string;
  policyBanner: string;
  projectLabel: string;
  allProjectsOption: string;
  queryLabel: string;
  queryPlaceholder: string;
  urlsLabel: string;
  urlsPlaceholder: string;
  providerLabel: string;
  maxResultsLabel: string;
  complexityLabel: string;
  classificationLabel: string;
  aiToggleLabel: string;
  submitBtn: string;
  submittingBtn: string;
  historyHeading: string;
  refreshBtn: string;
  loadingHistory: string;
  emptyHistory: string;
  inspectBtn: string;
  detailHeading: string;
  colDate: string;
  colQuery: string;
  colProvider: string;
  colSources: string;
  colStatus: string;
  colClass: string;
  colActions: string;
  unreviewedHeading: string;
  injectionHeading: string;
  findingsHeading: string;
  sourceLogHeading: string;
  colPriority: string;
  colSourceName: string;
  colPubDate: string;
  colAccessDate: string;
  colExtracted: string;
  colRating: string;
  colReviewState: string;
  reviewedTag: string;
  inaccessibleTag: string;
  errorPrefix: string;
}

const COPY: Record<Lang, ResearchCopy> = {
  ar: {
    heading: "البحث الهندسي المضبوط (Controlled Internet Research)",
    hint: "يبحث النظام في المصادر المصرّح بها، ثم يجلب محتوى كل صفحة أو ملف PDF فعلياً ولا يعتمد على مقتطفات محركات البحث مطلقاً.",
    policyBanner:
      "أولوية الموثوقية: (1) التشريعات واللوائح الرسمية ← (2) هيئات المواصفات القياسية ← (3) المنشورات الحكومية ← (4) وثائق الشركات المصنعة ← (5) الأوراق المحكمة ← (6) المراجع الموثوقة. كافة الصفحات المجلوبة بيانات غير موثوقة وتُسجَّل المستندات المتعذرة كغير مراجَعة.",
    projectLabel: "ربط بمشروع (اختياري)",
    allProjectsOption: "بحث عام (بدون ربط بمشروع محدد)",
    queryLabel: "موضوع أو سؤال البحث الهندسي *",
    queryPlaceholder: "مثال: متطلبات التهوية لغرف العمليات NFPA 99 أو كود البناء الليبي",
    urlsLabel: "روابط محددة للتحقق المباشر (اختياري — رابط في كل سطر)",
    urlsPlaceholder: "https://example.org/regulation.pdf",
    providerLabel: "مزوّد البحث",
    maxResultsLabel: "الحد الأقصى للنتائج",
    complexityLabel: "مستوى التحليل الذكي",
    classificationLabel: "تصنيف الإخراج",
    aiToggleLabel: "تلخيص النتائج عبر Gemini (ضمن حدود الاستخدام في الخطوة 04)",
    submitBtn: "تنفيذ البحث المضبوط وحفظ سجل المصادر",
    submittingBtn: "جاري البحث وجلب الصفحات والتحقق منها...",
    historyHeading: "سجل أبحاث الإنترنت والمصادر (Research History)",
    refreshBtn: "تحديث السجل",
    loadingHistory: "جاري تحميل سجل الأبحاث...",
    emptyHistory: "لا توجد عمليات بحث مسجلة حتى الآن.",
    inspectBtn: "عرض المصادر والنتائج",
    detailHeading: "تفاصيل البحث وسجل المصادر الموثّق",
    colDate: "التاريخ",
    colQuery: "الاستعلام",
    colProvider: "المزود",
    colSources: "المصادر (متاح/متعذر)",
    colStatus: "الحالة",
    colClass: "التصنيف",
    colActions: "عرض",
    unreviewedHeading: "مستندات تعذر الوصول إليها (غير مراجَعة — UNREVIEWED)",
    injectionHeading: "محاولات حقن تعليمات تم تجاهلها وتحييدها بأمان",
    findingsHeading: "النتائج الموثقة من صفحات تم التحقق من قراءتها",
    sourceLogHeading: "جدول سجل المصادر الكامل (Source Log)",
    colPriority: "الأولوية",
    colSourceName: "المصدر والرابط",
    colPubDate: "تاريخ النشر",
    colAccessDate: "تاريخ الوصول",
    colExtracted: "المعلومات المستخلصة",
    colRating: "تقييم الموثوقية",
    colReviewState: "المراجعة",
    reviewedTag: "تمت المراجعة",
    inaccessibleTag: "متعذر — غير مراجَع",
    errorPrefix: "تعذر إتمام البحث: ",
  },
  en: {
    heading: "Controlled Internet Research & Citation Log",
    hint: "Executes web search and directly fetches full target pages or PDFs. Search-engine snippets are discarded and never treated as engineering evidence.",
    policyBanner:
      "Priority Order: (1) Official Regulations → (2) Standards Bodies → (3) Government → (4) Manufacturers → (5) Peer-Reviewed → (6) Reputable References. All fetched pages are isolated as untrusted data; inaccessible documents are marked UNREVIEWED.",
    projectLabel: "Link to Project (optional)",
    allProjectsOption: "General / Unlinked Research",
    queryLabel: "Engineering Research Query *",
    queryPlaceholder: "e.g., Operating theatre ACH ventilation NFPA 99 ASHRAE 170",
    urlsLabel: "Explicit URLs to Fetch & Verify Directly (optional, one per line)",
    urlsPlaceholder: "https://example.org/standard.pdf",
    providerLabel: "Search Backend",
    maxResultsLabel: "Max Results",
    complexityLabel: "AI Complexity",
    classificationLabel: "Classification",
    aiToggleLabel: "Synthesize via Gemini AI (enforces Step 04 usage limits)",
    submitBtn: "Run Controlled Research & Save Source Log",
    submittingBtn: "Searching & fetching target pages...",
    historyHeading: "Research History (Source Provenance)",
    refreshBtn: "Refresh History",
    loadingHistory: "Loading research history...",
    emptyHistory: "No research runs recorded yet.",
    inspectBtn: "Inspect Source Log",
    detailHeading: "Persisted Research Run & Full Source Log",
    colDate: "Timestamp",
    colQuery: "Query",
    colProvider: "Provider",
    colSources: "Sources (Reviewed / Unreviewed)",
    colStatus: "Status",
    colClass: "Classification",
    colActions: "Inspect",
    unreviewedHeading: "Inaccessible Documents (Explicitly Marked UNREVIEWED)",
    injectionHeading: "Untrusted Prompt-Injection Attempts Safely Ignored",
    findingsHeading: "Verified Findings (Grounded in Fetched Sources Only)",
    sourceLogHeading: "Complete Persisted Source Log",
    colPriority: "Priority",
    colSourceName: "Source Name & URL",
    colPubDate: "Published",
    colAccessDate: "Accessed",
    colExtracted: "Extracted Info",
    colRating: "Reliability Rating",
    colReviewState: "Status",
    reviewedTag: "Reviewed",
    inaccessibleTag: "Inaccessible — Unreviewed",
    errorPrefix: "Research operation failed: ",
  },
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  return iso.replace("T", " ").replace(/\.\d+/, "").replace("+00:00", " UTC");
}

export interface ResearchViewProps {
  lang: Lang;
  initialCapabilities?: ResearchCapabilitiesOut | null;
  initialRuns?: ResearchRunSummaryOut[];
  initialDetail?: ResearchRunDetailOut | null;
}

export function ResearchView({
  lang,
  initialCapabilities = null,
  initialRuns = [],
  initialDetail = null,
}: ResearchViewProps) {
  const copy = COPY[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [capabilities, setCapabilities] = useState<ResearchCapabilitiesOut | null>(
    initialCapabilities
  );
  const [runs, setRuns] = useState<ResearchRunSummaryOut[]>(initialRuns);
  const [activeRun, setActiveRun] = useState<ResearchRunDetailOut | null>(initialDetail);
  const [projectId, setProjectId] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  const [urlsText, setUrlsText] = useState<string>("");
  const [searchProvider, setSearchProvider] = useState<SearchProviderName>("duckduckgo_lite");
  const [maxResults, setMaxResults] = useState<number>(5);
  const [complexity, setComplexity] = useState<TaskComplexity>("fast");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [synthesizeWithAi, setSynthesizeWithAi] = useState<boolean>(true);
  const [filterProjectId, setFilterProjectId] = useState<string>("");
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const res = await listResearchRuns({
        project_id: filterProjectId || undefined,
      });
      setRuns(res.runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingHistory(false);
    }
  }, [filterProjectId]);

  useEffect(() => {
    void listProjects()
      .then((res) => setProjects(res.projects))
      .catch(() => undefined);
    void getResearchCapabilities()
      .then((cap) => setCapabilities(cap))
      .catch(() => undefined);
    void loadHistory();
  }, [loadHistory]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const urls = urlsText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    try {
      const detail = await runControlledResearch({
        query,
        project_id: projectId || null,
        urls,
        search_provider: searchProvider,
        max_results: maxResults,
        complexity,
        classification,
        synthesize_with_ai: synthesizeWithAi,
      });
      setActiveRun(detail);
      setQuery("");
      setUrlsText("");
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await loadHistory();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleInspectRun(runId: string) {
    setError(null);
    try {
      const detail = await getResearchRunDetail(runId);
      setActiveRun(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <section className="subpanel" aria-label={copy.heading}>
        <div className="panel-header">
          <div>
            <h3 className="panel-title">{copy.heading}</h3>
            <p className="muted-hint" style={{ margin: "0.25rem 0 0" }}>
              {copy.hint}
            </p>
          </div>
          <span className="badge">{classification}</span>
        </div>

        <div className="status-box notice-box" style={{ marginTop: 0, marginBottom: "0.85rem" }}>
          {copy.policyBanner}
        </div>

        {capabilities && (
          <div className="badge-group" style={{ marginBottom: "0.85rem" }}>
            {capabilities.search_providers.map((p) => (
              <span
                key={p.id}
                className={`badge ${p.is_default || p.key_configured || !p.requires_api_key ? "badge-connected" : ""}`}
                title={p.pricing_summary}
              >
                {p.label}
              </span>
            ))}
          </div>
        )}

        <form onSubmit={(e) => void handleSubmit(e)} style={{ display: "grid", gap: "0.75rem" }}>
          <div className="form-grid">
            <label>
              <span>{copy.projectLabel}</span>
              <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">{copy.allProjectsOption}</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    [{p.code}] {p.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>{copy.providerLabel}</span>
              <select
                value={searchProvider}
                onChange={(e) => setSearchProvider(e.target.value as SearchProviderName)}
              >
                <option value="duckduckgo_lite">DuckDuckGo Lite (Free, No Key)</option>
                <option value="crossref">Crossref Peer-Reviewed (Free, No Key)</option>
                <option value="tavily">Tavily API (Optional Key in Keyring)</option>
                <option value="serper">Serper.dev (Optional Key in Keyring)</option>
                <option value="brave">Brave Search (Optional Key in Keyring)</option>
              </select>
            </label>

            <label>
              <span>{copy.maxResultsLabel}</span>
              <input
                type="number"
                min={1}
                max={10}
                value={maxResults}
                onChange={(e) => setMaxResults(Number(e.target.value) || 5)}
              />
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
          </div>

          <label>
            <span>{copy.queryLabel}</span>
            <input
              type="text"
              required
              dir="auto"
              placeholder={copy.queryPlaceholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>

          <label>
            <span>{copy.urlsLabel}</span>
            <textarea
              rows={2}
              dir="ltr"
              placeholder={copy.urlsPlaceholder}
              value={urlsText}
              onChange={(e) => setUrlsText(e.target.value)}
            />
          </label>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
              <input
                type="checkbox"
                checked={synthesizeWithAi}
                onChange={(e) => setSynthesizeWithAi(e.target.checked)}
              />
              <span>{copy.aiToggleLabel}</span>
            </label>

            {synthesizeWithAi && (
              <label>
                <span>{copy.complexityLabel}: </span>
                <select
                  value={complexity}
                  onChange={(e) => setComplexity(e.target.value as TaskComplexity)}
                >
                  <option value="fast">Fast</option>
                  <option value="deep">Deep</option>
                </select>
              </label>
            )}
          </div>

          <div>
            <button type="submit" className="btn" disabled={submitting || !query.trim()}>
              {submitting ? copy.submittingBtn : copy.submitBtn}
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

      <section className="subpanel" aria-label={copy.historyHeading}>
        <div className="panel-header">
          <h3 className="panel-title">
            {copy.historyHeading} ({runs.length})
          </h3>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <select
              value={filterProjectId}
              onChange={(e) => setFilterProjectId(e.target.value)}
            >
              <option value="">{copy.allProjectsOption}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  [{p.code}] {p.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => void loadHistory()}
            >
              {copy.refreshBtn}
            </button>
          </div>
        </div>

        {loadingHistory ? (
          <p className="muted-hint">{copy.loadingHistory}</p>
        ) : runs.length === 0 ? (
          <p className="muted-hint">{copy.emptyHistory}</p>
        ) : (
          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>{copy.colDate}</th>
                  <th>{copy.colQuery}</th>
                  <th>{copy.colProvider}</th>
                  <th>{copy.colSources}</th>
                  <th>{copy.colStatus}</th>
                  <th>{copy.colClass}</th>
                  <th>{copy.colActions}</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td dir="ltr">{formatDate(r.created_at)}</td>
                    <td dir="auto">
                      <strong>{r.query}</strong>
                    </td>
                    <td dir="ltr">
                      <code>{r.search_provider}</code>
                    </td>
                    <td dir="ltr">
                      {r.accessible_sources} / {r.inaccessible_sources} (total {r.total_sources})
                    </td>
                    <td dir="ltr">
                      <span
                        className={`badge ${
                          r.status === "completed" ? "badge-connected" : "badge-warn"
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td>
                      <span className="badge">{r.classification}</span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-compact"
                        onClick={() => void handleInspectRun(r.id)}
                      >
                        {copy.inspectBtn}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {activeRun && (
        <section className="subpanel" aria-label={copy.detailHeading}>
          <div className="panel-header">
            <h4 className="panel-title" dir="auto">
              {copy.detailHeading} — {activeRun.query}
            </h4>
            <div className="badge-group">
              <span className="badge">{activeRun.classification}</span>
              <span className="badge" dir="ltr">
                {activeRun.search_provider}
              </span>
              <span className="badge" dir="ltr">
                {activeRun.token_usage.total_tokens} tokens
              </span>
            </div>
          </div>

          {activeRun.summary && (
            <p dir="auto" style={{ marginTop: 0, lineHeight: 1.6 }}>
              {activeRun.summary}
            </p>
          )}

          {activeRun.artifact_relative_path && (
            <div className="status-box status-ok" style={{ marginBottom: "0.75rem" }}>
              Artifact: <code dir="ltr">{activeRun.artifact_relative_path}</code>
            </div>
          )}

          {activeRun.structured_output &&
            activeRun.structured_output.injection_attempts_ignored.length > 0 && (
              <div className="status-box notice-box" style={{ marginBottom: "0.75rem" }}>
                <strong>{copy.injectionHeading}:</strong>
                <ul className="outcome-list">
                  {activeRun.structured_output.injection_attempts_ignored.map((msg, i) => (
                    <li key={i} dir="auto">
                      {msg}
                    </li>
                  ))}
                </ul>
              </div>
            )}

          {activeRun.structured_output &&
            activeRun.structured_output.unreviewed_or_inaccessible.length > 0 && (
              <div className="status-box notice-box" style={{ marginBottom: "0.75rem" }}>
                <strong>{copy.unreviewedHeading}:</strong>
                <ul className="outcome-list">
                  {activeRun.structured_output.unreviewed_or_inaccessible.map((msg, i) => (
                    <li key={i} dir="ltr">
                      {msg}
                    </li>
                  ))}
                </ul>
              </div>
            )}

          {activeRun.structured_output &&
            activeRun.structured_output.verified_findings.length > 0 && (
              <div style={{ marginBottom: "0.9rem" }}>
                <h5 className="folders-title">{copy.findingsHeading}</h5>
                <ul className="outcome-list">
                  {activeRun.structured_output.verified_findings.map((f, i) => (
                    <li key={i} dir="auto">
                      <strong>[{f.priority_tier}]</strong> {f.claim}{" "}
                      <span dir="ltr">
                        (<a href={f.source_url} target="_blank" rel="noreferrer">{f.source_name}</a>
                        {f.publication_date ? `, ${f.publication_date}` : ""})
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

          <h5 className="folders-title">{copy.sourceLogHeading}</h5>
          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>{copy.colPriority}</th>
                  <th>{copy.colSourceName}</th>
                  <th>{copy.colPubDate}</th>
                  <th>{copy.colAccessDate}</th>
                  <th>{copy.colExtracted}</th>
                  <th>{copy.colRating}</th>
                  <th>{copy.colReviewState}</th>
                </tr>
              </thead>
              <tbody>
                {activeRun.sources.map((src) => (
                  <tr key={src.id}>
                    <td dir="ltr">
                      #{src.priority_rank} ({src.source_priority_tier})
                    </td>
                    <td dir="auto">
                      <div>
                        <strong>{src.source_name}</strong>
                      </div>
                      <a href={src.url} target="_blank" rel="noreferrer" dir="ltr">
                        {src.url}
                      </a>
                    </td>
                    <td dir="ltr">{src.publication_date || "—"}</td>
                    <td dir="ltr">{formatDate(src.access_date)}</td>
                    <td dir="auto">{src.extracted_info || src.failure_reason || "—"}</td>
                    <td dir="ltr">
                      <code>{src.reliability_rating}</code>
                    </td>
                    <td>
                      <span
                        className={`badge ${src.reviewed ? "badge-connected" : "badge-warn"}`}
                      >
                        {src.reviewed ? copy.reviewedTag : copy.inaccessibleTag}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
