import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  createCustomer as createCustomerRequest,
  createCustomerWithAccount as createCustomerWithAccountRequest,
  executeObjectOperationRun,
  executeExtractionSkillRun,
  executeSkillRun,
  executePromptRuns,
  loadBusinessSkills,
  loadExtractionSkills,
  loadObjectOperationResult,
  loadPageOperationTargets,
  loadApplicationRunDetail,
  loadWorkbenchTaskDocumentTree,
  loadWorkbenchDataset,
  loadPromptRunDetail,
  loadWorkbenchTaskDetail,
  submitApplicationRunReviewFeedback as submitApplicationRunReviewFeedbackRequest,
  uploadAndParseDocument as uploadAndParseDocumentRequest,
} from '../services/workbenchApi'
import { useAuthStore } from './auth'
import type {
  ApplicationDraftContext,
  ApplicationRunDetail,
  ApplicationRunReviewFeedbackRequest,
  ApplicationRunReviewFeedbackResponse,
  ApplicationSourceRunOption,
  CreateCustomerProvisionRequest,
  CreateCustomerRequest,
  BusinessSkill,
  ExtractionSkill,
  ExtractionSkillRunRequest,
  ObjectOperationResult,
  ObjectOperationRunRequest,
  OperationTarget,
  OperationType,
  PageResultDetail,
  PageResultSummary,
  PromptExecutionRequest,
  PromptRunRecordResponse,
  ResultStatus,
  SkillRunRequest,
  WorkbenchDataset,
  WorkbenchDocumentTree,
  TaskApplicationContext,
  TaskStatus,
  UserRole,
  UploadAndParseResponse,
  WorkbenchPromptConfig,
  WorkbenchTaskDetail,
} from '../types/workbench'

export const useWorkbenchStore = defineStore('workbench', () => {
  const auth = useAuthStore()
  const initialized = ref(false)
  const loading = ref(false)
  const loadError = ref('')
  const dataset = ref<WorkbenchDataset | null>(null)
  const activeRole = ref<UserRole>('admin')
  const activeTaskId = ref<string>('')
  const currentPageIndex = ref<number>(0)
  const selectedBlockId = ref<string>('')
  const promptDrafts = ref<Record<number, WorkbenchPromptConfig>>({})
  const pageResultDetails = ref<Record<string, PageResultDetail>>({})
  const targetsByPage = ref<Record<number, OperationTarget[]>>({})
  const businessSkills = ref<BusinessSkill[]>([])
  const extractionSkills = ref<ExtractionSkill[]>([])
  const selectedTargetId = ref<string>('')
  const objectOperationResultsByTarget = ref<Record<string, ObjectOperationResult | null>>({})
  const objectOperationErrorsByTarget = ref<Record<string, string | null>>({})
  const processing = ref(false)
  const pendingResultDetailRequests = new Map<string, Promise<PageResultDetail | null>>()
  const pendingOperationTargetRequests = new Map<string, Promise<OperationTarget[]>>()
  const pendingBusinessSkillRequests = new Map<string, Promise<BusinessSkill[]>>()
  const pendingExtractionSkillRequests = new Map<string, Promise<ExtractionSkill[]>>()
  const pendingApplicationRunRequests = new Map<string, Promise<ApplicationRunDetail>>()
  const pendingDocumentTreeRequests = new Map<string, Promise<WorkbenchDocumentTree | null>>()
  const pendingTaskDetailRequests = new Map<string, Promise<WorkbenchTaskDetail>>()

  function getEffectiveRole(role?: UserRole | null): UserRole {
    if (role === 'user') {
      return 'customer'
    }
    return role ?? 'customer'
  }

  function getActiveUserMeta() {
    if (auth.currentUser) {
      const effectiveRole = getEffectiveRole(auth.currentUser.role)
      return {
        uploadedByUserId: auth.currentUser.username,
        uploadedByName: auth.currentUser.displayName,
        roleScope: effectiveRole === 'admin' ? 'admin,customer' : 'customer',
      }
    }

    return {
      uploadedByUserId: '',
      uploadedByName: '',
      roleScope: activeRole.value === 'admin' ? 'admin,customer' : 'customer',
    }
  }

  function buildPromptPayloadText(promptConfig: WorkbenchPromptConfig) {
    return [
      `表格处理模式：${promptConfig.tableTaskMode || 'parse_json'}`,
      `文本提示词：${promptConfig.textPrompt || '未填写'}`,
      `表格提示词：${promptConfig.tablePrompt || '未填写'}`,
    ].join('\n\n')
  }

  const customers = computed(() => dataset.value?.customers ?? [])
  const tasks = computed(() => dataset.value?.tasks ?? [])
  const visibleTasks = computed(() =>
    tasks.value.filter((task) => task.roleScope.includes(activeRole.value)),
  )

  const activeTask = computed(() => {
    if (!dataset.value || !activeTaskId.value) {
      return null
    }

    return dataset.value.taskDetails[activeTaskId.value] ?? null
  })

  const activePage = computed(() => {
    const task = activeTask.value

    if (!task) {
      return null
    }

    return task.pages.find((page) => page.pageIndex === currentPageIndex.value) ?? task.pages[0] ?? null
  })

  function getResultScopeKey(result: PageResultSummary) {
    const startPageNo = result.startPageNo ?? result.pageNo
    const endPageNo = result.endPageNo ?? result.pageNo
    return `${result.runType ?? 'page'}:${startPageNo}:${endPageNo}:${result.runPurpose ?? 'parse_prompt'}`
  }

  function getLatestEffectiveResults(results: PageResultSummary[]) {
    const seenKeys = new Set<string>()
    return results.filter((result) => {
      const scopeKey = getResultScopeKey(result)
      if (seenKeys.has(scopeKey)) {
        return false
      }
      seenKeys.add(scopeKey)
      return true
    })
  }

  const currentParseResultSummary = computed<PageResultSummary | null>(() => {
    const task = activeTask.value
    const page = activePage.value

    if (!task || !page) {
      return null
    }

    return getLatestEffectiveResults(
      task.pageResults.filter((result) => {
        if (result.runPurpose !== 'parse_prompt') {
          return false
        }
        const startPageNo = result.startPageNo ?? result.pageNo
        const endPageNo = result.endPageNo ?? result.pageNo
        return page.pageNo >= startPageNo && page.pageNo <= endPageNo
      }),
    )[0] ?? null
  })

  const currentParseResultDetail = computed<PageResultDetail | null>(() => {
    const summary = currentParseResultSummary.value
    if (!summary) {
      return null
    }
    return pageResultDetails.value[summary.id] ?? null
  })

  const activeTargets = computed<OperationTarget[]>(() => {
    const page = activePage.value
    if (!page) {
      return []
    }
    return targetsByPage.value[page.pageNo] ?? []
  })

  const selectedTarget = computed<OperationTarget | null>(() => {
    if (!selectedTargetId.value) {
      return activeTargets.value[0] ?? null
    }
    return activeTargets.value.find((item) => item.id === selectedTargetId.value) ?? activeTargets.value[0] ?? null
  })

  const currentObjectOperationResult = computed<ObjectOperationResult | null>(() => {
    const target = selectedTarget.value
    if (!target) {
      return null
    }
    return objectOperationResultsByTarget.value[target.id] ?? null
  })

  const currentObjectOperationError = computed<string | null>(() => {
    const target = selectedTarget.value
    if (!target) {
      return null
    }
    return objectOperationErrorsByTarget.value[target.id] ?? null
  })

  const activeTaskApplicationContext = computed<TaskApplicationContext | null>(() => {
    const detail = activeTask.value
    if (!detail) {
      return null
    }
    return {
      taskId: detail.task.id,
      taskName: detail.task.taskName,
      customerId: detail.task.customerId,
      customerName: detail.task.customerName,
      documentId: detail.document.id,
      documentName: detail.document.fileName,
      documentType: detail.document.fileType,
      pageCount: detail.document.pageCount,
    }
  })

  async function init() {
    if (initialized.value || loading.value) {
      return
    }

    loading.value = true
    loadError.value = ''

    try {
      if (auth.currentUser) {
        activeRole.value = getEffectiveRole(auth.currentUser.role)
      }
      dataset.value = await loadWorkbenchDataset()
      initialized.value = true

      if (!activeTaskId.value) {
        const firstTask = dataset.value.tasks.find((task) => task.roleScope.includes(activeRole.value))

        if (firstTask) {
          selectTask(firstTask.id)
        }
      }
    } catch (error) {
      loadError.value = error instanceof Error ? error.message : '任务数据加载失败。'
      dataset.value = null
      initialized.value = false
      throw error
    } finally {
      loading.value = false
    }
  }

  function seedDatasetWithTaskDetail(detail: WorkbenchTaskDetail) {
    dataset.value = {
      customers: dataset.value?.customers ?? [],
      tasks: [detail.task, ...(dataset.value?.tasks ?? []).filter((task) => task.id !== detail.task.id)],
      taskDetails: {
        ...(dataset.value?.taskDetails ?? {}),
        [detail.task.id]: detail,
      },
    }
    hydrateObjectOperationResults(detail)
  }

  function ensurePromptDrafts(task: WorkbenchTaskDetail) {
    promptDrafts.value = task.pages.reduce<Record<number, WorkbenchPromptConfig>>((drafts, page) => {
      drafts[page.pageIndex] = page.promptConfig
      return drafts
    }, {})
  }

  function loadTaskDetailOnce(
    taskId: string,
    options: { includeDocumentTree?: boolean } = {},
  ): Promise<WorkbenchTaskDetail> {
    const includeDocumentTree = options.includeDocumentTree ?? false
    const requestKey = `${taskId}:${includeDocumentTree ? 'tree' : 'light'}`
    const pendingRequest = pendingTaskDetailRequests.get(requestKey)
    if (pendingRequest) {
      return pendingRequest
    }
    const request = loadWorkbenchTaskDetail(taskId, { includeDocumentTree })
      .finally(() => {
        pendingTaskDetailRequests.delete(requestKey)
      })
    pendingTaskDetailRequests.set(requestKey, request)
    return request
  }

  function setRole(role: UserRole) {
    const effectiveRole = getEffectiveRole(role)
    activeRole.value = effectiveRole

    const availableTask = dataset.value?.tasks.find((task) => task.roleScope.includes(effectiveRole))

    if (availableTask) {
      selectTask(availableTask.id)
    }
  }

  async function selectTask(taskId: string) {
    if (auth.currentUser) {
      activeRole.value = getEffectiveRole(auth.currentUser.role)
    }
    activeTaskId.value = taskId
    selectedBlockId.value = ''
    selectedTargetId.value = ''
    pageResultDetails.value = {}
    targetsByPage.value = {}
    businessSkills.value = []
    extractionSkills.value = []
    objectOperationResultsByTarget.value = {}
    objectOperationErrorsByTarget.value = {}

    if (!dataset.value) {
      const detail = await loadTaskDetailOnce(taskId, { includeDocumentTree: false })
      seedDatasetWithTaskDetail(detail)
      ensurePromptDrafts(detail)
      currentPageIndex.value = detail.pages[0]?.pageIndex ?? 0
      return
    }

    if (!dataset.value.taskDetails[taskId]) {
      const detail = await loadTaskDetailOnce(taskId, { includeDocumentTree: false })
      seedDatasetWithTaskDetail(detail)
    }

    const task = dataset.value.taskDetails[taskId]

    if (!task) {
      return
    }

    ensurePromptDrafts(task)
    hydrateObjectOperationResults(task)
    currentPageIndex.value = task.pages[0]?.pageIndex ?? 0
  }

  function setCurrentPage(pageIndex: number) {
    currentPageIndex.value = pageIndex
    selectedBlockId.value = ''
    selectedTargetId.value = ''
  }

  function selectBlock(blockId: string, pageIndex?: number) {
    if (typeof pageIndex === 'number') {
      currentPageIndex.value = pageIndex
    }

    selectedBlockId.value = blockId
  }

  function selectTarget(targetId: string) {
    selectedTargetId.value = targetId
    const target = activeTargets.value.find((item) => item.id === targetId)
    if (target?.blockIds?.[0]) {
      selectedBlockId.value = target.blockIds[0]
    }
  }

  function locateTarget(targetId: string) {
    const target = activeTargets.value.find((item) => item.id === targetId)
    if (!target) {
      return
    }
    selectedTargetId.value = targetId
    if (target.blockIds[0]) {
      selectedBlockId.value = target.blockIds[0]
    }
  }

  function formatPromptRuntimeStatus(status: PageResultSummary['status']) {
    if (status === 'processing') {
      return '执行中'
    }
    if (status === 'completed') {
      return '已完成'
    }
    if (status === 'failed') {
      return '失败'
    }
    if (status === 'needs_review') {
      return '需复核'
    }
    return '待执行'
  }

  function aggregatePromptResultStatus(results: PageResultSummary[]): TaskStatus {
    if (!results.length) {
      return 'pending'
    }
    if (results.some((item) => item.status === 'processing')) {
      return 'running'
    }
    if (results.some((item) => item.status === 'failed')) {
      return 'failed'
    }
    if (results.some((item) => item.status === 'needs_review')) {
      return 'needs_review'
    }
    if (results.every((item) => item.status === 'completed')) {
      return 'completed'
    }
    return 'pending'
  }

  function buildPromptResultSummary(detail: PageResultDetail): PageResultSummary {
    return {
      id: detail.id,
      title: detail.title,
      pageNo: detail.pageNo,
      pageIndex: detail.pageIndex,
      status: detail.status,
      runPhase: detail.runPhase,
      phaseStartedAt: detail.phaseStartedAt,
      lastHeartbeatAt: detail.lastHeartbeatAt,
      resultStage: detail.resultStage,
      runPurpose: detail.runPurpose,
      promptName: detail.promptName,
      runType: detail.runType,
      startPageNo: detail.startPageNo,
      endPageNo: detail.endPageNo,
      pageRange: detail.pageRange,
      errorMessage: detail.errorMessage,
      schemaTemplateId: detail.schemaTemplateId,
      schemaTemplateName: detail.schemaTemplateName,
      schemaTemplateVersion: detail.schemaTemplateVersion,
    }
  }

  function mergePromptResultDetailIntoTask(taskId: string, detail: PageResultDetail) {
    if (!dataset.value) {
      return
    }
    const task = dataset.value.taskDetails[taskId]
    if (!task) {
      return
    }

    const nextSummary = buildPromptResultSummary(detail)
    const nextResults = [...task.pageResults]
    const existingIndex = nextResults.findIndex((item) => item.id === detail.id)
    if (existingIndex >= 0) {
      nextResults[existingIndex] = nextSummary
    } else {
      nextResults.unshift(nextSummary)
    }

    const effectiveResults = getLatestEffectiveResults(nextResults)
    const pagePromptStatus = aggregatePromptResultStatus(effectiveResults)
    const latestRunLabel = `${detail.promptName} ${detail.pageRange || `第 ${detail.pageNo} 页`} ${formatPromptRuntimeStatus(detail.status)}`
    const nextDetail: WorkbenchTaskDetail = {
      ...task,
      task: {
        ...task.task,
        status: pagePromptStatus,
        promptRunCount: effectiveResults.length,
      },
      runtime: {
        ...task.runtime,
        pagePromptStatus,
        failedPageCount: effectiveResults.filter((item) => item.status === 'failed').length,
        completedPageCount: effectiveResults.filter((item) => item.status === 'completed').length,
        latestRunLabel,
      },
      pageResults: nextResults,
    }
    hydrateTaskDetail(nextDetail)
  }

  function mergeAdHocPageResultDetail(taskId: string, detail: PageResultDetail) {
    pageResultDetails.value = {
      ...pageResultDetails.value,
      [detail.id]: detail,
    }
    mergePromptResultDetailIntoTask(taskId, detail)
  }

  async function fetchResultDetail(
    resultId: string,
    taskId: string = activeTaskId.value,
    options: { force?: boolean } = {},
  ) {
    if (!taskId) {
      return null
    }
    const cachedDetail = pageResultDetails.value[resultId]
    const task = dataset.value?.taskDetails[taskId]
    const summary = task?.pageResults.find((item) => item.id === resultId)
    if (
      !options.force
      && cachedDetail
      && (!summary || !isCachedResultDetailStale(summary, cachedDetail))
    ) {
      return cachedDetail
    }
    const requestKey = `${taskId}:${resultId}`
    const pendingRequest = pendingResultDetailRequests.get(requestKey)
    if (pendingRequest) {
      return await pendingRequest
    }
    const request = (async () => {
      const detail = await loadPromptRunDetail(taskId, resultId)
      pageResultDetails.value = {
        ...pageResultDetails.value,
        [resultId]: detail,
      }
      mergePromptResultDetailIntoTask(taskId, detail)
      return detail
    })()
    pendingResultDetailRequests.set(requestKey, request)
    try {
      return await request
    } finally {
      pendingResultDetailRequests.delete(requestKey)
    }
  }

  async function ensureCurrentParseResultDetail(force = false) {
    const summary = currentParseResultSummary.value
    if (!summary || summary.status === 'failed') {
      return null
    }
    const cachedDetail = pageResultDetails.value[summary.id]
    if (!force && cachedDetail && !isCachedResultDetailStale(summary, cachedDetail)) {
      return cachedDetail
    }
    return await fetchResultDetail(summary.id, activeTaskId.value, { force })
  }

  function isCachedResultDetailStale(summary: PageResultSummary, detail: PageResultDetail) {
    if (detail.status !== summary.status) {
      return true
    }
    if (summary.status !== 'completed' && summary.status !== 'needs_review') {
      return false
    }
    const hasExtractionPayload = Boolean(
      detail.extractionResult
      && (
        detail.extractionResult.fields.length > 0
        || detail.extractionResult.tables.length > 0
        || detail.extractionResult.outputs.length > 0
        || detail.extractionResult.summary.trim()
        || detail.extractionResult.errors.length > 0
        || detail.extractionResult.validationErrors.length > 0
      ),
    )
    const hasProcessPayload = Boolean(detail.schemaProcessResult || detail.schemaOutput)
    const hasErrorPayload = Boolean(detail.errorMessage || detail.validationErrors?.length)

    return !hasExtractionPayload && !hasProcessPayload && !hasErrorPayload
  }

  async function ensureOperationTargets(force = false) {
    const task = activeTask.value
    const page = activePage.value
    if (!task || !page) {
      return []
    }
    if (!force && targetsByPage.value[page.pageNo]?.length) {
      if (!selectedTargetId.value) {
        selectedTargetId.value = targetsByPage.value[page.pageNo][0]?.id ?? ''
      }
      return targetsByPage.value[page.pageNo]
    }
    const requestKey = `${task.task.id}:${page.pageNo}`
    const pendingRequest = pendingOperationTargetRequests.get(requestKey)
    if (pendingRequest) {
      return await pendingRequest
    }
    const request = (async () => {
      const response = await loadPageOperationTargets(task.task.id, page.pageNo)
    targetsByPage.value = {
      ...targetsByPage.value,
      [page.pageNo]: response.targets,
    }
    if (!selectedTargetId.value || !response.targets.some((target) => target.id === selectedTargetId.value)) {
      selectedTargetId.value = response.targets[0]?.id ?? ''
    }
    return response.targets
    })()
    pendingOperationTargetRequests.set(requestKey, request)
    try {
      return await request
    } finally {
      pendingOperationTargetRequests.delete(requestKey)
    }
  }

  function updatePrompt(
    pageIndex: number,
    promptType: keyof WorkbenchPromptConfig,
    prompt: WorkbenchPromptConfig[keyof WorkbenchPromptConfig],
  ) {
    const currentPrompt = promptDrafts.value[pageIndex] ?? activeTask.value?.pages.find((page) => page.pageIndex === pageIndex)?.promptConfig

    if (!currentPrompt) {
      return
    }

    promptDrafts.value = {
      ...promptDrafts.value,
      [pageIndex]: {
        ...currentPrompt,
        [promptType]: prompt,
      },
    }
  }

  function reusePrompt(sourcePageIndex: number, targetPageIndex: number) {
    const prompt = promptDrafts.value[sourcePageIndex]

    if (!prompt) {
      return
    }

    promptDrafts.value = {
      ...promptDrafts.value,
      [targetPageIndex]: {
        ...prompt,
      },
    }
  }

  function hydrateTaskDetail(detail: WorkbenchTaskDetail) {
    if (!dataset.value) {
      seedDatasetWithTaskDetail(detail)
      return
    }
    const existingDetail = dataset.value.taskDetails[detail.task.id]
    const nextDetail = (
      detail.documentTree == null
      && existingDetail?.documentTree
      && detail.runtime.parseStatus === 'completed'
    )
      ? { ...detail, documentTree: existingDetail.documentTree }
      : detail
    dataset.value = {
      ...dataset.value,
      tasks: [
        nextDetail.task,
        ...dataset.value.tasks.filter((task) => task.id !== nextDetail.task.id),
      ],
      taskDetails: {
        ...dataset.value.taskDetails,
        [nextDetail.task.id]: nextDetail,
      },
    }
    hydrateObjectOperationResults(nextDetail)
  }

  function hydrateObjectOperationResults(detail: WorkbenchTaskDetail) {
    const persistedResults = detail.objectOperationResults ?? []
    if (!persistedResults.length) {
      return
    }

    const nextResults = { ...objectOperationResultsByTarget.value }
    const nextErrors = { ...objectOperationErrorsByTarget.value }
    const hydratedTargetIds = new Set<string>()
    for (const result of persistedResults) {
      for (const targetId of getObjectOperationResultTargetIds(result)) {
        if (hydratedTargetIds.has(targetId)) {
          continue
        }
        hydratedTargetIds.add(targetId)
        nextResults[targetId] = result
        nextErrors[targetId] = null
      }
    }
    objectOperationResultsByTarget.value = nextResults
    objectOperationErrorsByTarget.value = nextErrors
  }

  function getObjectOperationResultTargetIds(result: ObjectOperationResult) {
    return [result.targetId, ...(result.relatedTargetIds ?? [])].filter(Boolean)
  }

  function buildApplicationPromptSnapshot(detail: PageResultDetail | null) {
    if (!detail) {
      return ''
    }
    const parts = [
      detail.promptTrace?.text?.prompt?.trim() || '',
      detail.promptTrace?.table?.prompt?.trim() || '',
    ].filter(Boolean)
    return parts.join('\n\n')
  }

  function summarizeApplicationResultPreview(value: unknown, fallback: string) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim().slice(0, 12000)
    }
    if (value && typeof value === 'object') {
      try {
        return JSON.stringify(value, null, 2).slice(0, 20000)
      } catch {
        return fallback
      }
    }
    return fallback
  }

  function findTargetLabels(pageNo: number, targetIds: string[]) {
    const knownTargets = targetsByPage.value[pageNo] ?? []
    return targetIds.map((targetId) => knownTargets.find((item) => item.id === targetId)?.label || targetId)
  }

  function getResultSourceSkillId(result: ObjectOperationResult) {
    return result.skillId || result.sourceSkillId || ''
  }

  function getResultSourceSkillVersion(result: ObjectOperationResult) {
    return result.skillVersion || result.sourceSkillVersion || ''
  }

  function getResultSourceSkillName(result: ObjectOperationResult) {
    return result.sourceSkillName || result.skillId || result.sourceSkillId || ''
  }

  function buildOperationSelectionKey(result: ObjectOperationResult) {
    return [
      getResultSourceSkillId(result) || 'unknown-skill',
      getResultSourceSkillVersion(result) || 'unknown-version',
      result.pageNo,
      ...getObjectOperationResultTargetIds(result).sort(),
    ].join(':')
  }

  function isSameObjectOperationResult(left: ObjectOperationResult, right: ObjectOperationResult) {
    if (left.id && right.id && left.id === right.id) {
      return true
    }
    const leftTargets = getObjectOperationResultTargetIds(left).sort().join('|')
    const rightTargets = getObjectOperationResultTargetIds(right).sort().join('|')
    return left.pageNo === right.pageNo
      && getResultSourceSkillId(left) === getResultSourceSkillId(right)
      && getResultSourceSkillVersion(left) === getResultSourceSkillVersion(right)
      && leftTargets === rightTargets
  }

  async function collectApplicationDraftContext(
    options: { includeRunDetails?: boolean; includeOperationTargets?: boolean } = {},
  ): Promise<ApplicationDraftContext> {
    const detail = activeTask.value
    const sourceTask = activeTaskApplicationContext.value
    if (!detail || !sourceTask) {
      throw new Error('当前任务上下文不可用。')
    }

    const preloaders: Array<Promise<unknown>> = [
      ensureExtractionSkills(),
      ensureBusinessSkills(),
    ]
    if (options.includeOperationTargets) {
      preloaders.push(ensureOperationTargets())
    }
    await Promise.all(preloaders)

    const parseSummaries = getLatestEffectiveResults(
      detail.pageResults.filter((item) =>
        item.runPurpose === 'parse_prompt'
        && (item.status === 'completed' || item.status === 'needs_review'),
      ),
    )
    const parseDetails: Array<PageResultDetail | null> = options.includeRunDetails
      ? await Promise.all(parseSummaries.map((item) => fetchResultDetail(item.id, detail.task.id)))
      : []
    const parseOptionCandidates: Array<ApplicationSourceRunOption | null> = parseDetails
      .map((resultDetail, index) => {
        const runMeta = resultDetail?.extractionResult?.runMeta
        const skillId = String(runMeta?.skillId || '').trim()
        const skillVersion = String(runMeta?.skillVersion || '').trim()
        if (!resultDetail || !skillId || !skillVersion) {
          return null
        }
        const matchedSkill = extractionSkills.value.find((item) =>
          item.id === skillId && item.version === skillVersion,
        ) || extractionSkills.value.find((item) => item.id === skillId)
        const resultPreview = summarizeApplicationResultPreview(
          resultDetail.extractionResult,
          resultDetail.title || '解析结果',
        )
        return {
          id: `parse:${resultDetail.id}`,
          kind: 'extraction' as const,
          runId: resultDetail.id,
          skillId,
          skillVersion,
          skillName: matchedSkill?.name || skillId,
          executor: String(runMeta?.executor || matchedSkill?.executor || ''),
          pageNo: resultDetail.pageNo,
          title: resultDetail.title || matchedSkill?.name || skillId,
          summary: resultDetail.extractionResult?.summary || resultDetail.promptName || '结构化解析结果',
          createdAt: resultDetail.lastHeartbeatAt || resultDetail.phaseStartedAt || null,
          promptSnapshot: buildApplicationPromptSnapshot(resultDetail),
          configSnapshot: (runMeta?.configSnapshot as Record<string, unknown>) || {},
          inputMapping: [
            {
              source: 'document',
              label: `任务文档 ${detail.document.fileName}`,
            },
          ],
          outputAlias: `parse_${index + 1}`,
          resultPreview,
          targetMapping: null,
          recommended: resultDetail.id === currentParseResultSummary.value?.id,
        }
      })
    const parseOptions = parseOptionCandidates.filter(
      (item): item is ApplicationSourceRunOption => item !== null,
    )

    const operationResults: ObjectOperationResult[] = (options.includeRunDetails ? [...(detail.objectOperationResults ?? [])] : [])
      .filter((item) =>
        getResultSourceSkillId(item)
        && getResultSourceSkillVersion(item)
        && item.source === 'runtime',
      )
      .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
    const operationSelectionKeys = new Map<string, string>()
    for (const result of operationResults) {
      operationSelectionKeys.set(buildOperationSelectionKey(result), result.id)
    }
    const operationOptions: ApplicationSourceRunOption[] = operationResults.map((result, index) => {
      const targetIds = getObjectOperationResultTargetIds(result)
      const sourceSkillId = getResultSourceSkillId(result)
      const sourceSkillVersion = getResultSourceSkillVersion(result)
      const matchedSkill = businessSkills.value.find((item) =>
        item.id === sourceSkillId && (!sourceSkillVersion || item.version === sourceSkillVersion),
      ) || businessSkills.value.find((item) => item.id === sourceSkillId)
      return {
        id: `operation:${result.id}`,
        kind: 'operation',
        runId: result.id,
        skillId: sourceSkillId,
        skillVersion: sourceSkillVersion,
        skillName: matchedSkill?.name || getResultSourceSkillName(result) || '业务处理',
        executor: result.executor || matchedSkill?.executor || '',
        pageNo: result.pageNo,
        title: matchedSkill?.name || getResultSourceSkillName(result) || `业务处理 ${index + 1}`,
        summary: result.summary || '业务处理结果',
        createdAt: result.createdAt,
        promptSnapshot: '',
        configSnapshot: result.configSnapshot || {},
        inputMapping: [
          {
            source: index === 0 ? 'current_targets' : 'previous_step_output',
            label: index === 0 ? '当前任务提取对象' : '上一处理步骤输出',
            targetIds,
          },
        ],
        outputAlias: `operation_${index + 1}`,
        resultPreview: summarizeApplicationResultPreview(result.outputPayload, result.summary || '业务处理输出'),
        targetMapping: {
          targetIds,
          targetLabels: findTargetLabels(result.pageNo, targetIds),
        },
        recommended: operationSelectionKeys.get(buildOperationSelectionKey(result)) === result.id,
      }
    })

    const missingRequirements: string[] = []
    if (!parseOptions.length) {
      missingRequirements.push('当前任务还没有可发布的数据提取步骤。')
    }

    const suggestedName = `${detail.task.taskName} 应用`
    const recommendedOperationSteps = operationOptions.filter((item) => item.recommended)
    return {
      sourceTask,
      parseOptions,
      operationOptions,
      defaultParseOptionId: parseOptions.find((item) => item.recommended)?.id || parseOptions[0]?.id || '',
      defaultOperationOptionIds: recommendedOperationSteps.length
        ? recommendedOperationSteps.map((item) => item.id)
        : operationOptions.map((item) => item.id),
      missingRequirements,
      suggestedName,
      suggestedSummary: `复用 ${detail.document.fileName} 当前任务中验证通过的数据提取步骤，业务处理步骤可按需继续追加。`,
      suggestedDocumentType: detail.document.fileType || '通用文档',
      suggestedScenario: `${detail.task.customerName} · ${detail.task.taskName}`,
      suggestedCoverText: `基于任务 ${detail.task.id} 的数据提取与后续处理闭环`,
      suggestedReleaseNotes: [
        `简介：${suggestedName} 复用了当前任务中已验证的数据提取步骤。`,
        `来源任务：${detail.task.id} / ${detail.task.taskName}`,
        `输入材料：${detail.document.fileName}（${detail.document.fileType}）`,
        `步骤数量：${parseOptions.length} 个数据提取候选步骤 + ${operationOptions.length} 个业务处理候选步骤`,
        '建议使用方式：上传同类文档后先复用数据提取步骤，再按场景追加业务处理。',
      ].join('\n'),
    }
  }

  function cacheObjectOperationResult(result: ObjectOperationResult) {
    const nextResults = { ...objectOperationResultsByTarget.value }
    const nextErrors = { ...objectOperationErrorsByTarget.value }
    for (const targetId of getObjectOperationResultTargetIds(result)) {
      nextResults[targetId] = result
      nextErrors[targetId] = null
    }
    objectOperationResultsByTarget.value = nextResults
    objectOperationErrorsByTarget.value = nextErrors
  }

  function mergeObjectOperationResultIntoActiveTask(result: ObjectOperationResult) {
    const taskId = activeTaskId.value
    if (!dataset.value || !taskId) {
      return
    }
    const task = dataset.value.taskDetails[taskId]
    if (!task) {
      return
    }
    const nextResults = [
      result,
      ...(task.objectOperationResults ?? []).filter((item) => !isSameObjectOperationResult(item, result)),
    ]
    hydrateTaskDetail({
      ...task,
      objectOperationResults: nextResults,
    })
  }

  function mapRunStatusToResultStatus(status: PromptRunRecordResponse['status']): ResultStatus {
    if (status === 'completed') {
      return 'completed'
    }
    if (status === 'failed') {
      return 'failed'
    }
    if (status === 'needs_review') {
      return 'needs_review'
    }
    return 'processing'
  }

  function mergePromptRunsIntoActiveTask(runs: PromptRunRecordResponse[]) {
    const task = activeTask.value
    const taskId = activeTaskId.value
    if (!task || !taskId || !dataset.value || !runs.length) {
      return
    }

    const nextResults = [...task.pageResults]
    for (const run of runs) {
      const pageNo = run.startPageNo
      const pageIndex = Math.max(0, pageNo - 1)
      const summary: PageResultSummary = {
        id: run.id,
        title: run.runName,
        pageNo,
        pageIndex,
        status: mapRunStatusToResultStatus(run.status),
        runPhase: run.runPhase,
        phaseStartedAt: run.phaseStartedAt,
        lastHeartbeatAt: run.lastHeartbeatAt,
        resultStage: run.runPurpose === 'post_process' || run.runPurpose === 'schema_process' || run.runPurpose === 'summary'
          ? 'process'
          : 'parse',
        runPurpose: run.runPurpose,
        promptName: run.promptName,
        runType: run.runType,
        startPageNo: run.startPageNo,
        endPageNo: run.endPageNo,
        pageRange: run.pageRange,
        errorMessage: run.errorMessage,
        schemaTemplateId: run.schemaTemplateId,
        schemaTemplateName: run.schemaTemplateName,
        schemaTemplateVersion: run.schemaTemplateVersion,
      }
      const existingIndex = nextResults.findIndex((item) => item.id === run.id)
      if (existingIndex >= 0) {
        nextResults[existingIndex] = summary
      } else {
        nextResults.unshift(summary)
      }
    }

    const nextDetail: WorkbenchTaskDetail = {
      ...task,
      pageResults: nextResults,
    }
    hydrateTaskDetail(nextDetail)
  }

  function mergeApplicationRunDetail(run: ApplicationRunDetail) {
    const taskId = run.taskId
    if (!dataset.value || !taskId) {
      return
    }
    const task = dataset.value.taskDetails[taskId]
    if (!task) {
      return
    }

    hydrateTaskDetail({
      ...task,
      applicationRun: run,
    })
  }

  async function refreshApplicationRunDetail(
    runId: string,
    expectedTaskId: string = activeTaskId.value,
    options: { includeFinalOutput?: boolean } = {},
  ) {
    if (!runId) {
      return null
    }
    const requestKey = `${runId}:${options.includeFinalOutput === false ? 'light' : 'full'}`
    const pendingRequest = pendingApplicationRunRequests.get(requestKey)
    if (pendingRequest) {
      const run = await pendingRequest
      if (!expectedTaskId || run.taskId === expectedTaskId) {
        mergeApplicationRunDetail(run)
      }
      return run
    }

    const request = loadApplicationRunDetail(runId, options)
    pendingApplicationRunRequests.set(requestKey, request)
    try {
      const run = await request
      if (!expectedTaskId || run.taskId === expectedTaskId) {
        mergeApplicationRunDetail(run)
      }
      return run
    } finally {
      pendingApplicationRunRequests.delete(requestKey)
    }
  }

  async function submitApplicationRunReviewFeedback(
    runId: string,
    payload: ApplicationRunReviewFeedbackRequest,
  ): Promise<ApplicationRunReviewFeedbackResponse> {
    const response = await submitApplicationRunReviewFeedbackRequest(runId, payload)
    mergeApplicationRunDetail(response.run)
    return response
  }

  async function refreshTaskDetail(
    taskId: string = activeTaskId.value,
    options: { includeDocumentTree?: boolean } = {},
  ) {
    if (!taskId) {
      return
    }
    const detail = await loadTaskDetailOnce(taskId, {
      includeDocumentTree: options.includeDocumentTree ?? false,
    })
    hydrateTaskDetail(detail)
    if (taskId === activeTaskId.value) {
      ensurePromptDrafts(detail)
    }
  }

  async function ensureActiveDocumentTree(taskId: string = activeTaskId.value) {
    if (!taskId || !dataset.value) {
      return null
    }
    const task = dataset.value.taskDetails[taskId]
    if (!task) {
      return null
    }
    if (task.documentTree) {
      return task.documentTree
    }
    const pendingRequest = pendingDocumentTreeRequests.get(taskId)
    if (pendingRequest) {
      return pendingRequest
    }
    const request = loadWorkbenchTaskDocumentTree(taskId)
      .then((documentTree) => {
        const currentTask = dataset.value?.taskDetails[taskId]
        if (dataset.value && currentTask && documentTree) {
          hydrateTaskDetail({
            ...currentTask,
            documentTree,
          })
        }
        return documentTree
      })
      .finally(() => {
        pendingDocumentTreeRequests.delete(taskId)
      })
    pendingDocumentTreeRequests.set(taskId, request)
    return request
  }

  async function ensureBusinessSkills(force = false) {
    const task = activeTask.value
    const customerId = task?.task.customerId ?? ''
    const requestKey = customerId || 'platform'
    if (!force && businessSkills.value.length) {
      return businessSkills.value
    }
    const pendingRequest = pendingBusinessSkillRequests.get(requestKey)
    if (pendingRequest) {
      return pendingRequest
    }
    const request = loadBusinessSkills(customerId || null)
      .then((items) => {
        businessSkills.value = items
        return items
      })
      .finally(() => {
        pendingBusinessSkillRequests.delete(requestKey)
      })
    pendingBusinessSkillRequests.set(requestKey, request)
    return request
  }

  async function ensureExtractionSkills(force = false) {
    const task = activeTask.value
    const customerId = task?.task.customerId ?? ''
    const requestKey = customerId || 'platform'
    if (!force && extractionSkills.value.length) {
      return extractionSkills.value
    }
    const pendingRequest = pendingExtractionSkillRequests.get(requestKey)
    if (pendingRequest) {
      return pendingRequest
    }
    const request = loadExtractionSkills(customerId || null)
      .then((items) => {
        extractionSkills.value = items
        return items
      })
      .finally(() => {
        pendingExtractionSkillRequests.delete(requestKey)
      })
    pendingExtractionSkillRequests.set(requestKey, request)
    return request
  }

  async function runObjectOperation(payload: {
    targetId: string
    operationType: OperationType
    instruction: string
    resultMode?: ObjectOperationRunRequest['resultMode']
    relatedTargetIds?: string[]
  }) {
    const task = activeTask.value
    const page = activePage.value
    const target = activeTargets.value.find((item) => item.id === payload.targetId)
    if (!task || !page || !target) {
      return null
    }

    selectedTargetId.value = target.id
    objectOperationResultsByTarget.value = {
      ...objectOperationResultsByTarget.value,
      [target.id]: null,
    }
    objectOperationErrorsByTarget.value = {
      ...objectOperationErrorsByTarget.value,
      [target.id]: null,
    }
    processing.value = true
    try {
      const relatedTargets = activeTargets.value.filter((item) =>
        (payload.relatedTargetIds ?? []).includes(item.id),
      )
      const response = await executeObjectOperationRun(task.task.id, {
        pageNo: page.pageNo,
        target,
        relatedTargets,
        operationType: payload.operationType,
        instruction: payload.instruction,
        resultMode: payload.resultMode ?? 'auto',
      })
      if (response.run.status === 'failed') {
        throw new Error(response.run.errorMessage || '业务处理失败。')
      }
      const result = response.result ?? await loadObjectOperationResult(task.task.id, response.run.id)
      cacheObjectOperationResult(result)
      mergeObjectOperationResultIntoActiveTask(result)
      return response
    } catch (error) {
      objectOperationErrorsByTarget.value = {
        ...objectOperationErrorsByTarget.value,
        [target.id]: error instanceof Error ? error.message : '业务处理失败。',
      }
      throw error
    } finally {
      processing.value = false
    }
  }

  async function runSkillOperation(payload: Omit<SkillRunRequest, 'pageNo'>) {
    const task = activeTask.value
    const page = activePage.value
    const targetId = payload.targetIds[0] ?? ''
    if (!task || !page || !targetId) {
      return null
    }

    selectedTargetId.value = targetId
    objectOperationResultsByTarget.value = {
      ...objectOperationResultsByTarget.value,
      [targetId]: null,
    }
    objectOperationErrorsByTarget.value = {
      ...objectOperationErrorsByTarget.value,
      [targetId]: null,
    }
    processing.value = true
    try {
      const response = await executeSkillRun(task.task.id, {
        pageNo: page.pageNo,
        ...payload,
      })
      if (response.run.status === 'failed') {
        throw new Error(response.run.errorMessage || '业务处理失败。')
      }
      const result = response.result ?? await loadObjectOperationResult(task.task.id, response.run.id)
      cacheObjectOperationResult(result)
      mergeObjectOperationResultIntoActiveTask(result)
      return response
    } catch (error) {
      objectOperationErrorsByTarget.value = {
        ...objectOperationErrorsByTarget.value,
        [targetId]: error instanceof Error ? error.message : '业务处理失败。',
      }
      throw error
    } finally {
      processing.value = false
    }
  }

  async function runPromptProcessing(payload?: Pick<
    PromptExecutionRequest,
    'promptName' | 'promptText' | 'runMode' | 'createSummary' | 'pageContext' | 'tableTaskMode'
  >) {
    const task = activeTask.value
    const page = activePage.value
    if (!task || !page) {
      return null
    }

    processing.value = true
    try {
      const promptConfig = promptDrafts.value[page.pageIndex] ?? page.promptConfig
      const promptText = payload?.promptText ?? buildPromptPayloadText(promptConfig)
      const response = await executePromptRuns(task.task.id, {
        promptName: payload?.promptName ?? '页面提示词配置',
        promptText,
        startPageNo: page.pageNo,
        endPageNo: page.pageNo,
        runMode: payload?.runMode ?? 'page',
        createSummary: payload?.createSummary ?? false,
        tableTaskMode: payload?.tableTaskMode ?? promptConfig.tableTaskMode,
        pageContext: payload?.pageContext,
      })
      if (response.taskDetail) {
        hydrateTaskDetail(response.taskDetail)
        ensurePromptDrafts(response.taskDetail)
      } else {
        mergePromptRunsIntoActiveTask(response.runs)
      }
      const runId = response.runs[0]?.id
      if (runId) {
        await fetchResultDetail(runId, task.task.id)
      }
      return response
    } finally {
      processing.value = false
    }
  }

  async function runExtractionSkillProcessing(
    payload: Omit<ExtractionSkillRunRequest, 'pageNo'>,
    options: { fetchDetail?: boolean } = {},
  ) {
    const task = activeTask.value
    const page = activePage.value
    if (!task || !page) {
      return null
    }

    processing.value = true
    try {
      const response = await executeExtractionSkillRun(task.task.id, {
        pageNo: page.pageNo,
        ...payload,
      })
      if (response.taskDetail) {
        hydrateTaskDetail(response.taskDetail)
        ensurePromptDrafts(response.taskDetail)
      } else {
        mergePromptRunsIntoActiveTask(response.runs)
      }
      const runId = response.runs[0]?.id
      if (runId && options.fetchDetail !== false) {
        await fetchResultDetail(runId, task.task.id)
      }
      return response
    } finally {
      processing.value = false
    }
  }

  async function uploadAndParseDocument(customerId: string, file: File, taskName?: string) {
    processing.value = true
    try {
      const userMeta = getActiveUserMeta()
      const response: UploadAndParseResponse = await uploadAndParseDocumentRequest({
        customerId,
        file,
        taskName,
        ...userMeta,
      })

      if (dataset.value) {
        dataset.value = {
          ...dataset.value,
          tasks: [response.createdTask, ...dataset.value.tasks.filter((item) => item.id !== response.createdTask.id)],
        }
      }

      await selectTask(response.createdTask.id)
      return {
        response,
        parseStatus: response.parse,
      }
    } finally {
      processing.value = false
    }
  }

  async function createCustomer(payload: CreateCustomerRequest) {
    processing.value = true
    try {
      const customer = await createCustomerRequest(payload)
      if (dataset.value) {
        dataset.value = {
          ...dataset.value,
          customers: [...dataset.value.customers, customer],
        }
      }
      return customer
    } finally {
      processing.value = false
    }
  }

  async function createCustomerWithAccount(payload: CreateCustomerProvisionRequest) {
    processing.value = true
    try {
      const response = await createCustomerWithAccountRequest(payload)
      if (dataset.value) {
        dataset.value = {
          ...dataset.value,
          customers: [...dataset.value.customers, response.customer],
        }
      }
      return response
    } finally {
      processing.value = false
    }
  }

  function reset() {
    initialized.value = false
    loading.value = false
    loadError.value = ''
    dataset.value = null
    activeTaskId.value = ''
    currentPageIndex.value = 0
    selectedBlockId.value = ''
    pageResultDetails.value = {}
    promptDrafts.value = {}
    businessSkills.value = []
    extractionSkills.value = []
    objectOperationResultsByTarget.value = {}
    objectOperationErrorsByTarget.value = {}
    processing.value = false
  }

  return {
    activeTaskApplicationContext,
    activePage,
    activeRole,
    activeTask,
    currentPageIndex,
    currentParseResultSummary,
    currentParseResultDetail,
    activeTargets,
    businessSkills,
    extractionSkills,
    selectedTarget,
    currentObjectOperationResult,
    currentObjectOperationError,
    customers,
    initialized,
    loading,
    loadError,
    processing,
    promptDrafts,
    selectedBlockId,
    selectedTargetId,
    tasks,
    visibleTasks,
    init,
    reset,
    refreshTaskDetail,
    ensureActiveDocumentTree,
    refreshApplicationRunDetail,
    submitApplicationRunReviewFeedback,
    mergeApplicationRunDetail,
    mergeAdHocPageResultDetail,
    fetchResultDetail,
    ensureCurrentParseResultDetail,
    ensureOperationTargets,
    ensureBusinessSkills,
    ensureExtractionSkills,
    reusePrompt,
    runObjectOperation,
    runSkillOperation,
    runPromptProcessing,
    runExtractionSkillProcessing,
    createCustomer,
    createCustomerWithAccount,
    collectApplicationDraftContext,
    uploadAndParseDocument,
    selectBlock,
    selectTarget,
    locateTarget,
    selectTask,
    seedDatasetWithTaskDetail,
    setCurrentPage,
    setRole,
    updatePrompt,
  }
})
