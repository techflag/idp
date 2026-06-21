"""Schemas for the file-backed extraction skill prototype lab."""

from __future__ import annotations

# @edition-scope shared-api-contract
# @capability skill.prototypeOptimization
# @community-export include

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SourceFormat = Literal["text", "html", "json"]
PrototypeJobKind = Literal["candidate_generation"]
PrototypeJobState = Literal["queued", "running", "completed", "failed", "cancelled"]
PrototypeStatus = Literal[
    "draft",
    "generating",
    "evaluating",
    "recommended",
    "archived",
    "in_skillnet",
    "ready_for_gate",
    "gate_pending",
    "gate_approved",
    "gate_rejected",
]
GateDecision = Literal["pending", "approved", "rejected"]
PublishScope = Literal["platform", "customer", "skillnet_only"]


class PrototypeSource(BaseModel):
    format: SourceFormat = "text"
    content: str = ""
    fileName: str = "manual-input.txt"
    preview: str = ""


class EvaluationDatasetItem(BaseModel):
    id: str = ""
    name: str = ""
    sourceFormat: SourceFormat = "text"
    sampleText: str = ""
    sampleHtml: str = ""
    samplePayloadJson: Optional[Any] = None
    expectedOutput: Optional[Any] = None
    note: str = ""


class CandidateSkillVersion(BaseModel):
    id: str
    version: str
    name: str
    skillText: str = ""
    score: float = 0
    businessScore: float = 0
    protocolScore: float = 0
    latencyScore: float = 0
    tokenCost: int = 0
    durationMs: int = 0
    status: Literal["draft", "generated", "evaluated", "recommended", "failed"] = "generated"
    errors: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    createdAt: str


class CandidateDetailResponse(BaseModel):
    candidate: CandidateSkillVersion
    scoreBreakdown: dict[str, Any] = Field(default_factory=dict)
    sampleResults: list[dict[str, Any]] = Field(default_factory=list)
    patchEdits: list[dict[str, Any]] = Field(default_factory=list)
    artifactPath: str = ""
    resultPath: str = ""
    patchPath: str = ""
    applyReportPath: str = ""
    skillText: str = ""


class EvaluationRun(BaseModel):
    id: str
    status: Literal["pending", "running", "completed", "failed"] = "completed"
    candidateCount: int = 0
    sampleCount: int = 0
    recommendedCandidateId: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)
    items: list[dict[str, Any]] = Field(default_factory=list)
    createdAt: str
    completedAt: Optional[str] = None


class SkillNetEntry(BaseModel):
    id: str
    prototypeId: str
    candidateId: str
    name: str
    version: str
    status: Literal["private", "ready_for_gate", "published"] = "private"
    qualityScore: float = 0
    packagePath: str = ""
    evaluateReportPath: str = ""
    analyzeReportPath: str = ""
    createdAt: str


class MainlineGateRecord(BaseModel):
    id: str
    status: GateDecision = "pending"
    checks: list[dict[str, Any]] = Field(default_factory=list)
    reviewer: str = ""
    comment: str = ""
    createdAt: str
    decidedAt: Optional[str] = None


class PublishedSkillPackage(BaseModel):
    id: str
    prototypeId: str
    candidateId: str
    skillNetEntryId: str = ""
    name: str
    version: str
    scope: PublishScope
    target: str = ""
    packagePath: str = ""
    createdAt: str


class PrototypeProject(BaseModel):
    id: str
    name: str
    description: str = ""
    extractionGoal: str
    fieldRequirements: str = ""
    outputExample: str = ""
    source: PrototypeSource
    status: PrototypeStatus = "draft"
    baselineSkillText: str = ""
    candidates: list[CandidateSkillVersion] = Field(default_factory=list)
    dataset: list[EvaluationDatasetItem] = Field(default_factory=list)
    evaluationRuns: list[EvaluationRun] = Field(default_factory=list)
    recommendedCandidateId: Optional[str] = None
    skillNetEntry: Optional[SkillNetEntry] = None
    gateRecord: Optional[MainlineGateRecord] = None
    publishedPackage: Optional[PublishedSkillPackage] = None
    createdBy: str = ""
    createdAt: str
    updatedAt: str


class PrototypeListResponse(BaseModel):
    items: list[PrototypeProject]
    total: int


class PrototypeJobStatus(BaseModel):
    id: str
    prototypeId: str
    kind: PrototypeJobKind = "candidate_generation"
    status: PrototypeJobState = "queued"
    phase: str = "queued"
    message: str = ""
    progress: dict[str, Any] = Field(default_factory=dict)
    logTail: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    createdAt: str
    startedAt: Optional[str] = None
    updatedAt: str
    completedAt: Optional[str] = None


class PrototypeCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    extractionGoal: str = Field(min_length=1)
    fieldRequirements: str = ""
    outputExample: str = ""
    source: PrototypeSource
    dataset: list[EvaluationDatasetItem] = Field(default_factory=list)


class PrototypeUpdateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    extractionGoal: str = Field(min_length=1)
    fieldRequirements: str = ""
    outputExample: str = ""
    source: PrototypeSource


class PrototypeUpdateDatasetRequest(BaseModel):
    dataset: list[EvaluationDatasetItem] = Field(default_factory=list)


class BaselineGenerateRequest(BaseModel):
    instruction: str = ""


class BaselineUpdateRequest(BaseModel):
    skillText: str = ""


class CandidateGenerateRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=20)


class SkillNetCreateRequest(BaseModel):
    candidateId: Optional[str] = None


class MainlineGateRequest(BaseModel):
    decision: GateDecision = "pending"
    reviewer: str = ""
    comment: str = ""


class PublishRequest(BaseModel):
    scope: PublishScope = "platform"
    target: str = ""
