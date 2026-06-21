import type {
  ApplicationRunPlanResponse,
  ApplicationSourceRunOption,
  ApplicationStepDefinition,
  ApplicationStepKind,
  ExtractionResult,
} from './workbench'

export type ParsePanelTabKey = 'recognition' | 'tree' | 'extract'
export type SampleSourceMode = 'page' | 'selection' | 'tree' | 'target' | 'document'
export type ProcessingStepStatus = 'generated' | 'verified'

export interface ContentRange {
  id: string
  pageIndex: number
  pageNo: number
  label: string
  kind: string
  bbox: [number, number, number, number]
  blockIds: string[]
  pageRange: string
  summary: string
  text: string
}

export interface SampleSource {
  mode: SampleSourceMode
  kind: ApplicationStepKind
  title: string
  summary: string
  sourceScope: string
  sourceText: string
  pageNo: number | null
  pageIndex: number | null
  targetIds: string[]
  treeNodeId?: string
  treePath?: string[]
  pageRange?: { start?: number; end?: number }
  contentRefs?: Array<Record<string, unknown>>
  locator?: Record<string, unknown>
}

export interface DocumentTreeSource {
  id: string
  type: string
  typeLabel: string
  label: string
  preview: string
  meta: string
  depth: number
  pageNos: number[]
  locations: Array<{
    pageNo: number
    bbox: [number, number, number, number]
  }>
  sourceScope: string
  sourceText: string
}

export interface SampleExtractionDraft {
  status: 'draft' | 'confirmed'
  result: ExtractionResult
  editableOutput: string
  rawOutput?: unknown
  model: string
  durationMs: number
  inputChars: number
  outputChars: number
  promptTokens?: number | null
  completionTokens?: number | null
  totalTokens?: number | null
  errors: string[]
  generatedAt: string
  confirmedAt?: string
  trace?: {
    traceId: string
    tracePath?: string
    traceLevel?: 'full'
    generatedAt: string
  }
}

export interface SkillDevelopmentAsset {
  sampleContext?: unknown
  confirmedOutput?: unknown
  runtimeContract?: Record<string, unknown>
  evidenceSummary?: Record<string, unknown>
  validationReport?: Record<string, unknown>
  outputContractSummary?: Record<string, unknown>
  prototypeId?: string
  candidateSkillId?: string
  generatedAt?: string
  updatedAt?: string
}

export interface SampleProcessingResult {
  summary: string
  resultKind: 'decision' | 'object' | 'table' | 'text'
  outputPayload: unknown
  validationErrors: string[]
}

export interface SampleProcessingDraft {
  status: 'draft' | 'confirmed'
  result: SampleProcessingResult
  editableOutput: string
  rawOutput?: unknown
  model: string
  durationMs: number
  inputChars: number
  outputChars: number
  promptTokens?: number | null
  completionTokens?: number | null
  totalTokens?: number | null
  errors: string[]
  generatedAt: string
  confirmedAt?: string
}

export interface ProcessingStepDraft {
  id: string
  isLight?: boolean
  kind: ApplicationStepKind
  status: ProcessingStepStatus
  dataTypeName: string
  locatorInstruction?: string
  goal: string
  expectedOutput: string
  sourceTitle: string
  sourceScope: string
  skillText: string
  skillName: string
  errors: string[]
  model: string
  sampleSource?: SampleSource
  sampleExtraction?: SampleExtractionDraft
  sampleProcessing?: SampleProcessingDraft
  skillDevelopment?: SkillDevelopmentAsset
  semanticLocator?: Record<string, unknown>
  runOption?: ApplicationSourceRunOption
  applicationStep?: ApplicationStepDefinition
}

export interface ApplicationPlanSummary {
  status: ApplicationRunPlanResponse['status']
  requiresConfirmation: boolean
  totalStepCount: number
  selectedCount: number
  targetCount: number
  warnings: number
  blockedCount: number
  reviewCount: number
  firstIssue: string
}
