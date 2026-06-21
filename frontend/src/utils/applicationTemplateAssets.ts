import type {
  ApplicationAsset,
  ApplicationDraftContext,
  ExtractionResult,
  PageResultDetail,
  PageResultSummary,
  WorkbenchPage,
  WorkbenchTaskDetail,
} from '../types/workbench'
import { cloneJson, plainRecord } from './objectData'

const API_BASE_URL = ((import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')) || '/idp-api'
const UPLOADS_BASE_URL = ((import.meta.env.VITE_UPLOADS_BASE_URL as string | undefined)?.replace(/\/$/, '')) || ''

export function buildTemplateApplicationContext(application: ApplicationAsset): ApplicationDraftContext {
  const sourceTask = application.sourceTask
  return {
    sourceTask: {
      taskId: sourceTask.taskId || `application-sample-${application.applicationId}`,
      taskName: sourceTask.taskName || `${application.name} 样板`,
      customerId: sourceTask.customerId || '',
      customerName: sourceTask.customerName || '',
      documentId: sourceTask.documentId || '',
      documentName: sourceTask.documentName || application.name,
      documentType: sourceTask.documentType || application.documentType || 'PDF',
      pageCount: sourceTask.pageCount || templateSamplePageCount(application),
    },
    parseOptions: [],
    operationOptions: [],
    defaultParseOptionId: '',
    defaultOperationOptionIds: [],
    missingRequirements: [],
    suggestedName: application.name,
    suggestedSummary: application.summary,
    suggestedDocumentType: application.documentType,
    suggestedScenario: application.scenario,
    suggestedCoverText: application.coverText,
    suggestedReleaseNotes: application.releaseNotes,
  }
}

export function templateSamplePageCount(application: ApplicationAsset) {
  const sample = templateSampleFromApplication(application)
  const document = plainRecord(sample.document)
  const pageCount = Number(document.pageCount || document.sampledPageCount || 0)
  if (Number.isFinite(pageCount) && pageCount > 0) return pageCount
  const pages = Array.isArray(sample.pages) ? sample.pages : []
  return pages.length || 1
}

export function templateSampleFromApplication(application: ApplicationAsset): Record<string, unknown> {
  for (const step of application.steps.slice().sort((left, right) => left.stepOrder - right.stepOrder)) {
    const snapshotSample = plainRecord(step.snapshot.templateSample)
    if (Object.keys(snapshotSample).length) return cloneJson(snapshotSample) as Record<string, unknown>
    const refs = plainRecord(step.dependencyRefs)
    const refsSample = plainRecord(refs.templateSample)
    if (Object.keys(refsSample).length) return cloneJson(refsSample) as Record<string, unknown>
  }
  return {}
}

export function hasTemplateSampleRecognitionContext(application: ApplicationAsset): boolean {
  return hasRecognitionContext(templateSampleFromApplication(application))
}

export function buildTemplateSampleTaskDetail(application: ApplicationAsset): WorkbenchTaskDetail | null {
  const sample = templateSampleFromApplication(application)
  if (!Object.keys(sample).length) return null

  const sourceTask = buildTemplateApplicationContext(application).sourceTask
  const documentSnapshot = plainRecord(sample.document)
  const pages = normalizeTemplateSamplePages(sample.pages)
  const documentTree = plainRecord(sample.documentTree)
  const pageResults = normalizeTemplateSamplePageResults(sample.pageResults)
  const pdfUrl = normalizeTemplateFileUrl(
    String(documentSnapshot.pdfUrl || documentSnapshot.sourceUrl || documentSnapshot.previewUrl || ''),
  )
  const markdownUrl = normalizeTemplateFileUrl(String(documentSnapshot.markdownUrl || ''))
  const rawJsonUrl = normalizeTemplateFileUrl(String(documentSnapshot.rawJsonUrl || ''))
  if (!pdfUrl && !pages.length && !Object.keys(documentTree).length) return null

  return {
    task: {
      id: sourceTask.taskId,
      customerId: sourceTask.customerId,
      customerName: sourceTask.customerName,
      taskName: sourceTask.taskName,
      documentName: sourceTask.documentName,
      roleScope: ['admin', 'customer'],
      owner: '',
      status: 'completed',
      uploadTime: '',
      updatedAt: '',
      pageCount: sourceTask.pageCount,
      promptRunCount: pageResults.length,
      summary: '应用内保存的样板快照',
    },
    document: {
      id: sourceTask.documentId || String(documentSnapshot.id || `document-${application.applicationId}`),
      fileName: sourceTask.documentName || String(documentSnapshot.fileName || application.name),
      fileType: sourceTask.documentType || String(documentSnapshot.fileType || application.documentType || 'PDF'),
      pdfUrl,
      markdownUrl,
      rawJsonUrl,
      pageCount: sourceTask.pageCount || pages.length,
      sampledPageCount: Number(documentSnapshot.sampledPageCount || sourceTask.pageCount || pages.length),
    },
    runtime: {
      parseStatus: 'completed',
      pagePromptStatus: 'completed',
      summaryStatus: 'completed',
      latestRunLabel: '样板快照已加载',
      failedPageCount: 0,
      completedPageCount: pages.length,
      latestPromptRunAt: '',
    },
    pages,
    pageResults,
    objectOperationResults: [],
    summaryResults: [],
    documentTree: Object.keys(documentTree).length
      ? documentTree as unknown as WorkbenchTaskDetail['documentTree']
      : null,
    applicationRun: null,
  }
}

function hasRecognitionContext(sample: Record<string, unknown>): boolean {
  const pages = Array.isArray(sample.pages) ? sample.pages : []
  const documentTree = plainRecord(sample.documentTree)
  return pages.length > 0 || Object.keys(documentTree).length > 0
}

function isAbsoluteUrl(url: string): boolean {
  return /^(?:[a-z]+:)?\/\//i.test(url) || /^(?:data|blob):/i.test(url)
}

function normalizeTemplateFileUrl(url: string): string {
  const trimmed = url.trim()
  if (!trimmed) return ''
  if (isAbsoluteUrl(trimmed)) return trimmed
  if (trimmed.startsWith(`${API_BASE_URL}/`)) return trimmed
  if (UPLOADS_BASE_URL && trimmed.startsWith(`${UPLOADS_BASE_URL}/`)) return trimmed
  if (trimmed.startsWith('/api/')) return `${API_BASE_URL}${trimmed.slice('/api'.length)}`
  if (trimmed.startsWith('/sample-doc/')) return UPLOADS_BASE_URL ? `${UPLOADS_BASE_URL}${trimmed}` : trimmed
  if (trimmed.startsWith('/')) return UPLOADS_BASE_URL ? `${UPLOADS_BASE_URL}${trimmed}` : trimmed
  return trimmed
}

export function normalizeTemplateSamplePageResults(value: unknown): PageResultSummary[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is PageResultSummary => Boolean(item && typeof item === 'object'))
    .map((item) => cloneJson(item) as PageResultSummary)
}

export function getParseResultScopeKey(result: PageResultSummary) {
  const startPageNo = result.startPageNo ?? result.pageNo
  const endPageNo = result.endPageNo ?? result.pageNo
  return `${result.runType ?? 'page'}:${startPageNo}:${endPageNo}:${result.runPurpose ?? 'parse_prompt'}`
}

export function selectLatestTaskParseResultSummaries(results: PageResultSummary[]) {
  const seenKeys = new Set<string>()
  return results.filter((result) => {
    if (result.runPurpose !== 'parse_prompt') return false
    if (result.status !== 'completed' && result.status !== 'needs_review') return false
    const scopeKey = getParseResultScopeKey(result)
    if (seenKeys.has(scopeKey)) return false
    seenKeys.add(scopeKey)
    return true
  })
}

export function normalizeExtractionResult(value: unknown): ExtractionResult | null {
  const result = plainRecord(value)
  const outputs = Array.isArray(result.outputs) ? result.outputs as ExtractionResult['outputs'] : []
  const fields = Array.isArray(result.fields) ? result.fields as ExtractionResult['fields'] : []
  const tables = Array.isArray(result.tables) ? result.tables as ExtractionResult['tables'] : []
  const structuredObjects = Array.isArray(result.structuredObjects)
    ? result.structuredObjects as ExtractionResult['structuredObjects']
    : []
  const errors = Array.isArray(result.errors) ? result.errors.map(String) : []
  const validationErrors = Array.isArray(result.validationErrors)
    ? result.validationErrors.map(String)
    : []
  const summary = typeof result.summary === 'string' ? result.summary : ''
  const runMeta = plainRecord(result.runMeta)
  const hasPayload = outputs.length
    || fields.length
    || tables.length
    || structuredObjects.length
    || errors.length
    || validationErrors.length
    || summary.trim()
  if (!hasPayload) return null
  return {
    summary,
    outputs: cloneJson(outputs) as ExtractionResult['outputs'],
    errors,
    runMeta,
    fields: cloneJson(fields) as ExtractionResult['fields'],
    tables: cloneJson(tables) as ExtractionResult['tables'],
    structuredObjects: cloneJson(structuredObjects) as ExtractionResult['structuredObjects'],
    validationErrors,
  }
}

export function buildMergedParseResultDetail(resultDetails: PageResultDetail[]): PageResultDetail | null {
  const normalized = resultDetails
    .map((item) => ({
      detail: item,
      result: normalizeExtractionResult(item.extractionResult),
    }))
    .filter((item): item is { detail: PageResultDetail; result: ExtractionResult } => Boolean(item.result))
  if (!normalized.length) return null
  if (normalized.length === 1) {
    return {
      ...normalized[0].detail,
      extractionResult: normalized[0].result,
    }
  }
  const first = normalized[0].detail
  const startPages = normalized.map((item) => item.detail.startPageNo ?? item.detail.pageNo).filter(Number.isFinite)
  const endPages = normalized.map((item) => item.detail.endPageNo ?? item.detail.pageNo).filter(Number.isFinite)
  const startPageNo = startPages.length ? Math.min(...startPages) : first.pageNo
  const endPageNo = endPages.length ? Math.max(...endPages) : first.pageNo
  const extractionResult: ExtractionResult = {
    summary: `共合并 ${normalized.length} 个提取结果。`,
    outputs: normalized.flatMap((item, resultIndex) =>
      item.result.outputs.map((output, outputIndex) => ({
        ...output,
        id: output.id
          ? `${item.detail.id}:${output.id}`
          : `${item.detail.id}:output-${outputIndex}`,
        title: output.title || item.detail.title || `提取结果 ${resultIndex + 1}`,
      })),
    ),
    errors: uniqueStrings(normalized.flatMap((item) => item.result.errors)),
    runMeta: {
      merged: true,
      sourceResultIds: normalized.map((item) => item.detail.id),
    },
    fields: normalized.flatMap((item) => item.result.fields),
    tables: normalized.flatMap((item) => item.result.tables),
    structuredObjects: normalized.flatMap((item) => item.result.structuredObjects),
    validationErrors: uniqueStrings(normalized.flatMap((item) => item.result.validationErrors)),
  }
  return {
    ...first,
    id: `task-wide:${normalized.map((item) => item.detail.id).join(',')}`,
    title: '整份任务提取结果',
    pageNo: startPageNo,
    pageIndex: 0,
    status: normalized.some((item) => item.detail.status === 'needs_review') ? 'needs_review' : 'completed',
    runType: 'summary',
    startPageNo,
    endPageNo,
    pageRange: startPageNo === endPageNo ? `第 ${startPageNo} 页` : `第 ${startPageNo}-${endPageNo} 页`,
    extractionResult,
    outputText: normalized.map((item) => item.detail.outputText).filter(Boolean).join('\n\n') || first.outputText,
    evidenceRefs: normalized.flatMap((item) => item.detail.evidenceRefs ?? []),
  }
}

export function buildTemplateSampleParseResult(application: ApplicationAsset | null): PageResultDetail | null {
  if (!application) return null
  const sample = templateSampleFromApplication(application)
  const sampleExtraction = plainRecord(sample.sampleExtraction)
  const extractionResult = normalizeExtractionResult(sampleExtraction.result)
  if (!extractionResult) return null
  const pageResults = normalizeTemplateSamplePageResults(sample.pageResults)
  const firstResult = pageResults[0]
  return {
    id: firstResult?.id || `template-sample:${application.applicationId}`,
    title: firstResult?.title || '样板提取结果',
    pageNo: firstResult?.pageNo || 1,
    pageIndex: firstResult?.pageIndex || 0,
    status: firstResult?.status || 'completed',
    resultStage: firstResult?.resultStage || 'parse',
    runPurpose: 'parse_prompt',
    promptName: firstResult?.promptName || application.name,
    runType: firstResult?.runType || 'summary',
    startPageNo: firstResult?.startPageNo,
    endPageNo: firstResult?.endPageNo,
    pageRange: firstResult?.pageRange,
    errorMessage: firstResult?.errorMessage,
    schemaTemplateId: firstResult?.schemaTemplateId,
    schemaTemplateName: firstResult?.schemaTemplateName,
    schemaTemplateVersion: firstResult?.schemaTemplateVersion,
    promptTrace: firstResult?.promptTrace ?? null,
    extractionResult,
    outputText: sampleExtraction.editableOutput ? String(sampleExtraction.editableOutput) : null,
    evidenceRefs: firstResult?.evidenceRefs ?? [],
    validationErrors: extractionResult.validationErrors,
    llmTraceSummary: null,
  }
}

export function normalizeTemplateSamplePages(value: unknown): WorkbenchPage[] {
  if (Array.isArray(value)) {
    const pages = value.filter((item): item is WorkbenchPage => Boolean(item && typeof item === 'object'))
    if (pages.length) return cloneJson(pages) as WorkbenchPage[]
  }
  return [{
    pageIndex: 0,
    pageNo: 1,
    title: '样板快照',
    summary: '',
    promptConfig: {
      textPrompt: '',
      tablePrompt: '',
      tableTaskMode: 'parse_json',
    },
    promptStatus: 'ready',
    markdownSegments: [],
    blocks: [],
    rawItems: [],
    pageSize: [1000, 1400],
  }]
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((item) => item.trim()).filter(Boolean)))
}
