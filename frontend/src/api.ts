import type {
  BoqDetailOut,
  BoqExportOut,
  BoqItemCreateRequest,
  BoqItemUpdateRequest,
  BoqListResponse,
  BoqSheetCreateRequest,
  CadUnitChoice,
  ConnectionTestOut,
  DeliverableListResponse,
  DrawingVisionSummaryOut,
  ExtractionCapabilitiesOut,
  FileExtractionDetailOut,
  FileExtractionListResponse,
  HealthPayload,
  ProjectClassification,
  ProjectCreateInput,
  ProjectDetail,
  ProjectFileListResponse,
  ProjectFilesUploadResponse,
  ProjectListResponse,
  ProviderSettingsOut,
  ProviderSettingsUpdate,
  ResearchCapabilitiesOut,
  ResearchHistoryListResponse,
  ResearchRunCreateRequest,
  ResearchRunDetailOut,
  ResearchSourceListResponse,
  ReviewReportDetailOut,
  ReviewReportGenerateRequest,
  ReviewReportListResponse,
  SearchProviderName,
  SupportedExtensionsResponse,
  TaskComplexity,
  TaskCreateRequest,
  TaskDetailOut,
  TaskListResponse,
} from "./types";

const FRIENDLY_HTTP_ERRORS: Record<number, { en: string; ar: string }> = {
  400: {
    en: "Invalid request parameters.",
    ar: "تعذر تنفيذ الطلب بسبب مدخلات غير صالحة.",
  },
  401: {
    en: "API authentication failed. Check the key stored in OS Credential Manager.",
    ar: "فشل التحقق من مفتاح الاعتماد. راجع المفتاح المحفوظ في مخزن النظام.",
  },
  404: {
    en: "Requested record or file was not found.",
    ar: "لم يتم العثور على السجل أو الملف المطلوب.",
  },
  409: {
    en: "Blocked to protect existing immutable files or revisions.",
    ar: "تم منع العملية لحماية الملفات أو الإصدارات غير القابلة للاستبدال.",
  },
  413: {
    en: "Uploaded files exceed the configured local size limit.",
    ar: "حجم الملفات المرفوعة يتجاوز الحد الأقصى المسموح به.",
  },
  422: {
    en: "Validation check failed. Review missing or invalid inputs.",
    ar: "فشل التحقق من صحة المدخلات. راجع الحقول الناقصة أو غير الصالحة.",
  },
  429: {
    en: "Configured AI usage limit or provider quota reached.",
    ar: "تم بلوغ حد الاستخدام المحدد أو حصة مزود الذكاء الاصطناعي.",
  },
  500: {
    en: "Internal server error. Check local workspace logs using the correlation ID.",
    ar: "حدث خطأ داخلي في الخادم. راجع سجل النظام المحلي برقم التتبع.",
  },
  503: {
    en: "AI provider temporarily unavailable. Deterministic engineering workflows remain active.",
    ar: "خدمة الذكاء الاصطناعي غير متاحة مؤقتاً. الأدوات الهندسية الحتمية مستمرة بالعمل.",
  },
};

function sanitizeUiErrorText(raw: string): string {
  return raw
    .split(/\r?\n/)
    .filter((ln) => !ln.includes("Traceback (most recent") && !ln.trim().startsWith('File "'))
    .join(" ")
    .trim();
}

export async function extractErrorMessage(response: Response): Promise<string> {
  const uiLang =
    typeof document !== "undefined" && document.documentElement.lang === "en" ? "en" : "ar";
  const mapped = FRIENDLY_HTTP_ERRORS[response.status];
  const fallback = mapped ? mapped[uiLang] : `HTTP ${response.status}`;

  try {
    const body = (await response.json()) as {
      detail?: string | Array<{ msg?: string; loc?: Array<string | number> }>;
      correlation_id?: string;
      error?: {
        code?: string;
        message?: string;
        message_ar?: string;
        correlation_id?: string;
      };
    };
    const cid = body.error?.correlation_id || body.correlation_id;
    const cidSuffix = cid ? ` [ref: ${cid}]` : "";

    let detailMsg = "";
    if (typeof body.detail === "string" && body.detail.trim()) {
      detailMsg = sanitizeUiErrorText(body.detail);
    } else if (Array.isArray(body.detail) && body.detail.length > 0) {
      const messages = body.detail
        .map((item) => sanitizeUiErrorText(item.msg || ""))
        .filter((msg) => Boolean(msg));
      if (messages.length > 0) {
        detailMsg = messages.join("; ");
      }
    }

    if (body.error) {
      const baseEn = sanitizeUiErrorText(body.error.message || detailMsg || mapped?.en || "");
      const baseAr = sanitizeUiErrorText(body.error.message_ar || mapped?.ar || "");
      if (uiLang === "ar" && baseAr) {
        if (detailMsg && detailMsg !== baseEn && response.status < 500) {
          return `${baseAr} (${detailMsg})${cidSuffix}`;
        }
        return `${baseAr}${cidSuffix}`;
      }
      const chosen = baseEn || detailMsg || fallback;
      return `${chosen}${cidSuffix}`;
    }

    if (detailMsg) {
      return `${detailMsg}${cidSuffix}`;
    }
  } catch {
    return fallback;
  }
  return fallback;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as T;
}

export function fetchHealth(): Promise<HealthPayload> {
  return requestJson<HealthPayload>("/api/health");
}

export function listProjects(): Promise<ProjectListResponse> {
  return requestJson<ProjectListResponse>("/api/projects");
}

export function createProject(payload: ProjectCreateInput): Promise<ProjectDetail> {
  return requestJson<ProjectDetail>("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return requestJson<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`);
}

export function getSupportedExtensions(): Promise<SupportedExtensionsResponse> {
  return requestJson<SupportedExtensionsResponse>("/api/files/supported-extensions");
}

export function listProjectFiles(projectId: string): Promise<ProjectFileListResponse> {
  return requestJson<ProjectFileListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/files`
  );
}

export function uploadProjectFiles(
  projectId: string,
  files: File[]
): Promise<ProjectFilesUploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file, file.name);
  }
  return requestJson<ProjectFilesUploadResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/files`,
    {
      method: "POST",
      body: formData,
    }
  );
}

export function getFileDownloadUrl(fileId: string, versionNumber?: number): string {
  const base = `/api/files/${encodeURIComponent(fileId)}/download`;
  if (versionNumber !== undefined) {
    return `${base}?version=${encodeURIComponent(String(versionNumber))}`;
  }
  return base;
}

export function getProviderSettings(): Promise<ProviderSettingsOut> {
  return requestJson<ProviderSettingsOut>("/api/settings/provider");
}

export function updateProviderSettings(
  payload: ProviderSettingsUpdate
): Promise<ProviderSettingsOut> {
  return requestJson<ProviderSettingsOut>("/api/settings/provider", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function saveProviderApiKey(apiKey: string): Promise<ProviderSettingsOut> {
  return requestJson<ProviderSettingsOut>("/api/settings/provider/api-key", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function deleteProviderApiKey(): Promise<ProviderSettingsOut> {
  return requestJson<ProviderSettingsOut>("/api/settings/provider/api-key", {
    method: "DELETE",
  });
}

export function testProviderConnection(
  complexity: TaskComplexity = "fast"
): Promise<ConnectionTestOut> {
  return requestJson<ConnectionTestOut>("/api/settings/provider/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ complexity }),
  });
}

export function refreshProviderModels(): Promise<ProviderSettingsOut> {
  return requestJson<ProviderSettingsOut>("/api/settings/provider/models/refresh", {
    method: "POST",
  });
}

export function createTask(payload: TaskCreateRequest): Promise<TaskDetailOut> {
  return requestJson<TaskDetailOut>("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listTasks(filters?: {
  projectId?: string;
  status?: string;
}): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  if (filters?.projectId) {
    params.set("project_id", filters.projectId);
  }
  if (filters?.status) {
    params.set("status", filters.status);
  }
  const query = params.toString();
  return requestJson<TaskListResponse>(query ? `/api/tasks?${query}` : "/api/tasks");
}

export function getTaskDetail(taskId: string): Promise<TaskDetailOut> {
  return requestJson<TaskDetailOut>(`/api/tasks/${encodeURIComponent(taskId)}`);
}

export function getExtractionCapabilities(): Promise<ExtractionCapabilitiesOut> {
  return requestJson<ExtractionCapabilitiesOut>("/api/extraction/capabilities");
}

export function extractProjectFile(
  fileId: string,
  payload?: { version_number?: number; force_ocr?: boolean; confirmed_unit?: CadUnitChoice }
): Promise<FileExtractionDetailOut> {
  return requestJson<FileExtractionDetailOut>(
    `/api/files/${encodeURIComponent(fileId)}/extract`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function confirmExtractionDrawingUnit(
  extractionId: string,
  confirmedUnit: CadUnitChoice
): Promise<FileExtractionDetailOut> {
  return requestJson<FileExtractionDetailOut>(
    `/api/extractions/${encodeURIComponent(extractionId)}/confirm-unit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed_unit: confirmedUnit }),
    }
  );
}

export function listFileExtractions(fileId: string): Promise<FileExtractionListResponse> {
  return requestJson<FileExtractionListResponse>(
    `/api/files/${encodeURIComponent(fileId)}/extractions`
  );
}

export function getExtractionDetail(extractionId: string): Promise<FileExtractionDetailOut> {
  return requestJson<FileExtractionDetailOut>(
    `/api/extractions/${encodeURIComponent(extractionId)}`
  );
}

export function getExtractionPageImageUrl(extractionId: string, pageNumber: number): string {
  return `/api/extractions/${encodeURIComponent(extractionId)}/pages/${encodeURIComponent(String(pageNumber))}`;
}

export function summarizeDrawingVision(
  extractionId: string,
  payload?: { page_number?: number; complexity?: "fast" | "deep" }
): Promise<DrawingVisionSummaryOut> {
  return requestJson<DrawingVisionSummaryOut>(
    `/api/extractions/${encodeURIComponent(extractionId)}/vision-summary`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function getResearchCapabilities(): Promise<ResearchCapabilitiesOut> {
  return requestJson<ResearchCapabilitiesOut>("/api/research/capabilities");
}

export function saveSearchProviderKey(
  providerId: Exclude<SearchProviderName, "duckduckgo_lite" | "crossref">,
  apiKey: string
): Promise<ResearchCapabilitiesOut> {
  return requestJson<ResearchCapabilitiesOut>(
    `/api/research/providers/${encodeURIComponent(providerId)}/api-key`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    }
  );
}

export function deleteSearchProviderKey(
  providerId: Exclude<SearchProviderName, "duckduckgo_lite" | "crossref">
): Promise<ResearchCapabilitiesOut> {
  return requestJson<ResearchCapabilitiesOut>(
    `/api/research/providers/${encodeURIComponent(providerId)}/api-key`,
    { method: "DELETE" }
  );
}

export function runControlledResearch(
  payload: ResearchRunCreateRequest
): Promise<ResearchRunDetailOut> {
  return requestJson<ResearchRunDetailOut>("/api/research/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listResearchRuns(options?: {
  project_id?: string;
  status?: string;
}): Promise<ResearchHistoryListResponse> {
  const params = new URLSearchParams();
  if (options?.project_id) {
    params.set("project_id", options.project_id);
  }
  if (options?.status) {
    params.set("status", options.status);
  }
  const q = params.toString();
  return requestJson<ResearchHistoryListResponse>(
    q ? `/api/research/runs?${q}` : "/api/research/runs"
  );
}

export function getResearchRunDetail(runId: string): Promise<ResearchRunDetailOut> {
  return requestJson<ResearchRunDetailOut>(
    `/api/research/runs/${encodeURIComponent(runId)}`
  );
}

export function synthesizeResearchRun(
  runId: string,
  complexity: "fast" | "deep" = "fast"
): Promise<ResearchRunDetailOut> {
  return requestJson<ResearchRunDetailOut>(
    `/api/research/runs/${encodeURIComponent(runId)}/synthesize`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ complexity }),
    }
  );
}

export function listResearchSources(options?: {
  project_id?: string;
  reviewed_only?: boolean;
}): Promise<ResearchSourceListResponse> {
  const params = new URLSearchParams();
  if (options?.project_id) {
    params.set("project_id", options.project_id);
  }
  if (options?.reviewed_only !== undefined) {
    params.set("reviewed_only", String(options.reviewed_only));
  }
  const q = params.toString();
  return requestJson<ResearchSourceListResponse>(
    q ? `/api/research/sources?${q}` : "/api/research/sources"
  );
}

export function generateReviewReport(
  projectId: string,
  payload: ReviewReportGenerateRequest
): Promise<ReviewReportDetailOut> {
  return requestJson<ReviewReportDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/review-reports`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectReviewReports(
  projectId: string
): Promise<ReviewReportListResponse> {
  return requestJson<ReviewReportListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/review-reports`
  );
}

export function getReviewReportDetail(reportId: string): Promise<ReviewReportDetailOut> {
  return requestJson<ReviewReportDetailOut>(
    `/api/review-reports/${encodeURIComponent(reportId)}`
  );
}

export function enhanceReviewReportAi(
  reportId: string,
  complexity: "fast" | "deep" = "fast"
): Promise<ReviewReportDetailOut> {
  return requestJson<ReviewReportDetailOut>(
    `/api/review-reports/${encodeURIComponent(reportId)}/ai-synthesize`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ complexity }),
    }
  );
}

export function listDeliverables(options?: {
  project_id?: string;
  folder_name?: string;
  format?: string;
}): Promise<DeliverableListResponse> {
  const params = new URLSearchParams();
  if (options?.project_id) {
    params.set("project_id", options.project_id);
  }
  if (options?.folder_name) {
    params.set("folder_name", options.folder_name);
  }
  if (options?.format) {
    params.set("format", options.format);
  }
  const q = params.toString();
  return requestJson<DeliverableListResponse>(q ? `/api/deliverables?${q}` : "/api/deliverables");
}

export function getDeliverableDownloadUrl(deliverableId: string): string {
  return `/api/deliverables/${encodeURIComponent(deliverableId)}/download`;
}

export function createBoqSheet(
  projectId: string,
  payload: BoqSheetCreateRequest
): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/boq-sheets`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectBoqSheets(projectId: string): Promise<BoqListResponse> {
  return requestJson<BoqListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/boq-sheets`
  );
}

export function getBoqDetail(boqId: string): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(`/api/boq-sheets/${encodeURIComponent(boqId)}`);
}

export function updateBoqSheet(
  boqId: string,
  payload: {
    title?: string;
    currency?: string;
    classification?: ProjectClassification;
    language?: "ar" | "en";
  }
): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(`/api/boq-sheets/${encodeURIComponent(boqId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function importExtractionsIntoBoq(
  boqId: string,
  payload: {
    file_ids?: string[];
    include_dxf_ifc?: boolean;
    include_boq_imports?: boolean;
    replace_extracted?: boolean;
  }
): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(
    `/api/boq-sheets/${encodeURIComponent(boqId)}/import-extractions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function addBoqItem(
  boqId: string,
  payload: BoqItemCreateRequest
): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(`/api/boq-sheets/${encodeURIComponent(boqId)}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateBoqItem(
  boqId: string,
  itemId: string,
  payload: BoqItemUpdateRequest
): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(
    `/api/boq-sheets/${encodeURIComponent(boqId)}/items/${encodeURIComponent(itemId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function deleteBoqItem(boqId: string, itemId: string): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(
    `/api/boq-sheets/${encodeURIComponent(boqId)}/items/${encodeURIComponent(itemId)}`,
    { method: "DELETE" }
  );
}

export function rerunBoqChecks(boqId: string): Promise<BoqDetailOut> {
  return requestJson<BoqDetailOut>(
    `/api/boq-sheets/${encodeURIComponent(boqId)}/checks`,
    { method: "POST" }
  );
}

export function exportBoqDeliverables(
  boqId: string,
  payload?: { language?: "ar" | "en"; include_checks_sheet?: boolean }
): Promise<BoqExportOut> {
  return requestJson<BoqExportOut>(
    `/api/boq-sheets/${encodeURIComponent(boqId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function getClinicPresetModel(): Promise<import("./types").ParametricPlanModel> {
  return requestJson<import("./types").ParametricPlanModel>(
    "/api/parametric-drawings/clinic-preset"
  );
}

export function suggestParametricModel(
  projectId: string,
  payload: { brief: string; complexity?: "fast" | "deep" }
): Promise<import("./types").ParametricModelSuggestOut> {
  return requestJson<import("./types").ParametricModelSuggestOut>(
    `/api/projects/${encodeURIComponent(projectId)}/parametric-drawings/suggest-model`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function generateParametricDrawing(
  projectId: string,
  payload: import("./types").ParametricDrawingGenerateRequest
): Promise<import("./types").ParametricDrawingDetailOut> {
  return requestJson<import("./types").ParametricDrawingDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/parametric-drawings`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectParametricDrawings(
  projectId: string
): Promise<import("./types").ParametricDrawingListResponse> {
  return requestJson<import("./types").ParametricDrawingListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/parametric-drawings`
  );
}

export function getParametricDrawingDetail(
  drawingId: string
): Promise<import("./types").ParametricDrawingDetailOut> {
  return requestJson<import("./types").ParametricDrawingDetailOut>(
    `/api/parametric-drawings/${encodeURIComponent(drawingId)}`
  );
}

export function runProjectQaReview(
  projectId: string,
  payload?: { task_id?: string | null; classification?: import("./types").ProjectClassification }
): Promise<import("./types").QaReviewDetailOut> {
  return requestJson<import("./types").QaReviewDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/qa-reviews`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function listProjectQaReviews(
  projectId: string
): Promise<import("./types").QaReviewListResponse> {
  return requestJson<import("./types").QaReviewListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/qa-reviews`
  );
}

export function verifyTaskWithQa(
  taskId: string,
  payload?: { qa_review_id?: string | null; verifier_note?: string | null }
): Promise<import("./types").TaskVerifyOut> {
  return requestJson<import("./types").TaskVerifyOut>(
    `/api/tasks/${encodeURIComponent(taskId)}/verify`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function listProjectIssues(
  projectId: string,
  params?: { status?: string; severity?: string; task_id?: string }
): Promise<import("./types").IssueListResponse> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.severity) qs.set("severity", params.severity);
  if (params?.task_id) qs.set("task_id", params.task_id);
  const queryStr = qs.toString();
  return requestJson<import("./types").IssueListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/issues${queryStr ? `?${queryStr}` : ""}`
  );
}

export function createManualIssue(
  projectId: string,
  payload: {
    task_id?: string | null;
    description: string;
    discipline: string;
    severity: import("./types").IssueSeverity;
    reference?: string | null;
    corrective_action: string;
  }
): Promise<import("./types").IssueOut> {
  return requestJson<import("./types").IssueOut>(
    `/api/projects/${encodeURIComponent(projectId)}/issues`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function updateQaIssue(
  issueId: string,
  payload: {
    status?: import("./types").IssueStatus;
    severity?: import("./types").IssueSeverity;
    corrective_action?: string;
    closure_note?: string;
  }
): Promise<import("./types").IssueOut> {
  return requestJson<import("./types").IssueOut>(
    `/api/issues/${encodeURIComponent(issueId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listCalculationPresets(): Promise<import("./types").CalculationPresetListResponse> {
  return requestJson<import("./types").CalculationPresetListResponse>("/api/calculations/presets");
}

export function listProjectCalculations(
  projectId: string
): Promise<import("./types").CalculationListResponse> {
  return requestJson<import("./types").CalculationListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/calculations`
  );
}

export function getCalculationDetail(
  calculationId: string
): Promise<import("./types").CalculationDetailOut> {
  return requestJson<import("./types").CalculationDetailOut>(
    `/api/calculations/${encodeURIComponent(calculationId)}`
  );
}

export function createCalculation(
  projectId: string,
  payload: {
    task_id?: string | null;
    title: string;
    calculation_type: import("./types").CalculationType;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    inputs: Record<string, unknown>;
    assumptions_override?: string[];
    references: import("./types").CalculationReferenceIn[];
  }
): Promise<import("./types").CalculationDetailOut> {
  return requestJson<import("./types").CalculationDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/calculations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function updateCalculation(
  calculationId: string,
  payload: {
    title?: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    inputs?: Record<string, unknown>;
    assumptions_override?: string[];
    references?: import("./types").CalculationReferenceIn[];
  }
): Promise<import("./types").CalculationDetailOut> {
  return requestJson<import("./types").CalculationDetailOut>(
    `/api/calculations/${encodeURIComponent(calculationId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function exportCalculationDeliverables(
  calculationId: string,
  payload?: { language?: import("./types").ReportLanguage }
): Promise<import("./types").CalculationExportOut> {
  return requestJson<import("./types").CalculationExportOut>(
    `/api/calculations/${encodeURIComponent(calculationId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function listSpecificationPresets(): Promise<import("./types").SpecificationPresetListResponse> {
  return requestJson<import("./types").SpecificationPresetListResponse>("/api/specifications/presets");
}

export function generateProjectSpecification(
  projectId: string,
  payload: {
    task_id?: string | null;
    title?: string | null;
    discipline?: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    boq_sheet_ids?: string[];
    drawing_ids?: string[];
    research_source_ids?: string[];
    use_ai?: boolean;
    complexity?: TaskComplexity;
    change_note?: string | null;
  }
): Promise<import("./types").SpecificationDetailOut> {
  return requestJson<import("./types").SpecificationDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/specifications`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectSpecifications(
  projectId: string
): Promise<import("./types").SpecificationListResponse> {
  return requestJson<import("./types").SpecificationListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/specifications`
  );
}

export function getSpecificationDetail(
  specId: string
): Promise<import("./types").SpecificationDetailOut> {
  return requestJson<import("./types").SpecificationDetailOut>(
    `/api/specifications/${encodeURIComponent(specId)}`
  );
}

export function approveSpecificationDraft(
  specId: string,
  payload: { approved_by?: string; approval_note?: string | null; export_after_approval?: boolean }
): Promise<import("./types").SpecificationDetailOut> {
  return requestJson<import("./types").SpecificationDetailOut>(
    `/api/specifications/${encodeURIComponent(specId)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function exportSpecificationDeliverables(
  specId: string,
  payload?: { language?: import("./types").ReportLanguage; change_note?: string | null }
): Promise<import("./types").SpecificationExportOut> {
  return requestJson<import("./types").SpecificationExportOut>(
    `/api/specifications/${encodeURIComponent(specId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function listComparisonPresets(): Promise<import("./types").ComparisonPresetListResponse> {
  return requestJson<import("./types").ComparisonPresetListResponse>("/api/comparisons/presets");
}

export function createTechnicalComparison(
  projectId: string,
  payload: {
    task_id?: string | null;
    title?: string | null;
    comparison_scope: import("./types").ComparisonScope;
    discipline?: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    lifecycle_years?: number | null;
    criteria: import("./types").ComparisonCriterionIn[];
    options: import("./types").ComparisonOptionIn[];
    use_ai?: boolean;
    complexity?: TaskComplexity;
  }
): Promise<import("./types").TechnicalComparisonDetailOut> {
  return requestJson<import("./types").TechnicalComparisonDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/comparisons`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectComparisons(
  projectId: string
): Promise<import("./types").TechnicalComparisonListResponse> {
  return requestJson<import("./types").TechnicalComparisonListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/comparisons`
  );
}

export function getComparisonDetail(
  comparisonId: string
): Promise<import("./types").TechnicalComparisonDetailOut> {
  return requestJson<import("./types").TechnicalComparisonDetailOut>(
    `/api/comparisons/${encodeURIComponent(comparisonId)}`
  );
}

export function decideTechnicalComparison(
  comparisonId: string,
  payload: {
    selected_option_id: string;
    decided_by?: string;
    decision_note: string;
    approve_ai_draft?: boolean;
    export_after_decision?: boolean;
  }
): Promise<import("./types").TechnicalComparisonDetailOut> {
  return requestJson<import("./types").TechnicalComparisonDetailOut>(
    `/api/comparisons/${encodeURIComponent(comparisonId)}/decide`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function exportTechnicalComparison(
  comparisonId: string,
  payload?: { language?: import("./types").ReportLanguage }
): Promise<import("./types").TechnicalComparisonExportOut> {
  return requestJson<import("./types").TechnicalComparisonExportOut>(
    `/api/comparisons/${encodeURIComponent(comparisonId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function listPlanningPresets(): Promise<import("./types").PlanningPresetListResponse> {
  return requestJson<import("./types").PlanningPresetListResponse>("/api/planning/presets");
}

export function createProjectSchedule(
  projectId: string,
  payload: {
    task_id?: string | null;
    title?: string | null;
    discipline?: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    start_date: string;
    calendar: import("./types").WorkCalendarIn;
    wbs_items: import("./types").WbsItemIn[];
    activities: import("./types").ScheduleActivityIn[];
    baseline_schedule_id?: string | null;
    set_as_baseline?: boolean;
    use_ai?: boolean;
    complexity?: TaskComplexity;
  }
): Promise<import("./types").ProjectScheduleDetailOut> {
  return requestJson<import("./types").ProjectScheduleDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/schedules`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectSchedules(
  projectId: string
): Promise<import("./types").ProjectScheduleListResponse> {
  return requestJson<import("./types").ProjectScheduleListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/schedules`
  );
}

export function getScheduleDetail(
  scheduleId: string
): Promise<import("./types").ProjectScheduleDetailOut> {
  return requestJson<import("./types").ProjectScheduleDetailOut>(
    `/api/schedules/${encodeURIComponent(scheduleId)}`
  );
}

export function setScheduleAsBaseline(
  scheduleId: string
): Promise<import("./types").ProjectScheduleDetailOut> {
  return requestJson<import("./types").ProjectScheduleDetailOut>(
    `/api/schedules/${encodeURIComponent(scheduleId)}/set-baseline`,
    {
      method: "POST",
    }
  );
}

export function approveScheduleDraft(
  scheduleId: string,
  payload: { approved_by?: string; approval_note?: string | null; export_after_approval?: boolean }
): Promise<import("./types").ProjectScheduleDetailOut> {
  return requestJson<import("./types").ProjectScheduleDetailOut>(
    `/api/schedules/${encodeURIComponent(scheduleId)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function exportScheduleDeliverables(
  scheduleId: string,
  payload?: { language?: import("./types").ReportLanguage }
): Promise<import("./types").ProjectScheduleExportOut> {
  return requestJson<import("./types").ProjectScheduleExportOut>(
    `/api/schedules/${encodeURIComponent(scheduleId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function listStandardPresets(): Promise<import("./types").StandardPresetListResponse> {
  return requestJson<import("./types").StandardPresetListResponse>("/api/standards/presets");
}

export function listStandards(params?: {
  project_id?: string | null;
  include_global?: boolean;
  q?: string;
  number?: string;
  status?: string;
  issuing_body?: string;
  adopted_locally?: boolean | null;
}): Promise<import("./types").StandardListResponse> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set("project_id", params.project_id);
  if (params?.include_global !== undefined) {
    qs.set("include_global", String(params.include_global));
  }
  if (params?.q) qs.set("q", params.q);
  if (params?.number) qs.set("number", params.number);
  if (params?.status) qs.set("status", params.status);
  if (params?.issuing_body) qs.set("issuing_body", params.issuing_body);
  if (params?.adopted_locally !== undefined && params?.adopted_locally !== null) {
    qs.set("adopted_locally", String(params.adopted_locally));
  }
  const suffix = qs.toString();
  return requestJson<import("./types").StandardListResponse>(
    `/api/standards${suffix ? `?${suffix}` : ""}`
  );
}

export function createStandard(
  payload: import("./types").StandardCreatePayload
): Promise<import("./types").StandardDocumentOut> {
  return requestJson<import("./types").StandardDocumentOut>("/api/standards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function uploadStandardDocument(params: {
  file: File;
  project_id?: string | null;
  use_ai?: boolean;
  complexity?: TaskComplexity;
  jurisdiction?: string;
  adopted_locally?: boolean;
}): Promise<import("./types").StandardDocumentOut> {
  const formData = new FormData();
  formData.append("file", params.file);
  if (params.project_id) formData.append("project_id", params.project_id);
  formData.append("use_ai", String(Boolean(params.use_ai)));
  if (params.complexity) formData.append("complexity", params.complexity);
  if (params.jurisdiction) formData.append("jurisdiction", params.jurisdiction);
  formData.append("adopted_locally", String(Boolean(params.adopted_locally)));

  const res = await fetch("/api/standards/upload", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Upload failed with status ${res.status}`);
  }
  return (await res.json()) as import("./types").StandardDocumentOut;
}

export function getStandardDetail(
  standardId: string
): Promise<import("./types").StandardDocumentOut> {
  return requestJson<import("./types").StandardDocumentOut>(
    `/api/standards/${encodeURIComponent(standardId)}`
  );
}

export function updateStandard(
  standardId: string,
  payload: {
    standard_number?: string;
    title?: string;
    issuing_body?: string;
    edition_year?: string;
    status?: import("./types").StandardStatus;
    superseded_by_id?: string | null;
    supersession_note?: string | null;
    jurisdiction?: string;
    adopted_locally?: boolean;
    owner_notes?: string | null;
    owner_excerpts?: import("./types").OwnerExcerptIn[];
    confirm_metadata?: boolean;
    change_note?: string;
  }
): Promise<import("./types").StandardDocumentOut> {
  return requestJson<import("./types").StandardDocumentOut>(
    `/api/standards/${encodeURIComponent(standardId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function confirmStandardMetadata(
  standardId: string,
  payload: {
    standard_number?: string;
    title?: string;
    issuing_body?: string;
    edition_year?: string;
    status?: import("./types").StandardStatus;
    jurisdiction?: string;
    adopted_locally?: boolean;
    owner_notes?: string | null;
    owner_excerpts?: import("./types").OwnerExcerptIn[];
    confirmed_by?: string;
  }
): Promise<import("./types").StandardDocumentOut> {
  return requestJson<import("./types").StandardDocumentOut>(
    `/api/standards/${encodeURIComponent(standardId)}/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function supersedeStandard(
  standardId: string,
  payload: {
    superseded_by_id?: string | null;
    new_standard?: import("./types").StandardCreatePayload | null;
    supersession_note: string;
  }
): Promise<import("./types").StandardDocumentOut> {
  return requestJson<import("./types").StandardDocumentOut>(
    `/api/standards/${encodeURIComponent(standardId)}/supersede`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function exportStandardsRegister(payload: {
  project_id?: string | null;
  language?: import("./types").ReportLanguage;
  classification?: ProjectClassification;
}): Promise<import("./types").StandardRegisterExportOut> {
  return requestJson<import("./types").StandardRegisterExportOut>(
    "/api/standards/export-register",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function getStandardsRegisterDownloadUrl(filename: string): string {
  return `/api/standards/register-files/${encodeURIComponent(filename)}`;
}

export function listSpecialistPresets(): Promise<import("./types").SpecialistPresetListResponse> {
  return requestJson<import("./types").SpecialistPresetListResponse>(
    "/api/specialist-assessments/presets"
  );
}

export function createSpecialistAssessment(
  projectId: string,
  payload: {
    task_id?: string | null;
    domain: import("./types").SpecialistDomain;
    workflow_mode?: import("./types").SpecialistWorkflowMode;
    title: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    inputs: Record<string, unknown>;
    references?: import("./types").SpecialistReferenceIn[];
    use_ai?: boolean;
    complexity?: TaskComplexity;
  }
): Promise<import("./types").SpecialistDetailOut> {
  return requestJson<import("./types").SpecialistDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/specialist-assessments`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectSpecialistAssessments(
  projectId: string
): Promise<import("./types").SpecialistListResponse> {
  return requestJson<import("./types").SpecialistListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/specialist-assessments`
  );
}

export function getSpecialistDetail(
  assessmentId: string
): Promise<import("./types").SpecialistDetailOut> {
  return requestJson<import("./types").SpecialistDetailOut>(
    `/api/specialist-assessments/${encodeURIComponent(assessmentId)}`
  );
}

export function updateSpecialistAssessment(
  assessmentId: string,
  payload: {
    workflow_mode?: import("./types").SpecialistWorkflowMode;
    title?: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    inputs?: Record<string, unknown>;
    references?: import("./types").SpecialistReferenceIn[];
  }
): Promise<import("./types").SpecialistDetailOut> {
  return requestJson<import("./types").SpecialistDetailOut>(
    `/api/specialist-assessments/${encodeURIComponent(assessmentId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function approveSpecialistAssessment(
  assessmentId: string,
  payload: { approved_by?: string; approval_note?: string | null }
): Promise<import("./types").SpecialistDetailOut> {
  return requestJson<import("./types").SpecialistDetailOut>(
    `/api/specialist-assessments/${encodeURIComponent(assessmentId)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function exportSpecialistDeliverables(
  assessmentId: string,
  payload?: { language?: import("./types").ReportLanguage }
): Promise<import("./types").SpecialistExportOut> {
  return requestJson<import("./types").SpecialistExportOut>(
    `/api/specialist-assessments/${encodeURIComponent(assessmentId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function listStructuralPresets(): Promise<import("./types").StructuralPresetListResponse> {
  return requestJson<import("./types").StructuralPresetListResponse>(
    "/api/structural-assessments/presets"
  );
}

export function createStructuralAssessment(
  projectId: string,
  payload: {
    task_id?: string | null;
    assessment_type?: import("./types").StructuralAssessmentType;
    title: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    inputs: Record<string, unknown>;
    references?: import("./types").SpecialistReferenceIn[];
    use_ai?: boolean;
    complexity?: TaskComplexity;
  }
): Promise<import("./types").StructuralDetailOut> {
  return requestJson<import("./types").StructuralDetailOut>(
    `/api/projects/${encodeURIComponent(projectId)}/structural-assessments`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function listProjectStructuralAssessments(
  projectId: string
): Promise<import("./types").StructuralListResponse> {
  return requestJson<import("./types").StructuralListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/structural-assessments`
  );
}

export function getStructuralDetail(
  assessmentId: string
): Promise<import("./types").StructuralDetailOut> {
  return requestJson<import("./types").StructuralDetailOut>(
    `/api/structural-assessments/${encodeURIComponent(assessmentId)}`
  );
}

export function updateStructuralAssessment(
  assessmentId: string,
  payload: {
    assessment_type?: import("./types").StructuralAssessmentType;
    title?: string;
    language?: import("./types").ReportLanguage;
    classification?: ProjectClassification;
    revision?: string;
    inputs?: Record<string, unknown>;
    references?: import("./types").SpecialistReferenceIn[];
  }
): Promise<import("./types").StructuralDetailOut> {
  return requestJson<import("./types").StructuralDetailOut>(
    `/api/structural-assessments/${encodeURIComponent(assessmentId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function approveStructuralAssessment(
  assessmentId: string,
  payload: { approved_by?: string; approval_note?: string | null }
): Promise<import("./types").StructuralDetailOut> {
  return requestJson<import("./types").StructuralDetailOut>(
    `/api/structural-assessments/${encodeURIComponent(assessmentId)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function exportStructuralDeliverables(
  assessmentId: string,
  payload?: { language?: import("./types").ReportLanguage }
): Promise<import("./types").StructuralExportOut> {
  return requestJson<import("./types").StructuralExportOut>(
    `/api/structural-assessments/${encodeURIComponent(assessmentId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }
  );
}

export function getSystemInfo(): Promise<import("./types").SystemInfoOut> {
  return requestJson<import("./types").SystemInfoOut>("/api/system/info");
}

export function createSystemBackup(
  payload?: { label?: string }
): Promise<import("./types").BackupCreateOut> {
  return requestJson<import("./types").BackupCreateOut>("/api/system/backup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
}

export function restoreSystemBackup(payload: {
  backup_filename: string;
  dry_run: boolean;
  confirm_overwrite?: boolean;
}): Promise<import("./types").RestoreResultOut> {
  return requestJson<import("./types").RestoreResultOut>("/api/system/restore", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getBackupDownloadUrl(filename: string): string {
  return `/api/system/backups/${encodeURIComponent(filename)}/download`;
}
