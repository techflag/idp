<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import ApplicationRunPanel from '../components/ApplicationRunPanel.vue'
import DocumentReviewWorkspace from '../components/DocumentReviewWorkspace.vue'
import PanelCard from '../components/PanelCard.vue'
import TaskWorkbenchActionPanel from '../components/TaskWorkbenchActionPanel.vue'
import {
  executeApplicationRun,
  loadApplications,
  planApplicationRun,
  pollTaskParseStatus,
  runApplication as runApplicationWithFile,
  sampleLocateAndExtract,
  startTaskParse,
} from '../services/workbenchApi'
import { useAuthStore } from '../stores/auth'
import { useCapabilitiesStore } from '../stores/capabilities'
import { useWorkbenchStore } from '../stores/workbench'
import { buildMergedParseResultDetail } from '../utils/applicationTemplateAssets'
import { formatApplicationRunStatus } from '../utils/applicationRunDisplay'
import type {
  ApplicationAsset,
  ApplicationRunPlanResponse,
  ApplicationRunReviewFeedbackRequest,
  PageResultDetail,
  ResultStatus,
  SkillSampleLocateAndExtractResponse,
} from '../types/workbench'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()
const capabilities = useCapabilitiesStore()
const store = useWorkbenchStore()
type ParsePanelTabKey = 'recognition' | 'tree' | 'extract'
const parsePanelActiveTab = ref<ParsePanelTabKey>('recognition')

const uploadInputRef = ref<HTMLInputElement | null>(null)
const restartingParse = ref(false)
const applicationRunLoading = ref(false)
const applicationRunPlan = ref<ApplicationRunPlanResponse | null>(null)
const applicationRunResultDetail = ref<PageResultDetail | null>(null)
const publishedApplications = ref<ApplicationAsset[]>([])
const applicationsLoading = ref(false)
const temporaryExtractionLoading = ref(false)
const temporaryExtractionResult = ref<SkillSampleLocateAndExtractResponse | null>(null)
const temporaryExtractionError = ref('')
const taskLoading = ref(true)
const taskLoadResolved = ref(false)
const PARSE_POLL_INTERVAL_MS = 4000
const PARSE_POLL_RETRY_INTERVAL_MS = 5000
const APPLICATION_RUN_POLL_INTERVAL_MS = 4000
const APPLICATION_RUN_POLL_RETRY_INTERVAL_MS = 5000
const INITIAL_POLL_DELAY_MS = 2000

let parsePollingTimer: number | null = null
let applicationRunPollingTimer: number | null = null
const applicationRunTerminalRefreshes = new Set<string>()

const taskId = computed(() => String(route.params.taskId ?? ''))
const detail = computed(() => store.activeTask)
const isAdminView = computed(() => auth.currentUser?.role === 'admin')
const breadcrumbItems = computed(() => {
  const current = detail.value
  if (!current) return []

  const items: Array<{ key: string; label: string; title?: string; className?: string }> = []
  if (isAdminView.value) {
    items.push({ key: 'admin', label: t('workshop.adminConsole') })
  }

  if (current.task.customerName) {
    items.push({
      key: 'customer',
      label: current.task.customerName,
      title: current.task.customerName,
      className: 'is-customer',
    })
  }

  const documentName = current.document.fileName || current.task.documentName
  if (documentName) {
    items.push({
      key: 'document',
      label: documentName,
      title: documentName,
      className: 'is-document',
    })
  }

  const taskName = current.task.taskName
  if (
    taskName
    && !isDuplicateBreadcrumbName(taskName, documentName)
    && !isDuplicateBreadcrumbName(taskName, current.task.customerName)
  ) {
    items.push({
      key: 'task',
      label: taskName,
      title: taskName,
      className: 'is-task',
    })
  }

  return items
})
const isParseRunning = computed(() => {
  const status = detail.value?.runtime.parseStatus
  return status === 'pending' || status === 'running'
})
const isParseFailed = computed(() => detail.value?.runtime.parseStatus === 'failed')
const parseStatusText = computed(() => {
  if (!detail.value) {
    return ''
  }

  if (isParseRunning.value) {
    return detail.value.runtime.latestRunLabel || t('taskActions.parsing')
  }

  if (isParseFailed.value) {
    return detail.value.runtime.latestRunLabel || t('taskActions.parseFailed')
  }

  return detail.value.runtime.latestRunLabel || ''
})

function normalizeBreadcrumbName(value: string | undefined | null) {
  return String(value ?? '')
    .trim()
    .replace(/\.[a-z0-9]{2,5}$/i, '')
    .replace(/\s*(OCR\s*识别|识别任务|解析任务|结构化解析|文档解析)$/i, '')
    .replace(/[\s　_-]+/g, '')
    .toLowerCase()
}

function isDuplicateBreadcrumbName(value: string | undefined | null, reference: string | undefined | null) {
  const normalizedValue = normalizeBreadcrumbName(value)
  const normalizedReference = normalizeBreadcrumbName(reference)
  if (!normalizedValue || !normalizedReference) {
    return false
  }
  return normalizedValue === normalizedReference
}
const applicationRun = computed(() => detail.value?.applicationRun ?? null)
const applicationRunStatusText = computed(() => formatApplicationRunStatus(applicationRun.value))
const applicationRunTitle = computed(() => applicationRun.value?.applicationName || applicationRun.value?.applicationId || '')
const applicationRunSteps = computed(() => applicationRun.value?.steps ?? [])
const applicationExtractionRunIds = computed(() => applicationRunSteps.value
  .filter((step) => step.kind === 'extraction' && step.executionRunId)
  .map((step) => String(step.executionRunId)))
const applicationExtractionRunKey = computed(() => applicationExtractionRunIds.value.join('|'))
const applicationRunResultLoadKey = computed(() => {
  const currentTaskId = detail.value?.task.id ?? ''
  const runKey = applicationExtractionRunKey.value
  return currentTaskId && runKey ? `${currentTaskId}::${runKey}` : ''
})

function buildSyntheticApplicationRunResultDetail(): PageResultDetail | null {
  const run = applicationRun.value
  const task = detail.value?.task
  const finalOutput = run?.finalOutput
  if (!run || !task || !finalOutput || typeof finalOutput !== 'object') {
    return null
  }
  return {
    id: `application-run:${run.id}`,
    title: run.applicationName || run.applicationId || t('parse.extractionResult'),
    pageNo: 1,
    pageIndex: 0,
    status: run.status === 'running' || run.status === 'pending' ? 'processing' : run.status,
    promptName: run.applicationName || run.applicationId || 'application_run',
    runType: 'summary',
    runPurpose: 'extract_fields',
    pageRange: '',
    errorMessage: run.errorMessage || undefined,
    extractionResult: finalOutput as PageResultDetail['extractionResult'],
    outputText: '',
    validationErrors: [],
  }
}

const parsePanelResult = computed(() => (
  applicationRun.value
    ? applicationRunResultDetail.value ?? buildSyntheticApplicationRunResultDetail() ?? store.currentParseResultDetail
    : store.currentParseResultDetail
))
const parsePanelResultStatus = computed<ResultStatus | null>(() => {
  if (!applicationRun.value) {
    return store.currentParseResultSummary?.status ?? null
  }
  if (applicationRunResultDetail.value?.status) {
    return applicationRunResultDetail.value.status
  }
  if (applicationRun.value.status === 'completed') return 'completed'
  if (applicationRun.value.status === 'failed') return 'failed'
  if (applicationRun.value.status === 'needs_review') return 'needs_review'
  if (applicationRun.value.status === 'running' || applicationRun.value.status === 'pending') return 'processing'
  return null
})
const applicationRunCapability = computed(() => capabilities.getCapability('application.run'))
const applicationRunEnabled = computed(() => {
  const capability = applicationRunCapability.value
  if (!capability) return true
  return capability.enabled && capability.level === 'full'
})
const applicationRunDisabledReason = computed(() => {
  const capability = applicationRunCapability.value
  if (!capability) return ''
  if (capability.requiresConfiguration) {
    return capability.noConfigurationBehavior || t('taskActions.applicationRunConfigMissing')
  }
  if (capability.level !== 'full') {
    return capability.communityBoundary || capability.noConfigurationBehavior || t('taskActions.applicationRunLiteOnly')
  }
  if (!capability.enabled) {
    return capability.noConfigurationBehavior || t('taskActions.applicationRunTemporarilyUnavailable')
  }
  return ''
})
const temporaryExtractionCapability = computed(() => capabilities.getCapability('llm.extract'))
const temporaryExtractionEnabled = computed(() => {
  const capability = temporaryExtractionCapability.value
  if (!capability) return true
  return capability.enabled && capability.level !== 'unavailable'
})
const temporaryExtractionDisabledReason = computed(() => {
  const capability = temporaryExtractionCapability.value
  if (!capability) return ''
  if (capability.requiresConfiguration) {
    return capability.noConfigurationBehavior || t('taskActions.aiExtractConfigMissing')
  }
  if (!capability.enabled || capability.level === 'unavailable') {
    return capability.noConfigurationBehavior || t('taskActions.aiExtractTemporarilyUnavailable')
  }
  return ''
})
const taskApplications = computed(() => {
  const current = detail.value
  const documentType = String(current?.document.fileType || '').toLowerCase()
  const customerId = current?.task.customerId || ''
  return [...publishedApplications.value].sort((left, right) => (
    applicationRecommendationScore(right, customerId, documentType)
    - applicationRecommendationScore(left, customerId, documentType)
  ))
})
onMounted(async () => {
  if (!capabilities.initialized) {
    await capabilities.load()
  }
  await loadTask(taskId.value)
})

onBeforeUnmount(() => {
  stopParsePolling()
  stopApplicationRunPolling()
})

watch(taskId, async (value) => {
  stopParsePolling()
  stopApplicationRunPolling()
  temporaryExtractionResult.value = null
  temporaryExtractionError.value = ''
  await loadTask(value)
})

const showTaskUnavailable = computed(
  () => !store.loadError && taskLoadResolved.value && !taskLoading.value && !detail.value,
)

watch(
  () => detail.value?.task.customerId,
  (customerId) => {
    if (customerId) {
      void loadPublishedApplications()
    }
  },
  { immediate: true },
)

async function loadTask(id: string) {
  taskLoading.value = true
  taskLoadResolved.value = false
  try {
    await store.selectTask(id)
  } catch {
    // 页面直接根据后续状态展示加载失败或不可用，避免把加载过程误判成空态。
  } finally {
    taskLoading.value = false
    taskLoadResolved.value = true
  }
}

function applicationRecommendationScore(application: ApplicationAsset, customerId: string, documentType: string) {
  let score = 0
  if (application.sourceTask.customerId && application.sourceTask.customerId === customerId) {
    score += 4
  }
  const applicationDocumentType = String(application.documentType || '').toLowerCase()
  if (documentType && applicationDocumentType && applicationDocumentType.includes(documentType)) {
    score += 2
  }
  if (application.scope === 'public') {
    score += 1
  }
  return score
}

async function loadPublishedApplications() {
  if (applicationsLoading.value) {
    return
  }
  applicationsLoading.value = true
  try {
    publishedApplications.value = await loadApplications({ status: 'published' })
  } catch (error) {
    Message.warning(error instanceof Error ? error.message : t('taskActions.applicationListLoadFailed'))
  } finally {
    applicationsLoading.value = false
  }
}

watch(
  () => [detail.value?.task.id, store.currentParseResultSummary?.id, store.currentParseResultSummary?.status] as const,
  async ([currentTaskId, resultId, resultStatus], previous) => {
    if (!currentTaskId || !resultId || resultStatus === 'failed') {
      return
    }
    const previousResultId = previous?.[1]
    const previousStatus = previous?.[2]
    const shouldForce = previousResultId === resultId && previousStatus === 'processing' && resultStatus === 'completed'
    await store.ensureCurrentParseResultDetail(shouldForce)
  },
  { immediate: true },
)

watch(
  applicationRunResultLoadKey,
  async (loadKey) => {
    applicationRunResultDetail.value = null
    const currentTaskId = detail.value?.task.id
    const runKey = applicationExtractionRunKey.value
    const runIds = applicationExtractionRunIds.value
    if (!loadKey || !currentTaskId || !runKey || !runIds.length) {
      return
    }
    try {
      const results = await Promise.all(runIds.map((runId) => store.fetchResultDetail(runId, currentTaskId)))
      if (detail.value?.task.id !== currentTaskId || applicationExtractionRunKey.value !== runKey) {
        return
      }
      const resultDetails = results.filter((item): item is PageResultDetail => Boolean(item))
      const result = (
        buildMergedParseResultDetail(resultDetails)
        ?? resultDetails[resultDetails.length - 1]
        ?? buildSyntheticApplicationRunResultDetail()
        ?? null
      )
      applicationRunResultDetail.value = result
      if (result?.extractionResult) {
        showExtractResultTab()
      }
    } catch (error) {
      if (detail.value?.task.id === currentTaskId && applicationExtractionRunKey.value === runKey) {
        Message.warning(error instanceof Error ? error.message : t('taskActions.applicationResultLoadFailed'))
      }
    }
  },
  { immediate: true },
)

watch(
  () => [parsePanelActiveTab.value, detail.value?.task.id, detail.value?.documentTree] as const,
  async ([activeTab, currentTaskId, documentTree]) => {
    if (activeTab !== 'tree' || !currentTaskId || documentTree) {
      return
    }
    try {
      await store.ensureActiveDocumentTree(currentTaskId)
    } catch (error) {
      if (detail.value?.task.id === currentTaskId) {
        Message.warning(error instanceof Error ? error.message : t('taskActions.documentTreeLoadFailed'))
      }
    }
  },
  { immediate: true },
)

function stopParsePolling() {
  if (parsePollingTimer !== null) {
    window.clearTimeout(parsePollingTimer)
    parsePollingTimer = null
  }
}

function stopApplicationRunPolling() {
  if (applicationRunPollingTimer !== null) {
    window.clearTimeout(applicationRunPollingTimer)
    applicationRunPollingTimer = null
  }
}

function startParsePolling() {
  stopParsePolling()

  const poll = async () => {
    const currentTaskId = detail.value?.task.id
    if (!currentTaskId) {
      return
    }

    try {
      const status = await pollTaskParseStatus(currentTaskId)
      await store.refreshTaskDetail(currentTaskId)

      if (status.state === 'pending' || status.state === 'running') {
        parsePollingTimer = window.setTimeout(poll, PARSE_POLL_INTERVAL_MS)
        return
      }

      parsePollingTimer = null
      if (status.state === 'completed') {
        Message.success(t('taskActions.parseCompleted'))
        return
      }

      if (status.state === 'failed') {
        Message.error(status.errorMessage || t('taskActions.parseFailed'))
      }
    } catch {
      parsePollingTimer = window.setTimeout(poll, PARSE_POLL_RETRY_INTERVAL_MS)
    }
  }

  parsePollingTimer = window.setTimeout(poll, INITIAL_POLL_DELAY_MS)
}

watch(
  () => detail.value?.runtime.parseStatus,
  (status) => {
    if (status === 'pending' || status === 'running') {
      startParsePolling()
      return
    }

    stopParsePolling()
  },
  { immediate: true },
)

function startApplicationRunPolling() {
  stopApplicationRunPolling()

  const poll = async () => {
    const currentTaskId = detail.value?.task.id
    const currentRunId = applicationRun.value?.id
    if (!currentTaskId || !currentRunId) {
      applicationRunPollingTimer = null
      return
    }

    try {
      const refreshedRun = await store.refreshApplicationRunDetail(
        currentRunId,
        currentTaskId,
        { includeFinalOutput: false },
      )
      if (refreshedRun?.id !== currentRunId || refreshedRun.taskId !== currentTaskId) {
        applicationRunPollingTimer = null
        return
      }
      if (refreshedRun.status === 'pending' || refreshedRun.status === 'running') {
        applicationRunPollingTimer = window.setTimeout(poll, APPLICATION_RUN_POLL_INTERVAL_MS)
        return
      }

      applicationRunPollingTimer = null
      if (!applicationRunTerminalRefreshes.has(currentRunId)) {
        applicationRunTerminalRefreshes.add(currentRunId)
        try {
          await store.refreshTaskDetail(currentTaskId)
        } catch {
          Message.warning(t('taskActions.applicationStatusUpdatedRefreshFailed'))
        }
      }
      const latestRun = detail.value?.applicationRun
      if (detail.value?.task.id !== currentTaskId || latestRun?.id !== currentRunId) {
        return
      }
      if (refreshedRun.status === 'completed') {
        showExtractResultTab()
        Message.success(t('taskActions.applicationRunCompleted'))
        return
      }
      if (refreshedRun.status === 'needs_review') {
        Message.warning(refreshedRun.errorMessage || t('taskActions.applicationRunNeedsReview'))
        return
      }
      if (refreshedRun.status === 'failed') {
        Message.error(refreshedRun.errorMessage || t('taskActions.applicationRunFailed'))
      }
    } catch {
      applicationRunPollingTimer = window.setTimeout(poll, APPLICATION_RUN_POLL_RETRY_INTERVAL_MS)
    }
  }

  applicationRunPollingTimer = window.setTimeout(poll, INITIAL_POLL_DELAY_MS)
}

watch(
  () => applicationRun.value?.id,
  (runId) => {
    const status = applicationRun.value?.status
    if (runId && (status === 'pending' || status === 'running')) {
      startApplicationRunPolling()
      return
    }
    stopApplicationRunPolling()
  },
  { immediate: true },
)

function backToList() {
  if (store.activeRole === 'admin') {
    router.push({ name: 'admin-tasks' })
    return
  }

  router.push({ name: 'tasks' })
}

function openApplicationDetail() {
  const run = applicationRun.value
  if (!run) return
  router.push({ name: 'admin-applications-detail', params: { applicationId: run.applicationId } })
}

function showExtractResultTab() {
  parsePanelActiveTab.value = 'extract'
}

async function executeConfirmedApplicationPlan(plan: ApplicationRunPlanResponse) {
  const run = applicationRun.value
  const currentTaskId = detail.value?.task.id
  if (!run || !currentTaskId) {
    return
  }
  const nextRun = await executeApplicationRun(run.applicationId, {
    taskId: currentTaskId,
    version: run.version,
    planId: plan.planId,
    confirmedPlan: plan,
  })
  store.mergeApplicationRunDetail(nextRun)
  applicationRunPlan.value = null
  showExtractResultTab()
  Message.success(t('taskActions.applicationRerunStartedCurrentResult'))
}

async function rerunApplication() {
  const run = applicationRun.value
  const currentTaskId = detail.value?.task.id
  if (!run || !currentTaskId || applicationRunLoading.value) {
    return
  }
  applicationRunLoading.value = true
  try {
    const plan = await planApplicationRun(run.applicationId, {
      taskId: currentTaskId,
      version: run.version,
    })
    applicationRunPlan.value = plan
    if (plan.status === 'ready') {
      await executeConfirmedApplicationPlan(plan)
      return
    }
    Message.warning(plan.status === 'blocked'
      ? t('taskActions.applicationPlanBlocked')
      : t('taskActions.applicationPlanNeedsConfirm'))
  } catch (error) {
    Message.error(error instanceof Error ? error.message : t('taskActions.applicationRerunFailed'))
  } finally {
    applicationRunLoading.value = false
  }
}

async function confirmApplicationPlanRun() {
  const plan = applicationRunPlan.value
  if (!plan || applicationRunLoading.value) {
    return
  }
  if (plan.status === 'blocked') {
    Message.error(t('taskActions.applicationPlanBlockedCannotExecute'))
    return
  }
  applicationRunLoading.value = true
  try {
    await executeConfirmedApplicationPlan(plan)
  } catch (error) {
    Message.error(error instanceof Error ? error.message : t('taskActions.applicationPlanConfirmFailed'))
  } finally {
    applicationRunLoading.value = false
  }
}

async function submitApplicationRunReviewFeedback(payload: ApplicationRunReviewFeedbackRequest) {
  const run = applicationRun.value
  if (!run || applicationRunLoading.value) {
    return
  }
  applicationRunLoading.value = true
  try {
    await store.submitApplicationRunReviewFeedback(run.id, payload)
    Message.success(t('taskActions.applicationReviewFeedbackSaved'))
  } catch (error) {
    Message.error(error instanceof Error ? error.message : t('taskActions.applicationReviewFeedbackFailed'))
  } finally {
    applicationRunLoading.value = false
  }
}

async function runTaskApplication(payload: { applicationId: string; version: string | null }) {
  const currentTaskId = detail.value?.task.id
  if (!currentTaskId || applicationRunLoading.value) {
    return
  }
  if (!applicationRunEnabled.value) {
    Message.warning(applicationRunDisabledReason.value || t('taskActions.applicationRunTemporarilyUnavailable'))
    return
  }

  applicationRunLoading.value = true
  applicationRunPlan.value = null
  try {
    const run = await executeApplicationRun(payload.applicationId, {
      taskId: currentTaskId,
      version: payload.version,
    })
    store.mergeApplicationRunDetail(run)
    showExtractResultTab()
    Message.success(t('taskActions.applicationRunStartedCurrentTask'))
  } catch (error) {
    Message.error(error instanceof Error ? error.message : t('taskActions.applicationRunFailed'))
  } finally {
    applicationRunLoading.value = false
  }
}

async function runTemporaryExtraction(payload: { query: string; expectedOutput: string }) {
  const current = detail.value
  const page = store.activePage
  if (!current || !page || temporaryExtractionLoading.value) {
    return
  }
  if (!temporaryExtractionEnabled.value) {
    Message.warning(temporaryExtractionDisabledReason.value || t('taskActions.aiExtractTemporarilyUnavailable'))
    return
  }

  temporaryExtractionLoading.value = true
  temporaryExtractionError.value = ''
  showExtractResultTab()
  try {
    const response = await sampleLocateAndExtract({
      taskId: current.task.id,
      customerId: current.task.customerId,
      query: payload.query,
      expectedOutput: payload.expectedOutput,
      outputPreference: 'auto',
      runExtraction: true,
      sampleContext: {
        source: 'workbench_task_temporary_extraction',
        customerId: current.task.customerId,
        document: {
          id: current.document.id,
          documentId: current.document.id,
          fileName: current.document.fileName,
          pageCount: current.document.pageCount || current.document.sampledPageCount,
        },
        sampleSource: {
          mode: 'page',
          kind: 'extraction',
          title: page.title || current.document.fileName,
          summary: page.summary,
          sourceScope: t('taskActions.sourcePageScope', { page: page.pageNo }),
          pageNo: page.pageNo,
          pageIndex: page.pageIndex,
        },
      },
    })
    temporaryExtractionResult.value = response
    if (response.extractionResult) {
      store.mergeAdHocPageResultDetail(current.task.id, buildTemporaryExtractionResultDetail(response, current.task.id))
      Message.success(response.status === 'needs_review'
        ? t('taskActions.temporaryExtractionResultNeedsCheck')
        : t('taskActions.temporaryExtractionCompleted'))
      return
    }
    if (response.status === 'not_found') {
      Message.warning(response.errorMessage || t('taskActions.temporaryExtractionNotFoundAdjust'))
      return
    }
    Message.warning(response.errorMessage || t('taskActions.temporaryExtractionLocatedNoResult'))
  } catch (error) {
    temporaryExtractionError.value = error instanceof Error ? error.message : t('taskActions.temporaryExtractionFailed')
    Message.error(temporaryExtractionError.value)
  } finally {
    temporaryExtractionLoading.value = false
  }
}

function buildTemporaryExtractionResultDetail(
  response: SkillSampleLocateAndExtractResponse,
  currentTaskId: string,
): PageResultDetail {
  const page = store.activePage
  const locatedPageNo = response.locatedSource?.pageNo ?? page?.pageNo ?? 1
  const locatedPageIndex = response.locatedSource?.pageIndex ?? page?.pageIndex ?? Math.max(locatedPageNo - 1, 0)
  const status: ResultStatus = response.status === 'extracted'
    ? 'completed'
    : response.status === 'needs_review'
      ? 'needs_review'
      : response.status === 'not_found'
        ? 'failed'
        : 'needs_review'
  const pageRange = response.pageRange || response.locatedSource?.sourceScope || t('taskActions.sourcePageScope', { page: locatedPageNo })
  return {
    id: `temporary-extraction-${currentTaskId}-${Date.now()}`,
    title: response.dataTypeName || response.query || t('taskActions.temporaryExtractionTitle'),
    pageNo: locatedPageNo,
    pageIndex: locatedPageIndex,
    status,
    runPhase: status === 'completed' ? 'completed' : status === 'failed' ? 'failed' : 'needs_review',
    resultStage: 'parse',
    runPurpose: 'parse_prompt',
    promptName: t('taskActions.temporaryExtractionTitle'),
    runType: 'page',
    startPageNo: locatedPageNo,
    endPageNo: locatedPageNo,
    pageRange,
    errorMessage: response.errorMessage || response.errors[0] || '',
    evidenceRefs: response.evidenceRefs ?? [],
    promptTrace: response.promptTrace ?? null,
    extractionResult: response.extractionResult ?? null,
    outputText: response.editableOutput || '',
    validationErrors: response.extractionResult?.validationErrors ?? response.errors,
    llmTraceSummary: {
      callCount: response.provider || response.model ? 1 : 0,
      slowCallCount: 0,
      totalHttpMs: response.durationMs || 0,
      totalMs: response.durationMs || 0,
      inputChars: response.inputChars || 0,
      outputChars: response.outputChars || 0,
      promptTokens: response.promptTokens,
      completionTokens: response.completionTokens,
      totalTokens: response.totalTokens,
      model: response.model || null,
      provider: response.provider || null,
      latestStatus: response.status,
      latestErrorType: response.errors.length ? 'temporary_extraction_error' : null,
    },
  }
}

function openApplicationAuthoringFromTask() {
  const currentTaskId = detail.value?.task.id
  if (!currentTaskId) {
    Message.warning(t('taskActions.currentTaskUnavailable'))
    return
  }
  router.push({
    name: 'admin-applications-new',
    query: { taskId: currentTaskId },
  })
}

function openReuploadPicker() {
  uploadInputRef.value?.click()
}

async function rerunCurrentParse() {
  const currentTaskId = detail.value?.task.id
  if (!currentTaskId || restartingParse.value || isParseRunning.value) {
    return
  }

  restartingParse.value = true
  try {
    const status = await startTaskParse(currentTaskId)
    await store.refreshTaskDetail(currentTaskId)
    if (status.state === 'completed') {
      Message.success(t('taskActions.reparseCurrentFileCompleted'))
      return
    }
    Message.success(t('taskActions.reparseCurrentFileStarted'))
  } catch (error) {
    Message.error(error instanceof Error ? error.message : t('taskActions.reparseCurrentFileFailed'))
  } finally {
    restartingParse.value = false
  }
}

async function handleReuploadChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const customerId = detail.value?.task.customerId
  const currentApplicationRun = applicationRun.value

  if (!file || !customerId) {
    input.value = ''
    return
  }

  try {
    if (currentApplicationRun) {
      applicationRunLoading.value = true
      const result = await runApplicationWithFile(
        currentApplicationRun.applicationId,
        currentApplicationRun.version,
        {
          customerId,
          file,
          note: t('taskActions.applicationRunNote', { applicationId: currentApplicationRun.applicationId }),
        },
      )
      if (!result.taskId || !result.runId) {
        throw new Error(result.message || t('taskActions.applicationRunNoValidRecord'))
      }
      await router.push({ name: 'task-detail', params: { taskId: result.taskId } })
      await store.refreshTaskDetail(result.taskId)
      showExtractResultTab()
      Message.success(t('taskActions.uploadedAndApplicationRunStarted'))
      return
    }

    const result = await store.uploadAndParseDocument(customerId, file)
    await router.push({ name: 'task-detail', params: { taskId: result.response.createdTask.id } })
    Message.success(result.parseStatus?.state === 'completed'
      ? t('taskActions.reuploadRecognitionCompleted')
      : t('taskActions.reuploadRecognitionStarted'))
  } catch (error) {
    Message.error(error instanceof Error
      ? error.message
      : (currentApplicationRun ? t('taskActions.uploadAndApplicationRunFailed') : t('taskActions.reuploadRecognitionFailed')))
  } finally {
    applicationRunLoading.value = false
    input.value = ''
  }
}

</script>

<template>
  <div class="workbench-page">
    <PanelCard
      v-if="store.loadError"
      :title="t('taskActions.taskDataLoadFailed')"
      :description="store.loadError"
    >
      <a-empty :description="t('taskActions.backendTaskRecoverHint')" />
      <a-button type="primary" @click="backToList">{{ t('taskActions.backToList') }}</a-button>
    </PanelCard>

    <section v-if="detail" class="workbench-page__context-bar">
      <div class="workbench-page__context-main">
        <nav class="workbench-page__breadcrumb" :aria-label="t('taskActions.taskPathLabel')">
          <template v-for="(item, index) in breadcrumbItems" :key="item.key">
            <strong
              v-if="index === breadcrumbItems.length - 1"
              :class="item.className"
              :title="item.title || item.label"
            >
              {{ item.label }}
            </strong>
            <span v-else :class="item.className" :title="item.title || item.label">
              {{ item.label }}
            </span>
            <span v-if="index < breadcrumbItems.length - 1" class="workbench-page__breadcrumb-separator">/</span>
          </template>
        </nav>
        <span class="workbench-page__breadcrumb-meta">
          {{ t('taskActions.pageCount', { count: detail.document.sampledPageCount || detail.pages.length }) }}
        </span>
      </div>
      <div class="workbench-page__actions">
        <span class="workbench-page__status-chip">{{ detail.task.status }}</span>
        <span v-if="applicationRun" class="workbench-page__app-chip">
          {{ applicationRunTitle }} · {{ applicationRun.version }} · {{ applicationRunStatusText }}
        </span>
        <a-button
          v-if="!applicationRun"
          size="small"
          :loading="restartingParse"
          :disabled="isParseRunning || store.processing"
          @click="rerunCurrentParse"
        >
          {{ t('taskActions.reparseCurrentFile') }}
        </a-button>
        <a-button
          v-if="!applicationRun"
          size="small"
          :loading="store.processing"
          :disabled="isParseRunning || restartingParse"
          @click="openReuploadPicker"
        >
          {{ t('taskActions.uploadNewFileRecognition') }}
        </a-button>
        <a-button size="small" type="secondary" @click="backToList">{{ t('taskActions.back') }}</a-button>
        <input
          ref="uploadInputRef"
          class="workbench-page__file-input"
          type="file"
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
          @change="handleReuploadChange"
        />
      </div>
    </section>
    <div v-if="detail && isParseRunning" class="workbench-page__parse-state">
      <PanelCard :title="t('taskActions.parsing')" :description="parseStatusText || t('taskActions.parsingDescription')">
        <div class="workbench-page__parse-body">
          <a-spin />
          <span>{{ t('taskActions.parsingAutoRefresh') }}</span>
        </div>
      </PanelCard>
    </div>

    <div v-else-if="taskLoading" class="workbench-page__parse-state">
      <PanelCard :title="t('taskActions.taskLoading')" :description="t('taskActions.taskLoadingDescription')">
        <div class="workbench-page__parse-body">
          <a-spin />
          <span>{{ t('taskActions.taskLoadingAutoOpen') }}</span>
        </div>
      </PanelCard>
    </div>

    <DocumentReviewWorkspace
      v-else-if="detail"
      v-model:active-tab="parsePanelActiveTab"
      layout="resizable"
      :detail="detail"
      :current-page-index="store.currentPageIndex"
      :selected-block-id="store.selectedBlockId"
      :data-title="applicationRun ? t('taskActions.applicationExtractionResult') : t('taskActions.parseResult')"
      :page="store.activePage"
      :document-tree="detail?.documentTree ?? null"
      :result="parsePanelResult"
      :result-status="parsePanelResultStatus"
      @change-page="store.setCurrentPage"
      @select-block="store.selectBlock"
    >
      <template #side>
        <div class="workbench-page__side-content">
          <template v-if="applicationRun">
            <ApplicationRunPanel
              :run="applicationRun"
              :plan="applicationRunPlan"
              :loading="applicationRunLoading"
              :disabled="store.processing || isParseRunning"
              @open-application="openApplicationDetail"
              @rerun="rerunApplication"
              @upload-and-run="openReuploadPicker"
              @confirm="confirmApplicationPlanRun"
              @submit-review-feedback="submitApplicationRunReviewFeedback"
            />
          </template>
          <template v-else>
            <TaskWorkbenchActionPanel
              :applications="taskApplications"
              :applications-loading="applicationsLoading"
              :application-run-enabled="applicationRunEnabled"
              :application-run-disabled-reason="applicationRunDisabledReason"
              :application-action-loading="applicationRunLoading"
              :temporary-extraction-enabled="temporaryExtractionEnabled"
              :temporary-extraction-disabled-reason="temporaryExtractionDisabledReason"
              :temporary-extraction-loading="temporaryExtractionLoading"
              :temporary-extraction-result="temporaryExtractionResult"
              :temporary-extraction-error="temporaryExtractionError"
              :disabled="store.processing || isParseRunning"
              :document-name="detail.document.fileName"
              :page-no="store.activePage?.pageNo ?? null"
              :page-count="detail.document.sampledPageCount || detail.pages.length"
              @run-application="runTaskApplication"
              @temporary-extract="runTemporaryExtraction"
              @open-application-authoring="openApplicationAuthoringFromTask"
              @refresh-applications="loadPublishedApplications"
            />
          </template>
        </div>
      </template>
    </DocumentReviewWorkspace>

    <PanelCard
      v-else-if="showTaskUnavailable"
      :title="t('taskActions.taskUnavailable')"
      :description="t('taskActions.taskUnavailableDescription')"
    >
      <a-empty :description="t('taskActions.taskUnavailableEmpty')" />
      <a-button type="primary" @click="backToList">{{ t('taskActions.backToPrevious') }}</a-button>
    </PanelCard>
  </div>
</template>

<style scoped>
.workbench-page {
  display: grid;
  gap: 6px;
  --workbench-column-height: calc(100vh - 102px);
}

.workbench-page__context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 38px;
  padding: 4px 2px 9px;
  border-bottom: 1px solid #d7dde5;
  background: transparent;
}

.workbench-page__context-main {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1 1 auto;
  flex-wrap: wrap;
  row-gap: 3px;
}

.workbench-page__breadcrumb {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 700;
}

.workbench-page__breadcrumb span,
.workbench-page__breadcrumb strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-page__breadcrumb span {
  max-width: 180px;
  color: #64748b;
}

.workbench-page__breadcrumb-separator {
  flex: 0 0 auto;
  max-width: none !important;
  color: #cbd5e1;
}

.workbench-page__breadcrumb .is-document {
  max-width: min(360px, 30vw);
  color: #334155;
  font-weight: 800;
}

.workbench-page__breadcrumb strong {
  max-width: min(360px, 28vw);
  color: #334155;
  font-weight: 800;
}

.workbench-page__breadcrumb-meta {
  color: #64748b;
  font-size: 12px;
  line-height: 1.3;
  white-space: nowrap;
}

.workbench-page__status-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  background: #dcfce7;
  color: #15803d;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.workbench-page__app-chip {
  display: inline-flex;
  align-items: center;
  max-width: 360px;
  height: 24px;
  padding: 0 10px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-page__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.workbench-page__file-input {
  display: none;
}

.workbench-page__actions :deep(.arco-btn) {
  border-radius: 0;
}

.workbench-page__meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.workbench-page__parse-state {
  min-height: var(--workbench-column-height);
}

.workbench-page__parse-body {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0 4px;
}

.workbench-page__meta-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 86px;
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}

.workbench-page__meta-card span {
  color: #64748b;
  font-size: 12px;
}

.workbench-page__meta-card strong {
  margin-top: 4px;
  font-size: 20px;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.workbench-page__side-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  height: 100%;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.workbench-page__process-card {
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid #d7dde5;
  background: #fff;
}

.workbench-page__process-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.workbench-page__process-card-title {
  color: #111827;
  font-size: 12px;
  font-weight: 600;
}

.workbench-page__process-card-content {
  margin: 8px 0 0;
  color: #334155;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}


.workbench-page__side-content > :nth-child(2) {
  flex: 1;
  min-height: 0;
}

.workbench-page__side-content > .application-run-panel {
  flex: 1;
  min-height: 0;
}

.workbench-page__side-content :deep(.arco-btn) {
  border-radius: 0;
}

@media (max-width: 960px) {
  .workbench-page {
    --workbench-column-height: 720px;
  }

  .workbench-page__context-bar {
    flex-direction: column;
    align-items: flex-start;
  }

  .workbench-page__context-main,
  .workbench-page__actions {
    width: 100%;
  }

  .workbench-page__breadcrumb {
    flex-wrap: wrap;
    row-gap: 6px;
  }

  .workbench-page__breadcrumb span,
  .workbench-page__breadcrumb span.is-document,
  .workbench-page__breadcrumb strong {
    max-width: 100%;
  }

  .workbench-page__meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .workbench-page__meta {
    grid-template-columns: 1fr;
  }
}
</style>
