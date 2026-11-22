import { useCallback, useEffect, useState } from "react";
import {
  createSystemBackup,
  getBackupDownloadUrl,
  getSystemInfo,
  restoreSystemBackup,
} from "../api";
import type { BackupCreateOut, Lang, RestoreResultOut, SystemInfoOut } from "../types";

const COPY: Record<
  Lang,
  {
    heading: string;
    refreshBtn: string;
    bindLabel: string;
    corsLabel: string;
    logPathLabel: string;
    logRotationLabel: string;
    logShippingLabel: string;
    logShippingValue: string;
    backupDirLabel: string;
    keyringPolicyLabel: string;
    keyringPolicyValue: string;
    labelPlaceholder: string;
    createBackupBtn: string;
    creatingBtn: string;
    emptyBackups: string;
    filenameCol: string;
    sizeCol: string;
    shaCol: string;
    actionsCol: string;
    downloadLink: string;
    dryRunBtn: string;
    restoreBtn: string;
    confirmCheck: string;
  }
> = {
  ar: {
    heading: "الخطوة 20: أمان النظام وموقع السجلات والنسخ الاحتياطي والاستعادة",
    refreshBtn: "تحديث حالة النظام",
    bindLabel: "عنوان ربط الخادم (محلي فقط)",
    corsLabel: "مصادر CORS المحلية المسموحة",
    logPathLabel: "مسار ملف السجل المحلي الدوّار (بدون عارض ويب أو إرسال خارجي)",
    logRotationLabel: "سياسة تدوير السجل والتنقيح",
    logShippingLabel: "نقل السجلات عن بُعد / عارض السجلات",
    logShippingValue: "معطّل (محلي فقط مع تنقيح الأسرار وبيانات العميل)",
    backupDirLabel: "مجلد النسخ الاحتياطي المحلي",
    keyringPolicyLabel: "عزل مفاتيح API في مدير بيانات الاعتماد",
    keyringPolicyValue: "المفاتيح في keyring فقط — مستبعدة دائماً من النسخ الاحتياطية",
    labelPlaceholder: "وسم اختياري للنسخة (مثال: before_release)",
    createBackupBtn: "إنشاء نسخة احتياطية (ZIP + SHA-256)",
    creatingBtn: "جاري النسخ الاحتياطي...",
    emptyBackups: "لا توجد نسخ احتياطية منشأة بعد.",
    filenameCol: "الملف",
    sizeCol: "الحجم",
    shaCol: "بصمة SHA-256",
    actionsCol: "تحقق / تنزيل / استعادة",
    downloadLink: "تنزيل ZIP",
    dryRunBtn: "تحقق جاف (Dry-Run)",
    restoreBtn: "استعادة",
    confirmCheck: "أؤكد استبدال ملفات مساحة العمل وقاعدة البيانات من نسخة موثقة",
  },
  en: {
    heading: "Step 20: System Security, Local Log Location & Backup/Restore",
    refreshBtn: "Refresh System Info",
    bindLabel: "Backend Bind Host (Local Only)",
    corsLabel: "Strict Local CORS Origins",
    logPathLabel: "Local Rotating Log File Location (No Web Log Viewer / No Remote Shipping)",
    logRotationLabel: "Rotation & Redaction Policy",
    logShippingLabel: "Remote Log Shipping / Web Viewer",
    logShippingValue: "Disabled (local disk only, secret & client-data redacted)",
    backupDirLabel: "Backup Archive Directory",
    keyringPolicyLabel: "Credential Store Isolation",
    keyringPolicyValue: "API keys remain in OS keyring ONLY — excluded from backups",
    labelPlaceholder: "Optional backup tag (e.g. pre_review)",
    createBackupBtn: "Create Backup (ZIP + SHA-256)",
    creatingBtn: "Creating Backup...",
    emptyBackups: "No backup archives created yet.",
    filenameCol: "Archive",
    sizeCol: "Size",
    shaCol: "SHA-256",
    actionsCol: "Verify / Download / Restore",
    downloadLink: "Download ZIP",
    dryRunBtn: "Verify (Dry-Run)",
    restoreBtn: "Restore",
    confirmCheck: "Confirm overwriting workspace files & DB from verified archive",
  },
};

export interface SystemHardeningPanelProps {
  lang: Lang;
  initialSystemInfo?: SystemInfoOut | null;
}

export function SystemHardeningPanel({
  lang,
  initialSystemInfo = null,
}: SystemHardeningPanelProps) {
  const copy = COPY[lang];
  const [sysInfo, setSysInfo] = useState<SystemInfoOut | null>(initialSystemInfo);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const [busyFile, setBusyFile] = useState<string | null>(null);
  const [lastBackup, setLastBackup] = useState<BackupCreateOut | null>(null);
  const [restoreResult, setRestoreResult] = useState<RestoreResultOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadInfo = useCallback(async () => {
    try {
      const res = await getSystemInfo();
      setSysInfo(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void loadInfo();
  }, [loadInfo]);

  async function handleCreateBackup() {
    setCreating(true);
    setError(null);
    setRestoreResult(null);
    try {
      const created = await createSystemBackup({ label });
      setLastBackup(created);
      setLabel("");
      await loadInfo();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleRestore(filename: string, dryRun: boolean) {
    setBusyFile(filename);
    setError(null);
    try {
      const res = await restoreSystemBackup({
        backup_filename: filename,
        dry_run: dryRun,
        confirm_overwrite: !dryRun && confirmOverwrite,
      });
      setRestoreResult(res);
      if (!dryRun && res.restored) {
        setConfirmOverwrite(false);
        await loadInfo();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyFile(null);
    }
  }

  return (
    <section className="panel" aria-label={copy.heading}>
      <div className="panel-header">
        <h3>{copy.heading}</h3>
        <button type="button" className="btn btn-secondary" onClick={() => void loadInfo()}>
          {copy.refreshBtn}
        </button>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      <dl className="meta-grid">
        <div>
          <dt>{copy.bindLabel}</dt>
          <dd dir="ltr">
            <code>{sysInfo?.backend_host || "127.0.0.1"}</code>
          </dd>
        </div>
        <div>
          <dt>{copy.corsLabel}</dt>
          <dd dir="ltr">
            <code>{(sysInfo?.cors_origins || ["http://127.0.0.1:5173"]).join(", ")}</code>
          </dd>
        </div>
        <div>
          <dt>{copy.logPathLabel}</dt>
          <dd dir="ltr">
            <code>{sysInfo?.log_file_path || "workspaces/agent.log"}</code>
          </dd>
        </div>
        <div>
          <dt>{copy.logRotationLabel}</dt>
          <dd dir="ltr">{sysInfo?.log_rotation_policy || "Rotating JSONL (5 MB x 5)"}</dd>
        </div>
        <div>
          <dt>{copy.logShippingLabel}</dt>
          <dd>{copy.logShippingValue}</dd>
        </div>
        <div>
          <dt>{copy.backupDirLabel}</dt>
          <dd dir="ltr">
            <code>{sysInfo?.backup_dir || "workspaces/_backups"}</code>
          </dd>
        </div>
        <div>
          <dt>{copy.keyringPolicyLabel}</dt>
          <dd>{copy.keyringPolicyValue}</dd>
        </div>
      </dl>

      <div className="actions" style={{ marginTop: "0.75rem", flexWrap: "wrap", gap: "0.5rem" }}>
        <input
          type="text"
          dir="ltr"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={copy.labelPlaceholder}
          style={{ maxWidth: "18rem" }}
        />
        <button
          type="button"
          className="btn"
          disabled={creating}
          onClick={() => void handleCreateBackup()}
        >
          {creating ? copy.creatingBtn : copy.createBackupBtn}
        </button>
        <label style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
          <input
            type="checkbox"
            checked={confirmOverwrite}
            onChange={(e) => setConfirmOverwrite(e.target.checked)}
          />
          <span>{copy.confirmCheck}</span>
        </label>
      </div>

      {lastBackup && (
        <div className="alert success" style={{ marginTop: "0.75rem" }}>
          {lastBackup.message} — <code>{lastBackup.backup.sha256.slice(0, 16)}...</code>
        </div>
      )}

      {restoreResult && (
        <div
          className={`alert ${restoreResult.valid ? "success" : "error"}`}
          style={{ marginTop: "0.75rem" }}
        >
          {restoreResult.message} (valid={String(restoreResult.valid)}, dry_run=
          {String(restoreResult.dry_run)}, files={restoreResult.verified_files_count})
        </div>
      )}

      {(!sysInfo?.backups || sysInfo.backups.length === 0) ? (
        <p className="muted" style={{ marginTop: "0.75rem" }}>
          {copy.emptyBackups}
        </p>
      ) : (
        <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
          <table>
            <thead>
              <tr>
                <th>{copy.filenameCol}</th>
                <th>{copy.sizeCol}</th>
                <th>{copy.shaCol}</th>
                <th>{copy.actionsCol}</th>
              </tr>
            </thead>
            <tbody>
              {sysInfo.backups.map((b) => (
                <tr key={b.filename}>
                  <td dir="ltr">
                    <code>{b.filename}</code>
                  </td>
                  <td dir="ltr">{(b.size_bytes / 1024).toFixed(1)} KB</td>
                  <td dir="ltr" title={b.sha256}>
                    <code>{b.sha256.slice(0, 14)}...</code>
                  </td>
                  <td>
                    <div className="actions" style={{ gap: "0.35rem" }}>
                      <a
                        className="btn btn-secondary"
                        href={getBackupDownloadUrl(b.filename)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {copy.downloadLink}
                      </a>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={busyFile === b.filename}
                        onClick={() => void handleRestore(b.filename, true)}
                      >
                        {copy.dryRunBtn}
                      </button>
                      <button
                        type="button"
                        className="btn"
                        disabled={!confirmOverwrite || busyFile === b.filename}
                        onClick={() => void handleRestore(b.filename, false)}
                      >
                        {copy.restoreBtn}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
