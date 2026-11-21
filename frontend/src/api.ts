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

async function extractErrorMessage(response: Response): Promise<string> {
  const fallback = `HTTP ${response.status}`;
  try {
    const body = (await response.json()) as {
      detail?: string | Array<{ msg?: string; loc?: Array<string | number> }>;
    };
    if (typeof body.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const messages = body.detail
        .map((item) => item.msg?.trim())
        .filter((msg): msg is string => Boolean(msg));
      if (messages.length > 0) {
        return messages.join("; ");
      }
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
