import { ChangeEvent, DragEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  getFileDownloadUrl,
  getSupportedExtensions,
  listProjectFiles,
  uploadProjectFiles,
} from "../api";
import type {
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
    errorPrefix: "تعذر رفع أو جلب الملفات: ",
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
  },
};

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
}

export function ProjectFilesPanel({
  lang,
  projectId,
  initialFiles = [],
  initialExpandedFileId = null,
}: ProjectFilesPanelProps) {
  const copy = FILES_COPY[lang];
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [files, setFiles] = useState<ProjectFileOut[]>(initialFiles);
  const [extInfo, setExtInfo] = useState<SupportedExtensionsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [uploading, setUploading] = useState<boolean>(false);
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
                              <span className="badge badge-readonly" style={{ marginInlineStart: "0.35rem" }}>
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
