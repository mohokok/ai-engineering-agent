import type {
  ConnectionTestOut,
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
  payload?: { version_number?: number; force_ocr?: boolean }
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
