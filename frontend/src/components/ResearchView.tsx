import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  getResearchCapabilities,
  getResearchRunDetail,
  listProjectFiles,
  listProjects,
  listResearchRuns,
  runControlledResearch,
  synthesizeResearchRun,
} from "../api";
import type {
  Lang,
  OwnerProvidedSourceInput,
  ProjectClassification,
  ProjectFileOut,
  ProjectSummary,
  ResearchCapabilitiesOut,
  ResearchRunDetailOut,
  ResearchRunSummaryOut,
  SearchProviderName,
  SourcePriorityTier,
  TaskComplexity,
} from "../types";

interface ResearchCopy {
  heading: string;
  hint: string;
  policyBanner: string;
  projectLabel: string;
  allProjectsOption: string;
  ownerFilesLabel: string;
  ownerFilesHint: string;
  ownerTierLabel: string;
  queryLabel: string;
  queryPlaceholder: string;
  urlsLabel: string;
  urlsPlaceholder: string;
  providerLabel: string;
  maxResultsLabel: string;
  complexityLabel: string;
  complexityFast: string;
  complexityDeep: string;
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
  ownerProvidedTag: string;
  inaccessibleTag: string;
  notRelevantTag: string;
  unrankedTag: string;
  providerClaimNote: string;
  ownerTierNote: string;
  tokenEstimateHeading: string;
  confirmSynthesizeBtn: string;
  synthesizingBtn: string;
  errorPrefix: string;
}

const PROVIDER_LABELS: Record<Lang, Record<string, string>> = {
  ar: {
    duckduckgo_lite: "DuckDuckGo Lite (أفضل جهد — مجاني بدون مفتاح)",
    crossref: "Crossref الأبحاث المحكمة (مجاني بدون مفتاح)",
    tavily: "Tavily API (مُوصى به — مفتاح مجاني في الإعدادات)",
    serper: "Serper.dev بحث جوجل (مفتاح اختياري في الإعدادات)",
    brave: "Brave Search (مفتاح اختياري في الإعدادات)",
  },
  en: {
    duckduckgo_lite: "DuckDuckGo Lite (Best-Effort Free, Zero Key)",
    crossref: "Crossref Peer-Reviewed (Free, Zero Key)",
    tavily: "Tavily API (Recommended Free Key in Settings)",
    serper: "Serper.dev (Optional Key in Keyring)",
    brave: "Brave Search (Optional Key in Keyring)",
  },
};

const RUN_STATUS_LABELS: Record<Lang, Record<string, string>> = {
  ar: {
    completed: "مكتمل",
    partial_inaccessible: "جزئي (توجد مستندات متعذرة)",
    no_accessible_sources: "لا توجد مصادر متاحة (دون استهلاك AI)",
    failed: "فشل التنفيذ",
  },
  en: {
    completed: "completed",
    partial_inaccessible: "partial_inaccessible",
    no_accessible_sources: "no_accessible_sources",
    failed: "failed",
  },
};

const TIER_LABELS: Record<Lang, Record<string, string>> = {
  ar: {
    official_regulations: "تشريعات ولوائح رسمية",
    standards_bodies: "هيئات المواصفات القياسية",
    government: "منشورات حكومية",
    manufacturer: "وثائق الشركات المصنعة",
    peer_reviewed: "أبحاث علمية محكمة",
    reputable: "مراجع تقنية موثوقة",
    unverified: "غير موثق",
  },
  en: {
    official_regulations: "official_regulations",
    standards_bodies: "standards_bodies",
    government: "government",
    manufacturer: "manufacturer",
    peer_reviewed: "peer_reviewed",
    reputable: "reputable",
    unverified: "unverified",
  },
};

const RATING_LABELS: Record<Lang, Record<string, string>> = {
  ar: {
    high_official_regulation: "عالٍ — لائحة/تشريع رسمي",
    high_standards_body: "عالٍ — هيئة مواصفات",
    high_government: "عالٍ — مرجع حكومي",
    medium_manufacturer: "متوسط — وثيقة مصنّع",
    medium_peer_reviewed: "متوسط — ورقة محكمة",
    low_reputable_reference: "منخفض — مرجع موثوق",
    unrated: "غير مُقيَّم (ادعاء غير مُتحقق)",
    unreviewed: "غير مراجَع",
  },
  en: {
    high_official_regulation: "high_official_regulation",
    high_standards_body: "high_standards_body",
    high_government: "high_government",
    medium_manufacturer: "medium_manufacturer",
    medium_peer_reviewed: "medium_peer_reviewed",
    low_reputable_reference: "low_reputable_reference",
    unrated: "unrated",
    unreviewed: "unreviewed",
  },
};

const COPY: Record<Lang, ResearchCopy> = {
  ar: {
    heading: "البحث الهندسي المضبوط وسجل المصادر",
    hint: "يبحث النظام في المصادر المصرّح بها أو يفحص الروابط والملفات المرفوعة مباشرةً، ولا يعتمد على مقتطفات محركات البحث مطلقاً.",
    policyBanner:
      "أولوية الموثوقية: (1) التشريعات واللوائح الرسمية ← (2) هيئات المواصفات القياسية ← (3) المنشورات الحكومية ← (4) وثائق الشركات المصنعة ← (5) الأوراق المحكمة ← (6) المراجع الموثوقة. كافة الصفحات المجلوبة بيانات غير موثوقة وتُسجَّل المستندات المتعذرة كغير مراجَعة.",
    projectLabel: "ربط بمشروع (اختياري)",
    allProjectsOption: "بحث عام (بدون ربط بمشروع محدد)",
    ownerFilesLabel: "أو إرفاق ملفات مرفوعة مسبقاً من المشروع كمصدر مُقدَّم من المالك",
    ownerFilesHint: "مفيد للمستندات المحمية بـ HTTP 403/Paywall: نزّلها ثم ارفعها في «المشاريع والملفات» واخترها هنا.",
    ownerTierLabel: "تصنيف أولوية الملفات المرفقة",
    queryLabel: "موضوع أو سؤال البحث الهندسي *",
    queryPlaceholder: "مثال: متطلبات التهوية لغرف العمليات NFPA 99 أو لائحة السلامة المهنية",
    urlsLabel: "روابط محددة للتحقق المباشر (اختياري — رابط في كل سطر)",
    urlsPlaceholder: "https://example.org/regulation.pdf",
    providerLabel: "مزوّد البحث",
    maxResultsLabel: "الحد الأقصى للنتائج",
    complexityLabel: "مستوى التحليل الذكي",
    complexityFast: "سريع (Fast)",
    complexityDeep: "عميق (Deep)",
    classificationLabel: "تصنيف الإخراج",
    aiToggleLabel: "تلخيص النتائج عبر Gemini (ضمن حدود الاستخدام في الخطوة 04 — لا يُستدعى إذا لم يتوفر أي مصدر متاح)",
    submitBtn: "تنفيذ البحث المضبوط وحفظ سجل المصادر",
    submittingBtn: "جاري البحث وجلب الصفحات والتحقق منها...",
    historyHeading: "سجل أبحاث الإنترنت والمصادر",
    refreshBtn: "تحديث السجل",
    loadingHistory: "جاري تحميل سجل الأبحاث...",
    emptyHistory: "لا توجد عمليات بحث مسجلة حتى الآن.",
    inspectBtn: "عرض المصادر والنتائج",
    detailHeading: "تفاصيل البحث وسجل المصادر الموثّق",
    colDate: "التاريخ",
    colQuery: "الاستعلام",
    colProvider: "المزود",
    colSources: "المصادر (متاح / مالك / متعذر)",
    colStatus: "الحالة",
    colClass: "التصنيف",
    colActions: "عرض",
    unreviewedHeading: "مستندات تعذر الوصول إليها (غير مراجَعة — يُرجى تنزيلها ورفعها يدوياً)",
    injectionHeading: "محاولات حقن تعليمات تم تجاهلها وتحييدها بأمان",
    findingsHeading: "النتائج الموثقة من مصادر تم التحقق من قراءتها",
    sourceLogHeading: "جدول سجل المصادر الكامل",
    colPriority: "تصنيف الأولوية",
    colSourceName: "المصدر والرابط",
    colPubDate: "تاريخ النشر",
    colAccessDate: "تاريخ الوصول",
    colExtracted: "المعلومات المستخلصة",
    colRating: "تقييم الموثوقية",
    colReviewState: "حالة المراجعة",
    reviewedTag: "تمت المراجعة",
    ownerProvidedTag: "مُقدَّم من المالك (تمت المراجعة)",
    inaccessibleTag: "متعذر — غير مراجَع",
    notRelevantTag: "غير ذي صلة — لم يُقتبس",
    unrankedTag: "غير مصنّف",
    providerClaimNote: "ادعاء من المزوّد (غير مُتحقق)",
    ownerTierNote: "اختيار المالك",
    tokenEstimateHeading: "تقدير التوكنات قبل استدعاء Gemini (حدود الخطوة 04 وتقييد النص):",
    confirmSynthesizeBtn: "تأكيد وتشغيل تلخيص Gemini",
    synthesizingBtn: "جاري تلخيص المصادر المراجَعة عبر Gemini...",
    errorPrefix: "تعذر إتمام البحث: ",
  },
  en: {
    heading: "Controlled Internet Research & Citation Log",
    hint: "Executes web search and directly fetches full target pages/PDFs or reads owner-uploaded files. Search-engine snippets are discarded and never treated as evidence.",
    policyBanner:
      "Priority Order: (1) Official Regulations → (2) Standards Bodies → (3) Government → (4) Manufacturers → (5) Peer-Reviewed → (6) Reputable References. All fetched pages are isolated as untrusted data; inaccessible documents are marked UNREVIEWED.",
    projectLabel: "Link to Project (optional)",
    allProjectsOption: "General / Unlinked Research",
    ownerFilesLabel: "Attach Uploaded Project Files as Owner-Provided Sources (optional)",
    ownerFilesHint: "For HTTP 403/paywalled standards: download the document yourself and upload it in Projects & Files, then attach it here.",
    ownerTierLabel: "Priority Tier for Attached Owner Files",
    queryLabel: "Engineering Research Query *",
    queryPlaceholder: "e.g., Operating theatre ACH ventilation NFPA 99 ASHRAE 170",
    urlsLabel: "Explicit URLs to Fetch & Verify Directly (optional, one per line)",
    urlsPlaceholder: "https://example.org/standard.pdf",
    providerLabel: "Search Backend",
    maxResultsLabel: "Max Results",
    complexityLabel: "AI Complexity",
    complexityFast: "Fast",
    complexityDeep: "Deep",
    classificationLabel: "Classification",
    aiToggleLabel: "Synthesize via Gemini AI (enforces Step 04 limits; skipped when 0 sources accessible)",
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
    colSources: "Sources (Web / Owner / Blocked)",
    colStatus: "Status",
    colClass: "Classification",
    colActions: "Inspect",
    unreviewedHeading: "Inaccessible Documents (UNREVIEWED — Download & Upload in Projects & Files)",
    injectionHeading: "Untrusted Prompt-Injection Attempts Safely Ignored",
    findingsHeading: "Verified Findings (Grounded in Reviewed Sources Only)",
    sourceLogHeading: "Complete Persisted Source Log",
    colPriority: "Priority Tier",
    colSourceName: "Source Name & URL",
    colPubDate: "Published",
    colAccessDate: "Accessed",
    colExtracted: "Extracted Info",
    colRating: "Reliability Rating",
    colReviewState: "Status",
    reviewedTag: "Reviewed",
    ownerProvidedTag: "Owner-Provided (Reviewed)",
    inaccessibleTag: "Inaccessible — Unreviewed",
    notRelevantTag: "Not Relevant — Omitted",
    unrankedTag: "unranked",
    providerClaimNote: "Provider claim (not verified)",
    ownerTierNote: "Owner-selected tier",
    tokenEstimateHeading: "Pre-flight AI Token Estimate (Prompt Capped & Step 04 Budget Guard):",
    confirmSynthesizeBtn: "Confirm & Run Gemini Synthesis",
    synthesizingBtn: "Synthesizing reviewed prose with Gemini...",
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
  const [projectFiles, setProjectFiles] = useState<ProjectFileOut[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [ownerFileTier, setOwnerFileTier] = useState<SourcePriorityTier>("official_regulations");
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
  const [synthesizing, setSynthesizing] = useState<boolean>(false);
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

  useEffect(() => {
    setSelectedFileIds([]);
    if (!projectId) {
      setProjectFiles([]);
      return;
    }
    void listProjectFiles(projectId)
      .then((res) => setProjectFiles(res.files))
      .catch(() => setProjectFiles([]));
  }, [projectId]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const urls = urlsText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    const ownerFiles: OwnerProvidedSourceInput[] = selectedFileIds.map((fileId) => ({
      file_id: fileId,
      priority_tier: ownerFileTier,
    }));
    // On large runs (3+ requested results/URLs/files), run 0-token fetch & quality/relevance filter FIRST
    // so the owner sees how many sources survived and exact estimated tokens before calling Gemini.
    const isLargeRun = maxResults >= 3 || urls.length >= 3 || ownerFiles.length >= 3;
    try {
      const detail = await runControlledResearch({
        query,
        project_id: projectId || null,
        urls,
        owner_files: ownerFiles,
        search_provider: searchProvider,
        max_results: maxResults,
        complexity,
        classification,
        synthesize_with_ai: synthesizeWithAi && !isLargeRun,
      });
      setActiveRun(detail);
      setQuery("");
      setUrlsText("");
      setSelectedFileIds([]);
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await loadHistory();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirmSynthesize(runId: string) {
    setSynthesizing(true);
    setError(null);
    try {
      const updated = await synthesizeResearchRun(runId, complexity);
      setActiveRun(updated);
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await loadHistory();
    } finally {
      setSynthesizing(false);
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
                {PROVIDER_LABELS[lang][p.id] || p.label}
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
                <option value="duckduckgo_lite">{PROVIDER_LABELS[lang].duckduckgo_lite}</option>
                <option value="crossref">{PROVIDER_LABELS[lang].crossref}</option>
                <option value="tavily">{PROVIDER_LABELS[lang].tavily}</option>
                <option value="serper">{PROVIDER_LABELS[lang].serper}</option>
                <option value="brave">{PROVIDER_LABELS[lang].brave}</option>
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

          {projectFiles.length > 0 && (
            <div className="status-box" style={{ marginTop: 0 }}>
              <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>{copy.ownerFilesLabel}</div>
              <p className="muted-hint" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
                {copy.ownerFilesHint}
              </p>
              <label style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.5rem" }}>
                <span>{copy.ownerTierLabel}:</span>
                <select
                  value={ownerFileTier}
                  onChange={(e) => setOwnerFileTier(e.target.value as SourcePriorityTier)}
                >
                  <option value="official_regulations">{TIER_LABELS[lang].official_regulations}</option>
                  <option value="standards_bodies">{TIER_LABELS[lang].standards_bodies}</option>
                  <option value="government">{TIER_LABELS[lang].government}</option>
                  <option value="manufacturer">{TIER_LABELS[lang].manufacturer}</option>
                  <option value="peer_reviewed">{TIER_LABELS[lang].peer_reviewed}</option>
                  <option value="reputable">{TIER_LABELS[lang].reputable}</option>
                </select>
              </label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
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
                  <option value="fast">{copy.complexityFast}</option>
                  <option value="deep">{copy.complexityDeep}</option>
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
                    <td dir="auto">
                      <span>{PROVIDER_LABELS[lang][r.search_provider] || r.search_provider}</span>
                    </td>
                    <td dir="ltr">
                      {r.accessible_sources} / {r.owner_provided_sources ?? 0} / {r.inaccessible_sources + (r.not_relevant_sources ?? 0)}
                    </td>
                    <td dir="auto">
                      <span
                        className={`badge ${
                          r.status === "completed" ? "badge-connected" : "badge-warn"
                        }`}
                      >
                        {RUN_STATUS_LABELS[lang][r.status] || r.status}
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
              <span className="badge" dir="auto">
                {PROVIDER_LABELS[lang][activeRun.search_provider] || activeRun.search_provider}
              </span>
              <span className="badge" dir="auto">
                {RUN_STATUS_LABELS[lang][activeRun.status] || activeRun.status}
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

          {activeRun.token_usage.total_tokens === 0 &&
            activeRun.accessible_sources + (activeRun.owner_provided_sources ?? 0) > 0 && (
              <div className="status-box notice-box" style={{ marginBottom: "0.75rem" }}>
                <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>
                  {copy.tokenEstimateHeading}
                </div>
                <div dir="auto" style={{ marginBottom: "0.5rem" }}>
                  <code>~{activeRun.estimated_prompt_tokens ?? 0} est. prompt tokens</code>{" "}
                  ({activeRun.prompt_char_count ?? 0} / {activeRun.prompt_char_cap ?? 10000} chars cap)
                  {activeRun.step04_daily_tokens_remaining != null && (
                    <span>
                      {" "}
                      · Step 04 daily remaining:{" "}
                      <strong>{activeRun.step04_daily_tokens_remaining.toLocaleString()}</strong> tokens
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  className="btn btn-compact"
                  disabled={synthesizing}
                  onClick={() => void handleConfirmSynthesize(activeRun.id)}
                >
                  {synthesizing
                    ? copy.synthesizingBtn
                    : `${copy.confirmSynthesizeBtn} (~${activeRun.estimated_prompt_tokens ?? 0} est. tokens)`}
                </button>
              </div>
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
                    <td dir="auto">
                      {src.reviewed ? (
                        <div>
                          <span>
                            {TIER_LABELS[lang][src.source_priority_tier] || src.source_priority_tier}
                          </span>
                          <div className="muted-hint" style={{ fontSize: "0.78rem" }}>
                            {src.tier_is_provider_claim === false
                              ? copy.ownerTierNote
                              : src.tier_claim_label || copy.providerClaimNote}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <span className="badge badge-warn">{copy.unrankedTag}</span>
                          <div className="muted-hint" style={{ fontSize: "0.78rem" }}>
                            {src.tier_claim_label || copy.providerClaimNote}
                          </div>
                        </div>
                      )}
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
                    <td dir="auto">
                      <div style={{ maxHeight: "9rem", overflowY: "auto" }}>
                        {src.extracted_info || src.failure_reason || "—"}
                      </div>
                    </td>
                    <td dir="auto">
                      <code>{RATING_LABELS[lang][src.reliability_rating] || src.reliability_rating}</code>
                    </td>
                    <td>
                      <span
                        className={`badge ${src.reviewed ? "badge-connected" : "badge-warn"}`}
                      >
                        {src.access_status === "owner_provided"
                          ? copy.ownerProvidedTag
                          : src.access_status === "not_relevant"
                            ? copy.notRelevantTag
                            : src.reviewed
                              ? copy.reviewedTag
                              : copy.inaccessibleTag}
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
