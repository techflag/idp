import type {
  ApplicationSourceRunOption,
  ApplicationStepKind,
  ApplicationWorkshopStepDraft,
  ApplicationWorkshopStepDraftUpsertRequest,
} from '../types/workbench'
import type {
  ProcessingStepDraft,
  SampleExtractionDraft,
  SampleProcessingDraft,
  SampleSource,
  SampleSourceMode,
  SkillDevelopmentAsset,
} from '../types/applicationWorkshop'
import { cloneJson } from './objectData'

export function dedupeServerStepDrafts(records: ApplicationWorkshopStepDraft[]) {
  const preferredByKey = new Map<string, ApplicationWorkshopStepDraft>()
  const removedIds: string[] = []
  for (const record of records) {
    const key = stepDraftStableKey(record)
    const existing = preferredByKey.get(key)
    if (!existing) {
      preferredByKey.set(key, record)
      continue
    }
    const preferred = preferStepDraft(existing, record)
    const removed = preferred.id === existing.id ? record : existing
    preferredByKey.set(key, preferred)
    removedIds.push(removed.id)
  }
  return {
    records: [...preferredByKey.values()].sort(compareStepDraftsForDisplay),
    removedIds,
  }
}

export function normalizeLegacyProcessingStep(value: unknown): ProcessingStepDraft | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Partial<ProcessingStepDraft>
  const kind = item.kind === 'operation' ? 'operation' : 'extraction'
  const status = item.status === 'verified' ? 'verified' : 'generated'
  const dataTypeName = String(item.dataTypeName || item.skillName || '').trim()
  const skillName = String(item.skillName || dataTypeName || '').trim()
  if (!dataTypeName && !skillName) return null
  const sampleSource = normalizePersistedSampleSource(item.sampleSource)
  return {
    id: String(item.id || `legacy:${kind}:${dataTypeName || skillName}`),
    kind,
    status,
    dataTypeName: dataTypeName || skillName,
    goal: String(item.goal || ''),
    expectedOutput: String(item.expectedOutput || ''),
    sourceTitle: String(item.sourceTitle || ''),
    sourceScope: String(item.sourceScope || ''),
    skillText: String(item.skillText || ''),
    skillName: skillName || defaultStepName(kind, dataTypeName || skillName),
    errors: Array.isArray(item.errors) ? item.errors.map(String) : [],
    model: String(item.model || ''),
    sampleSource,
    sampleExtraction: normalizePersistedSampleExtraction(item.sampleExtraction),
    sampleProcessing: normalizePersistedSampleProcessing(item.sampleProcessing),
    skillDevelopment: normalizePersistedSkillDevelopment(item.skillDevelopment),
    semanticLocator: item.semanticLocator || sampleSource?.locator,
    runOption: normalizePersistedRunOption(item.runOption),
  }
}

export function processingStepFromServerDraft(record: ApplicationWorkshopStepDraft): ProcessingStepDraft {
  const kind = record.kind === 'operation' ? 'operation' : 'extraction'
  const status = record.status === 'verified' ? 'verified' : 'generated'
  const dataTypeName = record.dataTypeName.trim() || record.skillName.trim() || '未命名数据类型'
  const sampleSource = normalizePersistedSampleSource(record.sampleSource)
  return {
    id: record.id,
    isLight: Boolean(record.isLight),
    kind,
    status,
    dataTypeName,
    locatorInstruction: String(record.semanticLocator?.locatorInstruction || sampleSource?.locator?.locatorInstruction || ''),
    goal: record.goal,
    expectedOutput: record.expectedOutput,
    sourceTitle: record.sourceTitle,
    sourceScope: record.sourceScope,
    skillText: record.skillText,
    skillName: record.skillName || defaultStepName(kind, dataTypeName),
    errors: [...record.errors],
    model: record.model,
    sampleSource,
    sampleExtraction: normalizePersistedSampleExtraction(record.sampleExtraction),
    sampleProcessing: normalizePersistedSampleProcessing(record.sampleProcessing),
    skillDevelopment: normalizePersistedSkillDevelopment(record.skillDevelopment),
    semanticLocator: record.semanticLocator || sampleSource?.locator,
    runOption: normalizePersistedRunOption(record.runOption),
  }
}

export function processingStepToServerDraft(step: ProcessingStepDraft): ApplicationWorkshopStepDraftUpsertRequest {
  const semanticLocator = cloneJson(step.semanticLocator) as Record<string, unknown> | null
  if (semanticLocator && step.locatorInstruction) {
    semanticLocator.locatorInstruction = step.locatorInstruction
  }
  return {
    id: step.id,
    kind: step.kind,
    status: step.status,
    dataTypeName: step.dataTypeName,
    goal: step.goal,
    expectedOutput: step.expectedOutput,
    sourceTitle: step.sourceTitle,
    sourceScope: step.sourceScope,
    skillText: step.skillText,
    skillName: step.skillName,
    errors: [...step.errors],
    model: step.model,
    sampleSource: cloneJson(step.sampleSource) as Record<string, unknown> | null,
    semanticLocator,
    sampleExtraction: cloneJson(step.sampleExtraction) as Record<string, unknown> | null,
    sampleProcessing: cloneJson(step.sampleProcessing) as Record<string, unknown> | null,
    skillDevelopment: cloneJson(step.skillDevelopment) as Record<string, unknown> | null,
    runOption: cloneJson(step.runOption) as ApplicationSourceRunOption | null,
  }
}

export function normalizePersistedSampleSource(value: unknown): SampleSource | undefined {
  if (!value || typeof value !== 'object') return undefined
  const source = value as Partial<SampleSource>
  const mode = normalizeSampleSourceMode(source.mode)
  return {
    mode,
    kind: source.kind === 'operation' ? 'operation' : 'extraction',
    title: String(source.title || ''),
    summary: String(source.summary || ''),
    sourceScope: String(source.sourceScope || ''),
    sourceText: String(source.sourceText || ''),
    pageNo: typeof source.pageNo === 'number' ? source.pageNo : null,
    pageIndex: typeof source.pageIndex === 'number' ? source.pageIndex : null,
    targetIds: Array.isArray(source.targetIds) ? source.targetIds.map(String) : [],
    treeNodeId: typeof source.treeNodeId === 'string' ? source.treeNodeId : undefined,
    treePath: Array.isArray(source.treePath) ? source.treePath.map(String) : [],
    pageRange: source.pageRange && typeof source.pageRange === 'object' ? source.pageRange as SampleSource['pageRange'] : undefined,
    contentRefs: Array.isArray(source.contentRefs) ? source.contentRefs as Array<Record<string, unknown>> : [],
    locator: source.locator && typeof source.locator === 'object' ? source.locator as Record<string, unknown> : undefined,
  }
}

export function normalizePersistedRunOption(value: unknown): ApplicationSourceRunOption | undefined {
  if (!value || typeof value !== 'object') return undefined
  return value as ApplicationSourceRunOption
}

export function normalizePersistedSampleExtraction(value: unknown): SampleExtractionDraft | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Partial<SampleExtractionDraft>
  if (!item.result || typeof item.result !== 'object') return undefined
  return {
    status: item.status === 'confirmed' ? 'confirmed' : 'draft',
    result: item.result,
    editableOutput: String(item.editableOutput || ''),
    rawOutput: item.rawOutput,
    model: String(item.model || ''),
    durationMs: Number.isFinite(Number(item.durationMs)) ? Number(item.durationMs) : 0,
    inputChars: Number.isFinite(Number(item.inputChars)) ? Number(item.inputChars) : 0,
    outputChars: Number.isFinite(Number(item.outputChars)) ? Number(item.outputChars) : 0,
    promptTokens: typeof item.promptTokens === 'number' ? item.promptTokens : null,
    completionTokens: typeof item.completionTokens === 'number' ? item.completionTokens : null,
    totalTokens: typeof item.totalTokens === 'number' ? item.totalTokens : null,
    errors: Array.isArray(item.errors) ? item.errors.map(String) : [],
    generatedAt: String(item.generatedAt || new Date().toISOString()),
    confirmedAt: item.confirmedAt ? String(item.confirmedAt) : undefined,
    trace: normalizeSampleTrace(item.trace),
  }
}

export function sampleTraceFromResponse(response: { traceId?: string | null; tracePath?: string | null; traceLevel?: 'full' | null }): SampleExtractionDraft['trace'] | undefined {
  const traceId = String(response.traceId || '').trim()
  if (!traceId) return undefined
  return {
    traceId,
    tracePath: response.tracePath ? String(response.tracePath) : undefined,
    traceLevel: response.traceLevel === 'full' ? 'full' : undefined,
    generatedAt: new Date().toISOString(),
  }
}

export function normalizePersistedSampleProcessing(value: unknown): SampleProcessingDraft | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Partial<SampleProcessingDraft>
  if (!item.result || typeof item.result !== 'object') return undefined
  const result = item.result as Partial<SampleProcessingDraft['result']>
  const resultKind = result.resultKind === 'decision' || result.resultKind === 'table' || result.resultKind === 'text'
    ? result.resultKind
    : 'object'
  return {
    status: item.status === 'confirmed' ? 'confirmed' : 'draft',
    result: {
      summary: String(result.summary || ''),
      resultKind,
      outputPayload: result.outputPayload,
      validationErrors: Array.isArray(result.validationErrors) ? result.validationErrors.map(String) : [],
    },
    editableOutput: String(item.editableOutput || ''),
    rawOutput: item.rawOutput,
    model: String(item.model || ''),
    durationMs: Number.isFinite(Number(item.durationMs)) ? Number(item.durationMs) : 0,
    inputChars: Number.isFinite(Number(item.inputChars)) ? Number(item.inputChars) : 0,
    outputChars: Number.isFinite(Number(item.outputChars)) ? Number(item.outputChars) : 0,
    promptTokens: typeof item.promptTokens === 'number' ? item.promptTokens : null,
    completionTokens: typeof item.completionTokens === 'number' ? item.completionTokens : null,
    totalTokens: typeof item.totalTokens === 'number' ? item.totalTokens : null,
    errors: Array.isArray(item.errors) ? item.errors.map(String) : [],
    generatedAt: String(item.generatedAt || new Date().toISOString()),
    confirmedAt: item.confirmedAt ? String(item.confirmedAt) : undefined,
  }
}

export function normalizePersistedSkillDevelopment(value: unknown): SkillDevelopmentAsset | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Partial<SkillDevelopmentAsset>
  return {
    sampleContext: item.sampleContext,
    confirmedOutput: item.confirmedOutput,
    runtimeContract: normalizeRecord(item.runtimeContract),
    evidenceSummary: normalizeRecord(item.evidenceSummary),
    validationReport: normalizeRecord(item.validationReport),
    outputContractSummary: normalizeRecord(item.outputContractSummary),
    prototypeId: typeof item.prototypeId === 'string' ? item.prototypeId : undefined,
    candidateSkillId: typeof item.candidateSkillId === 'string' ? item.candidateSkillId : undefined,
    generatedAt: typeof item.generatedAt === 'string' ? item.generatedAt : undefined,
    updatedAt: typeof item.updatedAt === 'string' ? item.updatedAt : undefined,
  }
}

function normalizeRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

export function normalizeSampleSourceMode(value: unknown): SampleSourceMode {
  return value === 'selection' || value === 'tree' || value === 'target' || value === 'document' ? value : 'page'
}

export function defaultStepName(kind: ApplicationStepKind, name: string) {
  return kind === 'extraction' ? `${name}提取` : `${name}处理`
}

function stepDraftStableKey(record: ApplicationWorkshopStepDraft) {
  const runOption = record.runOption
  if (runOption && typeof runOption === 'object' && 'runId' in runOption && runOption.runId) {
    return `${record.kind}:run:${String(runOption.runId)}`
  }
  return [
    record.kind,
    normalizeStepKeyPart(record.dataTypeName || record.skillName),
    normalizeStepKeyPart(record.sourceScope),
    normalizeStepKeyPart(record.expectedOutput),
  ].join(':')
}

function normalizeStepKeyPart(value: string) {
  return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase()
}

function preferStepDraft(left: ApplicationWorkshopStepDraft, right: ApplicationWorkshopStepDraft) {
  const leftScore = stepDraftPreferenceScore(left)
  const rightScore = stepDraftPreferenceScore(right)
  if (leftScore !== rightScore) return rightScore > leftScore ? right : left
  return compareIsoTime(right.updatedAt, left.updatedAt) >= 0 ? right : left
}

function stepDraftPreferenceScore(record: ApplicationWorkshopStepDraft) {
  let score = 0
  if (record.status === 'verified') score += 100
  if (record.skillText.trim()) score += 20
  if (record.runOption) score += 30
  return score
}

function compareStepDraftsForDisplay(left: ApplicationWorkshopStepDraft, right: ApplicationWorkshopStepDraft) {
  if (left.status !== right.status) return left.status === 'verified' ? -1 : 1
  return compareIsoTime(left.updatedAt, right.updatedAt)
}

function compareIsoTime(left: string, right: string) {
  const leftTime = Date.parse(left || '')
  const rightTime = Date.parse(right || '')
  if (Number.isNaN(leftTime) && Number.isNaN(rightTime)) return 0
  if (Number.isNaN(leftTime)) return 1
  if (Number.isNaN(rightTime)) return -1
  return leftTime - rightTime
}

function normalizeSampleTrace(value: unknown): SampleExtractionDraft['trace'] | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Partial<NonNullable<SampleExtractionDraft['trace']>>
  const traceId = String(item.traceId || '').trim()
  if (!traceId) return undefined
  return {
    traceId,
    tracePath: item.tracePath ? String(item.tracePath) : undefined,
    traceLevel: item.traceLevel === 'full' ? 'full' : undefined,
    generatedAt: String(item.generatedAt || new Date().toISOString()),
  }
}
