"""Core domain records used by the in-memory repository.

These records keep business storage concerns separate from the API DTOs that
mirror the frontend workbench contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class CustomerRecord:
    id: str
    name: str
    projectCode: str
    owner: str
    description: str
    documentCount: int
    taskCount: int
    createdAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DocumentRecord:
    id: str
    customerId: str
    fileName: str
    fileType: str
    sourceUrl: str
    objectKey: str
    pageCount: int
    parseStatus: str
    uploadedByUserId: str
    uploadedByName: str
    uploadedAt: str
    updatedAt: str
    markdownUrl: str | None = None
    rawJsonUrl: str | None = None
    layoutUrl: str | None = None
    blockListUrl: str | None = None
    modelJsonUrl: str | None = None
    artifactBaseUrl: str | None = None
    parseTaskId: str | None = None
    parseError: str | None = None
    latestTaskId: str | None = None


@dataclass
class TaskRecord:
    id: str
    customerId: str
    documentId: str
    customerName: str
    taskName: str
    documentName: str
    roleScope: list[str]
    owner: str
    ownerUserId: str
    status: str
    uploadTime: str
    updatedAt: str
    pageCount: int
    promptRunCount: int
    summary: str


@dataclass
class PageTaskRecord:
    id: str
    taskId: str
    pageNo: int
    pageIndex: int
    promptName: str
    status: str


@dataclass
class SummaryTaskRecord:
    id: str
    taskId: str
    runName: str
    status: str


@dataclass
class PromptConfigRecord:
    id: str
    taskId: str
    promptName: str
    promptText: str
    startPageNo: int
    endPageNo: int
    runPurpose: str = "parse_prompt"
    sourceTemplateId: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PromptRunRecord:
    id: str
    taskId: str
    documentId: str
    runType: str
    runName: str
    promptName: str
    promptText: str
    startPageNo: int
    endPageNo: int
    status: str
    runPhase: str = "queued"
    runPurpose: str = "parse_prompt"
    promptConfigId: str | None = None
    templateId: str | None = None
    schemaTemplateName: str | None = None
    schemaTemplateVersion: str | None = None
    llmProvider: str | None = None
    llmModel: str | None = None
    errorMessage: str | None = None
    inputPath: str | None = None
    outputPath: str | None = None
    outputText: str | None = None
    inputFactsSnapshot: dict[str, Any] | None = None
    schemaDefinition: dict[str, Any] | None = None
    schemaOutput: dict[str, Any] | None = None
    validationErrors: list[str] = field(default_factory=list)
    structuredExtractionResult: dict[str, Any] | None = None
    structuredProcessResult: dict[str, Any] | None = None
    structuredBusinessResult: dict[str, Any] | None = None
    evidenceBlockIds: list[str] = field(default_factory=list)
    evidenceExcerpts: list[str] = field(default_factory=list)
    phaseStartedAt: Optional[str] = None
    lastHeartbeatAt: Optional[str] = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class LlmCallTraceRecord:
    id: str
    taskId: str
    documentId: str
    runId: str
    stage: str
    requestKind: str
    status: str
    runPhase: str
    provider: Optional[str] = None
    model: Optional[str] = None
    skillId: Optional[str] = None
    inputChars: int = 0
    outputChars: int = 0
    promptTokens: Optional[int] = None
    completionTokens: Optional[int] = None
    totalTokens: Optional[int] = None
    httpMs: Optional[int] = None
    totalMs: Optional[int] = None
    errorType: Optional[str] = None
    requestObjectKey: Optional[str] = None
    responseObjectKey: Optional[str] = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TaskResultArtifactRecord:
    id: str
    taskId: str
    documentId: str
    stage: str
    artifactKind: str
    objectKey: str
    contentHash: str
    sizeBytes: int
    contentType: str
    pageNo: int | None = None
    runId: str | None = None
    summary: dict[str, Any] | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TaskOperationTargetRecord:
    storageId: str
    taskId: str
    pageNo: int
    targetId: str
    sourceRunId: str
    targetType: str
    label: str
    valueText: str = ""
    excerpt: str | None = None
    blockPosition: str | None = None
    fieldKey: str | None = None
    rowIndex: int | None = None
    rowCount: int | None = None
    columnCount: int | None = None
    headers: list[str] = field(default_factory=list)
    blockIds: list[str] = field(default_factory=list)
    groupLabel: str | None = None
    dataObjectKey: str | None = None
    dataContentHash: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ParseJobRecord:
    taskId: str
    customerId: str
    documentId: str
    state: str
    mineruState: str | None = None
    mineruTaskId: str | None = None
    errorMessage: str | None = None
    extractedPages: int = 0
    totalPages: int = 0
    startTime: str | None = None
    fullZipSourceUrl: str | None = None
    fullZipPath: str | None = None
    markdownPath: str | None = None
    rawJsonPath: str | None = None
    layoutPath: str | None = None
    blockListPath: str | None = None
    modelJsonPath: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SchemaTemplateRecord:
    id: str
    name: str
    description: str
    documentType: str
    scope: str
    schemaDefinition: dict[str, Any]
    instructions: str = ""
    bindingConfig: dict[str, Any] | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class BusinessSkillRecord:
    id: str
    version: str
    name: str
    category: str
    targetTypes: list[str]
    executor: str
    resultKind: str
    renderer: str
    configSchema: dict[str, Any]
    outputSchema: dict[str, Any]
    status: str = "active"
    sourceTypes: list[str] = field(default_factory=list)
    promptTemplate: str = ""
    examples: list[dict[str, Any]] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    skillTextObjectKey: str = ""
    skillTextHash: str = ""
    skillTextSizeBytes: int = 0
    skillTextPreview: str = ""
    skillText: str = ""
    enabled: bool = True
    customerId: str | None = None
    tags: list[str] = field(default_factory=list)
    latestTestStatus: str | None = None
    sampleCount: int = 0
    testRunCount: int = 0
    lastTestedAt: str | None = None
    createdBy: str | None = None
    updatedBy: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SkillSampleRecord:
    id: str
    kind: str
    skillId: str
    version: str
    customerId: str | None
    instruction: str
    objectKey: str
    contentType: str
    fileName: str
    sizeBytes: int
    preview: str
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SkillTestRunRecord:
    id: str
    kind: str
    skillId: str
    version: str
    customerId: str | None
    status: str
    valid: bool
    errors: list[str]
    summary: dict[str, Any] | None = None
    inputObjectKey: str | None = None
    resultObjectKey: str | None = None
    factsObjectKey: str | None = None
    llmObjectKey: str | None = None
    result: dict[str, Any] | None = None
    facts: dict[str, Any] | None = None
    sampleId: str | None = None
    provider: str | None = None
    model: str | None = None
    durationMs: int | None = None
    inputChars: int = 0
    outputChars: int = 0
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ApplicationRecord:
    id: str
    customerId: str
    name: str
    scope: str = "private"
    description: str = ""
    documentType: str = ""
    scenario: str = ""
    coverText: str = ""
    releaseNotes: str = ""
    status: str = "draft"
    defaultVersion: str | None = None
    latestPublishedVersion: str | None = None
    sourceTaskId: str | None = None
    sourceDocumentId: str | None = None
    stepCount: int = 0
    createdByUserId: str | None = None
    createdByName: str | None = None
    updatedByUserId: str | None = None
    updatedByName: str | None = None
    publishedAt: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ApplicationVersionRecord:
    storageId: str
    applicationId: str
    customerId: str
    version: str
    name: str
    description: str = ""
    documentType: str = ""
    scenario: str = ""
    coverText: str = ""
    releaseNotes: str = ""
    status: str = "published"
    isDefault: bool = False
    sourceTaskId: str | None = None
    sourceDocumentId: str | None = None
    stepCount: int = 0
    publishedByUserId: str | None = None
    publishedByName: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    publishedAt: str | None = None


@dataclass
class ApplicationStepRecord:
    storageId: str
    applicationId: str
    versionLabel: str
    stepOrder: int
    kind: str
    skillId: str
    skillVersion: str
    skillName: str = ""
    sourceTaskId: str | None = None
    sourceDocumentId: str | None = None
    sourcePageNo: int | None = None
    sourceRunId: str | None = None
    sourceStatus: str | None = None
    runPurpose: str | None = None
    operationType: str | None = None
    resultMode: str | None = None
    skillSnapshot: dict[str, Any] = field(default_factory=dict)
    configSnapshot: dict[str, Any] = field(default_factory=dict)
    promptSnapshot: str = ""
    inputMapping: dict[str, Any] = field(default_factory=dict)
    targetMapping: dict[str, Any] = field(default_factory=dict)
    dependencyRefs: dict[str, Any] = field(default_factory=dict)
    outputSummary: dict[str, Any] = field(default_factory=dict)
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ApplicationRunRecord:
    id: str
    applicationId: str
    customerId: str
    taskId: str
    documentId: str
    version: str
    status: str = "running"
    stepCount: int = 0
    completedStepCount: int = 0
    triggeredByUserId: str | None = None
    triggeredByName: str | None = None
    errorMessage: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ApplicationRunStepRecord:
    storageId: str
    applicationRunId: str
    applicationId: str
    version: str
    stepOrder: int
    kind: str
    skillId: str
    skillVersion: str
    skillName: str = ""
    sourceApplicationStepId: str | None = None
    sourcePageNo: int | None = None
    sourceRunId: str | None = None
    executionRunId: str | None = None
    status: str = "running"
    inputMapping: dict[str, Any] = field(default_factory=dict)
    targetMapping: dict[str, Any] = field(default_factory=dict)
    configSnapshot: dict[str, Any] = field(default_factory=dict)
    promptSnapshot: str = ""
    outputSummary: dict[str, Any] = field(default_factory=dict)
    errorMessage: str | None = None
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
