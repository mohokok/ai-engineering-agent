export type Lang = "ar" | "en";

export type ProjectClassification =
  | "Preliminary"
  | "Conceptual"
  | "For Review"
  | "For Coordination"
  | "For Approval";

export interface HealthPayload {
  status: string;
  service: string;
  version: string;
  environment: string;
  classification: string;
}

export interface WorkspaceFolderOut {
  name: string;
  relative_path: string;
  exists: boolean;
}

export interface ProjectSummary {
  id: string;
  code: string;
  name: string;
  name_en: string | null;
  client_name: string | null;
  location: string | null;
  description: string | null;
  discipline_scope: string | null;
  status: string;
  classification: ProjectClassification | string;
  workspace_slug: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends ProjectSummary {
  workspace_exists: boolean;
  folders: WorkspaceFolderOut[];
}

export interface ProjectListResponse {
  projects: ProjectSummary[];
  total: number;
  classification: string;
}

export interface ProjectCreateInput {
  name: string;
  code?: string;
  name_en?: string;
  client_name?: string;
  location?: string;
  description?: string;
  discipline_scope?: string;
  classification?: ProjectClassification;
}

export interface SupportedExtensionOut {
  extension: string;
  category: string;
  target_folder: string;
  mime_hint: string;
}

export interface SupportedExtensionsResponse {
  extensions: SupportedExtensionOut[];
  explicitly_unsupported_examples: string[];
  max_upload_size_bytes: number;
  max_files_per_upload: number;
  classification: string;
}

export interface FileVersionOut {
  id: string;
  file_id: string;
  version_number: number;
  stored_relative_path: string;
  size_bytes: number;
  sha256: string;
  change_note: string | null;
  created_by: string;
  created_at: string;
}

export interface ProjectFileOut {
  id: string;
  project_id: string;
  folder_name: string;
  original_filename: string;
  stored_relative_path: string;
  mime_type: string | null;
  extension: string | null;
  size_bytes: number;
  sha256: string | null;
  is_original: boolean;
  status: string;
  classification: ProjectClassification | string;
  current_version: number;
  created_at: string;
  updated_at: string;
  versions: FileVersionOut[];
}

export interface FileUploadOutcomeItem {
  filename: string;
  outcome: "created" | "new_version" | "duplicate";
  message: string;
  duplicate_of_file_id: string | null;
  duplicate_of_filename: string | null;
  file: ProjectFileOut;
}

export interface ProjectFilesUploadResponse {
  project_id: string;
  created_count: number;
  new_version_count: number;
  duplicate_count: number;
  items: FileUploadOutcomeItem[];
  classification: string;
}

export interface ProjectFileListResponse {
  project_id: string;
  files: ProjectFileOut[];
  total: number;
  classification: string;
}

export type TaskComplexity = "fast" | "deep";

export interface ProviderModelOption {
  id: string;
  label: string;
  tier: string;
}

export interface ProviderCatalogItem {
  id: string;
  name: string;
  models: ProviderModelOption[];
}

export interface ModelSelection {
  fast: string;
  deep: string;
}

export interface UsageLimits {
  daily_request_limit: number;
  daily_token_limit: number;
  monthly_request_limit: number;
  monthly_token_limit: number;
  max_output_tokens: number;
}

export interface DailyUsageOut {
  date_utc: string;
  requests: number;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface MonthlyUsageOut {
  month_utc: string;
  requests: number;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface ConnectionCheckStatus {
  status: "untested" | "connected" | "error";
  checked_at: string | null;
  model: string | null;
  message: string | null;
  latency_ms: number | null;
}

export interface ProviderSettingsOut {
  active_provider: string;
  available_providers: ProviderCatalogItem[];
  models: ModelSelection;
  models_source: "live_api" | "fallback_catalog";
  models_refreshed_at: string | null;
  model_warning: string | null;
  usage_limits: UsageLimits;
  daily_usage: DailyUsageOut;
  monthly_usage: MonthlyUsageOut;
  api_key_configured: boolean;
  credential_backend: string;
  last_connection_check: ConnectionCheckStatus;
  consumer_subscription_notice: string;
  classification: string;
}

export interface ProviderSettingsUpdate {
  active_provider: string;
  models: ModelSelection;
  usage_limits: UsageLimits;
}

export interface TokenUsageOut {
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  thoughts_tokens: number;
  cached_tokens: number;
}

export interface ConnectionTestOut {
  connected: boolean;
  provider: string;
  model: string;
  message: string;
  latency_ms: number;
  usage: TokenUsageOut;
  daily_usage: DailyUsageOut;
  monthly_usage: MonthlyUsageOut;
  api_key_configured: boolean;
  classification: string;
}
