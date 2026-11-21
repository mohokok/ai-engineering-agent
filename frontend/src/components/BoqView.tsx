import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  addBoqItem,
  createBoqSheet,
  deleteBoqItem,
  exportBoqDeliverables,
  getBoqDetail,
  importExtractionsIntoBoq,
  listProjectBoqSheets,
  listProjectFiles,
  listProjects,
  rerunBoqChecks,
  updateBoqItem,
  updateBoqSheet,
} from "../api";
import type {
  BoqDetailOut,
  BoqItemOut,
  BoqRateSourceKind,
  BoqSheetSummaryOut,
  Lang,
  ProjectClassification,
  ProjectFileOut,
  ProjectSummary,
} from "../types";

const CLASSIFICATIONS: ProjectClassification[] = [
  "Preliminary",
  "Conceptual",
  "For Review",
  "For Coordination",
  "For Approval",
];

const CURRENCY_CHOICES = ["LYD", "USD", "EUR", "GBP", "SAR", "AED", "TND", "EGP"];

interface CopyText {
  createHeading: string;
  projectLabel: string;
  currencyLabel: string;
  customCurrencyLabel: string;
  classificationLabel: string;
  titleLabel: string;
  titlePlaceholder: string;
  filesLabel: string;
  noFilesHint: string;
  buildBtn: string;
  buildingBtn: string;
  savedBoqsHeading: string;
  noBoqs: string;
  itemsHeading: string;
  checksHeading: string;
  flaggedHeading: string;
  exportsHeading: string;
  importBtn: string;
  reimportReplaceBtn: string;
  checksBtn: string;
  exportBtn: string;
  exportingBtn: string;
  rateEditorHeading: string;
  rateLabel: string;
  rateSourceKindLabel: string;
  ownerInputOpt: string;
  datedResearchOpt: string;
  rateSourceRefLabel: string;
  rateSourceDateLabel: string;
  saveRateBtn: string;
  clearRateBtn: string;
  cancelBtn: string;
  addManualHeading: string;
  itemNoLabel: string;
  descLabel: string;
  unitLabel: string;
  qtyLabel: string;
  techRefLabel: string;
  dwgRefLabel: string;
  remarksLabel: string;
  addManualBtn: string;
  verifiedSubLabel: string;
  needsCheckSubLabel: string;
  grandTotalLabel: string;
  rateBlockedHint: string;
  colNo: string;
  colDesc: string;
  colUnit: string;
  colQty: string;
  colRate: string;
  colTotal: string;
  colTechRef: string;
  colDwgRef: string;
  colRateSrc: string;
  colVerif: string;
  colRemarks: string;
  colActions: string;
  setRateAction: string;
  deleteAction: string;
  noIssues: string;
  noFlagged: string;
  noExports: string;
  downloadLabel: string;
}

const COPY: Record<Lang, CopyText> = {
  ar: {
    createHeading: "إنشاء جدول الكميات والحصر الهندسي الحتمي (0 توكن)",
    projectLabel: "المشروع",
    currencyLabel: "العملة الافتراضية",
    customCurrencyLabel: "رمز عملة مخصص (3 أحرف ISO)",
    classificationLabel: "التصنيف الاستشاري",
    titleLabel: "عنوان جدول الكميات",
    titlePlaceholder: "مثال: مقايسة الأعمال المعمارية والإنشائية — Rev 01",
    filesLabel: "ملفات المشروع (DXF / DWG / IFC للحصر، أو XLSX / PDF للاستيراد)",
    noFilesHint: "لم تُرفع ملفات بعد؛ يمكنك إنشاء جدول يدوي أو رفع الملفات من تبويب المشاريع.",
    buildBtn: "بناء جدول الكميات (DXF / IFC / XLSX / PDF)",
    buildingBtn: "جاري البناء والحصر...",
    savedBoqsHeading: "جداول الكميات المحفوظة للمشروع",
    noBoqs: "لا توجد جداول كميات لهذا المشروع بعد.",
    itemsHeading: "بنود جدول الكميات والتحقق من الوحدات",
    checksHeading: "نتائج الفحص التلقائي (التكرار، النواقص، الوحدات، الحسابات)",
    flaggedHeading: "البنود المُعلّمة للمراجعة والتحقق البشري",
    exportsHeading: "ملفات التصدير النسخية في مجلد 06_BOQ (XLSX بصيغ حية + CSV)",
    importBtn: "استيراد/دمج من DXF/IFC/XLSX/PDF",
    reimportReplaceBtn: "تحديث البنود المستخرجة (بعد confirm-unit)",
    checksBtn: "إعادة تشغيل الفحوصات",
    exportBtn: "تصدير XLSX (معادلات حية) + CSV إلى 06_BOQ",
    exportingBtn: "جاري التصدير...",
    rateEditorHeading: "تسعير البند مع إلزامية توثيق المصدر",
    rateLabel: "سعر الوحدة",
    rateSourceKindLabel: "مصدر التسعير",
    ownerInputOpt: "إدخال مباشر من المالك (owner_input)",
    datedResearchOpt: "بحث تقني مؤرّخ ومُراجع (dated_research)",
    rateSourceRefLabel: "المرجع / اسم المصدر / الرابط",
    rateSourceDateLabel: "تاريخ المصدر",
    saveRateBtn: "حفظ السعر وتحديث الإجمالي",
    clearRateBtn: "مسح السعر",
    cancelBtn: "إلغاء",
    addManualHeading: "إضافة بند يدوي (Manual) — التسعير محجوب بلا مصدر موثّق",
    itemNoLabel: "رقم البند",
    descLabel: "الوصف",
    unitLabel: "الوحدة",
    qtyLabel: "الكمية",
    techRefLabel: "المرجع الفني",
    dwgRefLabel: "مرجع المخطط",
    remarksLabel: "ملاحظات",
    addManualBtn: "إضافة البند",
    verifiedSubLabel: "مجموع البنود المتحقّق منها",
    needsCheckSubLabel: "مجموع بنود Extracted-Needs-Check",
    grandTotalLabel: "الإجمالي الكلي للمقايسة",
    rateBlockedHint: "ملاحظة: يُمنع قبول أي سعر وحدة ما لم يُربط بإدخال المالك أو بحث تقني مؤرّخ.",
    colNo: "البند",
    colDesc: "الوصف",
    colUnit: "الوحدة",
    colQty: "الكمية",
    colRate: "السعر",
    colTotal: "الإجمالي",
    colTechRef: "المرجع الفني",
    colDwgRef: "مرجع المخطط",
    colRateSrc: "مصدر السعر",
    colVerif: "حالة التحقق",
    colRemarks: "ملاحظات",
    colActions: "إجراء",
    setRateAction: "تسعير موثّق",
    deleteAction: "حذف",
    noIssues: "لم تُرصد أخطاء تكرار أو نواقص أو تناقض وحدات أو أخطاء حسابية.",
    noFlagged: "لا توجد بنود مُعلّمة للمراجعة البشرية حالياً.",
    noExports: "لم يتم تصدير XLSX / CSV لهذا الجدول بعد.",
    downloadLabel: "تنزيل",
  },
  en: {
    createHeading: "Build Deterministic Bill of Quantities (0 AI Tokens)",
    projectLabel: "Project",
    currencyLabel: "Currency",
    customCurrencyLabel: "Custom Currency (3-letter ISO)",
    classificationLabel: "Classification Lock",
    titleLabel: "BOQ Title (optional)",
    titlePlaceholder: "e.g., Main Clinic Architectural & Structural BOQ",
    filesLabel: "Project Files (DXF/DWG/IFC for takeoff, XLSX/PDF for BOQ import)",
    noFilesHint: "No project files yet; you can start a manual BOQ or upload files in Projects & Files.",
    buildBtn: "Build BOQ (DXF / IFC / XLSX / PDF)",
    buildingBtn: "Building deterministic BOQ...",
    savedBoqsHeading: "Project BOQ Sheets",
    noBoqs: "No BOQ sheets saved for this project yet.",
    itemsHeading: "BOQ Line Items & Verification Tags",
    checksHeading: "Deterministic Audit Checks (Duplicates, Missing Items, Units, Arithmetic)",
    flaggedHeading: "Items Flagged for Human Verification",
    exportsHeading: "Versioned 06_BOQ Exports (Live-Formula XLSX + CSV)",
    importBtn: "Merge From DXF/IFC/XLSX/PDF",
    reimportReplaceBtn: "Refresh Extracted Rows (After confirm-unit)",
    checksBtn: "Run BOQ Checks",
    exportBtn: "Export XLSX (Live Formulas) + CSV to 06_BOQ",
    exportingBtn: "Exporting 06_BOQ files...",
    rateEditorHeading: "Assign Sourced Unit Rate (Unsourced Rates Strictly Blocked)",
    rateLabel: "Unit Rate",
    rateSourceKindLabel: "Rate Source Kind",
    ownerInputOpt: "Owner Input (owner_input)",
    datedResearchOpt: "Dated Reviewed Research (dated_research)",
    rateSourceRefLabel: "Rate Source Citation / URL / Quote Ref",
    rateSourceDateLabel: "Source Date (YYYY-MM-DD)",
    saveRateBtn: "Save Sourced Rate",
    clearRateBtn: "Clear Rate",
    cancelBtn: "Cancel",
    addManualHeading: "Add Manual BOQ Item",
    itemNoLabel: "Item No.",
    descLabel: "Description",
    unitLabel: "Unit",
    qtyLabel: "Quantity",
    techRefLabel: "Technical Ref",
    dwgRefLabel: "Drawing Ref",
    remarksLabel: "Remarks",
    addManualBtn: "Add BOQ Item",
    verifiedSubLabel: "Extracted-Verified Subtotal",
    needsCheckSubLabel: "Extracted-Needs-Check Subtotal",
    grandTotalLabel: "Grand Total",
    rateBlockedHint: "Policy: Unsourced or undated research unit rates and unconfirmed CAD-unit pricing are blocked.",
    colNo: "Item No.",
    colDesc: "Description",
    colUnit: "Unit",
    colQty: "Quantity",
    colRate: "Unit Rate",
    colTotal: "Total",
    colTechRef: "Technical Ref",
    colDwgRef: "Drawing Ref",
    colRateSrc: "Rate Source / Date",
    colVerif: "Verification Status",
    colRemarks: "Remarks",
    colActions: "Actions",
    setRateAction: "Set Sourced Rate",
    deleteAction: "Delete",
    noIssues: "No duplicate, missing-item, unit-consistency, or arithmetic issues detected.",
    noFlagged: "No items currently flagged for human verification.",
    noExports: "No versioned XLSX/CSV deliverables exported yet.",
    downloadLabel: "Download",
  },
};

export interface BoqViewProps {
  lang: Lang;
  initialProjects?: ProjectSummary[];
  initialBoq?: BoqDetailOut | null;
}

export function BoqView({
  lang,
  initialProjects = [],
  initialBoq = null,
}: BoqViewProps) {
  const copy = COPY[lang];
  const [projects, setProjects] = useState<ProjectSummary[]>(initialProjects);
  const [projectId, setProjectId] = useState<string>(initialProjects[0]?.id || "");
  const [projectFiles, setProjectFiles] = useState<ProjectFileOut[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);

  const [currency, setCurrency] = useState<string>("LYD");
  const [classification, setClassification] = useState<ProjectClassification>("Preliminary");
  const [title, setTitle] = useState<string>("");

  const [boqList, setBoqList] = useState<BoqSheetSummaryOut[]>([]);
  const [activeBoq, setActiveBoq] = useState<BoqDetailOut | null>(initialBoq);

  const [editingItem, setEditingItem] = useState<BoqItemOut | null>(null);
  const [rateValue, setRateValue] = useState<string>("");
  const [rateKind, setRateKind] = useState<BoqRateSourceKind>("owner_input");
  const [rateRef, setRateRef] = useState<string>("");
  const [rateDate, setRateDate] = useState<string>(new Date().toISOString().slice(0, 10));

  const [mItemNo, setMItemNo] = useState<string>("");
  const [mDesc, setMDesc] = useState<string>("");
  const [mUnit, setMUnit] = useState<string>("m2");
  const [mQty, setMQty] = useState<string>("0");
  const [mRate, setMRate] = useState<string>("");
  const [mRateKind, setMRateKind] = useState<BoqRateSourceKind>("owner_input");
  const [mRateRef, setMRateRef] = useState<string>("");
  const [mRateDate, setMRateDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [mTechRef, setMTechRef] = useState<string>("");
  const [mDwgRef, setMDwgRef] = useState<string>("");
  const [mRemarks, setMRemarks] = useState<string>("");

  const [building, setBuilding] = useState<boolean>(false);
  const [exporting, setExporting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadContext = useCallback(async (pid: string) => {
    if (!pid) {
      setProjectFiles([]);
      setBoqList([]);
      return;
    }
    try {
      const [filesRes, sheetsRes] = await Promise.all([
        listProjectFiles(pid),
        listProjectBoqSheets(pid),
      ]);
      setProjectFiles(filesRes.files);
      setBoqList(sheetsRes.sheets);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void listProjects()
      .then((res) => {
        setProjects(res.projects);
        setProjectId((prev) => prev || res.projects[0]?.id || "");
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setSelectedFileIds([]);
    if (projectId) {
      void loadContext(projectId);
    }
  }, [projectId, loadContext]);

  async function handleCreateBoq(event: FormEvent) {
    event.preventDefault();
    if (!projectId) {
      return;
    }
    setBuilding(true);
    setError(null);
    try {
      const created = await createBoqSheet(projectId, {
        title: title.trim() || null,
        language: lang,
        currency: currency.trim().toUpperCase() || "LYD",
        classification,
        file_ids: selectedFileIds,
      });
      setActiveBoq(created);
      setTitle("");
      await loadContext(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBuilding(false);
    }
  }

  async function handleCurrencyChange(nextCurrency: string) {
    if (!activeBoq) {
      return;
    }
    setError(null);
    try {
      const updated = await updateBoqSheet(activeBoq.id, { currency: nextCurrency });
      setActiveBoq(updated);
      await loadContext(activeBoq.project_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleImport(replaceExtracted: boolean) {
    if (!activeBoq) {
      return;
    }
    setError(null);
    try {
      const updated = await importExtractionsIntoBoq(activeBoq.id, {
        file_ids: selectedFileIds,
        replace_extracted: replaceExtracted,
      });
      setActiveBoq(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRerunChecks() {
    if (!activeBoq) {
      return;
    }
    setError(null);
    try {
      const updated = await rerunBoqChecks(activeBoq.id);
      setActiveBoq(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleExport() {
    if (!activeBoq) {
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const res = await exportBoqDeliverables(activeBoq.id, { language: lang });
      setActiveBoq(res.boq);
      await loadContext(activeBoq.project_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  }

  function openRateEditor(item: BoqItemOut) {
    setEditingItem(item);
    setRateValue(item.unit_rate != null ? String(item.unit_rate) : "");
    setRateKind(item.rate_source_kind || "owner_input");
    setRateRef(item.rate_source_ref || "");
    setRateDate(item.rate_source_date || new Date().toISOString().slice(0, 10));
  }

  async function handleSaveRate(event: FormEvent) {
    event.preventDefault();
    if (!activeBoq || !editingItem) {
      return;
    }
    setError(null);
    try {
      const parsed = Number(rateValue);
      const updated = await updateBoqItem(activeBoq.id, editingItem.id, {
        unit_rate: Number.isFinite(parsed) ? parsed : undefined,
        rate_source_kind: rateKind,
        rate_source_ref: rateRef.trim() || undefined,
        rate_source_date: rateDate.trim() || undefined,
      });
      setActiveBoq(updated);
      setEditingItem(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleClearRate() {
    if (!activeBoq || !editingItem) {
      return;
    }
    setError(null);
    try {
      const updated = await updateBoqItem(activeBoq.id, editingItem.id, { clear_rate: true });
      setActiveBoq(updated);
      setEditingItem(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleAddManualItem(event: FormEvent) {
    event.preventDefault();
    if (!activeBoq || !mDesc.trim()) {
      return;
    }
    setError(null);
    const hasRate = mRate.trim() !== "";
    try {
      const updated = await addBoqItem(activeBoq.id, {
        item_no: mItemNo.trim(),
        description: mDesc.trim(),
        unit: mUnit.trim(),
        quantity: Number(mQty) || 0,
        unit_rate: hasRate ? Number(mRate) : null,
        rate_source_kind: hasRate ? mRateKind : null,
        rate_source_ref: hasRate ? mRateRef.trim() || null : null,
        rate_source_date: hasRate ? mRateDate.trim() || null : null,
        technical_reference: mTechRef.trim() || null,
        drawing_reference: mDwgRef.trim() || null,
        remarks: mRemarks.trim() || null,
        verification_status: "Manual",
      });
      setActiveBoq(updated);
      setMItemNo("");
      setMDesc("");
      setMQty("0");
      setMRate("");
      setMRateRef("");
      setMTechRef("");
      setMDwgRef("");
      setMRemarks("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      {error && (
        <div className="status-box status-err" role="alert">
          {error}
        </div>
      )}

      <section className="subpanel" aria-label={copy.createHeading}>
        <div className="panel-header">
          <h3 className="panel-title">{copy.createHeading}</h3>
          <span className="badge badge-ok">{currency}</span>
        </div>

        <form onSubmit={(e) => void handleCreateBoq(e)} className="form-grid">
          <div className="field">
            <span>{copy.projectLabel}</span>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
              <option value="">--</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  [{p.code}] {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>{copy.currencyLabel}</span>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
              {CURRENCY_CHOICES.map((c) => (
                <option key={c} value={c}>
                  {c}
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
              {CLASSIFICATIONS.map((cls) => (
                <option key={cls} value={cls}>
                  {cls}
                </option>
              ))}
            </select>
          </div>

          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <span>{copy.titleLabel}</span>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={copy.titlePlaceholder}
            />
          </div>

          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <span>{copy.filesLabel}</span>
            {projectFiles.length === 0 ? (
              <p className="muted-hint">{copy.noFilesHint}</p>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                {projectFiles.map((f) => {
                  const checked = selectedFileIds.includes(f.id);
                  return (
                    <label
                      key={f.id}
                      style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setSelectedFileIds((prev) =>
                            prev.includes(f.id) ? prev.filter((id) => id !== f.id) : [...prev, f.id]
                          )
                        }
                      />
                      <span dir="auto">{f.original_filename}</span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>

          <div style={{ gridColumn: "1 / -1" }}>
            <button type="submit" className="btn" disabled={building || !projectId}>
              {building ? copy.buildingBtn : copy.buildBtn}
            </button>
          </div>
        </form>
      </section>

      <section className="subpanel" aria-label={copy.savedBoqsHeading}>
        <h3 className="panel-title">
          {copy.savedBoqsHeading} ({boqList.length})
        </h3>
        {boqList.length === 0 ? (
          <p className="muted-hint">{copy.noBoqs}</p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            {boqList.map((b) => (
              <button
                key={b.id}
                type="button"
                className={`btn btn-compact ${activeBoq?.id === b.id ? "" : "btn-secondary"}`}
                onClick={() => void getBoqDetail(b.id).then(setActiveBoq)}
              >
                {b.revision} — {b.currency} ({b.items_count})
              </button>
            ))}
          </div>
        )}
      </section>

      {activeBoq && (
        <>
          <section className="subpanel" aria-label={copy.itemsHeading}>
            <div className="panel-header">
              <div>
                <h3 className="panel-title" dir="auto">
                  {activeBoq.title} — {activeBoq.revision}
                </h3>
                <div className="muted-hint">
                  <span className="badge">{activeBoq.classification}</span> · {copy.currencyLabel}:{" "}
                  <strong>{activeBoq.currency}</strong>
                </div>
              </div>
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center" }}>
                <select
                  aria-label={copy.currencyLabel}
                  value={activeBoq.currency}
                  onChange={(e) => void handleCurrencyChange(e.target.value)}
                >
                  {CURRENCY_CHOICES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => void handleImport(false)}
                >
                  {copy.importBtn}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => void handleImport(true)}
                >
                  {copy.reimportReplaceBtn}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => void handleRerunChecks()}
                >
                  {copy.checksBtn}
                </button>
                <button
                  type="button"
                  className="btn btn-compact"
                  disabled={exporting}
                  onClick={() => void handleExport()}
                >
                  {exporting ? copy.exportingBtn : copy.exportBtn}
                </button>
              </div>
            </div>

            <div className="status-box notice-box" style={{ marginBottom: "0.75rem" }}>
              <div>
                <strong>{copy.verifiedSubLabel}:</strong>{" "}
                {activeBoq.checks.verified_priced_subtotal.toLocaleString()} {activeBoq.currency} ·{" "}
                <strong>{copy.needsCheckSubLabel}:</strong>{" "}
                {activeBoq.checks.needs_check_priced_subtotal.toLocaleString()} {activeBoq.currency} ·{" "}
                <strong>{copy.grandTotalLabel}:</strong>{" "}
                {activeBoq.checks.grand_total.toLocaleString()} {activeBoq.currency}
              </div>
              <div className="muted-hint" style={{ marginTop: "0.25rem" }}>
                {copy.rateBlockedHint}
              </div>
              {Boolean(
                (activeBoq.source_metadata?.omission_summary as { omitted_count?: number } | undefined)
                  ?.omitted_count
              ) && (
                <div className="muted-hint" style={{ marginTop: "0.25rem", fontWeight: 600 }}>
                  {String(
                    (activeBoq.source_metadata?.omission_summary as { note?: string } | undefined)?.note || ""
                  )}
                </div>
              )}
            </div>

            {editingItem && (
              <form
                onSubmit={(e) => void handleSaveRate(e)}
                className="subpanel"
                style={{ marginBottom: "0.9rem", border: "1px solid #cbd5e1" }}
              >
                <h4 className="folders-title">
                  {copy.rateEditorHeading}: [{editingItem.item_no}] {editingItem.description}
                </h4>
                <div className="form-grid">
                  <label className="field">
                    <span>
                      {copy.rateLabel} ({activeBoq.currency})
                    </span>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={rateValue}
                      onChange={(e) => setRateValue(e.target.value)}
                      required
                    />
                  </label>
                  <label className="field">
                    <span>{copy.rateSourceKindLabel}</span>
                    <select
                      value={rateKind}
                      onChange={(e) => setRateKind(e.target.value as BoqRateSourceKind)}
                    >
                      <option value="owner_input">{copy.ownerInputOpt}</option>
                      <option value="dated_research">{copy.datedResearchOpt}</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>{copy.rateSourceRefLabel}</span>
                    <input
                      type="text"
                      value={rateRef}
                      onChange={(e) => setRateRef(e.target.value)}
                      required
                    />
                  </label>
                  <label className="field">
                    <span>{copy.rateSourceDateLabel}</span>
                    <input
                      type="date"
                      value={rateDate}
                      onChange={(e) => setRateDate(e.target.value)}
                      required={rateKind === "dated_research"}
                    />
                  </label>
                </div>
                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
                  <button type="submit" className="btn btn-compact">
                    {copy.saveRateBtn}
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-compact"
                    onClick={() => void handleClearRate()}
                  >
                    {copy.clearRateBtn}
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-compact"
                    onClick={() => setEditingItem(null)}
                  >
                    {copy.cancelBtn}
                  </button>
                </div>
              </form>
            )}

            <div className="table-wrap">
              <table className="files-table">
                <thead>
                  <tr>
                    <th>{copy.colNo}</th>
                    <th>{copy.colDesc}</th>
                    <th>{copy.colUnit}</th>
                    <th>{copy.colQty}</th>
                    <th>
                      {copy.colRate} ({activeBoq.currency})
                    </th>
                    <th>
                      {copy.colTotal} ({activeBoq.currency})
                    </th>
                    <th>{copy.colTechRef}</th>
                    <th>{copy.colDwgRef}</th>
                    <th>{copy.colRateSrc}</th>
                    <th>{copy.colVerif}</th>
                    <th>{copy.colRemarks}</th>
                    <th>{copy.colActions}</th>
                  </tr>
                </thead>
                <tbody>
                  {activeBoq.items.map((it) => (
                    <tr key={it.id}>
                      <td dir="ltr">
                        <strong>{it.item_no}</strong>
                      </td>
                      <td dir="auto">{it.description}</td>
                      <td dir="ltr">{it.unit || "—"}</td>
                      <td dir="ltr">{it.quantity}</td>
                      <td dir="ltr">{it.unit_rate != null ? it.unit_rate : "—"}</td>
                      <td dir="ltr">{it.total != null ? it.total : "—"}</td>
                      <td dir="auto">{it.technical_reference || "—"}</td>
                      <td dir="auto">{it.drawing_reference || "—"}</td>
                      <td dir="auto">
                        {it.rate_source_kind
                          ? `${it.rate_source_kind}: ${it.rate_source_ref || ""} (${it.rate_source_date || ""})`
                          : "—"}
                      </td>
                      <td dir="ltr">
                        <span
                          className={`badge ${
                            it.verification_status === "Extracted-Verified"
                              ? "badge-ok"
                              : it.verification_status === "Extracted-Needs-Check"
                                ? "badge-warn"
                                : ""
                          }`}
                        >
                          {it.verification_status}
                        </span>
                      </td>
                      <td dir="auto">{it.remarks || "—"}</td>
                      <td>
                        <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="btn btn-secondary btn-compact"
                            onClick={() => openRateEditor(it)}
                          >
                            {copy.setRateAction}
                          </button>
                          {it.verification_status === "Extracted-Needs-Check" && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-compact"
                              onClick={() =>
                                void updateBoqItem(activeBoq.id, it.id, {
                                  verification_status: "Extracted-Verified",
                                }).then(setActiveBoq)
                              }
                            >
                              {lang === "ar" ? "تأكيد التحقق" : "Mark Verified"}
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-secondary btn-compact"
                            onClick={() =>
                              void deleteBoqItem(activeBoq.id, it.id).then(setActiveBoq)
                            }
                          >
                            {copy.deleteAction}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="subpanel" aria-label={copy.addManualHeading}>
            <h4 className="folders-title">{copy.addManualHeading}</h4>
            <form onSubmit={(e) => void handleAddManualItem(e)} className="form-grid">
              <label className="field">
                <span>{copy.itemNoLabel}</span>
                <input value={mItemNo} onChange={(e) => setMItemNo(e.target.value)} />
              </label>
              <label className="field">
                <span>{copy.descLabel}</span>
                <input value={mDesc} onChange={(e) => setMDesc(e.target.value)} required />
              </label>
              <label className="field">
                <span>{copy.unitLabel}</span>
                <input value={mUnit} onChange={(e) => setMUnit(e.target.value)} />
              </label>
              <label className="field">
                <span>{copy.qtyLabel}</span>
                <input
                  type="number"
                  step="0.0001"
                  min="0"
                  value={mQty}
                  onChange={(e) => setMQty(e.target.value)}
                  required
                />
              </label>
              <label className="field">
                <span>
                  {copy.rateLabel} ({activeBoq.currency})
                </span>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={mRate}
                  onChange={(e) => setMRate(e.target.value)}
                />
              </label>
              <label className="field">
                <span>{copy.rateSourceKindLabel}</span>
                <select
                  value={mRateKind}
                  onChange={(e) => setMRateKind(e.target.value as BoqRateSourceKind)}
                >
                  <option value="owner_input">{copy.ownerInputOpt}</option>
                  <option value="dated_research">{copy.datedResearchOpt}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.rateSourceRefLabel}</span>
                <input value={mRateRef} onChange={(e) => setMRateRef(e.target.value)} />
              </label>
              <label className="field">
                <span>{copy.rateSourceDateLabel}</span>
                <input
                  type="date"
                  value={mRateDate}
                  onChange={(e) => setMRateDate(e.target.value)}
                />
              </label>
              <label className="field">
                <span>{copy.techRefLabel}</span>
                <input value={mTechRef} onChange={(e) => setMTechRef(e.target.value)} />
              </label>
              <label className="field">
                <span>{copy.dwgRefLabel}</span>
                <input value={mDwgRef} onChange={(e) => setMDwgRef(e.target.value)} />
              </label>
              <label className="field">
                <span>{copy.remarksLabel}</span>
                <input value={mRemarks} onChange={(e) => setMRemarks(e.target.value)} />
              </label>
              <div style={{ gridColumn: "1 / -1" }}>
                <button type="submit" className="btn btn-compact">
                  {copy.addManualBtn}
                </button>
              </div>
            </form>
          </section>

          <section className="subpanel" aria-label={copy.checksHeading}>
            <h4 className="folders-title">
              {copy.checksHeading} ({activeBoq.checks.issues_count})
            </h4>
            {activeBoq.checks.issues.length === 0 ? (
              <p className="muted-hint">{copy.noIssues}</p>
            ) : (
              <div className="table-wrap" style={{ marginBottom: "0.75rem" }}>
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Type</th>
                      <th>Severity</th>
                      <th>{copy.colNo}</th>
                      <th>Message</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeBoq.checks.issues.map((iss) => (
                      <tr key={iss.issue_id}>
                        <td dir="ltr">{iss.issue_id}</td>
                        <td dir="ltr">{iss.check_type}</td>
                        <td>
                          <span
                            className={`badge ${
                              iss.severity === "high" ? "badge-warn" : ""
                            }`}
                          >
                            {iss.severity}
                          </span>
                        </td>
                        <td dir="ltr">{iss.item_no || "—"}</td>
                        <td dir="auto">{iss.message}</td>
                        <td dir="auto">{iss.recommended_action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <h4 className="folders-title">
              {copy.flaggedHeading} ({activeBoq.checks.flagged_items.length})
            </h4>
            {activeBoq.checks.flagged_items.length === 0 ? (
              <p className="muted-hint">{copy.noFlagged}</p>
            ) : (
              <ul className="outcome-list">
                {activeBoq.checks.flagged_items.map((flg) => (
                  <li key={flg.item_id} dir="auto">
                    <strong>[{flg.item_no}]</strong> {flg.description} ({flg.quantity}{" "}
                    {flg.unit || "—"}) —{" "}
                    <span className="badge badge-warn">{flg.verification_status}</span>:{" "}
                    {flg.reason}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="subpanel" aria-label={copy.exportsHeading}>
            <h4 className="folders-title">
              {copy.exportsHeading} ({activeBoq.deliverables.length})
            </h4>
            {activeBoq.deliverables.length === 0 ? (
              <p className="muted-hint">{copy.noExports}</p>
            ) : (
              <div className="table-wrap">
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>Folder</th>
                      <th>File</th>
                      <th>Format</th>
                      <th>SHA-256</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeBoq.deliverables.map((d) => (
                      <tr key={d.id}>
                        <td dir="ltr">
                          <code>{d.folder_name || "06_BOQ"}</code>
                        </td>
                        <td dir="ltr">
                          <code>{d.relative_path || d.filename}</code>
                        </td>
                        <td dir="ltr">{d.format.toUpperCase()}</td>
                        <td dir="ltr">
                          <code>{d.sha256 ? `${d.sha256.slice(0, 12)}...` : "—"}</code>
                        </td>
                        <td>
                          <a
                            className="btn btn-compact"
                            href={d.download_url}
                            download={d.filename || undefined}
                          >
                            {copy.downloadLabel} ({d.format.toUpperCase()})
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
