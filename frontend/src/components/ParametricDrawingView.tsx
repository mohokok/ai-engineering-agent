import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  generateParametricDrawing,
  getClinicPresetModel,
  listProjectParametricDrawings,
  listProjects,
  suggestParametricModel,
} from "../api";
import type {
  Lang,
  PaperSizeChoice,
  ParametricDrawingDetailOut,
  ParametricPlanModel,
  ProjectClassification,
  ProjectSummary,
} from "../types";

const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const SCALES = [50, 100, 150, 200];
const PAPER_SIZES: PaperSizeChoice[] = ["A3", "A4", "A2", "A1"];

interface CopyText {
  heading: string;
  subtitle: string;
  projectLabel: string;
  drawingNoLabel: string;
  titleLabel: string;
  scaleLabel: string;
  paperSizeLabel: string;
  classificationLabel: string;
  notesLabel: string;
  loadClinicBtn: string;
  loadingClinicBtn: string;
  aiDraftHeading: string;
  aiBriefLabel: string;
  aiBriefPlaceholder: string;
  aiSuggestBtn: string;
  aiSuggestingBtn: string;
  aiConfirmLabel: string;
  aiUnconfirmedWarn: string;
  modelJsonLabel: string;
  generateBtn: string;
  generatingBtn: string;
  savedDrawingsHeading: string;
  noDrawings: string;
  roundTripHeading: string;
  roundTripPass: string;
  roundTripWarn: string;
  roomsHeading: string;
  doorSchedHeading: string;
  windowSchedHeading: string;
  downloadsHeading: string;
  downloadBtn: string;
  totalAreaLabel: string;
  colRoomId: string;
  colNameAr: string;
  colNameEn: string;
  colArea: string;
  colPerim: string;
  colFloor: string;
  colWall: string;
  colMark: string;
  colDims: string;
  colSwing: string;
  colQty: string;
  colSpec: string;
  colIds: string;
}

const COPY: Record<Lang, CopyText> = {
  ar: {
    heading: "الرسم الهندسي البارامتري (DXF + PDF بمقياس حقيقي)",
    subtitle:
      "نموذج JSON بالمليمترات ($INSUNITS=4) ← توليد مخطط AutoCAD مع خطوط عربية TrueType (Tahoma) + PDF فيكتوري بمقياس رسم دقيق وجداول أبواب ونوافذ وتشطيبات وفحص عكسي Step 07 بـ 0 توكن ذكاء اصطناعي.",
    projectLabel: "المشروع",
    drawingNoLabel: "رقم اللوحة",
    titleLabel: "عنوان اللوحة",
    scaleLabel: "مقياس الرسم",
    paperSizeLabel: "حجم الورق",
    classificationLabel: "التصنيف",
    notesLabel: "ملاحظات هندسية",
    loadClinicBtn: "تحميل نموذج العيادة التجريبي (5 غرف / 80 م²)",
    loadingClinicBtn: "جاري تحميل النموذج...",
    aiDraftHeading: "مساعدة الذكاء الاصطناعي الاختيارية (تتطلب تأكيد المالك قبل الرسم)",
    aiBriefLabel: "وصف التصميم المطلوب لاقتراح نموذج JSON أولي",
    aiBriefPlaceholder: "مثال: عيادة طبية صغيرة 5 فراغات بمساحة تقارب 80 متر مربع بالمليمتر...",
    aiSuggestBtn: "اقتراح نموذج JSON بالذكاء الاصطناعي",
    aiSuggestingBtn: "جاري اقتراح النموذج...",
    aiConfirmLabel:
      "أؤكد مراجعتي للأبعاد والإحداثيات المقترحة من الذكاء الاصطناعي والموافقة على توليد المخطط",
    aiUnconfirmedWarn:
      "المساحات تُحسب بالكود فقط (Shoelace). يجب وضع علامة تأكيد المالك قبل توليد اللوحة.",
    modelJsonLabel: "نموذج الغرف والجدران والأبواب والنوافذ (JSON بالمليمتر mm)",
    generateBtn: "توليد لوحة DXF + PDF بمقياس حقيقي (0 توكن)",
    generatingBtn: "جاري التوليد والفحص العكسي...",
    savedDrawingsHeading: "اللوحات المولَّدة في 05_Design_Drawings",
    noDrawings: "لا توجد لوحات بارامترية لهذا المشروع بعد.",
    roundTripHeading: "فحص المطابقة العكسي (Step 07 DXF Read-Back)",
    roundTripPass: "ناجح — $INSUNITS=4 (mm)، خطوط عربية TrueType، والمساحات والكتل متطابقة",
    roundTripWarn: "تحذير — راجع الفروقات المسجلة أدناه",
    roomsHeading: "مساحات الغرف وجدول التشطيبات (محسوبة بالكود هندسياً)",
    doorSchedHeading: "جدول الأبواب (مطابق للنموذج)",
    windowSchedHeading: "جدول النوافذ (مطابق للنموذج)",
    downloadsHeading: "ملفات التسليم المحفوظة (05_Design_Drawings)",
    downloadBtn: "تحميل",
    totalAreaLabel: "إجمالي المساحة الصافية المحسوبة",
    colRoomId: "الرمز",
    colNameAr: "الاسم العربي",
    colNameEn: "الاسم الإنجليزي",
    colArea: "المساحة (م²)",
    colPerim: "المحيط (م)",
    colFloor: "الأرضيات",
    colWall: "الجدران",
    colMark: "النموذج",
    colDims: "الأبعاد (مم)",
    colSwing: "الفتح",
    colQty: "العدد",
    colSpec: "المواصفة",
    colIds: "العناصر",
  },
  en: {
    heading: "Parametric CAD Engine (mm DXF + True-Scale PDF)",
    subtitle:
      "Millimetre JSON floor-plan model ($INSUNITS=4) -> AutoCAD DXF with Arabic TrueType (Tahoma, zero SHX) + exact-scale vector PDF, model-matched Door/Window/Finishes schedules, and Step 07 round-trip verification at 0 AI tokens.",
    projectLabel: "Project",
    drawingNoLabel: "Drawing No",
    titleLabel: "Drawing Title",
    scaleLabel: "Scale",
    paperSizeLabel: "Sheet Size",
    classificationLabel: "Classification",
    notesLabel: "Engineering Notes",
    loadClinicBtn: "Load Synthetic Clinic Preset (5 Rooms / 80 m2)",
    loadingClinicBtn: "Loading preset...",
    aiDraftHeading: "Optional AI JSON Draft (Requires Owner Confirmation Before Drawing)",
    aiBriefLabel: "Design brief for optional Gemini draft model",
    aiBriefPlaceholder: "e.g., 5-room outpatient clinic floor plan ~80 m2 in mm...",
    aiSuggestBtn: "Suggest JSON Model (Gemini)",
    aiSuggestingBtn: "Drafting model...",
    aiConfirmLabel:
      "I confirm I reviewed the AI-suggested coordinates & dimensions and approve CAD/PDF generation",
    aiUnconfirmedWarn:
      "Room areas are computed strictly in code (Shoelace). Owner confirmation is required for AI-suggested drafts.",
    modelJsonLabel: "Parametric Room / Wall / Door / Window Model (JSON in mm)",
    generateBtn: "Generate DXF + True-Scale PDF (0 AI Tokens)",
    generatingBtn: "Generating & Verifying...",
    savedDrawingsHeading: "Generated Drawings in 05_Design_Drawings",
    noDrawings: "No parametric drawings generated for this project yet.",
    roundTripHeading: "Automatic Step 07 DXF Round-Trip Audit",
    roundTripPass: "PASS — $INSUNITS=4 (mm), Arabic TrueType styles, exact rooms & blocks verified",
    roundTripWarn: "WARNING — review recorded discrepancies below",
    roomsHeading: "Code-Computed Room Areas & Finishes Schedule",
    doorSchedHeading: "Door Schedule (Model-Matched)",
    windowSchedHeading: "Window Schedule (Model-Matched)",
    downloadsHeading: "Saved Deliverables (05_Design_Drawings)",
    downloadBtn: "Download",
    totalAreaLabel: "Total Computed Net Room Area",
    colRoomId: "Room ID",
    colNameAr: "Arabic Name",
    colNameEn: "English Name",
    colArea: "Area (m²)",
    colPerim: "Perim (m)",
    colFloor: "Floor Finish",
    colWall: "Wall Finish",
    colMark: "Mark",
    colDims: "W x H (mm)",
    colSwing: "Swing / Sill",
    colQty: "Qty",
    colSpec: "Specification",
    colIds: "Element IDs",
  },
};

export function ParametricDrawingView({
  lang,
  initialDrawing = null,
}: {
  lang: Lang;
  initialDrawing?: ParametricDrawingDetailOut | null;
}) {
  const copy = COPY[lang];

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [drawings, setDrawings] = useState<ParametricDrawingDetailOut[]>(initialDrawing ? [initialDrawing] : []);
  const [activeDrawing, setActiveDrawing] = useState<ParametricDrawingDetailOut | null>(initialDrawing);

  const [drawingNo, setDrawingNo] = useState("A-101");
  const [title, setTitle] = useState("مخطط الدور الأرضي لعيادة طبية / Clinic Ground Floor Plan");
  const [scaleDenom, setScaleDenom] = useState<number>(100);
  const [paperSize, setPaperSize] = useState<PaperSizeChoice>("A3");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [notes, setNotes] = useState(
    "All dimensions in millimetres (mm). Do not scale directly from unverified prints; verify structural grids on site."
  );

  const [modelJsonText, setModelJsonText] = useState<string>("");
  const [aiBrief, setAiBrief] = useState<string>("");
  const [aiSuggested, setAiSuggested] = useState(false);
  const [ownerConfirmedModel, setOwnerConfirmedModel] = useState(true);
  const [aiMessage, setAiMessage] = useState<string | null>(null);

  const [loadingPreset, setLoadingPreset] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPreset = useCallback(async () => {
    setLoadingPreset(true);
    setError(null);
    try {
      const preset: ParametricPlanModel = await getClinicPresetModel();
      setModelJsonText(JSON.stringify(preset, null, 2));
      setAiSuggested(false);
      setOwnerConfirmedModel(true);
      setAiMessage(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingPreset(false);
    }
  }, []);

  const refreshDrawings = useCallback(async (pid: string) => {
    if (!pid) {
      setDrawings([]);
      setActiveDrawing(null);
      return;
    }
    try {
      const res = await listProjectParametricDrawings(pid);
      setDrawings(res.drawings);
      if (res.drawings.length > 0) {
        setActiveDrawing((prev) => res.drawings.find((d) => d.id === prev?.id) ?? res.drawings[0]);
      } else {
        setActiveDrawing(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const res = await listProjects();
        setProjects(res.projects);
        if (res.projects.length > 0) {
          setProjectId((prev) => prev || res.projects[0].id);
          setClassification(res.projects[0].classification as ProjectClassification);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
    void loadPreset();
  }, [loadPreset]);

  useEffect(() => {
    void refreshDrawings(projectId);
  }, [projectId, refreshDrawings]);

  async function handleSuggestModel() {
    if (!projectId || !aiBrief.trim()) return;
    setSuggesting(true);
    setError(null);
    setAiMessage(null);
    try {
      const res = await suggestParametricModel(projectId, { brief: aiBrief.trim(), complexity: "fast" });
      setModelJsonText(JSON.stringify(res.plan_model, null, 2));
      setAiSuggested(true);
      setOwnerConfirmedModel(false);
      setAiMessage(`${res.message} (Tokens: ${res.tokens_used})`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSuggesting(false);
    }
  }

  async function handleGenerateDrawing(e: FormEvent) {
    e.preventDefault();
    if (!projectId) return;
    if (aiSuggested && !ownerConfirmedModel) {
      setError(copy.aiUnconfirmedWarn);
      return;
    }

    let parsedModel: ParametricPlanModel;
    try {
      parsedModel = JSON.parse(modelJsonText) as ParametricPlanModel;
    } catch (err) {
      setError(`Invalid plan JSON: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }

    setGenerating(true);
    setError(null);
    try {
      const created = await generateParametricDrawing(projectId, {
        drawing_no: drawingNo.trim() || "A-101",
        title: title.trim() || "Parametric Plan",
        scale_denominator: scaleDenom,
        paper_size: paperSize,
        classification,
        notes: notes.trim() || null,
        ai_suggested: aiSuggested,
        owner_confirmed_model: ownerConfirmedModel,
        plan_model: parsedModel,
      });
      setActiveDrawing(created);
      await refreshDrawings(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      {error && (
        <div className="status-box status-err" role="alert">
          {error}
        </div>
      )}

      <section className="subpanel" aria-label={copy.heading}>
        <div className="panel-header">
          <div>
            <h2 className="panel-title">{copy.heading}</h2>
            <p className="muted-hint">{copy.subtitle}</p>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={loadingPreset}
            onClick={() => void loadPreset()}
          >
            {loadingPreset ? copy.loadingClinicBtn : copy.loadClinicBtn}
          </button>
        </div>

        <form onSubmit={(e) => void handleGenerateDrawing(e)} className="form-grid">
          <div className="field">
            <span>{copy.projectLabel}</span>
            <select
              value={projectId}
              onChange={(e) => {
                const pid = e.target.value;
                setProjectId(pid);
                const found = projects.find((p) => p.id === pid);
                if (found) setClassification(found.classification as ProjectClassification);
              }}
              required
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
            <span>{copy.drawingNoLabel}</span>
            <input
              type="text"
              dir="ltr"
              value={drawingNo}
              onChange={(e) => setDrawingNo(e.target.value)}
              required
            />
          </div>

          <div className="field">
            <span>{copy.scaleLabel}</span>
            <select value={scaleDenom} onChange={(e) => setScaleDenom(Number(e.target.value))}>
              {SCALES.map((s) => (
                <option key={s} value={s}>
                  1:{s}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>{copy.paperSizeLabel}</span>
            <select value={paperSize} onChange={(e) => setPaperSize(e.target.value as PaperSizeChoice)}>
              {PAPER_SIZES.map((ps) => (
                <option key={ps} value={ps}>
                  {ps}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>{copy.classificationLabel}</span>
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
          </div>

          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <span>{copy.titleLabel}</span>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>

          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <span>{copy.notesLabel}</span>
            <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <div
            className="field"
            style={{
              gridColumn: "1 / -1",
              border: "1px dashed #94a3b8",
              borderRadius: "8px",
              padding: "0.75rem",
            }}
          >
            <strong>{copy.aiDraftHeading}</strong>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
              <input
                type="text"
                style={{ flex: "1 1 260px" }}
                value={aiBrief}
                onChange={(e) => setAiBrief(e.target.value)}
                placeholder={copy.aiBriefPlaceholder}
                aria-label={copy.aiBriefLabel}
              />
              <button
                type="button"
                className="btn btn-secondary"
                disabled={suggesting || !projectId || !aiBrief.trim()}
                onClick={() => void handleSuggestModel()}
              >
                {suggesting ? copy.aiSuggestingBtn : copy.aiSuggestBtn}
              </button>
            </div>
            {aiMessage && (
              <div className="status-box status-ok" style={{ marginTop: "0.5rem" }}>
                {aiMessage}
              </div>
            )}
            {aiSuggested && (
              <label
                style={{
                  display: "inline-flex",
                  gap: "0.45rem",
                  alignItems: "center",
                  marginTop: "0.5rem",
                  fontWeight: 600,
                }}
              >
                <input
                  type="checkbox"
                  checked={ownerConfirmedModel}
                  onChange={(e) => setOwnerConfirmedModel(e.target.checked)}
                />
                <span>{copy.aiConfirmLabel}</span>
              </label>
            )}
          </div>

          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <span>{copy.modelJsonLabel}</span>
            <textarea
              dir="ltr"
              rows={12}
              style={{ fontFamily: "monospace", fontSize: "0.82rem" }}
              value={modelJsonText}
              onChange={(e) => setModelJsonText(e.target.value)}
              required
            />
          </div>

          <div style={{ gridColumn: "1 / -1", display: "flex", gap: "0.75rem", alignItems: "center" }}>
            <button
              type="submit"
              className="btn"
              disabled={generating || !projectId || (aiSuggested && !ownerConfirmedModel)}
            >
              {generating ? copy.generatingBtn : copy.generateBtn}
            </button>
          </div>
        </form>
      </section>

      <section className="subpanel" aria-label={copy.savedDrawingsHeading}>
        <div className="panel-header">
          <h3 className="panel-title">
            {copy.savedDrawingsHeading} ({drawings.length})
          </h3>
        </div>
        {drawings.length === 0 ? (
          <p className="muted-hint">{copy.noDrawings}</p>
        ) : (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {drawings.map((d) => (
              <button
                key={d.id}
                type="button"
                className={activeDrawing?.id === d.id ? "btn" : "btn btn-secondary"}
                onClick={() => setActiveDrawing(d)}
              >
                {d.drawing_no} · {d.revision} · {d.scale_label} ({d.total_area_m2.toFixed(2)} m²)
              </button>
            ))}
          </div>
        )}
      </section>

      {activeDrawing && (
        <section className="subpanel" aria-label={activeDrawing.drawing_no}>
          <div className="panel-header">
            <div>
              <h3 className="panel-title">
                {activeDrawing.drawing_no} — {activeDrawing.title} ({activeDrawing.revision})
              </h3>
              <p className="muted-hint">
                {copy.totalAreaLabel}: <strong>{activeDrawing.total_area_m2.toFixed(2)} m²</strong> ·{" "}
                {activeDrawing.scale_label} · {activeDrawing.paper_size} ·{" "}
                <span className="badge">{activeDrawing.classification}</span>
              </p>
            </div>
            <span className={`badge ${activeDrawing.round_trip_passed ? "badge-ok" : ""}`}>
              {activeDrawing.round_trip_passed ? copy.roundTripPass : copy.roundTripWarn}
            </span>
          </div>

          <div className="status-box" style={{ marginBottom: "1rem" }}>
            <strong>{copy.roundTripHeading}:</strong>{" "}
            <span dir="ltr">
              $INSUNITS={activeDrawing.round_trip_check.insunits_code} ({activeDrawing.round_trip_check.units}) |{" "}
              units_doubtful={String(activeDrawing.round_trip_check.units_doubtful)} |{" "}
              SHX={String(activeDrawing.round_trip_check.uses_shx_font)} |{" "}
              Rooms={activeDrawing.round_trip_check.extracted_area_contour_count}/
              {activeDrawing.round_trip_check.expected_room_count} |{" "}
              Area={activeDrawing.round_trip_check.extracted_total_area_m2.toFixed(2)}/
              {activeDrawing.round_trip_check.expected_total_area_m2.toFixed(2)} m² |{" "}
              Doors={activeDrawing.round_trip_check.extracted_doors_count}/
              {activeDrawing.round_trip_check.expected_doors_count} |{" "}
              Windows={activeDrawing.round_trip_check.extracted_windows_count}/
              {activeDrawing.round_trip_check.expected_windows_count}
            </span>
          </div>

          <h4>{copy.downloadsHeading}</h4>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1rem" }}>
            {activeDrawing.deliverables.map((deliv) => (
              <a
                key={deliv.id}
                className="btn"
                href={deliv.download_url}
                download={deliv.filename || undefined}
              >
                {copy.downloadBtn} {deliv.format.toUpperCase()} ({deliv.filename})
              </a>
            ))}
          </div>

          <h4>{copy.roomsHeading}</h4>
          <div className="table-wrap" style={{ marginBottom: "1rem" }}>
            <table className="files-table">
              <thead>
                <tr>
                  <th>{copy.colRoomId}</th>
                  <th>{copy.colNameAr}</th>
                  <th>{copy.colNameEn}</th>
                  <th>{copy.colArea}</th>
                  <th>{copy.colPerim}</th>
                  <th>{copy.colFloor}</th>
                  <th>{copy.colWall}</th>
                </tr>
              </thead>
              <tbody>
                {activeDrawing.rooms_computed.map((rm) => (
                  <tr key={rm.room_id}>
                    <td dir="ltr">
                      <code>{rm.room_id}</code>
                    </td>
                    <td dir="rtl">{rm.name_ar}</td>
                    <td dir="ltr">{rm.name_en}</td>
                    <td dir="ltr">
                      <strong>{rm.area_m2.toFixed(2)}</strong>
                    </td>
                    <td dir="ltr">{rm.perimeter_m.toFixed(2)}</td>
                    <td dir="ltr">{rm.floor_finish}</td>
                    <td dir="ltr">{rm.wall_finish}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
            <div>
              <h4>{copy.doorSchedHeading}</h4>
              <div className="table-wrap">
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>{copy.colMark}</th>
                      <th>{copy.colDims}</th>
                      <th>{copy.colSwing}</th>
                      <th>{copy.colQty}</th>
                      <th>{copy.colSpec}</th>
                      <th>{copy.colIds}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeDrawing.door_schedule.map((d) => (
                      <tr key={d.mark}>
                        <td dir="ltr">
                          <strong>{d.mark}</strong>
                        </td>
                        <td dir="ltr">
                          {d.width_mm} x {d.height_mm}
                        </td>
                        <td dir="ltr">{d.swing}</td>
                        <td dir="ltr">
                          <strong>{d.count}</strong>
                        </td>
                        <td dir="ltr">{d.material}</td>
                        <td dir="ltr">{d.door_ids.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <h4>{copy.windowSchedHeading}</h4>
              <div className="table-wrap">
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>{copy.colMark}</th>
                      <th>{copy.colDims}</th>
                      <th>{copy.colSwing}</th>
                      <th>{copy.colQty}</th>
                      <th>{copy.colSpec}</th>
                      <th>{copy.colIds}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeDrawing.window_schedule.map((w) => (
                      <tr key={w.mark}>
                        <td dir="ltr">
                          <strong>{w.mark}</strong>
                        </td>
                        <td dir="ltr">
                          {w.width_mm} x {w.height_mm}
                        </td>
                        <td dir="ltr">Sill {w.sill_mm} mm</td>
                        <td dir="ltr">
                          <strong>{w.count}</strong>
                        </td>
                        <td dir="ltr">{w.glazing}</td>
                        <td dir="ltr">{w.window_ids.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
