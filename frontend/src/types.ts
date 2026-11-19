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

export type AssignmentLanguage = "ar" | "en" | "mixed";

export type InputFileStatus = "attached" | "missing" | "referenced_in_prompt";

export interface IdentifiedInputFile {
  filename: string;
  role: string;
  status: InputFileStatus;
}

export interface OrchestratorUnderstanding {
  language_detected: AssignmentLanguage;
  restated_assignment: string;
  primary_discipline: string;
  secondary_disciplines: string[];
  expected_deliverables: string[];
  input_files: IdentifiedInputFile[];
  applicable_standards_to_verify: string[];
  missing_information: string[];
  assumptions: string[];
  clarification_needed: boolean;
  clarifying_questions: string[];
  recommended_next_steps: string[];
  suggested_classification: ProjectClassification;
}

export interface AttachedFileSummary {
  file_id: string;
  filename: string;
  folder_name: string;
  extension: string | null;
  mime_type: string | null;
  size_bytes: number;
  sha256: string | null;
  current_version: number;
}

export interface TaskTokenUsageOut {
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  thoughts_tokens: number;
  cached_tokens: number;
  latency_ms: number;
}

export interface TaskStepOut {
  id: string;
  task_id: string;
  step_order: number;
  module_name: string;
  title: string;
  status: string;
  input_payload: Record<string, unknown> | null;
  output_payload: Record<string, unknown> | null;
  notes: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface TaskLogEntryOut {
  id: string;
  action: string;
  entity_type: string;
  actor: string;
  details_json: Record<string, unknown> | null;
  created_at: string;
}

export interface TaskCreateRequest {
  project_id: string;
  prompt: string;
  title?: string | null;
  complexity?: TaskComplexity;
  task_type?: string;
  attached_file_ids?: string[];
  classification?: ProjectClassification;
}

export interface TaskSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  title: string;
  prompt: string;
  task_type: string;
  status: string;
  classification: ProjectClassification | string;
  complexity: string | null;
  provider_name: string | null;
  model_name: string | null;
  plan_summary: string | null;
  result_summary: string | null;
  error_message: string | null;
  attached_file_ids: string[];
  structured_output: OrchestratorUnderstanding | null;
  token_usage: TaskTokenUsageOut;
  step_count: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskDetailOut extends TaskSummaryOut {
  attached_files: AttachedFileSummary[];
  steps: TaskStepOut[];
  logs: TaskLogEntryOut[];
}

export interface TaskListResponse {
  tasks: TaskSummaryOut[];
  total: number;
  classification: ProjectClassification | string;
}

export interface OcrCapabilityOut {
  installed: boolean;
  status: string;
  version: string | null;
  languages: string[];
  ara_installed: boolean;
  eng_installed: boolean;
  install_url: string;
  message: string;
}

export interface ExtractionCapabilitiesOut {
  ocr: OcrCapabilityOut;
  supported_extensions: string[];
  cad_bim_deferred_extensions: string[];
  classification: ProjectClassification | string;
}

export interface ExtractedItem {
  item_index: number;
  item_type: "text" | "table" | "cell_formula" | "slide_note" | "image_meta" | "ocr_text";
  source_file: string;
  file_id: string | null;
  version_number: number;
  page_or_sheet: string;
  location: string;
  text: string | null;
  raw_values: string[][] | null;
  formula: string | null;
  cached_value: string | null;
  unit_or_format: string | null;
  extraction_method: "native" | "ocr" | "hybrid";
}

export interface ExtractionCounts {
  pages: number;
  sheets: number;
  slides: number;
  tables: number;
  formulas: number;
  text_items: number;
  ocr_items: number;
  rendered_page_images: number;
  total_items: number;
}

export interface FileExtractionSummaryOut {
  id: string;
  project_id: string;
  file_id: string;
  source_file: string;
  folder_name: string;
  extension: string;
  version_number: number;
  extraction_version: number;
  source_sha256: string;
  sha256_before: string;
  sha256_after: string;
  original_unchanged: boolean;
  status: "extracted" | "partial_ocr_unavailable" | "failed";
  ocr_status: string;
  classification: ProjectClassification | string;
  counts: ExtractionCounts;
  warnings: string[];
  rendered_page_images: string[];
  artifact_relative_path: string | null;
  error_message: string | null;
  created_at: string;
}

export interface FileExtractionDetailOut extends FileExtractionSummaryOut {
  ocr: OcrCapabilityOut;
  items: ExtractedItem[];
}

export interface FileExtractionListResponse {
  file_id: string;
  extractions: FileExtractionSummaryOut[];
  total: number;
  classification: ProjectClassification | string;
}
