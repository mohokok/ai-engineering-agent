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

export interface OdaCapabilityOut {
  installed: boolean;
  status: string;
  version: string | null;
  install_url: string;
  message: string;
}

export interface FormatSupportEntry {
  extension: string;
  category: string;
  support_level: "native" | "converted_via_oda" | "stored_read_only" | "not_supported";
  provider_or_tool: string;
  notes: string;
}

export interface ExtractionCapabilitiesOut {
  ocr: OcrCapabilityOut;
  oda?: OdaCapabilityOut;
  format_support_matrix?: FormatSupportEntry[];
  supported_extensions: string[];
  cad_bim_deferred_extensions: string[];
  classification: ProjectClassification | string;
}

export type PageStatus = "text" | "ocr_text" | "ocr_empty_or_blank" | "failed";

export interface PageReconciliationOut {
  total_pages: number;
  page_items_count: number;
  reconciled: boolean;
  status_counts: Record<string, number>;
  blank_pages: number[];
  failed_pages: number[];
  unreliable_native_pages: number[];
  low_confidence_pages: number[];
  low_confidence_threshold: number;
}

export interface ExtractedItem {
  item_index: number;
  item_type:
    | "text"
    | "table"
    | "cell_formula"
    | "slide_note"
    | "image_meta"
    | "ocr_text"
    | "cad_layer"
    | "cad_block"
    | "cad_entity"
    | "cad_dimension"
    | "cad_polyline_area"
    | "bim_space"
    | "bim_element"
    | "vision_summary";
  source_file: string;
  file_id: string | null;
  version_number: number;
  page_or_sheet: string;
  location: string;
  text: string | null;
  raw_text?: string | null;
  raw_values: string[][] | null;
  raw_uncollapsed_values?: string[][] | null;
  normalization_applied?: string | null;
  formula: string | null;
  cached_value: string | null;
  unit_or_format: string | null;
  ocr_dpi?: number | null;
  start_row?: number | null;
  start_column?: number | null;
  start_column_letter?: string | null;
  row_numbers?: number[] | null;
  layer?: string | null;
  raw_layer?: string | null;
  block_name?: string | null;
  raw_block_name?: string | null;
  entity_handle?: string | null;
  cad_space?: string | null;
  area?: number | null;
  perimeter_or_length?: number | null;
  properties?: Record<string, unknown> | null;
  quantities?: Record<string, unknown> | null;
  extraction_method: "native" | "ocr" | "converted_oda" | "hybrid" | "ai_vision";
  page_status?: PageStatus | null;
  native_text_unreliable?: boolean;
  native_unreliable_reason?: string | null;
  raw_native_text?: string | null;
  ocr_confidence_mean?: number | null;
  ocr_low_confidence?: boolean;
  page_error?: string | null;
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
  layers?: number;
  blocks?: number;
  block_inserts?: number;
  entities?: number;
  dimensions?: number;
  polylines?: number;
  closed_areas?: number;
  ifc_spaces?: number;
  ifc_walls?: number;
  ifc_doors?: number;
  ifc_windows?: number;
  total_items: number;
}

export interface DrawingVisionSummaryOut {
  extraction_id: string;
  page_number: number;
  ai_interpretation_only: boolean;
  disclaimer: string;
  provider_name: string;
  model_name: string;
  drawing_title: string | null;
  discipline_guess: string;
  visible_labels_and_notes: string[];
  key_elements_observed: string[];
  uncertainty_notes: string[];
  token_usage: Record<string, number>;
  artifact_relative_path: string;
  classification: ProjectClassification | string;
}

export type CadUnitChoice =
  | "unitless"
  | "mm"
  | "cm"
  | "dm"
  | "m"
  | "km"
  | "in"
  | "ft"
  | "yd"
  | "mi";

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
  ocr_dpi?: number | null;
  converter_status?: string | null;
  converted_artifact_relative_path?: string | null;
  cad_units?: string | null;
  units_doubtful?: boolean;
  units_status?: string | null;
  owner_confirmed_unit?: string | null;
  drawing_inventory?: Record<string, unknown> | null;
  vision_summaries?: DrawingVisionSummaryOut[];
  classification: ProjectClassification | string;
  counts: ExtractionCounts;
  page_reconciliation?: PageReconciliationOut | null;
  warnings: string[];
  rendered_page_images: string[];
  artifact_relative_path: string | null;
  error_message: string | null;
  created_at: string;
}

export interface FileExtractionDetailOut extends FileExtractionSummaryOut {
  ocr: OcrCapabilityOut;
  oda?: OdaCapabilityOut | null;
  items: ExtractedItem[];
}

export interface FileExtractionListResponse {
  file_id: string;
  extractions: FileExtractionSummaryOut[];
  total: number;
  classification: ProjectClassification | string;
}

export type SourcePriorityTier =
  | "official_regulations"
  | "standards_bodies"
  | "government"
  | "manufacturer"
  | "peer_reviewed"
  | "reputable"
  | "unverified";

export type SearchProviderName =
  | "duckduckgo_lite"
  | "crossref"
  | "tavily"
  | "serper"
  | "brave";

export interface SearchProviderOptionOut {
  id: SearchProviderName;
  label: string;
  requires_api_key: boolean;
  key_configured: boolean;
  is_default: boolean;
  pricing_summary: string;
  notes: string;
}

export interface ResearchCapabilitiesOut {
  default_provider: SearchProviderName;
  search_providers: SearchProviderOptionOut[];
  source_priority_order: SourcePriorityTier[];
  snippets_never_evidence: boolean;
  untrusted_page_isolation: boolean;
  classification: ProjectClassification | string;
}

export interface ResearchVerifiedFinding {
  claim: string;
  source_name: string;
  source_url: string;
  publication_date: string | null;
  priority_tier: SourcePriorityTier;
}

export interface ResearchSynthesisPayload {
  summary: string;
  verified_findings: ResearchVerifiedFinding[];
  unreviewed_or_inaccessible: string[];
  standards_and_gaps: string[];
  injection_attempts_ignored: string[];
  assumptions: string[];
  suggested_classification: ProjectClassification | string;
}

export type PublicationDateKind = "published" | "http_last_modified" | "unknown";

export interface ResearchSourceOut {
  id: string;
  research_run_id: string | null;
  project_id: string | null;
  task_id: string | null;
  source_name: string;
  url: string;
  publication_date: string | null;
  publication_date_kind?: PublicationDateKind;
  access_date: string;
  query_text: string | null;
  extracted_info: string | null;
  reliability_rating: string;
  source_type: string;
  source_priority_tier: SourcePriorityTier | string;
  priority_rank: number;
  tier_is_provider_claim?: boolean;
  tier_claim_label?: string | null;
  access_status: "accessible" | "owner_provided" | "inaccessible" | "not_relevant" | "partial" | string;
  reviewed: boolean;
  http_status: number | null;
  failure_reason: string | null;
  untrusted_neutralized: boolean;
  created_at: string;
}

export interface ResearchRunSummaryOut {
  id: string;
  project_id: string | null;
  task_id: string | null;
  query: string;
  search_provider: string;
  classification: ProjectClassification | string;
  status: string;
  summary: string | null;
  error_message: string | null;
  total_sources: number;
  accessible_sources: number;
  owner_provided_sources?: number;
  inaccessible_sources: number;
  not_relevant_sources?: number;
  estimated_prompt_tokens?: number;
  prompt_char_count?: number;
  prompt_char_cap?: number;
  step04_daily_tokens_remaining?: number | null;
  step04_monthly_tokens_remaining?: number | null;
  token_usage: TaskTokenUsageOut;
  artifact_relative_path: string | null;
  created_at: string;
}

export interface ResearchRunDetailOut extends ResearchRunSummaryOut {
  structured_output: ResearchSynthesisPayload | null;
  sources: ResearchSourceOut[];
}

export interface ResearchHistoryListResponse {
  runs: ResearchRunSummaryOut[];
  total: number;
  classification: ProjectClassification | string;
}

export interface ResearchSourceListResponse {
  sources: ResearchSourceOut[];
  total: number;
  classification: ProjectClassification | string;
}

export interface OwnerProvidedSourceInput {
  file_id: string;
  priority_tier: SourcePriorityTier;
  publication_date?: string | null;
}

export interface ResearchRunCreateRequest {
  query: string;
  project_id?: string | null;
  task_id?: string | null;
  urls?: string[];
  owner_files?: OwnerProvidedSourceInput[];
  search_provider?: SearchProviderName;
  max_results?: number;
  complexity?: TaskComplexity;
  classification?: ProjectClassification;
  synthesize_with_ai?: boolean;
}

export type ReportLanguage = "ar" | "en";
export type FindingSeverity = "critical" | "high" | "medium" | "low" | "info";
export type FindingStatus = "open" | "needs_verification" | "resolved";
export type StatementCategory =
  | "verified_fact"
  | "calculated"
  | "ocr_unverified"
  | "assumption"
  | "recommendation";

export interface DocumentRegisterEntry {
  file_name: string;
  file_type: string;
  pages_or_entities: string;
  extraction_status: string;
  confidence: string;
}

export interface OcrExtractedTextItem {
  file_id?: string | null;
  source_file: string;
  page_or_sheet: string;
  confidence_mean?: number | null;
  low_confidence: boolean;
  native_text_unreliable: boolean;
  status_label: string;
  text: string;
  source_links: SourceLocationRef[];
}

export interface SourceLocationRef {
  ref_id: string;
  source_kind: "extraction" | "research_source" | string;
  source_id: string;
  file_id?: string | null;
  extraction_id?: string | null;
  research_run_id?: string | null;
  url?: string | null;
  source_name: string;
  page_or_sheet: string;
  location: string;
  excerpt?: string | null;
}

export interface ReviewFinding {
  finding_id: string;
  discipline: string;
  severity: FindingSeverity | string;
  location_or_drawing_ref: string;
  evidence: string;
  recommendation: string;
  status: FindingStatus | string;
  statement_category: StatementCategory | string;
  source_links: SourceLocationRef[];
}

export interface CategorizedStatement {
  category: StatementCategory | string;
  text: string;
  formula_or_method?: string | null;
  source_links: SourceLocationRef[];
}

export interface RevisionBlockOut {
  version: number;
  revision: string;
  classification: ProjectClassification | string;
  prepared_by: string;
  review_notice: string;
  issued_at_iso: string;
  change_note: string;
  source_files_count: number;
  reviewed_research_count: number;
}

export interface DeliverableOut {
  id: string;
  project_id: string;
  report_id?: string | null;
  boq_id?: string | null;
  task_id?: string | null;
  file_id?: string | null;
  title: string;
  deliverable_type: string;
  discipline: string;
  format: string;
  classification: ProjectClassification | string;
  status: string;
  version: number;
  folder_name?: string | null;
  filename?: string | null;
  relative_path?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  sha256?: string | null;
  summary?: string | null;
  download_url: string;
  created_at: string;
  updated_at: string;
}

export interface DeliverableListResponse {
  deliverables: DeliverableOut[];
  total: number;
  classification: ProjectClassification | string;
}

export interface ReviewReportSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  title: string;
  discipline: string;
  language: ReportLanguage | string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  status: string;
  summary?: string | null;
  findings_count: number;
  estimated_prompt_tokens?: number;
  prompt_char_count?: number;
  prompt_char_cap?: number;
  step04_daily_tokens_remaining?: number | null;
  step04_monthly_tokens_remaining?: number | null;
  token_usage: TaskTokenUsageOut;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReviewReportDetailOut extends ReviewReportSummaryOut {
  is_inventory_only?: boolean;
  revision_block: RevisionBlockOut;
  document_register?: DocumentRegisterEntry[];
  findings: ReviewFinding[];
  verified_facts: CategorizedStatement[];
  verified_facts_total?: number;
  verified_facts_shown?: number;
  appendix_verified_facts?: CategorizedStatement[];
  ocr_text_items?: OcrExtractedTextItem[];
  ocr_text_items_total?: number;
  calculated_items: CategorizedStatement[];
  assumptions: CategorizedStatement[];
  recommendations: CategorizedStatement[];
  gaps_or_unextracted: string[];
  source_registry: SourceLocationRef[];
  deliverables: DeliverableOut[];
}

export interface ReviewReportListResponse {
  reports: ReviewReportSummaryOut[];
  total: number;
  classification: ProjectClassification | string;
}

export interface ReviewReportGenerateRequest {
  task_id?: string | null;
  file_ids?: string[];
  research_run_ids?: string[];
  title?: string | null;
  discipline?: string;
  language?: ReportLanguage;
  classification?: ProjectClassification;
  review_notes?: string | null;
  change_note?: string;
  use_ai?: boolean;
  complexity?: TaskComplexity;
}

export type BoqVerificationStatus =
  | "Extracted-Verified"
  | "Extracted-Needs-Check"
  | "Manual";

export type BoqRateSourceKind = "owner_input" | "dated_research";

export type BoqCheckType =
  | "duplicate_item"
  | "missing_item"
  | "unit_consistency"
  | "arithmetic_total"
  | "unverified_unit"
  | "rate_provenance";

export interface BoqCheckIssue {
  issue_id: string;
  check_type: BoqCheckType;
  severity: "high" | "medium" | "info";
  item_id?: string | null;
  item_no?: string | null;
  message: string;
  recommended_action: string;
}

export interface BoqFlaggedItem {
  item_id: string;
  item_no: string;
  description: string;
  unit: string;
  quantity: number;
  verification_status: BoqVerificationStatus;
  reason: string;
}

export interface BoqChecksSummaryOut {
  total_items: number;
  verified_items_count: number;
  needs_check_items_count: number;
  manual_items_count: number;
  priced_items_count: number;
  unpriced_items_count: number;
  verified_priced_subtotal: number;
  needs_check_priced_subtotal: number;
  grand_total: number;
  issues_count: number;
  high_issues_count: number;
  issues: BoqCheckIssue[];
  flagged_item_ids: string[];
  flagged_items: BoqFlaggedItem[];
}

export interface BoqItemOut {
  id: string;
  boq_sheet_id: string;
  row_order: number;
  item_no: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate?: number | null;
  total?: number | null;
  reported_total?: number | null;
  technical_reference?: string | null;
  drawing_reference?: string | null;
  remarks?: string | null;
  verification_status: BoqVerificationStatus;
  rate_source_kind?: BoqRateSourceKind | null;
  rate_source_ref?: string | null;
  rate_source_date?: string | null;
  source_file_id?: string | null;
  source_extraction_id?: string | null;
  discipline?: string | null;
  layer_or_category?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BoqSheetSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  title: string;
  language: ReportLanguage | string;
  currency: string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  export_version: number;
  source_scope: string;
  status: string;
  summary?: string | null;
  items_count: number;
  grand_total: number;
  issues_count: number;
  high_issues_count: number;
  created_at: string;
  updated_at: string;
}

export interface BoqDetailOut extends BoqSheetSummaryOut {
  checks: BoqChecksSummaryOut;
  items: BoqItemOut[];
  deliverables: DeliverableOut[];
  source_metadata: Record<string, unknown>;
}

export interface BoqListResponse {
  sheets: BoqSheetSummaryOut[];
  total: number;
  classification: ProjectClassification | string;
}

export interface BoqExportOut {
  boq: BoqDetailOut;
  xlsx_deliverable: DeliverableOut;
  csv_deliverable: DeliverableOut;
}

export interface BoqSheetCreateRequest {
  title?: string | null;
  language?: ReportLanguage;
  currency?: string;
  classification?: ProjectClassification;
  file_ids?: string[];
  include_dxf_ifc?: boolean;
  include_boq_imports?: boolean;
  task_id?: string | null;
}

export interface BoqItemCreateRequest {
  item_no?: string;
  description: string;
  unit?: string;
  quantity: number;
  unit_rate?: number | null;
  technical_reference?: string | null;
  drawing_reference?: string | null;
  remarks?: string | null;
  verification_status?: BoqVerificationStatus;
  rate_source_kind?: BoqRateSourceKind | null;
  rate_source_ref?: string | null;
  rate_source_date?: string | null;
}

export interface BoqItemUpdateRequest {
  item_no?: string | null;
  description?: string | null;
  unit?: string | null;
  quantity?: number | null;
  unit_rate?: number | null;
  clear_rate?: boolean;
  technical_reference?: string | null;
  drawing_reference?: string | null;
  remarks?: string | null;
  verification_status?: BoqVerificationStatus | null;
  rate_source_kind?: BoqRateSourceKind | null;
  rate_source_ref?: string | null;
  rate_source_date?: string | null;
}
