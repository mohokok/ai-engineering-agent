import { ChangeEvent, DragEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  confirmExtractionDrawingUnit,
  extractProjectFile,
  getExtractionCapabilities,
  getExtractionPageImageUrl,
  getFileDownloadUrl,
  getSupportedExtensions,
  listProjectFiles,
  summarizeDrawingVision,
  uploadProjectFiles,
} from "../api";
import type {
  CadUnitChoice,
  DrawingVisionSummaryOut,
  ExtractionCapabilitiesOut,
  FileExtractionDetailOut,
  Lang,
  ProjectFileOut,
  ProjectFilesUploadResponse,
  SupportedExtensionsResponse,
} from "../types";

interface FilesPanelCopy {
  heading: string;
  refreshBtn: string;
  loading: string;
  dropzoneTitle: string;
  dropzoneHint: string;
  chooseFilesBtn: string;
  uploadingBtn: string;
  supportedLabel: string;
  emptyList: string;
  colFile: string;
  colType: string;
  colSize: string;
  colHash: string;
  colUploaded: string;
  colVersion: string;
  colActions: string;
  readOnlyBadge: string;
  downloadBtn: string;
  extractBtn: string;
  extractingBtn: string;
  versionsBtn: string;
  hideVersionsBtn: string;
  versionsHeading: string;
  colVerNum: string;
  colVerPath: string;
  colVerHash: string;
  colVerNote: string;
  colVerDate: string;
  originalVersionTag: string;
  summaryPrefix: string;
  createdTag: string;
  newVersionTag: string;
  duplicateTag: string;
  errorPrefix: string;
  ocrLabel: string;
  odaLabel: string;
  matrixToggleLabel: string;
  extractionHeading: string;
  originalVerified: string;
  warningsLabel: string;
  renderedPagesLabel: string;
  visionBtn: string;
  visionLoadingBtn: string;
  inventoryHeading: string;
  rawJsonLabel: string;
  confirmUnitLabel: string;
  confirmUnitBtn: string;
  confirmingUnitBtn: string;
  unitsDoubtfulTitle: string;
}

const FILES_COPY: Record<Lang, FilesPanelCopy> = {
  ar: {
    heading: "ملفات المشروع وسجل الإصدارات",
    refreshBtn: "تحديث الملفات",
    loading: "جاري تحميل الملفات...",
    dropzoneTitle: "اسحب وأفلت ملفات المشروع هنا أو اختر عدة ملفات للرفع",
    dropzoneHint:
      "تُصنف الرسومات والصور في 02_Original_Drawings والمستندات والجداول في 01_Input_Documents مع حفظ الأصل للقراءة فقط وبصمة SHA-256.",
    chooseFilesBtn: "اختيار ملفات متعددة",
    uploadingBtn: "جاري رفع وفحص الملفات...",
    supportedLabel: "الامتدادات المدعومة",
    emptyList: "لا توجد ملفات مرفوعة لهذا المشروع بعد.",
    colFile: "الملف والمجلد",
    colType: "النوع",
    colSize: "الحجم",
    colHash: "بصمة SHA-256",
    colUploaded: "تاريخ الرفع / التحديث",
    colVersion: "الإصدار والتصنيف",
    colActions: "الإجراءات",
    readOnlyBadge: "الأصل للقراءة فقط",
    downloadBtn: "تنزيل",
    extractBtn: "استخراج البيانات",
    extractingBtn: "جاري الاستخراج...",
    versionsBtn: "سجل الإصدارات",
    hideVersionsBtn: "إخفاء الإصدارات",
    versionsHeading: "سجل الإصدارات الثابت",
    colVerNum: "الإصدار",
    colVerPath: "المسار النسبي",
    colVerHash: "SHA-256",
    colVerNote: "ملاحظة",
    colVerDate: "التاريخ",
    originalVersionTag: "أصل v1",
    summaryPrefix: "نتيجة الرفع",
    createdTag: "جديد",
    newVersionTag: "إصدار جديد",
    duplicateTag: "مكرر (تم تخطيه)",
    errorPrefix: "تعذر تنفيذ العملية: ",
    ocrLabel: "حالة التعرف الضوئي Tesseract OCR (ara+eng)",
    odaLabel: "حالة محوّل ODA File Converter (.dwg → .dxf)",
    matrixToggleLabel: "مصفوفة دعم الصيغ (Native / Converted via ODA / Not Supported)",
    extractionHeading: "نتائج الاستخراج المهيكل (Normalized JSON)",
    originalVerified: "تم التحقق: الأصل لم يتغير (SHA-256 مطابق تماماً)",
    warningsLabel: "ملاحظات وتحذيرات الاستخراج",
    renderedPagesLabel: "معاينة الصفحات والرسومات المصوّرة (03_Analysis)",
    visionBtn: "تلخيص بصري بـ Gemini Vision (تفسير غير قياسي)",
    visionLoadingBtn: "جاري التلخيص البصري...",
    inventoryHeading: "جدول جرد الرسومات ونماذج BIM (Drawing & BIM Inventory)",
    rawJsonLabel: "عرض JSON المهيكل الكامل للاستخراج",
    confirmUnitLabel: "تأكيد وحدة الرسم الهندسية من المالك",
    confirmUnitBtn: "تأكيد الوحدة",
    confirmingUnitBtn: "جاري الحفظ...",
    unitsDoubtfulTitle: "تنبيه: وحدات الرسم مشكوك فيها — يجب تأكيد الوحدة من المالك قبل اعتماد m²",
  },
  en: {
    heading: "Project Files & Version History",
    refreshBtn: "Refresh Files",
    loading: "Loading files...",
    dropzoneTitle: "Drag & drop engineering files here or select multiple files to upload",
    dropzoneHint:
      "Drawings/images route to 02_Original_Drawings and documents/spreadsheets route to 01_Input_Documents with read-only originals and SHA-256 verification.",
    chooseFilesBtn: "Select Multiple Files",
    uploadingBtn: "Uploading & hashing...",
    supportedLabel: "Supported Extensions",
    emptyList: "No files uploaded to this project yet.",
    colFile: "File & Folder",
    colType: "Type",
    colSize: "Size",
    colHash: "SHA-256 Hash",
    colUploaded: "Upload / Updated Date",
    colVersion: "Version & Label",
    colActions: "Actions",
    readOnlyBadge: "Read-only original",
    downloadBtn: "Download",
    extractBtn: "Extract Content",
    extractingBtn: "Extracting...",
    versionsBtn: "Version History",
    hideVersionsBtn: "Hide Versions",
    versionsHeading: "Immutable Version History",
    colVerNum: "Version",
    colVerPath: "Stored Path",
    colVerHash: "SHA-256",
    colVerNote: "Note",
    colVerDate: "Timestamp",
    originalVersionTag: "Original v1",
    summaryPrefix: "Upload Summary",
    createdTag: "Created",
    newVersionTag: "New Version",
    duplicateTag: "Duplicate (Skipped)",
    errorPrefix: "File operation failed: ",
    ocrLabel: "Tesseract OCR Status (ara+eng)",
    odaLabel: "ODA File Converter Status (.dwg → .dxf)",
    matrixToggleLabel: "Format Support Matrix (Native / Converted via ODA / Not Supported)",
    extractionHeading: "Structured Extraction Output (Normalized JSON)",
    originalVerified: "Verified: original file untouched (SHA-256 identical)",
    warningsLabel: "Extraction Notes & Warnings",
    renderedPagesLabel: "Rendered Page & Drawing Images (03_Analysis)",
    visionBtn: "Gemini Vision Summary (AI Interpretation — Not Measurement)",
    visionLoadingBtn: "Summarizing via Gemini Vision...",
    inventoryHeading: "Drawing & BIM Inventory Table",
    rawJsonLabel: "Inspect Full Normalized Extraction JSON",
    confirmUnitLabel: "Owner-Confirmed Drawing Unit",
    confirmUnitBtn: "Confirm Unit",
    confirmingUnitBtn: "Confirming...",
    unitsDoubtfulTitle: "units doubtful - owner must confirm drawing unit",
  },
};

const DEFAULT_EXTRACTABLE = new Set([
  ".pdf",
  ".docx",
  ".xlsx",
  ".csv",
  ".pptx",
  ".dxf",
  ".dwg",
  ".ifc",
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".bmp",
  ".webp",
  ".txt",
  ".md",
]);

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatIsoTimestamp(iso: string): string {
  return iso.replace("T", " ").replace(/\.\d+/, "").replace("+00:00", " UTC");
}

function shortHash(hash: string | null): string {
  if (!hash) {
    return "—";
  }
  return `${hash.slice(0, 12)}…${hash.slice(-6)}`;
}

export interface ProjectFilesPanelProps {
  lang: Lang;
  projectId: string;
  initialFiles?: ProjectFileOut[];
  initialExpandedFileId?: string | null;
  initialCapabilities?: ExtractionCapabilitiesOut | null;
  initialExtraction?: FileExtractionDetailOut | null;
}

export function ProjectFilesPanel({
  lang,
  projectId,
  initialFiles = [],
  initialExpandedFileId = null,
  initialCapabilities = null,
  initialExtraction = null,
}: ProjectFilesPanelProps) {
  const copy = FILES_COPY[lang];
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [files, setFiles] = useState<ProjectFileOut[]>(initialFiles);
  const [extInfo, setExtInfo] = useState<SupportedExtensionsResponse | null>(null);
  const [capabilities, setCapabilities] = useState<ExtractionCapabilitiesOut | null>(
    initialCapabilities
  );
  const [loading, setLoading] = useState<boolean>(false);
  const [uploading, setUploading] = useState<boolean>(false);
  const [extractingFileId, setExtractingFileId] = useState<string | null>(null);
  const [confirmingUnit, setConfirmingUnit] = useState<boolean>(false);
  const [selectedCadUnit, setSelectedCadUnit] = useState<CadUnitChoice>(
    (initialExtraction?.owner_confirmed_unit as CadUnitChoice | undefined) || "m"
  );
  const [summarizingVision, setSummarizingVision] = useState<boolean>(false);
  const [activeExtraction, setActiveExtraction] =
    useState<FileExtractionDetailOut | null>(initialExtraction);
  const [latestVisionSummary, setLatestVisionSummary] =
    useState<DrawingVisionSummaryOut | null>(null);
  const [dragActive, setDragActive] = useState<boolean>(false);
  const [expandedFileId, setExpandedFileId] = useState<string | null>(initialExpandedFileId);
  const [lastUpload, setLastUpload] = useState<ProjectFilesUploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadFiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listProjectFiles(projectId);
      setFiles(data.files);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadFiles();
    void getSupportedExtensions()
      .then((info) => setExtInfo(info))
      .catch(() => undefined);
    void getExtractionCapabilities()
      .then((cap) => setCapabilities(cap))
      .catch(() => undefined);
  }, [loadFiles]);

  async function processUpload(selectedFiles: File[]) {
    if (selectedFiles.length === 0) {
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const result = await uploadProjectFiles(projectId, selectedFiles);
      setLastUpload(result);
      await loadFiles();
      if (result.items.length > 0) {
        setExpandedFileId(result.items[0].file.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleExtractFile(fileId: string) {
    setExtractingFileId(fileId);
    setError(null);
    setLatestVisionSummary(null);
    try {
      const result = await extractProjectFile(fileId);
      setActiveExtraction(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExtractingFileId(null);
    }
  }

  async function handleConfirmDrawingUnit(extractionId: string) {
    setConfirmingUnit(true);
    setError(null);
    try {
      const updated = await confirmExtractionDrawingUnit(extractionId, selectedCadUnit);
      setActiveExtraction(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setConfirmingUnit(false);
    }
  }

  async function handleVisionSummary(extractionId: string, pageNumber = 1) {
    setSummarizingVision(true);
    setError(null);
    try {
      const summary = await summarizeDrawingVision(extractionId, { page_number: pageNumber });
      setLatestVisionSummary(summary);
      setActiveExtraction((prev) =>
        prev && prev.id === extractionId
          ? { ...prev, vision_summaries: [...(prev.vision_summaries || []), summary] }
          : prev
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSummarizingVision(false);
    }
  }

  function handleFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files ? Array.from(event.target.files) : [];
    event.target.value = "";
    void processUpload(picked);
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!dragActive) {
      setDragActive(true);
    }
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
    const dropped = Array.from(event.dataTransfer.files || []);
    void processUpload(dropped);
  }

  const acceptList = extInfo
    ? extInfo.extensions.map((item) => item.extension).join(",")
    : ".pdf,.doc,.docx,.txt,.rtf,.html,.htm,.md,.xls,.xlsx,.csv,.ods,.ppt,.pptx,.xml,.json,.landxml,.dwg,.dxf,.dgn,.dwf,.svg,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.ifc,.rvt,.rfa,.rte,.obj,.stl,.step,.stp,.iges,.igs,.gltf,.glb";

  const extractableSet = capabilities
    ? new Set(capabilities.supported_extensions.map((item) => item.toLowerCase()))
    : DEFAULT_EXTRACTABLE;

  return (
    <section className="subpanel files-panel" aria-label={copy.heading}>
      <div className="panel-header">
        <h3 className="panel-title">
          {copy.heading} ({files.length})
        </h3>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => void loadFiles()}
          disabled={loading || uploading}
        >
          {loading ? copy.loading : copy.refreshBtn}
        </button>
      </div>

      {capabilities && (
        <div style={{ display: "grid", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <div
            className={`status-box compact-status ${
              capabilities.ocr.installed ? "status-ok" : "notice-box"
            }`}
            style={{ marginTop: 0 }}
          >
            <strong>{copy.ocrLabel}:</strong>{" "}
            <span dir="ltr">{capabilities.ocr.status}</span> —{" "}
            <span>{capabilities.ocr.message}</span>
          </div>

          {capabilities.oda && (
            <div
              className={`status-box compact-status ${
                capabilities.oda.installed ? "status-ok" : "notice-box"
              }`}
              style={{ marginTop: 0 }}
            >
              <strong>{copy.odaLabel}:</strong>{" "}
              <span dir="ltr">{capabilities.oda.status}</span> —{" "}
              <span>{capabilities.oda.message}</span>
            </div>
          )}

          {capabilities.format_support_matrix && capabilities.format_support_matrix.length > 0 && (
            <details>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                {copy.matrixToggleLabel}
              </summary>
              <div className="table-wrap" style={{ marginTop: "0.5rem" }}>
                <table className="files-table">
                  <thead>
                    <tr>
                      <th>Format</th>
                      <th>Category</th>
                      <th>Support</th>
                      <th>Tool / Library</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {capabilities.format_support_matrix.map((row) => (
                      <tr key={row.extension}>
                        <td dir="ltr">
                          <code>{row.extension}</code>
                        </td>
                        <td dir="auto">{row.category}</td>
                        <td dir="ltr">
                          <span
                            className={`badge ${
                              row.support_level === "native"
                                ? "badge-connected"
                                : row.support_level === "converted_via_oda"
                                  ? ""
                                  : "badge-warn"
                            }`}
                          >
                            {row.support_level}
                          </span>
                        </td>
                        <td dir="ltr">{row.provider_or_tool}</td>
                        <td dir="auto">{row.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      )}

      <div
        className={`dropzone ${dragActive ? "dropzone-active" : ""}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <p className="dropzone-title">{copy.dropzoneTitle}</p>
        <p className="muted-line">{copy.dropzoneHint}</p>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={acceptList}
          onChange={handleFileInputChange}
          style={{ display: "none" }}
          aria-label={copy.chooseFilesBtn}
        />

        <div className="actions" style={{ justifyContent: "center" }}>
          <button
            type="button"
            className="btn"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? copy.uploadingBtn : copy.chooseFilesBtn}
          </button>
        </div>

        {extInfo && (
          <p className="supported-hint" dir="ltr">
            <strong>{copy.supportedLabel}:</strong>{" "}
            {extInfo.extensions.map((item) => item.extension).join(" ")} (max{" "}
            {formatBytes(extInfo.max_upload_size_bytes)}, up to {extInfo.max_files_per_upload} files)
          </p>
        )}
      </div>

      {error && (
        <div className="status-box status-err" role="alert">
          <strong>{copy.errorPrefix}</strong>
          <span>{error}</span>
        </div>
      )}

      {lastUpload && (
        <div className="status-box status-ok">
          <strong>{copy.summaryPrefix}:</strong>{" "}
          <span>
            {copy.createdTag}: {lastUpload.created_count} • {copy.newVersionTag}:{" "}
            {lastUpload.new_version_count} • {copy.duplicateTag}: {lastUpload.duplicate_count}
          </span>
          <ul className="outcome-list">
            {lastUpload.items.map((item, idx) => (
              <li key={`${item.filename}-${idx}`}>
                <strong dir="auto">{item.filename}</strong> — <code>{item.outcome}</code>:{" "}
                {item.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {files.length === 0 ? (
        <p className="muted-line">{loading ? copy.loading : copy.emptyList}</p>
      ) : (
        <div className="table-wrap">
          <table className="files-table">
            <thead>
              <tr>
                <th>{copy.colFile}</th>
                <th>{copy.colType}</th>
                <th>{copy.colSize}</th>
                <th>{copy.colHash}</th>
                <th>{copy.colUploaded}</th>
                <th>{copy.colVersion}</th>
                <th>{copy.colActions}</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => {
                const isExpanded = expandedFileId === file.id;
                const canExtract = Boolean(
                  file.extension && extractableSet.has(file.extension.toLowerCase())
                );
                return (
                  <tr key={file.id}>
                    <td>
                      <div className="file-cell-main">
                        <strong dir="auto">{file.original_filename}</strong>
                        <div className="file-submeta">
                          <code dir="ltr">{file.folder_name}</code>
                          {file.is_original && (
                            <span className="badge badge-readonly">{copy.readOnlyBadge}</span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td dir="ltr">
                      <div>{file.extension || "—"}</div>
                      <div className="muted-small">{file.mime_type || ""}</div>
                    </td>
                    <td dir="ltr" title={`${file.size_bytes} bytes`}>
                      {formatBytes(file.size_bytes)}
                    </td>
                    <td>
                      <code className="mono-hash" dir="ltr" title={file.sha256 || ""}>
                        {shortHash(file.sha256)}
                      </code>
                    </td>
                    <td dir="ltr" className="muted-small">
                      {formatIsoTimestamp(file.updated_at)}
                    </td>
                    <td>
                      <div className="badge-group">
                        <span className="badge">v{file.current_version}</span>
                        <span className="badge">{file.classification}</span>
                      </div>
                    </td>
                    <td>
                      <div className="actions" style={{ marginTop: 0 }}>
                        <a
                          className="btn btn-secondary btn-compact"
                          href={getFileDownloadUrl(file.id)}
                          download={file.original_filename}
                        >
                          {copy.downloadBtn}
                        </a>
                        {canExtract && (
                          <button
                            type="button"
                            className="btn btn-compact"
                            disabled={extractingFileId === file.id}
                            onClick={() => void handleExtractFile(file.id)}
                          >
                            {extractingFileId === file.id ? copy.extractingBtn : copy.extractBtn}
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn-secondary btn-compact"
                          onClick={() =>
                            setExpandedFileId((prev) => (prev === file.id ? null : file.id))
                          }
                        >
                          {isExpanded
                            ? copy.hideVersionsBtn
                            : `${copy.versionsBtn} (${file.versions.length})`}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {activeExtraction && (
        <div className="version-history-panel">
          <div className="panel-header">
            <h4 className="folders-title">
              {copy.extractionHeading} — <span dir="auto">{activeExtraction.source_file}</span>
            </h4>
            <div className="badge-group">
              <span
                className={`badge ${
                  activeExtraction.status === "extracted" ? "badge-connected" : "badge-warn"
                }`}
              >
                {activeExtraction.status}
              </span>
              <span className="badge">OCR: {activeExtraction.ocr_status}</span>
              {activeExtraction.converter_status && (
                <span className="badge">ODA: {activeExtraction.converter_status}</span>
              )}
              {activeExtraction.cad_units && (
                <span className="badge" dir="ltr">
                  Units: {activeExtraction.cad_units}
                </span>
              )}
              {activeExtraction.units_doubtful && (
                <span className="badge badge-warn" dir="ltr">
                  units doubtful
                </span>
              )}
              <span className="badge">{activeExtraction.classification}</span>
            </div>
          </div>

          {((activeExtraction.drawing_inventory as Record<string, unknown> | null)?.kind ===
            "cad_dxf" ||
            activeExtraction.units_doubtful) && (
            <div
              className={`status-box ${activeExtraction.units_doubtful ? "notice-box" : "status-ok"}`}
              style={{ marginTop: 0, marginBottom: "0.75rem" }}
            >
              {activeExtraction.units_doubtful && (
                <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>
                  {copy.unitsDoubtfulTitle}
                </div>
              )}
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
                <label>
                  <span>{copy.confirmUnitLabel}: </span>
                  <select
                    value={selectedCadUnit}
                    onChange={(e) => setSelectedCadUnit(e.target.value as CadUnitChoice)}
                  >
                    <option value="m">m (meters)</option>
                    <option value="cm">cm (centimeters)</option>
                    <option value="mm">mm (millimeters)</option>
                    <option value="ft">ft (feet)</option>
                    <option value="in">in (inches)</option>
                    <option value="yd">yd (yards)</option>
                    <option value="unitless">unitless (keep m2 null)</option>
                  </select>
                </label>
                <button
                  type="button"
                  className="btn btn-compact"
                  disabled={confirmingUnit}
                  onClick={() => void handleConfirmDrawingUnit(activeExtraction.id)}
                >
                  {confirmingUnit ? copy.confirmingUnitBtn : copy.confirmUnitBtn}
                </button>
              </div>
            </div>
          )}

          {activeExtraction.original_unchanged && (
            <div className="status-box status-ok" style={{ marginTop: 0, marginBottom: "0.75rem" }}>
              {copy.originalVerified} (<code>{shortHash(activeExtraction.sha256_after)}</code>)
              {activeExtraction.converted_artifact_relative_path && (
                <span>
                  {" "}
                  • Converted DXF: <code dir="ltr">{activeExtraction.converted_artifact_relative_path}</code>
                </span>
              )}
            </div>
          )}

          {activeExtraction.warnings.length > 0 && (
            <div className="status-box notice-box" style={{ marginTop: 0, marginBottom: "0.75rem" }}>
              <strong>{copy.warningsLabel}:</strong>
              <ul className="outcome-list">
                {activeExtraction.warnings.map((w, idx) => (
                  <li key={idx} dir="auto">
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <dl className="meta-grid">
            <div>
              <dt>Pages</dt>
              <dd dir="ltr">{activeExtraction.counts.pages}</dd>
            </div>
            <div>
              <dt>Sheets</dt>
              <dd dir="ltr">{activeExtraction.counts.sheets}</dd>
            </div>
            <div>
              <dt>Slides</dt>
              <dd dir="ltr">{activeExtraction.counts.slides}</dd>
            </div>
            <div>
              <dt>Tables</dt>
              <dd dir="ltr">{activeExtraction.counts.tables}</dd>
            </div>
            <div>
              <dt>Formulas</dt>
              <dd dir="ltr">{activeExtraction.counts.formulas}</dd>
            </div>
            <div>
              <dt>Text / OCR Items</dt>
              <dd dir="ltr">
                {activeExtraction.counts.text_items} / {activeExtraction.counts.ocr_items}
              </dd>
            </div>
            {(activeExtraction.counts.layers || 0) > 0 && (
              <div>
                <dt>CAD Layers / Blocks</dt>
                <dd dir="ltr">
                  {activeExtraction.counts.layers} / {activeExtraction.counts.blocks ?? 0}
                </dd>
              </div>
            )}
            {(activeExtraction.counts.entities || 0) > 0 && (
              <div>
                <dt>Entities / Areas</dt>
                <dd dir="ltr">
                  {activeExtraction.counts.entities} / {activeExtraction.counts.closed_areas ?? 0}
                </dd>
              </div>
            )}
            {(activeExtraction.counts.ifc_spaces || 0) > 0 && (
              <div>
                <dt>IFC Spaces / Walls / Doors / Win</dt>
                <dd dir="ltr">
                  {activeExtraction.counts.ifc_spaces} / {activeExtraction.counts.ifc_walls ?? 0} /{" "}
                  {activeExtraction.counts.ifc_doors ?? 0} /{" "}
                  {activeExtraction.counts.ifc_windows ?? 0}
                </dd>
              </div>
            )}
          </dl>

          {activeExtraction.rendered_page_images.length > 0 && (
            <div style={{ marginBottom: "0.85rem" }}>
              <strong>{copy.renderedPagesLabel}:</strong>{" "}
              <span className="badge-group" style={{ marginTop: "0.35rem" }}>
                {activeExtraction.rendered_page_images.map((relPath, idx) => (
                  <a
                    key={relPath}
                    className="btn btn-secondary btn-compact"
                    href={getExtractionPageImageUrl(activeExtraction.id, idx + 1)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    PNG Page {idx + 1}
                  </a>
                ))}
                <button
                  type="button"
                  className="btn btn-compact"
                  disabled={summarizingVision}
                  onClick={() => void handleVisionSummary(activeExtraction.id, 1)}
                >
                  {summarizingVision ? copy.visionLoadingBtn : copy.visionBtn}
                </button>
              </span>
            </div>
          )}

          {((activeExtraction.vision_summaries && activeExtraction.vision_summaries.length > 0) ||
            latestVisionSummary) && (
            <div className="status-box notice-box" style={{ marginBottom: "0.85rem" }}>
              {(() => {
                const list = activeExtraction.vision_summaries || [];
                const activeVision =
                  list[list.length - 1] || latestVisionSummary;
                if (!activeVision) {
                  return null;
                }
                return (
                  <div>
                    <div className="badge-group" style={{ marginBottom: "0.35rem" }}>
                      <span className="badge badge-warn">
                        AI INTERPRETATION ONLY — NOT MEASUREMENT
                      </span>
                      <span className="badge" dir="ltr">
                        {activeVision.model_name} (page {activeVision.page_number})
                      </span>
                    </div>
                    <p style={{ margin: "0.25rem 0", fontWeight: 600 }}>
                      {activeVision.disclaimer}
                    </p>
                    <p dir="auto" style={{ margin: "0.25rem 0" }}>
                      <strong>Title:</strong> {activeVision.drawing_title || "—"} |{" "}
                      <strong>Discipline Guess:</strong> {activeVision.discipline_guess}
                    </p>
                    {activeVision.visible_labels_and_notes.length > 0 && (
                      <p dir="auto" style={{ margin: "0.25rem 0" }}>
                        <strong>Visible Labels:</strong>{" "}
                        {activeVision.visible_labels_and_notes.join(" • ")}
                      </p>
                    )}
                    {activeVision.uncertainty_notes.length > 0 && (
                      <p dir="auto" style={{ margin: "0.25rem 0" }}>
                        <strong>Uncertainties:</strong>{" "}
                        {activeVision.uncertainty_notes.join(" • ")}
                      </p>
                    )}
                  </div>
                );
              })()}
            </div>
          )}

          {activeExtraction.drawing_inventory && (
            <div style={{ marginBottom: "0.9rem" }}>
              <h5 className="folders-title" style={{ marginBottom: "0.5rem" }}>
                {copy.inventoryHeading}
              </h5>
              {(() => {
                const inv = activeExtraction.drawing_inventory as Record<string, unknown>;
                const kind = String(inv.kind || "");
                if (kind === "cad_dxf") {
                  const layers = (inv.layers as Array<Record<string, unknown>>) || [];
                  const blocks = (inv.blocks as Array<Record<string, unknown>>) || [];
                  const areas = (inv.closed_areas as Array<Record<string, unknown>>) || [];
                  return (
                    <div style={{ display: "grid", gap: "0.65rem" }}>
                      {layers.length > 0 && (
                        <div className="table-wrap">
                          <table className="files-table">
                            <thead>
                              <tr>
                                <th>Layer Name</th>
                                <th>Color</th>
                                <th>Linetype</th>
                                <th>ModelSpace</th>
                                <th>PaperSpace</th>
                                <th>Total Entities</th>
                              </tr>
                            </thead>
                            <tbody>
                              {layers.map((l, i) => (
                                <tr key={`${String(l.name)}-${i}`}>
                                  <td dir="auto">
                                    <code>{String(l.name)}</code>
                                    {Boolean(l.raw_name) && (
                                      <span style={{ opacity: 0.75, marginInlineStart: "0.35rem" }}>
                                        (raw: <code dir="ltr">{String(l.raw_name)}</code>)
                                      </span>
                                    )}
                                  </td>
                                  <td dir="ltr">{String(l.color ?? "")}</td>
                                  <td dir="ltr">{String(l.linetype ?? "")}</td>
                                  <td dir="ltr">{String(l.modelspace_entities ?? 0)}</td>
                                  <td dir="ltr">{String(l.paperspace_entities ?? 0)}</td>
                                  <td dir="ltr">{String(l.total_entities ?? 0)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {areas.length > 0 && (
                        <div className="table-wrap">
                          <table className="files-table">
                            <thead>
                              <tr>
                                <th>Handle</th>
                                <th>Layer</th>
                                <th>Geometry</th>
                                <th>Native Area</th>
                                <th>Area (m2)</th>
                                <th>Perimeter / Length</th>
                              </tr>
                            </thead>
                            <tbody>
                              {areas.map((a, i) => (
                                <tr key={`${String(a.handle)}-${i}`}>
                                  <td dir="ltr">
                                    <code>{String(a.handle)}</code>
                                  </td>
                                  <td dir="auto">{String(a.layer)}</td>
                                  <td dir="ltr">{String(a.type)}</td>
                                  <td dir="ltr">
                                    {String(a.area_native ?? "—")} {String(a.area_native_unit ?? "")}
                                  </td>
                                  <td dir="ltr">
                                    {a.area_m2 !== undefined && a.area_m2 !== null
                                      ? String(a.area_m2)
                                      : "—"}
                                  </td>
                                  <td dir="ltr">{String(a.perimeter_native ?? "—")}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {blocks.length > 0 && (
                        <div className="table-wrap">
                          <table className="files-table">
                            <thead>
                              <tr>
                                <th>Block Name</th>
                                <th>Inserts</th>
                                <th>Entities in Def</th>
                                <th>XREF?</th>
                              </tr>
                            </thead>
                            <tbody>
                              {blocks.map((b, i) => (
                                <tr key={`${String(b.name)}-${i}`}>
                                  <td dir="auto">
                                    <code>{String(b.name)}</code>
                                    {Boolean(b.raw_name) && (
                                      <span style={{ opacity: 0.75, marginInlineStart: "0.35rem" }}>
                                        (raw: <code dir="ltr">{String(b.raw_name)}</code>)
                                      </span>
                                    )}
                                  </td>
                                  <td dir="ltr">{String(b.insert_count ?? 0)}</td>
                                  <td dir="ltr">{String(b.definition_entities ?? 0)}</td>
                                  <td dir="ltr">{b.is_xref ? "Yes (external)" : "No"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                }
                if (kind === "bim_ifc") {
                  const spaces = (inv.spaces as Array<Record<string, unknown>>) || [];
                  const elements = (inv.elements as Array<Record<string, unknown>>) || [];
                  return (
                    <div style={{ display: "grid", gap: "0.65rem" }}>
                      {spaces.length > 0 && (
                        <div className="table-wrap">
                          <table className="files-table">
                            <thead>
                              <tr>
                                <th>IfcSpace Name</th>
                                <th>Storey</th>
                                <th>Explicit Area</th>
                                <th>Source Quantity</th>
                                <th>GlobalId</th>
                              </tr>
                            </thead>
                            <tbody>
                              {spaces.map((s, i) => (
                                <tr key={`${String(s.global_id)}-${i}`}>
                                  <td dir="auto">
                                    <strong>{String(s.name || s.global_id)}</strong>
                                  </td>
                                  <td dir="auto">{String(s.storey || "—")}</td>
                                  <td dir="ltr">
                                    {s.area !== null && s.area !== undefined
                                      ? `${String(s.area)} ${String(s.area_unit || "")}`
                                      : "not_provided_in_ifc"}
                                  </td>
                                  <td dir="ltr">
                                    <code>{String(s.area_source || "—")}</code>
                                  </td>
                                  <td dir="ltr">
                                    <code>{String(s.global_id)}</code>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {elements.length > 0 && (
                        <div className="table-wrap">
                          <table className="files-table">
                            <thead>
                              <tr>
                                <th>IFC Type</th>
                                <th>Name</th>
                                <th>Tag</th>
                                <th>Storey</th>
                                <th>Explicit Area</th>
                              </tr>
                            </thead>
                            <tbody>
                              {elements.slice(0, 50).map((el, i) => (
                                <tr key={`${String(el.global_id)}-${i}`}>
                                  <td dir="ltr">
                                    <code>{String(el.ifc_type)}</code>
                                  </td>
                                  <td dir="auto">{String(el.name || "—")}</td>
                                  <td dir="ltr">{String(el.tag || "—")}</td>
                                  <td dir="auto">{String(el.storey || "—")}</td>
                                  <td dir="ltr">
                                    {el.area !== null && el.area !== undefined
                                      ? String(el.area)
                                      : "—"}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                }
                return null;
              })()}
            </div>
          )}

          <div className="table-wrap">
            <table className="files-table">
              <thead>
                <tr>
                  <th>Page / Sheet</th>
                  <th>Location</th>
                  <th>Type</th>
                  <th>Method</th>
                  <th>Extracted Content / Formula & Value</th>
                </tr>
              </thead>
              <tbody>
                {activeExtraction.items.map((item) => (
                  <tr key={item.item_index}>
                    <td dir="ltr">
                      <code>{item.page_or_sheet}</code>
                    </td>
                    <td dir="ltr">
                      <code>{item.location}</code>
                    </td>
                    <td dir="ltr">{item.item_type}</td>
                    <td dir="ltr">{item.extraction_method}</td>
                    <td dir="auto">
                      {item.formula ? (
                        <div dir="ltr">
                          <code>{item.formula}</code>
                          {item.cached_value !== null ? ` = ${item.cached_value}` : " (uncached)"}
                          {item.unit_or_format ? ` [${item.unit_or_format}]` : ""}
                        </div>
                      ) : item.raw_values ? (
                        <div dir="ltr">
                          {item.raw_values.length} rows:{" "}
                          {item.raw_values
                            .slice(0, 3)
                            .map((r) => r.join(" | "))
                            .join(" / ")}
                        </div>
                      ) : (
                        item.text || "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>
              {copy.rawJsonLabel}
            </summary>
            <pre className="json-preview" dir="ltr">
              {JSON.stringify(activeExtraction, null, 2)}
            </pre>
          </details>
        </div>
      )}

      {expandedFileId && (
        <div className="version-history-panel">
          {(() => {
            const selected = files.find((item) => item.id === expandedFileId);
            if (!selected) {
              return null;
            }
            return (
              <>
                <h4 className="folders-title">
                  {copy.versionsHeading} — <span dir="auto">{selected.original_filename}</span>
                </h4>
                <div className="table-wrap">
                  <table className="files-table version-table">
                    <thead>
                      <tr>
                        <th>{copy.colVerNum}</th>
                        <th>{copy.colVerPath}</th>
                        <th>{copy.colSize}</th>
                        <th>{copy.colVerHash}</th>
                        <th>{copy.colVerDate}</th>
                        <th>{copy.colVerNote}</th>
                        <th>{copy.colActions}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.versions.map((ver) => (
                        <tr key={ver.id}>
                          <td>
                            <span className="badge">v{ver.version_number}</span>
                            {ver.version_number === 1 && (
                              <span
                                className="badge badge-readonly"
                                style={{ marginInlineStart: "0.35rem" }}
                              >
                                {copy.originalVersionTag}
                              </span>
                            )}
                          </td>
                          <td>
                            <code dir="ltr">{ver.stored_relative_path}</code>
                          </td>
                          <td dir="ltr">{formatBytes(ver.size_bytes)}</td>
                          <td>
                            <code className="mono-hash" dir="ltr" title={ver.sha256}>
                              {shortHash(ver.sha256)}
                            </code>
                          </td>
                          <td dir="ltr" className="muted-small">
                            {formatIsoTimestamp(ver.created_at)}
                          </td>
                          <td>{ver.change_note || "—"}</td>
                          <td>
                            <a
                              className="btn btn-secondary btn-compact"
                              href={getFileDownloadUrl(selected.id, ver.version_number)}
                              download={selected.original_filename}
                            >
                              {copy.downloadBtn} v{ver.version_number}
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            );
          })()}
        </div>
      )}
    </section>
  );
}
