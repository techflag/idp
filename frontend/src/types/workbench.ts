export type UserRole = 'admin' | 'user' | 'customer'

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'needs_review'

export type PromptStatus = 'draft' | 'ready' | 'submitted'

export type ResultStatus = 'empty' | 'processing' | 'completed' | 'failed' | 'needs_review'
export type ResultStage = 'parse' | 'process'
export type RunPurpose = 'parse_prompt' | 'post_process' | 'schema_process' | 'summary'
export type RunPhase = 'queued' | 'preparing_input' | 'model_processing' | 'validating' | 'saving' | 'completed' | 'failed' | 'needs_review'

export type ResultSourceMode = 'text' | 'table'

export type PromptTraceKey = 'text' | 'table'

export type OperationTargetType = 'field' | 'table' | 'structured_object' | 'record_collection' | 'record' | 'output'
export type OperationType = 'review' | 'compare' | 'transform' | 'map'
export type OperationResultKind = 'decision' | 'object' | 'table' | 'text'
export type BusinessSkillExecutor =
  | 'llm_structured'
  | 'local_transform'
  | 'quality_check'
  | 'export_data'
  | 'http_connector'
  | 'controlled_python'
  | 'external_connector'
export type BusinessSkillRenderer =
  | 'processed_objects'
  | 'issue_cards'
  | 'data_table'
  | 'field_cards'
  | 'text_block'
  | 'extraction_result'
  | 'field_grid'
  | 'record_cards'
  | 'nested_records'
  | 'json_view'
  | 'auto'
export type SkillStatus = 'draft' | 'active' | 'disabled' | 'deprecated'

export interface PromptTemplate {
  id: string
  name: string
  content: string
  description: string
}

export interface SchemaFieldDefinition {
  fieldKey: string
  label: string
  type: 'string' | 'number' | 'boolean' | 'object' | 'array' | 'enum'
  required: boolean
  description: string
  children: SchemaFieldDefinition[]
  itemSchema?: SchemaFieldDefinition | null
  enumValues: string[]
}

export interface SchemaTemplateSummary {
  id: string
  name: string
  description: string
  documentType: string
  scope: 'page'
  fieldCount: number
  updatedAt: string
}

export interface SchemaTemplateDetail extends SchemaTemplateSummary {
  schemaDefinition: SchemaFieldDefinition[]
  instructions: string
  bindingConfig?: Record<string, unknown> | null
}

export interface SchemaTemplateUpsertRequest {
  name: string
  description: string
  documentType: string
  scope: 'page'
  schemaDefinition: SchemaFieldDefinition[]
  instructions: string
  bindingConfig?: Record<string, unknown> | null
}

export interface CustomerSummary {
  id: string
  name: string
  projectCode: string
  owner: string
  documentCount: number
  taskCount: number
  description: string
}

export interface CreateCustomerRequest {
  name: string
  projectCode: string
  owner: string
  description: string
}

export interface CreateCustomerAccountRequest {
  username: string
  password: string
  displayName: string
  customerIds?: string[]
}

export interface CreateCustomerProvisionRequest {
  customer: CreateCustomerRequest
  account: CreateCustomerAccountRequest
}

export interface CreateCustomerProvisionResponse {
  customer: CustomerSummary
  account: {
    id: string
    username: string
    role: UserRole
    displayName: string
    customerIds: string[]
  }
}

export interface DocumentSummary {
  id: string
  customerId: string
  fileName: string
  fileType: string
  sourceUrl: string
  objectKey: string
  pageCount: number
  parseStatus: string
  uploadedByName: string
  uploadedAt: string
  updatedAt: string
  latestTaskId?: string | null
}

export interface TaskSummary {
  id: string
  customerId: string
  customerName: string
  taskName: string
  documentName: string
  roleScope: UserRole[]
  owner: string
  status: TaskStatus
  uploadTime: string
  updatedAt: string
  pageCount: number
  promptRunCount: number
  summary: string
}

export interface WorkbenchEvidenceRef {
  pageNo: number
  blockId: string
  blockPosition: string
  excerpt: string
}

export interface WorkbenchBlock {
  id: string
  pageIndex: number
  pageNo: number
  blockPosition: string
  type: string
  title: string
  content: string
  htmlContent?: string
  bbox: [number, number, number, number]
}

export interface WorkbenchMarkdownSegment {
  id: string
  pageIndex: number
  pageNo: number
  blockId: string
  blockPosition: string
  type: string
  html: string
  bbox: [number, number, number, number]
}

export type WorkbenchMarkdownSegmentLike = WorkbenchMarkdownSegment | string

export type TableTaskMode = 'parse_json' | 'semantic_extract' | 'semantic_enrich'

export interface WorkbenchPromptConfig {
  textPrompt: string
  tablePrompt: string
  tableTaskMode: TableTaskMode
}

export interface ExtractionFieldItem {
  label: string
  value: string
  source: 'text' | 'table' | 'parser' | 'llm'
  evidenceRefs: WorkbenchEvidenceRef[]
}

export interface ExtractionTableItem {
  title: string
  headers: string[]
  rows: string[][]
  source: 'parser' | 'llm'
  evidenceRefs: WorkbenchEvidenceRef[]
  parserMeta: Record<string, unknown>
}

export interface ExtractionStructuredObjectItem {
  id: string
  title: string
  type: 'kv_record_table'
  kv: Record<string, string>
  table: Array<Record<string, string>>
  source: 'parser' | 'llm'
  evidenceRefs: WorkbenchEvidenceRef[]
  parserMeta: Record<string, unknown>
}

export type ExtractionOutputType =
  | 'field_list'
  | 'data_table'
  | 'kv_table'
  | 'kv_record_table'
  | 'record_collection'
  | 'custom'

export interface ExtractionOutputItem {
  id: string
  title: string
  type: ExtractionOutputType
  renderer: string
  data: unknown
  schema: Record<string, unknown>
  sourceRefs: WorkbenchEvidenceRef[]
}

export interface ExtractionResult {
  summary: string
  outputs: ExtractionOutputItem[]
  errors: string[]
  runMeta: Record<string, unknown>
  fields: ExtractionFieldItem[]
  tables: ExtractionTableItem[]
  structuredObjects: ExtractionStructuredObjectItem[]
  validationErrors: string[]
}

export interface OperationTarget {
  id: string
  pageNo: number
  type: OperationTargetType
  label: string
  valueText: string
  sourceRunId?: string | null
  excerpt?: string | null
  blockIds: string[]
  blockPosition?: string | null
  fieldKey?: string | null
  rowIndex?: number | null
  rowCount?: number | null
  columnCount?: number | null
  headers?: string[]
  groupLabel?: string | null
  data?: unknown
}

export interface PageOperationTargetsResponse {
  pageNo: number
  targets: OperationTarget[]
}

export interface BusinessSkillConfigOption {
  label: string
  value: string
}

export interface BusinessSkillConfigField {
  type: string
  label: string
  required: boolean
  placeholder: string
  options: BusinessSkillConfigOption[]
  default?: unknown
  helpText: string
}

export interface BusinessSkill {
  id: string
  version: string
  name: string
  category: string
  targetTypes: OperationTargetType[]
  customerScope: 'platform' | 'customer'
  scope?: 'platform' | 'customer'
  customerId?: string | null
  enabled: boolean
  status: SkillStatus
  tags: string[]
  sourceTypes: string[]
  executor: BusinessSkillExecutor
  resultKind: OperationResultKind
  renderer: BusinessSkillRenderer
  configSchema: Record<string, BusinessSkillConfigField>
  outputSchema: Record<string, unknown>
  promptTemplate: string
  skillText: string
  skillTextObjectKey: string
  skillTextHash: string
  skillTextSizeBytes: number
  skillTextPreview: string
  examples: Array<Record<string, unknown>>
  defaults: Record<string, unknown>
  latestTestStatus?: string | null
  sampleCount: number
  testRunCount: number
  lastTestedAt?: string | null
  createdBy?: string | null
  updatedBy?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export interface BusinessSkillUpsertRequest {
  skillText: string
  customerId?: string | null
}

export interface ExtractionSkill {
  id: string
  version: string
  name: string
  category: string
  sourceTypes: string[]
  customerScope: 'platform' | 'customer'
  scope?: 'platform' | 'customer'
  customerId?: string | null
  enabled: boolean
  status: SkillStatus
  tags: string[]
  executor: string
  inputBuilder: string
  renderer: string
  configSchema: Record<string, BusinessSkillConfigField>
  outputSchema: Record<string, unknown>
  summaryTemplate: string
  promptTemplate: string
  skillText: string
  skillTextObjectKey: string
  skillTextHash: string
  skillTextSizeBytes: number
  skillTextPreview: string
  rules: string[]
  examples: Array<Record<string, unknown>>
  defaults: Record<string, unknown>
  latestTestStatus?: string | null
  sampleCount: number
  testRunCount: number
  lastTestedAt?: string | null
  createdBy?: string | null
  updatedBy?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export interface ExtractionSkillUpsertRequest {
  skillText: string
  customerId?: string | null
}

export type SkillKind = 'extraction' | 'operation'

export type UnifiedSkill = (BusinessSkill | ExtractionSkill) & { kind: SkillKind }

export type ApplicationStatus = 'draft' | 'published' | 'disabled'
export type ApplicationScope = 'public' | 'private'
export type ApplicationStepKind = 'extraction' | 'operation'
export type ApplicationRunMode = 'api' | 'async' | 'task_bootstrap'

export interface TaskApplicationContext {
  taskId: string
  taskName: string
  customerId: string
  customerName: string
  documentId: string
  documentName: string
  documentType: string
  pageCount: number
}

export interface ApplicationStepInputMapping {
  source: 'document' | 'previous_step_output' | 'named_output_alias' | 'current_targets'
  label: string
  alias?: string
  targetIds?: string[]
}

export interface ApplicationStepTargetMapping {
  targetIds: string[]
  targetLabels: string[]
}

export interface ApplicationStepSnapshot {
  runId: string
  promptSnapshot?: string
  configSnapshot: Record<string, unknown>
  inputMapping: ApplicationStepInputMapping[]
  targetMapping?: ApplicationStepTargetMapping | null
  resultPreview: string
  sourceTaskId: string
  sourcePageNo?: number | null
  semanticLocator?: Record<string, unknown> | null
  templateSample?: Record<string, unknown> | null
}

export interface ApplicationStepDefinition {
  id: string
  kind: ApplicationStepKind
  stepOrder: number
  skillId: string
  skillVersion: string
  skillName: string
  executor?: string | null
  outputAlias: string
  sourceSummary: string
  snapshot: ApplicationStepSnapshot
  sourceDocumentId?: string | null
  sourceRunId?: string | null
  sourceStatus?: string | null
  runPurpose?: string | null
  operationType?: string | null
  resultMode?: string | null
  skillSnapshot?: Record<string, unknown>
  configSnapshot?: Record<string, unknown>
  rawInputMapping?: Record<string, unknown>
  rawTargetMapping?: Record<string, unknown>
  dependencyRefs?: Record<string, unknown>
  outputSummary?: Record<string, unknown>
}

export interface ApplicationVersionSummary {
  version: string
  status: ApplicationStatus
  isDefault: boolean
  stepCount: number
  publishedAt?: string | null
  createdAt: string
  updatedAt: string
}

export interface ApplicationAsset {
  id: string
  applicationId: string
  version: string
  resolvedVersion?: string | null
  status: ApplicationStatus
  scope: ApplicationScope
  defaultVersion?: string | null
  latestPublishedVersion?: string | null
  name: string
  summary: string
  documentType: string
  scenario: string
  coverText: string
  releaseNotes: string
  stepCount: number
  createdAt: string
  updatedAt: string
  publishedAt?: string | null
  sourceTask: TaskApplicationContext
  steps: ApplicationStepDefinition[]
  finalOutputAlias: string
  versions?: ApplicationVersionSummary[]
}

export interface ApplicationDraftPayload {
  applicationId?: string
  scope: ApplicationScope
  name: string
  summary: string
  documentType: string
  scenario: string
  coverText: string
  releaseNotes: string
  sourceTask: TaskApplicationContext
  sampleContext?: SkillSampleContext | null
  steps: ApplicationStepDefinition[]
  finalOutputAlias: string
}

export interface ApplicationRunRequest {
  customerId: string
  file?: File
  note?: string
}

export interface ApplicationPlanTarget {
  targetId: string
  pageNo: number
  type: string
  label: string
  excerpt: string
  score: number
  reasons: string[]
  payload: Record<string, unknown>
}

export interface ApplicationRunPlanStep {
  planStepId: string
  sourceStepOrder: number
  kind: ApplicationStepKind
  skillId: string
  skillVersion: string
  skillName: string
  selected: boolean
  confidence: number
  reason: string
  targetSelector: Record<string, unknown>
  targets: ApplicationPlanTarget[]
  locatorResult?: Record<string, unknown>
  executionGate?: {
    autoExecute?: boolean
    needsReview?: boolean
    confidence?: number
    candidateGap?: number
    warnings?: string[]
  }
  candidateGap?: number
  needsReview?: boolean
  upstreamPlanStepIds: string[]
  warnings: string[]
}

export interface ApplicationRunPlanResponse {
  planId: string
  applicationId: string
  taskId: string
  version: string
  status: 'ready' | 'needs_review' | 'blocked'
  requiresConfirmation: boolean
  documentProfile: Record<string, unknown>
  steps: ApplicationRunPlanStep[]
  warnings: string[]
  agentscope: Record<string, unknown>
  traceId?: string | null
  tracePath?: string | null
  traceLevel?: string | null
}

export interface ApplicationRunStepSummary {
  stepOrder: number
  kind: ApplicationStepKind
  skillId: string
  skillVersion: string
  skillName: string
  sourcePageNo?: number | null
  sourceRunId?: string | null
  executionRunId?: string | null
  status: TaskStatus
  inputMapping: Record<string, unknown>
  targetMapping: Record<string, unknown>
  configSnapshot: Record<string, unknown>
  promptSnapshot: string
  outputSummary: Record<string, unknown>
  errorMessage?: string | null
  createdAt: string
  updatedAt: string
}

export interface ApplicationRunDetail {
  id: string
  applicationId: string
  applicationName?: string
  customerId: string
  taskId: string
  documentId: string
  version: string
  status: TaskStatus
  stepCount: number
  completedStepCount: number
  errorMessage?: string | null
  createdAt: string
  updatedAt: string
  steps: ApplicationRunStepSummary[]
  finalOutput?: Record<string, unknown> | null
}

export interface ApplicationRunReviewFeedbackRequest {
  stepOrder: number
  correctedOutput?: Record<string, unknown>
  note?: string
  evidenceRefs?: Array<Record<string, unknown>>
  markAsRegression?: boolean
}

export interface ApplicationRunReviewFeedbackResponse {
  run: ApplicationRunDetail
  feedback: Record<string, unknown>
}

export interface ApplicationDetailLoadOptions {
  version?: string | null
  includeDraft?: boolean
}

export interface ApplicationDetailUpdatePayload {
  scope?: ApplicationScope
  name?: string
  summary?: string
  documentType?: string
  scenario?: string
  coverText?: string
  releaseNotes?: string
  status?: ApplicationStatus
  steps?: ApplicationStepDefinition[]
}

export interface ApplicationPublishPayload {
  version?: string
  setAsDefault?: boolean
}

export interface ApplicationRunResult {
  mode: ApplicationRunMode
  applicationId: string
  version: string
  taskId?: string
  runId?: string
  message: string
  parse?: Record<string, unknown>
  applicationRun?: ApplicationRunDetail
  finalOutput?: Record<string, unknown> | null
  stepResults?: Array<Record<string, unknown>>
}

export interface ApplicationSourceRunOption {
  id: string
  kind: ApplicationStepKind
  runId: string
  skillId: string
  skillVersion: string
  skillName: string
  executor?: string | null
  pageNo?: number | null
  title: string
  summary: string
  createdAt?: string | null
  promptSnapshot?: string
  configSnapshot: Record<string, unknown>
  inputMapping: ApplicationStepInputMapping[]
  outputAlias: string
  resultPreview: string
  targetMapping?: ApplicationStepTargetMapping | null
  recommended: boolean
}

export interface ApplicationWorkshopStepDraft {
  id: string
  taskId: string
  isLight?: boolean
  kind: ApplicationStepKind
  status: 'generated' | 'verified'
  dataTypeName: string
  goal: string
  expectedOutput: string
  sourceTitle: string
  sourceScope: string
  skillText: string
  skillName: string
  errors: string[]
  model: string
  sampleSource?: Record<string, unknown> | null
  semanticLocator?: Record<string, unknown> | null
  sampleExtraction?: Record<string, unknown> | null
  sampleProcessing?: Record<string, unknown> | null
  skillDevelopment?: Record<string, unknown> | null
  runOption?: ApplicationSourceRunOption | null
  createdAt: string
  updatedAt: string
}

export interface ApplicationWorkshopStepDraftUpsertRequest {
  id: string
  kind: ApplicationStepKind
  status: 'generated' | 'verified'
  dataTypeName: string
  goal: string
  expectedOutput: string
  sourceTitle: string
  sourceScope: string
  skillText: string
  skillName: string
  errors: string[]
  model: string
  sampleSource?: Record<string, unknown> | null
  semanticLocator?: Record<string, unknown> | null
  sampleExtraction?: Record<string, unknown> | null
  sampleProcessing?: Record<string, unknown> | null
  skillDevelopment?: Record<string, unknown> | null
  runOption?: ApplicationSourceRunOption | null
}

export interface ApplicationDraftContext {
  sourceTask: TaskApplicationContext
  parseOptions: ApplicationSourceRunOption[]
  operationOptions: ApplicationSourceRunOption[]
  defaultParseOptionId: string
  defaultOperationOptionIds: string[]
  missingRequirements: string[]
  suggestedName: string
  suggestedSummary: string
  suggestedDocumentType: string
  suggestedScenario: string
  suggestedCoverText: string
  suggestedReleaseNotes: string
}

export interface SkillCopyDraftRequest {
  kind: SkillKind
  sourceSkillId: string
  sourceCustomerId?: string | null
  targetCustomerId: string
}

export interface SkillCopyDraftResponse {
  kind: SkillKind
  sourceSkillId: string
  targetCustomerId: string
  skillText: string
}

export interface SkillOwnershipUpdateRequest {
  kind: SkillKind
  sourceCustomerId: string
  targetCustomerId: string
}

export interface SkillSample {
  id: string
  kind: SkillKind
  skillId: string
  version: string
  customerId?: string | null
  instruction: string
  objectKey: string
  contentType: string
  fileName: string
  sizeBytes: number
  preview: string
  content?: string | null
  createdAt: string
  updatedAt: string
}

export interface SkillSampleUpsertRequest {
  kind: SkillKind
  skillId: string
  version: string
  customerId?: string | null
  instruction: string
  content: string
  fileName?: string
  contentType?: string
}

export interface SkillPrototypeSource {
  format: 'text' | 'html' | 'json'
  content: string
  fileName: string
  preview?: string
}

export interface SkillPrototypeDatasetItem {
  id?: string
  name?: string
  sourceFormat?: 'text' | 'html' | 'json'
  sampleText?: string
  sampleHtml?: string
  samplePayloadJson?: unknown
  expectedOutput?: unknown
  note?: string
}

export interface SkillPrototypeProject {
  id: string
  name: string
  description: string
  extractionGoal: string
  fieldRequirements: string
  outputExample: string
  source: SkillPrototypeSource
  status: string
  baselineSkillText: string
  dataset: SkillPrototypeDatasetItem[]
  candidates: Array<Record<string, unknown>>
  recommendedCandidateId?: string | null
  createdAt: string
  updatedAt: string
}

export interface SkillPrototypeCreateRequest {
  name: string
  description?: string
  extractionGoal: string
  fieldRequirements?: string
  outputExample?: string
  source: SkillPrototypeSource
  dataset?: SkillPrototypeDatasetItem[]
}

export interface SkillPrototypeBaselineUpdateRequest {
  skillText: string
}

export interface SkillTestRunSummary {
  id: string
  kind: SkillKind
  skillId: string
  version: string
  customerId?: string | null
  status: string
  valid: boolean
  errors: string[]
  summary?: Record<string, unknown> | null
  inputObjectKey?: string | null
  resultObjectKey?: string | null
  factsObjectKey?: string | null
  llmObjectKey?: string | null
  result?: Record<string, unknown> | null
  facts?: Record<string, unknown> | null
  sampleId?: string | null
  provider?: string | null
  model?: string | null
  durationMs?: number | null
  inputChars: number
  outputChars: number
  createdAt: string
  updatedAt: string
}

export interface SkillValidateRequest {
  kind: SkillKind
  skillText: string
  customerId?: string | null
}

export interface SkillValidateResponse {
  valid: boolean
  errors: string[]
  skillId?: string | null
  version?: string | null
  name?: string | null
  executor?: string | null
}

export interface SkillTestRunRequest {
  kind: SkillKind
  skillText: string
  sampleText: string
  config: Record<string, unknown>
  customerId?: string | null
  persist?: boolean
  sampleId?: string | null
}

export interface SkillTestRunResponse {
  valid: boolean
  errors: string[]
  facts: Record<string, unknown>
  rawOutput?: Record<string, unknown> | null
  extractionResult?: ExtractionResult | null
  durationMs?: number | null
  provider?: string | null
  model?: string | null
  inputChars: number
  outputChars: number
}

export interface SkillAssistRequest {
  kind: SkillKind
  skillText: string
  instruction: string
  sampleText?: string
  customerId?: string | null
}

export interface SkillAssistResponse {
  valid: boolean
  errors: string[]
  skillText: string
  reasoning: string
  answer: string
  provider: string
  model: string
  durationMs: number
  inputChars: number
  outputChars: number
}

export interface SkillSampleContext {
  sampleId?: string
  source?: string
  applicationId?: string | null
  customerId?: string | null
  document?: Record<string, unknown>
  pages?: WorkbenchPage[]
  documentTree?: WorkbenchDocumentTree | null
  operationTargets?: OperationTarget[]
  sampleSource?: Record<string, unknown>
}

export interface SkillDraftFromSampleRequest {
  taskId?: string
  applicationId?: string | null
  sampleContext?: SkillSampleContext | null
  kind: SkillKind
  instruction: string
  expectedOutput?: string
  targetIds?: string[]
  pageNo?: number | null
  customerId?: string | null
  dataTypeName?: string
  sourceScope?: string
  sourceLabel?: string
  sourceText?: string
  treeNodeId?: string
  treePath?: string[]
  pageRange?: Record<string, unknown> | null
  contentRefs?: Array<Record<string, unknown>>
  confirmedSampleOutput?: unknown
}

export interface SkillDraftFromSampleResponse {
  kind: SkillKind
  taskId: string
  customerId?: string | null
  sampleSummary: Record<string, unknown>
  assist: SkillAssistResponse
  evidenceDiagnostics: Record<string, unknown>
  validationReport: Record<string, unknown>
  outputContractSummary: Record<string, unknown>
}

export interface SkillSampleExtractFromSampleResponse {
  kind: SkillKind
  taskId: string
  customerId?: string | null
  sampleSummary: Record<string, unknown>
  extractionResult: ExtractionResult
  rawOutput: unknown
  editableOutput: string
  provider: string
  model: string
  durationMs: number
  inputChars: number
  outputChars: number
  promptTokens?: number | null
  completionTokens?: number | null
  totalTokens?: number | null
  errors: string[]
  evidenceDiagnostics: Record<string, unknown>
  validationReport: Record<string, unknown>
  outputContractSummary: Record<string, unknown>
  traceId?: string | null
  tracePath?: string | null
  traceLevel?: 'full' | null
}

export interface SkillSampleLocateCandidate {
  nodeId: string
  title: string
  type: string
  pageNo: number
  pageRange: string
  path: string[]
  excerpt: string
  score: number
  reasons: string[]
  warnings: string[]
  payload: Record<string, unknown>
}

export interface SkillSampleLocatedSource {
  mode: 'tree'
  kind: ApplicationStepKind
  title: string
  summary: string
  sourceScope: string
  sourceText: string
  pageNo: number | null
  pageIndex: number | null
  targetIds: string[]
  treeNodeId?: string | null
  treePath: string[]
  pageRange?: Record<string, unknown> | null
  contentRefs: Array<Record<string, unknown>>
  locatorReason: string
}

export interface SkillSampleLocateAndExtractRequest {
  taskId?: string
  applicationId?: string | null
  sampleContext?: SkillSampleContext | null
  query: string
  customerId?: string | null
  outputPreference?: 'auto' | 'field_list' | 'data_table' | 'record_collection' | 'notes'
  locatorInstruction?: string
  extraInstruction?: string
  expectedOutput?: string
  selectedCandidateId?: string | null
  runExtraction?: boolean
}

export interface SkillSampleLocateAndExtractResponse {
  kind: SkillKind
  taskId: string
  customerId?: string | null
  status: 'located' | 'extracted' | 'needs_review' | 'not_found'
  query: string
  dataTypeName: string
  outputPreference: string
  locatedSource?: SkillSampleLocatedSource | null
  candidates: SkillSampleLocateCandidate[]
  locatorResult: Record<string, unknown>
  locatorProfile: Record<string, unknown>
  locatorSkillText: string
  sampleSummary: Record<string, unknown>
  extractionResult?: ExtractionResult | null
  rawOutput: unknown
  editableOutput: string
  provider: string
  model: string
  durationMs: number
  inputChars: number
  outputChars: number
  promptTokens?: number | null
  completionTokens?: number | null
  totalTokens?: number | null
  errors: string[]
  evidenceDiagnostics: Record<string, unknown>
  validationReport: Record<string, unknown>
  outputContractSummary: Record<string, unknown>
  errorMessage?: string
  pageRange?: string
  evidenceRefs?: WorkbenchEvidenceRef[]
  promptTrace?: PageResultPromptTrace | null
  traceId?: string | null
  tracePath?: string | null
  traceLevel?: 'full' | null
}

export interface SkillSampleProcessFromSampleResponse {
  kind: SkillKind
  taskId: string
  customerId?: string | null
  sampleSummary: Record<string, unknown>
  summary: string
  resultKind: 'decision' | 'object' | 'table' | 'text'
  outputPayload: unknown
  validationErrors: string[]
  rawOutput: unknown
  editableOutput: string
  provider: string
  model: string
  durationMs: number
  inputChars: number
  outputChars: number
  promptTokens?: number | null
  completionTokens?: number | null
  totalTokens?: number | null
  errors: string[]
  evidenceDiagnostics: Record<string, unknown>
  validationReport: Record<string, unknown>
  outputContractSummary: Record<string, unknown>
}

export interface ExtractionSkillRunRequest {
  pageNo: number
  skillId: string
  skillVersion: string
  config: Record<string, unknown>
}

export interface SkillRunRequest {
  pageNo: number
  skillId: string
  skillVersion: string
  targetIds: string[]
  config: Record<string, unknown>
  upstreamRunIds?: string[]
}

export interface ObjectOperationRunRequest {
  pageNo: number
  target: OperationTarget
  relatedTargets: OperationTarget[]
  operationType: OperationType
  instruction: string
  resultMode: 'auto' | 'decision' | 'object' | 'table' | 'text'
}

export interface ObjectOperationResult {
  id: string
  targetId: string
  pageNo: number
  operationType: OperationType
  executionSource?: string | null
  skillId?: string | null
  skillVersion?: string | null
  sourceSkillId?: string | null
  sourceSkillVersion?: string | null
  sourceSkillName?: string | null
  sourceApplicationId?: string | null
  sourceApplicationVersion?: string | null
  sourceApplicationStepId?: string | null
  executor?: string | null
  configSnapshot?: Record<string, unknown> | null
  resultKind: OperationResultKind
  summary: string
  outputPayload?: unknown
  validationErrors: string[]
  runPhase?: RunPhase
  phaseStartedAt?: string | null
  lastHeartbeatAt?: string | null
  llmTraceSummary?: LlmCallTraceSummary | null
  evidenceRefs: WorkbenchEvidenceRef[]
  relatedTargetIds: string[]
  createdAt: string
  source: 'runtime'
}

export interface ObjectOperationExecutionResponse {
  run: PromptRunRecordResponse
  result?: ObjectOperationResult | null
}

export interface SchemaProcessResult {
  templateId: string
  templateName: string
  templateVersion?: string | null
  summary: string
  schemaOutput: Record<string, unknown>
  validationErrors: string[]
  evidenceRefs: WorkbenchEvidenceRef[]
  source: 'runtime'
}

export interface PromptTraceItem {
  key: PromptTraceKey
  label: string
  sourceMode: ResultSourceMode
  prompt: string
  summary: string
}

export interface PageResultPromptTrace {
  text?: PromptTraceItem | null
  table?: PromptTraceItem | null
}

export interface WorkbenchPage {
  pageIndex: number
  pageNo: number
  title: string
  summary: string
  promptConfig: WorkbenchPromptConfig
  promptStatus: PromptStatus
  markdownSegments: WorkbenchMarkdownSegmentLike[]
  blocks: WorkbenchBlock[]
  rawItems: unknown[]
  pageSize: [number, number]
}

export interface PageResultSummary {
  id: string
  title: string
  pageNo: number
  pageIndex: number
  status: ResultStatus
  runPhase?: RunPhase
  phaseStartedAt?: string | null
  lastHeartbeatAt?: string | null
  resultStage?: ResultStage
  runPurpose?: RunPurpose
  promptName: string
  runType?: 'page' | 'page_group' | 'summary'
  startPageNo?: number
  endPageNo?: number
  pageRange?: string
  errorMessage?: string
  schemaTemplateId?: string | null
  schemaTemplateName?: string | null
  schemaTemplateVersion?: string | null
  evidenceRefs?: WorkbenchEvidenceRef[]
  promptTrace?: PageResultPromptTrace | null
}

export interface PageResultDetail extends PageResultSummary {
  promptTrace?: PageResultPromptTrace | null
  extractionResult?: ExtractionResult | null
  outputText?: string | null
  schemaProcessResult?: SchemaProcessResult | null
  schemaOutput?: Record<string, unknown> | null
  evidenceRefs?: WorkbenchEvidenceRef[]
  validationErrors?: string[]
  llmTraceSummary?: LlmCallTraceSummary | null
}

export interface LlmCallTraceSummary {
  callCount: number
  slowCallCount: number
  totalHttpMs: number
  totalMs: number
  inputChars: number
  outputChars: number
  promptTokens?: number | null
  completionTokens?: number | null
  totalTokens?: number | null
  model?: string | null
  provider?: string | null
  latestStatus?: string | null
  latestErrorType?: string | null
}

export interface SummaryResultItem {
  id: string
  title: string
  status: ResultStatus
  runName: string
  detail: string
  pageRange: string
  errorMessage?: string
  updatedAt?: string
}

export interface TaskRuntimeInfo {
  parseStatus: TaskStatus
  pagePromptStatus: TaskStatus
  summaryStatus: TaskStatus
  latestRunLabel: string
  failedPageCount?: number
  completedPageCount?: number
  latestPromptRunAt?: string
}

export interface WorkbenchDocument {
  id: string
  fileName: string
  fileType: string
  pdfUrl: string
  markdownUrl: string
  rawJsonUrl: string
  pageCount: number
  sampledPageCount: number
}

export interface DocumentTreeLocation {
  page?: number
  bbox?: number[]
}

export interface DocumentTreeMergeDescription {
  row?: number
  column?: number
  rowSpan?: number
  colSpan?: number
  text?: string
  description?: string
}

export interface DocumentTreeNode {
  type?: string
  title?: string
  metadata?: string
  content?: string
  level?: number
  location?: DocumentTreeLocation[]
  block_ids?: Array<string | number>
  rawHtml?: string
  rows?: string[][]
  mergeDescriptions?: DocumentTreeMergeDescription[]
  children?: DocumentTreeNode[]
}

export interface WorkbenchDocumentTree {
  source: string
  docId: string
  tree: DocumentTreeNode
  modules?: Record<string, unknown>[]
  treeText?: string
}

export interface WorkbenchTaskDetail {
  task: TaskSummary
  document: WorkbenchDocument
  runtime: TaskRuntimeInfo
  pages: WorkbenchPage[]
  pageResults: PageResultSummary[]
  objectOperationResults?: ObjectOperationResult[]
  summaryResults?: SummaryResultItem[]
  documentTree?: WorkbenchDocumentTree | null
  applicationRun?: ApplicationRunDetail | null
}

export interface WorkbenchDataset {
  customers: CustomerSummary[]
  tasks: TaskSummary[]
  taskDetails: Record<string, WorkbenchTaskDetail>
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface AdminOverviewResponse {
  customers: CustomerSummary[]
  tasks: TaskSummary[]
  totalCustomers: number
  totalDocuments: number
  totalTasks: number
}

export interface CustomerWorkspaceResponse {
  customer: CustomerSummary
  documents: DocumentSummary[]
  tasks: TaskSummary[]
}

export interface PromptExecutionRequest {
  promptName: string
  promptText: string
  startPageNo: number
  endPageNo?: number
  runMode: 'page' | 'page_group' | 'auto'
  pageGroupSize?: number
  templateId?: string
  runName?: string
  createSummary?: boolean
  runPurpose?: RunPurpose
  tableTaskMode?: TableTaskMode
  pageContext?: {
    pages: WorkbenchPage[]
  }
}

export interface SchemaRunRequest {
  templateId: string
  startPageNo: number
  endPageNo?: number
  runMode: 'page' | 'page_group' | 'auto'
  pageGroupSize?: number
  runName?: string
  createSummary?: boolean
}

export interface PromptRunRecordResponse {
  id: string
  runType: 'page' | 'page_group' | 'summary'
  runPurpose: RunPurpose
  runName: string
  promptName: string
  promptText: string
  startPageNo: number
  endPageNo: number
  pageRange: string
  status: TaskStatus
  runPhase?: RunPhase
  phaseStartedAt?: string | null
  lastHeartbeatAt?: string | null
  errorMessage?: string
  outputText?: string
  inputPath?: string
  outputPath?: string
  updatedAt: string
  schemaTemplateId?: string | null
  schemaTemplateName?: string | null
  schemaTemplateVersion?: string | null
}

export interface PromptExecutionResponse {
  taskDetail?: WorkbenchTaskDetail | null
  runs: PromptRunRecordResponse[]
  summaryRun?: PromptRunRecordResponse | null
}

export interface ParseProgress {
  extractedPages: number
  totalPages: number
  startTime?: string | null
}

export interface ParseArtifactUrls {
  artifactBaseUrl?: string | null
  fullZipUrl?: string | null
  markdownUrl?: string | null
  rawJsonUrl?: string | null
  layoutUrl?: string | null
  blockListUrl?: string | null
  modelJsonUrl?: string | null
}

export interface ParseTaskStatusResponse {
  taskId: string
  customerId: string
  documentId: string
  state: TaskStatus
  mineruState?: string | null
  mineruTaskId?: string | null
  errorMessage?: string | null
  progress: ParseProgress
  artifacts: ParseArtifactUrls
}

export interface UploadAndParseResponse {
  document: WorkbenchDocument
  createdTask: TaskSummary
  parse: ParseTaskStatusResponse
}
