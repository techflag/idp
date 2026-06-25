// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
import type {
  ApplicationAsset,
  ApplicationDetailLoadOptions,
  ApplicationDetailUpdatePayload,
  ApplicationDraftPayload,
  ApplicationPublishPayload,
  ApplicationRunPlanResponse,
  ApplicationRunRequest,
  ApplicationRunDetail,
  ApplicationRunReviewFeedbackRequest,
  ApplicationRunReviewFeedbackResponse,
  ApplicationRunResult,
  ApplicationScope,
  ApplicationStatus,
  ApplicationStepDefinition,
  ApplicationStepInputMapping,
  ApplicationStepKind,
  ApplicationStepTargetMapping,
  ApplicationVersionSummary,
  ApplicationWorkshopStepDraft,
  ApplicationWorkshopStepDraftUpsertRequest,
  AdminOverviewResponse,
  BusinessSkill,
  BusinessSkillUpsertRequest,
  CreateCustomerRequest,
  CreateCustomerProvisionRequest,
  CreateCustomerProvisionResponse,
  CustomerWorkspaceResponse,
  CustomerSummary,
  DocumentSummary,
  ObjectOperationExecutionResponse,
  ObjectOperationResult,
  ObjectOperationRunRequest,
  ExtractionSkill,
  ExtractionSkillRunRequest,
  ExtractionSkillUpsertRequest,
  PaginatedResponse,
  PageResultDetail,
  PageOperationTargetsResponse,
  ParseTaskStatusResponse,
  TaskSummary,
  PromptExecutionRequest,
  PromptExecutionResponse,
  WorkbenchDataset,
  SchemaRunRequest,
  SchemaTemplateDetail,
  SchemaTemplateSummary,
  SchemaTemplateUpsertRequest,
  SkillAssistRequest,
  SkillAssistResponse,
  SkillCopyDraftRequest,
  SkillCopyDraftResponse,
  SkillDraftFromSampleRequest,
  SkillDraftFromSampleResponse,
  SkillSampleLocateAndExtractRequest,
  SkillSampleLocateAndExtractResponse,
  SkillSampleExtractFromSampleResponse,
  SkillSampleProcessFromSampleResponse,
  SkillOwnershipUpdateRequest,
  SkillPrototypeBaselineUpdateRequest,
  SkillPrototypeCreateRequest,
  SkillPrototypeProject,
  SkillSample,
  SkillSampleUpsertRequest,
  SkillTestRunRequest,
  SkillTestRunResponse,
  SkillTestRunSummary,
  SkillRunRequest,
  SkillValidateRequest,
  SkillValidateResponse,
  UnifiedSkill,
  TableTaskMode,
  UploadAndParseResponse,
  WorkbenchBlock,
  WorkbenchDocumentTree,
  WorkbenchPage,
  WorkbenchPromptConfig,
  WorkbenchTaskDetail,
} from '../types/workbench'
import type { AuthUser, LoginRequest, LoginResponse } from '../types/auth'
import type { SystemCapabilitiesResponse } from '../types/system'

const API_BASE_URL = ((import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')) || '/idp-api'
const UPLOADS_BASE_URL = ((import.meta.env.VITE_UPLOADS_BASE_URL as string | undefined)?.replace(/\/$/, '')) || ''
const DEFAULT_TABLE_TASK_MODE: TableTaskMode = 'parse_json'
const TABLE_TASK_MODES = new Set<TableTaskMode>(['parse_json', 'semantic_extract', 'semantic_enrich'])
const APPLICATION_STORAGE_KEY = 'techflag-workbench-applications-v1'

function isAbsoluteUrl(url: string): boolean {
  return /^(?:[a-z]+:)?\/\//i.test(url) || /^(?:data|blob):/i.test(url)
}

function normalizeFileUrl(url?: string | null): string {
  if (!url) {
    return ''
  }

  if (isAbsoluteUrl(url)) {
    return url
  }

  if (url.startsWith(`${API_BASE_URL}/`)) {
    return url
  }

  if (UPLOADS_BASE_URL && url.startsWith(`${UPLOADS_BASE_URL}/`)) {
    return url
  }

  if (url.startsWith('/api/')) {
    return `${API_BASE_URL}${url.slice('/api'.length)}`
  }

  if (url.startsWith('/sample-doc/')) {
    return UPLOADS_BASE_URL ? `${UPLOADS_BASE_URL}${url}` : url
  }

  if (url.startsWith('/')) {
    return UPLOADS_BASE_URL ? `${UPLOADS_BASE_URL}${url}` : url
  }

  return url
}

function normalizeTableTaskMode(value: unknown): TableTaskMode {
  return TABLE_TASK_MODES.has(value as TableTaskMode) ? (value as TableTaskMode) : DEFAULT_TABLE_TASK_MODE
}

function withNoCacheParam(path: string): string {
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}_ts=${Date.now()}`
}

type SampleRequestPayload = {
  taskId?: string
  applicationId?: string | null
  customerId?: string | null
  sampleContext?: SkillDraftFromSampleRequest['sampleContext'] | SkillSampleLocateAndExtractRequest['sampleContext'] | null
}

function sampleContextForRequest(payload: SampleRequestPayload) {
  const sampleContext = payload.sampleContext
  if (!sampleContext) return undefined
  if (!String(payload.taskId || '').trim()) {
    return stripSampleRequestGeometry(sampleContext)
  }

  return {
    sampleId: sampleContext.sampleId,
    source: sampleContext.source,
    applicationId: sampleContext.applicationId ?? payload.applicationId ?? null,
    customerId: sampleContext.customerId ?? payload.customerId ?? null,
    document: compactSampleDocument(sampleContext.document),
    pages: [],
    documentTree: null,
    operationTargets: [],
    sampleSource: compactSampleSource(sampleContext.sampleSource),
  }
}

function compactSampleDocument(document?: Record<string, unknown>) {
  if (!document || typeof document !== 'object') return {}
  return {
    id: document.id ?? document.documentId ?? '',
    documentId: document.documentId ?? document.id ?? '',
    fileName: document.fileName ?? document.name ?? '',
    pageCount: document.pageCount ?? document.pages ?? undefined,
  }
}

function compactSampleSource(source?: Record<string, unknown>) {
  if (!source || typeof source !== 'object') return {}
  return stripSampleRequestGeometry({
    mode: source.mode,
    kind: source.kind,
    title: source.title,
    summary: source.summary,
    sourceScope: source.sourceScope,
    pageNo: source.pageNo,
    pageIndex: source.pageIndex,
    targetIds: source.targetIds,
    treeNodeId: source.treeNodeId,
    treePath: source.treePath,
    pageRange: source.pageRange,
    contentRefs: Array.isArray(source.contentRefs)
      ? source.contentRefs.map((item) => stripSampleRequestGeometry(item))
      : undefined,
  }) as Record<string, unknown>
}

function stripSampleRequestGeometry(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => stripSampleRequestGeometry(item))
  }
  if (!value || typeof value !== 'object') {
    return value
  }
  const geometryKeys = new Set([
    'bbox',
    'boundingbox',
    'box',
    'polygon',
    'points',
    'quad',
    'quads',
    'rect',
    'rotation',
  ])
  const result: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (geometryKeys.has(key.replace(/_/g, '').toLowerCase())) continue
    result[key] = stripSampleRequestGeometry(item)
  }
  return result
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? undefined)
  const method = init?.method?.toUpperCase() || 'GET'

  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
  headers.set('Pragma', 'no-cache')

  const requestPath = method === 'GET' ? withNoCacheParam(path) : path
  const response = await fetch(`${API_BASE_URL}${requestPath}`, {
    cache: 'no-store',
    credentials: 'include',
    headers,
    ...init,
  })

  if (!response.ok) {
    let message = `Request failed: ${path}`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        message = String(payload.detail)
      }
    } catch {
      // ignore JSON parse failure and keep default message
    }
    throw new Error(message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('content-type') || ''
  if (!contentType.toLowerCase().includes('application/json')) {
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  return response.json() as Promise<T>
}

async function fetchForm<T>(path: string, formData: FormData, init?: Omit<RequestInit, 'body'>): Promise<T> {
  const headers = new Headers(init?.headers ?? undefined)
  headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
  headers.set('Pragma', 'no-cache')

  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: 'no-store',
    credentials: 'include',
    headers,
    ...init,
    body: formData,
  })

  if (!response.ok) {
    let message = `Request failed: ${path}`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        message = String(payload.detail)
      }
    } catch {
      // ignore JSON parse failure and keep default message
    }
    throw new Error(message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('content-type') || ''
  if (!contentType.toLowerCase().includes('application/json')) {
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  return response.json() as Promise<T>
}

function canUseLocalStorage() {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function readStoredApplications(): ApplicationAsset[] {
  if (!canUseLocalStorage()) {
    return []
  }
  try {
    const raw = window.localStorage.getItem(APPLICATION_STORAGE_KEY)
    if (!raw) {
      return []
    }
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed as ApplicationAsset[] : []
  } catch {
    return []
  }
}

function withApplicationFallback<T>(executor: () => Promise<T>, fallback: () => T | Promise<T>): Promise<T> {
  return executor().catch(async () => {
    return await fallback()
  })
}

function normalizePromptExecutionPayload(payload: PromptExecutionRequest): PromptExecutionRequest {
  return {
    ...payload,
    tableTaskMode: normalizeTableTaskMode(payload.tableTaskMode),
    pageContext: payload.pageContext
      ? {
          pages: payload.pageContext.pages.map((page) => ({
            pageIndex: page.pageIndex,
            pageNo: page.pageNo,
            title: page.title,
            summary: page.summary,
            promptConfig: {
              textPrompt: page.promptConfig?.textPrompt ?? '',
              tablePrompt: page.promptConfig?.tablePrompt ?? '',
              tableTaskMode: normalizeTableTaskMode(page.promptConfig?.tableTaskMode),
            },
            promptStatus: page.promptStatus,
            markdownSegments: page.markdownSegments.map((segment) => {
              if (typeof segment === 'string') {
                return segment
              }
              return {
                id: segment.id,
                pageIndex: segment.pageIndex,
                pageNo: segment.pageNo,
                blockId: segment.blockId,
                blockPosition: segment.blockPosition,
                type: segment.type,
                html: segment.html,
                bbox: [...segment.bbox] as [number, number, number, number],
              }
            }),
            blocks: page.blocks.map((block) => ({
              id: block.id,
              pageIndex: block.pageIndex,
              pageNo: block.pageNo,
              blockPosition: block.blockPosition,
              type: block.type,
              title: block.title,
              content: block.content,
              htmlContent: block.htmlContent,
              bbox: [...block.bbox] as [number, number, number, number],
            })),
            rawItems: page.rawItems.map((item) => {
              if (item && typeof item === 'object' && !Array.isArray(item)) {
                return { ...(item as Record<string, unknown>) }
              }
              return item
            }),
            pageSize: [...page.pageSize] as [number, number],
          })),
        }
      : undefined,
  }
}

function normalizePromptConfig(
  page: Partial<WorkbenchPage> & { prompt?: string; promptConfig?: WorkbenchPromptConfig },
  fallback = buildPromptConfig(page.blocks ?? []),
): WorkbenchPromptConfig {
  if (page.promptConfig) {
    return {
      textPrompt: page.promptConfig.textPrompt ?? '',
      tablePrompt: page.promptConfig.tablePrompt ?? '',
      tableTaskMode: normalizeTableTaskMode(page.promptConfig.tableTaskMode),
    }
  }

  if (typeof page.prompt === 'string' && page.prompt.trim()) {
    const parsedPrompt = parsePromptText(page.prompt)

    return {
      textPrompt: parsedPrompt?.textPrompt ?? page.prompt,
      tablePrompt: parsedPrompt?.tablePrompt ?? fallback.tablePrompt,
      tableTaskMode: normalizeTableTaskMode(parsedPrompt?.tableTaskMode ?? fallback.tableTaskMode),
    }
  }

  return fallback
}

function normalizePagesPromptState(pages: WorkbenchPage[]): WorkbenchPage[] {
  return pages.map((page) => ({
    ...page,
    promptConfig: normalizePromptConfig(page),
    promptStatus: page.promptStatus ?? 'draft',
  }))
}

function parsePromptText(promptText: string): WorkbenchPromptConfig | null {
  const trimmed = promptText.trim()

  if (!trimmed) {
    return null
  }

  const textMatch = trimmed.match(/文本提示词：([\s\S]*?)(?:\n\s*\n\S+提示词：|$)/)
  const tableMatch = trimmed.match(/表格提示词：([\s\S]*?)(?:\n\s*\n\S+提示词：|$)/)
  const tableTaskModeMatch = trimmed.match(/表格处理模式：([a-z_]+)/)

  if (!textMatch && !tableMatch && !tableTaskModeMatch) {
    return null
  }

  return {
    textPrompt: textMatch?.[1]?.trim() || '',
    tablePrompt: tableMatch?.[1]?.trim() || '',
    tableTaskMode: normalizeTableTaskMode(tableTaskModeMatch?.[1]),
  }
}

async function normalizeTaskDetail(detail: WorkbenchTaskDetail): Promise<WorkbenchTaskDetail> {
  const normalizedPages = normalizePagesPromptState(detail.pages)

  return {
    ...detail,
    document: {
      ...detail.document,
      pdfUrl: normalizeFileUrl(detail.document.pdfUrl),
      markdownUrl: normalizeFileUrl(detail.document.markdownUrl),
      rawJsonUrl: normalizeFileUrl(detail.document.rawJsonUrl),
      sampledPageCount: normalizedPages.length,
    },
    pages: normalizedPages,
    pageResults: detail.pageResults,
  }
}

function normalizeParseStatusResponse(response: ParseTaskStatusResponse): ParseTaskStatusResponse {
  return {
    ...response,
    artifacts: {
      ...response.artifacts,
      artifactBaseUrl: normalizeFileUrl(response.artifacts.artifactBaseUrl),
      fullZipUrl: normalizeFileUrl(response.artifacts.fullZipUrl),
      markdownUrl: normalizeFileUrl(response.artifacts.markdownUrl),
      rawJsonUrl: normalizeFileUrl(response.artifacts.rawJsonUrl),
      layoutUrl: normalizeFileUrl(response.artifacts.layoutUrl),
      blockListUrl: normalizeFileUrl(response.artifacts.blockListUrl),
      modelJsonUrl: normalizeFileUrl(response.artifacts.modelJsonUrl),
    },
  }
}

async function normalizeDataset(dataset: WorkbenchDataset): Promise<WorkbenchDataset> {
  const normalizedTaskDetails = await Promise.all(
    Object.entries(dataset.taskDetails).map(async ([taskId, detail]) => {
      return [taskId, await normalizeTaskDetail(detail)] as const
    }),
  )

  return {
    ...dataset,
    taskDetails: Object.fromEntries(normalizedTaskDetails),
  }
}

function buildPromptConfig(blocks: WorkbenchBlock[] = []): WorkbenchPromptConfig {
  const hasTextBlocks = blocks.some((block) => block.type !== 'table')

  return {
    textPrompt: hasTextBlocks
      ? [
          '1. 提取当前页文本中的关键字段，一行一条返回。',
          '2. 只基于当前页直接可见文本返回结果。',
          '3. 无相关字段时返回空结果，不要补推。',
        ].join('\n')
      : '',
    tablePrompt: '',
    tableTaskMode: DEFAULT_TABLE_TASK_MODE,
  }
}

export async function loadWorkbenchDataset(): Promise<WorkbenchDataset> {
  const dataset = await fetchJson<WorkbenchDataset>('/workbench/dataset')
  return await normalizeDataset(dataset)
}

export async function loadAdminOverview(): Promise<AdminOverviewResponse> {
  return fetchJson<AdminOverviewResponse>('/overview/admin')
}

export async function loadAdminTasks(
  page = 1,
  pageSize = 10,
  customerId?: string | null,
): Promise<PaginatedResponse<TaskSummary>> {
  const params = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
  })
  if (customerId) {
    params.set('customerId', customerId)
  }
  return fetchJson<PaginatedResponse<TaskSummary>>(`/admin/tasks?${params.toString()}`)
}

export async function loadCustomers(page = 1, pageSize = 10): Promise<PaginatedResponse<CustomerSummary>> {
  return fetchJson<PaginatedResponse<CustomerSummary>>(`/customers?page=${page}&pageSize=${pageSize}`)
}

export async function loadMyTasks(page = 1, pageSize = 10): Promise<PaginatedResponse<TaskSummary>> {
  return fetchJson<PaginatedResponse<TaskSummary>>(`/me/tasks?page=${page}&pageSize=${pageSize}`)
}

export async function loadUserTasks(userId: string, page = 1, pageSize = 10): Promise<PaginatedResponse<TaskSummary>> {
  return fetchJson<PaginatedResponse<TaskSummary>>(`/users/${userId}/tasks?page=${page}&pageSize=${pageSize}`)
}

export async function loadWorkbenchTaskDetail(
  taskId: string,
  options: { includeDocumentTree?: boolean } = {},
): Promise<WorkbenchTaskDetail> {
  const params = new URLSearchParams()
  if (options.includeDocumentTree !== undefined) {
    params.set('includeDocumentTree', options.includeDocumentTree ? 'true' : 'false')
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  const detail = await fetchJson<WorkbenchTaskDetail>(`/workbench/tasks/${encodeURIComponent(taskId)}${suffix}`)
  return normalizeTaskDetail(detail)
}

export async function loadWorkbenchTaskDocumentTree(taskId: string): Promise<WorkbenchDocumentTree | null> {
  return fetchJson<WorkbenchDocumentTree | null>(`/workbench/tasks/${encodeURIComponent(taskId)}/document-tree`)
}

export async function loadPromptRunDetail(
  taskId: string,
  runId: string,
  init?: RequestInit,
): Promise<PageResultDetail> {
  return fetchJson<PageResultDetail>(`/tasks/${taskId}/prompt-runs/${runId}`, init)
}

export async function loadSchemaRunDetail(taskId: string, runId: string): Promise<PageResultDetail> {
  return fetchJson<PageResultDetail>(`/tasks/${taskId}/schema-runs/${runId}`)
}

export async function loadPageOperationTargets(
  taskId: string,
  pageNo: number,
): Promise<PageOperationTargetsResponse> {
  return fetchJson<PageOperationTargetsResponse>(`/tasks/${taskId}/pages/${pageNo}/operation-targets`)
}

export async function loadBusinessSkills(customerId?: string | null): Promise<BusinessSkill[]> {
  const query = customerId ? `?customerId=${encodeURIComponent(customerId)}` : ''
  return fetchJson<BusinessSkill[]>(`/business-skills${query}`)
}

export async function loadExtractionSkills(customerId?: string | null): Promise<ExtractionSkill[]> {
  const query = customerId ? `?customerId=${encodeURIComponent(customerId)}` : ''
  return fetchJson<ExtractionSkill[]>(`/extraction-skills${query}`)
}

interface LoadSkillsOptions {
  customerId?: string | null
  scope?: 'platform' | 'customer' | 'all'
  status?: string
  keyword?: string
  page?: number
  pageSize?: number
}

export async function loadSkills(
  kind: 'extraction' | 'operation',
  options: LoadSkillsOptions = {},
): Promise<PaginatedResponse<UnifiedSkill>> {
  const params = new URLSearchParams({ kind })
  if (options.scope) params.set('scope', options.scope)
  if (options.customerId) params.set('customerId', options.customerId)
  if (options.status) params.set('status', options.status)
  if (options.keyword) params.set('keyword', options.keyword)
  if (options.page) params.set('page', String(options.page))
  if (options.pageSize) params.set('pageSize', String(options.pageSize))
  const response = await fetchJson<PaginatedResponse<BusinessSkill | ExtractionSkill>>(`/skills?${params.toString()}`)
  return {
    ...response,
    items: response.items.map((item) => ({ ...item, kind })),
  }
}

export async function loadSkillDetail(
  kind: 'extraction' | 'operation',
  skillId: string,
  scope: 'platform' | 'customer' = 'platform',
  customerId?: string | null,
  includeText = true,
): Promise<UnifiedSkill> {
  const params = new URLSearchParams({ kind, scope })
  if (customerId) params.set('customerId', customerId)
  if (includeText) params.set('includeText', 'true')
  const item = await fetchJson<BusinessSkill | ExtractionSkill>(`/skills/${encodeURIComponent(skillId)}?${params.toString()}`)
  return { ...item, kind }
}

export async function createExtractionSkill(payload: ExtractionSkillUpsertRequest): Promise<ExtractionSkill> {
  return fetchJson<ExtractionSkill>('/extraction-skills', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateExtractionSkill(
  skillId: string,
  payload: ExtractionSkillUpsertRequest,
): Promise<ExtractionSkill> {
  return fetchJson<ExtractionSkill>(`/extraction-skills/${encodeURIComponent(skillId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function createBusinessSkill(payload: BusinessSkillUpsertRequest): Promise<BusinessSkill> {
  return fetchJson<BusinessSkill>('/business-skills', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateBusinessSkill(
  skillId: string,
  payload: BusinessSkillUpsertRequest,
): Promise<BusinessSkill> {
  return fetchJson<BusinessSkill>(`/business-skills/${encodeURIComponent(skillId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function createSkill(payload: {
  kind: 'extraction' | 'operation'
  skillText: string
  customerId?: string | null
}): Promise<UnifiedSkill> {
  const item = await fetchJson<BusinessSkill | ExtractionSkill>('/skills', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return { ...item, kind: payload.kind }
}

export async function updateSkill(
  skillId: string,
  payload: {
    kind: 'extraction' | 'operation'
    skillText: string
    customerId?: string | null
  },
): Promise<UnifiedSkill> {
  const item = await fetchJson<BusinessSkill | ExtractionSkill>(`/skills/${encodeURIComponent(skillId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
  return { ...item, kind: payload.kind }
}

export async function copySkillDraft(payload: SkillCopyDraftRequest): Promise<SkillCopyDraftResponse> {
  return fetchJson<SkillCopyDraftResponse>('/skills/copy-draft', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function moveSkillOwnership(
  skillId: string,
  payload: SkillOwnershipUpdateRequest,
): Promise<UnifiedSkill> {
  const item = await fetchJson<BusinessSkill | ExtractionSkill>(`/skills/${encodeURIComponent(skillId)}/ownership`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
  return { ...item, kind: payload.kind }
}

export async function loadSkillSamples(params: {
  kind: 'extraction' | 'operation'
  skillId: string
  customerId?: string | null
  includeContent?: boolean
}): Promise<SkillSample[]> {
  const query = new URLSearchParams({ kind: params.kind })
  if (params.customerId) query.set('customerId', params.customerId)
  if (params.includeContent) query.set('includeContent', 'true')
  return fetchJson<SkillSample[]>(`/skills/${encodeURIComponent(params.skillId)}/samples?${query.toString()}`)
}

export async function saveSkillSample(skillId: string, payload: SkillSampleUpsertRequest): Promise<SkillSample> {
  return fetchJson<SkillSample>(`/skills/${encodeURIComponent(skillId)}/samples`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function createSkillPrototype(payload: SkillPrototypeCreateRequest): Promise<SkillPrototypeProject> {
  return fetchJson<SkillPrototypeProject>('/skill-prototypes', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateSkillPrototypeBaseline(
  prototypeId: string,
  payload: SkillPrototypeBaselineUpdateRequest,
): Promise<SkillPrototypeProject> {
  return fetchJson<SkillPrototypeProject>(`/skill-prototypes/${encodeURIComponent(prototypeId)}/baseline`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function loadSkillTestRuns(params: {
  kind: 'extraction' | 'operation'
  skillId: string
  customerId?: string | null
}): Promise<SkillTestRunSummary[]> {
  const query = new URLSearchParams({ kind: params.kind })
  if (params.customerId) query.set('customerId', params.customerId)
  return fetchJson<SkillTestRunSummary[]>(`/skills/${encodeURIComponent(params.skillId)}/test-runs?${query.toString()}`)
}

export async function loadSkillTestRunDetail(params: {
  kind: 'extraction' | 'operation'
  skillId: string
  runId: string
  customerId?: string | null
}): Promise<SkillTestRunSummary> {
  const query = new URLSearchParams({ kind: params.kind })
  if (params.customerId) query.set('customerId', params.customerId)
  return fetchJson<SkillTestRunSummary>(
    `/skills/${encodeURIComponent(params.skillId)}/test-runs/${encodeURIComponent(params.runId)}?${query.toString()}`,
  )
}

export async function validateSkill(payload: SkillValidateRequest): Promise<SkillValidateResponse> {
  return fetchJson<SkillValidateResponse>('/skills/validate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function testRunSkill(payload: SkillTestRunRequest): Promise<SkillTestRunResponse> {
  return fetchJson<SkillTestRunResponse>('/skills/test-run', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function assistSkill(payload: SkillAssistRequest): Promise<SkillAssistResponse> {
  return fetchJson<SkillAssistResponse>('/skills/assist', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function draftSkillFromSample(payload: SkillDraftFromSampleRequest): Promise<SkillDraftFromSampleResponse> {
  return fetchJson<SkillDraftFromSampleResponse>('/skills/draft-from-sample', {
    method: 'POST',
    body: JSON.stringify({
      taskId: payload.taskId ?? '',
      applicationId: payload.applicationId ?? undefined,
      sampleContext: sampleContextForRequest(payload),
      kind: payload.kind,
      instruction: payload.instruction,
      expectedOutput: payload.expectedOutput ?? '',
      targetIds: payload.targetIds ?? [],
      pageNo: payload.pageNo ?? undefined,
      customerId: payload.customerId ?? undefined,
      dataTypeName: payload.dataTypeName ?? '',
      sourceScope: payload.sourceScope ?? '',
      sourceLabel: payload.sourceLabel ?? '',
      sourceText: payload.sourceText ?? '',
      treeNodeId: payload.treeNodeId ?? undefined,
      treePath: payload.treePath ?? [],
      pageRange: payload.pageRange ?? undefined,
      contentRefs: stripSampleRequestGeometry(payload.contentRefs ?? []),
      confirmedSampleOutput: payload.confirmedSampleOutput,
    }),
  })
}

export async function sampleExtractFromSample(
  payload: SkillDraftFromSampleRequest,
): Promise<SkillSampleExtractFromSampleResponse> {
  return fetchJson<SkillSampleExtractFromSampleResponse>('/skills/sample-extract-from-sample', {
    method: 'POST',
    body: JSON.stringify({
      taskId: payload.taskId ?? '',
      applicationId: payload.applicationId ?? undefined,
      sampleContext: sampleContextForRequest(payload),
      kind: payload.kind,
      instruction: payload.instruction,
      expectedOutput: payload.expectedOutput ?? '',
      targetIds: payload.targetIds ?? [],
      pageNo: payload.pageNo ?? undefined,
      customerId: payload.customerId ?? undefined,
      dataTypeName: payload.dataTypeName ?? '',
      sourceScope: payload.sourceScope ?? '',
      sourceLabel: payload.sourceLabel ?? '',
      sourceText: payload.sourceText ?? '',
      treeNodeId: payload.treeNodeId ?? undefined,
      treePath: payload.treePath ?? [],
      pageRange: payload.pageRange ?? undefined,
      contentRefs: stripSampleRequestGeometry(payload.contentRefs ?? []),
    }),
  })
}

export async function sampleLocateAndExtract(
  payload: SkillSampleLocateAndExtractRequest,
): Promise<SkillSampleLocateAndExtractResponse> {
  return fetchJson<SkillSampleLocateAndExtractResponse>('/skills/sample-locate-and-extract', {
    method: 'POST',
    body: JSON.stringify({
      taskId: payload.taskId ?? '',
      applicationId: payload.applicationId ?? undefined,
      sampleContext: sampleContextForRequest(payload),
      query: payload.query,
      customerId: payload.customerId ?? undefined,
      outputPreference: payload.outputPreference ?? 'auto',
      locatorInstruction: payload.locatorInstruction ?? '',
      extraInstruction: payload.extraInstruction ?? '',
      expectedOutput: payload.expectedOutput ?? '',
      selectedCandidateId: payload.selectedCandidateId ?? undefined,
      runExtraction: payload.runExtraction ?? true,
    }),
  })
}

export async function sampleProcessFromSample(
  payload: SkillDraftFromSampleRequest,
): Promise<SkillSampleProcessFromSampleResponse> {
  return fetchJson<SkillSampleProcessFromSampleResponse>('/skills/sample-process-from-sample', {
    method: 'POST',
    body: JSON.stringify({
      taskId: payload.taskId ?? '',
      applicationId: payload.applicationId ?? undefined,
      sampleContext: sampleContextForRequest(payload),
      kind: payload.kind,
      instruction: payload.instruction,
      expectedOutput: payload.expectedOutput ?? '',
      targetIds: payload.targetIds ?? [],
      pageNo: payload.pageNo ?? undefined,
      customerId: payload.customerId ?? undefined,
      dataTypeName: payload.dataTypeName ?? '',
      sourceScope: payload.sourceScope ?? '',
      sourceLabel: payload.sourceLabel ?? '',
      sourceText: payload.sourceText ?? '',
      treeNodeId: payload.treeNodeId ?? undefined,
      treePath: payload.treePath ?? [],
      pageRange: payload.pageRange ?? undefined,
      contentRefs: stripSampleRequestGeometry(payload.contentRefs ?? []),
    }),
  })
}

export async function loadApplicationWorkshopStepDrafts(
  taskId: string,
  options: { light?: boolean } = {},
): Promise<ApplicationWorkshopStepDraft[]> {
  const normalizedTaskId = taskId.trim()
  if (!normalizedTaskId) {
    throw new Error('应用样例草稿没有系统任务 ID。')
  }
  const params = new URLSearchParams()
  if (options.light) {
    params.set('light', 'true')
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return fetchJson<ApplicationWorkshopStepDraft[]>(`/workbench/tasks/${normalizedTaskId}/application-step-drafts${suffix}`)
}

export async function loadApplicationWorkshopStepDraft(
  taskId: string,
  draftId: string,
): Promise<ApplicationWorkshopStepDraft> {
  const normalizedTaskId = taskId.trim()
  const normalizedDraftId = draftId.trim()
  if (!normalizedTaskId) {
    throw new Error('应用样例草稿没有系统任务 ID。')
  }
  if (!normalizedDraftId) {
    throw new Error('应用样例草稿没有草稿 ID。')
  }
  return fetchJson<ApplicationWorkshopStepDraft>(
    `/workbench/tasks/${normalizedTaskId}/application-step-drafts/${encodeURIComponent(normalizedDraftId)}`,
  )
}

export async function saveApplicationWorkshopStepDraft(
  taskId: string,
  payload: ApplicationWorkshopStepDraftUpsertRequest,
): Promise<ApplicationWorkshopStepDraft> {
  const normalizedTaskId = taskId.trim()
  if (!normalizedTaskId) {
    throw new Error('应用样例草稿没有系统任务 ID。')
  }
  return fetchJson<ApplicationWorkshopStepDraft>(`/workbench/tasks/${normalizedTaskId}/application-step-drafts/${payload.id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteApplicationWorkshopStepDraft(taskId: string, draftId: string): Promise<void> {
  const normalizedTaskId = taskId.trim()
  if (!normalizedTaskId) {
    throw new Error('应用样例草稿没有系统任务 ID。')
  }
  await fetchJson<void>(`/workbench/tasks/${normalizedTaskId}/application-step-drafts/${draftId}`, {
    method: 'DELETE',
  })
}

export async function executeSkillRun(
  taskId: string,
  payload: SkillRunRequest,
): Promise<ObjectOperationExecutionResponse> {
  return fetchJson<ObjectOperationExecutionResponse>(`/tasks/${taskId}/skill-runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function executeObjectOperationRun(
  taskId: string,
  payload: ObjectOperationRunRequest,
): Promise<ObjectOperationExecutionResponse> {
  return fetchJson<ObjectOperationExecutionResponse>(`/tasks/${taskId}/object-operation-runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function loadObjectOperationResult(
  taskId: string,
  runId: string,
): Promise<ObjectOperationResult> {
  return fetchJson<ObjectOperationResult>(`/tasks/${taskId}/object-operation-runs/${runId}`)
}

export async function executePromptRuns(
  taskId: string,
  payload: PromptExecutionRequest,
): Promise<PromptExecutionResponse> {
  const normalizedPayload = normalizePromptExecutionPayload(payload)
  const response = await fetchJson<PromptExecutionResponse>(`/tasks/${taskId}/prompt-runs`, {
    method: 'POST',
    body: JSON.stringify(normalizedPayload),
  })
  return {
    ...response,
    taskDetail: response.taskDetail ? await normalizeTaskDetail(response.taskDetail) : null,
  }
}

export async function executeExtractionSkillRun(
  taskId: string,
  payload: ExtractionSkillRunRequest,
): Promise<PromptExecutionResponse> {
  const response = await fetchJson<PromptExecutionResponse>(`/tasks/${taskId}/extraction-skill-runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return {
    ...response,
    taskDetail: response.taskDetail ? await normalizeTaskDetail(response.taskDetail) : null,
  }
}

export async function executeSchemaRuns(
  taskId: string,
  payload: SchemaRunRequest,
): Promise<PromptExecutionResponse> {
  const response = await fetchJson<PromptExecutionResponse>(`/tasks/${taskId}/schema-runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return {
    ...response,
    taskDetail: response.taskDetail ? await normalizeTaskDetail(response.taskDetail) : null,
  }
}

export async function loadSchemaTemplates(): Promise<SchemaTemplateSummary[]> {
  return fetchJson<SchemaTemplateSummary[]>('/schema-templates')
}

export async function loadSchemaTemplateDetail(templateId: string): Promise<SchemaTemplateDetail> {
  return fetchJson<SchemaTemplateDetail>(`/schema-templates/${templateId}`)
}

export async function createSchemaTemplate(
  payload: SchemaTemplateUpsertRequest,
): Promise<SchemaTemplateDetail> {
  return fetchJson<SchemaTemplateDetail>('/schema-templates', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateSchemaTemplate(
  templateId: string,
  payload: SchemaTemplateUpsertRequest,
): Promise<SchemaTemplateDetail> {
  return fetchJson<SchemaTemplateDetail>(`/schema-templates/${templateId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function uploadAndParseDocument(params: {
  customerId: string
  uploadedByUserId: string
  uploadedByName: string
  roleScope: string
  file: File
  taskName?: string
}): Promise<UploadAndParseResponse> {
  const formData = new FormData()
  formData.append('uploadedByUserId', params.uploadedByUserId)
  formData.append('uploadedByName', params.uploadedByName)
  formData.append('roleScope', params.roleScope)
  if (params.taskName?.trim()) {
    formData.append('taskName', params.taskName.trim())
  }
  formData.append('file', params.file)

  const response = await fetchForm<UploadAndParseResponse>(
    `/customers/${params.customerId}/documents/upload-and-parse`,
    formData,
    { method: 'POST' },
  )

  return {
    ...response,
    document: {
      ...response.document,
      pdfUrl: normalizeFileUrl(response.document.pdfUrl),
      markdownUrl: normalizeFileUrl(response.document.markdownUrl),
      rawJsonUrl: normalizeFileUrl(response.document.rawJsonUrl),
    },
    parse: normalizeParseStatusResponse(response.parse),
  }
}

export async function pollTaskParseStatus(taskId: string): Promise<ParseTaskStatusResponse> {
  const response = await fetchJson<ParseTaskStatusResponse>(`/tasks/${taskId}/parse/poll`, {
    method: 'POST',
  })
  return normalizeParseStatusResponse(response)
}

export async function startTaskParse(taskId: string): Promise<ParseTaskStatusResponse> {
  const response = await fetchJson<ParseTaskStatusResponse>(`/tasks/${taskId}/parse`, {
    method: 'POST',
  })
  return normalizeParseStatusResponse(response)
}

export async function loadApplications(params: {
  status?: 'draft' | 'published' | 'disabled'
  keyword?: string
} = {}): Promise<ApplicationAsset[]> {
  return withApplicationFallback(
    async () => {
      const query = new URLSearchParams()
      query.set('page', '1')
      query.set('pageSize', '100')
      if (params.status === 'published') {
        query.set('publishedOnly', 'true')
      }
      const response = await fetchJson<PaginatedResponse<Record<string, unknown>>>(`/applications?${query.toString()}`)
      return response.items
        .map((item) => normalizeApplicationAsset(item))
        .filter((item) => {
          if (params.status && item.status !== params.status) {
            return false
          }
          const keyword = params.keyword?.trim().toLowerCase()
          if (!keyword) {
            return true
          }
          return [
            item.name,
            item.applicationId,
            item.summary,
            item.documentType,
            item.scenario,
          ].join(' ').toLowerCase().includes(keyword)
        })
    },
    () => {
      const keyword = params.keyword?.trim().toLowerCase() || ''
      return readStoredApplications().filter((item) => {
        if (params.status && item.status !== params.status) {
          return false
        }
        if (!keyword) {
          return true
        }
        return [
          item.name,
          item.applicationId,
          item.summary,
          item.documentType,
          item.scenario,
        ].join(' ').toLowerCase().includes(keyword)
      })
    },
  )
}

export async function loadApplicationDetail(
  applicationId: string,
  options: ApplicationDetailLoadOptions = {},
): Promise<ApplicationAsset> {
  return withApplicationFallback(
    async () => {
      const query = new URLSearchParams()
      if (options.version) {
        query.set('version', options.version)
      }
      if (options.includeDraft) {
        query.set('includeDraft', 'true')
      }
      const queryString = query.size ? `?${query.toString()}` : ''
      const response = await fetchJson<Record<string, unknown>>(`/applications/${encodeURIComponent(applicationId)}${queryString}`)
      return normalizeApplicationAsset(response)
    },
    () => {
      const items = readStoredApplications().filter((item) => item.applicationId === applicationId)
      const matched = options.version
        ? items.find((item) => item.version === options.version)
        : items.find((item) => item.status === 'published') || items[0]
      if (!matched) {
        throw new Error('应用不存在。')
      }
      return matched
    },
  )
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function toInputMappings(input: unknown): ApplicationStepInputMapping[] {
  if (Array.isArray(input)) {
    return input.filter((item): item is ApplicationStepInputMapping => Boolean(item && typeof item === 'object'))
  }
  const record = asRecord(input)
  if (!Object.keys(record).length) {
    return []
  }
  return [{
    source: 'document',
    label: asString(record.label, '文档输入'),
    alias: asString(record.alias, ''),
    targetIds: Array.isArray(record.targetIds) ? record.targetIds.filter((item): item is string => typeof item === 'string') : [],
  }]
}

function toTargetMapping(input: unknown): ApplicationStepTargetMapping | null {
  const record = asRecord(input)
  const targetIds = Array.isArray(record.targetIds) ? record.targetIds.filter((item): item is string => typeof item === 'string') : []
  const targetLabels = Array.isArray(record.targetLabels) ? record.targetLabels.filter((item): item is string => typeof item === 'string') : []
  if (!targetIds.length && !targetLabels.length) {
    return null
  }
  return { targetIds, targetLabels }
}

function normalizeApplicationVersionSummary(raw: Record<string, unknown>): ApplicationVersionSummary {
  return {
    version: asString(raw.version),
    status: (asString(raw.status, 'published') as ApplicationStatus),
    isDefault: Boolean(raw.isDefault),
    stepCount: asNumber(raw.stepCount),
    publishedAt: asString(raw.publishedAt) || null,
    createdAt: asString(raw.createdAt),
    updatedAt: asString(raw.updatedAt),
  }
}

function normalizeApplicationAsset(raw: Record<string, unknown>): ApplicationAsset {
  const versions = Array.isArray(raw.versions)
    ? raw.versions.map((item) => normalizeApplicationVersionSummary(asRecord(item)))
    : []
  const steps = Array.isArray(raw.steps) ? raw.steps.map((item, index) => {
    const step = asRecord(item)
    const outputSummary = asRecord(step.outputSummary)
    const sourceTaskId = asString(step.sourceTaskId || raw.sourceTaskId)
    const skillSnapshot = asRecord(step.skillSnapshot)
    const configSnapshot = asRecord(step.configSnapshot)
    const dependencyRefs = asRecord(step.dependencyRefs)
    const inputMapping = asRecord(step.inputMapping)
    const targetMapping = asRecord(step.targetMapping)
    return {
      id: asString(step.storageId || step.id || `${asString(raw.id)}:step:${index + 1}`, `${asString(raw.id)}:step:${index + 1}`),
      kind: (asString(step.kind, 'operation') as ApplicationStepKind),
      stepOrder: asNumber(step.stepOrder, index + 1),
      skillId: asString(step.skillId),
      skillVersion: asString(step.skillVersion),
      skillName: asString(step.skillName, asString(step.skillId)),
      executor: asString(skillSnapshot.executor, ''),
      outputAlias: asString(dependencyRefs.outputAlias, `step_${index + 1}`),
      sourceSummary: asString(outputSummary.summary || outputSummary.text || outputSummary.message, '已记录该步骤输出。'),
      snapshot: {
        runId: asString(step.sourceRunId),
        promptSnapshot: asString(step.promptSnapshot),
        configSnapshot,
        inputMapping: toInputMappings(inputMapping),
        targetMapping: toTargetMapping(targetMapping),
        resultPreview: asString(outputSummary.summary || outputSummary.text || outputSummary.message),
        sourceTaskId,
        sourcePageNo: typeof step.sourcePageNo === 'number' ? step.sourcePageNo : null,
        semanticLocator: asRecord(dependencyRefs.semanticLocator),
        templateSample: asRecord(dependencyRefs.templateSample),
      },
      sourceDocumentId: asString(step.sourceDocumentId) || null,
      sourceRunId: asString(step.sourceRunId) || null,
      sourceStatus: asString(step.sourceStatus) || null,
      runPurpose: asString(step.runPurpose) || null,
      operationType: asString(step.operationType) || null,
      resultMode: asString(step.resultMode) || null,
      skillSnapshot,
      configSnapshot,
      rawInputMapping: inputMapping,
      rawTargetMapping: targetMapping,
      dependencyRefs,
      outputSummary,
    }
  }) : []
  const lastStep = steps[steps.length - 1]
  const resolvedVersion = asString(raw.resolvedVersion || raw.defaultVersion || raw.latestPublishedVersion || versions[0]?.version, 'draft')
  const sourceTaskId = asString(raw.sourceTaskId)
  const sourceDocumentId = asString(raw.sourceDocumentId)
  const documentType = asString(raw.documentType)
  const name = asString(raw.name)
  return {
    id: asString(raw.id, asString(raw.applicationId)),
    applicationId: asString(raw.id),
    version: resolvedVersion,
    resolvedVersion: asString(raw.resolvedVersion) || null,
    status: (asString(raw.status, 'draft') as ApplicationStatus),
    scope: (asString(raw.scope, 'private') as ApplicationScope),
    defaultVersion: asString(raw.defaultVersion) || null,
    latestPublishedVersion: asString(raw.latestPublishedVersion) || null,
    name,
    summary: asString(raw.description || raw.summary || raw.coverText),
    documentType,
    scenario: asString(raw.scenario),
    coverText: asString(raw.coverText),
    releaseNotes: asString(raw.releaseNotes),
    stepCount: asNumber(raw.stepCount, steps.length),
    createdAt: asString(raw.createdAt),
    updatedAt: asString(raw.updatedAt),
    publishedAt: asString(raw.publishedAt) || null,
    sourceTask: {
      taskId: sourceTaskId,
      taskName: sourceTaskId || '来源任务',
      customerId: asString(raw.customerId),
      customerName: asString(raw.createdByName, '当前客户'),
      documentId: sourceDocumentId,
      documentName: sourceDocumentId || name,
      documentType,
      pageCount: 0,
    },
    steps,
    finalOutputAlias: lastStep?.outputAlias || 'final_output',
    versions,
  }
}

function toApplicationStepSelectionRequest(item: ApplicationStepDefinition, index: number) {
  const dependencyRefs = {
    ...(item.dependencyRefs || {}),
  }
  if (item.snapshot.semanticLocator) {
    dependencyRefs.semanticLocator = item.snapshot.semanticLocator
  }
  if (item.snapshot.templateSample) {
    dependencyRefs.templateSample = item.snapshot.templateSample
  }
  return {
    kind: item.kind,
    runId: item.snapshot.runId,
    stepOrder: index + 1,
    skillId: item.skillId,
    skillVersion: item.skillVersion,
    skillName: item.skillName,
    sourceTaskId: item.snapshot.sourceTaskId || undefined,
    sourceDocumentId: item.sourceDocumentId || undefined,
    sourcePageNo: item.snapshot.sourcePageNo ?? undefined,
    sourceRunId: item.sourceRunId || item.snapshot.runId,
    sourceStatus: item.sourceStatus || undefined,
    runPurpose: item.runPurpose || undefined,
    operationType: item.operationType || undefined,
    resultMode: item.resultMode || undefined,
    skillSnapshot: item.skillSnapshot,
    configSnapshot: item.configSnapshot || item.snapshot.configSnapshot,
    promptSnapshot: item.snapshot.promptSnapshot,
    inputMapping: item.rawInputMapping,
    targetMapping: item.rawTargetMapping,
    dependencyRefs,
    outputSummary: item.outputSummary,
    semanticLocator: item.snapshot.semanticLocator || undefined,
  }
}

function toApplicationDraftCreateRequest(payload: ApplicationDraftPayload, publish: boolean) {
  const sourceTaskId = payload.sourceTask.taskId.trim()
  const realSourceTaskId = sourceTaskId && !sourceTaskId.startsWith('application-sample-') && sourceTaskId !== 'inline-sample'
    ? sourceTaskId
    : ''
  return {
    taskId: realSourceTaskId,
    sourceTaskId: realSourceTaskId || undefined,
    customerId: payload.sourceTask.customerId || payload.sampleContext?.customerId || undefined,
    sampleContext: payload.sampleContext ?? undefined,
    scope: payload.scope,
    name: payload.name.trim(),
    description: payload.summary.trim(),
    documentType: payload.documentType.trim(),
    scenario: payload.scenario.trim(),
    coverText: payload.coverText.trim(),
    releaseNotes: payload.releaseNotes.trim(),
    steps: payload.steps.map(toApplicationStepSelectionRequest),
    publish,
  }
}

export async function saveApplicationDraft(payload: ApplicationDraftPayload): Promise<ApplicationAsset> {
  const response = await fetchJson<Record<string, unknown>>('/applications', {
    method: 'POST',
    body: JSON.stringify(toApplicationDraftCreateRequest(payload, false)),
  })
  return normalizeApplicationAsset(response)
}

export async function publishApplication(payload: ApplicationDraftPayload): Promise<ApplicationAsset> {
  const response = await fetchJson<Record<string, unknown>>('/applications', {
    method: 'POST',
    body: JSON.stringify(toApplicationDraftCreateRequest(payload, true)),
  })
  return normalizeApplicationAsset(response)
}

function toApplicationDraftUpdateRequest(payload: ApplicationDetailUpdatePayload) {
  return {
    scope: payload.scope,
    name: payload.name?.trim(),
    description: payload.summary?.trim(),
    documentType: payload.documentType?.trim(),
    scenario: payload.scenario?.trim(),
    coverText: payload.coverText?.trim(),
    releaseNotes: payload.releaseNotes?.trim(),
    status: payload.status,
    steps: payload.steps?.map(toApplicationStepSelectionRequest),
  }
}

export async function updateApplicationDetail(
  applicationId: string,
  payload: ApplicationDetailUpdatePayload,
): Promise<ApplicationAsset> {
  const response = await fetchJson<Record<string, unknown>>(`/applications/${encodeURIComponent(applicationId)}`, {
    method: 'PATCH',
    body: JSON.stringify(toApplicationDraftUpdateRequest(payload)),
  })
  return normalizeApplicationAsset(response)
}

export async function publishApplicationDetail(
  applicationId: string,
  payload: ApplicationPublishPayload = {},
): Promise<ApplicationAsset> {
  const response = await fetchJson<Record<string, unknown>>(`/applications/${encodeURIComponent(applicationId)}/publish`, {
    method: 'POST',
    body: JSON.stringify({
      version: payload.version?.trim() || undefined,
      setAsDefault: payload.setAsDefault ?? true,
    }),
  })
  return normalizeApplicationAsset(response)
}

export async function planApplicationRun(
  applicationId: string,
  payload: { taskId: string; version?: string | null },
): Promise<ApplicationRunPlanResponse> {
  return fetchJson<ApplicationRunPlanResponse>(`/applications/${encodeURIComponent(applicationId)}/runs/plan`, {
    method: 'POST',
    body: JSON.stringify({
      taskId: payload.taskId,
      version: payload.version || undefined,
    }),
  })
}

export async function executeApplicationRun(
  applicationId: string,
  payload: {
    taskId: string
    version?: string | null
    planId?: string | null
    confirmedPlan?: ApplicationRunPlanResponse | null
  },
): Promise<ApplicationRunDetail> {
  return fetchJson<ApplicationRunDetail>(`/applications/${encodeURIComponent(applicationId)}/runs`, {
    method: 'POST',
    body: JSON.stringify({
      taskId: payload.taskId,
      version: payload.version || undefined,
      planId: payload.planId || undefined,
      confirmedPlan: payload.confirmedPlan || undefined,
    }),
  })
}

export async function loadApplicationRunDetail(
  runId: string,
  options: { includeFinalOutput?: boolean } = {},
): Promise<ApplicationRunDetail> {
  const params = new URLSearchParams()
  if (options.includeFinalOutput === false) {
    params.set('includeFinalOutput', 'false')
  }
  const query = params.toString()
  return fetchJson<ApplicationRunDetail>(
    `/applications/runs/${encodeURIComponent(runId)}${query ? `?${query}` : ''}`,
  )
}

export async function submitApplicationRunReviewFeedback(
  runId: string,
  payload: ApplicationRunReviewFeedbackRequest,
): Promise<ApplicationRunReviewFeedbackResponse> {
  return fetchJson<ApplicationRunReviewFeedbackResponse>(
    `/applications/runs/${encodeURIComponent(runId)}/review-feedback`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export async function runApplication(
  applicationId: string,
  version: string,
  payload: ApplicationRunRequest,
): Promise<ApplicationRunResult> {
  if (!payload.file) {
    throw new Error('请先上传待处理文件。')
  }

  const formData = new FormData()
  formData.append('customerId', payload.customerId)
  formData.append('version', version)
  formData.append('file', payload.file)
  if (payload.note?.trim()) {
    formData.append('note', payload.note.trim())
  }

  return fetchForm<ApplicationRunResult>(
    `/applications/${encodeURIComponent(applicationId)}/run`,
    formData,
    { method: 'POST' },
  )
}

export async function login(payload: LoginRequest): Promise<AuthUser> {
  const response = await fetchJson<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return response.user
}

export async function logout(): Promise<void> {
  await fetchJson<void>('/auth/logout', {
    method: 'POST',
  })
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  return fetchJson<AuthUser>('/auth/me')
}

export async function fetchSystemCapabilities(): Promise<SystemCapabilitiesResponse> {
  return fetchJson<SystemCapabilitiesResponse>('/system/capabilities')
}

export async function loadCustomerWorkspace(customerId: string): Promise<CustomerWorkspaceResponse> {
  return fetchJson<CustomerWorkspaceResponse>(`/customers/${customerId}`)
}

export async function loadCustomerDocuments(
  customerId: string,
  page = 1,
  pageSize = 10,
): Promise<PaginatedResponse<DocumentSummary>> {
  return fetchJson<PaginatedResponse<DocumentSummary>>(
    `/customers/${customerId}/documents?page=${page}&pageSize=${pageSize}`,
  )
}

export async function createCustomer(payload: CreateCustomerRequest): Promise<CustomerSummary> {
  return fetchJson<CustomerSummary>('/customers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function createCustomerWithAccount(
  payload: CreateCustomerProvisionRequest,
): Promise<CreateCustomerProvisionResponse> {
  return fetchJson<CreateCustomerProvisionResponse>('/customers/provision', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
