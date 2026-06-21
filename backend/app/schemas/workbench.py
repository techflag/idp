"""API schemas for the workbench-facing backend contract.

Field names intentionally stay in camelCase so the frontend can replace the
current local sample layer with minimal mapping work.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

from app.schemas.auth import AuthUserResponse, CreateCustomerAccountRequest

UserRole = Literal["admin", "user", "customer"]
SkillKind = Literal["extraction", "operation"]
SkillStatus = Literal["draft", "active", "disabled", "deprecated"]
ApplicationStepKind = Literal["extraction", "operation"]
ApplicationStatus = Literal["draft", "published", "disabled"]
ApplicationScope = Literal["public", "private"]
TaskStatus = Literal["pending", "running", "completed", "failed", "needs_review"]
PromptStatus = Literal["draft", "ready", "submitted"]
ResultStatus = Literal["empty", "processing", "completed", "failed", "needs_review"]
RunPhase = Literal[
    "queued",
    "preparing_input",
    "model_processing",
    "validating",
    "saving",
    "completed",
    "failed",
    "needs_review",
]
PromptRunType = Literal["page", "page_group", "summary"]
ResultStage = Literal["parse", "process"]
RunPurpose = Literal["parse_prompt", "post_process", "schema_process", "summary"]
ResultSourceMode = Literal["text", "table"]
PromptTraceKey = Literal["text", "table"]
OperationTargetType = Literal["field", "table", "structured_object", "record_collection", "record", "output"]
OperationType = Literal["review", "compare", "transform", "map"]
OperationResultKind = Literal["decision", "object", "table", "text"]
BusinessSkillExecutor = Literal[
    "llm_structured",
    "local_transform",
    "quality_check",
    "export_data",
    "http_connector",
    "controlled_python",
    "external_connector",
]
BusinessSkillRenderer = Literal[
    "processed_objects",
    "issue_cards",
    "data_table",
    "field_cards",
    "text_block",
    "extraction_result",
    "field_grid",
    "record_cards",
    "nested_records",
    "json_view",
    "auto",
]
TableTaskMode = Literal["parse_json", "semantic_extract", "semantic_enrich"]
T = TypeVar("T")


class SchemaFieldDefinition(BaseModel):
    fieldKey: str
    label: str
    type: Literal["string", "number", "boolean", "object", "array", "enum"]
    required: bool = False
    description: str = ""
    children: list["SchemaFieldDefinition"] = Field(default_factory=list)
    itemSchema: Optional["SchemaFieldDefinition"] = None
    enumValues: list[str] = Field(default_factory=list)


class SchemaTemplateSummary(BaseModel):
    id: str
    name: str
    description: str
    documentType: str
    scope: Literal["page"] = "page"
    fieldCount: int = 0
    updatedAt: str


class SchemaTemplateDetail(SchemaTemplateSummary):
    schemaDefinition: list[SchemaFieldDefinition]
    instructions: str = ""
    bindingConfig: Optional[dict[str, Any]] = None


class SchemaTemplateUpsertRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    documentType: str = ""
    scope: Literal["page"] = "page"
    schemaDefinition: list[SchemaFieldDefinition] = Field(default_factory=list)
    instructions: str = ""
    bindingConfig: Optional[dict[str, Any]] = None


class PromptTemplate(BaseModel):
    id: str
    name: str
    content: str
    description: str


class CustomerSummary(BaseModel):
    id: str
    name: str
    projectCode: str
    owner: str
    documentCount: int
    taskCount: int
    description: str


class TaskSummary(BaseModel):
    id: str
    customerId: str
    customerName: str
    taskName: str
    documentName: str
    roleScope: list[UserRole]
    owner: str
    status: TaskStatus
    uploadTime: str
    updatedAt: str
    pageCount: int
    promptRunCount: int
    summary: str


class WorkbenchEvidenceRef(BaseModel):
    pageNo: int
    blockId: str
    blockPosition: str
    excerpt: str


class WorkbenchBlock(BaseModel):
    id: str
    pageIndex: int
    pageNo: int
    blockPosition: str
    type: str
    title: str
    content: str
    htmlContent: Optional[str] = None
    bbox: tuple[float, float, float, float]


class WorkbenchMarkdownSegment(BaseModel):
    id: str
    pageIndex: int
    pageNo: int
    blockId: str
    blockPosition: str
    type: str
    html: str
    bbox: tuple[float, float, float, float]


class WorkbenchPageSummary(BaseModel):
    pageIndex: int
    pageNo: int
    prompt: str
    promptStatus: PromptStatus
    promptName: Optional[str] = None
    promptStartPageNo: Optional[int] = None
    promptEndPageNo: Optional[int] = None
    promptTemplateId: Optional[str] = None


class WorkbenchPageDetail(WorkbenchPageSummary):
    markdownSegments: list[WorkbenchMarkdownSegment]
    blocks: list[WorkbenchBlock]
    rawItems: list[dict[str, Any]]
    pageSize: tuple[float, float]


class ExtractionFieldItem(BaseModel):
    label: str
    value: str
    source: Literal["text", "table", "parser", "llm"] = "llm"
    evidenceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)


class ExtractionTableItem(BaseModel):
    title: str
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    source: Literal["parser", "llm"] = "parser"
    evidenceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)
    parserMeta: dict[str, Any] = Field(default_factory=dict)


class ExtractionStructuredObjectItem(BaseModel):
    id: str
    title: str
    type: Literal["kv_record_table"] = "kv_record_table"
    kv: dict[str, str] = Field(default_factory=dict)
    table: list[dict[str, str]] = Field(default_factory=list)
    source: Literal["parser", "llm"] = "parser"
    evidenceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)
    parserMeta: dict[str, Any] = Field(default_factory=dict)


class ExtractionOutputItem(BaseModel):
    id: str
    title: str
    type: Literal["field_list", "data_table", "kv_table", "kv_record_table", "record_collection", "custom"]
    renderer: str = "auto"
    data: Any = Field(default_factory=dict)
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    sourceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ExtractionResult(BaseModel):
    summary: str
    outputs: list[ExtractionOutputItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    runMeta: dict[str, Any] = Field(default_factory=dict)
    fields: list[ExtractionFieldItem] = Field(default_factory=list)
    tables: list[ExtractionTableItem] = Field(default_factory=list)
    structuredObjects: list[ExtractionStructuredObjectItem] = Field(default_factory=list)
    validationErrors: list[str] = Field(default_factory=list)


class OperationTargetRef(BaseModel):
    id: str
    pageNo: int
    type: OperationTargetType
    label: str
    valueText: str = ""
    sourceRunId: Optional[str] = None
    excerpt: Optional[str] = None
    blockIds: list[str] = Field(default_factory=list)
    blockPosition: Optional[str] = None
    fieldKey: Optional[str] = None
    rowIndex: Optional[int] = None
    rowCount: Optional[int] = None
    columnCount: Optional[int] = None
    headers: list[str] = Field(default_factory=list)
    groupLabel: Optional[str] = None
    data: Optional[Any] = None


class PageOperationTargetsResponse(BaseModel):
    pageNo: int
    targets: list[OperationTargetRef]


class BusinessSkillConfigOption(BaseModel):
    label: str
    value: str


class BusinessSkillConfigField(BaseModel):
    type: str
    label: str
    required: bool = False
    placeholder: str = ""
    options: list[BusinessSkillConfigOption] = Field(default_factory=list)
    default: Optional[Any] = None
    helpText: str = ""


class BusinessSkillDetail(BaseModel):
    id: str
    version: str
    name: str
    category: str = "business_operation"
    targetTypes: list[OperationTargetType] = Field(default_factory=list)
    customerScope: Literal["platform", "customer"] = "platform"
    scope: Literal["platform", "customer"] = "platform"
    customerId: Optional[str] = None
    enabled: bool = True
    status: SkillStatus = "active"
    tags: list[str] = Field(default_factory=list)
    sourceTypes: list[str] = Field(default_factory=list)
    executor: BusinessSkillExecutor
    resultKind: OperationResultKind
    renderer: BusinessSkillRenderer = "auto"
    configSchema: dict[str, BusinessSkillConfigField] = Field(default_factory=dict)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    promptTemplate: str = ""
    skillText: str = ""
    skillTextObjectKey: str = ""
    skillTextHash: str = ""
    skillTextSizeBytes: int = 0
    skillTextPreview: str = ""
    examples: list[dict[str, Any]] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    latestTestStatus: Optional[str] = None
    sampleCount: int = 0
    testRunCount: int = 0
    lastTestedAt: Optional[str] = None
    createdBy: Optional[str] = None
    updatedBy: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class BusinessSkillUpsertRequest(BaseModel):
    skillText: str = Field(min_length=1)
    customerId: Optional[str] = None


class ExtractionSkillDetail(BaseModel):
    id: str
    version: str
    name: str
    category: str = "extraction"
    sourceTypes: list[str] = Field(default_factory=list)
    customerScope: Literal["platform", "customer"] = "platform"
    scope: Literal["platform", "customer"] = "platform"
    customerId: Optional[str] = None
    enabled: bool = True
    status: SkillStatus = "active"
    tags: list[str] = Field(default_factory=list)
    executor: str
    inputBuilder: str = "page_compact"
    renderer: str = "auto"
    configSchema: dict[str, BusinessSkillConfigField] = Field(default_factory=dict)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    summaryTemplate: str = ""
    promptTemplate: str = ""
    skillText: str = ""
    skillTextObjectKey: str = ""
    skillTextHash: str = ""
    skillTextSizeBytes: int = 0
    skillTextPreview: str = ""
    rules: list[str] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    latestTestStatus: Optional[str] = None
    sampleCount: int = 0
    testRunCount: int = 0
    lastTestedAt: Optional[str] = None
    createdBy: Optional[str] = None
    updatedBy: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class ExtractionSkillUpsertRequest(BaseModel):
    skillText: str = Field(min_length=1)
    customerId: Optional[str] = None


class UnifiedSkillUpsertRequest(BaseModel):
    kind: SkillKind
    skillText: str = Field(min_length=1)
    customerId: Optional[str] = None


class SkillCopyDraftRequest(BaseModel):
    kind: SkillKind
    sourceSkillId: str = Field(min_length=1)
    sourceCustomerId: Optional[str] = None
    targetCustomerId: str = Field(min_length=1)


class SkillCopyDraftResponse(BaseModel):
    kind: SkillKind
    sourceSkillId: str
    targetCustomerId: str
    skillText: str


class SkillOwnershipUpdateRequest(BaseModel):
    kind: SkillKind
    sourceCustomerId: str = Field(min_length=1)
    targetCustomerId: str = Field(min_length=1)


class SkillSampleUpsertRequest(BaseModel):
    kind: SkillKind
    skillId: str = Field(min_length=1)
    version: str = "1.0.0"
    customerId: Optional[str] = None
    instruction: str = ""
    content: str = Field(min_length=1)
    fileName: str = "sample.txt"
    contentType: str = "text/plain; charset=utf-8"


class SkillSampleResponse(BaseModel):
    id: str
    kind: SkillKind
    skillId: str
    version: str
    customerId: Optional[str] = None
    instruction: str = ""
    objectKey: str
    contentType: str
    fileName: str
    sizeBytes: int
    preview: str
    content: Optional[str] = None
    createdAt: str
    updatedAt: str


class SkillTestRunSummary(BaseModel):
    id: str
    kind: SkillKind
    skillId: str
    version: str
    customerId: Optional[str] = None
    status: str
    valid: bool
    errors: list[str] = Field(default_factory=list)
    summary: Optional[dict[str, Any]] = None
    inputObjectKey: Optional[str] = None
    resultObjectKey: Optional[str] = None
    factsObjectKey: Optional[str] = None
    llmObjectKey: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    facts: Optional[dict[str, Any]] = None
    sampleId: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    durationMs: Optional[int] = None
    inputChars: int = 0
    outputChars: int = 0
    createdAt: str
    updatedAt: str


class SkillValidateRequest(BaseModel):
    kind: SkillKind
    skillText: str = Field(min_length=1)
    customerId: Optional[str] = None


class SkillValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    skillId: Optional[str] = None
    version: Optional[str] = None
    name: Optional[str] = None
    executor: Optional[str] = None


class SkillTestRunRequest(BaseModel):
    kind: SkillKind
    skillText: str = Field(min_length=1)
    sampleText: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    customerId: Optional[str] = None
    persist: bool = False
    sampleId: Optional[str] = None


class SkillTestRunResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    rawOutput: Optional[dict[str, Any]] = None
    extractionResult: Optional[ExtractionResult] = None
    durationMs: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    inputChars: int = 0
    outputChars: int = 0


class SkillAssistRequest(BaseModel):
    kind: SkillKind
    skillText: str = ""
    instruction: str = Field(min_length=1)
    sampleText: str = ""
    customerId: Optional[str] = None


class SkillAssistResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    skillText: str
    reasoning: str = ""
    answer: str = ""
    provider: str = "dashscope"
    model: str = "qwen3.7-max"
    durationMs: int = 0
    inputChars: int = 0
    outputChars: int = 0


class ApplicationWorkshopStepDraft(BaseModel):
    id: str = Field(min_length=1)
    taskId: str
    isLight: bool = False
    kind: ApplicationStepKind
    status: Literal["generated", "verified"] = "generated"
    dataTypeName: str = ""
    goal: str = ""
    expectedOutput: str = ""
    sourceTitle: str = ""
    sourceScope: str = ""
    skillText: str = ""
    skillName: str = ""
    errors: list[str] = Field(default_factory=list)
    model: str = ""
    sampleSource: Optional[dict[str, Any]] = None
    semanticLocator: Optional[dict[str, Any]] = None
    sampleExtraction: Optional[dict[str, Any]] = None
    sampleProcessing: Optional[dict[str, Any]] = None
    skillDevelopment: Optional[dict[str, Any]] = None
    runOption: Optional[dict[str, Any]] = None
    createdAt: str = ""
    updatedAt: str = ""


class ApplicationWorkshopStepDraftUpsertRequest(BaseModel):
    id: str = Field(min_length=1)
    kind: ApplicationStepKind
    status: Literal["generated", "verified"] = "generated"
    dataTypeName: str = ""
    goal: str = ""
    expectedOutput: str = ""
    sourceTitle: str = ""
    sourceScope: str = ""
    skillText: str = ""
    skillName: str = ""
    errors: list[str] = Field(default_factory=list)
    model: str = ""
    sampleSource: Optional[dict[str, Any]] = None
    semanticLocator: Optional[dict[str, Any]] = None
    sampleExtraction: Optional[dict[str, Any]] = None
    sampleProcessing: Optional[dict[str, Any]] = None
    skillDevelopment: Optional[dict[str, Any]] = None
    runOption: Optional[dict[str, Any]] = None


class ExtractionSkillRunRequest(BaseModel):
    pageNo: int = Field(ge=1)
    skillId: str = Field(min_length=1)
    skillVersion: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class SkillRunRequest(BaseModel):
    pageNo: int = Field(ge=1)
    skillId: str = Field(min_length=1)
    skillVersion: str = Field(min_length=1)
    targetIds: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    upstreamRunIds: list[str] = Field(default_factory=list)


class ObjectOperationRunRequest(BaseModel):
    pageNo: int = Field(ge=1)
    target: OperationTargetRef
    relatedTargets: list[OperationTargetRef] = Field(default_factory=list)
    operationType: OperationType
    instruction: str = Field(min_length=1)
    resultMode: Literal["auto", "decision", "object", "table", "text"] = "auto"


class ObjectOperationResult(BaseModel):
    id: str
    targetId: str
    pageNo: int
    operationType: OperationType
    executionSource: Optional[str] = None
    skillId: Optional[str] = None
    skillVersion: Optional[str] = None
    sourceSkillId: Optional[str] = None
    sourceSkillVersion: Optional[str] = None
    sourceSkillName: Optional[str] = None
    sourceApplicationId: Optional[str] = None
    sourceApplicationVersion: Optional[str] = None
    sourceApplicationStepId: Optional[str] = None
    executor: Optional[str] = None
    configSnapshot: Optional[dict[str, Any]] = None
    resultKind: OperationResultKind
    summary: str
    outputPayload: Optional[Any] = None
    validationErrors: list[str] = Field(default_factory=list)
    runPhase: RunPhase = "completed"
    phaseStartedAt: Optional[str] = None
    lastHeartbeatAt: Optional[str] = None
    llmTraceSummary: Optional["LlmCallTraceSummary"] = None
    evidenceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)
    relatedTargetIds: list[str] = Field(default_factory=list)
    createdAt: str
    source: Literal["runtime"] = "runtime"


class SchemaProcessResult(BaseModel):
    templateId: str
    templateName: str
    templateVersion: Optional[str] = None
    summary: str
    schemaOutput: dict[str, Any] = Field(default_factory=dict)
    validationErrors: list[str] = Field(default_factory=list)
    evidenceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)
    source: Literal["runtime"] = "runtime"


class PromptTraceItem(BaseModel):
    key: PromptTraceKey
    label: str
    sourceMode: ResultSourceMode
    prompt: str
    summary: str


class PageResultPromptTrace(BaseModel):
    text: Optional[PromptTraceItem] = None
    table: Optional[PromptTraceItem] = None


class PageResultSummary(BaseModel):
    id: str
    title: str
    pageNo: int
    pageIndex: int
    status: ResultStatus
    runPhase: RunPhase = "completed"
    phaseStartedAt: Optional[str] = None
    lastHeartbeatAt: Optional[str] = None
    resultStage: ResultStage = "parse"
    runPurpose: RunPurpose = "parse_prompt"
    promptName: str
    runType: PromptRunType = "page"
    startPageNo: Optional[int] = None
    endPageNo: Optional[int] = None
    pageRange: Optional[str] = None
    errorMessage: Optional[str] = None
    schemaTemplateId: Optional[str] = None
    schemaTemplateName: Optional[str] = None
    schemaTemplateVersion: Optional[str] = None
    evidenceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)
    promptTrace: Optional[PageResultPromptTrace] = None
    sourceSections: dict[str, Any] = Field(default_factory=dict)


class PageResultDetail(PageResultSummary):
    promptTrace: Optional[PageResultPromptTrace] = None
    extractionResult: Optional[ExtractionResult] = None
    outputText: Optional[str] = None
    schemaProcessResult: Optional[SchemaProcessResult] = None
    schemaOutput: Optional[dict[str, Any]] = None
    evidenceRefs: list[WorkbenchEvidenceRef] = Field(default_factory=list)
    validationErrors: list[str] = Field(default_factory=list)
    llmTraceSummary: Optional["LlmCallTraceSummary"] = None


class LlmCallTraceSummary(BaseModel):
    callCount: int = 0
    slowCallCount: int = 0
    totalHttpMs: int = 0
    totalMs: int = 0
    inputChars: int = 0
    outputChars: int = 0
    promptTokens: Optional[int] = None
    completionTokens: Optional[int] = None
    totalTokens: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    latestStatus: Optional[str] = None
    latestErrorType: Optional[str] = None


class SummaryResultItem(BaseModel):
    id: str
    title: str
    status: ResultStatus
    runName: str
    detail: str
    pageRange: str
    errorMessage: Optional[str] = None
    updatedAt: Optional[str] = None


class TaskRuntimeInfo(BaseModel):
    parseStatus: TaskStatus
    pagePromptStatus: TaskStatus
    summaryStatus: TaskStatus
    latestRunLabel: str
    failedPageCount: int = 0
    completedPageCount: int = 0
    latestPromptRunAt: Optional[str] = None


class WorkbenchDocument(BaseModel):
    id: str
    fileName: str
    fileType: str
    pdfUrl: str
    markdownUrl: str
    rawJsonUrl: str
    pageCount: int
    sampledPageCount: int


class WorkbenchDocumentTree(BaseModel):
    source: str
    docId: str
    tree: dict[str, Any]
    modules: list[dict[str, Any]] = Field(default_factory=list)
    treeText: str = ""


class WorkbenchTaskDetail(BaseModel):
    task: TaskSummary
    document: WorkbenchDocument
    runtime: TaskRuntimeInfo
    pages: list[WorkbenchPageDetail]
    pageResults: list[PageResultSummary]
    objectOperationResults: list[ObjectOperationResult] = Field(default_factory=list)
    summaryResults: list[SummaryResultItem] = Field(default_factory=list)
    documentTree: Optional[WorkbenchDocumentTree] = None
    applicationRun: Optional[ApplicationRunDetail] = None


class PromptExecutionContext(BaseModel):
    documentId: str
    parseStatus: TaskStatus
    pages: list[WorkbenchPageDetail]


class WorkbenchDataset(BaseModel):
    customers: list[CustomerSummary]
    tasks: list[TaskSummary]
    taskDetails: dict[str, WorkbenchTaskDetail]


class ApplicationStepSelectionRequest(BaseModel):
    kind: ApplicationStepKind
    runId: str = Field(min_length=1)
    stepOrder: int = Field(ge=1)
    semanticLocator: Optional[dict[str, Any]] = None
    skillId: Optional[str] = None
    skillVersion: Optional[str] = None
    skillName: Optional[str] = None
    sourceTaskId: Optional[str] = None
    sourceDocumentId: Optional[str] = None
    sourcePageNo: Optional[int] = None
    sourceRunId: Optional[str] = None
    sourceStatus: Optional[str] = None
    runPurpose: Optional[str] = None
    operationType: Optional[str] = None
    resultMode: Optional[str] = None
    skillSnapshot: Optional[dict[str, Any]] = None
    configSnapshot: Optional[dict[str, Any]] = None
    promptSnapshot: Optional[str] = None
    inputMapping: Optional[dict[str, Any]] = None
    targetMapping: Optional[dict[str, Any]] = None
    dependencyRefs: Optional[dict[str, Any]] = None
    outputSummary: Optional[dict[str, Any]] = None


class SkillSampleContext(BaseModel):
    sampleId: str = ""
    source: str = "inline"
    applicationId: Optional[str] = None
    customerId: Optional[str] = None
    document: dict[str, Any] = Field(default_factory=dict)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    documentTree: Optional[WorkbenchDocumentTree] = None
    operationTargets: list[OperationTargetRef] = Field(default_factory=list)
    sampleSource: dict[str, Any] = Field(default_factory=dict)


class ApplicationDraftCreateRequest(BaseModel):
    taskId: str = ""
    sourceTaskId: Optional[str] = None
    customerId: Optional[str] = None
    sampleContext: Optional[SkillSampleContext] = None
    scope: ApplicationScope = "private"
    name: str = Field(min_length=1)
    description: str = ""
    documentType: str = ""
    scenario: str = ""
    coverText: str = ""
    releaseNotes: str = ""
    steps: list[ApplicationStepSelectionRequest] = Field(default_factory=list)
    publish: bool = False
    version: Optional[str] = None


class ApplicationDraftUpdateRequest(BaseModel):
    scope: Optional[ApplicationScope] = None
    name: Optional[str] = None
    description: Optional[str] = None
    documentType: Optional[str] = None
    scenario: Optional[str] = None
    coverText: Optional[str] = None
    releaseNotes: Optional[str] = None
    status: Optional[ApplicationStatus] = None
    steps: Optional[list[ApplicationStepSelectionRequest]] = None


class ApplicationPublishRequest(BaseModel):
    version: Optional[str] = None
    setAsDefault: bool = True


class ApplicationPlanTarget(BaseModel):
    targetId: str
    pageNo: int
    type: str
    label: str
    excerpt: str = ""
    score: float = 0
    reasons: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplicationRunPlanStep(BaseModel):
    planStepId: str
    sourceStepOrder: int
    kind: ApplicationStepKind
    skillId: str
    skillVersion: str
    skillName: str = ""
    selected: bool = True
    confidence: float = 1
    reason: str = ""
    targetSelector: dict[str, Any] = Field(default_factory=dict)
    targets: list[ApplicationPlanTarget] = Field(default_factory=list)
    locatorResult: dict[str, Any] = Field(default_factory=dict)
    executionGate: dict[str, Any] = Field(default_factory=dict)
    candidateGap: float = 0
    needsReview: bool = False
    upstreamPlanStepIds: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApplicationRunPlanRequest(BaseModel):
    taskId: str = Field(min_length=1)
    version: Optional[str] = None


class ApplicationRunPlanResponse(BaseModel):
    planId: str
    applicationId: str
    taskId: str
    version: str
    status: Literal["ready", "needs_review", "blocked"] = "ready"
    requiresConfirmation: bool = True
    documentProfile: dict[str, Any] = Field(default_factory=dict)
    steps: list[ApplicationRunPlanStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    agentscope: dict[str, Any] = Field(default_factory=dict)
    traceId: Optional[str] = None
    tracePath: Optional[str] = None
    traceLevel: Optional[str] = None


class ApplicationRunRequest(BaseModel):
    taskId: str = Field(min_length=1)
    version: Optional[str] = None
    planId: Optional[str] = None
    confirmedPlan: Optional[ApplicationRunPlanResponse] = None


class SkillDraftFromSampleRequest(BaseModel):
    taskId: str = ""
    applicationId: Optional[str] = None
    sampleContext: Optional[SkillSampleContext] = None
    kind: SkillKind = "operation"
    instruction: str = Field(min_length=1)
    expectedOutput: str = ""
    targetIds: list[str] = Field(default_factory=list)
    pageNo: Optional[int] = Field(default=None, ge=1)
    customerId: Optional[str] = None
    dataTypeName: str = ""
    sourceScope: str = ""
    sourceLabel: str = ""
    sourceText: str = ""
    treeNodeId: Optional[str] = None
    treePath: list[str] = Field(default_factory=list)
    pageRange: Optional[dict[str, Any]] = None
    contentRefs: list[dict[str, Any]] = Field(default_factory=list)
    confirmedSampleOutput: Optional[Any] = None


class SkillDraftFromSampleResponse(BaseModel):
    kind: SkillKind
    taskId: str
    customerId: Optional[str] = None
    sampleSummary: dict[str, Any] = Field(default_factory=dict)
    assist: SkillAssistResponse
    evidenceDiagnostics: dict[str, Any] = Field(default_factory=dict)
    validationReport: dict[str, Any] = Field(default_factory=dict)
    outputContractSummary: dict[str, Any] = Field(default_factory=dict)


class SkillSampleExtractFromSampleResponse(BaseModel):
    kind: SkillKind
    taskId: str
    customerId: Optional[str] = None
    sampleSummary: dict[str, Any] = Field(default_factory=dict)
    extractionResult: ExtractionResult
    rawOutput: Any = Field(default_factory=dict)
    editableOutput: str = ""
    provider: str = "dashscope"
    model: str = ""
    durationMs: int = 0
    inputChars: int = 0
    outputChars: int = 0
    promptTokens: Optional[int] = None
    completionTokens: Optional[int] = None
    totalTokens: Optional[int] = None
    errors: list[str] = Field(default_factory=list)
    evidenceDiagnostics: dict[str, Any] = Field(default_factory=dict)
    validationReport: dict[str, Any] = Field(default_factory=dict)
    outputContractSummary: dict[str, Any] = Field(default_factory=dict)
    traceId: Optional[str] = None
    tracePath: Optional[str] = None
    traceLevel: Optional[Literal["full"]] = None


class SkillSampleLocateAndExtractRequest(BaseModel):
    taskId: str = ""
    applicationId: Optional[str] = None
    sampleContext: Optional[SkillSampleContext] = None
    query: str = Field(min_length=1)
    customerId: Optional[str] = None
    outputPreference: Literal["auto", "field_list", "data_table", "record_collection", "notes"] = "auto"
    locatorInstruction: str = ""
    extraInstruction: str = ""
    expectedOutput: str = ""
    selectedCandidateId: Optional[str] = None
    runExtraction: bool = True


class SkillSampleLocateCandidate(BaseModel):
    nodeId: str
    title: str = ""
    type: str = ""
    pageNo: int = 1
    pageRange: str = ""
    path: list[str] = Field(default_factory=list)
    excerpt: str = ""
    score: float = 0
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class SkillSampleLocatedSource(BaseModel):
    mode: str = "tree"
    kind: ApplicationStepKind = "extraction"
    title: str = ""
    summary: str = ""
    sourceScope: str = ""
    sourceText: str = ""
    pageNo: Optional[int] = None
    pageIndex: Optional[int] = None
    targetIds: list[str] = Field(default_factory=list)
    treeNodeId: Optional[str] = None
    treePath: list[str] = Field(default_factory=list)
    pageRange: Optional[dict[str, Any]] = None
    contentRefs: list[dict[str, Any]] = Field(default_factory=list)
    locatorReason: str = ""


class SkillSampleLocateAndExtractResponse(BaseModel):
    kind: SkillKind = "extraction"
    taskId: str
    customerId: Optional[str] = None
    status: Literal["located", "extracted", "needs_review", "not_found"] = "not_found"
    query: str = ""
    dataTypeName: str = ""
    outputPreference: str = "auto"
    locatedSource: Optional[SkillSampleLocatedSource] = None
    candidates: list[SkillSampleLocateCandidate] = Field(default_factory=list)
    locatorResult: dict[str, Any] = Field(default_factory=dict)
    locatorProfile: dict[str, Any] = Field(default_factory=dict)
    locatorSkillText: str = ""
    sampleSummary: dict[str, Any] = Field(default_factory=dict)
    extractionResult: Optional[ExtractionResult] = None
    rawOutput: Any = Field(default_factory=dict)
    editableOutput: str = ""
    provider: str = ""
    model: str = ""
    durationMs: int = 0
    inputChars: int = 0
    outputChars: int = 0
    promptTokens: Optional[int] = None
    completionTokens: Optional[int] = None
    totalTokens: Optional[int] = None
    errors: list[str] = Field(default_factory=list)
    evidenceDiagnostics: dict[str, Any] = Field(default_factory=dict)
    validationReport: dict[str, Any] = Field(default_factory=dict)
    outputContractSummary: dict[str, Any] = Field(default_factory=dict)
    traceId: Optional[str] = None
    tracePath: Optional[str] = None
    traceLevel: Optional[Literal["full"]] = None


class SkillSampleProcessFromSampleResponse(BaseModel):
    kind: SkillKind
    taskId: str
    customerId: Optional[str] = None
    sampleSummary: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    resultKind: OperationResultKind = "object"
    outputPayload: Any = Field(default_factory=dict)
    validationErrors: list[str] = Field(default_factory=list)
    rawOutput: Any = Field(default_factory=dict)
    editableOutput: str = ""
    provider: str = "dashscope"
    model: str = ""
    durationMs: int = 0
    inputChars: int = 0
    outputChars: int = 0
    promptTokens: Optional[int] = None
    completionTokens: Optional[int] = None
    totalTokens: Optional[int] = None
    errors: list[str] = Field(default_factory=list)
    evidenceDiagnostics: dict[str, Any] = Field(default_factory=dict)
    validationReport: dict[str, Any] = Field(default_factory=dict)
    outputContractSummary: dict[str, Any] = Field(default_factory=dict)


class ApplicationStepSnapshot(BaseModel):
    stepOrder: int
    kind: ApplicationStepKind
    skillId: str
    skillVersion: str
    skillName: str = ""
    sourceTaskId: Optional[str] = None
    sourceDocumentId: Optional[str] = None
    sourcePageNo: Optional[int] = None
    sourceRunId: Optional[str] = None
    sourceStatus: Optional[str] = None
    runPurpose: Optional[str] = None
    operationType: Optional[str] = None
    resultMode: Optional[str] = None
    skillSnapshot: dict[str, Any] = Field(default_factory=dict)
    configSnapshot: dict[str, Any] = Field(default_factory=dict)
    promptSnapshot: str = ""
    inputMapping: dict[str, Any] = Field(default_factory=dict)
    targetMapping: dict[str, Any] = Field(default_factory=dict)
    dependencyRefs: dict[str, Any] = Field(default_factory=dict)
    outputSummary: dict[str, Any] = Field(default_factory=dict)


class ApplicationSummary(BaseModel):
    id: str
    customerId: str
    scope: ApplicationScope = "private"
    name: str
    description: str = ""
    documentType: str = ""
    scenario: str = ""
    coverText: str = ""
    releaseNotes: str = ""
    status: ApplicationStatus
    defaultVersion: Optional[str] = None
    latestPublishedVersion: Optional[str] = None
    sourceTaskId: Optional[str] = None
    sourceDocumentId: Optional[str] = None
    stepCount: int = 0
    createdByUserId: Optional[str] = None
    createdByName: Optional[str] = None
    updatedByUserId: Optional[str] = None
    updatedByName: Optional[str] = None
    publishedAt: Optional[str] = None
    createdAt: str
    updatedAt: str


class ApplicationVersionSummary(BaseModel):
    version: str
    status: ApplicationStatus
    isDefault: bool = False
    stepCount: int = 0
    publishedByUserId: Optional[str] = None
    publishedByName: Optional[str] = None
    publishedAt: Optional[str] = None
    createdAt: str
    updatedAt: str


class ApplicationDetail(ApplicationSummary):
    resolvedVersion: Optional[str] = None
    steps: list[ApplicationStepSnapshot] = Field(default_factory=list)
    versions: list[ApplicationVersionSummary] = Field(default_factory=list)


class ApplicationRunStepSummary(BaseModel):
    stepOrder: int
    kind: ApplicationStepKind
    skillId: str
    skillVersion: str
    skillName: str = ""
    sourcePageNo: Optional[int] = None
    sourceRunId: Optional[str] = None
    executionRunId: Optional[str] = None
    status: TaskStatus
    inputMapping: dict[str, Any] = Field(default_factory=dict)
    targetMapping: dict[str, Any] = Field(default_factory=dict)
    configSnapshot: dict[str, Any] = Field(default_factory=dict)
    promptSnapshot: str = ""
    outputSummary: dict[str, Any] = Field(default_factory=dict)
    errorMessage: Optional[str] = None
    createdAt: str
    updatedAt: str


class ApplicationRunSummary(BaseModel):
    id: str
    applicationId: str
    applicationName: str = ""
    customerId: str
    taskId: str
    documentId: str
    version: str
    status: TaskStatus
    stepCount: int = 0
    completedStepCount: int = 0
    triggeredByUserId: Optional[str] = None
    triggeredByName: Optional[str] = None
    errorMessage: Optional[str] = None
    createdAt: str
    updatedAt: str


class ApplicationRunDetail(ApplicationRunSummary):
    steps: list[ApplicationRunStepSummary] = Field(default_factory=list)
    finalOutput: Optional[dict[str, Any]] = None


class ApplicationRunReviewFeedbackRequest(BaseModel):
    stepOrder: int = Field(ge=1)
    correctedOutput: dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list)
    markAsRegression: bool = True


class ApplicationRunReviewFeedbackResponse(BaseModel):
    run: ApplicationRunDetail
    feedback: dict[str, Any] = Field(default_factory=dict)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    pageSize: int


class DocumentSummary(BaseModel):
    id: str
    customerId: str
    fileName: str
    fileType: str
    sourceUrl: str
    objectKey: str
    pageCount: int
    parseStatus: str
    uploadedByName: str
    uploadedAt: str
    updatedAt: str
    latestTaskId: Optional[str] = None


class DocumentDetail(DocumentSummary):
    markdownUrl: Optional[str] = None
    rawJsonUrl: Optional[str] = None
    layoutUrl: Optional[str] = None
    blockListUrl: Optional[str] = None
    modelJsonUrl: Optional[str] = None
    artifactBaseUrl: Optional[str] = None
    parseTaskId: Optional[str] = None
    parseError: Optional[str] = None
    relatedTasks: list[TaskSummary] = Field(default_factory=list)


class CreateCustomerRequest(BaseModel):
    name: str = Field(min_length=1)
    projectCode: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    description: str = ""


class CreateCustomerProvisionRequest(BaseModel):
    customer: CreateCustomerRequest
    account: CreateCustomerAccountRequest


class CreateCustomerProvisionResponse(BaseModel):
    customer: CustomerSummary
    account: AuthUserResponse


class CustomerWorkspaceResponse(BaseModel):
    customer: CustomerSummary
    documents: list[DocumentSummary]
    tasks: list[TaskSummary]


class AdminOverviewResponse(BaseModel):
    customers: list[CustomerSummary]
    tasks: list[TaskSummary]
    totalCustomers: int
    totalDocuments: int
    totalTasks: int


class UserTaskListResponse(BaseModel):
    userId: str
    tasks: list[TaskSummary]


class OssUploadContractRequest(BaseModel):
    fileName: str = Field(min_length=1)
    contentType: str = Field(min_length=1)


class OssUploadContractResponse(BaseModel):
    provider: str
    bucket: str
    region: str
    objectKey: str
    uploadUrl: str
    publicUrl: str
    headers: dict[str, str]
    expiresAt: str


class RegisterDocumentRequest(BaseModel):
    fileName: str = Field(min_length=1)
    fileType: str = Field(min_length=1)
    objectKey: str = Field(min_length=1)
    sourceUrl: str = Field(min_length=1)
    pageCount: int = Field(default=0, ge=0)
    uploadedByUserId: str = Field(min_length=1)
    uploadedByName: str = Field(min_length=1)
    roleScope: list[UserRole] = Field(default_factory=lambda: ["admin", "customer"])
    taskName: Optional[str] = None


class RegisterDocumentResponse(BaseModel):
    document: DocumentDetail
    createdTask: TaskSummary


class ParseProgress(BaseModel):
    extractedPages: int = 0
    totalPages: int = 0
    startTime: Optional[str] = None


class ParseArtifactUrls(BaseModel):
    artifactBaseUrl: Optional[str] = None
    fullZipUrl: Optional[str] = None
    markdownUrl: Optional[str] = None
    rawJsonUrl: Optional[str] = None
    layoutUrl: Optional[str] = None
    blockListUrl: Optional[str] = None
    modelJsonUrl: Optional[str] = None


class ParseTaskStatusResponse(BaseModel):
    taskId: str
    customerId: str
    documentId: str
    state: TaskStatus
    mineruState: Optional[str] = None
    mineruTaskId: Optional[str] = None
    errorMessage: Optional[str] = None
    progress: ParseProgress = Field(default_factory=ParseProgress)
    artifacts: ParseArtifactUrls = Field(default_factory=ParseArtifactUrls)


class UploadAndParseResponse(BaseModel):
    document: DocumentDetail
    createdTask: TaskSummary
    parse: ParseTaskStatusResponse


class ApplicationUploadRunResponse(BaseModel):
    mode: Literal["api", "async"] = "api"
    applicationId: str
    version: str
    taskId: str
    runId: str
    message: str = ""
    parse: ParseTaskStatusResponse
    applicationRun: ApplicationRunDetail
    finalOutput: Optional[dict[str, Any]] = None
    stepResults: list[dict[str, Any]] = Field(default_factory=list)


class PromptExecutionPageContextPage(BaseModel):
    pageIndex: int = 0
    pageNo: int = Field(ge=1)
    title: str = ""
    summary: str = ""
    markdownSegments: list[WorkbenchMarkdownSegment] = Field(default_factory=list)
    blocks: list[WorkbenchBlock] = Field(default_factory=list)
    rawItems: list[dict[str, Any]] = Field(default_factory=list)
    pageSize: tuple[float, float] = (0.0, 0.0)


class PromptExecutionPageContext(BaseModel):
    pages: list[PromptExecutionPageContextPage] = Field(default_factory=list)


class PromptExecutionRequest(BaseModel):
    promptName: str = Field(min_length=1)
    promptText: str = Field(min_length=1)
    startPageNo: int = Field(ge=1)
    endPageNo: Optional[int] = Field(default=None, ge=1)
    runMode: Literal["page", "page_group", "auto"] = "page"
    pageGroupSize: Optional[int] = Field(default=None, ge=1)
    templateId: Optional[str] = None
    runName: Optional[str] = None
    createSummary: bool = False
    runPurpose: RunPurpose = "parse_prompt"
    pageContext: Optional[PromptExecutionPageContext] = None
    tableTaskMode: TableTaskMode = "parse_json"


class SchemaRunRequest(BaseModel):
    templateId: str = Field(min_length=1)
    startPageNo: int = Field(ge=1)
    endPageNo: Optional[int] = Field(default=None, ge=1)
    runMode: Literal["page", "page_group", "auto"] = "page"
    pageGroupSize: Optional[int] = Field(default=None, ge=1)
    runName: Optional[str] = None
    createSummary: bool = False


class PostProcessRunRequest(BaseModel):
    instruction: str = Field(min_length=1)
    startPageNo: int = Field(ge=1)
    endPageNo: Optional[int] = Field(default=None, ge=1)
    runMode: Literal["page", "page_group", "auto"] = "page"
    pageGroupSize: Optional[int] = Field(default=None, ge=1)
    responseMode: Literal["auto", "json", "table", "issues", "text"] = "auto"
    runName: Optional[str] = None
    createSummary: bool = False


class FailedPromptRerunRequest(BaseModel):
    runIds: list[str] = Field(default_factory=list)
    createSummary: bool = False


class SummaryExecutionRequest(BaseModel):
    promptName: str = Field(default="文档级汇总", min_length=1)
    promptText: str = Field(
        default="基于已完成的分页或页组结果，汇总整份文档的关键结论、风险与证据页范围。",
        min_length=1,
    )
    runName: Optional[str] = None


class PromptRunRecordResponse(BaseModel):
    id: str
    runType: PromptRunType
    runPurpose: RunPurpose = "parse_prompt"
    runName: str
    promptName: str
    promptText: str
    startPageNo: int
    endPageNo: int
    pageRange: str
    status: TaskStatus
    runPhase: RunPhase = "queued"
    phaseStartedAt: Optional[str] = None
    lastHeartbeatAt: Optional[str] = None
    errorMessage: Optional[str] = None
    outputText: Optional[str] = None
    inputPath: Optional[str] = None
    outputPath: Optional[str] = None
    updatedAt: str
    schemaTemplateId: Optional[str] = None
    schemaTemplateName: Optional[str] = None
    schemaTemplateVersion: Optional[str] = None


class PromptExecutionResponse(BaseModel):
    taskDetail: Optional[WorkbenchTaskDetail] = None
    runs: list[PromptRunRecordResponse]
    summaryRun: Optional[PromptRunRecordResponse] = None


class ObjectOperationExecutionResponse(BaseModel):
    run: PromptRunRecordResponse
    result: Optional[ObjectOperationResult] = None


ObjectOperationResult.model_rebuild()
PageResultDetail.model_rebuild()
SchemaFieldDefinition.model_rebuild()
