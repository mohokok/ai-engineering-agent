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
  verification_status?: string;
  last_qa_review_id?: string | null;
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
  drawing_id?: string | null;
  calculation_id?: string | null;
  specification_id?: string | null;
  comparison_id?: string | null;
  schedule_id?: string | null;
  assessment_id?: string | null;
  structural_id?: string | null;
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

export type PaperSizeChoice = "A3" | "A4" | "A2" | "A1";

export interface RoomSpec {
  room_id: string;
  name_ar: string;
  name_en: string;
  x_mm?: number | null;
  y_mm?: number | null;
  width_mm?: number | null;
  height_mm?: number | null;
  polygon_mm?: [number, number][] | null;
  floor_finish?: string;
  wall_finish?: string;
  ceiling_finish?: string;
  skirting?: string;
}

export interface WallSpec {
  wall_id: string;
  start_mm: [number, number];
  end_mm: [number, number];
  thickness_mm?: number;
  wall_type?: "exterior" | "interior";
}

export interface DoorSpec {
  door_id: string;
  mark: string;
  position_mm: [number, number];
  width_mm: number;
  height_mm?: number;
  angle_deg?: number;
  swing?: "left" | "right";
  swing_side?: "in" | "out";
  material?: string;
  fire_rating?: string;
  hardware?: string;
  room_ref?: string;
}

export interface WindowSpec {
  window_id: string;
  mark: string;
  position_mm: [number, number];
  width_mm: number;
  height_mm?: number;
  sill_mm?: number;
  angle_deg?: number;
  glazing?: string;
  room_ref?: string;
}

export interface ParametricPlanModel {
  units: "mm";
  north_angle_deg: number;
  rooms: RoomSpec[];
  walls: WallSpec[];
  doors: DoorSpec[];
  windows: WindowSpec[];
}

export interface ComputedRoomMetric {
  room_id: string;
  name_ar: string;
  name_en: string;
  polygon_mm: [number, number][];
  area_mm2: number;
  area_m2: number;
  perimeter_mm: number;
  perimeter_m: number;
  centroid_mm: [number, number];
  floor_finish: string;
  wall_finish: string;
  ceiling_finish: string;
  skirting: string;
}

export interface DoorScheduleRow {
  mark: string;
  width_mm: number;
  height_mm: number;
  swing: string;
  material: string;
  fire_rating: string;
  hardware: string;
  count: number;
  door_ids: string[];
  room_refs: string[];
}

export interface WindowScheduleRow {
  mark: string;
  width_mm: number;
  height_mm: number;
  sill_mm: number;
  glazing: string;
  count: number;
  window_ids: string[];
  room_refs: string[];
}

export interface RoundTripCheckOut {
  passed: boolean;
  insunits_code: number;
  units: string;
  units_doubtful: boolean;
  ttf_font_styles: string[];
  uses_shx_font: boolean;
  expected_room_count: number;
  extracted_area_contour_count: number;
  expected_total_area_m2: number;
  extracted_total_area_m2: number;
  area_diff_m2: number;
  expected_doors_count: number;
  extracted_doors_count: number;
  expected_windows_count: number;
  extracted_windows_count: number;
  mismatches: string[];
}

export interface ParametricDrawingGenerateRequest {
  task_id?: string | null;
  drawing_no: string;
  title: string;
  scale_denominator: number;
  paper_size: PaperSizeChoice;
  classification: ProjectClassification;
  notes?: string | null;
  ai_suggested: boolean;
  owner_confirmed_model: boolean;
  plan_model: ParametricPlanModel;
}

export interface ParametricModelSuggestOut {
  requires_owner_confirmation: boolean;
  message: string;
  plan_model: ParametricPlanModel;
  tokens_used: number;
}

export interface ParametricDrawingDetailOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  drawing_no: string;
  title: string;
  scale_denominator: number;
  scale_label: string;
  paper_size: string;
  units: string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  status: string;
  notes?: string | null;
  round_trip_passed: boolean;
  ai_suggested: boolean;
  plan_model: ParametricPlanModel;
  rooms_computed: ComputedRoomMetric[];
  total_area_m2: number;
  door_schedule: DoorScheduleRow[];
  window_schedule: WindowScheduleRow[];
  round_trip_check: RoundTripCheckOut;
  deliverables: DeliverableOut[];
  created_at: string;
  updated_at: string;
}

export interface ParametricDrawingListResponse {
  drawings: ParametricDrawingDetailOut[];
  total: number;
  classification: ProjectClassification | string;
}

export type IssueSeverity = "critical" | "high" | "medium" | "low" | "info";
export type IssueStatus = "open" | "in_review" | "closed";
export type IssueCategory =
  | "arithmetic"
  | "unit"
  | "reference"
  | "schedule_consistency"
  | "missing_deliverable"
  | "integrity"
  | "manual"
  | "general";

export interface QaCheckMetricOut {
  category: IssueCategory;
  checked_count: number;
  failed_count: number;
  passed: boolean;
  details: string;
}

export interface QaContextIsolationReport {
  producer_reasoning_excluded: boolean;
  excluded_fields: string[];
  inspected_boq_ids: string[];
  inspected_drawing_ids: string[];
  inspected_report_ids: string[];
  inspected_calculation_ids?: string[];
  inspected_specification_ids?: string[];
  inspected_comparison_ids?: string[];
  inspected_schedule_ids?: string[];
  inspected_standard_ids?: string[];
  inspected_assessment_ids?: string[];
  inspected_structural_ids?: string[];
  inspected_deliverable_ids: string[];
  inspected_extraction_ids: string[];
  inspected_research_source_count: number;
  expected_task_deliverables: string[];
}

export interface IssueOut {
  id: string;
  project_id: string;
  task_id?: string | null;
  deliverable_id?: string | null;
  qa_review_id?: string | null;
  issue_number: string;
  title?: string | null;
  description: string;
  discipline: string;
  severity: IssueSeverity | string;
  check_category: IssueCategory | string;
  reference?: string | null;
  corrective_action?: string | null;
  recommended_action?: string | null;
  status: IssueStatus | string;
  closure_note?: string | null;
  closed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IssueListResponse {
  issues: IssueOut[];
  total: number;
  open_count: number;
  closed_count: number;
}

export interface QaReviewDetailOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  task_verification_status?: string | null;
  classification: ProjectClassification | string;
  status: string;
  producer_reasoning_excluded: boolean;
  qa_context_summary: QaContextIsolationReport;
  checks: QaCheckMetricOut[];
  issues_opened_count: number;
  open_issues_count: number;
  tokens_used: number;
  issues: IssueOut[];
  created_at: string;
}

export interface QaReviewListResponse {
  reviews: QaReviewDetailOut[];
  total: number;
}

export interface TaskVerifyOut {
  task_id: string;
  verification_status: string;
  qa_review_id: string;
  open_issues_count: number;
  message: string;
}

export type CalculationDiscipline = "electrical" | "plumbing";
export type CalculationType =
  | "electrical_load_schedule"
  | "electrical_cable_sizing"
  | "electrical_voltage_drop"
  | "plumbing_water_demand"
  | "plumbing_pipe_sizing";
export type CalculationReferenceKind = "owner_supplied" | "verified_source_log";

export interface CalculationReferenceIn {
  source_kind: CalculationReferenceKind;
  source_name: string;
  source_ref: string;
  research_source_id?: string | null;
  publication_date?: string | null;
  notes?: string | null;
}

export interface CalculationReferenceOut extends CalculationReferenceIn {
  verification_label: string;
}

export interface CalculationSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  title: string;
  discipline: CalculationDiscipline | string;
  calculation_type: CalculationType | string;
  language: ReportLanguage | string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  export_version: number;
  status: string;
  acceptance_passed: boolean;
  data_provenance?: string;
  acceptance_outcome_label?: string;
  tokens_used: number;
  created_at: string;
  updated_at: string;
}

export interface CalculationDetailOut extends CalculationSummaryOut {
  inputs: Record<string, unknown>;
  units: Record<string, string>;
  equations: string;
  method: string;
  assumptions: string[];
  assumptions_text: string;
  results: Record<string, unknown>;
  acceptance_criteria: string[];
  acceptance_criteria_text: string;
  references: CalculationReferenceOut[];
  references_text: string;
  deliverables: DeliverableOut[];
}

export interface CalculationListResponse {
  calculations: CalculationSummaryOut[];
  total: number;
}

export interface CalculationExportOut {
  calculation: CalculationDetailOut;
  docx_deliverable: DeliverableOut;
  pdf_deliverable: DeliverableOut;
  xlsx_deliverable: DeliverableOut;
}

export interface CalculationPresetOut {
  calculation_type: CalculationType;
  discipline: CalculationDiscipline;
  title_en: string;
  title_ar: string;
  inputs: Record<string, unknown>;
  default_reference: CalculationReferenceIn;
}

export interface CalculationPresetListResponse {
  presets: CalculationPresetOut[];
}

export type SpecPartKey =
  | "scope"
  | "standards"
  | "materials"
  | "execution"
  | "testing"
  | "acceptance"
  | "submittals"
  | "warranty";

export type SpecDraftStatus = "not_used" | "unverified_ai_draft" | "owner_approved";

export interface SpecTraceRef {
  trace_id: string;
  trace_kind: "boq_item" | "drawing" | "drawing_schedule" | "research_source";
  boq_sheet_id?: string | null;
  boq_item_id?: string | null;
  boq_item_no?: string | null;
  drawing_id?: string | null;
  drawing_no?: string | null;
  schedule_kind?: string | null;
  research_source_id?: string | null;
  source_url?: string | null;
  label: string;
}

export interface SpecClause {
  clause_id: string;
  part: SpecPartKey | string;
  text: string;
  draft_origin: "deterministic_template" | "ai_unverified_draft" | "owner_approved" | string;
  trace_refs: SpecTraceRef[];
}

export interface SpecStandardCitation {
  research_source_id?: string | null;
  source_name: string;
  url: string;
  publication_date?: string | null;
  status: "verified_source_log" | "no_verified_standard_on_file" | string;
  citation_text: string;
  verification_label: string;
}

export interface SpecSection {
  section_code: string;
  title: string;
  discipline: string;
  mapped_boq_item_ids: string[];
  mapped_drawing_ids: string[];
  mapped_drawing_refs: string[];
  standards: SpecStandardCitation[];
  clauses: SpecClause[];
  missing_parts: string[];
}

export interface SpecificationSummaryOut {
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
  export_version: number;
  status: string;
  use_ai: boolean;
  ai_draft_status: SpecDraftStatus | string;
  ai_draft_label: string;
  owner_approved_by?: string | null;
  owner_approved_at?: string | null;
  sections_count: number;
  clauses_count: number;
  tokens_used: number;
  summary?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SpecificationDetailOut extends SpecificationSummaryOut {
  source_boq_sheet_ids: string[];
  source_drawing_ids: string[];
  source_research_ids: string[];
  missing_standards_notices: string[];
  sections: SpecSection[];
  token_usage: TaskTokenUsageOut;
  deliverables: DeliverableOut[];
}

export interface SpecificationListResponse {
  specifications: SpecificationSummaryOut[];
  total: number;
}

export interface SpecificationExportOut {
  specification: SpecificationDetailOut;
  docx_deliverable: DeliverableOut;
  pdf_deliverable: DeliverableOut;
}

export interface SpecificationPresetOut {
  key: string;
  title_en: string;
  title_ar: string;
  description_en: string;
  description_ar: string;
  discipline: string;
  boq_items: Array<Record<string, unknown>>;
  drawing_summary: Record<string, unknown>;
  reviewed_source: Record<string, unknown>;
  request_defaults: {
    title?: string | null;
    discipline: string;
    language: ReportLanguage;
    classification: ProjectClassification;
    use_ai: boolean;
  };
}

export interface SpecificationPresetListResponse {
  presets: SpecificationPresetOut[];
}

export type ComparisonScope = "equipment" | "material" | "vendor_offer" | "system_alternative";
export type ComparisonCategory =
  | "compliance"
  | "performance"
  | "safety"
  | "durability"
  | "energy"
  | "maintainability"
  | "constructability"
  | "initial_cost"
  | "operating_cost"
  | "lifecycle_cost"
  | "risks";
export type ScoringDirection = "higher_better" | "lower_better" | "boolean_pass" | "direct_score_0_100";
export type ComparisonSourceKind =
  | "boq_item"
  | "specification"
  | "calculation"
  | "research_source"
  | "owner_entered";
export type ComparisonDraftStatus = "not_used" | "unverified_ai_draft" | "owner_approved";
export type OwnerDecisionStatus = "pending_owner_decision" | "owner_selected";
export type UnitCheckStatus = "exact" | "converted_explicitly" | "flagged_mismatch" | "not_applicable";

export interface ComparisonCriterionIn {
  criterion_id: string;
  category: ComparisonCategory;
  label: string;
  weight: string | number;
  is_mandatory: boolean;
  direction: ScoringDirection;
  target_unit: string;
  mandatory_min?: number | null;
  mandatory_max?: number | null;
  mandatory_expected_bool?: boolean | null;
  source_kind: ComparisonSourceKind;
  source_ref: string;
  boq_item_id?: string | null;
  specification_id?: string | null;
  calculation_id?: string | null;
  research_source_id?: string | null;
}

export interface ComparisonCellIn {
  criterion_id: string;
  value?: number | string | boolean | null;
  unit?: string | null;
  source_kind: ComparisonSourceKind;
  source_ref?: string | null;
  boq_item_id?: string | null;
  specification_id?: string | null;
  calculation_id?: string | null;
  research_source_id?: string | null;
  notes?: string | null;
}

export interface ComparisonOptionIn {
  option_id: string;
  name: string;
  vendor_or_source: string;
  risks: string[];
  cells: ComparisonCellIn[];
}

export interface EvaluatedCellOut {
  criterion_id: string;
  category: ComparisonCategory | string;
  label: string;
  weight: number;
  is_mandatory: boolean;
  raw_value?: number | string | boolean | null;
  display_value: string;
  raw_unit: string;
  target_unit: string;
  converted_value?: string | null;
  unit_status: UnitCheckStatus | string;
  conversion_note?: string | null;
  is_missing: boolean;
  mandatory_passed?: boolean | null;
  normalized_score: number;
  weighted_score: number;
  source_kind: ComparisonSourceKind | string;
  source_ref: string;
  boq_item_id?: string | null;
  specification_id?: string | null;
  calculation_id?: string | null;
  research_source_id?: string | null;
  notes?: string | null;
}

export interface EvaluatedOptionOut {
  option_id: string;
  name: string;
  vendor_or_source: string;
  advisory_rank: number;
  total_weighted_score: number;
  mandatory_passed: boolean;
  failed_mandatory_criteria: string[];
  missing_values_count: number;
  unit_mismatch_count: number;
  risks: string[];
  cells: EvaluatedCellOut[];
}

export interface ComparisonMatrixOut {
  total_weight: number;
  weights_sum_valid: boolean;
  advisory_notice: string;
  leading_option_id?: string | null;
  leading_option_name?: string | null;
  unit_mismatch_flags: string[];
  missing_mandatory_flags: string[];
  options: EvaluatedOptionOut[];
}

export interface TechnicalComparisonSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  title: string;
  comparison_scope: ComparisonScope | string;
  discipline: string;
  language: ReportLanguage | string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  export_version: number;
  status: string;
  use_ai: boolean;
  ai_draft_status: ComparisonDraftStatus | string;
  ai_draft_label: string;
  owner_decision_status: OwnerDecisionStatus | string;
  owner_selected_option_id?: string | null;
  owner_decision_note?: string | null;
  owner_decided_by?: string | null;
  owner_decided_at?: string | null;
  total_weight: number;
  criteria_count: number;
  options_count: number;
  tokens_used: number;
  summary?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TechnicalComparisonDetailOut extends TechnicalComparisonSummaryOut {
  criteria: ComparisonCriterionIn[];
  matrix: ComparisonMatrixOut;
  token_usage: TaskTokenUsageOut;
  deliverables: DeliverableOut[];
}

export interface TechnicalComparisonListResponse {
  comparisons: TechnicalComparisonSummaryOut[];
  total: number;
}

export interface TechnicalComparisonExportOut {
  comparison: TechnicalComparisonDetailOut;
  docx_deliverable: DeliverableOut;
  pdf_deliverable: DeliverableOut;
  xlsx_deliverable: DeliverableOut;
}

export interface ComparisonPresetOut {
  key: string;
  title_en: string;
  title_ar: string;
  comparison_scope: ComparisonScope;
  discipline: string;
  lifecycle_years?: number | null;
  criteria: ComparisonCriterionIn[];
  options: ComparisonOptionIn[];
}

export interface ComparisonPresetListResponse {
  presets: ComparisonPresetOut[];
}

export type ScheduleSourceKind =
  | "boq_item"
  | "specification"
  | "calculation"
  | "research_source"
  | "owner_entered";
export type CalendarPresetKey = "libya_sun_thu" | "mon_fri" | "six_day_sat_thu" | "custom";
export type ScheduleDraftStatus = "not_used" | "unverified_ai_draft" | "owner_approved";

export interface WorkCalendarIn {
  preset: CalendarPresetKey;
  weekend_days?: number[] | null;
  holidays: string[];
  hours_per_day: number;
  source_ref: string;
}

export interface WbsItemIn {
  wbs_code: string;
  title: string;
  parent_code?: string | null;
  discipline: string;
}

export interface ActivityDependencyIn {
  predecessor_id: string;
  dep_type: "FS";
  lag_days: number;
}

export interface ScheduleActivityIn {
  activity_id: string;
  wbs_code: string;
  name: string;
  is_milestone: boolean;
  duration_days?: number | null;
  quantity?: number | null;
  unit?: string | null;
  predecessors: ActivityDependencyIn[];
  source_kind: ScheduleSourceKind;
  source_ref: string;
  boq_item_id?: string | null;
  specification_id?: string | null;
  calculation_id?: string | null;
  research_source_id?: string | null;
  notes?: string | null;
}

export interface EvaluatedActivityOut {
  activity_id: string;
  wbs_code: string;
  name: string;
  is_milestone: boolean;
  duration_days?: number | null;
  display_duration: string;
  quantity?: number | null;
  unit: string;
  predecessors: ActivityDependencyIn[];
  early_start_wd?: number | null;
  early_finish_wd?: number | null;
  late_start_wd?: number | null;
  late_finish_wd?: number | null;
  total_float_wd?: number | null;
  planned_start?: string | null;
  planned_finish?: string | null;
  late_start_date?: string | null;
  late_finish_date?: string | null;
  is_critical: boolean;
  cpm_status: "computed" | "blocked_missing_duration" | string;
  branch_block_reason?: string | null;
  baseline_duration_days?: number | null;
  baseline_start?: string | null;
  baseline_finish?: string | null;
  start_variance_wd?: number | null;
  finish_variance_wd?: number | null;
  float_variance_wd?: number | null;
  variance_status: string;
  source_kind: ScheduleSourceKind | string;
  source_ref: string;
  boq_item_id?: string | null;
  specification_id?: string | null;
  calculation_id?: string | null;
  research_source_id?: string | null;
  notes?: string | null;
}

export interface ScheduleResultOut {
  project_start_date: string;
  effective_start_date: string;
  project_finish_date?: string | null;
  total_duration_wd?: number | null;
  calendar_preset: CalendarPresetKey | string;
  calendar_summary: string;
  weekend_days: number[];
  holidays: string[];
  critical_path_complete: boolean;
  critical_path_ids: string[];
  blocked_activity_ids: string[];
  blocked_branch_flags: string[];
  missing_duration_flags: string[];
  milestone_summary: Array<Record<string, unknown>>;
  baseline_schedule_id?: string | null;
  baseline_title?: string | null;
  project_finish_variance_wd?: number | null;
  baseline_comparison_notes: string[];
  activities: EvaluatedActivityOut[];
}

export interface ProjectScheduleSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  baseline_schedule_id?: string | null;
  title: string;
  discipline: string;
  language: ReportLanguage | string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  export_version: number;
  status: string;
  is_baseline: boolean;
  start_date: string;
  use_ai: boolean;
  ai_draft_status: ScheduleDraftStatus | string;
  ai_draft_label: string;
  owner_approved_by?: string | null;
  owner_approved_at?: string | null;
  wbs_count: number;
  activities_count: number;
  total_duration_wd?: number | null;
  critical_path_complete: boolean;
  tokens_used: number;
  summary?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectScheduleDetailOut extends ProjectScheduleSummaryOut {
  calendar: WorkCalendarIn;
  wbs_items: WbsItemIn[];
  schedule_result: ScheduleResultOut;
  token_usage: TaskTokenUsageOut;
  deliverables: DeliverableOut[];
}

export interface ProjectScheduleListResponse {
  schedules: ProjectScheduleSummaryOut[];
  total: number;
}

export interface ProjectScheduleExportOut {
  schedule: ProjectScheduleDetailOut;
  pdf_deliverable: DeliverableOut;
  xlsx_deliverable: DeliverableOut;
}

export interface PlanningPresetOut {
  key: string;
  title_en: string;
  title_ar: string;
  discipline: string;
  start_date: string;
  calendar: WorkCalendarIn;
  wbs_items: WbsItemIn[];
  activities: ScheduleActivityIn[];
}

export interface PlanningPresetListResponse {
  presets: PlanningPresetOut[];
}

export type StandardStatus = "current" | "superseded" | "withdrawn" | "unknown";
export type StandardMetadataStatus =
  | "owner_entered"
  | "unverified_suggestion"
  | "unverified_ai_suggestion"
  | "owner_confirmed";
export type StandardAiSuggestionStatus =
  | "not_used"
  | "unverified_ai_suggestion"
  | "owner_confirmed";

export interface OwnerExcerptIn {
  excerpt_id?: string | null;
  page_ref: string;
  text: string;
}

export interface OwnerExcerptOut {
  excerpt_id: string;
  page_ref: string;
  text: string;
  added_at: string;
}

export interface StandardCitationHitOut {
  module: string;
  artifact_id: string;
  artifact_title: string;
  location: string;
  flagged_status: string;
}

export interface StandardCreatePayload {
  project_id?: string | null;
  standard_number: string;
  title: string;
  issuing_body?: string;
  edition_year?: string;
  status?: StandardStatus;
  superseded_by_id?: string | null;
  supersession_note?: string | null;
  jurisdiction?: string;
  adopted_locally?: boolean;
  owner_notes?: string | null;
  owner_excerpts?: OwnerExcerptIn[];
}

export interface StandardDocumentOut {
  id: string;
  project_id?: string | null;
  standard_number: string;
  title: string;
  issuing_body: string;
  edition_year: string;
  status: StandardStatus | string;
  superseded_by_id?: string | null;
  superseded_by_number?: string | null;
  superseded_by_title?: string | null;
  replacement_chain_summary?: string | null;
  supersession_note?: string | null;
  jurisdiction: string;
  adopted_locally: boolean;
  owner_notes?: string | null;
  owner_excerpts: OwnerExcerptOut[];
  metadata_status: StandardMetadataStatus | string;
  metadata_label: string;
  suggested_metadata?: Record<string, unknown> | null;
  use_ai: boolean;
  ai_suggestion_status: StandardAiSuggestionStatus | string;
  tokens_used: number;
  token_usage: TaskTokenUsageOut;
  original_filename?: string | null;
  file_relative_path?: string | null;
  file_sha256?: string | null;
  file_size_bytes?: number | null;
  mime_type?: string | null;
  version: number;
  history: Array<Record<string, unknown>>;
  where_cited: StandardCitationHitOut[];
  citation_warnings: string[];
  created_at: string;
  updated_at: string;
}

export interface StandardListResponse {
  standards: StandardDocumentOut[];
  total: number;
}

export interface StandardRegisterExportFileOut {
  format: "docx" | "pdf" | "xlsx";
  filename: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
  download_url: string;
}

export interface StandardRegisterExportOut {
  project_id?: string | null;
  language: ReportLanguage | string;
  standards_count: number;
  cited_warnings_count: number;
  files: StandardRegisterExportFileOut[];
}

export interface StandardPresetOut {
  key: string;
  label_en: string;
  label_ar: string;
  standard: StandardCreatePayload;
}

export interface StandardPresetListResponse {
  presets: StandardPresetOut[];
}

export type SpecialistDomain = "hvac" | "fire" | "healthcare";
export type SpecialistWorkflowMode = "input_preparation" | "output_check" | "full_preflight";
export type SpecialistReferenceKind =
  | "standard_library"
  | "verified_source_log"
  | "no_verified_standard_on_file";

export interface SpecialistReferenceIn {
  source_kind: SpecialistReferenceKind;
  standard_library_id?: string | null;
  research_source_id?: string | null;
  citation_note?: string | null;
}

export interface SpecialistReferenceOut {
  source_kind: SpecialistReferenceKind | string;
  standard_library_id?: string | null;
  research_source_id?: string | null;
  code_or_source_name: string;
  edition_or_date: string;
  status: string;
  citation_note?: string | null;
  verification_label: string;
}

export interface SpecialistCheckRowOut {
  item_id: string;
  label: string;
  expected: string;
  actual: string;
  unit: string;
  status: string;
  notes: string;
}

export interface SpecialistResultsOut {
  equations: string[];
  methodology: string;
  prepared_items: Array<Record<string, unknown>>;
  check_rows: SpecialistCheckRowOut[];
  blocked_flags: string[];
  metrics: Record<string, unknown>;
}

export interface SpecialistSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  domain: SpecialistDomain | string;
  workflow_mode: SpecialistWorkflowMode | string;
  title: string;
  language: ReportLanguage | string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  export_version: number;
  status: string;
  checks_passed: boolean;
  blocked_missing_count: number;
  failed_checks_count: number;
  standards_status: string;
  use_ai: boolean;
  ai_draft_status: "not_used" | "unverified_ai_draft" | "owner_approved" | string;
  ai_draft_label: string;
  owner_approved_by?: string | null;
  owner_approved_at?: string | null;
  tokens_used: number;
  preliminary_label: string;
  software_recommendation: string;
  summary?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SpecialistDetailOut extends SpecialistSummaryOut {
  inputs: Record<string, unknown>;
  results: SpecialistResultsOut;
  references: SpecialistReferenceOut[];
  preliminary_assumptions: string[];
  token_usage: TaskTokenUsageOut;
  deliverables: DeliverableOut[];
}

export interface SpecialistListResponse {
  assessments: SpecialistSummaryOut[];
  total: number;
}

export interface SpecialistExportOut {
  assessment: SpecialistDetailOut;
  docx_deliverable: DeliverableOut;
  pdf_deliverable: DeliverableOut;
  xlsx_deliverable: DeliverableOut;
}

export interface SpecialistPresetOut {
  key: string;
  domain: SpecialistDomain;
  workflow_mode: SpecialistWorkflowMode;
  label_en: string;
  label_ar: string;
  preliminary_warning: string;
  inputs: Record<string, unknown>;
}

export interface SpecialistPresetListResponse {
  presets: SpecialistPresetOut[];
}

export type StructuralAssessmentType =
  | "takedown_check"
  | "load_combinations"
  | "simple_statics_beam"
  | "full_structural_check";

export interface StructuralSummaryOut {
  id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task_id?: string | null;
  assessment_type: StructuralAssessmentType | string;
  title: string;
  language: ReportLanguage | string;
  classification: ProjectClassification | string;
  revision: string;
  version: number;
  export_version: number;
  status: string;
  checks_passed: boolean;
  blocked_missing_count: number;
  failed_checks_count: number;
  standards_status: string;
  use_ai: boolean;
  ai_draft_status: "not_used" | "unverified_ai_draft" | "owner_approved" | string;
  ai_draft_label: string;
  owner_approved_by?: string | null;
  owner_approved_at?: string | null;
  tokens_used: number;
  preliminary_label: string;
  software_recommendation: string;
  summary?: string | null;
  created_at: string;
  updated_at: string;
}

export interface StructuralDetailOut extends StructuralSummaryOut {
  inputs: Record<string, unknown>;
  results: SpecialistResultsOut;
  references: SpecialistReferenceOut[];
  preliminary_assumptions: string[];
  token_usage: TaskTokenUsageOut;
  deliverables: DeliverableOut[];
}

export interface StructuralListResponse {
  assessments: StructuralSummaryOut[];
  total: number;
}

export interface StructuralExportOut {
  assessment: StructuralDetailOut;
  docx_deliverable: DeliverableOut;
  pdf_deliverable: DeliverableOut;
  xlsx_deliverable: DeliverableOut;
}

export interface StructuralPresetOut {
  key: string;
  assessment_type: StructuralAssessmentType;
  label_en: string;
  label_ar: string;
  preliminary_warning: string;
  inputs: Record<string, unknown>;
}

export interface StructuralPresetListResponse {
  presets: StructuralPresetOut[];
}
