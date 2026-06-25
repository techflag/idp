<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ApplicationStepManager from '../components/ApplicationStepManager.vue'
import ApplicationWorkshopHeader from '../components/ApplicationWorkshopHeader.vue'
import DocumentReviewWorkspace from '../components/DocumentReviewWorkspace.vue'
import ProcessingStepDrawer from '../components/ProcessingStepDrawer.vue'
import StepSkillEditorModal from '../components/StepSkillEditorModal.vue'
import {
  buildPageContentRanges,
  buildPageSourceText,
  isTableRangeKind,
  safeJson,
} from '../utils/applicationWorkshopContent'
import {
  buildMergedParseResultDetail,
  buildTemplateApplicationContext,
  buildTemplateSampleParseResult,
  buildTemplateSampleTaskDetail,
  hasTemplateSampleRecognitionContext,
  normalizeExtractionResult,
  selectLatestTaskParseResultSummaries,
} from '../utils/applicationTemplateAssets'
import {
  dedupeServerStepDrafts,
  defaultStepName,
  normalizeLegacyProcessingStep,
  normalizePersistedSampleExtraction,
  normalizePersistedSampleProcessing,
  normalizePersistedSkillDevelopment,
  normalizePersistedSampleSource,
  processingStepFromServerDraft,
  processingStepToServerDraft,
  sampleTraceFromResponse,
} from '../utils/applicationStepDrafts'
import {
  buildTreeNodePreviewRanges as buildDocumentTreePreviewRanges,
  findBestRangeForTreeNode as findBestDocumentTreeRange,
} from '../utils/applicationTreeRanges'
import { cloneJson, plainRecord } from '../utils/objectData'
import {
  createSkillPrototype,
  createSkill,
  deleteApplicationWorkshopStepDraft,
  draftSkillFromSample,
  loadApplicationDetail,
  loadApplicationWorkshopStepDraft,
  loadApplicationWorkshopStepDrafts,
  loadCustomers,
  loadObjectOperationResult,
  loadPromptRunDetail,
  loadSkillDetail,
  planApplicationRun,
  pollTaskParseStatus,
  publishApplication,
  publishApplicationDetail,
  saveApplicationDraft,
  saveApplicationWorkshopStepDraft,
  sampleExtractFromSample,
  sampleLocateAndExtract,
  sampleProcessFromSample,
  startTaskParse,
  updateSkillPrototypeBaseline,
  updateApplicationDetail,
} from '../services/workbenchApi'
import { useWorkbenchStore } from '../stores/workbench'
import { useAuthStore } from '../stores/auth'
import { useCapabilitiesStore } from '../stores/capabilities'
import { t } from '../i18n'
import type {
  ApplicationAsset,
  ApplicationDraftContext,
  ApplicationDraftPayload,
  ApplicationRunPlanResponse,
  ApplicationSourceRunOption,
  ApplicationStepDefinition,
  ApplicationStepKind,
  OperationTarget,
  PageResultDetail,
  PromptRunRecordResponse,
  ResultStatus,
  SkillSampleContext,
  SkillSampleLocateAndExtractResponse,
  UnifiedSkill,
  WorkbenchPage,
} from '../types/workbench'
import type {
  ApplicationPlanSummary,
  ContentRange,
  DocumentTreeSource,
  ParsePanelTabKey,
  ProcessingStepDraft,
  SampleSource,
  SampleSourceMode,
  SkillDevelopmentAsset,
} from '../types/applicationWorkshop'

const LEGACY_DEMO_TASK_ID = 'task-a0070dd475'
const STEP_RUN_POLL_INTERVAL_MS = 1500
const STEP_RUN_MAX_ATTEMPTS = 20
const STEP_RUN_DETAIL_TIMEOUT_MS = 30000
const PARSE_POLL_INTERVAL_MS = 4000
const PARSE_POLL_RETRY_INTERVAL_MS = 5000
const INITIAL_POLL_DELAY_MS = 1600
const LEGACY_PROCESSING_STEPS_STORAGE_PREFIX = 'idp:application-workshop:processing-steps:'

type StepRunSyncState = {
  draftId: string
  runId: string
  kind: ApplicationStepKind
  status: 'starting' | 'running' | 'syncing' | 'completed' | 'failed' | 'needs_review'
  message: string
  resultPreview?: string
  validationErrors?: string[]
  detailStatus?: ResultStatus | string
  updatedAt: string
}
type StepRunOutcome = {
  status: 'processing' | 'completed' | 'failed' | 'needs_review' | 'empty'
  detail: PageResultDetail | null
  message: string
  resultPreview: string
  validationErrors: string[]
}
type ExtractionTrialExpectation = {
  outputType: string
  fieldLabels: string[]
  fieldCount: number
  tableHeaders: string[]
  tableRowCount: number
  recordFields: string[]
  recordCount: number
}

const route = useRoute()
const router = useRouter()
const store = useWorkbenchStore()
const auth = useAuthStore()
const capabilities = useCapabilitiesStore()

const taskLoading = ref(true)
const contextLoading = ref(false)
const generating = ref(false)
const sampleExtracting = ref(false)
const sampleProcessing = ref(false)
const runningStep = ref(false)
const stepRunState = ref<StepRunSyncState | null>(null)
const llmExtractCapability = computed(() => capabilities.getCapability('llm.extract'))
const llmExtractProvider = computed(() => capabilities.getProvider('llm.dashscope'))
const prototypeOptimizationCapability = computed(() => capabilities.getCapability('skill.prototypeOptimization'))
const prototypeOptimizationEnabled = computed(() => Boolean(prototypeOptimizationCapability.value?.enabled))
const sampleExtractDisabled = computed(() => {
  const capability = llmExtractCapability.value
  return Boolean(capability && !capability.enabled)
})
const sampleExtractDisabledReason = computed(() => {
  const capability = llmExtractCapability.value
  const provider = llmExtractProvider.value
  if (provider?.status === 'not_configured') {
    return provider.message
  }
  if (capability?.requiresConfiguration) {
    return capability.noConfigurationBehavior || '当前 AI 抽取能力缺少必要配置。'
  }
  if (capability && !capability.enabled) {
    return capability.noConfigurationBehavior || '当前版本暂不可使用 AI 抽取。'
  }
  return ''
})
const sampleExtractApplyUrl = computed(() => llmExtractProvider.value?.applyUrl || '')
const isStepRunSyncActive = computed(() => {
  if (runningStep.value) return true
  const status = stepRunState.value?.status
  return status === 'starting' || status === 'running' || status === 'syncing'
})
const prototypeCreating = ref(false)
const saveLoading = ref(false)
const uploadingSample = ref(false)
const restartingParse = ref(false)
const uploadCustomerLoading = ref(false)
const uploadCustomerFallbackOptions = ref<Array<{ id: string; name: string }>>([])
const parsePanelActiveTab = ref<ParsePanelTabKey>('recognition')
const selectedRangeId = ref('')
const selectedTreeNode = ref<DocumentTreeSource | null>(null)
const uploadInputRef = ref<HTMLInputElement | null>(null)
const uploadCustomerId = ref('')
const sourceMode = ref<SampleSourceMode>('document')
const dataTypeName = ref('')
const locatorInstruction = ref('')
const processingGoal = ref('')
const expectedOutput = ref('')
const applicationName = ref('')
const contextError = ref('')
const templateAssetIssue = ref<{
  title: string
  description: string
  sourceTaskId?: string
} | null>(null)
const stepDrawerVisible = ref(false)
const skillEditorVisible = ref(false)
const editingStepId = ref('')
const applicationDraftContext = ref<ApplicationDraftContext | null>(null)
const currentDraft = ref<ProcessingStepDraft | null>(null)
const processingSteps = ref<ProcessingStepDraft[]>([])
const savedApplication = ref<ApplicationAsset | null>(null)
const editingApplication = ref<ApplicationAsset | null>(null)
const lastPlan = ref<ApplicationRunPlanResponse | null>(null)
const taskWideParseResultDetail = ref<PageResultDetail | null>(null)
const stepRunResultDetails = ref<Record<string, PageResultDetail>>({})
let parsePollingTimer: number | null = null
let sampleExtractionSaveTimer: number | null = null
let sampleProcessingSaveTimer: number | null = null
let taskWideParseResultLoadSeq = 0

const editingApplicationId = computed(() => {
  const paramId = route.params.applicationId
  const queryId = route.query.applicationId
  if (typeof paramId === 'string' && paramId.trim()) return paramId.trim()
  if (typeof queryId === 'string' && queryId.trim()) return queryId.trim()
  return ''
})
const isEditingApplication = computed(() => Boolean(editingApplicationId.value))
const loadingSampleMaterialText = computed(() =>
  t('workshop.loadingSampleMaterial', {
    target: taskId.value || editingApplicationId.value || t('workshop.newApplication'),
  }),
)
function routeTaskIdFromQuery() {
  const queryTaskId = route.query.taskId
  return typeof queryTaskId === 'string' ? queryTaskId.trim() : ''
}

const hasLegacyDemoTaskQuery = computed(() =>
  !editingApplicationId.value && routeTaskIdFromQuery() === LEGACY_DEMO_TASK_ID
)
const taskId = computed(() => {
  if (hasLegacyDemoTaskQuery.value) return ''
  return routeTaskIdFromQuery()
})

const detail = computed(() => {
  if (!taskId.value && !editingApplicationId.value) return null
  return store.activeTask
})
const runtimeTaskId = computed(() => detail.value?.task.id || taskId.value)
const activePage = computed(() => store.activePage)
const taskParseResultSummaries = computed(() =>
  selectLatestTaskParseResultSummaries(detail.value?.pageResults ?? []),
)
const taskParseResultSummaryKey = computed(() =>
  taskParseResultSummaries.value
    .map((item) => `${item.id}:${item.status}:${item.runPhase || ''}`)
    .join('|'),
)
const templateSampleParseResult = computed(() =>
  buildTemplateSampleParseResult(editingApplication.value || savedApplication.value),
)
const parsePanelResult = computed(() =>
  taskWideParseResultDetail.value
  || templateSampleParseResult.value
  || store.currentParseResultDetail,
)
const parsePanelResultStatus = computed<ResultStatus | null>(() =>
  parsePanelResult.value?.status
  || store.currentParseResultSummary?.status
  || null,
)
const pageCount = computed(() => detail.value?.document.sampledPageCount || detail.value?.pages.length || 0)
const isParseRunning = computed(() => {
  const status = detail.value?.runtime.parseStatus
  return status === 'pending' || status === 'running'
})
const isParseFailed = computed(() => detail.value?.runtime.parseStatus === 'failed')
const parseStatusText = computed(() => {
  if (!detail.value) return ''
  if (isParseRunning.value) return detail.value.runtime.latestRunLabel || 'OCR 识别中'
  if (isParseFailed.value) return detail.value.runtime.latestRunLabel || 'OCR 识别失败'
  return detail.value.runtime.latestRunLabel || 'OCR 已完成'
})
const activeTargets = computed(() => store.activeTargets)
const selectedTarget = computed(() => store.selectedTarget)
const uploadCustomerOptions = computed(() => {
  const options: Array<{ id: string; name: string }> = []
  const appendOption = (id?: string | null, name?: string | null) => {
    const normalizedId = String(id || '').trim()
    if (!normalizedId || options.some((item) => item.id === normalizedId)) return
    options.push({
      id: normalizedId,
      name: String(name || '').trim() || normalizedId,
    })
  }
  store.customers.forEach((customer) => appendOption(customer.id, customer.name))
  uploadCustomerFallbackOptions.value.forEach((customer) => appendOption(customer.id, customer.name))
  auth.currentUser?.customerIds.forEach((customerId) => appendOption(customerId, customerId))
  const currentTask = detail.value?.task
  if (currentTask) appendOption(currentTask.customerId, currentTask.customerName || currentTask.customerId)
  const applicationCustomer = editingApplication.value?.sourceTask || savedApplication.value?.sourceTask || null
  if (applicationCustomer?.customerId) appendOption(applicationCustomer.customerId, applicationCustomer.customerName)
  return options
})
const sampleUploadBusy = computed(() => uploadingSample.value || uploadCustomerLoading.value)
const effectiveUploadCustomerId = computed(() =>
  uploadCustomerId.value
  || detail.value?.task.customerId
  || editingApplication.value?.sourceTask.customerId
  || savedApplication.value?.sourceTask.customerId
  || uploadCustomerOptions.value[0]?.id
  || '',
)
const contentRanges = computed(() => (detail.value?.pages ?? []).flatMap((page) => buildPageContentRanges(page)))
const previewContentRanges = computed(() => {
  const treeRanges = selectedTreeNode.value ? buildTreeNodePreviewRanges(selectedTreeNode.value) : []
  return treeRanges.length ? [...contentRanges.value, ...treeRanges] : contentRanges.value
})
const activePageRanges = computed(() =>
  contentRanges.value.filter((range) => range.pageIndex === activePage.value?.pageIndex),
)
const selectedRange = computed(() =>
  contentRanges.value.find((range) => range.id === selectedRangeId.value) ?? null,
)
const verifiedSteps = computed(() => collectPublishableProcessingSteps())
const canSaveApplication = computed(() =>
  Boolean(
    applicationDraftContext.value
    && verifiedSteps.value.some((item) => item.kind === 'extraction')
  ),
)
const visiblePlanSummary = computed<ApplicationPlanSummary | null>(() => {
  if (!lastPlan.value) return null
  const selected = lastPlan.value.steps.filter((item) => item.selected)
  const stepWarnings = lastPlan.value.steps.flatMap((item) => item.warnings)
  const warnings = lastPlan.value.warnings.length + stepWarnings.length
  const targetCount = selected.reduce((sum, item) => sum + item.targets.length, 0)
  const blockedCount = lastPlan.value.status === 'blocked'
    ? lastPlan.value.steps.filter((item) => !item.selected).length
    : 0
  const reviewCount = lastPlan.value.steps.filter((item) => item.needsReview || item.executionGate?.needsReview).length
  const firstUnselected = lastPlan.value.steps.find((item) => !item.selected)
  const effectiveStatus = lastPlan.value.status === 'ready' && (!selected.length || !targetCount)
    ? 'blocked'
    : lastPlan.value.status
  return {
    status: effectiveStatus,
    requiresConfirmation: lastPlan.value.requiresConfirmation,
    totalStepCount: lastPlan.value.steps.length,
    selectedCount: selected.length,
    targetCount,
    warnings,
    blockedCount,
    reviewCount,
    firstIssue: lastPlan.value.warnings[0] || stepWarnings[0] || firstUnselected?.reason || '',
  }
})

const activeSource = computed<SampleSource>(() => {
  const mode = sourceMode.value
  const draftSource = currentDraft.value?.sampleSource
  if (stepDrawerVisible.value && draftSource) {
    return draftSource
  }
  if (draftSource && draftSource.mode === mode && (editingStepId.value || currentDraft.value?.id.startsWith('application:'))) {
    return draftSource
  }
  if (mode === 'target' && selectedTarget.value) {
    const target = selectedTarget.value
    return {
      mode,
      kind: 'operation',
      title: `提取结果 · ${target.label}`,
      summary: target.excerpt || target.valueText || target.label,
      sourceScope: `第 ${target.pageNo} 页 · 已结构化对象`,
      sourceText: buildTargetSourceText(target),
      pageNo: target.pageNo,
      pageIndex: pageIndexFromPageNo(target.pageNo),
      targetIds: [target.id],
    }
  }

  if (mode === 'tree' && selectedTreeNode.value) {
    const node = selectedTreeNode.value
    return {
      mode,
      kind: 'extraction',
      title: `文档树 · ${node.label}`,
      summary: node.preview || `${node.typeLabel} · ${node.meta || '文档树'}`,
      sourceScope: node.sourceScope || node.meta || '文档树节点',
      sourceText: buildTreeSourceText(node),
      pageNo: node.pageNos.length === 1 ? node.pageNos[0] : null,
      pageIndex: node.pageNos.length === 1 ? pageIndexFromPageNo(node.pageNos[0]) : null,
      targetIds: [],
      treeNodeId: node.id,
      treePath: buildTreeNodePath(node),
      pageRange: buildPageRange(node.pageNos),
      contentRefs: buildTreeContentRefs(node),
    }
  }

  if (mode === 'selection' && selectedRange.value) {
    const range = selectedRange.value
    return {
      mode,
      kind: 'extraction',
      title: range.label,
      summary: range.summary,
      sourceScope: range.pageRange,
      sourceText: range.text || range.summary,
      pageNo: range.pageNo,
      pageIndex: range.pageIndex,
      targetIds: [],
    }
  }

  if (mode === 'document') {
    return {
      mode,
      kind: 'extraction',
      title: '整份样例材料',
      summary: `${pageCount.value} 页，系统会从整份 DocParser 结果中学习动态匹配线索`,
      sourceScope: '整份文档',
      sourceText: buildDocumentSourceText(),
      pageNo: null,
      pageIndex: null,
      targetIds: [],
    }
  }

  const page = activePage.value
  return {
    mode: 'page',
    kind: 'extraction',
    title: page ? `当前页完整内容 · 第 ${page.pageNo} 页` : '当前页完整内容',
    summary: page ? `${page.blocks.length} 个 OCR 内容块，包含本页文本、表格和列表结构` : '使用当前页全部 OCR 内容作为样例证据',
    sourceScope: page ? `第 ${page.pageNo} 页完整内容` : '当前页完整内容',
    sourceText: page ? buildPageSourceText(page) : '',
    pageNo: page?.pageNo ?? null,
    pageIndex: page?.pageIndex ?? null,
    targetIds: [],
  }
})

const effectiveDataTypeName = computed(() =>
  dataTypeName.value.trim() || defaultDataTypeName(activeSource.value),
)

function sampleRequestTaskId() {
  return taskId.value.trim()
}

function currentApplicationIdForSample() {
  return editingApplicationId.value
    || editingApplication.value?.applicationId
    || savedApplication.value?.applicationId
    || ''
}

function buildSkillSampleContext(source?: SampleSource): SkillSampleContext | null {
  const taskDetail = detail.value
  const applicationId = currentApplicationIdForSample()
  const sampleSource = source || currentDraft.value?.sampleSource || activeSource.value
  if (!taskDetail && !sampleSource?.sourceText?.trim()) {
    return null
  }
  const operationTargets = activeTargets.value.length
    ? activeTargets.value
    : (selectedTarget.value ? [selectedTarget.value] : [])
  return {
    sampleId: applicationId
      ? `application-sample-${applicationId}`
      : (taskDetail?.task.id || sampleRequestTaskId() || 'inline-sample'),
    source: applicationId && !sampleRequestTaskId() ? 'application_template' : 'task_sample',
    applicationId: applicationId || null,
    customerId: taskDetail?.task.customerId || effectiveUploadCustomerId.value || null,
    document: taskDetail?.document ? cloneJson(taskDetail.document) as Record<string, unknown> : {},
    pages: taskDetail?.pages ? cloneJson(taskDetail.pages) as WorkbenchPage[] : [],
    documentTree: taskDetail?.documentTree ? cloneJson(taskDetail.documentTree) as SkillSampleContext['documentTree'] : null,
    operationTargets: cloneJson(operationTargets) as OperationTarget[],
    sampleSource: cloneJson(sampleSource) as Record<string, unknown>,
  }
}

const effectiveGoal = computed(() =>
  processingGoal.value.trim() || (
    activeSource.value.kind === 'extraction'
      ? '把这类内容整理成结构化数据，保留来源页码，后续同类材料可以自动提取。'
      : '基于这类数据做核对、判断和异常提示，输出可以复核的处理结论。'
  ),
)

const effectiveExpectedOutput = computed(() =>
  expectedOutput.value.trim() || (
    activeSource.value.kind === 'extraction'
      ? '结构化字段、表格或记录集合；每条结果带来源证据。'
      : '处理结论、异常项、判断依据和建议动作。'
  ),
)

const DEFAULT_PROCESSING_GOAL_TEXTS = new Set([
  '提取这类内容中的关键字段和值，例如编号、名称、日期、主体、金额等；字段缺失时保持为空，并保留来源证据。',
  '把这类表格整理成结构化表格，保留表头、行列关系、合并单元格含义和来源证据。',
  '把这类连续文本或列表整理成多条记录，每条记录拆出主体、时间、金额、状态、说明等可识别字段。',
  '提取这类说明、备注、结论或异常提示，保留完整语义和来源证据，避免只截取片段。',
  '把这类内容整理成结构化数据，保留来源页码，后续同类材料可以自动提取。',
  '基于这类数据做核对、判断和异常提示，输出可以复核的处理结论。',
])

const DEFAULT_EXPECTED_OUTPUT_TEXTS = new Set([
  '字段列表：字段名、字段值、来源页码。',
  '表格：表头、行数据、合并单元格说明、来源页码。',
  '记录集合：每条记录包含字段和值、来源页码；跨页连续时保持同一组记录。',
  '说明列表：主题、说明内容、影响或结论、来源页码。',
  '结构化字段、表格或记录集合；每条结果带来源证据。',
  '处理结论、异常项、判断依据和建议动作。',
])

function normalizeOptionalUserText(value: string, defaults: Set<string>) {
  const text = String(value || '').trim()
  if (!text) return ''
  return defaults.has(text) ? '' : text
}

function userProcessingGoalText() {
  return normalizeOptionalUserText(processingGoal.value, DEFAULT_PROCESSING_GOAL_TEXTS)
}

function userLocatorInstructionText() {
  return String(locatorInstruction.value || '').trim()
}

function userExpectedOutputText() {
  return normalizeOptionalUserText(expectedOutput.value, DEFAULT_EXPECTED_OUTPUT_TEXTS)
}

onMounted(async () => {
  await cleanupLegacyDemoTaskQuery()
  await loadCurrentTask()
})

onBeforeUnmount(() => {
  stopParsePolling()
  if (sampleExtractionSaveTimer) {
    window.clearTimeout(sampleExtractionSaveTimer)
    sampleExtractionSaveTimer = null
  }
  if (sampleProcessingSaveTimer) {
    window.clearTimeout(sampleProcessingSaveTimer)
    sampleProcessingSaveTimer = null
  }
})

watch(taskId, async () => {
  stopParsePolling()
  await loadCurrentTask()
})

watch(editingApplicationId, async () => {
  stopParsePolling()
  await loadCurrentTask()
})

watch(
  uploadCustomerOptions,
  (options) => {
    if (!options.length) {
      uploadCustomerId.value = ''
      return
    }
    const currentCustomerId = detail.value?.task.customerId
    const preferred = currentCustomerId && options.some((item) => item.id === currentCustomerId)
      ? currentCustomerId
      : options[0].id
    if (!options.some((item) => item.id === uploadCustomerId.value)) {
      uploadCustomerId.value = preferred
    }
  },
  { immediate: true },
)

watch(
  () => detail.value?.task.customerId,
  (customerId) => {
    if (customerId) {
      uploadCustomerId.value = customerId
    }
  },
)

watch(
  [
    () => parsePanelActiveTab.value,
    () => detail.value?.task.id || '',
    () => store.currentParseResultSummary?.id || '',
    () => store.currentParseResultSummary?.status || '',
  ],
  async ([activeTab, currentTaskId, resultId, resultStatus], previous) => {
    if (isStepRunSyncActive.value) return
    if (activeTab !== 'extract') return
    if (!currentTaskId || !resultId || resultStatus === 'failed') return
    const shouldForce = previous?.[2] === resultId && previous?.[3] === 'processing' && resultStatus === 'completed'
    await store.ensureCurrentParseResultDetail(shouldForce)
  },
  { immediate: true },
)

watch(
  [
    () => parsePanelActiveTab.value,
    () => detail.value?.task.id || '',
    () => taskParseResultSummaryKey.value,
  ],
  async ([activeTab]) => {
    if (isStepRunSyncActive.value) return
    if (activeTab !== 'extract') return
    await refreshTaskWideParseResult()
  },
  { immediate: true },
)

watch(
  [
    () => parsePanelActiveTab.value,
    () => detail.value?.task.id || '',
    () => detail.value?.documentTree,
  ],
  async ([activeTab, currentTaskId, documentTree]) => {
    if (activeTab !== 'tree' || !currentTaskId || documentTree) {
      return
    }
    try {
      await store.ensureActiveDocumentTree(currentTaskId)
    } catch (error) {
      if (detail.value?.task.id === currentTaskId) {
        Message.warning(error instanceof Error ? error.message : '文档树加载失败。')
      }
    }
  },
  { immediate: true },
)

watch(
  () => stepRunState.value?.status,
  async (status, previous) => {
    if (!previous || isStepRunSyncActive.value) return
    if (status === 'completed' || status === 'failed') {
      await refreshTaskWideParseResult()
    }
  },
)

watch(
  () => store.currentPageIndex,
  async () => {
    if (!detail.value) return
    if (isStepRunSyncActive.value || parsePanelActiveTab.value === 'extract' || sourceMode.value === 'target') {
      await store.ensureOperationTargets()
    }
    if (!isStepRunSyncActive.value && parsePanelActiveTab.value === 'extract') {
      await store.ensureCurrentParseResultDetail()
    }
    if (sourceMode.value === 'selection' && selectedRange.value?.pageIndex !== store.currentPageIndex) {
      sourceMode.value = 'page'
    }
  },
)

watch(
  () => store.selectedBlockId,
  (blockId) => {
    if (!blockId) return
    if (stepDrawerVisible.value && currentDraft.value) return
    const matchedRange = contentRanges.value.find((range) => range.blockIds.includes(blockId))
    if (matchedRange) {
      selectedRangeId.value = matchedRange.id
      sourceMode.value = 'selection'
      parsePanelActiveTab.value = 'recognition'
    }
  },
)

watch(
  () => store.selectedTargetId,
  (targetId) => {
    if (!targetId) return
    if (stepDrawerVisible.value && currentDraft.value) return
    sourceMode.value = 'target'
    parsePanelActiveTab.value = 'extract'
  },
)

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

watch(applicationDraftContext, (context) => {
  if (context && !applicationName.value.trim()) {
    applicationName.value = context.suggestedName
  }
})

async function loadCurrentTask() {
  taskLoading.value = true
  contextError.value = ''
  applicationDraftContext.value = null
  currentDraft.value = null
  processingSteps.value = []
  selectedTreeNode.value = null
  savedApplication.value = null
  editingApplication.value = null
  lastPlan.value = null
  templateAssetIssue.value = null
  try {
    const editableApplication = await loadEditableApplication()
    let liveTaskLoaded = false
    if (taskId.value) {
      try {
        await store.selectTask(taskId.value)
        liveTaskLoaded = true
      } catch (error) {
        if (!editableApplication) {
          throw error
        }
        console.warn('Failed to load source task, using application template sample snapshot instead.', error)
        Message.warning('来源样例任务不可用，已使用应用内保存的样板快照。')
      }
    }
    if (!liveTaskLoaded && editableApplication) {
      const sampleTaskDetail = buildTemplateSampleTaskDetail(editableApplication)
      const sampleHasRecognitionContext = hasTemplateSampleRecognitionContext(editableApplication)
      if (sampleTaskDetail && sampleHasRecognitionContext) {
        store.seedDatasetWithTaskDetail(sampleTaskDetail)
        await store.selectTask(sampleTaskDetail.task.id)
      } else if (editableApplication.sourceTask.taskId) {
        try {
          await store.selectTask(editableApplication.sourceTask.taskId)
          liveTaskLoaded = true
          templateAssetIssue.value = {
            title: '旧应用缺少样板快照，已从来源任务临时恢复',
            description: '这个应用是在样板资产固化前创建的。当前页面先使用来源任务恢复原始样例；保存草稿或发布后，样例 PDF、文档树和 Skill 快照会写入应用资产，后续不再依赖该任务。',
            sourceTaskId: editableApplication.sourceTask.taskId,
          }
          Message.warning('旧应用缺少样板快照，已从来源任务临时恢复；请保存一次固化到应用。')
        } catch (error) {
          console.warn('Application template sample is missing and source task cannot be loaded.', error)
          templateAssetIssue.value = {
            title: '应用缺少样板资产',
            description: '这个应用没有保存原始样例快照，来源任务也无法读取。应用编辑需要样例 PDF、文档树、定位结果和 Skill 快照作为模板资产；请重新上传样例并保存，或使用仍保留原任务的应用版本重新固化。',
            sourceTaskId: editableApplication.sourceTask.taskId,
          }
        }
      } else if (sampleTaskDetail) {
        store.seedDatasetWithTaskDetail(sampleTaskDetail)
        await store.selectTask(sampleTaskDetail.task.id)
        templateAssetIssue.value = {
          title: '样板快照缺少识别上下文',
          description: '当前应用只保留了样例文件预览地址，缺少完整 OCR 页面、文档树和定位上下文。请重新上传样例或使用仍保留来源任务的应用版本重新保存。',
        }
      } else {
        templateAssetIssue.value = {
          title: '应用缺少样板资产',
          description: '这个应用没有保存原始样例快照，也没有可恢复的来源任务。应用编辑需要样例 PDF、文档树、定位结果和 Skill 快照作为模板资产；请重新上传样例并保存。',
        }
      }
    }
    if (!liveTaskLoaded && !editableApplication) {
      templateAssetIssue.value = {
        title: '还没有样例材料',
        description: '新建文档应用需要先上传一份样例材料；OCR 完成后再制作定位 Skill 和抽取 Skill。只有从识别任务创建应用时，页面才会携带任务 ID。',
      }
      await ensureUploadCustomerOptions()
      return
    }
    const persistedStepCount = editableApplication ? 0 : await loadPersistedProcessingSteps()
    if (isParseRunning.value) {
      contextError.value = 'OCR 识别完成后会自动载入应用制作上下文。'
      return
    }
    if (liveTaskLoaded) {
      await Promise.all([
        store.ensureExtractionSkills(),
        store.ensureBusinessSkills(),
      ])
      await loadApplicationContext({ includeRunDetails: false })
    } else if (editableApplication) {
      applicationDraftContext.value = buildTemplateApplicationContext(editableApplication)
      await Promise.all([
        store.ensureExtractionSkills(),
        store.ensureBusinessSkills(),
      ])
    } else {
      await Promise.all([
        store.ensureExtractionSkills(),
        store.ensureBusinessSkills(),
      ])
      await loadApplicationContext({ includeRunDetails: false })
    }
    if (editableApplication) {
      hydrateProcessingStepsFromApplication(editableApplication)
    } else if (!persistedStepCount) {
      hydrateProcessingStepsFromContext()
    }
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '任务加载失败。')
  } finally {
    taskLoading.value = false
  }
}

async function cleanupLegacyDemoTaskQuery() {
  if (!hasLegacyDemoTaskQuery.value) return
  const nextQuery = { ...route.query }
  delete nextQuery.taskId
  await router.replace({
    name: 'admin-applications-new',
    query: nextQuery,
  })
}

async function loadEditableApplication() {
  if (!editingApplicationId.value) {
    return null
  }
  const application = await loadApplicationDetail(editingApplicationId.value, {
    version: 'draft',
    includeDraft: true,
  })
  editingApplication.value = application
  savedApplication.value = application
  applicationName.value = application.name
  return application
}

async function refreshTaskWideParseResult() {
  if (isStepRunSyncActive.value) return
  if (parsePanelActiveTab.value !== 'extract') return
  const loadSeq = ++taskWideParseResultLoadSeq
  taskWideParseResultDetail.value = null
  const taskDetail = detail.value
  if (!taskDetail) return
  const summaries = taskParseResultSummaries.value
  if (!summaries.length) return
  const resultDetails = await Promise.all(
    summaries.map(async (summary) => {
      try {
        return await store.fetchResultDetail(summary.id, taskDetail.task.id)
      } catch {
        return null
      }
    }),
  )
  if (loadSeq !== taskWideParseResultLoadSeq) return
  const usableDetails = resultDetails.filter((item): item is PageResultDetail =>
    Boolean(item && normalizeExtractionResult(item.extractionResult)),
  )
  taskWideParseResultDetail.value = buildMergedParseResultDetail(usableDetails)
}

function stopParsePolling() {
  if (parsePollingTimer !== null) {
    window.clearTimeout(parsePollingTimer)
    parsePollingTimer = null
  }
}

function startParsePolling() {
  stopParsePolling()

  const poll = async () => {
    const currentTaskId = taskId.value
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
        await Promise.all([
          store.ensureExtractionSkills(),
          store.ensureBusinessSkills(),
        ])
        await loadApplicationContext({ includeRunDetails: false })
        Message.success('OCR 识别已完成，可以开始制作文档应用。')
        return
      }

      if (status.state === 'failed') {
        contextError.value = status.errorMessage || 'OCR 识别失败。'
        Message.error(contextError.value)
      }
    } catch {
      parsePollingTimer = window.setTimeout(poll, PARSE_POLL_RETRY_INTERVAL_MS)
    }
  }

  parsePollingTimer = window.setTimeout(poll, INITIAL_POLL_DELAY_MS)
}

async function ensureUploadCustomerOptions() {
  if (effectiveUploadCustomerId.value || uploadCustomerLoading.value) {
    return
  }
  uploadCustomerLoading.value = true
  try {
    const response = await loadCustomers(1, 100)
    uploadCustomerFallbackOptions.value = response.items.map((customer) => ({
      id: customer.id,
      name: customer.name,
    }))
    if (!uploadCustomerId.value && response.items[0]?.id) {
      uploadCustomerId.value = response.items[0].id
    }
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '读取客户空间失败。')
  } finally {
    uploadCustomerLoading.value = false
  }
}

async function openUploadPicker() {
  if (!effectiveUploadCustomerId.value) {
    await ensureUploadCustomerOptions()
  }
  if (!effectiveUploadCustomerId.value) {
    Message.warning('没有可用客户空间，请先创建客户空间后再上传样例。')
    return
  }
  uploadInputRef.value?.click()
}

async function refreshParseStatus() {
  if (!taskId.value) return
  contextLoading.value = true
  try {
    await store.refreshTaskDetail(taskId.value)
    if (!isParseRunning.value && !isParseFailed.value) {
      await loadApplicationContext()
    }
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '刷新 OCR 状态失败。')
  } finally {
    contextLoading.value = false
  }
}

async function rerunCurrentParse() {
  const currentTaskId = runtimeTaskId.value
  if (!currentTaskId || restartingParse.value || isParseRunning.value) {
    return
  }

  restartingParse.value = true
  contextError.value = ''
  try {
    const status = await startTaskParse(currentTaskId)
    await store.refreshTaskDetail(currentTaskId)
    if (status.state === 'completed') {
      await loadApplicationContext()
      Message.success('已使用当前文件重新完成 OCR 识别。')
      return
    }
    if (status.state === 'failed') {
      contextError.value = status.errorMessage || 'OCR 识别失败。'
      Message.error(contextError.value)
      return
    }
    Message.success('已开始重新识别当前文件。')
    startParsePolling()
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '重新识别当前文件失败。')
  } finally {
    restartingParse.value = false
  }
}

async function handleUploadChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  const customerId = effectiveUploadCustomerId.value
  if (!customerId) {
    Message.warning('请先选择客户空间。')
    input.value = ''
    return
  }

  uploadingSample.value = true
  try {
    const taskName = `${file.name.replace(/\.[^.]+$/, '') || '应用样例'} OCR 识别`
    const result = await store.uploadAndParseDocument(customerId, file, taskName)
    const nextTaskId = result.response.createdTask.id
    await router.replace({
      name: isEditingApplication.value ? 'admin-applications-edit' : 'admin-applications-new',
      params: isEditingApplication.value ? { applicationId: editingApplicationId.value } : {},
      query: {
        ...route.query,
        taskId: nextTaskId,
      },
    })
    if (result.parseStatus?.state === 'completed') {
      await loadCurrentTask()
      Message.success('文件已上传并完成 OCR 识别。')
    } else if (result.parseStatus?.state === 'failed') {
      await loadCurrentTask()
      Message.warning(result.parseStatus.errorMessage || '文件已上传，但 OCR 识别未完成。')
    } else {
      Message.success('文件已上传，OCR 识别已启动。')
      startParsePolling()
    }
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '上传并提交 OCR 识别失败。')
  } finally {
    uploadingSample.value = false
    input.value = ''
  }
}

async function loadApplicationContext(options: { includeRunDetails?: boolean } = {}) {
  contextLoading.value = true
  contextError.value = ''
  try {
    applicationDraftContext.value = await store.collectApplicationDraftContext({
      includeRunDetails: options.includeRunDetails ?? false,
      includeOperationTargets: options.includeRunDetails ?? false,
    })
  } catch (error) {
    contextError.value = error instanceof Error ? error.message : '当前任务上下文不可用。'
  } finally {
    contextLoading.value = false
  }
}

async function loadPersistedProcessingSteps() {
  try {
    const records = await loadApplicationWorkshopStepDrafts(taskId.value, { light: true })
    if (!records.length) {
      return await importLegacyLocalProcessingSteps()
    }
    const { records: dedupedRecords, removedIds } = dedupeServerStepDrafts(records)
    processingSteps.value = dedupedRecords.map(processingStepFromServerDraft)
    removedIds.forEach((id) => {
      void deleteProcessingStepDraft(id, { silent: true })
    })
    return processingSteps.value.length
  } catch (error) {
    console.error('Failed to load application workshop step drafts', error)
    Message.warning('数据类型草稿读取失败，当前页面会先使用已跑通结果。')
    return 0
  }
}

async function ensureFullProcessingStepDraft(stepOrId: ProcessingStepDraft | string): Promise<ProcessingStepDraft | null> {
  const step = typeof stepOrId === 'string'
    ? processingSteps.value.find((item) => item.id === stepOrId)
    : stepOrId
  if (!step) {
    return null
  }
  if (!step.isLight || !taskId.value.trim()) {
    return step
  }
  const record = await loadApplicationWorkshopStepDraft(taskId.value, step.id)
  const fullStep = processingStepFromServerDraft(record)
  replaceProcessingStepInMemory(fullStep)
  if (currentDraft.value?.id === step.id) {
    currentDraft.value = fullStep
  }
  return fullStep
}

async function ensureFullProcessingStepsForPublish(): Promise<boolean> {
  for (const step of [...processingSteps.value]) {
    if (step.isLight) {
      const fullStep = await ensureFullProcessingStepDraft(step)
      if (!fullStep) {
        Message.error(`草稿 ${step.dataTypeName || step.id} 读取失败。`)
        return false
      }
    }
  }
  return true
}

async function importLegacyLocalProcessingSteps() {
  if (typeof window === 'undefined') return 0
  const storageKey = `${LEGACY_PROCESSING_STEPS_STORAGE_PREFIX}${taskId.value}`
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return 0
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return 0
    const steps = parsed
      .map(normalizeLegacyProcessingStep)
      .filter((item): item is ProcessingStepDraft => Boolean(item))
    if (!steps.length) return 0
    processingSteps.value = steps
    const results = await Promise.all(steps.map((step) => saveProcessingStepDraft(step, { silent: true })))
    const savedCount = results.filter(Boolean).length
    if (savedCount) {
      window.localStorage.removeItem(storageKey)
      Message.success(`已将 ${savedCount} 个旧数据类型草稿迁移到数据库。`)
    }
    return savedCount
  } catch (error) {
    console.error('Failed to migrate legacy local processing steps', error)
    return 0
  }
}

async function saveProcessingStepDraft(step: ProcessingStepDraft, options: { silent?: boolean } = {}) {
  const draftTaskId = taskId.value.trim()
  let writableStep = step
  if (step.isLight) {
    const fullStep = await ensureFullProcessingStepDraft(step)
    if (!fullStep) {
      if (!options.silent) {
        Message.error('草稿完整内容读取失败，暂不能保存。')
      }
      return false
    }
    writableStep = fullStep
  }
  if (!draftTaskId) {
    upsertProcessingStep(writableStep)
    if (currentDraft.value?.id === writableStep.id) {
      currentDraft.value = writableStep
    }
    return true
  }
  try {
    const saved = await saveApplicationWorkshopStepDraft(draftTaskId, processingStepToServerDraft(writableStep))
    const normalized = processingStepFromServerDraft(saved)
    replaceProcessingStepInMemory(normalized)
    if (currentDraft.value?.id === normalized.id) {
      currentDraft.value = normalized
    }
    return true
  } catch (error) {
    console.error('Failed to save application workshop step draft', error)
    if (!options.silent) {
      Message.error(error instanceof Error ? error.message : '数据类型草稿保存失败。')
    }
    return false
  }
}

async function hydrateProcessingStepSkillText(
  step: ProcessingStepDraft,
  options: { silent?: boolean; persist?: boolean } = {},
) {
  if (step.skillText.trim() || !step.runOption?.skillId) {
    return step
  }
  const skillText = await loadSkillTextForRunOption(step.runOption, options)
  if (!skillText.trim()) {
    if (options.persist) {
      await saveProcessingStepDraft(step, { silent: options.silent })
    }
    return step
  }
  const updated: ProcessingStepDraft = {
    ...step,
    skillText,
  }
  processingSteps.value = processingSteps.value.map((item) => (item.id === updated.id ? updated : item))
  if (currentDraft.value?.id === updated.id) {
    currentDraft.value = updated
  }
  if (options.persist) {
    await saveProcessingStepDraft(updated, { silent: options.silent })
  }
  return updated
}

async function loadSkillTextForRunOption(
  option: ApplicationSourceRunOption,
  options: { silent?: boolean } = {},
) {
  const customerId = detail.value?.task.customerId ?? null
  const attempts = customerId
    ? [
        { scope: 'customer' as const, customerId },
        { scope: 'platform' as const, customerId: null },
      ]
    : [
        { scope: 'platform' as const, customerId: null },
      ]
  for (const attempt of attempts) {
    try {
      const skill = await loadSkillDetail(option.kind, option.skillId, attempt.scope, attempt.customerId, true)
      if (skill.skillText?.trim()) {
        return skill.skillText
      }
    } catch (error) {
      if (!options.silent) {
        console.error('Failed to load skill text for application step', error)
      }
    }
  }
  return ''
}

async function deleteProcessingStepDraft(id: string, options: { silent?: boolean } = {}) {
  const draftTaskId = taskId.value.trim()
  if (!draftTaskId) {
    processingSteps.value = processingSteps.value.filter((item) => item.id !== id)
    if (currentDraft.value?.id === id) {
      currentDraft.value = null
    }
    return true
  }
  try {
    await deleteApplicationWorkshopStepDraft(draftTaskId, id)
    return true
  } catch (error) {
    console.error('Failed to delete application workshop step draft', error)
    if (!options.silent) {
      Message.warning(error instanceof Error ? error.message : '数据类型草稿删除失败。')
    }
    return false
  }
}

function handleSelectRange(rangeId: string, pageIndex?: number) {
  const range = contentRanges.value.find((item) => item.id === rangeId)
  if (!range) return
  selectedRangeId.value = rangeId
  selectedTreeNode.value = null
  sourceMode.value = 'selection'
  parsePanelActiveTab.value = 'recognition'
  if (typeof pageIndex === 'number') {
    store.setCurrentPage(pageIndex)
  }
  const blockId = range.blockIds[0]
  if (blockId) {
    store.selectBlock(blockId, range.pageIndex)
  }
}

function handleSelectBlock(blockId: string, pageIndex?: number) {
  selectedTreeNode.value = null
  store.selectBlock(blockId, pageIndex)
  const matchedRange = contentRanges.value.find((range) => range.blockIds.includes(blockId))
  if (matchedRange) {
    selectedRangeId.value = matchedRange.id
    sourceMode.value = 'selection'
    parsePanelActiveTab.value = 'recognition'
  }
}

function handleSelectTarget(target: OperationTarget) {
  store.selectTarget(target.id)
  selectedRangeId.value = ''
  selectedTreeNode.value = null
  sourceMode.value = 'target'
  parsePanelActiveTab.value = 'extract'
}

function handleSelectTreeNode(node: DocumentTreeSource) {
  selectedTreeNode.value = node
  sourceMode.value = 'tree'
  parsePanelActiveTab.value = 'tree'
  const treeRanges = buildTreeNodePreviewRanges(node)
  const matchedRange = treeRanges[0] ?? findBestRangeForTreeNode(node)
  selectedRangeId.value = matchedRange?.id ?? ''
  const firstPage = node.pageNos[0]
  if (firstPage) {
    store.setCurrentPage(pageIndexFromPageNo(firstPage))
  }
}

function buildTreeNodePreviewRanges(node: DocumentTreeSource): ContentRange[] {
  return buildDocumentTreePreviewRanges(node, detail.value?.pages ?? [])
}

function findBestRangeForTreeNode(node: DocumentTreeSource) {
  return findBestDocumentTreeRange(node, contentRanges.value)
}

function openNewStepDrawer(preferredMode?: SampleSourceMode) {
  editingStepId.value = ''
  dataTypeName.value = ''
  locatorInstruction.value = ''
  processingGoal.value = ''
  expectedOutput.value = ''
  currentDraft.value = null
  if (preferredMode) {
    sourceMode.value = preferredMode
  } else {
    sourceMode.value = 'document'
  }
  stepDrawerVisible.value = true
}

function openCurrentPageStepDrawer() {
  selectedRangeId.value = ''
  selectedTreeNode.value = null
  store.selectTarget('')
  parsePanelActiveTab.value = 'recognition'
  openNewStepDrawer('page')
}

async function openEditStepDrawer(stepId: string) {
  const step = await ensureFullProcessingStepDraft(stepId)
  if (!step) return
  editingStepId.value = step.id
  dataTypeName.value = step.dataTypeName
  locatorInstruction.value = locatorInstructionFromStep(step)
  processingGoal.value = step.goal
  expectedOutput.value = step.expectedOutput
  currentDraft.value = step
  if (step.semanticLocator || step.sampleSource?.locator) {
    sourceMode.value = 'document'
  } else if (step.sampleSource?.mode) {
    sourceMode.value = step.sampleSource.mode
    if (step.sampleSource.mode === 'target') {
      const targetId = step.sampleSource.targetIds[0]
      if (step.sampleSource.pageIndex !== null && step.sampleSource.pageIndex !== undefined) {
        store.setCurrentPage(step.sampleSource.pageIndex)
        void store.ensureOperationTargets()
      }
      if (targetId) {
        store.selectTarget(targetId)
      }
    }
  }
  stepDrawerVisible.value = true
  void hydrateProcessingStepSkillText(step, { silent: true, persist: true })
}

async function duplicateProcessingStep(stepId: string) {
  const step = await ensureFullProcessingStepDraft(stepId)
  if (!step) return
  const duplicated: ProcessingStepDraft = {
    ...step,
    id: `draft:${Date.now()}`,
    status: 'generated',
    dataTypeName: `${step.dataTypeName} 副本`,
    skillName: `${step.skillName} 副本`,
    runOption: undefined,
  }
  editingStepId.value = ''
  dataTypeName.value = duplicated.dataTypeName
  locatorInstruction.value = locatorInstructionFromStep(duplicated)
  processingGoal.value = duplicated.goal
  expectedOutput.value = duplicated.expectedOutput
  currentDraft.value = duplicated
  if (duplicated.semanticLocator || duplicated.sampleSource?.locator) {
    sourceMode.value = 'document'
  } else if (duplicated.sampleSource?.mode) {
    sourceMode.value = duplicated.sampleSource.mode
  }
  stepDrawerVisible.value = true
}

async function generateProcessingStep() {
  if (activeSource.value.kind === 'extraction') {
    sourceMode.value = 'document'
    await locateAndExtractProcessingStep()
    return
  }
  await sampleProcessProcessingStep()
}

async function locateAndExtractProcessingStep(selectedCandidateId?: string) {
  const query = dataTypeName.value.trim()
  if (!query) {
    Message.warning(t('workshop.enterDataBlockFirst'))
    return
  }
  const sampleContext = buildSkillSampleContext(activeSource.value)
  if (!sampleContext) {
    Message.warning(t('workshop.loadSampleAssetFirst'))
    return
  }
  sampleExtracting.value = true
  try {
    const response = await sampleLocateAndExtract({
      taskId: sampleRequestTaskId(),
      applicationId: sampleContext.applicationId,
      sampleContext,
      query,
      customerId: detail.value?.task.customerId ?? null,
      outputPreference: 'auto',
      locatorInstruction: userLocatorInstructionText(),
      extraInstruction: '',
      expectedOutput: '',
      selectedCandidateId,
      runExtraction: false,
    })
    await handleLocateAndExtractResponse(response, sampleContext)
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '定位并试抽取失败。')
  } finally {
    sampleExtracting.value = false
  }
}

async function handleLocateAndExtractResponse(response: SkillSampleLocateAndExtractResponse, sampleContext: SkillSampleContext | null = null) {
  const query = response.dataTypeName || response.query || effectiveDataTypeName.value
  const trace = sampleTraceFromResponse(response)
  const locatorMeta = {
    status: response.status,
    query: response.query,
    locatorInstruction: userLocatorInstructionText(),
    dataTypeName: query,
    outputPreference: response.outputPreference,
    locatedSource: response.locatedSource,
    candidates: response.candidates,
    locatorResult: response.locatorResult,
    locatorProfile: response.locatorProfile || {},
    locatorSkillText: response.locatorSkillText || '',
    trace,
    generatedAt: new Date().toISOString(),
  }
  if ((response.status !== 'located' && response.status !== 'extracted') || !response.locatedSource) {
    const pendingSource: SampleSource = {
      mode: 'document',
      kind: 'extraction',
      title: '文档树定位',
      summary: response.status === 'not_found' ? '暂未找到可靠的数据块位置' : '请选择一个候选模块后继续抽取',
      sourceScope: '文档树定位模块',
      sourceText: '',
      pageNo: null,
      pageIndex: null,
      targetIds: [],
      locator: locatorMeta,
    }
    const draft: ProcessingStepDraft = {
      id: editingStepId.value || currentDraft.value?.id || `draft:${Date.now()}`,
      kind: 'extraction',
      status: 'generated',
      dataTypeName: query,
      locatorInstruction: userLocatorInstructionText(),
      goal: userProcessingGoalText(),
      expectedOutput: userExpectedOutputText(),
      sourceTitle: pendingSource.title,
      sourceScope: pendingSource.sourceScope,
      skillText: '',
      skillName: defaultStepName('extraction', query),
      errors: response.errors || [],
      model: response.model,
      sampleSource: pendingSource,
      semanticLocator: locatorMeta,
      skillDevelopment: buildSkillDevelopmentAsset({
        response,
        sampleContext,
        previous: currentDraft.value?.skillDevelopment,
      }),
      runOption: undefined,
    }
    currentDraft.value = draft
    upsertProcessingStep(draft)
    await saveProcessingStepDraft(draft, { silent: true })
    if (response.status === 'not_found') {
      Message.warning('未定位到可靠的数据块，请换个说法或手动选择文档树节点。')
    } else {
      Message.info('定位结果需要确认，请选择一个候选模块继续抽取。')
    }
    return
  }

  const locatedSource = normalizeLocatedSampleSource(response.locatedSource, locatorMeta)
  const draft: ProcessingStepDraft = {
    id: editingStepId.value || currentDraft.value?.id || `draft:${Date.now()}`,
    kind: 'extraction',
    status: 'generated',
    dataTypeName: query,
    locatorInstruction: userLocatorInstructionText(),
    goal: userProcessingGoalText(),
    expectedOutput: userExpectedOutputText(),
    sourceTitle: locatedSource.title,
    sourceScope: locatedSource.sourceScope,
    skillText: '',
    skillName: defaultStepName('extraction', query),
    errors: response.errors || [],
    model: response.model,
    sampleSource: locatedSource,
    semanticLocator: locatorMeta,
      sampleExtraction: response.extractionResult ? {
      status: 'draft',
      result: response.extractionResult,
      editableOutput: response.editableOutput || JSON.stringify(response.rawOutput ?? {}, null, 2),
      rawOutput: response.rawOutput,
      model: response.model,
      durationMs: response.durationMs,
      inputChars: response.inputChars,
      outputChars: response.outputChars,
      promptTokens: response.promptTokens ?? null,
      completionTokens: response.completionTokens ?? null,
      totalTokens: response.totalTokens ?? null,
      errors: response.errors || [],
      trace,
      generatedAt: new Date().toISOString(),
    } : undefined,
    skillDevelopment: buildSkillDevelopmentAsset({
      response,
      sampleContext,
      previous: currentDraft.value?.skillDevelopment,
    }),
    runOption: undefined,
  }
  currentDraft.value = draft
  upsertProcessingStep(draft)
  const persisted = await saveProcessingStepDraft(draft)
  if (!persisted) {
    Message.warning(response.extractionResult ? '已定位并抽取样例，但暂未保存到数据库。' : '已定位，但暂未保存到数据库。')
    return
  }
  Message.success(response.extractionResult ? '已定位到文档树模块并完成样例抽取。' : '定位完成。请到抽取 Skill 写提示词后试抽取。')
}

async function sampleExtractLocatedProcessingStep() {
  const source = currentDraft.value?.sampleSource
  if (!source || source.kind !== 'extraction') {
    Message.warning(t('workshop.completeLocationFirst'))
    return
  }
  if (!source.sourceText.trim()) {
    Message.warning(t('workshop.locatedResultNoExtractableContent'))
    return
  }
  const sampleContext = buildSkillSampleContext(source)
  if (!sampleContext) {
    Message.warning(t('workshop.loadSampleAssetFirst'))
    return
  }
  sampleExtracting.value = true
  try {
    const response = await sampleExtractFromSample({
      taskId: sampleRequestTaskId(),
      applicationId: sampleContext.applicationId,
      sampleContext,
      kind: 'extraction',
      instruction: buildSkillInstruction(source),
      expectedOutput: userExpectedOutputText(),
      targetIds: source.targetIds,
      pageNo: source.pageNo,
      customerId: detail.value?.task.customerId ?? null,
      dataTypeName: effectiveDataTypeName.value,
      sourceScope: source.sourceScope,
      sourceLabel: source.title,
      sourceText: source.sourceText,
      ...sampleRequestSourceFields(source),
    })
    const trace = sampleTraceFromResponse(response)
    const draft: ProcessingStepDraft = {
      ...(currentDraft.value || {
        id: editingStepId.value || `draft:${Date.now()}`,
        kind: 'extraction',
        status: 'generated',
        dataTypeName: effectiveDataTypeName.value,
        sourceTitle: source.title,
        sourceScope: source.sourceScope,
        skillText: '',
        skillName: defaultStepName('extraction', effectiveDataTypeName.value),
        errors: [],
        model: '',
      }),
      kind: 'extraction',
      status: 'generated',
      dataTypeName: effectiveDataTypeName.value,
      locatorInstruction: locatorInstructionFromStep(currentDraft.value),
      goal: userProcessingGoalText(),
      expectedOutput: userExpectedOutputText(),
      sourceTitle: source.title,
      sourceScope: source.sourceScope,
      skillText: currentDraft.value?.skillText || '',
      skillName: currentDraft.value?.skillName || defaultStepName('extraction', effectiveDataTypeName.value),
      errors: response.errors || [],
      model: response.model,
      sampleSource: source,
      semanticLocator: currentDraft.value?.semanticLocator || source.locator,
      sampleExtraction: {
        status: 'draft',
        result: response.extractionResult,
        editableOutput: response.editableOutput || JSON.stringify(response.rawOutput ?? {}, null, 2),
        rawOutput: response.rawOutput,
        model: response.model,
        durationMs: response.durationMs,
        inputChars: response.inputChars,
        outputChars: response.outputChars,
        promptTokens: response.promptTokens ?? null,
        completionTokens: response.completionTokens ?? null,
        totalTokens: response.totalTokens ?? null,
        errors: response.errors || [],
        trace,
        generatedAt: new Date().toISOString(),
      },
      skillDevelopment: buildSkillDevelopmentAsset({
        response,
        sampleContext,
        previous: currentDraft.value?.skillDevelopment,
      }),
      runOption: undefined,
    }
    currentDraft.value = draft
    upsertProcessingStep(draft)
    const persisted = await saveProcessingStepDraft(draft)
    if (!persisted) {
      Message.warning('样例抽取完成，但暂未保存到数据库。')
      return
    }
    Message.success('样例抽取完成，请核对结果。')
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '样例抽取失败。')
  } finally {
    sampleExtracting.value = false
  }
}

function normalizeLocatedSampleSource(value: SkillSampleLocateAndExtractResponse['locatedSource'], locatorMeta: Record<string, unknown>): SampleSource {
  const source = (value || {}) as Partial<NonNullable<SkillSampleLocateAndExtractResponse['locatedSource']>>
  return {
    mode: 'tree',
    kind: 'extraction',
    title: String(source.title || '文档树定位模块'),
    summary: String(source.summary || ''),
    sourceScope: String(source.sourceScope || '文档树定位模块'),
    sourceText: String(source.sourceText || ''),
    pageNo: typeof source.pageNo === 'number' ? source.pageNo : null,
    pageIndex: typeof source.pageIndex === 'number' ? source.pageIndex : null,
    targetIds: Array.isArray(source.targetIds) ? source.targetIds.map(String) : [],
    treeNodeId: typeof source.treeNodeId === 'string' ? source.treeNodeId : undefined,
    treePath: Array.isArray(source.treePath) ? source.treePath.map(String) : [],
    pageRange: source.pageRange && typeof source.pageRange === 'object' ? source.pageRange as SampleSource['pageRange'] : undefined,
    contentRefs: Array.isArray(source.contentRefs) ? source.contentRefs as Array<Record<string, unknown>> : [],
    locator: locatorMeta,
  }
}

function locatorInstructionFromStep(step: ProcessingStepDraft | null | undefined) {
  const locator = step?.semanticLocator || step?.sampleSource?.locator
  const value = locator && typeof locator === 'object'
    ? (locator as Record<string, unknown>).locatorInstruction
    : ''
  return String(step?.locatorInstruction || value || '').trim()
}

type SkillDevelopmentMetaResponse = {
  sampleSummary?: Record<string, unknown>
  evidenceDiagnostics?: Record<string, unknown>
  validationReport?: Record<string, unknown>
  outputContractSummary?: Record<string, unknown>
}

function buildSkillDevelopmentAsset(options: {
  response?: SkillDevelopmentMetaResponse
  sampleContext?: SkillSampleContext | null
  confirmedOutput?: unknown
  previous?: SkillDevelopmentAsset
  prototypeId?: string
  candidateSkillId?: string
}): SkillDevelopmentAsset {
  const now = new Date().toISOString()
  const response = options.response
  return {
    ...(options.previous || {}),
    sampleContext: options.sampleContext !== undefined
      ? cloneJson(options.sampleContext) as unknown
      : options.previous?.sampleContext,
    confirmedOutput: options.confirmedOutput !== undefined
      ? cloneJson(options.confirmedOutput) as unknown
      : options.previous?.confirmedOutput,
    runtimeContract: plainRecord(response?.outputContractSummary || options.previous?.runtimeContract),
    evidenceSummary: plainRecord(response?.evidenceDiagnostics || options.previous?.evidenceSummary),
    validationReport: plainRecord(response?.validationReport || options.previous?.validationReport),
    outputContractSummary: plainRecord(response?.outputContractSummary || options.previous?.outputContractSummary),
    prototypeId: options.prototypeId || options.previous?.prototypeId,
    candidateSkillId: options.candidateSkillId || options.previous?.candidateSkillId,
    generatedAt: options.previous?.generatedAt || now,
    updatedAt: now,
  }
}

async function sampleProcessProcessingStep() {
  const source = activeSource.value
  if (source.kind !== 'operation' || !source.targetIds.length) {
    Message.warning(t('workshop.selectExtractionResultFirst'))
    return
  }
  if (!source.sourceText.trim()) {
    Message.warning(t('workshop.currentExtractionNoStructuredContent'))
    return
  }
  const sampleContext = buildSkillSampleContext(source)
  if (!sampleContext) {
    Message.warning(t('workshop.loadSampleAssetFirst'))
    return
  }
  sampleProcessing.value = true
  try {
    const response = await sampleProcessFromSample({
      taskId: sampleRequestTaskId(),
      applicationId: sampleContext.applicationId,
      sampleContext,
      kind: 'operation',
      instruction: buildSkillInstruction(source),
      expectedOutput: userExpectedOutputText(),
      targetIds: source.targetIds,
      pageNo: source.pageNo,
      customerId: detail.value?.task.customerId ?? null,
      dataTypeName: effectiveDataTypeName.value,
      sourceScope: source.sourceScope,
      sourceLabel: source.title,
      sourceText: source.sourceText,
      ...sampleRequestSourceFields(source),
    })
    const draft: ProcessingStepDraft = {
      id: editingStepId.value || `draft:${Date.now()}`,
      kind: 'operation',
      status: 'generated',
      dataTypeName: effectiveDataTypeName.value,
      goal: userProcessingGoalText(),
      expectedOutput: userExpectedOutputText(),
      sourceTitle: source.title,
      sourceScope: source.sourceScope,
      skillText: '',
      skillName: defaultStepName('operation', effectiveDataTypeName.value),
      errors: response.errors || [],
      model: response.model,
      sampleSource: {
        ...source,
        targetIds: [...source.targetIds],
      },
      sampleProcessing: {
        status: 'draft',
        result: {
          summary: response.summary,
          resultKind: response.resultKind,
          outputPayload: response.outputPayload,
          validationErrors: response.validationErrors || [],
        },
        editableOutput: response.editableOutput || JSON.stringify(response.rawOutput ?? {}, null, 2),
        rawOutput: response.rawOutput,
        model: response.model,
        durationMs: response.durationMs,
        inputChars: response.inputChars,
        outputChars: response.outputChars,
        promptTokens: response.promptTokens ?? null,
        completionTokens: response.completionTokens ?? null,
        totalTokens: response.totalTokens ?? null,
        errors: response.errors || [],
        generatedAt: new Date().toISOString(),
      },
      skillDevelopment: buildSkillDevelopmentAsset({
        response,
        sampleContext,
        previous: currentDraft.value?.skillDevelopment,
      }),
      runOption: undefined,
    }
    currentDraft.value = draft
    upsertProcessingStep(draft)
    const persisted = await saveProcessingStepDraft(draft)
    if (!persisted) {
      Message.warning('样例处理已完成，但暂未保存到数据库。')
      return
    }
    Message.success('样例处理已完成，请确认 JSON 后生成处理 Skill。')
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '样例数据试处理失败。')
  } finally {
    sampleProcessing.value = false
  }
}

async function generateSkillProcessingStep(confirmedSampleOutput?: unknown) {
  const source = currentDraft.value?.sampleSource || activeSource.value
  if (!source.sourceText.trim()) {
    Message.warning(t('workshop.currentSampleNoLearningContent'))
    return
  }
  const sampleContext = buildSkillSampleContext(source)
  if (!sampleContext) {
    Message.warning(t('workshop.loadSampleAssetFirst'))
    return
  }
  generating.value = true
  try {
    const response = await draftSkillFromSample({
      taskId: sampleRequestTaskId(),
      applicationId: sampleContext.applicationId,
      sampleContext,
      kind: source.kind,
      instruction: buildSkillInstruction(source),
      expectedOutput: userExpectedOutputText(),
      targetIds: source.targetIds,
      pageNo: source.pageNo,
      customerId: detail.value?.task.customerId ?? null,
      dataTypeName: effectiveDataTypeName.value,
      sourceScope: source.sourceScope,
      sourceLabel: source.title,
      sourceText: source.sourceText,
      ...sampleRequestSourceFields(source),
      confirmedSampleOutput,
    })
    const existingDraft = currentDraft.value
    const sampleExtraction = existingDraft?.sampleExtraction
      ? {
          ...existingDraft.sampleExtraction,
          status: confirmedSampleOutput !== undefined && source.kind === 'extraction' ? 'confirmed' as const : existingDraft.sampleExtraction.status,
          confirmedAt: confirmedSampleOutput !== undefined && source.kind === 'extraction' ? new Date().toISOString() : existingDraft.sampleExtraction.confirmedAt,
        }
      : undefined
    const sampleProcessingDraft = existingDraft?.sampleProcessing
      ? {
          ...existingDraft.sampleProcessing,
          status: confirmedSampleOutput !== undefined && source.kind === 'operation' ? 'confirmed' as const : existingDraft.sampleProcessing.status,
          confirmedAt: confirmedSampleOutput !== undefined && source.kind === 'operation' ? new Date().toISOString() : existingDraft.sampleProcessing.confirmedAt,
        }
      : undefined
    const draftId = editingStepId.value || existingDraft?.id || `draft:${Date.now()}`
    const skillDevelopment = buildSkillDevelopmentAsset({
      response,
      sampleContext,
      confirmedOutput: confirmedSampleOutput,
      previous: existingDraft?.skillDevelopment,
    })
    const normalizedSkillText = ensureSkillMarkdownFrontmatter({
      kind: source.kind,
      skillText: response.assist.skillText,
      draftId,
      dataTypeName: effectiveDataTypeName.value,
      skillName: extractSkillName(response.assist.skillText) || defaultStepName(source.kind, effectiveDataTypeName.value),
      skillDevelopment,
      sampleExtraction,
      sampleProcessing: sampleProcessingDraft,
    })
    const draft: ProcessingStepDraft = {
      id: draftId,
      kind: source.kind,
      status: 'generated',
      dataTypeName: effectiveDataTypeName.value,
      locatorInstruction: locatorInstructionFromStep(existingDraft) || userLocatorInstructionText(),
      goal: userProcessingGoalText(),
      expectedOutput: userExpectedOutputText(),
      sourceTitle: source.title,
      sourceScope: source.sourceScope,
      skillText: normalizedSkillText,
      skillName: extractSkillName(normalizedSkillText) || defaultStepName(source.kind, effectiveDataTypeName.value),
      errors: response.assist.errors || [],
      model: response.assist.model,
      sampleSource: {
        ...source,
        targetIds: [...source.targetIds],
      },
      sampleExtraction,
      sampleProcessing: sampleProcessingDraft,
      skillDevelopment,
      semanticLocator: existingDraft?.semanticLocator || source.locator,
    }
    currentDraft.value = draft
    upsertProcessingStep(draft)
    const persisted = await saveProcessingStepDraft(draft)
    if (!persisted) {
      Message.warning(source.kind === 'operation' ? '处理步骤已生成，但暂未保存到数据库。' : '抽取步骤已生成，但暂未保存到数据库。')
      return
    }
    Message.success(
      response.assist.valid
        ? 'Skill 草稿已生成并保存。下一步点击“保存并试跑”，通过后会加入文档应用。'
        : 'Skill 草稿已生成并保存，但需要先调整 SKILL.md，再点击“保存并试跑”。',
    )
  } catch (error) {
    Message.error(error instanceof Error ? error.message : source.kind === 'operation' ? '生成处理步骤失败。' : '生成抽取步骤失败。')
  } finally {
    generating.value = false
  }
}

async function confirmSampleExtractionAndGenerateSkill() {
  const draft = currentDraft.value
  if (!draft) {
    Message.warning('请先完成 AI 试跑。')
    return
  }
  const sampleDraft = draft.kind === 'operation' ? draft.sampleProcessing : draft.sampleExtraction
  if (!sampleDraft) {
    Message.warning(draft.kind === 'operation' ? '请先完成 AI 试处理。' : '请先完成 AI 试抽取。')
    return
  }
  let confirmedOutput: unknown
  try {
    confirmedOutput = JSON.parse(sampleDraft.editableOutput)
  } catch {
    Message.error('样例输出 JSON 格式不正确，请修正后再生成 Skill。')
    return
  }
  await generateSkillProcessingStep(confirmedOutput)
}

function updateSampleExtractionOutput(value: string) {
  const draft = currentDraft.value
  if (!draft?.sampleExtraction) return
  const updated: ProcessingStepDraft = {
    ...draft,
    sampleExtraction: {
      ...draft.sampleExtraction,
      status: 'draft',
      editableOutput: value,
    },
  }
  currentDraft.value = updated
  upsertProcessingStep(updated)
  if (sampleExtractionSaveTimer) {
    window.clearTimeout(sampleExtractionSaveTimer)
  }
  sampleExtractionSaveTimer = window.setTimeout(() => {
    sampleExtractionSaveTimer = null
    void saveProcessingStepDraft(updated, { silent: true })
  }, 600)
}

function updateSampleProcessingOutput(value: string) {
  const draft = currentDraft.value
  if (!draft?.sampleProcessing) return
  const updated: ProcessingStepDraft = {
    ...draft,
    sampleProcessing: {
      ...draft.sampleProcessing,
      status: 'draft',
      editableOutput: value,
    },
  }
  currentDraft.value = updated
  upsertProcessingStep(updated)
  if (sampleProcessingSaveTimer) {
    window.clearTimeout(sampleProcessingSaveTimer)
  }
  sampleProcessingSaveTimer = window.setTimeout(() => {
    sampleProcessingSaveTimer = null
    void saveProcessingStepDraft(updated, { silent: true })
  }, 600)
}

async function createPrototypeFromCurrentStep() {
  const draft = currentDraft.value
  if (!draft) {
    Message.warning('请先生成一个处理步骤。')
    return
  }
  if (draft.kind !== 'extraction') {
    Message.warning('一期候选优化先支持抽取 Skill。')
    return
  }
  const source = draft.sampleSource || activeSource.value
  const sourceText = String(source.sourceText || '').trim()
  if (!sourceText) {
    Message.warning('当前步骤没有可用于创建候选优化项目的样例内容。')
    return
  }
  const confirmedOutput = resolveConfirmedOutputForDraft(draft)
  if (confirmedOutput === undefined) {
    Message.warning('请先确认样例输出后再创建候选优化项目。')
    return
  }
  prototypeCreating.value = true
  try {
    const outputExample = JSON.stringify(confirmedOutput, null, 2)
    const project = await createSkillPrototype({
      name: `${draft.dataTypeName || draft.skillName || '抽取'} Skill 候选优化项目`,
      description: `来自文档应用制作步骤：${draft.skillName || draft.dataTypeName}`,
      extractionGoal: draft.goal || buildSkillInstruction(source),
      fieldRequirements: draft.expectedOutput || '',
      outputExample,
      source: {
        format: 'text',
        content: sourceText,
        fileName: `${draft.id || 'application-step'}-sample.txt`,
      },
      dataset: [
        {
          id: `sample-${Date.now()}`,
          name: draft.dataTypeName || draft.skillName || '应用制作样例',
          sourceFormat: 'text',
          sampleText: sourceText,
          expectedOutput: confirmedOutput,
          note: '由应用制作页确认样例生成。',
        },
      ],
    })
    if (draft.skillText.trim()) {
      await updateSkillPrototypeBaseline(project.id, { skillText: draft.skillText })
    }
    const updated: ProcessingStepDraft = {
      ...draft,
      skillDevelopment: buildSkillDevelopmentAsset({
        previous: draft.skillDevelopment,
        confirmedOutput,
        prototypeId: project.id,
      }),
    }
    currentDraft.value = updated
    upsertProcessingStep(updated)
    await saveProcessingStepDraft(updated, { silent: true })
    Message.success(`候选优化项目已创建：${project.id}`)
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '创建候选优化项目失败。')
  } finally {
    prototypeCreating.value = false
  }
}

function resolveConfirmedOutputForDraft(draft: ProcessingStepDraft): unknown {
  if (draft.skillDevelopment?.confirmedOutput !== undefined) return draft.skillDevelopment.confirmedOutput
  const sample = draft.kind === 'operation' ? draft.sampleProcessing : draft.sampleExtraction
  if (!sample?.editableOutput?.trim()) return undefined
  try {
    return JSON.parse(sample.editableOutput)
  } catch {
    return undefined
  }
}

async function saveAndRunCurrentStep() {
  const draft = currentDraft.value
  if (!draft) {
    Message.warning(activeSource.value.kind === 'operation' ? '请先生成处理步骤。' : '请先生成抽取步骤。')
    return
  }
  if (!draft.skillText.trim()) {
    Message.warning(draft.kind === 'operation' ? '请先确认样例处理结果并生成处理 Skill。' : '请先确认样例抽取结果并生成 Skill。')
    return
  }
  const normalizedSkillText = ensureSkillMarkdownFrontmatter(draft)
  let runnableDraft = draft
  if (normalizedSkillText !== draft.skillText.trim()) {
    const normalizedDraft: ProcessingStepDraft = {
      ...draft,
      skillText: normalizedSkillText,
      skillName: extractSkillName(normalizedSkillText) || draft.skillName,
    }
    currentDraft.value = normalizedDraft
    upsertProcessingStep(normalizedDraft)
    await saveProcessingStepDraft(normalizedDraft, { silent: true })
    runnableDraft = normalizedDraft
  }
  const source = runnableDraft.sampleSource || activeSource.value
  if (runnableDraft.kind === 'operation' && !source.targetIds.length) {
    Message.warning('业务处理步骤需要先选择一个提取结果作为样例。')
    return
  }
  runningStep.value = true
  stepRunState.value = null
  let activeRunStart: { runId: string; run?: PromptRunRecordResponse | null } | null = null
  try {
    if (source.pageIndex !== null) {
      store.setCurrentPage(source.pageIndex)
      await store.ensureOperationTargets()
    }
    const savedSkill = await createSkill({
      kind: runnableDraft.kind,
      skillText: runnableDraft.skillText,
      customerId: detail.value?.task.customerId ?? null,
    })
    await refreshSkillLists(runnableDraft.kind)
    const runStart = await runSavedSkill(runnableDraft.kind, savedSkill.id, savedSkill.version, source, runnableDraft.dataTypeName)
    activeRunStart = runStart
    setStepRunState(runStart, runnableDraft.kind, 'running', `已启动 ${runStart.runId}，正在等待模型试跑结果。`, undefined, runnableDraft.id)
    if (runnableDraft.kind === 'extraction') {
      void continueStepRunSync(runnableDraft, savedSkill, source, runStart)
      Message.info(`试跑已启动：${runStart.runId}。完成后会自动校验，通过后加入应用。`)
      return
    }
    const runCompleted = await waitForStepRun(runnableDraft.kind, runStart)
    if (runCompleted) {
      await assertStepRunMatchesConfirmedSample(runnableDraft, runStart)
    }
    const option = await resolveStepRunOption(runnableDraft.kind, runStart, savedSkill, runnableDraft, source)
    if (!option) {
      const message = runCompleted
        ? `运行 ${runStart.runId} 已完成，正在同步为应用步骤。`
        : `运行 ${runStart.runId} 仍在执行；系统会继续同步，完成后自动校验，通过后加入应用。`
      setStepRunState(runStart, runnableDraft.kind, runCompleted ? 'syncing' : 'running', message, undefined, runnableDraft.id)
      void continueStepRunSync(runnableDraft, savedSkill, source, runStart)
      Message.info('试跑已启动，完成后会自动校验，通过后加入应用。')
      return
    }
    await applyVerifiedStepRun(runnableDraft, option)
  } catch (error) {
    const stepLabel = runnableDraft.kind === 'extraction' ? '抽取步骤' : '处理步骤'
    if (activeRunStart) {
      const outcome = runnableDraft.kind === 'extraction' ? await loadStepRunOutcome(runnableDraft.kind, activeRunStart) : null
      stepRunState.value = {
        draftId: runnableDraft.id,
        runId: activeRunStart.runId,
        kind: runnableDraft.kind,
        status: 'failed',
        message: error instanceof Error ? error.message : `${stepLabel}试跑失败。`,
        resultPreview: outcome?.resultPreview || '',
        validationErrors: outcome?.validationErrors,
        detailStatus: outcome?.detail?.status,
        updatedAt: new Date().toISOString(),
      }
    }
    Message.error(error instanceof Error ? error.message : `${stepLabel}试跑失败。`)
  } finally {
    runningStep.value = false
  }
}

function setStepRunState(
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
  kind: ApplicationStepKind,
  status: StepRunSyncState['status'],
  message: string,
  resultPreview?: string,
  draftId = currentDraft.value?.id || '',
  outcome?: StepRunOutcome,
) {
  stepRunState.value = {
    draftId,
    runId: runStart.runId,
    kind,
    status,
    message,
    resultPreview,
    validationErrors: outcome?.validationErrors,
    detailStatus: outcome?.detail?.status,
    updatedAt: new Date().toISOString(),
  }
}

async function applyVerifiedStepRun(
  draft: ProcessingStepDraft,
  option: ApplicationSourceRunOption,
) {
  const verified: ProcessingStepDraft = {
    ...draft,
    status: 'verified',
    skillName: option.skillName || draft.skillName,
    runOption: option,
  }
  upsertProcessingStep(verified)
  currentDraft.value = verified
  const persisted = await saveProcessingStepDraft(verified)
  const stepLabel = draft.kind === 'extraction' ? '抽取步骤' : '处理步骤'
  stepRunState.value = {
    draftId: draft.id,
    runId: option.runId,
    kind: draft.kind,
    status: 'completed',
    message: persisted ? `${stepLabel}已试跑完成，并已加入文档应用。` : `${stepLabel}已试跑完成，但草稿保存失败。`,
    resultPreview: option.resultPreview,
    updatedAt: new Date().toISOString(),
  }
  Message.success(persisted ? `${stepLabel}已试跑，并加入文档应用。` : `${stepLabel}已试跑，但草稿保存失败。`)
}

async function continueStepRunSync(
  draft: ProcessingStepDraft,
  savedSkill: UnifiedSkill,
  source: SampleSource,
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const outcome = await loadStepRunOutcome(draft.kind, runStart)
      if (outcome.status === 'processing') {
        setStepRunState(
          runStart,
          draft.kind,
          'running',
          `运行 ${runStart.runId} 仍在执行；完成后会自动同步。`,
          outcome.resultPreview,
          draft.id,
          outcome,
        )
        await delay(3000)
        continue
      }
      if (outcome.status === 'failed' || outcome.status === 'empty') {
        stepRunState.value = {
          draftId: draft.id,
          runId: runStart.runId,
          kind: draft.kind,
          status: 'failed',
          message: outcome.message,
          resultPreview: outcome.resultPreview,
          validationErrors: outcome.validationErrors,
          detailStatus: outcome.detail?.status,
          updatedAt: new Date().toISOString(),
        }
        Message.error(outcome.message)
        return
      }
      if (outcome.status === 'needs_review') {
        stepRunState.value = {
          draftId: draft.id,
          runId: runStart.runId,
          kind: draft.kind,
          status: 'needs_review',
          message: outcome.message,
          resultPreview: outcome.resultPreview,
          validationErrors: outcome.validationErrors,
          detailStatus: outcome.detail?.status,
          updatedAt: new Date().toISOString(),
        }
        Message.warning(outcome.message)
        return
      }
      await assertStepRunMatchesConfirmedSample(draft, runStart)
      setStepRunState(
        runStart,
        draft.kind,
        'syncing',
        `运行 ${runStart.runId} 已完成，正在同步输出和应用步骤。`,
        outcome.resultPreview,
        draft.id,
        outcome,
      )
      const option = await resolveStepRunOption(draft.kind, runStart, savedSkill, draft, source)
      if (option) {
        await applyVerifiedStepRun(draft, option)
        return
      }
      await delay(3000)
    } catch (error) {
      const outcome = draft.kind === 'extraction' ? await loadStepRunOutcome(draft.kind, runStart) : null
      stepRunState.value = {
        draftId: draft.id,
        runId: runStart.runId,
        kind: draft.kind,
        status: 'failed',
        message: error instanceof Error ? error.message : '步骤试跑同步失败。',
        resultPreview: outcome?.resultPreview || '',
        validationErrors: outcome?.validationErrors,
        detailStatus: outcome?.detail?.status,
        updatedAt: new Date().toISOString(),
      }
      Message.error(stepRunState.value.message)
      return
    }
  }
  setStepRunState(runStart, draft.kind, 'syncing', `运行 ${runStart.runId} 已启动，但结果同步超过预期；可以稍后刷新应用步骤。`, undefined, draft.id)
}

async function refreshSkillLists(kind: ApplicationStepKind) {
  if (kind === 'extraction') {
    await store.ensureExtractionSkills(true)
  } else {
    await store.ensureBusinessSkills(true)
  }
}

async function runSavedSkill(
  kind: ApplicationStepKind,
  skillId: string,
  skillVersion: string,
  source: SampleSource,
  dataTypeNameForRun: string,
): Promise<{ runId: string; run?: PromptRunRecordResponse | null }> {
  if (kind === 'extraction') {
    const response = await store.runExtractionSkillProcessing({
      skillId,
      skillVersion,
      config: {
        dataTypeName: dataTypeNameForRun,
        sourceScope: source.sourceScope,
        ...buildExtractionTrialRuntimeConfig(source, currentDraft.value),
      },
    }, { fetchDetail: false })
    const run = response?.runs[0] || null
    const runId = run?.id
    if (!runId) throw new Error('解析步骤没有返回运行记录。')
    return { runId, run }
  }

  const response = await store.runSkillOperation({
    skillId,
    skillVersion,
    targetIds: source.targetIds,
    config: {
      dataTypeName: dataTypeNameForRun,
      sourceScope: source.sourceScope,
    },
  })
  if (!response) throw new Error('处理步骤没有返回运行记录。')
  if (response.run.status === 'failed') {
    throw new Error(response.run.errorMessage || '处理步骤试跑失败。')
  }
  if (response.run.status === 'needs_review') {
    throw new Error('处理步骤试跑需要人工复核，确认通过后才能加入应用。')
  }
  if (response.run.status !== 'completed') {
    throw new Error('处理步骤尚未完成，暂不能加入应用。')
  }
  const runId = response?.result?.id || response?.run.id
  if (!runId) throw new Error('处理步骤没有返回运行记录。')
  return { runId, run: response.run }
}

function buildExtractionTrialRuntimeConfig(
  source: SampleSource,
  draft: ProcessingStepDraft | null,
): Record<string, unknown> {
  if (!draft || draft.kind !== 'extraction') return {}
  const expectation = resolveExtractionTrialExpectationForDraft(draft)
  if (!expectation.outputType) return {}
  const pageNos = sampleSourcePageNos(source)
  const contentRefs: Array<Record<string, unknown>> = Array.isArray(source.contentRefs) ? source.contentRefs : []
  const selectedContent = contentRefs.map((ref) => ({
    source: String(ref.source || ref.kind || source.mode || '').trim() || source.mode,
    title: String(ref.title || ref.label || source.title || '').trim(),
    treeNodeId: String(ref.treeNodeId || ref.nodeId || source.treeNodeId || '').trim(),
    nodeId: String(ref.nodeId || ref.treeNodeId || source.treeNodeId || '').trim(),
    blockIds: Array.isArray(ref.blockIds) ? ref.blockIds.map(String).filter(Boolean) : [],
    pages: Array.isArray(ref.pages) ? ref.pages : pageNos,
    evidencePages: Array.isArray(ref.evidencePages) ? ref.evidencePages : pageNos,
    excerpt: String(ref.excerpt || ref.summary || ref.sourceText || source.summary || '').trim().slice(0, 500),
  }))
  if (!selectedContent.length) {
    selectedContent.push({
      source: source.mode,
      title: source.title || draft.dataTypeName,
      treeNodeId: source.treeNodeId || '',
      nodeId: source.treeNodeId || '',
      blockIds: [],
      pages: pageNos,
      evidencePages: pageNos,
      excerpt: (source.summary || source.sourceText || '').slice(0, 500),
    })
  }
  const outputProtocol = buildExtractionTrialOutputProtocol(expectation)
  const generatedTargets = buildExtractionTrialGeneratedTargets(expectation)
  const runtimeContract = {
    contractVersion: 'application_workshop_trial_contract_v2',
    outputType: expectation.outputType,
    fieldLabels: expectation.fieldLabels,
    tableHeaders: expectation.tableHeaders,
    recordFields: expectation.recordFields,
    expectedCounts: {
      fields: expectation.fieldCount || expectation.fieldLabels.length || undefined,
      tableRows: expectation.tableRowCount || undefined,
      records: expectation.recordCount || undefined,
    },
    selectedContent,
    matchedPageNos: pageNos,
    outputProtocol,
    rules: [
      '本次试跑必须遵守应用制作确认样例的输出契约。',
      'runtimeContract 是最终运行契约；Skill.md 正文是能力说明，不得缩小或替换本契约。',
      '输出值只能来自当前任务 facts 和 selectedContent 对应证据；证据不足时按输出协议留空或进入复核。',
    ],
  }
  return {
    runtimeContract,
    applicationScope: {
      inputMapping: {
        sourceScope: source.sourceScope,
        pageNo: source.pageNo,
        startPageNo: pageNos[0] || source.pageNo || 1,
        endPageNo: pageNos[pageNos.length - 1] || source.pageNo || 1,
        matchedPageNos: pageNos,
        contentRefs: selectedContent,
        sampleSource: cloneJson(source),
      },
      targetMapping: {
        outputType: expectation.outputType,
        generatedTargets,
        targetSelector: {
          locatorProfile: {
            confirmedOutputShape: [
              {
                outputType: expectation.outputType,
                fieldLabels: expectation.fieldLabels,
                tableHeaders: expectation.tableHeaders,
                recordFields: expectation.recordFields,
                expectedCounts: runtimeContract.expectedCounts,
              },
            ],
          },
        },
      },
    },
  }
}

function sampleSourcePageNos(source: SampleSource): number[] {
  const pages = new Set<number>()
  const start = Number(source.pageRange?.start)
  const end = Number(source.pageRange?.end || source.pageRange?.start)
  if (Number.isFinite(start) && start > 0) {
    const last = Number.isFinite(end) && end >= start ? end : start
    for (let page = start; page <= last; page += 1) pages.add(page)
  }
  if (source.pageNo) pages.add(source.pageNo)
  for (const ref of source.contentRefs || []) {
    const values = Array.isArray(ref.evidencePages) ? ref.evidencePages : Array.isArray(ref.pages) ? ref.pages : []
    values.forEach((value) => {
      const page = Number(value)
      if (Number.isFinite(page) && page > 0) pages.add(page)
    })
  }
  return Array.from(pages).sort((a, b) => a - b)
}

function resolveExtractionTrialExpectationForDraft(draft: ProcessingStepDraft): ExtractionTrialExpectation {
  const candidates: unknown[] = [
    parseJsonOrUndefined(draft.sampleExtraction?.editableOutput),
    draft.skillDevelopment?.confirmedOutput,
    draft.sampleExtraction?.result,
    draft.skillDevelopment?.outputContractSummary,
    draft.skillDevelopment?.runtimeContract,
  ]
  const outputType = resolveExtractionTrialOutputType(draft, candidates)
  const fieldLabels = extractFieldListLabels(candidates)
  const fieldCount = Math.max(...candidates.map((item) => extractFieldListCount(item)), fieldLabels.length, 0)
  const tableShape = extractDataTableShape(candidates)
  const recordShape = extractRecordCollectionShape(candidates)
  return {
    outputType,
    fieldLabels,
    fieldCount,
    tableHeaders: tableShape.headers,
    tableRowCount: tableShape.rowCount,
    recordFields: recordShape.fields,
    recordCount: recordShape.count,
  }
}

function resolveExtractionTrialOutputType(draft: ProcessingStepDraft, candidates: unknown[]) {
  const contract = plainRecord(draft.skillDevelopment?.outputContractSummary || draft.skillDevelopment?.runtimeContract)
  const direct = pickKnownExtractionOutputType([
    contract.outputType,
    contract.type,
    contract.resultType,
    resolveExtractionOutputType(draft),
  ])
  if (direct) return direct
  for (const candidate of candidates) {
    const detected = detectExtractionOutputType(candidate)
    if (detected) return detected
  }
  return 'custom'
}

function detectExtractionOutputType(value: unknown, depth = 0): string {
  if (!value || depth > 8) return ''
  if (Array.isArray(value)) {
    return value.length ? 'record_collection' : ''
  }
  if (typeof value !== 'object') return ''
  const record = value as Record<string, unknown>
  const explicit = pickKnownExtractionOutputType([record.type, record.outputType, record.renderer])
  if (explicit) return explicit
  if (Array.isArray(record.fields)) return 'field_list'
  if (Array.isArray(record.headers) && Array.isArray(record.rows)) return 'data_table'
  if (Array.isArray(record.records)) return 'record_collection'
  for (const key of ['data', 'data_table', 'field_list', 'record_collection']) {
    const detected = detectExtractionOutputType(record[key], depth + 1)
    if (detected) return detected
  }
  if (Array.isArray(record.outputs)) {
    for (const output of record.outputs) {
      const detected = detectExtractionOutputType(output, depth + 1)
      if (detected) return detected
    }
  }
  return ''
}

function buildExtractionTrialOutputProtocol(expectation: ExtractionTrialExpectation) {
  if (expectation.outputType === 'field_list') {
    return {
      jsonShape: {
        fields: expectation.fieldLabels.map((label) => ({
          label,
          value: '从 facts 填入；缺失时为空字符串',
          source_page: '第 X 页或空字符串',
        })),
      },
      requiredFieldLabels: expectation.fieldLabels,
      missingValue: '',
      forbiddenTopLevelKeys: ['headers', 'rows', 'mergeNotes'],
    }
  }
  if (expectation.outputType === 'data_table') {
    return {
      jsonShape: {
        headers: expectation.tableHeaders,
        rows: '二维数组；保持确认样例的行列语义',
        mergeNotes: '可选；合并单元格、分组或矩阵语义说明',
        evidence: '可选；来源页和证据摘要',
      },
      expectedHeaders: expectation.tableHeaders,
      expectedRowCount: expectation.tableRowCount || undefined,
      preserveStructure: true,
    }
  }
  if (expectation.outputType === 'record_collection') {
    return {
      jsonShape: {
        records: [
          Object.fromEntries(expectation.recordFields.map((field) => [field, '从 facts 填入；缺失时为空字符串'])),
        ],
      },
      requiredRecordFields: expectation.recordFields,
      expectedRecordCount: expectation.recordCount || undefined,
      missingValue: '',
    }
  }
  return {
    jsonShape: '按确认样例的 JSON 结构输出。',
    preserveConfirmedShape: true,
  }
}

function buildExtractionTrialGeneratedTargets(expectation: ExtractionTrialExpectation) {
  if (expectation.outputType === 'field_list') {
    return expectation.fieldLabels.map((label, index) => ({
      id: `trial-field-${index + 1}`,
      type: 'field',
      label,
      fieldKey: label,
    }))
  }
  if (expectation.outputType === 'data_table') {
    return expectation.tableHeaders.map((label, index) => ({
      id: `trial-column-${index + 1}`,
      type: 'table_column',
      label,
      fieldKey: label,
    }))
  }
  if (expectation.outputType === 'record_collection') {
    return expectation.recordFields.map((label, index) => ({
      id: `trial-record-field-${index + 1}`,
      type: 'record_field',
      label,
      fieldKey: label,
    }))
  }
  return []
}

function extractDataTableShape(value: unknown): { headers: string[]; rowCount: number } {
  const values = Array.isArray(value) ? value : [value]
  const headers: string[] = []
  let rowCount = 0
  values.forEach((item) => collectDataTableShape(item, headers, (count) => {
    rowCount = Math.max(rowCount, count)
  }, 0))
  return { headers: uniqueStrings(headers), rowCount }
}

function collectDataTableShape(
  value: unknown,
  headers: string[],
  updateRowCount: (count: number) => void,
  depth: number,
) {
  if (!value || depth > 8) return
  if (Array.isArray(value)) {
    for (const item of value) collectDataTableShape(item, headers, updateRowCount, depth + 1)
    return
  }
  if (typeof value !== 'object') return
  const record = value as Record<string, unknown>
  if (Array.isArray(record.headers)) {
    headers.push(...record.headers.map((item) => String(item || '').trim()).filter(Boolean))
  }
  if (Array.isArray(record.rows)) {
    updateRowCount(record.rows.length)
  }
  for (const key of ['data', 'data_table']) {
    collectDataTableShape(record[key], headers, updateRowCount, depth + 1)
  }
  if (Array.isArray(record.outputs)) {
    for (const output of record.outputs) collectDataTableShape(output, headers, updateRowCount, depth + 1)
  }
}

function extractRecordCollectionShape(value: unknown): { fields: string[]; count: number } {
  const values = Array.isArray(value) ? value : [value]
  const fields: string[] = []
  let count = 0
  values.forEach((item) => collectRecordCollectionShape(item, fields, (nextCount) => {
    count = Math.max(count, nextCount)
  }, 0))
  return { fields: uniqueStrings(fields), count }
}

function collectRecordCollectionShape(
  value: unknown,
  fields: string[],
  updateCount: (count: number) => void,
  depth: number,
) {
  if (!value || depth > 8) return
  if (Array.isArray(value)) {
    updateCount(value.length)
    for (const item of value) {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        fields.push(...Object.keys(item as Record<string, unknown>).filter(Boolean))
      }
    }
    return
  }
  if (typeof value !== 'object') return
  const record = value as Record<string, unknown>
  const schema = plainRecord(record.schema)
  for (const key of ['required', 'requiredFields', 'fields', 'recordFields']) {
    const schemaFields = schema[key] || record[key]
    if (Array.isArray(schemaFields)) {
      fields.push(...schemaFields.map((item) => String(item || '').trim()).filter(Boolean))
    }
  }
  if (Array.isArray(record.records)) {
    updateCount(record.records.length)
    for (const item of record.records) {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        fields.push(...Object.keys(item as Record<string, unknown>).filter(Boolean))
      }
    }
  }
  for (const key of ['data', 'record_collection']) {
    collectRecordCollectionShape(record[key], fields, updateCount, depth + 1)
  }
  if (Array.isArray(record.outputs)) {
    for (const output of record.outputs) collectRecordCollectionShape(output, fields, updateCount, depth + 1)
  }
}

async function waitForStepRun(
  kind: ApplicationStepKind,
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
  maxAttempts = STEP_RUN_MAX_ATTEMPTS,
) {
  if (kind === 'operation') {
    return true
  }
  if (runStart.run?.status === 'completed') {
    return true
  }
  if (runStart.run?.status === 'failed') {
    throw new Error(runStart.run.errorMessage || '解析步骤试跑失败。')
  }
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const outcome = await loadStepRunOutcome(kind, runStart)
    if (outcome.status === 'processing') {
      if (attempt < maxAttempts - 1) {
        await delay(STEP_RUN_POLL_INTERVAL_MS)
      }
      continue
    }
    if (outcome.status === 'failed' || outcome.status === 'empty') {
      throw new Error(outcome.message)
    }
    if (outcome.status === 'needs_review') return true
    return true
  }
  const finalOutcome = await loadStepRunOutcome(kind, runStart)
  if (finalOutcome.status === 'completed') {
    return true
  }
  if (finalOutcome.status === 'failed' || finalOutcome.status === 'empty') {
    throw new Error(finalOutcome.message)
  }
  if (finalOutcome.status === 'needs_review') return true
  return false
}

async function loadStepRunOutcome(
  kind: ApplicationStepKind,
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
): Promise<StepRunOutcome> {
  if (kind !== 'extraction') {
    return {
      status: 'completed',
      detail: null,
      message: '处理步骤试跑已完成。',
      resultPreview: summarizeRunOptionPreview(runStart.run?.outputText, '处理步骤试跑已完成。'),
      validationErrors: [],
    }
  }
  const detail = await fetchStepResultDetail(runStart.runId)
  if (!detail || detail.status === 'processing') {
    return {
      status: 'processing',
      detail,
      message: `运行 ${runStart.runId} 仍在执行。`,
      resultPreview: buildStepRunResultPreview(detail, '模型仍在生成本次试跑输出。'),
      validationErrors: detail?.validationErrors || [],
    }
  }
  const validationErrors = detail.validationErrors || []
  const resultPreview = buildStepRunResultPreview(detail, detail.errorMessage || detail.title || '试跑已结束。')
  if (detail.status === 'failed') {
    return {
      status: 'failed',
      detail,
      message: detail.errorMessage || validationErrors[0] || '解析步骤试跑失败。',
      resultPreview,
      validationErrors,
    }
  }
  if (detail.status === 'empty') {
    return {
      status: 'empty',
      detail,
      message: '解析步骤试跑没有抽取到有效结果，不能加入应用。',
      resultPreview,
      validationErrors,
    }
  }
  if (detail.status === 'needs_review') {
    return {
      status: 'needs_review',
      detail,
      message: detail.errorMessage || validationErrors[0] || '解析步骤试跑需要人工复核，确认通过后才能加入应用。',
      resultPreview,
      validationErrors,
    }
  }
  return {
    status: 'completed',
    detail,
    message: '解析步骤试跑已完成。',
    resultPreview,
    validationErrors,
  }
}

function buildStepRunResultPreview(detail: PageResultDetail | null, fallback: string) {
  if (!detail) return fallback
  const payload = {
    runId: detail.id,
    status: detail.status,
    promptName: detail.promptName,
    pageRange: detail.pageRange,
    errorMessage: detail.errorMessage || undefined,
    validationErrors: detail.validationErrors?.length ? detail.validationErrors : undefined,
    output: detail.extractionResult || detail.schemaOutput || detail.outputText || undefined,
  }
  return summarizeRunOptionPreview(payload, fallback)
}

async function assertStepRunMatchesConfirmedSample(
  draft: ProcessingStepDraft,
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
) {
  if (draft.kind !== 'extraction') return
  const expectation = resolveExtractionTrialExpectationForDraft(draft)
  const detail = await fetchStepResultDetail(runStart.runId)
  if (!detail?.extractionResult) {
    throw new Error('Skill 试跑没有返回可校验的抽取结果。')
  }
  if (expectation.outputType === 'field_list') {
    const actualLabels = extractFieldListLabels(detail.extractionResult)
    const actualCount = actualLabels.length || extractFieldListCount(detail.extractionResult)
    const missingLabels = expectation.fieldLabels.filter((label) => !actualLabels.includes(label))
    const expectedCount = expectation.fieldCount || expectation.fieldLabels.length
    const countMismatch = expectedCount > 0 && actualCount !== expectedCount
    if (!actualCount || missingLabels.length || countMismatch) {
      const missingText = missingLabels.length ? `，缺少：${missingLabels.slice(0, 12).join('、')}` : ''
      const expectedText = expectation.fieldLabels.length
        ? `确认样例 ${expectation.fieldLabels.length} 个字段`
        : `确认样例 ${expectedCount} 个字段`
      throw new Error(
        `Skill 试跑输出与确认样例不一致：${expectedText}，模型试跑返回 ${actualCount} 个字段${missingText}。请调整 SKILL.md 后重新试跑。`,
      )
    }
    return
  }
  if (expectation.outputType === 'data_table') {
    const actual = extractDataTableShape(detail.extractionResult)
    const expectedRows = expectation.tableRowCount
    const expectedHeaders = expectation.tableHeaders
    const missingHeaders = expectedHeaders.filter((header) => !actual.headers.includes(header))
    const rowMismatch = expectedRows > 0 && actual.rowCount < expectedRows
    if (!actual.rowCount || missingHeaders.length || rowMismatch) {
      const missingText = missingHeaders.length ? `，缺少表头：${missingHeaders.slice(0, 12).join('、')}` : ''
      throw new Error(
        `Skill 试跑输出与确认样例不一致：确认样例 ${expectedRows || '若干'} 行表格，模型试跑返回 ${actual.rowCount} 行${missingText}。请调整 SKILL.md 后重新试跑。`,
      )
    }
    return
  }
  if (expectation.outputType === 'record_collection') {
    const actual = extractRecordCollectionShape(detail.extractionResult)
    const expectedCount = expectation.recordCount
    const missingFields = expectation.recordFields.filter((field) => !actual.fields.includes(field))
    const countMismatch = expectedCount > 0 && actual.count !== expectedCount
    if (!actual.count || missingFields.length || countMismatch) {
      const missingText = missingFields.length ? `，缺少记录字段：${missingFields.slice(0, 12).join('、')}` : ''
      throw new Error(
        `Skill 试跑输出与确认样例不一致：确认样例 ${expectedCount || '若干'} 条记录，模型试跑返回 ${actual.count} 条${missingText}。请调整 SKILL.md 或定位范围后重新试跑。`,
      )
    }
  }
}

function parseJsonOrUndefined(value: unknown): unknown {
  if (typeof value !== 'string' || !value.trim()) return undefined
  try {
    return JSON.parse(value)
  } catch {
    return undefined
  }
}

function extractFieldListLabels(value: unknown): string[] {
  const labels: string[] = []
  collectFieldListLabels(value, labels, 0)
  return uniqueStrings(labels)
}

function extractFieldListCount(value: unknown): number {
  const counts: number[] = []
  collectFieldListCounts(value, counts, 0)
  return counts.length ? Math.max(...counts) : 0
}

function collectFieldListCounts(value: unknown, counts: number[], depth: number) {
  if (!value || depth > 8) return
  if (typeof value === 'string') {
    const match = value.match(/(\d+)\s*个字段/)
    if (match) counts.push(Number(match[1]))
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectFieldListCounts(item, counts, depth + 1)
    return
  }
  if (typeof value !== 'object') return
  const record = value as Record<string, unknown>
  for (const key of ['fieldLabels', 'labels', 'requiredFields', 'fieldsToExtract']) {
    const fieldLabels = record[key]
    if (Array.isArray(fieldLabels) && fieldLabels.every((item) => typeof item === 'string')) {
      counts.push(fieldLabels.map((item) => String(item || '').trim()).filter(Boolean).length)
    }
  }
  if (Array.isArray(record.fields)) {
    counts.push(record.fields.length)
  }
  for (const key of ['summary', 'resultSummary', 'description', 'text']) {
    collectFieldListCounts(record[key], counts, depth + 1)
  }
  if (record.data) collectFieldListCounts(record.data, counts, depth + 1)
  if (Array.isArray(record.outputs)) collectFieldListCounts(record.outputs, counts, depth + 1)
}

function collectFieldListLabels(value: unknown, labels: string[], depth: number) {
  if (!value || depth > 8) return
  if (Array.isArray(value)) {
    for (const item of value) collectFieldListLabels(item, labels, depth + 1)
    return
  }
  if (typeof value !== 'object') return
  const record = value as Record<string, unknown>
  for (const key of ['fieldLabels', 'labels', 'requiredFields', 'fieldsToExtract']) {
    const fieldLabels = record[key]
    if (Array.isArray(fieldLabels) && fieldLabels.every((item) => typeof item === 'string')) {
      labels.push(...fieldLabels.map((item) => item.trim()).filter(Boolean))
    }
  }
  if (Array.isArray(record.fields)) {
    for (const field of record.fields) {
      const fieldRecord = plainRecord(field)
      const label = String(fieldRecord.label || fieldRecord.name || fieldRecord.field || '').trim()
      if (label) labels.push(label)
    }
  }
  if (record.data) collectFieldListLabels(record.data, labels, depth + 1)
  if (Array.isArray(record.outputs)) collectFieldListLabels(record.outputs, labels, depth + 1)
}

async function resolveStepRunOption(
  kind: ApplicationStepKind,
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
  savedSkill: UnifiedSkill,
  draft: ProcessingStepDraft,
  source: SampleSource,
) {
  const runId = runStart.runId
  const existing = findRunOption(kind, runId)
  if (existing) return existing

  const fallback = await buildFallbackRunOption(kind, runStart, savedSkill, draft, source)
  if (fallback) {
    mergeRunOptionIntoApplicationContext(fallback)
    return fallback
  }
  return null
}

async function buildFallbackRunOption(
  kind: ApplicationStepKind,
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
  savedSkill: UnifiedSkill,
  draft: ProcessingStepDraft,
  source: SampleSource,
): Promise<ApplicationSourceRunOption | null> {
  if (kind === 'extraction') {
    return await buildFallbackExtractionRunOption(runStart, savedSkill, draft)
  }
  return await buildFallbackOperationRunOption(runStart.runId, savedSkill, draft, source)
}

async function buildFallbackExtractionRunOption(
  runStart: { runId: string; run?: PromptRunRecordResponse | null },
  savedSkill: UnifiedSkill,
  draft: ProcessingStepDraft,
): Promise<ApplicationSourceRunOption | null> {
  if (!runtimeTaskId.value) return null
  const runId = runStart.runId
  const resultDetail = await fetchStepResultDetail(runId)
  const completedStatuses = new Set(['completed', 'ready'])
  if (resultDetail && !completedStatuses.has(String(resultDetail.status))) {
    return null
  }
  if (!resultDetail && runStart.run?.status && runStart.run.status !== 'completed') {
    return null
  }
  const extractionResult = resultDetail?.extractionResult
  const runMeta = plainRecord(extractionResult?.runMeta)
  const skillId = String(runMeta.skillId || savedSkill.id || draft.runOption?.skillId || '').trim()
  const skillVersion = String(runMeta.skillVersion || savedSkill.version || draft.runOption?.skillVersion || '1.0.0').trim()
  if (!skillId || !skillVersion) return null
  const summary = String(
    extractionResult?.summary
      || resultDetail?.promptName
      || resultDetail?.title
      || runStart.run?.runName
      || runStart.run?.promptName
      || '结构化解析结果',
  ).trim()
  const pageNo = resultDetail?.pageNo || runStart.run?.startPageNo || 1
  return {
    id: `parse:${runId}`,
    kind: 'extraction',
    runId,
    skillId,
    skillVersion,
    skillName: savedSkill.name || draft.skillName || skillId,
    executor: String(runMeta.executor || savedSkill.executor || ''),
    pageNo,
    title: resultDetail?.title || runStart.run?.runName || savedSkill.name || draft.skillName || skillId,
    summary,
    createdAt: resultDetail?.lastHeartbeatAt || resultDetail?.phaseStartedAt || runStart.run?.updatedAt || null,
    promptSnapshot: draft.skillText,
    configSnapshot: plainRecord(runMeta.configSnapshot),
    inputMapping: [
      {
        source: 'document',
        label: `任务文档 ${detail.value?.document.fileName || ''}`.trim() || '任务文档',
      },
    ],
    outputAlias: nextRunOptionAlias('extraction'),
    resultPreview: summarizeRunOptionPreview(extractionResult || runStart.run?.outputText, summary),
    targetMapping: null,
    recommended: true,
  }
}

async function fetchStepResultDetail(runId: string): Promise<PageResultDetail | null> {
  const detailTaskId = runtimeTaskId.value
  if (!detailTaskId) return null
  const cached = stepRunResultDetails.value[runId]
  if (cached && cached.status !== 'processing') {
    return cached
  }

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => {
    controller.abort()
  }, STEP_RUN_DETAIL_TIMEOUT_MS)
  try {
    const detail = await loadPromptRunDetail(detailTaskId, runId, {
      signal: controller.signal,
    })
    stepRunResultDetails.value = {
      ...stepRunResultDetails.value,
      [runId]: detail,
    }
    return detail
  } catch (error) {
    if ((error as { name?: string })?.name !== 'AbortError') {
      console.warn('Failed to fetch step run detail', error)
    }
    return cached ?? null
  } finally {
    window.clearTimeout(timeoutId)
  }
}

async function buildFallbackOperationRunOption(
  runId: string,
  savedSkill: UnifiedSkill,
  draft: ProcessingStepDraft,
  source: SampleSource,
): Promise<ApplicationSourceRunOption | null> {
  if (!taskId.value) return null
  let result = detail.value?.objectOperationResults?.find((item) => item.id === runId) || null
  if (!result) {
    try {
      result = await loadObjectOperationResult(taskId.value, runId)
    } catch {
      result = null
    }
  }
  if (!result) return null
  const skillId = String(result.skillId || result.sourceSkillId || savedSkill.id || '').trim()
  const skillVersion = String(result.skillVersion || result.sourceSkillVersion || savedSkill.version || '').trim()
  if (!skillId || !skillVersion) return null
  const targetIds = uniqueStrings([result.targetId, ...(result.relatedTargetIds || []), ...source.targetIds])
  const summary = result.summary || '业务处理结果'
  return {
    id: `operation:${runId}`,
    kind: 'operation',
    runId,
    skillId,
    skillVersion,
    skillName: savedSkill.name || result.sourceSkillName || draft.skillName || skillId,
    executor: result.executor || savedSkill.executor || '',
    pageNo: result.pageNo,
    title: savedSkill.name || result.sourceSkillName || draft.skillName || '业务处理',
    summary,
    createdAt: result.createdAt || null,
    promptSnapshot: draft.skillText,
    configSnapshot: plainRecord(result.configSnapshot),
    inputMapping: [
      {
        source: 'current_targets',
        label: '当前任务提取对象',
        targetIds,
      },
    ],
    outputAlias: nextRunOptionAlias('operation'),
    resultPreview: summarizeRunOptionPreview(result.outputPayload, summary),
    targetMapping: {
      targetIds,
      targetLabels: [],
    },
    recommended: true,
  }
}

function mergeRunOptionIntoApplicationContext(option: ApplicationSourceRunOption) {
  const context = applicationDraftContext.value
  if (!context) return
  if (option.kind === 'extraction') {
    const parseOptions = replaceOrAppendRunOption(context.parseOptions, option)
    applicationDraftContext.value = {
      ...context,
      parseOptions,
      defaultParseOptionId: option.id,
      missingRequirements: context.missingRequirements.filter((item) => !item.includes('数据提取步骤')),
    }
    return
  }
  const operationOptions = replaceOrAppendRunOption(context.operationOptions, option)
  applicationDraftContext.value = {
    ...context,
    operationOptions,
    defaultOperationOptionIds: uniqueStrings([...context.defaultOperationOptionIds, option.id]),
  }
}

function replaceOrAppendRunOption(options: ApplicationSourceRunOption[], option: ApplicationSourceRunOption) {
  const next = options.filter((item) => item.runId !== option.runId && item.id !== option.id)
  return [...next, option]
}

function nextRunOptionAlias(kind: ApplicationStepKind) {
  const context = applicationDraftContext.value
  if (kind === 'extraction') {
    return `parse_${(context?.parseOptions.length || 0) + 1}`
  }
  return `operation_${(context?.operationOptions.length || 0) + 1}`
}

function summarizeRunOptionPreview(value: unknown, fallback: string) {
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

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item || '').trim()).filter(Boolean)))
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function findRunOption(kind: ApplicationStepKind, runId: string) {
  const context = applicationDraftContext.value
  if (!context) return null
  const options = kind === 'extraction' ? context.parseOptions : context.operationOptions
  return options.find((item) => item.runId === runId) ?? null
}

function processingStepPublishKey(step: ProcessingStepDraft) {
  return step.runOption
    ? `${step.kind}:${step.runOption.runId}`
    : `${step.kind}:${step.id}`
}

function collectPublishableProcessingSteps() {
  const steps = [...processingSteps.value]
  const draft = currentDraft.value
  if (draft?.status === 'verified' && draft.runOption) {
    const draftKey = processingStepPublishKey(draft)
    if (!steps.some((item) => processingStepPublishKey(item) === draftKey)) {
      steps.push(draft)
    }
  }
  return steps.filter((item) => item.status === 'verified' && item.runOption)
}

function currentDraftPublishIssue() {
  const draft = currentDraft.value
  if (!draft) return ''
  const hasDraftWork = Boolean(
    draft.skillText.trim()
    || draft.sampleExtraction?.status === 'confirmed'
    || draft.sampleProcessing?.status === 'confirmed',
  )
  if (!hasDraftWork) return ''
  if (draft.status === 'verified' && draft.runOption) return ''
  const stepName = draft.skillName || draft.dataTypeName || '当前步骤'
  if (draft.status === 'verified') {
    return `当前步骤「${stepName}」缺少试跑结果，无法写入应用。请重新试跑后再保存或发布。`
  }
  return `当前正在编辑的「${stepName}」还没有试跑并加入文档应用，保存或发布不会包含它。请先点击“保存并试跑”。`
}

function upsertProcessingStep(step: ProcessingStepDraft) {
  const key = step.runOption
    ? `${step.kind}:${step.runOption.runId}`
    : `${step.kind}:${step.dataTypeName}:${step.sourceScope}`
  const editingId = editingStepId.value.trim()
  const removed: ProcessingStepDraft[] = []
  const next = processingSteps.value.filter((item) => {
    const itemKey = item.runOption
      ? `${item.kind}:${item.runOption.runId}`
      : `${item.kind}:${item.dataTypeName}:${item.sourceScope}`
    const shouldReplace = item.id === step.id || (editingId && item.id === editingId) || itemKey === key
    const shouldKeep = !shouldReplace
    if (!shouldKeep) removed.push(item)
    return shouldKeep
  })
  processingSteps.value = [...next, step]
  removed
    .filter((item) => item.id !== step.id)
    .forEach((item) => {
      void deleteProcessingStepDraft(item.id, { silent: true })
    })
}

function replaceProcessingStepInMemory(step: ProcessingStepDraft) {
  let replaced = false
  const next: ProcessingStepDraft[] = []
  for (const item of processingSteps.value) {
    if (item.id !== step.id) {
      next.push(item)
      continue
    }
    if (!replaced) {
      next.push(step)
      replaced = true
    }
  }
  if (!replaced) {
    next.push(step)
  }
  processingSteps.value = next
}

function addExistingOption(option: ApplicationSourceRunOption) {
  const step = appendProcessingStepFromOption(option)
  if (!step) {
    Message.info('这个步骤已经在应用里。')
    return
  }
  void hydrateProcessingStepSkillText(step, { silent: true, persist: true })
  Message.success('已加入文档应用。')
}

function appendProcessingStepFromOption(option: ApplicationSourceRunOption) {
  const exists = processingSteps.value.some((item) => item.runOption?.runId === option.runId)
  if (exists) return null
  const step = buildVerifiedProcessingStep(option)
  processingSteps.value = [
    ...processingSteps.value,
    step,
  ]
  return step
}

function buildVerifiedProcessingStep(option: ApplicationSourceRunOption): ProcessingStepDraft {
  return {
    id: `verified:${option.kind}:${option.runId}`,
    kind: option.kind,
    status: 'verified',
    dataTypeName: option.skillName || option.title,
    goal: option.summary,
    expectedOutput: option.resultPreview,
    sourceTitle: option.title,
    sourceScope: option.pageNo ? `第 ${option.pageNo} 页 · 运行时动态匹配` : '运行时动态匹配',
    skillText: '',
    skillName: option.skillName || option.title,
    errors: [],
    model: '',
    runOption: option,
  }
}

function hydrateProcessingStepsFromContext() {
  const context = applicationDraftContext.value
  if (!context || processingSteps.value.length) return
  const parseOptions = context.parseOptions
  const operationOptions = context.operationOptions.filter((item) => context.defaultOperationOptionIds.includes(item.id))
  const options = [...parseOptions, ...operationOptions]
  if (!options.length) return
  const steps = options.map(buildVerifiedProcessingStep)
  processingSteps.value = steps
  steps.forEach((step) => {
    void hydrateProcessingStepSkillText(step, { silent: true, persist: true })
  })
}

function hydrateProcessingStepsFromApplication(application: ApplicationAsset) {
  applicationName.value = application.name || applicationName.value
  savedApplication.value = application
  editingApplication.value = application
  const steps = application.steps
    .slice()
    .sort((left, right) => left.stepOrder - right.stepOrder)
    .map(processingStepFromApplicationStep)
  processingSteps.value = steps
  currentDraft.value = steps[0] ?? null
}

function processingStepFromApplicationStep(step: ApplicationStepDefinition): ProcessingStepDraft {
  const semanticLocator = semanticLocatorFromApplicationStep(step)
  const templateSample = templateSampleFromApplicationStep(step)
  const sampleSource = sampleSourceFromApplicationStep(step, semanticLocator)
  const runOption = runOptionFromApplicationStep(step)
  const dataTypeName = step.skillName || outputSummaryText(step) || defaultStepName(step.kind, '')
  return {
    id: `application:${step.id}`,
    kind: step.kind,
    status: 'verified',
    dataTypeName,
    locatorInstruction: String(semanticLocator?.locatorInstruction || ''),
    goal: String(step.snapshot.promptSnapshot || step.sourceSummary || ''),
    expectedOutput: String(step.snapshot.resultPreview || outputSummaryText(step) || ''),
    sourceTitle: sampleSource?.title || step.skillName,
    sourceScope: sampleSource?.sourceScope || (step.snapshot.sourcePageNo ? `第 ${step.snapshot.sourcePageNo} 页 · 样例` : '样例来源'),
    skillText: skillTextFromApplicationStep(step),
    skillName: step.skillName || defaultStepName(step.kind, dataTypeName),
    errors: [],
    model: String(step.outputSummary?.model || ''),
    sampleSource,
    sampleExtraction: normalizePersistedSampleExtraction(templateSample.sampleExtraction),
    sampleProcessing: normalizePersistedSampleProcessing(templateSample.sampleProcessing),
    skillDevelopment: normalizePersistedSkillDevelopment(templateSample.skillDevelopment),
    semanticLocator: semanticLocator || sampleSource?.locator,
    runOption,
    applicationStep: step,
  }
}

function runOptionFromApplicationStep(step: ApplicationStepDefinition): ApplicationSourceRunOption {
  const runId = step.sourceRunId || step.snapshot.runId || step.id
  return {
    id: `${step.kind}:application:${runId}`,
    kind: step.kind,
    runId,
    skillId: step.skillId,
    skillVersion: step.skillVersion,
    skillName: step.skillName,
    executor: step.executor,
    pageNo: step.snapshot.sourcePageNo ?? null,
    title: step.skillName,
    summary: step.sourceSummary || outputSummaryText(step) || step.snapshot.resultPreview || step.skillName,
    createdAt: null,
    promptSnapshot: step.snapshot.promptSnapshot || skillTextFromApplicationStep(step),
    configSnapshot: step.configSnapshot || step.snapshot.configSnapshot || {},
    inputMapping: step.snapshot.inputMapping || [],
    outputAlias: step.outputAlias || `step_${step.stepOrder}`,
    resultPreview: step.snapshot.resultPreview || outputSummaryText(step),
    targetMapping: step.snapshot.targetMapping ?? null,
    recommended: false,
  }
}

function semanticLocatorFromApplicationStep(step: ApplicationStepDefinition) {
  const refs = plainRecord(step.dependencyRefs)
  const dependencyLocator = plainRecord(refs.semanticLocator)
  const snapshotLocator = plainRecord(step.snapshot.semanticLocator)
  const locator = Object.keys(dependencyLocator).length ? dependencyLocator : snapshotLocator
  return Object.keys(locator).length ? cloneJson(locator) as Record<string, unknown> : null
}

function templateSampleFromApplicationStep(step: ApplicationStepDefinition) {
  const snapshotSample = plainRecord(step.snapshot.templateSample)
  if (Object.keys(snapshotSample).length) return snapshotSample
  const refs = plainRecord(step.dependencyRefs)
  return plainRecord(refs.templateSample)
}

function sampleSourceFromApplicationStep(
  step: ApplicationStepDefinition,
  semanticLocator: Record<string, unknown> | null,
): SampleSource | undefined {
  const templateSample = templateSampleFromApplicationStep(step)
  const persistedSource = normalizePersistedSampleSource(templateSample.sampleSource)
  if (persistedSource) {
    return {
      ...persistedSource,
      locator: semanticLocator || persistedSource.locator,
    }
  }
  const locatedSource = plainRecord(semanticLocator?.locatedSource)
  if (Object.keys(locatedSource).length) {
    return normalizeLocatedSampleSource(locatedSource as unknown as SkillSampleLocateAndExtractResponse['locatedSource'], semanticLocator || {})
  }
  return {
    mode: step.kind === 'extraction' ? 'tree' : 'target',
    kind: step.kind,
    title: step.skillName || `步骤 ${step.stepOrder}`,
    summary: step.sourceSummary || outputSummaryText(step),
    sourceScope: step.snapshot.sourcePageNo ? `第 ${step.snapshot.sourcePageNo} 页 · 样例` : '样例来源',
    sourceText: '',
    pageNo: step.snapshot.sourcePageNo ?? null,
    pageIndex: step.snapshot.sourcePageNo ? pageIndexFromPageNo(step.snapshot.sourcePageNo) : null,
    targetIds: step.snapshot.targetMapping?.targetIds ?? [],
    locator: semanticLocator || undefined,
  }
}

function skillTextFromApplicationStep(step: ApplicationStepDefinition) {
  const snapshot = plainRecord(step.skillSnapshot)
  return String(
    snapshot.skillText
    || snapshot.skillMarkdown
    || snapshot.markdown
    || snapshot.prompt
    || snapshot.content
    || step.snapshot.promptSnapshot
    || '',
  )
}

function outputSummaryText(step: ApplicationStepDefinition) {
  const summary = plainRecord(step.outputSummary)
  return String(summary.summary || summary.text || summary.message || step.snapshot.resultPreview || '').trim()
}

async function removeProcessingStep(id: string) {
  processingSteps.value = processingSteps.value.filter((item) => item.id !== id)
  if (currentDraft.value?.id === id) {
    currentDraft.value = null
  }
  await deleteProcessingStepDraft(id)
}

function updateCurrentDraftSkillText(value: string) {
  const draft = currentDraft.value
  if (!draft) return
  const updated: ProcessingStepDraft = {
    ...draft,
    skillText: value,
  }
  currentDraft.value = updated
  processingSteps.value = processingSteps.value.map((item) => (item.id === updated.id ? updated : item))
}

function updateCurrentDraftLocatorSkillText(value: string) {
  const draft = currentDraft.value
  if (!draft) return
  const updated: ProcessingStepDraft = {
    ...draft,
    semanticLocator: {
      ...plainRecord(draft.semanticLocator),
      locatorSkillText: value,
      source: 'workshop_editor',
    },
  }
  currentDraft.value = updated
  processingSteps.value = processingSteps.value.map((item) => (item.id === updated.id ? updated : item))
}

async function saveCurrentDraftEdit() {
  const draft = currentDraft.value
  if (!draft) return
  const normalizedSkillText = draft.skillText.trim()
    ? ensureSkillMarkdownFrontmatter(draft)
    : draft.skillText
  const draftToSave: ProcessingStepDraft = normalizedSkillText !== draft.skillText.trim()
    ? {
        ...draft,
        skillText: normalizedSkillText,
        skillName: extractSkillName(normalizedSkillText) || draft.skillName,
      }
    : draft
  if (draftToSave !== draft) {
    currentDraft.value = draftToSave
    upsertProcessingStep(draftToSave)
  }
  const saved = await saveProcessingStepDraft(draftToSave)
  if (saved) {
    Message.success('SKILL 修改已保存。')
  }
}

function openCurrentDraftSkillEditor() {
  const draft = currentDraft.value
  if (!draft) {
    Message.warning('请先生成或选择一个处理步骤。')
    return
  }
  skillEditorVisible.value = true
}

async function saveCurrentDraftLocatorSkill() {
  const draft = currentDraft.value
  if (!draft) return
  const saved = await saveProcessingStepDraft(draft)
  if (saved) {
    Message.success('定位 Skill 修改已保存。')
  }
}

async function saveAndTestCurrentDraft() {
  const draft = currentDraft.value
  if (!draft) return
  const saved = await saveProcessingStepDraft(draft)
  if (!saved) return
  await saveAndRunCurrentStep()
}

async function addRecommendedSteps() {
  await loadApplicationContext({ includeRunDetails: true })
  const context = applicationDraftContext.value
  if (!context) return
  const parse = context.parseOptions.find((item) => item.id === context.defaultParseOptionId)
  const operations = context.operationOptions.filter((item) => context.defaultOperationOptionIds.includes(item.id))
  if (!parse && !operations.length) {
    Message.info('当前任务还没有可加入应用的已跑通结果。')
    return
  }
  if (parse) addExistingOption(parse)
  operations.forEach(addExistingOption)
}

function buildApplicationPayload(): ApplicationDraftPayload | null {
  const context = applicationDraftContext.value
  if (!context) {
    Message.warning('当前任务上下文不可用。')
    return null
  }
  const draftIssue = currentDraftPublishIssue()
  if (draftIssue) {
    Message.warning(draftIssue)
    return null
  }
  const options = verifiedSteps.value
    .map((item) => item.runOption)
    .filter((item): item is ApplicationSourceRunOption => Boolean(item))
  const extractionOptions = options.filter((item) => item.kind === 'extraction')
  const operationOptions = options.filter((item) => item.kind === 'operation')
  if (!extractionOptions.length) {
    Message.warning('保存应用前至少需要一个已验证的数据提取步骤。')
    return null
  }
  const orderedOptions = [...extractionOptions, ...operationOptions]
  const steps = orderedOptions.map((option, index) => buildStepDefinition(option, index + 1))
  const existing = editingApplication.value
  const sampleContext = buildSkillSampleContext(activeSource.value)
  return {
    applicationId: existing?.applicationId,
    scope: existing?.scope || 'private',
    name: applicationName.value.trim() || existing?.name || context.suggestedName,
    summary: existing?.summary || buildApplicationSummary(orderedOptions),
    documentType: existing?.documentType || context.suggestedDocumentType,
    scenario: existing?.scenario || context.suggestedScenario,
    coverText: existing?.coverText || `用样例材料沉淀 ${steps.length} 个可复用处理步骤`,
    releaseNotes: existing?.releaseNotes || [
      '应用来源：样例材料 + DocParser 识别结果 + AI 生成处理步骤。',
      '运行方式：新材料上传后自动解析，再按内容特征选择步骤和目标范围。',
      '复核策略：低置信度、缺字段和异常冲突进入人工确认。',
    ].join('\n'),
    sourceTask: existing?.sourceTask || context.sourceTask,
    sampleContext,
    steps,
    finalOutputAlias: steps[steps.length - 1]?.outputAlias || 'final_output',
  }
}

async function handleSaveApplication(action: 'draft' | 'published') {
  const hasFullSteps = await ensureFullProcessingStepsForPublish()
  if (!hasFullSteps) return
  const payload = buildApplicationPayload()
  if (!payload) return

  saveLoading.value = true
  lastPlan.value = null
  try {
    let result: ApplicationAsset
    if (editingApplicationId.value) {
      const updated = await updateApplicationDetail(editingApplicationId.value, {
        scope: payload.scope,
        name: payload.name,
        summary: payload.summary,
        documentType: payload.documentType,
        scenario: payload.scenario,
        coverText: payload.coverText,
        releaseNotes: payload.releaseNotes,
        steps: payload.steps,
      })
      result = action === 'published'
        ? await publishApplicationDetail(editingApplicationId.value, { setAsDefault: true })
        : updated
    } else {
      result = action === 'published'
        ? await publishApplication(payload)
        : await saveApplicationDraft(payload)
    }
    editingApplication.value = result
    savedApplication.value = result
    Message.success(action === 'published' ? '文档应用已发布。' : '文档应用草稿已保存。')
    if (action === 'published' && taskId.value) {
      const runnableVersion = result.defaultVersion || result.latestPublishedVersion || result.resolvedVersion || result.version
      if (runnableVersion && runnableVersion !== 'draft') {
        try {
          lastPlan.value = await planApplicationRun(result.applicationId, {
            taskId: taskId.value,
            version: runnableVersion,
          })
          if (lastPlan.value.status === 'ready') {
            Message.success('运行计划已生成，定位通过。')
          } else {
            Message.warning(lastPlan.value.status === 'blocked'
              ? '应用已发布，但当前样例运行计划被定位门禁阻断。'
              : '应用已发布，但当前样例运行计划需要复核后再执行。')
          }
        } catch (error) {
          Message.warning(error instanceof Error
            ? `应用已发布，但运行计划生成失败：${error.message}`
            : '应用已发布，但运行计划生成失败。')
        }
      }
    } else if (action === 'published') {
      Message.info('应用已发布；当前使用应用内样板快照，已跳过样例任务运行计划。')
    }
  } catch (error) {
    Message.error(error instanceof Error ? error.message : (action === 'published' ? '应用发布失败。' : '应用保存失败。'))
  } finally {
    saveLoading.value = false
  }
}

function buildStepDefinition(option: ApplicationSourceRunOption, stepOrder: number): ApplicationStepDefinition {
  const draft = processingSteps.value.find((item) => item.runOption?.runId === option.runId)
  const sourceStep = draft?.applicationStep
  const semanticLocator = semanticLocatorForRunOption(option)
  const templateSample = buildTemplateSampleSnapshot(draft)
  const sourceTaskId = sampleRequestTaskId()
  const nextSnapshot = {
    ...(sourceStep?.snapshot || {}),
    runId: option.runId,
    promptSnapshot: draft?.skillText || option.promptSnapshot,
    configSnapshot: option.configSnapshot,
    inputMapping: option.inputMapping,
    targetMapping: option.targetMapping,
    resultPreview: option.resultPreview,
    sourceTaskId,
    sourcePageNo: option.pageNo,
    semanticLocator,
    templateSample,
  }
  if (sourceStep) {
    return {
      ...sourceStep,
      kind: option.kind,
      stepOrder,
      skillId: option.skillId,
      skillVersion: option.skillVersion,
      skillName: option.skillName,
      executor: option.executor,
      outputAlias: option.outputAlias || sourceStep.outputAlias || `${option.kind}_${stepOrder}`,
      sourceSummary: option.summary,
      snapshot: nextSnapshot,
      sourceRunId: sourceStep.sourceRunId || option.runId,
      configSnapshot: sourceStep.configSnapshot || option.configSnapshot,
      skillSnapshot: {
        ...(sourceStep.skillSnapshot || {}),
        skillText: draft?.skillText || skillTextFromApplicationStep(sourceStep),
      },
      dependencyRefs: {
        ...(sourceStep.dependencyRefs || {}),
        semanticLocator,
        templateSample,
      },
      outputSummary: sourceStep.outputSummary,
    }
  }
  return {
    id: `step-${stepOrder}-${option.kind}-${option.runId}`,
    kind: option.kind,
    stepOrder,
    skillId: option.skillId,
    skillVersion: option.skillVersion,
    skillName: option.skillName,
    executor: option.executor,
    outputAlias: option.outputAlias || `${option.kind}_${stepOrder}`,
    sourceSummary: option.summary,
    snapshot: nextSnapshot,
    dependencyRefs: {
      ...(semanticLocator ? { semanticLocator } : {}),
      templateSample,
    },
  }
}

function semanticLocatorForRunOption(option: ApplicationSourceRunOption) {
  const step = processingSteps.value.find((item) => item.runOption?.runId === option.runId)
  return cloneJson(step?.semanticLocator || step?.sampleSource?.locator || null) as Record<string, unknown> | null
}

function buildTemplateSampleSnapshot(draft: ProcessingStepDraft | undefined): Record<string, unknown> {
  const existing = plainRecord(draft?.applicationStep?.snapshot.templateSample)
  if (Object.keys(existing).length && !detail.value) {
    return cloneJson(existing) as Record<string, unknown>
  }
  const taskDetail = detail.value
  const sourceTask = applicationDraftContext.value?.sourceTask
  return {
    protocol: 'application_template_sample_v1',
    capturedAt: new Date().toISOString(),
    sourceTask: sourceTask ? cloneJson(sourceTask) : null,
    document: taskDetail?.document ? cloneJson(taskDetail.document) : plainRecord(existing.document),
    documentTree: taskDetail?.documentTree ? cloneJson(taskDetail.documentTree) : plainRecord(existing.documentTree),
    pages: taskDetail?.pages ? cloneJson(taskDetail.pages) : (Array.isArray(existing.pages) ? cloneJson(existing.pages) : []),
    pageResults: taskDetail?.pageResults ? cloneJson(taskDetail.pageResults) : (Array.isArray(existing.pageResults) ? cloneJson(existing.pageResults) : []),
    sampleSource: cloneJson(draft?.sampleSource || plainRecord(existing.sampleSource)),
    semanticLocator: cloneJson(draft?.semanticLocator || plainRecord(existing.semanticLocator)),
    sampleExtraction: cloneJson(draft?.sampleExtraction || plainRecord(existing.sampleExtraction)),
    sampleProcessing: cloneJson(draft?.sampleProcessing || plainRecord(existing.sampleProcessing)),
    skillDevelopment: cloneJson(draft?.skillDevelopment || plainRecord(existing.skillDevelopment)),
  }
}

function buildSkillInstruction(source: SampleSource) {
  const scopePolicy = (() => {
    if (source.mode === 'tree') {
      return '文档树节点是样例结构，请利用节点标题、层级、子节点和内容形态生成动态适用条件；页码只作为证据，不得作为匹配条件。'
    }
    if (source.mode === 'page') {
      return '当前页完整 OCR 内容只是样例证据，不能把 Skill 写成只处理这一页；同类页面或同类内容结构也要能识别。'
    }
    if (source.mode === 'selection') {
      return '选中内容只是样例片段，同类内容出现在其他页或跨页时也要能识别。'
    }
    if (source.mode === 'target') {
      return '已有提取结果只是样例输入，后续要能处理同类结构化数据。'
    }
    return '整份材料用于学习文档结构，后续运行时要自动找到对应内容范围。'
  })()
  const dynamicRule = [
    '不要写死页码；页码只能作为样例证据。',
    scopePolicy,
    '请根据标题、表头、字段、上下文和内容特征描述动态适用条件。',
    '输出必须可复核，默认只保留来源页码等轻量来源字段。',
    '不要编造样例中不存在的数据。',
  ].join('\n')
  const explicitGoal = userProcessingGoalText()
  const explicitExpectedOutput = userExpectedOutputText()
  const goalLabel = source.kind === 'extraction' && explicitGoal ? '用户抽取要求' : '处理目标'
  const outputLabel = source.kind === 'extraction' && explicitExpectedOutput ? '用户输出要求' : '输出要求'
  const lines = [
    `数据类型：${effectiveDataTypeName.value}`,
    `样例来源：${source.title}`,
    `样例范围：${source.sourceScope}`,
    `${goalLabel}：${explicitGoal || (source.kind === 'extraction' ? `提取“${effectiveDataTypeName.value}”对应的数据内容。` : `基于“${effectiveDataTypeName.value}”样例数据完成业务处理。`)}`,
  ]
  if (explicitExpectedOutput) {
    lines.push(`${outputLabel}：${explicitExpectedOutput}`)
  }
  lines.push(
    '',
    '生成要求：',
    dynamicRule,
  )
  return lines.join('\n')
}

function buildApplicationSummary(options: ApplicationSourceRunOption[]) {
  const extractionCount = options.filter((item) => item.kind === 'extraction').length
  const operationCount = options.filter((item) => item.kind === 'operation').length
  if (!operationCount) {
    return `基于样例材料制作的文档应用，包含 ${extractionCount} 个数据提取步骤。`
  }
  return `基于样例材料制作的文档应用，包含 ${extractionCount} 个数据提取步骤和 ${operationCount} 个业务处理步骤。`
}

function defaultDataTypeName(source: SampleSource) {
  if (source.mode === 'target' && selectedTarget.value?.label) return selectedTarget.value.label
  if (source.mode === 'tree' && selectedTreeNode.value?.label) return cleanLabel(selectedTreeNode.value.label)
  if (source.mode === 'selection' && selectedRange.value) return cleanLabel(selectedRange.value.label)
  if (source.mode === 'page') return '当前页完整内容'
  if (source.mode === 'document') return '整份材料'
  return activePage.value?.title || '当前页内容'
}

function cleanLabel(value: string) {
  return value.replace(/^(文本|表格|列表|标题|图片)\s*·\s*/, '').trim() || value
}

type SkillFrontmatterSource = Pick<ProcessingStepDraft, 'kind' | 'skillText'> & {
  id?: string
  dataTypeName?: string
  skillName?: string
  skillDevelopment?: SkillDevelopmentAsset
  sampleExtraction?: ProcessingStepDraft['sampleExtraction']
  sampleProcessing?: ProcessingStepDraft['sampleProcessing']
  draftId?: string
}

function ensureSkillMarkdownFrontmatter(source: SkillFrontmatterSource) {
  const body = String(source.skillText || '').trim()
  if (!body) return ''
  if (body.startsWith('---')) return body

  const seed = source.draftId || source.id || source.dataTypeName || source.skillName || body
  const name = source.skillName || defaultStepName(source.kind, source.dataTypeName || '样例数据')
  const id = buildGeneratedSkillId(source.kind, seed)
  const frontmatter = source.kind === 'operation'
    ? [
        '---',
        `id: ${id}`,
        'version: "1.0.0"',
        `name: ${yamlString(name)}`,
        'kind: operation',
        'category: business_operation',
        'targetTypes: [field, table, structured_object, record_collection, record, output]',
        'executor: llm_structured',
        `resultKind: ${resolveOperationResultKind(source)}`,
        'renderer: auto',
        'outputSchema:',
        '  type: object',
        '---',
      ]
    : [
        '---',
        `id: ${id}`,
        'version: "1.0.0"',
        `name: ${yamlString(name)}`,
        'kind: extraction',
        'category: extraction',
        'enabled: true',
        'sourceTypes: [text, html_table]',
        'executor: llm_structured',
        'input:',
        '  builder: page_compact',
        `renderer: ${resolveExtractionRenderer(resolveExtractionOutputType(source))}`,
        'output:',
        `  type: ${resolveExtractionOutputType(source)}`,
        '---',
      ]
  return `${frontmatter.join('\n')}\n\n${body}`
}

function buildGeneratedSkillId(kind: ApplicationStepKind, seed: string) {
  const prefix = kind === 'operation' ? 'process' : 'extract'
  const normalized = String(seed || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 36)
    || 'sample'
  return `${prefix}_${normalized}_${hashText(seed).slice(0, 8)}`
}

function hashText(value: string) {
  let hash = 0
  const text = String(value || '')
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
}

function yamlString(value: string) {
  return JSON.stringify(String(value || ''))
}

function resolveExtractionOutputType(source: SkillFrontmatterSource) {
  const contract = plainRecord(source.skillDevelopment?.outputContractSummary || source.skillDevelopment?.runtimeContract)
  const direct = pickKnownExtractionOutputType([
    contract.outputType,
    contract.type,
    contract.resultType,
    contract.renderer,
  ])
  if (direct) return direct

  const outputs = source.sampleExtraction?.result.outputs || []
  const outputTypes = outputs
    .map((item) => pickKnownExtractionOutputType([item.type]))
    .filter((item): item is string => Boolean(item))
  return outputTypes[0] || 'custom'
}

function pickKnownExtractionOutputType(values: unknown[]) {
  const allowed = new Set(['field_list', 'data_table', 'record_collection', 'kv_table', 'kv_record_table', 'custom'])
  for (const value of values) {
    const text = String(value || '').trim()
    if (allowed.has(text)) return text
  }
  return ''
}

function resolveExtractionRenderer(outputType: string) {
  if (outputType === 'field_list') return 'field_list'
  if (outputType === 'record_collection') return 'nested_records'
  if (outputType === 'data_table' || outputType === 'kv_table' || outputType === 'kv_record_table') return 'data_table'
  return 'auto'
}

function resolveOperationResultKind(source: SkillFrontmatterSource) {
  const contract = plainRecord(source.skillDevelopment?.outputContractSummary || source.skillDevelopment?.runtimeContract)
  const allowed = new Set(['decision', 'object', 'table', 'text'])
  const candidates = [
    contract.resultKind,
    contract.outputType,
    contract.type,
    source.sampleProcessing?.result.resultKind,
  ]
  for (const value of candidates) {
    const text = String(value || '').trim()
    if (allowed.has(text)) return text
  }
  return 'object'
}

function extractSkillName(skillText: string) {
  const match = skillText.match(/^\s*name\s*:\s*(.+)$/m)
  return match?.[1]?.trim().replace(/^["']|["']$/g, '') || ''
}

function buildTargetSourceText(target: OperationTarget) {
  return [
    `对象名称：${target.label}`,
    `对象类型：${target.type}`,
    `内容：${target.valueText || target.excerpt || ''}`,
    `表头：${(target.headers || []).join(' / ')}`,
    `结构化数据：${safeJson(target.data)}`,
  ].filter(Boolean).join('\n')
}

function buildDocumentSourceText() {
  const pages = detail.value?.pages ?? []
  return pages.slice(0, 8).map((page) => buildPageSourceText(page, 4000)).join('\n\n')
}

function buildTreeSourceText(node: DocumentTreeSource) {
  const lines = [
    `节点类型：${node.typeLabel || node.type}`,
    `节点标题：${node.label}`,
    node.meta ? `节点层级：${node.meta}` : '',
    node.sourceScope ? `证据页码：${node.sourceScope}` : '',
    node.preview ? `节点预览：${node.preview}` : '',
    node.sourceText ? `节点文本：${node.sourceText}` : '',
  ].filter(Boolean)
  const matchedRange = findBestRangeForTreeNode(node)
  if (matchedRange?.text) {
    lines.push(`匹配内容：${matchedRange.text}`)
  }
  const pageSet = new Set(node.pageNos)
  const pageTableRanges = contentRanges.value
    .filter((range) => pageSet.has(range.pageNo) && isTableRangeKind(range.kind) && range.text)
    .slice(0, 4)
  for (const range of pageTableRanges) {
    lines.push(`同页表格：${range.label}\n${range.text}`)
  }
  return lines.join('\n').slice(0, 5000)
}

function buildTreeNodePath(node: DocumentTreeSource) {
  return [
    node.typeLabel || node.type,
    ...String(node.meta || '')
      .split(/[>\/·｜|]/)
      .map((item) => item.trim())
      .filter(Boolean),
    node.label,
  ].filter((item, index, items) => item && items.indexOf(item) === index)
}

function buildPageRange(pageNos: number[]) {
  const pages = pageNos.filter((pageNo) => Number.isFinite(pageNo))
  if (!pages.length) return undefined
  return {
    start: Math.min(...pages),
    end: Math.max(...pages),
  }
}

function buildTreeContentRefs(node: DocumentTreeSource) {
  return node.locations.map((location) => ({
    treeNodeId: node.id,
    pageNo: location.pageNo,
    bbox: location.bbox,
  }))
}

function sampleRequestSourceFields(source: SampleSource) {
  return {
    treeNodeId: source.treeNodeId,
    treePath: source.treePath ?? [],
    pageRange: source.pageRange ?? undefined,
    contentRefs: source.contentRefs ?? [],
  }
}

function pageIndexFromPageNo(pageNo: number) {
  const page = detail.value?.pages.find((item) => item.pageNo === pageNo)
  return page?.pageIndex ?? Math.max(0, pageNo - 1)
}

</script>

<template>
  <div class="application-workbench">
    <ApplicationWorkshopHeader
      v-model:application-name="applicationName"
      v-model:upload-customer-id="uploadCustomerId"
      :document-title="detail?.document.fileName || ''"
      :document-meta="isParseRunning ? parseStatusText : `${pageCount} pages` || ''"
      :save-loading="saveLoading"
      :can-save-application="canSaveApplication"
      :saved="Boolean(savedApplication)"
      :upload-customer-options="uploadCustomerOptions"
      :uploading-sample="sampleUploadBusy"
      :task-loading="taskLoading"
      :store-loading="store.loading"
      :can-upload-sample="!uploadCustomerLoading"
      :is-editing-application="isEditingApplication"
      @save-draft="handleSaveApplication('draft')"
      @publish="handleSaveApplication('published')"
      @upload-sample="openUploadPicker"
      @back-to-market="router.push({ name: 'admin-applications' })"
      @back-to-detail="router.push({ name: 'admin-applications-detail', params: { applicationId: editingApplicationId } })"
    />
    <input
      ref="uploadInputRef"
      class="application-workbench__file-input"
      type="file"
      accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff,.doc,.docx"
      @change="handleUploadChange"
    />

    <section v-if="taskLoading" class="application-workbench__loading">
      <a-spin />
      <span>{{ loadingSampleMaterialText }}</span>
    </section>

    <section v-else-if="!detail" class="application-workbench__loading application-workbench__asset-missing">
      <a-empty :description="templateAssetIssue?.title || '没有读取到样例材料。'" />
      <p>{{ templateAssetIssue?.description || '请重新上传样例材料后继续编辑模板资产。' }}</p>
      <small v-if="templateAssetIssue?.sourceTaskId">来源任务：{{ templateAssetIssue.sourceTaskId }}</small>
      <div class="application-workbench__asset-actions">
        <a-button
          type="primary"
          :loading="sampleUploadBusy"
          :disabled="uploadCustomerLoading"
          @click="openUploadPicker"
        >
          上传样例并 OCR
        </a-button>
        <a-button
          v-if="isEditingApplication"
          @click="router.push({ name: 'admin-applications-detail', params: { applicationId: editingApplicationId } })"
        >
          返回应用详情
        </a-button>
      </div>
    </section>

    <section v-else-if="isParseRunning" class="application-workbench__loading application-workbench__loading--parse">
      <a-spin />
      <span>{{ parseStatusText }}</span>
      <small>OCR 完成后会自动载入识别结果、文档树和应用制作上下文。</small>
      <a-button size="small" :loading="contextLoading" @click="refreshParseStatus">刷新状态</a-button>
    </section>

    <DocumentReviewWorkspace
      v-else
      v-model:active-tab="parsePanelActiveTab"
      layout="fixed"
      height="calc(100vh - 106px)"
      :detail="detail"
      :current-page-index="store.currentPageIndex"
      :selected-block-id="store.selectedBlockId"
      :content-ranges="previewContentRanges"
      :selected-range-id="selectedRangeId"
      overlay-mode="ranges"
      data-title="DocParser 内容"
      :data-subtitle="`${activePageRanges.length} 个内容范围 · ${activeTargets.length} 个提取对象`"
      :page="store.activePage"
      :document-tree="detail?.documentTree ?? null"
      :result="parsePanelResult"
      :result-status="parsePanelResultStatus"
      :operation-targets="activeTargets"
      :selected-target-id="store.selectedTargetId"
      :selected-tree-node-id="selectedTreeNode?.id || ''"
      @change-page="store.setCurrentPage"
      @select-block="handleSelectBlock"
      @select-range="handleSelectRange"
      @select-target="handleSelectTarget"
      @select-tree-node="handleSelectTreeNode"
    >
      <template #data-actions>
        <a-button size="mini" @click="openCurrentPageStepDrawer">用当前页生成</a-button>
        <a-button
          size="mini"
          :loading="restartingParse"
          :disabled="isParseRunning || sampleUploadBusy"
          @click="rerunCurrentParse"
        >
          重新识别当前文件
        </a-button>
        <a-button size="mini" :loading="contextLoading" @click="() => loadApplicationContext()">刷新</a-button>
      </template>

      <template #side>
        <ApplicationStepManager
          v-model:application-name="applicationName"
          :steps="processingSteps"
          :can-save="canSaveApplication"
          :save-loading="saveLoading"
          :context-loading="contextLoading"
          :context-error="contextError"
          :saved-application="savedApplication"
          :plan-summary="visiblePlanSummary"
          @create="openNewStepDrawer"
          @edit="openEditStepDrawer"
          @duplicate="duplicateProcessingStep"
          @remove="removeProcessingStep"
          @add-existing="addRecommendedSteps"
          @save-draft="handleSaveApplication('draft')"
          @publish="handleSaveApplication('published')"
        />
      </template>
    </DocumentReviewWorkspace>

    <ProcessingStepDrawer
      v-model:source-mode="sourceMode"
      v-model:data-type-name="dataTypeName"
      v-model:locator-instruction="locatorInstruction"
      v-model:processing-goal="processingGoal"
      v-model:expected-output="expectedOutput"
      :visible="stepDrawerVisible"
      :active-source="activeSource"
      :default-data-type-name="defaultDataTypeName(activeSource)"
      :effective-goal="effectiveGoal"
      :effective-expected-output="effectiveExpectedOutput"
      :current-draft="currentDraft"
      :generating="generating"
      :sample-extracting="sampleExtracting"
      :sample-processing="sampleProcessing"
      :sample-extract-disabled="sampleExtractDisabled"
      :sample-extract-disabled-reason="sampleExtractDisabledReason"
      :sample-extract-apply-url="sampleExtractApplyUrl"
      :running-step="runningStep"
      :step-run-state="stepRunState"
      :prototype-creating="prototypeCreating"
      :prototype-optimization-enabled="prototypeOptimizationEnabled"
      :can-use-tree="Boolean(selectedTreeNode)"
      :can-use-selection="Boolean(selectedRange)"
      :can-use-target="Boolean(selectedTarget)"
      @close="stepDrawerVisible = false"
      @generate="generateProcessingStep"
      @sample-extract="sampleExtractLocatedProcessingStep"
      @select-locate-candidate="locateAndExtractProcessingStep"
      @confirm-sample-generate="confirmSampleExtractionAndGenerateSkill"
      @update-sample-extraction-output="updateSampleExtractionOutput"
      @update-sample-processing-output="updateSampleProcessingOutput"
      @update-locator-skill-text="updateCurrentDraftLocatorSkillText"
      @open-skill-editor="openCurrentDraftSkillEditor"
      @create-prototype="createPrototypeFromCurrentStep"
      @save-locator-skill="saveCurrentDraftLocatorSkill"
      @save-run="saveAndRunCurrentStep"
    />

    <StepSkillEditorModal
      v-model:visible="skillEditorVisible"
      :draft="currentDraft"
      :running="runningStep"
      @update:skill-text="updateCurrentDraftSkillText"
      @save="saveCurrentDraftEdit"
      @save-and-test="saveAndTestCurrentDraft"
    />
  </div>
</template>

<style scoped>
.application-workbench {
  display: grid;
  gap: 6px;
  height: calc(100vh - 56px);
  min-width: 1180px;
  overflow: hidden;
  color: #111827;
  background: #eef3f8;
}

.application-workbench__file-input {
  display: none;
}

.application-workbench__loading {
  min-width: 0;
  border: 1px solid #d7dee8;
  background: #fff;
}

.application-workbench__loading {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 420px;
  color: #64748b;
}

.application-workbench__loading--parse {
  align-content: center;
  padding: 24px;
  text-align: center;
}

.application-workbench__loading--parse span {
  color: #0f172a;
  font-size: 16px;
  font-weight: 850;
}

.application-workbench__loading--parse small {
  max-width: 420px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.7;
}

.application-workbench__asset-missing {
  align-content: center;
  justify-items: center;
  padding: 32px;
  text-align: center;
}

.application-workbench__asset-missing p {
  max-width: 720px;
  margin: 0;
  color: #475569;
  font-size: 14px;
  line-height: 1.8;
}

.application-workbench__asset-missing small {
  color: #94a3b8;
  font-size: 12px;
}

.application-workbench__asset-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 8px;
}

</style>
