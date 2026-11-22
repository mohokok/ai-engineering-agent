import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  deleteProviderApiKey,
  getProviderSettings,
  refreshProviderModels,
  saveProviderApiKey,
  testProviderConnection,
  updateProviderSettings,
} from "../api";
import type {
  ConnectionTestOut,
  Lang,
  ProviderModelOption,
  ProviderSettingsOut,
  SystemInfoOut,
} from "../types";
import { SystemHardeningPanel } from "./SystemHardeningPanel";

interface SettingsCopy {
  heading: string;
  refreshBtn: string;
  loading: string;
  noticeTitle: string;
  noticeBodyAr: string;
  keySectionHeading: string;
  keyStatusLabel: string;
  keyStoredBadge: string;
  keyMissingBadge: string;
  keyBackendLabel: string;
  keyInputLabel: string;
  keyInputPlaceholder: string;
  saveKeyBtn: string;
  savingKeyBtn: string;
  removeKeyBtn: string;
  configSectionHeading: string;
  refreshModelsBtn: string;
  refreshingModelsBtn: string;
  liveModelsBadge: string;
  fallbackModelsBadge: string;
  modelsRefreshedNotice: string;
  customModelOption: string;
  manualModelPlaceholder: string;
  providerLabel: string;
  fastModelLabel: string;
  deepModelLabel: string;
  dailyReqLimitLabel: string;
  dailyTokenLimitLabel: string;
  monthlyReqLimitLabel: string;
  monthlyTokenLimitLabel: string;
  maxOutputTokensLabel: string;
  saveConfigBtn: string;
  savingConfigBtn: string;
  usageSectionHeading: string;
  requestsTodayLabel: string;
  tokensTodayLabel: string;
  requestsMonthLabel: string;
  tokensMonthLabel: string;
  promptTokensLabel: string;
  outputTokensLabel: string;
  connectionHeading: string;
  statusConnected: string;
  statusError: string;
  statusUntested: string;
  testConnectionBtn: string;
  testingConnectionBtn: string;
  keySavedNotice: string;
  keyRemovedNotice: string;
  configSavedNotice: string;
  errorPrefix: string;
}

const SETTINGS_COPY: Record<Lang, SettingsCopy> = {
  ar: {
    heading: "إعدادات مزود الذكاء الاصطناعي و Gemini API",
    refreshBtn: "تحديث الإعدادات",
    loading: "جاري تحميل الإعدادات...",
    noticeTitle: "تنبيه مهم حول الاشتراك والمفتاح",
    noticeBodyAr:
      "اشتراك Gemini الاستهلاكي (Gemini Advanced / Google One) لا يشمل تلقائياً الوصول إلى واجهة Gemini API. يجب إنشاء مفتاح Gemini API مصرح به من Google AI Studio؛ ويُحفظ محلياً فقط في مدير بيانات اعتماد Windows (keyring) ولا يُعرض أو يُعاد من الخادم أبداً.",
    keySectionHeading: "بيانات اعتماد Gemini API (مقنّع في الواجهة)",
    keyStatusLabel: "حالة المفتاح",
    keyStoredBadge: "محفوظ بأمان (••••••••••••)",
    keyMissingBadge: "غير محفوظ بعد",
    keyBackendLabel: "مخزن المفاتيح",
    keyInputLabel: "أدخل مفتاح Gemini API جديداً (يُحفظ في keyring فقط)",
    keyInputPlaceholder: "أدخل المفتاح هنا — لن يظهر بعد الحفظ",
    saveKeyBtn: "حفظ المفتاح في Windows Credential Manager",
    savingKeyBtn: "جاري الحفظ...",
    removeKeyBtn: "حذف المفتاح المحفوظ",
    configSectionHeading: "اختيار المزود والنماذج وحدود الاستخدام",
    refreshModelsBtn: "تحديث النماذج الحية (generateContent)",
    refreshingModelsBtn: "جاري جلب النماذج...",
    liveModelsBadge: "قائمة حية من Gemini API",
    fallbackModelsBadge: "قائمة افتراضية",
    modelsRefreshedNotice: "تم تحديث قائمة النماذج الداعمة لـ generateContent من حسابك.",
    customModelOption: "— إدخال معرف نموذج مخصص أدناه —",
    manualModelPlaceholder: "أو اكتب معرف النموذج يدوياً",
    providerLabel: "مزود الذكاء الاصطناعي النشط",
    fastModelLabel: "النموذج للمهام السريعة (Fast)",
    deepModelLabel: "النموذج للتحليل العميق (Deep)",
    dailyReqLimitLabel: "الحد اليومي للطلبات",
    dailyTokenLimitLabel: "الحد اليومي للرموز (Tokens)",
    monthlyReqLimitLabel: "الحد الشهري للطلبات",
    monthlyTokenLimitLabel: "الحد الشهري للرموز (Tokens)",
    maxOutputTokensLabel: "الحد الأقصى لرموز الإخراج في الطلب",
    saveConfigBtn: "حفظ تفضيلات النماذج والحدود",
    savingConfigBtn: "جاري الحفظ...",
    usageSectionHeading: "الاستخدام اليومي المسجل (UTC)",
    requestsTodayLabel: "الطلبات اليوم",
    tokensTodayLabel: "إجمالي الرموز اليوم",
    requestsMonthLabel: "الطلبات هذا الشهر",
    tokensMonthLabel: "إجمالي الرموز هذا الشهر",
    promptTokensLabel: "رموز الإدخال",
    outputTokensLabel: "رموز الإخراج",
    connectionHeading: "حالة الاتصال واختبار التكامل",
    statusConnected: "متصل بنجاح",
    statusError: "فشل الاتصال",
    statusUntested: "لم يتم الاختبار بعد",
    testConnectionBtn: "اختبار الاتصال بـ Gemini",
    testingConnectionBtn: "جاري اختبار الاتصال...",
    keySavedNotice: "تم حفظ المفتاح في مخزن بيانات الاعتماد (keyring) بنجاح.",
    keyRemovedNotice: "تم حذف المفتاح من مخزن بيانات الاعتماد.",
    configSavedNotice: "تم حفظ تفضيلات المزود وحدود الاستخدام.",
    errorPrefix: "تعذر إتمام الإجراء: ",
  },
  en: {
    heading: "AI Provider & Gemini API Settings",
    refreshBtn: "Refresh Settings",
    loading: "Loading settings...",
    noticeTitle: "Important API Access Notice",
    noticeBodyAr: "",
    keySectionHeading: "Gemini API Credentials (Masked & Keyring-Backed)",
    keyStatusLabel: "Key Status",
    keyStoredBadge: "Stored securely (••••••••••••)",
    keyMissingBadge: "Not configured",
    keyBackendLabel: "Credential Backend",
    keyInputLabel: "Enter Gemini API Key (stored only in Windows Credential Manager via keyring)",
    keyInputPlaceholder: "Paste API key locally — never echoed back",
    saveKeyBtn: "Save API Key to Keyring",
    savingKeyBtn: "Saving key...",
    removeKeyBtn: "Remove Stored Key",
    configSectionHeading: "Provider Selection, Complexity Models & Usage Limits",
    refreshModelsBtn: "Refresh models",
    refreshingModelsBtn: "Refreshing models...",
    liveModelsBadge: "Live API (generateContent)",
    fallbackModelsBadge: "Fallback catalog",
    modelsRefreshedNotice: "Refreshed live generateContent-capable models from your API key.",
    customModelOption: "— Custom model ID entered below —",
    manualModelPlaceholder: "Or enter custom model ID manually",
    providerLabel: "Active AI Provider",
    fastModelLabel: "Fast Complexity Model",
    deepModelLabel: "Deep Complexity Model",
    dailyReqLimitLabel: "Daily Request Limit",
    dailyTokenLimitLabel: "Daily Token Limit",
    monthlyReqLimitLabel: "Monthly Request Limit",
    monthlyTokenLimitLabel: "Monthly Token Limit",
    maxOutputTokensLabel: "Max Output Tokens per Call",
    saveConfigBtn: "Save Model & Limit Preferences",
    savingConfigBtn: "Saving preferences...",
    usageSectionHeading: "Recorded Today's Usage (UTC)",
    requestsTodayLabel: "Requests Today",
    tokensTodayLabel: "Total Tokens Today",
    requestsMonthLabel: "Requests This Month",
    tokensMonthLabel: "Total Tokens This Month",
    promptTokensLabel: "Prompt Tokens",
    outputTokensLabel: "Output Tokens",
    connectionHeading: "Connection Status & Live Check",
    statusConnected: "Connected",
    statusError: "Connection Error",
    statusUntested: "Not Tested Yet",
    testConnectionBtn: "Test connection",
    testingConnectionBtn: "Testing connection...",
    keySavedNotice: "API key stored securely in system credential store (keyring).",
    keyRemovedNotice: "Stored API key removed from system credential store.",
    configSavedNotice: "Provider model selection and usage limits updated.",
    errorPrefix: "Action failed: ",
  },
};

interface ModelSelectorFieldProps {
  label: string;
  value: string;
  onChange: (nextValue: string) => void;
  options: ProviderModelOption[];
  customOptionLabel: string;
  manualPlaceholder: string;
}

function ModelSelectorField({
  label,
  value,
  onChange,
  options,
  customOptionLabel,
  manualPlaceholder,
}: ModelSelectorFieldProps) {
  const isKnownOption = options.some((opt) => opt.id === value);
  return (
    <label className="field">
      <span>{label}</span>
      <select
        dir="ltr"
        value={isKnownOption ? value : "__custom__"}
        onChange={(e) => {
          if (e.target.value !== "__custom__") {
            onChange(e.target.value);
          }
        }}
      >
        {options.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
        {!isKnownOption && <option value="__custom__">{customOptionLabel}</option>}
      </select>
      <input
        type="text"
        dir="ltr"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={manualPlaceholder}
      />
    </label>
  );
}

export interface ProviderSettingsViewProps {
  lang: Lang;
  initialSettings?: ProviderSettingsOut | null;
  initialSystemInfo?: SystemInfoOut | null;
}

export function ProviderSettingsView({
  lang,
  initialSettings = null,
  initialSystemInfo = null,
}: ProviderSettingsViewProps) {
  const copy = SETTINGS_COPY[lang];

  const [settings, setSettings] = useState<ProviderSettingsOut | null>(initialSettings);
  const [loading, setLoading] = useState<boolean>(false);
  const [savingKey, setSavingKey] = useState<boolean>(false);
  const [savingConfig, setSavingConfig] = useState<boolean>(false);
  const [refreshingModels, setRefreshingModels] = useState<boolean>(false);
  const [testing, setTesting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastTest, setLastTest] = useState<ConnectionTestOut | null>(null);

  const [apiKeyInput, setApiKeyInput] = useState<string>("");
  const [activeProvider, setActiveProvider] = useState<string>(
    initialSettings?.active_provider ?? "gemini"
  );
  const [fastModel, setFastModel] = useState<string>(
    initialSettings?.models.fast ?? "gemini-3.8-flash"
  );
  const [deepModel, setDeepModel] = useState<string>(
    initialSettings?.models.deep ?? "gemini-4-argon"
  );
  const [dailyReqLimit, setDailyReqLimit] = useState<number>(
    initialSettings?.usage_limits.daily_request_limit ?? 200
  );
  const [dailyTokenLimit, setDailyTokenLimit] = useState<number>(
    initialSettings?.usage_limits.daily_token_limit ?? 500000
  );
  const [monthlyReqLimit, setMonthlyReqLimit] = useState<number>(
    initialSettings?.usage_limits.monthly_request_limit ?? 3000
  );
  const [monthlyTokenLimit, setMonthlyTokenLimit] = useState<number>(
    initialSettings?.usage_limits.monthly_token_limit ?? 5000000
  );
  const [maxOutputTokens, setMaxOutputTokens] = useState<number>(
    initialSettings?.usage_limits.max_output_tokens ?? 8192
  );

  const syncFormState = useCallback((loaded: ProviderSettingsOut) => {
    setSettings(loaded);
    setActiveProvider(loaded.active_provider);
    setFastModel(loaded.models.fast);
    setDeepModel(loaded.models.deep);
    setDailyReqLimit(loaded.usage_limits.daily_request_limit);
    setDailyTokenLimit(loaded.usage_limits.daily_token_limit);
    setMonthlyReqLimit(loaded.usage_limits.monthly_request_limit);
    setMonthlyTokenLimit(loaded.usage_limits.monthly_token_limit);
    setMaxOutputTokens(loaded.usage_limits.max_output_tokens);
  }, []);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getProviderSettings();
      syncFormState(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [syncFormState]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  async function handleSaveKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!apiKeyInput.trim()) {
      return;
    }
    setSavingKey(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await saveProviderApiKey(apiKeyInput.trim());
      setApiKeyInput("");
      syncFormState(updated);
      setNotice(copy.keySavedNotice);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  }

  async function handleDeleteKey() {
    setSavingKey(true);
    setError(null);
    setNotice(null);
    setLastTest(null);
    try {
      const updated = await deleteProviderApiKey();
      syncFormState(updated);
      setNotice(copy.keyRemovedNotice);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  }

  async function handleSaveConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSavingConfig(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateProviderSettings({
        active_provider: activeProvider,
        models: { fast: fastModel.trim(), deep: deepModel.trim() },
        usage_limits: {
          daily_request_limit: Number(dailyReqLimit),
          daily_token_limit: Number(dailyTokenLimit),
          monthly_request_limit: Number(monthlyReqLimit),
          monthly_token_limit: Number(monthlyTokenLimit),
          max_output_tokens: Number(maxOutputTokens),
        },
      });
      syncFormState(updated);
      setNotice(copy.configSavedNotice);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingConfig(false);
    }
  }

  async function handleRefreshModels() {
    setRefreshingModels(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await refreshProviderModels();
      syncFormState(updated);
      setNotice(copy.modelsRefreshedNotice);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshingModels(false);
    }
  }

  async function handleTestConnection() {
    setTesting(true);
    setError(null);
    setNotice(null);
    setLastTest(null);
    try {
      const result = await testProviderConnection("fast");
      setLastTest(result);
      await loadSettings();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await loadSettings();
    } finally {
      setTesting(false);
    }
  }

  const activeProviderMeta = settings?.available_providers.find(
    (item) => item.id === activeProvider
  );
  const checkStatus = settings?.last_connection_check.status ?? "untested";
  const statusLabel =
    checkStatus === "connected"
      ? copy.statusConnected
      : checkStatus === "error"
      ? copy.statusError
      : copy.statusUntested;

  return (
    <div className="workspace-section">
      <div className="panel-header">
        <h2 className="panel-title">{copy.heading}</h2>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => void loadSettings()}
          disabled={loading}
        >
          {loading ? copy.loading : copy.refreshBtn}
        </button>
      </div>

      <div className="status-box notice-box">
        <strong>{copy.noticeTitle}:</strong>{" "}
        <span>
          {lang === "ar"
            ? copy.noticeBodyAr
            : settings?.consumer_subscription_notice ||
              "Note: A Gemini consumer web subscription does not include Gemini API access. Store an authorized Gemini API key locally via keyring."}
        </span>
      </div>

      {settings?.model_warning && (
        <div className="status-box notice-box" role="status">
          <span>{settings.model_warning}</span>
        </div>
      )}

      {error && (
        <div className="status-box status-err" role="alert">
          <strong>{copy.errorPrefix}</strong>
          <span>{error}</span>
        </div>
      )}

      {notice && (
        <div className="status-box status-ok">
          <span>{notice}</span>
        </div>
      )}

      <section className="subpanel" aria-label={copy.connectionHeading}>
        <div className="panel-header">
          <h3 className="panel-title">{copy.connectionHeading}</h3>
          <span
            className={`badge ${
              checkStatus === "connected"
                ? "badge-connected"
                : checkStatus === "error"
                ? "badge-err"
                : ""
            }`}
          >
            {statusLabel}
          </span>
        </div>

        <dl className="meta-grid">
          <div>
            <dt>{copy.keyStatusLabel}</dt>
            <dd>
              {settings?.api_key_configured ? copy.keyStoredBadge : copy.keyMissingBadge}
            </dd>
          </div>
          <div>
            <dt>{copy.keyBackendLabel}</dt>
            <dd dir="ltr">{settings?.credential_backend || "keyring"}</dd>
          </div>
          <div>
            <dt>{copy.requestsTodayLabel}</dt>
            <dd dir="ltr">
              {settings?.daily_usage.requests ?? 0} / {dailyReqLimit}
            </dd>
          </div>
          <div>
            <dt>{copy.tokensTodayLabel}</dt>
            <dd dir="ltr">
              {settings?.daily_usage.total_tokens ?? 0} / {dailyTokenLimit}
            </dd>
          </div>
          <div>
            <dt>{copy.requestsMonthLabel}</dt>
            <dd dir="ltr">
              {settings?.monthly_usage.requests ?? 0} / {monthlyReqLimit}
            </dd>
          </div>
          <div>
            <dt>{copy.tokensMonthLabel}</dt>
            <dd dir="ltr">
              {settings?.monthly_usage.total_tokens ?? 0} / {monthlyTokenLimit}
            </dd>
          </div>
        </dl>

        {settings?.last_connection_check.message && (
          <p className="muted-line" dir="auto">
            {settings.last_connection_check.message}
            {settings.last_connection_check.latency_ms !== null &&
              ` (${settings.last_connection_check.latency_ms} ms)`}
          </p>
        )}

        {lastTest && (
          <p className="muted-line" dir="ltr">
            Model: {lastTest.model} • Tokens: {lastTest.usage.total_tokens} • Latency:{" "}
            {lastTest.latency_ms} ms
          </p>
        )}

        <div className="actions">
          <button
            type="button"
            className="btn"
            onClick={() => void handleTestConnection()}
            disabled={testing}
          >
            {testing ? copy.testingConnectionBtn : copy.testConnectionBtn}
          </button>
          {settings?.api_key_configured && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void handleDeleteKey()}
              disabled={savingKey}
            >
              {copy.removeKeyBtn}
            </button>
          )}
        </div>
      </section>

      <section className="subpanel" aria-label={copy.keySectionHeading}>
        <h3 className="panel-title">{copy.keySectionHeading}</h3>
        <form className="project-form" onSubmit={(e) => void handleSaveKey(e)}>
          <label className="field">
            <span>{copy.keyInputLabel}</span>
            <input
              type="password"
              autoComplete="off"
              dir="ltr"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder={copy.keyInputPlaceholder}
            />
          </label>
          <div className="actions">
            <button
              type="submit"
              className="btn"
              disabled={savingKey || !apiKeyInput.trim()}
            >
              {savingKey ? copy.savingKeyBtn : copy.saveKeyBtn}
            </button>
          </div>
        </form>
      </section>

      <section className="subpanel" aria-label={copy.configSectionHeading}>
        <div className="panel-header">
          <h3 className="panel-title">{copy.configSectionHeading}</h3>
          <div className="badge-group">
            <span className="badge">
              {settings?.models_source === "live_api"
                ? copy.liveModelsBadge
                : copy.fallbackModelsBadge}
            </span>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void handleRefreshModels()}
              disabled={refreshingModels}
            >
              {refreshingModels ? copy.refreshingModelsBtn : copy.refreshModelsBtn}
            </button>
          </div>
        </div>
        <form className="project-form" onSubmit={(e) => void handleSaveConfig(e)}>
          <div className="form-grid">
            <label className="field">
              <span>{copy.providerLabel}</span>
              <select
                value={activeProvider}
                onChange={(e) => setActiveProvider(e.target.value)}
              >
                {(settings?.available_providers.length
                  ? settings.available_providers
                  : [{ id: "gemini", name: "Google Gemini (Official google-genai SDK)", models: [] }]
                ).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <ModelSelectorField
              label={copy.fastModelLabel}
              value={fastModel}
              onChange={setFastModel}
              options={activeProviderMeta?.models || []}
              customOptionLabel={copy.customModelOption}
              manualPlaceholder={copy.manualModelPlaceholder}
            />

            <ModelSelectorField
              label={copy.deepModelLabel}
              value={deepModel}
              onChange={setDeepModel}
              options={activeProviderMeta?.models || []}
              customOptionLabel={copy.customModelOption}
              manualPlaceholder={copy.manualModelPlaceholder}
            />

            <label className="field">
              <span>{copy.dailyReqLimitLabel}</span>
              <input
                type="number"
                min={1}
                max={100000}
                dir="ltr"
                value={dailyReqLimit}
                onChange={(e) => setDailyReqLimit(Number(e.target.value))}
              />
            </label>

            <label className="field">
              <span>{copy.dailyTokenLimitLabel}</span>
              <input
                type="number"
                min={1000}
                max={100000000}
                dir="ltr"
                value={dailyTokenLimit}
                onChange={(e) => setDailyTokenLimit(Number(e.target.value))}
              />
            </label>

            <label className="field">
              <span>{copy.monthlyReqLimitLabel}</span>
              <input
                type="number"
                min={1}
                max={5000000}
                dir="ltr"
                value={monthlyReqLimit}
                onChange={(e) => setMonthlyReqLimit(Number(e.target.value))}
              />
            </label>

            <label className="field">
              <span>{copy.monthlyTokenLimitLabel}</span>
              <input
                type="number"
                min={1000}
                max={5000000000}
                dir="ltr"
                value={monthlyTokenLimit}
                onChange={(e) => setMonthlyTokenLimit(Number(e.target.value))}
              />
            </label>

            <label className="field">
              <span>{copy.maxOutputTokensLabel}</span>
              <input
                type="number"
                min={64}
                max={65536}
                dir="ltr"
                value={maxOutputTokens}
                onChange={(e) => setMaxOutputTokens(Number(e.target.value))}
              />
            </label>
          </div>

          <div className="actions">
            <button type="submit" className="btn" disabled={savingConfig}>
              {savingConfig ? copy.savingConfigBtn : copy.saveConfigBtn}
            </button>
          </div>
        </form>

        <dl className="meta-grid" style={{ marginTop: "1rem", marginBottom: 0 }}>
          <div>
            <dt>{copy.promptTokensLabel}</dt>
            <dd dir="ltr">{settings?.daily_usage.prompt_tokens ?? 0}</dd>
          </div>
          <div>
            <dt>{copy.outputTokensLabel}</dt>
            <dd dir="ltr">{settings?.daily_usage.output_tokens ?? 0}</dd>
          </div>
          <div>
            <dt>{copy.usageSectionHeading}</dt>
            <dd dir="ltr">{settings?.daily_usage.date_utc || "—"}</dd>
          </div>
        </dl>
      </section>

      <SystemHardeningPanel lang={lang} initialSystemInfo={initialSystemInfo} />
    </div>
  );
}
