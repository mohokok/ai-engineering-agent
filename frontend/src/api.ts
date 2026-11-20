import type {
  CadUnitChoice,
  ConnectionTestOut,
  DeliverableListResponse,
  DrawingVisionSummaryOut,
  ExtractionCapabilitiesOut,
  FileExtractionDetailOut,
  FileExtractionListResponse,
  HealthPayload,
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
