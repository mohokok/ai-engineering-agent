import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  approveSpecialistAssessment,
  createSpecialistAssessment,
  exportSpecialistDeliverables,
  getDeliverableDownloadUrl,
  getSpecialistDetail,
  listProjectSpecialistAssessments,
  listProjects,
  listResearchSources,
  listSpecialistPresets,
  listStandards,
} from "../api";
import type {
  Lang,
  ProjectClassification,
  ProjectSummary,
  ReportLanguage,
  ResearchSourceOut,
  SpecialistDetailOut,
  SpecialistDomain,
  SpecialistPresetOut,
  SpecialistReferenceIn,
  SpecialistSummaryOut,
  SpecialistWorkflowMode,
  StandardDocumentOut,
} from "../types";

const DOMAINS: SpecialistDomain[] = ["hvac", "fire", "healthcare"];
const MODES: SpecialistWorkflowMode[] = ["full_preflight", "input_preparation", "output_check"];
const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const COPY: Record<
  Lang,
  {
    heading: string;
    subtitle: string;
    notice: string;
    projectLabel: string;
    presetLabel: string;
    loadPresetBtn: string;
    domainLabel: string;
    modeLabel: string;
    titleLabel: string;
    classLabel: string;
    langLabel: string;
    stdSelectLabel: string;
    noStdOption: string;
    rsSelectLabel: string;
    noRsOption: string;
    inputsJsonLabel: string;
    useAiCheck: string;
    runBtn: string;
    runningBtn: string;
    listHeading: string;
    emptyList: string;
    detailHeading: string;
    selectPrompt: string;
    softwareHeading: string;
    prelimHeading: string;
    aiApproveBtn: string;
    exportBtn: string;
    exportingBtn: string;
    checksHeading: string;
    preparedHeading: string;
    refsHeading: string;
    equationsHeading: string;
    deliverablesHeading: string;
  }
> = {
  ar: {
    heading: "الخطوة 18: تحضير المدخلات وفحص المخرجات — التكييف (HVAC) والحريق (Fire) والرعاية الصحية",
    subtitle:
      "أداة تحضير مدخلات ومراجعة منطقية حتمية فقط (0 توكن افتراضياً) — لا تستبدل المهندس المرخص أو برمجيات المحاكاة المعتمدة.",
    notice:
      "تنبيه إلزامي: جميع الحسابات والحدود الأولية تتطلب اعتماد مهندس مرخص، ولا يُستشهَد بـ WHO/FGI/NFPA/ASHRAE إلا من مكتبة المعايير أو سجل المصادر المُراجع، وإلا يُعرَض 'no verified standard on file - verify against the locally adopted code'. المدخلات الناقصة تمنع الاعتماد باسم 'not provided'.",
    projectLabel: "المشروع",
    presetLabel: "نموذج تمثيلي أولي (Synthetic)",
    loadPresetBtn: "تعبئة النموذج",
    domainLabel: "التخصص",
    modeLabel: "الوضع (تحضير / فحص / شامل)",
    titleLabel: "عنوان التقييم",
    classLabel: "التصنيف",
    langLabel: "اللغة",
    stdSelectLabel: "معيار مالك موثق (اختياري)",
    noStdOption: "-- بدون معيار موثق (سيظهر إشعار verify against locally adopted code) --",
    rsSelectLabel: "مصدر بحثي مراجَع (WHO/FGI/Code)",
    noRsOption: "-- بدون مصدر بحثي إضافي --",
    inputsJsonLabel: "مدخلات المناطق / الفضاءات الهندسية (JSON — احذف أي قيمة لاختبار حجب 'not provided')",
    useAiCheck: "تفعيل ملخص نثري اختياري بالذكاء الاصطناعي (بوسم UNVERIFIED AI DRAFT — لا يؤثر على الحسابات)",
    runBtn: "تشغيل التحضير والفحص الحتمي",
    runningBtn: "جاري التنفيذ...",
    listHeading: "التقييمات المسجلة للتخصصات",
    emptyList: "لا توجد تقييمات تكييف/حريق/صحة مسجلة لهذا المشروع بعد.",
    detailHeading: "تفاصيل الفحص وتوصية البرمجيات والمخرجات",
    selectPrompt: "اختر تقييماً لعرض نتائج الفحص والمدخلات المحضّرة والتصدير.",
    softwareHeading: "توصية البرمجيات الهندسية المعتمدة",
    prelimHeading: "تنويه أولي والافتراضات",
    aiApproveBtn: "اعتماد المالك / المهندس للمسودة (Approve AI Draft)",
    exportBtn: "تصدير الحزمة (DOCX + PDF + XLSX حية)",
    exportingBtn: "جاري التصدير...",
    checksHeading: "جدول فحص المخرجات واكتمال المدخلات",
    preparedHeading: "جدول المدخلات المحضّرة والقيم",
    refsHeading: "حالة المراجع والمعايير",
    equationsHeading: "المعادلات والمنهجية",
    deliverablesHeading: "الملفات المُصدَّرة وبصمة SHA-256",
  },
  en: {
    heading: "Step 18: HVAC, Fire & Healthcare — Input Preparation & Output Check Skills",
    subtitle:
      "Deterministic preflight preparation & output checking ONLY (0 AI tokens default). Validated commercial software & a licensed engineer remain mandatory for final sign-off.",
    notice:
      "Mandatory Policy: Presets and assumptions are preliminary and require a licensed engineer. Cite WHO/FGI/NFPA/ASHRAE ONLY when present in the owner's Standards Library or reviewed ResearchSource log — otherwise display 'no verified standard on file - verify against the locally adopted code'. Missing inputs render as 'not provided' and block that result.",
    projectLabel: "Project",
    presetLabel: "Synthetic Fixture Preset (Preliminary)",
    loadPresetBtn: "Load Synthetic Preset",
    domainLabel: "Domain",
    modeLabel: "Workflow Mode",
    titleLabel: "Assessment Title",
    classLabel: "Classification",
    langLabel: "Language",
    stdSelectLabel: "Verified Standards Library Entry (Optional)",
    noStdOption: "-- None (emits 'no verified standard on file - verify against the locally adopted code') --",
    rsSelectLabel: "Reviewed ResearchSource (WHO / FGI / Code)",
    noRsOption: "-- No additional ResearchSource --",
    inputsJsonLabel: "Zone / Space Inputs JSON (omit any required value to test 'not provided' blocking)",
    useAiCheck: "Optional AI summary prose (tagged UNVERIFIED AI DRAFT; 0 effect on checks)",
    runBtn: "Run Preparation & Preflight Checks",
    runningBtn: "Evaluating...",
    listHeading: "Project Specialist Assessments",
    emptyList: "No HVAC, Fire, or Healthcare assessments recorded yet for this project.",
    detailHeading: "Assessment Results, Software Handoff & Exports",
    selectPrompt: "Select an assessment from the list to inspect check verdicts, prepared inputs, and exports.",
    softwareHeading: "Validated Commercial Software Recommendation",
    prelimHeading: "Preliminary Engineer Warning & Assumptions",
    aiApproveBtn: "Approve AI Draft (Licensed Engineer / Owner)",
    exportBtn: "Export Package (DOCX + PDF + Live XLSX)",
    exportingBtn: "Exporting...",
    checksHeading: "Preflight Output Checks & Missing-Input Gates",
    preparedHeading: "Prepared Inputs & Computed Metrics",
    refsHeading: "Standards & Source Log Verification",
    equationsHeading: "Deterministic Equations & Methodology",
    deliverablesHeading: "Exported Immutable Deliverables (SHA-256)",
  },
};

function verdictBadgeStyle(row: { status: string; checks_passed: boolean }): Record<string, string> {
  if (row.status === "blocked_missing_inputs") {
    return { backgroundColor: "#fef7e0", color: "#9a6700", border: "1px solid #f6d57f" };
  }
  if (row.checks_passed) {
    return { backgroundColor: "#e6f4ea", color: "#137333", border: "1px solid #a8dab5" };
  }
  return { backgroundColor: "#fce8e6", color: "#c5221f", border: "1px solid #f4a9a2" };
}

export function SpecialistEngineeringView({
  lang,
  initialPresets = [],
  initialAssessments = [],
  initialSelected = null,
}: {
  lang: Lang;
  initialPresets?: SpecialistPresetOut[];
  initialAssessments?: SpecialistSummaryOut[];
  initialSelected?: SpecialistDetailOut | null;
}) {
  const t = COPY[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [presets, setPresets] = useState<SpecialistPresetOut[]>(initialPresets);
  const [selectedPresetKey, setSelectedPresetKey] = useState<string>(initialPresets[0]?.key || "");

  const [standards, setStandards] = useState<StandardDocumentOut[]>([]);
  const [researchSources, setResearchSources] = useState<ResearchSourceOut[]>([]);
  const [assessments, setAssessments] = useState<SpecialistSummaryOut[]>(initialAssessments);
  const [selectedDetail, setSelectedDetail] = useState<SpecialistDetailOut | null>(initialSelected);

  const [domain, setDomain] = useState<SpecialistDomain>("hvac");
  const [workflowMode, setWorkflowMode] = useState<SpecialistWorkflowMode>("full_preflight");
  const [title, setTitle] = useState<string>("Synthetic Clinic HVAC Preflight Check");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [outLang, setOutLang] = useState<ReportLanguage>(lang === "ar" ? "ar" : "en");
  const [selectedStdId, setSelectedStdId] = useState<string>("");
  const [selectedRsId, setSelectedRsId] = useState<string>("");
  const [inputsJsonText, setInputsJsonText] = useState<string>(
    initialPresets[0] ? JSON.stringify(initialPresets[0].inputs, null, 2) : '{"zones": []}'
  );
  const [useAi, setUseAi] = useState<boolean>(false);

  const [submitting, setSubmitting] = useState<boolean>(false);
  const [exporting, setExporting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [infoMsg, setInfoMsg] = useState<string | null>(null);

  const loadProjectContext = useCallback(async (pid: string) => {
    if (!pid) return;
    try {
      const [listRes, stdRes, rsRes] = await Promise.all([
        listProjectSpecialistAssessments(pid),
        listStandards({ project_id: pid, include_global: true }),
        listResearchSources({ project_id: pid, reviewed_only: true }),
      ]);
      setAssessments(listRes.assessments);
      setStandards(stdRes.standards);
      setResearchSources(
        rsRes.sources.filter(
          (rs) => rs.reviewed && (rs.access_status === "accessible" || rs.access_status === "owner_provided")
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [projRes, presetRes] = await Promise.all([listProjects(), listSpecialistPresets()]);
        setProjects(projRes.projects);
        setPresets(presetRes.presets);
        if (presetRes.presets.length > 0) {
          const p0 = presetRes.presets[0];
          setSelectedPresetKey(p0.key);
          setDomain(p0.domain);
          setWorkflowMode(p0.workflow_mode);
          setInputsJsonText(JSON.stringify(p0.inputs, null, 2));
        }
        if (projRes.projects.length > 0) {
          const firstPid = projRes.projects[0].id;
          setSelectedProjectId((prev) => prev || firstPid);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      void loadProjectContext(selectedProjectId);
    }
  }, [loadProjectContext, selectedProjectId]);

  const handleLoadPreset = () => {
    const preset = presets.find((p) => p.key === selectedPresetKey);
    if (!preset) return;
    setDomain(preset.domain);
    setWorkflowMode(preset.workflow_mode);
    setTitle(lang === "ar" ? preset.label_ar : preset.label_en);
    setInputsJsonText(JSON.stringify(preset.inputs, null, 2));
    setError(null);
    setInfoMsg(preset.preliminary_warning);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId) {
      setError("Select a project first.");
      return;
    }
    let parsedInputs: Record<string, unknown>;
    try {
      parsedInputs = JSON.parse(inputsJsonText) as Record<string, unknown>;
    } catch {
      setError("Inputs JSON is invalid JSON.");
      return;
    }

    const refs: SpecialistReferenceIn[] = [];
    if (selectedStdId) {
      refs.push({ source_kind: "standard_library", standard_library_id: selectedStdId });
    }
    if (selectedRsId) {
      refs.push({ source_kind: "verified_source_log", research_source_id: selectedRsId });
    }

    setSubmitting(true);
    setError(null);
    setInfoMsg(null);
    try {
      const created = await createSpecialistAssessment(selectedProjectId, {
        domain,
        workflow_mode: workflowMode,
        title: title.trim() || `${domain.toUpperCase()} Preflight`,
        language: outLang,
        classification,
        inputs: parsedInputs,
        references: refs,
        use_ai: useAi,
      });
      setSelectedDetail(created);
      setInfoMsg(
        `${created.domain.toUpperCase()} v${created.version} evaluated (tokens=${created.tokens_used}, standards=${created.standards_status}).`
      );
      await loadProjectContext(selectedProjectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSelectAssessment = async (id: string) => {
    setError(null);
    try {
      const det = await getSpecialistDetail(id);
      setSelectedDetail(det);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleApproveAi = async () => {
    if (!selectedDetail) return;
    setError(null);
    try {
      const updated = await approveSpecialistAssessment(selectedDetail.id, {
        approved_by: "Licensed Engineer / Owner",
      });
      setSelectedDetail(updated);
      setInfoMsg("Owner / Licensed Engineer approval recorded.");
      await loadProjectContext(selectedProjectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleExport = async () => {
    if (!selectedDetail) return;
    setExporting(true);
    setError(null);
    try {
      const res = await exportSpecialistDeliverables(selectedDetail.id, { language: outLang });
      setSelectedDetail(res.assessment);
      setInfoMsg(`Exported DOCX + PDF + XLSX into 04_Engineering_Calculations.`);
      await loadProjectContext(selectedProjectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  const preparedItems = (selectedDetail?.results?.prepared_items || []) as Array<Record<string, unknown>>;
  const preparedCols = preparedItems.length > 0 ? Object.keys(preparedItems[0]) : [];

  return (
    <div className="panel" data-testid="specialist-engineering-view">
      <h2>{t.heading}</h2>
      <p className="muted">{t.subtitle}</p>

      <div
        className="card"
        style={{ marginBottom: "1rem", backgroundColor: "#fff8e1", border: "1px solid #ffd54f" }}
      >
        <strong>{t.notice}</strong>
      </div>

      {error ? (
        <div className="alert error" role="alert">
          {error}
        </div>
      ) : null}
      {infoMsg ? (
        <div className="alert" style={{ backgroundColor: "#e8f5e9", color: "#1b5e20" }}>
          {infoMsg}
        </div>
      ) : null}

      <form className="card" style={{ marginBottom: "1rem" }} onSubmit={handleSubmit}>
        <div className="form-grid">
          <label>
            {t.projectLabel}
            <select
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} — {p.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            {t.presetLabel}
            <select
              value={selectedPresetKey}
              onChange={(e) => setSelectedPresetKey(e.target.value)}
            >
              {presets.map((p) => (
                <option key={p.key} value={p.key}>
                  {lang === "ar" ? p.label_ar : p.label_en}
                </option>
              ))}
            </select>
          </label>

          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <button type="button" className="btn btn-secondary" onClick={handleLoadPreset}>
              {t.loadPresetBtn}
            </button>
          </div>

          <label>
            {t.domainLabel}
            <select
              value={domain}
              onChange={(e) => setDomain(e.target.value as SpecialistDomain)}
            >
              {DOMAINS.map((d) => (
                <option key={d} value={d}>
                  {d.toUpperCase()}
                </option>
              ))}
            </select>
          </label>

          <label>
            {t.modeLabel}
            <select
              value={workflowMode}
              onChange={(e) => setWorkflowMode(e.target.value as SpecialistWorkflowMode)}
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>

          <label>
            {t.titleLabel}
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </label>

          <label>
            {t.classLabel}
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
          </label>

          <label>
            {t.langLabel}
            <select
              value={outLang}
              onChange={(e) => setOutLang(e.target.value as ReportLanguage)}
            >
              <option value="ar">العربية (RTL)</option>
              <option value="en">English (LTR)</option>
            </select>
          </label>

          <label>
            {t.stdSelectLabel}
            <select value={selectedStdId} onChange={(e) => setSelectedStdId(e.target.value)}>
              <option value="">{t.noStdOption}</option>
              {standards.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.standard_number} ({s.edition_year}) [{s.status}]
                </option>
              ))}
            </select>
          </label>

          <label>
            {t.rsSelectLabel}
            <select value={selectedRsId} onChange={(e) => setSelectedRsId(e.target.value)}>
              <option value="">{t.noRsOption}</option>
              {researchSources.map((rs) => (
                <option key={rs.id} value={rs.id}>
                  {rs.source_name} ({rs.source_priority_tier})
                </option>
              ))}
            </select>
          </label>
        </div>

        <label style={{ display: "block", marginTop: "0.75rem" }}>
          {t.inputsJsonLabel}
          <textarea
            rows={7}
            style={{ width: "100%", fontFamily: "monospace", marginTop: "0.25rem" }}
            value={inputsJsonText}
            onChange={(e) => setInputsJsonText(e.target.value)}
          />
        </label>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "1rem",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: "0.75rem",
          }}
        >
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={useAi}
              onChange={(e) => setUseAi(e.target.checked)}
            />
            <span>{t.useAiCheck}</span>
          </label>

          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? t.runningBtn : t.runBtn}
          </button>
        </div>
      </form>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(280px, 1fr) minmax(380px, 1.6fr)",
          gap: "1rem",
        }}
      >
        <div className="card">
          <h3>
            {t.listHeading} ({assessments.length})
          </h3>
          {assessments.length === 0 ? (
            <p className="muted">{t.emptyList}</p>
          ) : (
            <div style={{ display: "grid", gap: "0.5rem" }}>
              {assessments.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => void handleSelectAssessment(a.id)}
                  style={{
                    textAlign: lang === "ar" ? "right" : "left",
                    padding: "0.75rem",
                    borderRadius: "8px",
                    border:
                      selectedDetail?.id === a.id ? "2px solid #0b57d0" : "1px solid #cbd5e1",
                    backgroundColor: selectedDetail?.id === a.id ? "#f0f7ff" : "#ffffff",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                    <strong>
                      [{a.domain.toUpperCase()}] {a.title}
                    </strong>
                    <span
                      style={{
                        ...verdictBadgeStyle(a),
                        padding: "0.15rem 0.5rem",
                        borderRadius: "999px",
                        fontSize: "0.76rem",
                        fontWeight: 600,
                      }}
                    >
                      {a.status === "blocked_missing_inputs"
                        ? "BLOCKED"
                        : a.checks_passed
                        ? "PASS (PRELIM)"
                        : "FAIL"}
                    </span>
                  </div>
                  <div className="muted" style={{ fontSize: "0.78rem", marginTop: "0.25rem" }}>
                    {a.workflow_mode} | v{a.version} | tokens={a.tokens_used} | {a.standards_status}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3>{t.detailHeading}</h3>
          {!selectedDetail ? (
            <p className="muted">{t.selectPrompt}</p>
          ) : (
            <div style={{ display: "grid", gap: "0.85rem" }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
                <strong>
                  [{selectedDetail.domain.toUpperCase()}] {selectedDetail.title}
                </strong>
                <span className="badge">{selectedDetail.classification}</span>
                <span className="badge">{selectedDetail.revision} v{selectedDetail.version}</span>
                <span className="badge">Tokens: {selectedDetail.tokens_used}</span>
              </div>

              {selectedDetail.ai_draft_status === "unverified_ai_draft" ? (
                <div className="alert error">
                  <div>
                    <strong>{selectedDetail.ai_draft_label}</strong>
                  </div>
                  <button
                    type="button"
                    className="btn"
                    style={{ marginTop: "0.5rem" }}
                    onClick={() => void handleApproveAi()}
                  >
                    {t.aiApproveBtn}
                  </button>
                </div>
              ) : null}

              <div
                style={{
                  padding: "0.65rem",
                  backgroundColor: "#eff6ff",
                  border: "1px solid #93c5fd",
                  borderRadius: "6px",
                }}
              >
                <strong>{t.softwareHeading}:</strong> {selectedDetail.software_recommendation}
              </div>

              <div
                style={{
                  padding: "0.65rem",
                  backgroundColor: "#fff8e1",
                  border: "1px solid #ffd54f",
                  borderRadius: "6px",
                }}
              >
                <div>
                  <strong>{t.prelimHeading}:</strong> {selectedDetail.preliminary_label}
                </div>
                <ul style={{ margin: "0.35rem 0 0", paddingInlineStart: "1.2rem", fontSize: "0.84rem" }}>
                  {selectedDetail.preliminary_assumptions.map((asm, idx) => (
                    <li key={idx}>{asm}</li>
                  ))}
                </ul>
              </div>

              <div>
                <h4>{t.refsHeading}</h4>
                <ul style={{ margin: 0, paddingInlineStart: "1.2rem", fontSize: "0.86rem" }}>
                  {selectedDetail.references.map((rf, idx) => (
                    <li key={idx}>
                      <strong>{rf.source_kind}:</strong> {rf.code_or_source_name} —{" "}
                      <em>{rf.verification_label}</em> [{rf.status}]
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h4>{t.checksHeading}</h4>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Item</th>
                      <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Check</th>
                      <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Target</th>
                      <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Actual</th>
                      <th style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1" }}>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(selectedDetail.results.check_rows || []).map((c, idx) => (
                      <tr key={`${c.item_id}-${idx}`}>
                        <td style={{ padding: "0.25rem" }}>{c.item_id}</td>
                        <td style={{ padding: "0.25rem" }}>{c.label}</td>
                        <td style={{ padding: "0.25rem" }}>{c.expected}</td>
                        <td style={{ padding: "0.25rem" }}>{c.actual}</td>
                        <td style={{ padding: "0.25rem", fontWeight: 700 }}>{c.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {preparedItems.length > 0 ? (
                <div style={{ overflowX: "auto" }}>
                  <h4>{t.preparedHeading}</h4>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                    <thead>
                      <tr>
                        {preparedCols.map((col) => (
                          <th key={col} style={{ textAlign: "start", borderBottom: "1px solid #cbd5e1", padding: "0.25rem" }}>
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preparedItems.map((it, ridx) => (
                        <tr key={ridx}>
                          {preparedCols.map((col) => (
                            <td key={col} style={{ padding: "0.25rem", borderBottom: "1px solid #f1f5f9" }}>
                              {String(it[col] ?? "not provided")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              <div>
                <h4>{t.equationsHeading}</h4>
                <ul style={{ margin: 0, paddingInlineStart: "1.2rem", fontSize: "0.84rem" }}>
                  {(selectedDetail.results.equations || []).map((eq, i) => (
                    <li key={i}>
                      <code>{eq}</code>
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <button
                  type="button"
                  className="btn"
                  disabled={exporting}
                  onClick={() => void handleExport()}
                >
                  {exporting ? t.exportingBtn : t.exportBtn}
                </button>
                {selectedDetail.deliverables.length > 0 ? (
                  <div style={{ marginTop: "0.6rem" }}>
                    <h4>{t.deliverablesHeading}</h4>
                    <ul style={{ margin: 0, paddingInlineStart: "1.2rem", fontSize: "0.84rem" }}>
                      {selectedDetail.deliverables.map((d) => (
                        <li key={d.id}>
                          <a href={getDeliverableDownloadUrl(d.id)} target="_blank" rel="noreferrer">
                            {d.format.toUpperCase()}: {d.filename}
                          </a>{" "}
                          (SHA-256: <code>{d.sha256?.slice(0, 12)}...</code>)
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
