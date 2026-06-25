<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { computed, ref, watch } from 'vue'
import type {
  ProcessingStepDraft,
  SampleSource,
  SampleSourceMode,
} from '../types/applicationWorkshop'
import type { SkillSampleLocateCandidate, SkillSampleLocatedSource } from '../types/workbench'
import type { ExtractionOutputItem } from '../types/workbench'
import { t } from '../i18n'
import { translateStaticText } from '../i18n/staticText'
import SkillMarkdownEditor from './SkillMarkdownEditor.vue'

const props = defineProps<{
  visible: boolean
  sourceMode: SampleSourceMode
  activeSource: SampleSource
  dataTypeName: string
  locatorInstruction: string
  processingGoal: string
  expectedOutput: string
  defaultDataTypeName: string
  effectiveGoal: string
  effectiveExpectedOutput: string
  currentDraft: ProcessingStepDraft | null
  generating?: boolean
  sampleExtracting?: boolean
  sampleExtractDisabled?: boolean
  sampleExtractDisabledReason?: string
  sampleExtractApplyUrl?: string
  sampleProcessing?: boolean
  runningStep?: boolean
  stepRunState?: StepRunSyncState | null
  prototypeCreating?: boolean
  prototypeOptimizationEnabled?: boolean
  canUseTree: boolean
  canUseSelection: boolean
  canUseTarget: boolean
}>()

const emit = defineEmits<{
  close: []
  'update:sourceMode': [value: SampleSourceMode]
  'update:dataTypeName': [value: string]
  'update:locatorInstruction': [value: string]
  'update:processingGoal': [value: string]
  'update:expectedOutput': [value: string]
  generate: []
  sampleExtract: []
  confirmSampleGenerate: []
  updateSampleExtractionOutput: [value: string]
  updateSampleProcessingOutput: [value: string]
  updateLocatorSkillText: [value: string]
  openSkillEditor: []
  createPrototype: []
  saveLocatorSkill: []
  saveRun: []
  selectLocateCandidate: [candidateId: string]
}>()

type QuickIntent = {
  key: 'fields' | 'table' | 'records' | 'notes'
  label: string
  hint: string
  dataTypeName: string
  goal: string
  output: string
}

type DrawerTabKey = 'locate' | 'extract'
type ExtractSubTabKey = 'sample' | 'validation'
type LocatedModuleRow = {
  key: string
  title: string
  summary: string
  pages: string
  blockCount: number
  detailText: string
}
type StepRunSyncState = {
  draftId: string
  runId: string
  kind: 'extraction' | 'operation'
  status: 'starting' | 'running' | 'syncing' | 'completed' | 'failed' | 'needs_review'
  message: string
  resultPreview?: string
  validationErrors?: string[]
  detailStatus?: string
  updatedAt: string
}

const activeDrawerTab = ref<DrawerTabKey>('locate')
const activeExtractSubTab = ref<ExtractSubTabKey>('sample')
const locatorSkillModalVisible = ref(false)
const locatorModuleModalVisible = ref(false)
const locatorModuleModalTitle = ref('')
const locatorModuleModalMeta = ref('')
const locatorModuleModalText = ref('')

const sourceOptions = computed(() => [
  {
    mode: 'tree' as SampleSourceMode,
    label: t('workshop.sourceTreeNode'),
    description: t('workshop.sourceTreeNodeDescription'),
    disabled: !props.canUseTree,
  },
  {
    mode: 'page' as SampleSourceMode,
    label: t('workshop.sourceCurrentPage'),
    description: t('workshop.sourceCurrentPageDescription'),
    disabled: false,
  },
  {
    mode: 'document' as SampleSourceMode,
    label: t('workshop.sourceQueryDocumentTree'),
    description: t('workshop.sourceQueryDocumentTreeDescription'),
    disabled: false,
  },
  {
    mode: 'selection' as SampleSourceMode,
    label: t('workshop.sourceSelectedRange'),
    description: t('workshop.sourceSelectedRangeDescription'),
    disabled: !props.canUseSelection,
  },
  {
    mode: 'target' as SampleSourceMode,
    label: t('workshop.sourceExistingExtraction'),
    description: t('workshop.sourceExistingExtractionDescription'),
    disabled: !props.canUseTarget,
  },
])

const sourceNote = computed(() => {
  if (props.sourceMode === 'tree') return t('workshop.sourceTreeNote')
  if (props.sourceMode === 'page') return t('workshop.sourcePageNote')
  if (props.sourceMode === 'selection') return t('workshop.sourceSelectionNote')
  if (props.sourceMode === 'target') return t('workshop.sourceTargetNote')
  return t('workshop.sourceDocumentNote')
})

const quickIntents: QuickIntent[] = [
  {
    key: 'fields',
    label: '字段信息',
    hint: '姓名、编号、日期、主体、金额等一问一答字段。',
    dataTypeName: '基础信息',
    goal: '提取这类内容中的关键字段和值，例如编号、名称、日期、主体、金额等；字段缺失时保持为空，并保留来源证据。',
    output: '字段列表：字段名、字段值、来源页码。'
  },
  {
    key: 'table',
    label: '表格数据',
    hint: '信息概要、检测结果、订单明细等有行列关系的内容。',
    dataTypeName: '表格数据',
    goal: '把这类表格整理成结构化表格，保留表头、行列关系、合并单元格含义和来源证据。',
    output: '表格：表头、行数据、合并单元格说明、来源页码。'
  },
  {
    key: 'records',
    label: '记录列表',
    hint: '跨页明细、流水、贷款记录、查询记录等重复内容。',
    dataTypeName: '明细记录',
    goal: '把这类连续文本或列表整理成多条记录，每条记录拆出主体、时间、金额、状态、说明等可识别字段。',
    output: '记录集合：每条记录包含字段和值、来源页码；跨页连续时保持同一组记录。'
  },
  {
    key: 'notes',
    label: '说明/结论',
    hint: '备注、说明、异常提示、结论和复核建议。',
    dataTypeName: '说明记录',
    goal: '提取这类说明、备注、结论或异常提示，保留完整语义和来源证据，避免只截取片段。',
    output: '说明列表：主题、说明内容、影响或结论、来源页码。'
  },
]

const suggestedIntent = computed<QuickIntent>(() => {
  const text = [
    props.activeSource.title,
    props.activeSource.summary,
    props.defaultDataTypeName,
    props.activeSource.sourceText.slice(0, 2400),
  ].join(' ').toLowerCase()
  if (
    text.includes('表格') ||
    text.includes('table') ||
    text.includes('tablegrid') ||
    text.includes('表格内容') ||
    text.includes('| ---') ||
    text.includes('<table') ||
    text.includes('概要') ||
    text.includes('统计')
  ) {
    return quickIntents[1]
  }
  if (text.includes('记录') || text.includes('列表') || text.includes('明细') || text.includes('流水') || text.includes('订单')) {
    return quickIntents[2]
  }
  if (text.includes('说明') || text.includes('结论') || text.includes('备注') || text.includes('异常') || text.includes('提示')) {
    return quickIntents[3]
  }
  return quickIntents[0]
})

const suggestedDataTypeName = computed(() => {
  const value = props.defaultDataTypeName.trim()
  if (!value || ['当前页内容', '整份材料', '当前页样例', '当前页完整内容'].includes(value)) return suggestedIntent.value.dataTypeName
  if (value.length > 28) return suggestedIntent.value.dataTypeName
  return value
})

const guidedSummary = computed(() => {
  if (props.sourceMode === 'tree') return t('workshop.guidedTreeSummary')
  if (props.sourceMode === 'selection') return t('workshop.guidedSelectionSummary')
  if (props.sourceMode === 'document') return t('workshop.guidedDocumentSummary')
  if (props.sourceMode === 'target') return t('workshop.guidedTargetSummary')
  return t('workshop.guidedPageSummary')
})

const workflowKind = computed(() => props.currentDraft?.kind || props.activeSource.kind)
const isOperationWorkflow = computed(() => workflowKind.value === 'operation')
const isExtractionTemplate = computed(() => workflowKind.value === 'extraction')

const primaryActionLabel = computed(() => {
  if (isOperationWorkflow.value) return props.currentDraft?.sampleProcessing ? t('workshop.runProcessingAgain') : t('workshop.aiTrialProcessing')
  if (activeDrawerTab.value === 'extract') return props.currentDraft?.sampleExtraction ? t('workshop.runExtractionAgain') : t('workshop.aiTrialExtraction')
  return semanticLocator.value ? t('workshop.regenerateLocatorSkill') : t('workshop.generateLocatorSkill')
})

const primaryActionLoading = computed(() =>
  isExtractionTemplate.value ? Boolean(props.sampleExtracting) : Boolean(props.sampleProcessing),
)

const sampleExtraction = computed(() => props.currentDraft?.sampleExtraction)
const sampleProcessingDraft = computed(() => props.currentDraft?.sampleProcessing)
const skillDevelopment = computed(() => props.currentDraft?.skillDevelopment)
const activeSourceKey = computed(() => [
  workflowKind.value,
  props.activeSource.mode,
  props.activeSource.title,
  props.activeSource.sourceScope,
  props.activeSource.treeNodeId || '',
  props.activeSource.targetIds.join(','),
  props.currentDraft?.id || '',
].join('|'))
const drawerTabItems = computed(() => {
  if (isOperationWorkflow.value) {
    return [
      { key: 'locate' as DrawerTabKey, label: t('workshop.processingInput'), description: t('workshop.confirmProcessingObject') },
      { key: 'extract' as DrawerTabKey, label: t('workshop.sampleProcessing'), description: sampleProcessingDraft.value ? t('workshop.reviewProcessingResult') : t('workshop.waitingTrialProcessing') },
    ]
  }
  return [
    { key: 'locate' as DrawerTabKey, label: t('workshop.locatorSkill'), description: semanticLocator.value ? locatorStatusText.value : t('workshop.findContentRangeFirst') },
    { key: 'extract' as DrawerTabKey, label: t('workshop.extractionSkill'), description: extractTabDescription.value },
  ]
})
const semanticLocator = computed<Record<string, unknown> | null>(() => {
  const value = props.currentDraft?.semanticLocator || props.currentDraft?.sampleSource?.locator
  return value && typeof value === 'object' ? value as Record<string, unknown> : null
})
const locatorStatus = computed(() => String(semanticLocator.value?.status || ''))
const locatorCandidates = computed<SkillSampleLocateCandidate[]>(() => {
  const value = semanticLocator.value?.candidates
  return Array.isArray(value) ? value as SkillSampleLocateCandidate[] : []
})
const locatedSource = computed<SkillSampleLocatedSource | null>(() => {
  const value = semanticLocator.value?.locatedSource
  return value && typeof value === 'object' ? value as SkillSampleLocatedSource : null
})
const locatorQuery = computed(() => String(semanticLocator.value?.query || props.dataTypeName || ''))
const locatorReason = computed(() => {
  const result = semanticLocator.value?.locatorResult
  if (result && typeof result === 'object' && !Array.isArray(result)) {
    return String((result as Record<string, unknown>).reason || locatedSource.value?.locatorReason || '')
  }
  return String(locatedSource.value?.locatorReason || '')
})
const locatorProfile = computed<Record<string, unknown>>(() => {
  const value = semanticLocator.value?.locatorProfile
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
})
const locatorSkillText = computed(() => String(semanticLocator.value?.locatorSkillText || ''))
const hasLocatorSkill = computed(() => Boolean(locatorSkillText.value.trim()))
const currentSampleSourceText = computed(() => String(props.currentDraft?.sampleSource?.sourceText || '').trim())
const hasLocatedInput = computed(() => Boolean(locatedSource.value || currentSampleSourceText.value))
const sampleExtractBlocked = computed(() => Boolean(props.sampleExtractDisabled))
const sampleExtractBlockReason = computed(() => String(props.sampleExtractDisabledReason || '').trim())
const sampleExtractActionDisabled = computed(() => !hasLocatedInput.value || sampleExtractBlocked.value)
const locatorNeedsSelection = computed(() => Boolean(!hasLocatedInput.value && locatorCandidates.value.length))
const extractInputStatusText = computed(() => {
  if (locatedSource.value) return t('workshop.usingLocatedContent')
  if (currentSampleSourceText.value) return t('workshop.hasExtractableSampleContent')
  if (locatorNeedsSelection.value) return t('workshop.locatorCandidatePendingSelection')
  if (hasLocatorSkill.value) return t('workshop.locatorSkillSaved')
  return t('workshop.waitingLocation')
})
const sampleEmptyMessage = computed(() => {
  if (hasVerifiedRun.value) return t('workshop.currentStepVerifiedOutput')
  if (hasLocatedInput.value) return t('workshop.writePromptThenTrialExtract')
  if (locatorNeedsSelection.value) return t('workshop.locatorCandidateSelectionHint')
  if (hasLocatorSkill.value) return t('workshop.locatorSavedNoContentHint')
  if (semanticLocator.value) return t('workshop.locatorNoReliableContentHint')
  return t('workshop.generateLocatorFirstHint')
})
const sampleEmptyActionLabel = computed(() => {
  if (locatorNeedsSelection.value) return t('workshop.viewLocatorCandidates')
  if (hasLocatorSkill.value || semanticLocator.value) return t('workshop.backToLocateTab')
  return t('workshop.generateLocatorSkill')
})
const locatorPositiveTerms = computed(() => locatorProfileTerms('positiveTerms'))
const locatorNegativeTerms = computed(() => locatorProfileTerms('negativeTerms'))
const locatorExpectedTypes = computed(() => locatorProfileTerms('expectedObjectTypes'))
function locatorProfileTerms(key: string) {
  const values = locatorProfile.value[key]
  return Array.isArray(values) ? values.map((item) => String(item || '').trim()).filter(Boolean).slice(0, 8) : []
}

function candidateMatchedTerms(candidate: SkillSampleLocateCandidate): string[] {
  const payload = asRecord(candidate.payload)
  const values = Array.isArray(candidate.matchedTerms)
    ? candidate.matchedTerms
    : Array.isArray(payload.matchedTerms)
      ? payload.matchedTerms
      : []
  return values.map((item) => String(item || '').trim()).filter(Boolean).slice(0, 10)
}

function candidateMatchedWindows(candidate: SkillSampleLocateCandidate): Array<Record<string, unknown>> {
  const payload = asRecord(candidate.payload)
  const values = Array.isArray(candidate.matchedWindows)
    ? candidate.matchedWindows
    : Array.isArray(payload.matchedWindows)
      ? payload.matchedWindows
      : []
  return values.filter(isRecord).slice(0, 3)
}

function candidatePrimaryWindow(candidate: SkillSampleLocateCandidate): Record<string, unknown> {
  const topLevelWindow = asRecord(candidate.rowWindow)
  if (Object.keys(topLevelWindow).length) return topLevelWindow
  const payloadWindow = asRecord(asRecord(candidate.payload).rowWindow)
  if (Object.keys(payloadWindow).length) return payloadWindow
  return candidateMatchedWindows(candidate)[0] || {}
}

function candidatePreviewText(candidate: SkillSampleLocateCandidate): string {
  const window = candidatePrimaryWindow(candidate)
  const rows = Array.isArray(window.previewRows) ? window.previewRows : []
  const rowLines = rows
    .filter(Array.isArray)
    .map((row) => row.map((cell) => String(cell || '').trim()).filter(Boolean).join(' | '))
    .filter(Boolean)
  if (rowLines.length) return rowLines.slice(0, 3).join('；')
  const pathText = candidate.path?.length ? candidate.path.join(' / ') : ''
  const excerpt = String(candidate.excerpt || '').trim()
  if (pathText && !looksLikeRawCandidateText(pathText)) return pathText
  if (excerpt && !looksLikeRawCandidateText(excerpt)) return excerpt
  const payload = asRecord(candidate.payload)
  const rowCount = Number(payload.rowCount || 0)
  const columnCount = Number(payload.columnCount || 0)
  return `${candidate.type || t('workshop.candidateModule')} · ${rowCount || 0} 行 · ${columnCount || 0} 列`
}

function candidateWindowText(candidate: SkillSampleLocateCandidate): string {
  const window = candidatePrimaryWindow(candidate)
  if (!Object.keys(window).length) return ''
  const rowStart = Number(window.rowStart)
  const rowEnd = Number(window.rowEnd)
  const terms = candidateMatchedTerms(candidate)
  const flags: string[] = []
  if (Number.isFinite(rowStart) && Number.isFinite(rowEnd) && rowStart > 0 && rowEnd > 0) {
    flags.push(`命中行 ${rowStart}-${rowEnd}`)
  }
  if (terms.length) flags.push(`命中 ${terms.slice(0, 6).join('、')}`)
  if (window.headerLike && window.hasFollowingDataRows) flags.push('表头+数据行')
  return flags.join(' · ')
}

function candidateShapeText(candidate: SkillSampleLocateCandidate): string {
  const shape = asRecord(candidate.shapeSignals || asRecord(candidate.payload).shapeSignals)
  const rowCount = Number(shape.rowCount || asRecord(candidate.payload).rowCount || 0)
  const columnCount = Number(shape.columnCount || asRecord(candidate.payload).columnCount || 0)
  const matchedRowCount = Number(shape.matchedRowCount || 0)
  const matchedTermCount = Number(shape.matchedTermCount || 0)
  const parts = [
    rowCount ? `${rowCount} 行` : '',
    columnCount ? `${columnCount} 列` : '',
    matchedRowCount ? `${matchedRowCount} 个命中行` : '',
    matchedTermCount ? `${matchedTermCount} 个信号` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}

function looksLikeRawCandidateText(value: string): boolean {
  const text = String(value || '').toLowerCase()
  return text.includes('<table') || text.includes('<img') || text.includes('data:image') || text.includes('base64,')
}
const locatedEvidencePageRange = computed(() => {
  const pageRange = locatedSource.value?.pageRange
  const data = pageRange && typeof pageRange === 'object' ? pageRange as Record<string, unknown> : {}
  let start = typeof data.start === 'number' ? data.start : null
  let end = typeof data.end === 'number' ? data.end : start
  if (!start) {
    const refs = locatedSource.value?.contentRefs || []
    const pages = refs.flatMap((ref) => {
      if (!ref || typeof ref !== 'object') return []
      const values = (ref as Record<string, unknown>).evidencePages
      return Array.isArray(values) ? values : []
    })
      .map((page) => Number(page))
      .filter((page) => Number.isFinite(page) && page > 0)
    if (pages.length) {
      start = Math.min(...pages)
      end = Math.max(...pages)
    }
  }
  if (!start) return ''
  return end && end !== start ? `${start}-${end}` : `${start}`
})
const locatorWarnings = computed(() => {
  const values: string[] = []
  const result = semanticLocator.value?.locatorResult
  if (result && typeof result === 'object' && !Array.isArray(result)) {
    const warnings = (result as Record<string, unknown>).warnings
    if (Array.isArray(warnings)) {
      warnings.forEach((item) => {
        const text = String(item || '').trim()
        if (text && !values.includes(text)) values.push(text)
      })
    }
  }
  locatorCandidates.value.forEach((candidate) => {
    candidate.warnings.forEach((warning) => {
      const text = String(warning || '').trim()
      if (text && !values.includes(text)) values.push(text)
    })
  })
  return values
})
const locatorClassifiedCandidates = computed<Record<string, unknown>[]>(() => {
  const result = semanticLocator.value?.locatorResult
  if (!result || typeof result !== 'object' || Array.isArray(result)) return []
  const values = (result as Record<string, unknown>).classifiedCandidates
  return Array.isArray(values)
    ? values.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    : []
})
const relatedLocatorRows = computed(() => locatorClassifiedCandidates.value
  .filter((item) => String(item.role || '') === 'related')
  .map((item, index) => ({
    key: String(item.nodeId || `related-${index}`),
    title: String(item.title || t('workshop.relatedModule')),
    path: Array.isArray(item.path) ? item.path.map(String).join(' / ') : String(item.excerpt || ''),
    pages: pageRangeText((item as Record<string, unknown>).pages || item.pageNo),
    reason: String(item.roleReason || ''),
  })))
const locatedModuleRows = computed<LocatedModuleRow[]>(() => {
  const refs = locatedSource.value?.contentRefs || []
  const rows = refs.map((ref, index) => {
    const nodeId = String(ref.nodeId || ref.treeNodeId || ref.id || '').trim()
    const blockIds = Array.isArray(ref.blockIds) ? ref.blockIds.map(String).filter(Boolean) : []
    const pathTitle = locatedSource.value?.treePath?.length
      ? locatedSource.value.treePath[locatedSource.value.treePath.length - 1]
      : ''
    const refText = String(ref.sourceText || ref.text || ref.content || ref.excerpt || '').trim()
    const fallbackText = locatedSource.value?.sourceText || locatedSource.value?.summary || ''
    return {
      key: nodeId || blockIds.join(',') || `module-${index}`,
      title: String(ref.title || ref.label || pathTitle || t('workshop.matchedRange', { index: index + 1 })).trim(),
      summary: refText || locatedSource.value?.summary || '',
      pages: pageRangeText(ref.evidencePages || ref.pages || ref.pageNo),
      blockCount: blockIds.length,
      detailText: refText || fallbackText,
    }
  })
  if (rows.length || !locatedSource.value) return rows
  return [{
    key: locatedSource.value.treeNodeId || 'located-source',
    title: locatedSource.value.title || t('workshop.matchedDocumentTreeModule'),
    summary: locatedSource.value.summary || '',
    pages: locatedEvidencePageRange.value,
    blockCount: 0,
    detailText: locatedSource.value.sourceText || locatedSource.value.summary || '',
  }]
})
const locatedModuleCount = computed(() => locatedModuleRows.value.length)
const visibleLocatedModuleRows = computed(() => locatedModuleRows.value.slice(0, 4))
const hiddenLocatedModuleCount = computed(() => Math.max(0, locatedModuleRows.value.length - visibleLocatedModuleRows.value.length))
const relatedLocatorCount = computed(() => relatedLocatorRows.value.length)
const locatorStatusText = computed(() => {
  if (locatorStatus.value === 'extracted') return t('workshop.located')
  if (locatorStatus.value === 'needs_review') return t('workshop.pendingSelection')
  if (locatorStatus.value === 'not_found') return t('workshop.notMatched')
  return hasLocatedInput.value ? t('workshop.located') : t('workshop.pendingLocation')
})
const shouldShowLocatorResult = computed(() =>
  isExtractionTemplate.value
  && Boolean(semanticLocator.value),
)
const locatorAssetStatusText = computed(() => {
  if (!semanticLocator.value) return t('workshop.pendingGenerate')
  if (hasLocatorSkill.value) return t('workshop.locatorSkillSaved')
  return t('workshop.locatorSkillMissing')
})
const locatorSummaryLine = computed(() => {
  if (hasLocatedInput.value) {
    const base = t('workshop.modulesForExtraction', { count: locatedModuleCount.value || 1 })
    const related = relatedLocatorCount.value ? ` · ${t('workshop.relatedModuleCount', { count: relatedLocatorCount.value })}` : ''
    return `${base}${related}`
  }
  if (locatorCandidates.value.length) return t('workshop.candidateModuleCount', { count: locatorCandidates.value.length })
  return t('workshop.noReliableModuleFound')
})

const editableJsonError = computed(() => {
  const text = sampleExtraction.value?.editableOutput || ''
  if (!text.trim()) return t('workshop.jsonCannotBeEmpty')
  try {
    JSON.parse(text)
    return ''
  } catch (error) {
    return error instanceof Error ? error.message : t('workshop.invalidJsonFormat')
  }
})

const sampleProcessingJsonError = computed(() => {
  const text = sampleProcessingDraft.value?.editableOutput || ''
  if (!text.trim()) return t('workshop.jsonCannotBeEmpty')
  try {
    JSON.parse(text)
    return ''
  } catch (error) {
    return error instanceof Error ? error.message : t('workshop.invalidJsonFormat')
  }
})

const previewOutputs = computed<ExtractionOutputItem[]>(() => {
  const sample = sampleExtraction.value
  if (!sample) return []
  const parsed = parseEditableJson(sample.editableOutput)
  const editableOutputs = outputsFromEditableJson(parsed)
  if (editableOutputs.length) return editableOutputs
  const editableOutput = outputFromEditableJson(parsed)
  if (editableOutput) return [editableOutput]
  return sample.result.outputs || []
})

const sampleExtractionSummary = computed(() => {
  const sample = sampleExtraction.value
  if (!sample) return ''
  if (sample.result.summary) return sample.result.summary
  const output = previewOutputs.value[0]
  if (!output) return t('workshop.sampleExtractionCompleted')
  if (output.type === 'data_table') return t('workshop.extractedRows', { count: tableRows(output.data).length })
  if (output.type === 'field_list') return t('workshop.extractedFields', { count: fieldItems(output.data).length })
  if (output.type === 'record_collection') return t('workshop.extractedRecords', { count: recordItems(output.data).length })
  return t('workshop.sampleExtractionCompleted')
})

const sampleExtractionMeta = computed(() => {
  const sample = sampleExtraction.value
  if (!sample) return ''
  const parts = [
    sample.model ? `${t('trace.model')}${t('parse.labelSeparator')}${sample.model}` : '',
    sample.durationMs ? `${t('trace.duration')}${t('parse.labelSeparator')}${formatDuration(sample.durationMs)}` : '',
    sample.totalTokens ? `Token${t('parse.labelSeparator')}${sample.totalTokens}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
})

const sampleExtractionTrace = computed(() => sampleExtraction.value?.trace)
const sampleExtractionStats = computed(() => {
  const outputs = previewOutputs.value
  let fieldCount = 0
  let rowCount = 0
  let recordCount = 0
  outputs.forEach((output) => {
    if (output.type === 'field_list') fieldCount += fieldItems(output.data).length
    if (output.type === 'data_table') rowCount += tableRows(output.data).length
    if (output.type === 'record_collection') recordCount += recordItems(output.data).length
  })
  const parts = [
    outputs.length ? t('workshop.outputCount', { count: outputs.length }) : '',
    fieldCount ? t('workshop.fieldCount', { count: fieldCount }) : '',
    rowCount ? t('workshop.tableRowCount', { count: rowCount }) : '',
    recordCount ? t('workshop.recordCount', { count: recordCount }) : '',
  ].filter(Boolean)
  return parts.join(' · ') || t('workshop.waitingSampleOutput')
})
const extractTabDescription = computed(() => {
  if (sampleExtraction.value) return sampleExtractionStats.value
  if (hasLocatedInput.value) return t('workshop.readyTrialExtract')
  if (locatorNeedsSelection.value) return t('workshop.pendingLocationSelection')
  if (hasLocatorSkill.value) return t('workshop.pendingRelocation')
  return t('workshop.waitingSampleExtraction')
})

watch(
  () => [
    props.visible,
    activeSourceKey.value,
    Boolean(hasLocatedInput.value),
    Boolean(sampleExtraction.value),
    Boolean(sampleProcessingDraft.value),
    Boolean(props.currentDraft?.skillText?.trim()),
  ] as const,
  (
    [visible, sourceKey, hasLocated, hasExtraction, hasProcessing, hasSkill],
    [previousVisible, previousSourceKey, previousHasLocated, previousHasExtraction, previousHasProcessing, previousHasSkill],
  ) => {
    if (!visible) {
      activeDrawerTab.value = 'locate'
      activeExtractSubTab.value = 'sample'
      return
    }
    if (!previousVisible) {
      resetTabsForCurrentSource()
      return
    }
    if (sourceKey !== previousSourceKey) {
      resetTabsForCurrentSource()
      return
    }
    if (isExtractionTemplate.value && hasSkill && !previousHasSkill) {
      activeDrawerTab.value = 'extract'
      activeExtractSubTab.value = 'validation'
      return
    }
    if (isExtractionTemplate.value && hasLocated && !hasExtraction && !previousHasLocated) {
      activeDrawerTab.value = 'extract'
      activeExtractSubTab.value = 'sample'
      return
    }
    const becameReady = isOperationWorkflow.value
      ? hasProcessing && !previousHasProcessing
      : hasExtraction && !previousHasExtraction
    if (becameReady) {
      activeDrawerTab.value = 'extract'
      activeExtractSubTab.value = 'sample'
    }
  },
)

async function copySampleExtractionTrace() {
  const trace = sampleExtractionTrace.value
  if (!trace?.traceId) return
  const text = trace.tracePath ? `${trace.traceId}\n${trace.tracePath}` : trace.traceId
  try {
    await navigator.clipboard.writeText(text)
    Message.success(t('workshop.traceCopied'))
  } catch {
    Message.warning(t('workshop.traceCopyFailed'))
  }
}

const sampleProcessingSummary = computed(() => {
  const sample = sampleProcessingDraft.value
  if (!sample) return ''
  if (sample.result.summary) return sample.result.summary
  return t('workshop.sampleProcessingCompleted')
})

const sampleProcessingMeta = computed(() => {
  const sample = sampleProcessingDraft.value
  if (!sample) return ''
  const parts = [
    sample.result.resultKind ? `${t('workshop.resultType')}${t('parse.labelSeparator')}${sample.result.resultKind}` : '',
    sample.model ? `${t('trace.model')}${t('parse.labelSeparator')}${sample.model}` : '',
    sample.durationMs ? `${t('trace.duration')}${t('parse.labelSeparator')}${formatDuration(sample.durationMs)}` : '',
    sample.totalTokens ? `Token${t('parse.labelSeparator')}${sample.totalTokens}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
})

const sampleProcessingPreview = computed(() => {
  const sample = sampleProcessingDraft.value
  if (!sample) return ''
  const parsed = parseEditableJson(sample.editableOutput)
  return JSON.stringify(parsed ?? sample.result, null, 2)
})

const canShowSkillValidation = computed(() => Boolean(props.currentDraft?.skillText?.trim()))
const sampleConfirmed = computed(() => {
  if (!props.currentDraft) return false
  return props.currentDraft.kind === 'operation'
    ? props.currentDraft.sampleProcessing?.status === 'confirmed'
    : props.currentDraft.sampleExtraction?.status === 'confirmed'
})
const developmentValidationReport = computed(() => asRecord(skillDevelopment.value?.validationReport))
const developmentEvidenceSummary = computed(() => asRecord(skillDevelopment.value?.evidenceSummary))
const developmentContractSummary = computed(() => asRecord(skillDevelopment.value?.outputContractSummary || skillDevelopment.value?.runtimeContract))
const developmentValidationStatus = computed(() => String(developmentValidationReport.value.status || 'pending'))
const developmentValidationChecks = computed(() => {
  const checks = developmentValidationReport.value.checks
  return Array.isArray(checks)
    ? checks.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    : []
})
const evidenceSummaryLine = computed(() => {
  const evidence = developmentEvidenceSummary.value
  const pages = Array.isArray(evidence.selectedPages) ? evidence.selectedPages.join('、') : ''
  const parts = [
    evidence.status ? t('workshop.evidenceStatus', { status: evidence.status }) : '',
    pages ? t('workshop.evidencePages', { pages }) : '',
    typeof evidence.contentRefCount === 'number'
      ? t('workshop.evidenceRefCount', { count: evidence.contentRefCount })
      : '',
    typeof evidence.sampleChars === 'number' ? t('workshop.sampleCharCount', { count: evidence.sampleChars }) : '',
  ].filter(Boolean)
  return parts.join(' · ') || t('workshop.waitingSampleEvidence')
})
const outputContractLine = computed(() => {
  const contract = developmentContractSummary.value
  const outputType = String(contract.outputType || contract.resultKind || '')
  const renderer = String(contract.renderer || '')
  return [outputType, renderer].filter(Boolean).join(' · ') || t('workshop.waitingOutputContract')
})
const hasVerifiedRun = computed(() =>
  Boolean(props.currentDraft?.status === 'verified' || props.currentDraft?.runOption),
)
const activeStepRunState = computed(() => {
  const state = props.stepRunState
  if (!state || props.currentDraft?.kind !== state.kind) return null
  if (state.draftId && props.currentDraft?.id !== state.draftId) return null
  return state
})
const isStepRunActive = computed(() => {
  const status = activeStepRunState.value?.status
  return status === 'starting' || status === 'running' || status === 'syncing'
})
const stepRunStatusText = computed(() => {
  const state = activeStepRunState.value
  if (!state) return ''
  if (state.status === 'completed') return t('workshop.stepRunCompleted')
  if (state.status === 'needs_review') return t('workshop.stepRunNeedsReview')
  if (state.status === 'failed') return t('workshop.stepRunFailed')
  if (state.status === 'syncing') return t('workshop.stepRunSyncing')
  if (state.status === 'running') return t('workshop.stepRunRunning')
  return t('workshop.stepRunStarting')
})
const stepRunButtonText = computed(() => {
  const status = activeStepRunState.value?.status
  if (status === 'running') return t('workshop.waitingTrialResult')
  if (status === 'syncing') return t('workshop.stepRunSyncing')
  if (status === 'starting') return t('workshop.stepRunStarting')
  return t('workshop.saveAndRunTrial')
})
const canCreatePrototype = computed(() => {
  const draft = props.currentDraft
  return Boolean(
    props.prototypeOptimizationEnabled !== false
      && draft?.kind === 'extraction'
      && draft.skillText.trim()
      && (sampleConfirmed.value || hasVerifiedRun.value),
  )
})
const sampleConfirmHint = computed(() => (
  isOperationWorkflow.value
    ? t('workshop.processingConfirmHint')
    : t('workshop.extractionConfirmHint')
))
const shouldShowDraftRunHint = computed(() =>
  Boolean(props.currentDraft?.skillText?.trim() && props.currentDraft.status !== 'verified'),
)
const draftRunHint = computed(() => (
  t('workshop.draftRunHint')
))
const developmentStages = computed(() => [
  {
    key: 'sample',
    label: t('workshop.sampleTrial'),
    status: hasVerifiedRun.value || sampleConfirmed.value ? 'done' : (sampleExtraction.value || sampleProcessingDraft.value ? 'pending' : 'empty'),
    text: hasVerifiedRun.value
      ? t('workshop.passed')
      : (sampleConfirmed.value
          ? t('workshop.confirmed')
          : (sampleExtraction.value || sampleProcessingDraft.value ? t('workshop.pendingConfirm') : t('workshop.pendingTrial'))),
  },
  {
    key: 'skill',
    label: t('workshop.skillDraft'),
    status: props.currentDraft?.skillText.trim() ? 'done' : 'empty',
    text: props.currentDraft?.skillText.trim() ? t('workshop.generated') : t('workshop.pendingGenerate'),
  },
  {
    key: 'validation',
    label: t('workshop.trialValidation'),
    status: activeStepRunState.value?.status === 'failed'
      ? 'failed'
      : activeStepRunState.value?.status === 'needs_review'
        ? 'needs_review'
      : isStepRunActive.value
        ? 'running'
        : hasVerifiedRun.value || developmentValidationStatus.value === 'passed'
      ? 'done'
      : (developmentValidationStatus.value === 'failed' || props.currentDraft?.errors.length ? 'failed' : 'pending'),
    text: activeStepRunState.value
      ? stepRunStatusText.value
      : hasVerifiedRun.value
      ? t('workshop.passed')
      : (developmentValidationStatus.value === 'passed'
          ? t('workshop.passed')
          : (developmentValidationStatus.value === 'failed' || props.currentDraft?.errors.length
              ? t('workshop.needsAdjustment')
              : t('workshop.pendingTrial'))),
  },
])
const extractSubTabItems = computed(() => [
  {
    key: 'sample' as ExtractSubTabKey,
    label: t('workshop.sampleResult'),
    description: sampleExtraction.value
      ? sampleExtractionStats.value
      : (hasVerifiedRun.value ? t('workshop.verifiedOutput') : t('workshop.waitingTrialExtraction')),
    disabled: false,
  },
  {
    key: 'validation' as ExtractSubTabKey,
    label: t('workshop.skillTrial'),
    description: props.currentDraft?.skillText?.trim() ? formatStepStatus(props.currentDraft) : t('workshop.skillTrialAfterGenerate'),
    disabled: !canShowSkillValidation.value,
  },
])

function localizePlatformDiagnostic(value: unknown) {
  return translateStaticText(String(value || ''))
}

function resetTabsForCurrentSource() {
  activeExtractSubTab.value = 'sample'
  if (isOperationWorkflow.value) {
    activeDrawerTab.value = sampleProcessingDraft.value ? 'extract' : 'locate'
    return
  }
  if (props.currentDraft?.skillText?.trim()) {
    activeDrawerTab.value = 'extract'
    activeExtractSubTab.value = 'validation'
    return
  }
  activeDrawerTab.value = hasLocatedInput.value || sampleExtraction.value ? 'extract' : 'locate'
}

function applySuggestedDefaults() {
  const shouldFillDataTypeName = !(isExtractionTemplate.value && props.sourceMode === 'document')
  if (shouldFillDataTypeName && !props.dataTypeName.trim()) {
    emit('update:dataTypeName', suggestedDataTypeName.value)
  }
}

function generateWithDefaults() {
  applySuggestedDefaults()
  if (isExtractionTemplate.value && activeDrawerTab.value === 'extract') {
    if (sampleExtractBlocked.value) {
      Message.warning(sampleExtractBlockReason.value || t('workshop.aiExtractionUnavailable'))
      return
    }
    emit('sampleExtract')
    return
  }
  emit('generate')
}

function setMode(mode: SampleSourceMode) {
  if (mode === 'tree' && !props.canUseTree) return
  if (mode === 'selection' && !props.canUseSelection) return
  if (mode === 'target' && !props.canUseTarget) return
  emit('update:sourceMode', mode)
}

function formatStepStatus(step: ProcessingStepDraft) {
  if (step.status === 'verified') return t('workshop.verified')
  if (step.kind === 'operation' && !step.skillText.trim() && step.sampleProcessing?.status !== 'confirmed') return t('workshop.pendingConfirm')
  if (!step.skillText.trim() && step.sampleExtraction?.status !== 'confirmed') return t('workshop.pendingConfirm')
  if (!step.skillText.trim()) return t('workshop.pendingGenerateSkill')
  if (step.errors.length) return t('workshop.needsAdjustment')
  return t('workshop.pendingTrial')
}

function openLocatedModule(module: LocatedModuleRow) {
  locatorModuleModalTitle.value = module.title || t('workshop.matchedModule')
  locatorModuleModalMeta.value = module.pages ? t('workshop.evidencePagesLabel', { pages: module.pages }) : ''
  locatorModuleModalText.value = module.detailText || module.summary || locatedSource.value?.sourceText || t('workshop.noPreviewContent')
  locatorModuleModalVisible.value = true
}

function parseEditableJson(value: string): unknown {
  try {
    return JSON.parse(value)
  } catch {
    return undefined
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function outputFromEditableJson(value: unknown): ExtractionOutputItem | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const data = value as Record<string, unknown>
  if (Array.isArray(data.headers) && Array.isArray(data.rows)) {
    return {
      id: 'editable-output',
      title: t('workshop.extractionOutput'),
      type: 'data_table',
      renderer: 'data_table',
      data,
      schema: {},
      sourceRefs: [],
    }
  }
  if (Array.isArray(data.fields)) {
    return {
      id: 'editable-output',
      title: t('workshop.extractionOutput'),
      type: 'field_list',
      renderer: 'field_list',
      data,
      schema: {},
      sourceRefs: [],
    }
  }
  if (Array.isArray(data.records)) {
    return {
      id: 'editable-output',
      title: t('workshop.extractionOutput'),
      type: 'record_collection',
      renderer: 'nested_records',
      data,
      schema: {},
      sourceRefs: [],
    }
  }
  if (Array.isArray(data.outputs)) {
    const first = data.outputs.find((item): item is ExtractionOutputItem => Boolean(item && typeof item === 'object'))
    return first || null
  }
  return {
    id: 'editable-output',
    title: t('workshop.extractionOutput'),
    type: 'custom',
    renderer: 'auto',
    data,
    schema: {},
    sourceRefs: [],
  }
}

function outputsFromEditableJson(value: unknown): ExtractionOutputItem[] {
  if (!isRecord(value) || !Array.isArray(value.outputs)) return []
  return value.outputs.filter((item): item is ExtractionOutputItem => isRecord(item))
}

function tableHeaders(value: unknown): string[] {
  if (!value || typeof value !== 'object') return []
  return tableRawHeaders(value).map((header, index) => normalizeTableHeader(header, index))
}

function tableRawHeaders(value: unknown): string[] {
  if (!value || typeof value !== 'object') return []
  const record = value as Record<string, unknown>
  const headers = Array.isArray(record.headers) ? record.headers.map((item) => String(item ?? '')) : []
  const rows = Array.isArray(record.rows) ? record.rows : []
  const hasRowSourcePage = rows.some((row) => {
    const rowRecord = asRecord(row)
    return Boolean(rowRecord.source_page || rowRecord.sourcePage)
  })
  if (headers.length) {
    const next = [...headers]
    if (hasRowSourcePage && !next.includes('source_page') && !next.includes('sourcePage')) {
      next.push('source_page')
    }
    return next
  }
  const inferred: string[] = []
  rows.forEach((row) => {
    if (Array.isArray(row)) {
      row.forEach((_, index) => inferred.push(t('parse.columnFallback', { index: index + 1 })))
      return
    }
    if (row && typeof row === 'object') {
      inferred.push(...Object.keys(row as Record<string, unknown>))
    }
  })
  return Array.from(new Set(inferred))
}

function normalizeTableHeader(value: unknown, index: number) {
  const text = stringifyCell(value).trim()
  if (text === 'source_page' || text === 'sourcePage') return t('parse.sourcePage')
  if (!text) return index === 0 ? t('parse.item') : t('parse.columnFallback', { index: index + 1 })
  return text
}

function tableRows(value: unknown): unknown[][] {
  if (!value || typeof value !== 'object') return []
  const rows = (value as Record<string, unknown>).rows
  if (!Array.isArray(rows)) return []
  const headers = tableRawHeaders(value)
  return rows.map((row) => {
    if (Array.isArray(row)) return headers.map((_, index) => row[index])
    const record = asRecord(row)
    return headers.map((header) => {
      if (header === 'source_page' && record.sourcePage !== undefined && record.source_page === undefined) {
        return record.sourcePage
      }
      return record[header]
    })
  })
}

function outputNotes(value: unknown, key: 'mergeNotes' | 'evidence') {
  if (!value || typeof value !== 'object') return []
  const notes = (value as Record<string, unknown>)[key]
  if (!Array.isArray(notes)) return []
  return notes.map(normalizeOutputNote).filter(Boolean)
}

function normalizeOutputNote(note: unknown) {
  if (!note) return ''
  if (typeof note === 'string') return note.trim()
  const record = asRecord(note)
  const text = stringifyCell(record.text || record.note || record.description || record.summary).trim()
  const page = stringifyCell(record.source_page || record.sourcePage || record.page || record.pageNo).trim()
  if (text && page) return `${text}（${page}）`
  return text || page
}

function fieldItems(value: unknown): Array<Record<string, unknown>> {
  if (!value || typeof value !== 'object') return []
  const fields = (value as Record<string, unknown>).fields
  return Array.isArray(fields) ? fields.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : []
}

function recordItems(value: unknown): Array<Record<string, unknown>> {
  if (!value || typeof value !== 'object') return []
  const records = (value as Record<string, unknown>).records
  return Array.isArray(records) ? records.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : []
}

function recordColumns(records: Array<Record<string, unknown>>): string[] {
  const columns: string[] = []
  records.slice(0, 8).forEach((record) => {
    Object.keys(record).forEach((key) => {
      if (!columns.includes(key)) columns.push(key)
    })
  })
  return columns.slice(0, 10)
}

function stringifyCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function pageRangeText(value: unknown): string {
  if (Array.isArray(value)) {
    const pages = value
      .map((item) => Number(item))
      .filter((item) => Number.isFinite(item) && item > 0)
    if (!pages.length) return ''
    const start = Math.min(...pages)
    const end = Math.max(...pages)
    return start === end ? `${start}` : `${start}-${end}`
  }
  const pageNo = Number(value)
  return Number.isFinite(pageNo) && pageNo > 0 ? `${pageNo}` : ''
}

function formatDuration(value: number): string {
  if (value >= 1000) return `${Math.round(value / 100) / 10}s`
  return `${value}ms`
}

async function copyText(value: string, label: string) {
  const localizedLabel = localizePlatformDiagnostic(label)
  if (!value.trim()) {
    Message.info(t('common.emptyWithLabel', { label: localizedLabel }))
    return
  }
  try {
    await navigator.clipboard.writeText(value)
    Message.success(t('common.copiedWithLabel', { label: localizedLabel }))
  } catch {
    Message.warning(t('common.copyFailedManual'))
  }
}
</script>

<template>
  <a-drawer
    :visible="visible"
    :width="920"
    :footer="false"
    unmount-on-close
    :title="isOperationWorkflow ? t('workshop.generateProcessingStep') : t('workshop.createExtractionTemplate')"
    @cancel="emit('close')"
  >
    <div class="processing-step-drawer">
      <nav class="processing-step-drawer__tabs" :aria-label="t('workshop.steps')">
        <button
          v-for="(tab, index) in drawerTabItems"
          :key="tab.key"
          type="button"
          :class="{ 'is-active': activeDrawerTab === tab.key }"
          @click="activeDrawerTab = tab.key"
        >
          <i>{{ index + 1 }}</i>
          <span>
            <strong>{{ tab.label }}</strong>
            <em>{{ tab.description }}</em>
          </span>
        </button>
      </nav>

      <section v-show="activeDrawerTab === 'locate'" class="processing-step-drawer__tab-panel">
      <section class="processing-step-drawer__main processing-step-drawer__main--compact">
        <div class="processing-step-drawer__prompt-grid processing-step-drawer__prompt-grid--locate">
          <label class="processing-step-drawer__field">
            <span>{{ isExtractionTemplate ? t('workshop.dataBlockToExtract') : t('workshop.processingObjectName') }}</span>
            <a-input
              :model-value="isExtractionTemplate ? dataTypeName : dataTypeName || suggestedDataTypeName"
              :placeholder="isExtractionTemplate ? t('workshop.dataBlockPlaceholder') : t('workshop.processingObjectPlaceholder', { defaultName: defaultDataTypeName })"
              @update:model-value="(value) => emit('update:dataTypeName', String(value))"
            />
          </label>
          <label v-if="isExtractionTemplate" class="processing-step-drawer__field">
            <span>{{ t('workshop.locatorPromptOptional') }}</span>
            <a-textarea
              :model-value="locatorInstruction"
              :placeholder="t('workshop.locatorPromptPlaceholder')"
              :auto-size="{ minRows: 2, maxRows: 3 }"
              @update:model-value="(value) => emit('update:locatorInstruction', String(value))"
            />
          </label>
        </div>
        <details v-if="!isExtractionTemplate" class="processing-step-drawer__optional">
          <summary>{{ t('workshop.advancedSettings') }}</summary>
          <div class="processing-step-drawer__recommendation">
            <span>{{ t('workshop.outputShape') }}</span>
            <strong>{{ t('workshop.autoDetect') }}</strong>
            <p>{{ t('workshop.autoOutputShapeDescription', { summary: guidedSummary }) }}</p>
          </div>
          <label class="processing-step-drawer__field">
            <span>{{ t('workshop.specialProcessingGoal') }}</span>
            <a-textarea
              :model-value="processingGoal"
              :placeholder="t('workshop.specialProcessingGoalPlaceholder')"
              :auto-size="{ minRows: 2, maxRows: 4 }"
              @update:model-value="(value) => emit('update:processingGoal', String(value))"
            />
          </label>
          <label class="processing-step-drawer__field">
            <span>{{ t('workshop.outputFormatPreference') }}</span>
            <a-textarea
              :model-value="expectedOutput"
              :placeholder="t('workshop.outputFormatPreferencePlaceholder')"
              :auto-size="{ minRows: 2, maxRows: 4 }"
              @update:model-value="(value) => emit('update:expectedOutput', String(value))"
            />
          </label>
          <details class="processing-step-drawer__source-more">
            <summary>{{ t('workshop.processingInputSource') }}</summary>
            <div class="processing-step-drawer__source-switch">
              <button
                v-for="option in sourceOptions"
                :key="option.mode"
                type="button"
                :disabled="option.disabled"
                :class="{ 'is-active': sourceMode === option.mode }"
                @click="setMode(option.mode)"
              >
                <strong>{{ option.label }}</strong>
                <span>{{ option.description }}</span>
              </button>
            </div>
            <p>{{ sourceNote }}</p>
          </details>
        </details>
        <div class="processing-step-drawer__action-row">
          <a-button type="primary" :loading="primaryActionLoading" @click="generateWithDefaults">
            {{ primaryActionLabel }}
          </a-button>
        </div>
      </section>

      <section
        v-if="shouldShowLocatorResult"
        class="processing-step-drawer__section processing-step-drawer__section--locator"
      >
        <header class="processing-step-drawer__validation-summary processing-step-drawer__static-summary">
          <span>
            <strong>{{ t('workshop.locatorAssets') }}</strong>
            <em>{{ locatorSummaryLine }}</em>
          </span>
          <div class="processing-step-drawer__summary-actions">
            <a-button
              v-if="hasLocatorSkill"
              size="mini"
              @click="locatorSkillModalVisible = true"
            >
              {{ t('workshop.editSkill') }}
            </a-button>
            <a-button v-if="hasLocatorSkill" size="mini" @click="copyText(locatorSkillText, t('workshop.locatorSkill'))">
              {{ t('common.copy') }}
            </a-button>
            <a-tag :color="locatorStatus === 'extracted' ? 'green' : locatorStatus === 'needs_review' ? 'orange' : 'red'">
              {{ locatorStatusText }}
            </a-tag>
          </div>
        </header>

        <div class="processing-step-drawer__validation-body">
          <a-alert
            v-if="semanticLocator && !hasLocatorSkill"
            type="warning"
            :show-icon="false"
            :content="locatorAssetStatusText"
          />

          <div v-if="locatedSource" class="processing-step-drawer__located-stack">
            <article
              v-for="module in visibleLocatedModuleRows"
              :key="module.key"
              class="processing-step-drawer__located-source"
            >
              <div>
                <strong :title="module.title">{{ module.title }}</strong>
                <span :title="module.summary || locatedSource.summary">
                  {{ module.summary || locatedSource.summary }}
                </span>
              </div>
              <div class="processing-step-drawer__located-source-actions">
                <a-tag v-if="module.pages" size="small">
                  {{ t('workshop.evidencePagesLabel', { pages: module.pages }) }}
                </a-tag>
                <a-button size="mini" @click="openLocatedModule(module)">
                  {{ t('workshop.viewContent') }}
                </a-button>
              </div>
            </article>
            <details v-if="hiddenLocatedModuleCount" class="processing-step-drawer__locator-skill">
              <summary>{{ t('workshop.viewRemainingMatchedModules', { count: hiddenLocatedModuleCount }) }}</summary>
              <div class="processing-step-drawer__candidate-list">
                <article
                  v-for="module in locatedModuleRows.slice(visibleLocatedModuleRows.length)"
                  :key="module.key"
                  class="processing-step-drawer__candidate"
                >
                  <div>
                    <strong>{{ module.title }}</strong>
                    <span>{{ module.summary || locatedSource.summary }}</span>
                    <em v-if="module.pages">{{ t('workshop.evidencePagesLabel', { pages: module.pages }) }}</em>
                  </div>
                  <div class="processing-step-drawer__candidate-side">
                    <a-button size="mini" @click="openLocatedModule(module)">
                      {{ t('workshop.viewContent') }}
                    </a-button>
                  </div>
                </article>
              </div>
            </details>
          </div>

          <details v-if="relatedLocatorRows.length" class="processing-step-drawer__locator-skill">
            <summary>{{ t('workshop.relatedModulesNotExtracted', { count: relatedLocatorRows.length }) }}</summary>
            <div class="processing-step-drawer__candidate-list">
              <article
                v-for="module in relatedLocatorRows"
                :key="module.key"
                class="processing-step-drawer__candidate"
              >
                <div>
                  <strong>{{ module.title }}</strong>
                  <span>{{ module.path || module.reason }}</span>
                  <em v-if="module.pages">{{ t('workshop.evidencePagesLabel', { pages: module.pages }) }}</em>
                  <em v-if="module.reason">{{ module.reason }}</em>
                </div>
                <div class="processing-step-drawer__candidate-side">
                  <a-tag size="small">{{ t('workshop.related') }}</a-tag>
                </div>
              </article>
            </div>
          </details>

          <div v-if="!locatedSource && locatorCandidates.length" class="processing-step-drawer__review-card">
            <strong>{{ t('workshop.locatorCandidatePendingConfirm') }}</strong>
            <p>{{ t('workshop.locatorCandidatePendingConfirmDescription') }}</p>
          </div>

          <details
            v-if="hasLocatorSkill || locatorPositiveTerms.length || locatorNegativeTerms.length || locatorExpectedTypes.length || locatorReason || locatorWarnings.length"
            class="processing-step-drawer__locator-skill"
          >
            <summary>{{ t('workshop.locatorEvidenceProfileAdvanced') }}</summary>
            <p v-if="locatorReason" class="processing-step-drawer__locator-reason">
              {{ locatorReason }}
            </p>
            <a-alert
              v-for="warning in locatorWarnings"
              :key="warning"
              type="warning"
              :show-icon="false"
              :content="warning"
            />
            <div class="processing-step-drawer__locator-chips">
              <span v-if="locatorQuery">
                {{ t('workshop.queryLabel', { value: locatorQuery }) }}
              </span>
              <span v-if="locatorExpectedTypes.length">
                {{ t('workshop.objectLabel', { value: locatorExpectedTypes.join('、') }) }}
              </span>
              <span v-if="locatorPositiveTerms.length">
                {{ t('workshop.positiveLabel', { value: locatorPositiveTerms.join('、') }) }}
              </span>
              <span v-if="locatorNegativeTerms.length">
                {{ t('workshop.excludeLabel', { value: locatorNegativeTerms.join('、') }) }}
              </span>
            </div>
          </details>

          <details v-if="!locatedSource && locatorCandidates.length" open class="processing-step-drawer__locator-skill">
            <summary>{{ t('workshop.candidateModules') }}</summary>
          <div class="processing-step-drawer__candidate-list">
            <article
              v-for="candidate in locatorCandidates"
              :key="candidate.nodeId"
              class="processing-step-drawer__candidate"
            >
              <div>
                <strong>{{ candidate.title || t('workshop.candidateModule') }}</strong>
                <span :title="candidatePreviewText(candidate)">{{ candidatePreviewText(candidate) }}</span>
                <em v-if="candidateWindowText(candidate)">{{ candidateWindowText(candidate) }}</em>
                <em v-else-if="candidateShapeText(candidate)">{{ candidateShapeText(candidate) }}</em>
                <em v-if="candidate.pageRange">{{ t('workshop.evidencePagesLabel', { pages: candidate.pageRange }) }}</em>
              </div>
              <div class="processing-step-drawer__candidate-side">
                <a-tag size="small">{{ t('workshop.candidate') }}</a-tag>
                <a-button size="mini" type="primary" @click="emit('selectLocateCandidate', candidate.nodeId)">
                  {{ t('workshop.useCandidate') }}
                </a-button>
              </div>
            </article>
          </div>
          </details>
        </div>
      </section>
      </section>

      <section v-show="activeDrawerTab === 'extract'" class="processing-step-drawer__tab-panel">
      <section v-if="isExtractionTemplate" class="processing-step-drawer__main processing-step-drawer__main--compact">
        <div class="processing-step-drawer__compact-status">
          <span>{{ t('workshop.extractionInput') }}</span>
          <strong>{{ extractInputStatusText }}</strong>
        </div>
        <div class="processing-step-drawer__prompt-grid">
        <label class="processing-step-drawer__field">
          <span>{{ t('workshop.extractionPromptOptional') }}</span>
          <a-textarea
            :model-value="processingGoal"
            :placeholder="t('workshop.extractionPromptPlaceholder')"
            :auto-size="{ minRows: 2, maxRows: 4 }"
            @update:model-value="(value) => emit('update:processingGoal', String(value))"
          />
        </label>
        <label class="processing-step-drawer__field">
          <span>{{ t('workshop.outputRequirementsOptional') }}</span>
          <a-textarea
            :model-value="expectedOutput"
            :placeholder="t('workshop.outputRequirementsPlaceholder')"
            :auto-size="{ minRows: 2, maxRows: 4 }"
            @update:model-value="(value) => emit('update:expectedOutput', String(value))"
          />
        </label>
        </div>
        <a-alert
          v-if="sampleExtractBlocked && sampleExtractBlockReason"
          type="warning"
          class="processing-step-drawer__capability-alert"
          :show-icon="true"
        >
          <template #title>{{ t('workshop.aiExtractionConfigIncomplete') }}</template>
          <div class="processing-step-drawer__capability-alert-body">
            <span>{{ sampleExtractBlockReason }}</span>
            <a
              v-if="sampleExtractApplyUrl"
              :href="sampleExtractApplyUrl"
              target="_blank"
              rel="noreferrer"
            >
              {{ t('workshop.applyNow') }}
            </a>
          </div>
        </a-alert>
        <div class="processing-step-drawer__action-row">
          <a-button type="primary" :loading="sampleExtracting" :disabled="sampleExtractActionDisabled" @click="generateWithDefaults">
            {{ sampleExtraction ? t('workshop.runExtractionAgain') : t('workshop.aiTrialExtraction') }}
          </a-button>
        </div>
      </section>
      <nav
        v-if="isExtractionTemplate && (sampleExtraction || canShowSkillValidation)"
        class="processing-step-drawer__subtabs"
        :aria-label="t('workshop.extractionSkillSubsteps')"
      >
        <button
          v-for="tab in extractSubTabItems"
          :key="tab.key"
          type="button"
          :disabled="tab.disabled"
          :class="{ 'is-active': activeExtractSubTab === tab.key }"
          @click="activeExtractSubTab = tab.key"
        >
          <strong>{{ tab.label }}</strong>
          <span>{{ tab.description }}</span>
        </button>
      </nav>
      <section
        v-if="isExtractionTemplate && sampleExtraction && activeExtractSubTab === 'sample'"
        class="processing-step-drawer__section processing-step-drawer__section--sample-result"
      >
        <header class="processing-step-drawer__validation-summary processing-step-drawer__static-summary">
          <span>
            <strong>{{ t('workshop.extractionSampleResult') }}</strong>
            <em>{{ sampleExtractionSummary }}</em>
          </span>
          <a-tag :color="sampleExtraction.status === 'confirmed' ? 'green' : editableJsonError ? 'orange' : 'blue'">
            {{ sampleExtraction.status === 'confirmed' ? t('workshop.confirmed') : t('workshop.pendingConfirm') }}
          </a-tag>
        </header>

        <div class="processing-step-drawer__validation-body">
          <details v-if="sampleExtractionMeta || sampleExtractionTrace" class="processing-step-drawer__run-meta">
            <summary>{{ t('workshop.runInfo') }}</summary>
            <div v-if="sampleExtractionMeta" class="processing-step-drawer__meta-line">
              {{ sampleExtractionMeta }}
            </div>
            <div v-if="sampleExtractionTrace" class="processing-step-drawer__meta-line processing-step-drawer__trace-line">
              <span>{{ t('workshop.processTrace', { traceId: sampleExtractionTrace.traceId }) }}</span>
              <a-button size="mini" type="text" @click="copySampleExtractionTrace">
                {{ t('common.copy') }}
              </a-button>
            </div>
          </details>
          <a-alert
            v-if="editableJsonError"
            type="warning"
            :show-icon="false"
            :content="t('workshop.jsonCannotConfirm', { error: editableJsonError })"
          />
          <div class="processing-step-drawer__sample-metrics">
            {{ sampleExtractionStats }}
          </div>

          <div class="processing-step-drawer__preview-list">
            <section v-for="output in previewOutputs" :key="output.id" class="processing-step-drawer__preview">
              <div class="processing-step-drawer__result-head">
                <span>{{ output.title || t('workshop.preview') }}</span>
                <a-tag size="small">{{ output.type }}</a-tag>
              </div>

              <template v-if="output.type === 'data_table'">
                <div class="processing-step-drawer__table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th v-for="header in tableHeaders(output.data)" :key="header">
                          {{ header }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(row, rowIndex) in tableRows(output.data)" :key="rowIndex">
                        <td v-for="(cell, cellIndex) in row" :key="cellIndex">
                          {{ stringifyCell(cell) }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div
                  v-if="outputNotes(output.data, 'mergeNotes').length || outputNotes(output.data, 'evidence').length"
                  class="processing-step-drawer__table-semantics"
                >
                  <div v-if="outputNotes(output.data, 'mergeNotes').length">
                    <strong>{{ t('parse.structureNotes') }}</strong>
                    <span
                      v-for="note in outputNotes(output.data, 'mergeNotes')"
                      :key="`sample-merge-${output.id}-${note}`"
                    >
                      {{ note }}
                    </span>
                  </div>
                  <div v-if="outputNotes(output.data, 'evidence').length">
                    <strong>{{ t('parse.evidenceSummary') }}</strong>
                    <span
                      v-for="note in outputNotes(output.data, 'evidence')"
                      :key="`sample-evidence-${output.id}-${note}`"
                    >
                      {{ note }}
                    </span>
                  </div>
                </div>
              </template>

              <div v-else-if="output.type === 'field_list'" class="processing-step-drawer__table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{{ t('parse.field') }}</th>
                      <th>{{ t('parse.value') }}</th>
                      <th>{{ t('workshop.source') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(field, fieldIndex) in fieldItems(output.data)" :key="fieldIndex">
                      <td>{{ stringifyCell(field.label ?? field.key ?? field.field_name ?? field.name) }}</td>
                      <td>{{ stringifyCell(field.value ?? field.field_value ?? '') }}</td>
                      <td>{{ stringifyCell(field.source_page ?? field.page ?? '') }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div v-else-if="output.type === 'record_collection'" class="processing-step-drawer__table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th v-for="column in recordColumns(recordItems(output.data))" :key="column">
                        {{ column }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(record, rowIndex) in recordItems(output.data)" :key="rowIndex">
                      <td v-for="column in recordColumns(recordItems(output.data))" :key="column">
                        {{ stringifyCell(record[column]) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <pre v-else>{{ JSON.stringify(output.data, null, 2) }}</pre>
            </section>
          </div>

          <details class="processing-step-drawer__json-editor">
            <summary>{{ t('workshop.advancedViewJson') }}</summary>
            <div class="processing-step-drawer__raw-json-head">
              <span>{{ t('workshop.rawConfirmedOutput') }}</span>
              <a-button size="mini" @click="copyText(sampleExtraction.editableOutput, t('workshop.sampleJson'))">
                {{ t('common.copy') }}
              </a-button>
            </div>
            <pre>{{ sampleExtraction.editableOutput }}</pre>
          </details>

          <div class="processing-step-drawer__draft-actions">
            <a-button
              type="primary"
              long
              :loading="generating"
              :disabled="Boolean(editableJsonError)"
              @click="emit('confirmSampleGenerate')"
            >
              {{ t('workshop.confirmAndGenerateExtractionSkill') }}
            </a-button>
          </div>
          <p class="processing-step-drawer__action-note">
            {{ sampleConfirmHint }}
          </p>
        </div>
      </section>

      <section v-else-if="isExtractionTemplate && activeExtractSubTab === 'sample'" class="processing-step-drawer__empty">
        <template v-if="currentDraft?.runOption">
          <strong>{{ t('workshop.sampleFromSkillTrial') }}</strong>
          <p>{{ t('workshop.sampleFromSkillTrialDescription') }}</p>
          <div class="processing-step-drawer__result">
            <div class="processing-step-drawer__result-head">
              <span>{{ t('workshop.sampleOutput') }}</span>
              <a-button size="mini" @click="copyText(currentDraft.runOption.resultPreview, t('workshop.sampleOutput'))">
                {{ t('common.copy') }}
              </a-button>
            </div>
            <pre>{{ currentDraft.runOption.resultPreview || t('workshop.noOutput') }}</pre>
          </div>
        </template>
        <template v-else>
        <strong>{{ t('workshop.noSampleExtractionResult') }}</strong>
        <p>{{ sampleEmptyMessage }}</p>
        <a-button v-if="!hasLocatedInput" type="primary" @click="activeDrawerTab = 'locate'">
          {{ sampleEmptyActionLabel }}
        </a-button>
        </template>
      </section>

      <details
        v-if="isOperationWorkflow && sampleProcessingDraft"
        open
        class="processing-step-drawer__section processing-step-drawer__section--sample-result"
      >
        <summary class="processing-step-drawer__validation-summary">
          <span>
            <strong>{{ t('workshop.sampleProcessingResult') }}</strong>
            <em>{{ sampleProcessingSummary }}</em>
          </span>
          <a-tag :color="sampleProcessingDraft.status === 'confirmed' ? 'green' : sampleProcessingJsonError ? 'orange' : 'blue'">
            {{ sampleProcessingDraft.status === 'confirmed' ? t('workshop.confirmed') : t('workshop.pendingConfirm') }}
          </a-tag>
        </summary>

        <div class="processing-step-drawer__validation-body">
          <div v-if="sampleProcessingMeta" class="processing-step-drawer__meta-line">
            {{ sampleProcessingMeta }}
          </div>
          <a-alert
            v-if="sampleProcessingJsonError"
            type="warning"
            :show-icon="false"
            :content="t('workshop.jsonCannotConfirm', { error: sampleProcessingJsonError })"
          />
          <section class="processing-step-drawer__preview">
            <div class="processing-step-drawer__result-head">
              <span>{{ t('workshop.confirmedOutput') }}</span>
              <a-tag size="small">{{ sampleProcessingDraft.result.resultKind }}</a-tag>
            </div>
            <pre>{{ sampleProcessingPreview }}</pre>
          </section>

          <details class="processing-step-drawer__json-editor">
            <summary>{{ t('workshop.advancedViewJson') }}</summary>
            <div class="processing-step-drawer__raw-json-head">
              <span>{{ t('workshop.rawProcessingOutput') }}</span>
              <a-button size="mini" @click="copyText(sampleProcessingDraft.editableOutput, t('workshop.processingJson'))">
                {{ t('common.copy') }}
              </a-button>
            </div>
            <pre>{{ sampleProcessingDraft.editableOutput }}</pre>
          </details>

          <div class="processing-step-drawer__draft-actions">
            <a-button long :loading="sampleProcessing" @click="generateWithDefaults">
              {{ t('workshop.runProcessingAgain') }}
            </a-button>
            <a-button
              type="primary"
              long
              :loading="generating"
              :disabled="Boolean(sampleProcessingJsonError)"
              @click="emit('confirmSampleGenerate')"
            >
              {{ t('workshop.confirmAndGenerateProcessingSkill') }}
            </a-button>
          </div>
          <p class="processing-step-drawer__action-note">
            {{ sampleConfirmHint }}
          </p>
        </div>
      </details>

      <section v-else-if="isOperationWorkflow" class="processing-step-drawer__empty">
        <strong>{{ t('workshop.noSampleProcessingResult') }}</strong>
        <p>{{ t('workshop.noSampleProcessingResultDescription') }}</p>
        <div class="processing-step-drawer__empty-actions">
          <a-button @click="activeDrawerTab = 'locate'">
            {{ t('workshop.backToProcessingInput') }}
          </a-button>
          <a-button type="primary" :loading="sampleProcessing" @click="generateWithDefaults">
            {{ t('workshop.aiTrialProcessing') }}
          </a-button>
        </div>
      </section>

      <details
        v-if="currentDraft && canShowSkillValidation && (isOperationWorkflow || activeExtractSubTab === 'validation')"
        open
        class="processing-step-drawer__section processing-step-drawer__section--validation processing-step-drawer__section--skill-check"
      >
        <summary class="processing-step-drawer__validation-summary">
          <span>
            <strong>{{ currentDraft.kind === 'operation' ? t('workshop.processingSkillTrialValidation') : t('workshop.extractionSkillTrialValidation') }}</strong>
            <em>{{ currentDraft.skillName || currentDraft.dataTypeName }}</em>
          </span>
          <a-tag :color="activeStepRunState?.status === 'failed' || activeStepRunState?.status === 'needs_review' ? 'orange' : currentDraft.status === 'verified' || activeStepRunState?.status === 'completed' ? 'green' : 'blue'">
            {{ activeStepRunState ? stepRunStatusText : formatStepStatus(currentDraft) }}
          </a-tag>
        </summary>

        <div class="processing-step-drawer__validation-body">
          <div class="processing-step-drawer__dev-stages" :aria-label="t('workshop.skillDevelopmentAssetStatus')">
            <span
              v-for="stage in developmentStages"
              :key="stage.key"
              class="processing-step-drawer__dev-stage"
              :class="`is-${stage.status}`"
            >
              <strong>{{ stage.label }}</strong>
              <em>{{ stage.text }}</em>
            </span>
          </div>

          <div
            v-if="activeStepRunState"
            class="processing-step-drawer__step-run-status"
            :class="`is-${activeStepRunState.status}`"
          >
            <div>
              <strong>{{ stepRunStatusText }}</strong>
              <span>{{ activeStepRunState.message }}</span>
            </div>
            <em>{{ activeStepRunState.runId }}</em>
          </div>

          <details v-if="skillDevelopment" class="processing-step-drawer__run-meta">
            <summary>{{ t('workshop.runDiagnostics') }}</summary>
            <div class="processing-step-drawer__meta-line">
              {{ t('workshop.outputContractLine', { value: outputContractLine }) }}
            </div>
            <div class="processing-step-drawer__meta-line">
              {{ t('workshop.evidencePackageLine', { value: evidenceSummaryLine }) }}
            </div>
            <div v-if="developmentValidationChecks.length" class="processing-step-drawer__check-list">
              <span
                v-for="check in developmentValidationChecks"
                :key="String(check.key || check.label)"
                :class="`is-${String(check.status || 'pending')}`"
              >
                <strong>{{ localizePlatformDiagnostic(check.label || check.key) }}</strong>
                <em>{{ localizePlatformDiagnostic(check.detail || check.status || '') }}</em>
              </span>
            </div>
          </details>

          <a-alert
            v-if="currentDraft.errors.length"
            type="warning"
            :show-icon="false"
            :content="currentDraft.errors.join('；')"
          />
          <a-alert
            v-if="activeStepRunState?.validationErrors?.length"
            type="warning"
            :show-icon="false"
            :content="t('workshop.trialValidationErrors', { errors: activeStepRunState.validationErrors.join('；') })"
          />
          <div
            v-if="activeStepRunState?.resultPreview"
            class="processing-step-drawer__result"
          >
            <div class="processing-step-drawer__result-head">
              <span>{{ activeStepRunState.status === 'completed' ? t('workshop.currentTrialOutput') : t('workshop.currentTrialOutputWithDiagnostics') }}</span>
              <a-button size="mini" @click="copyText(activeStepRunState.resultPreview || '', t('workshop.trialOutput'))">
                {{ t('common.copy') }}
              </a-button>
            </div>
            <pre>{{ activeStepRunState.resultPreview }}</pre>
          </div>
          <div v-else-if="currentDraft.runOption" class="processing-step-drawer__result">
            <div class="processing-step-drawer__result-head">
              <span>{{ t('workshop.sampleOutput') }}</span>
              <a-button size="mini" @click="copyText(currentDraft.runOption.resultPreview, t('workshop.sampleOutput'))">
                {{ t('common.copy') }}
              </a-button>
            </div>
            <pre>{{ currentDraft.runOption.resultPreview || t('workshop.noOutput') }}</pre>
          </div>
          <a-alert
            v-if="shouldShowDraftRunHint"
            type="info"
            :show-icon="false"
            :content="draftRunHint"
          />
          <div class="processing-step-drawer__draft-actions">
            <a-button long @click="emit('openSkillEditor')">
              {{ t('workshop.editSkillMarkdown') }}
            </a-button>
            <a-button
              v-if="
                prototypeOptimizationEnabled !== false
                && currentDraft.kind === 'extraction'
                && (canCreatePrototype || skillDevelopment?.prototypeId)
              "
              long
              :loading="prototypeCreating"
              :disabled="!canCreatePrototype"
              @click="emit('createPrototype')"
            >
              {{ skillDevelopment?.prototypeId ? t('workshop.updateOptimizationProject') : t('workshop.createCandidateOptimizationProject') }}
            </a-button>
            <a-button type="primary" long :loading="runningStep || isStepRunActive" :disabled="isStepRunActive" @click="emit('saveRun')">
              {{ stepRunButtonText }}
            </a-button>
          </div>
        </div>
      </details>
      </section>
    </div>
    <a-modal
      :visible="locatorSkillModalVisible"
      :footer="false"
      :title="t('workshop.locatorSkillMarkdown')"
      :width="880"
      unmount-on-close
      @cancel="locatorSkillModalVisible = false"
    >
      <SkillMarkdownEditor
        :model-value="locatorSkillText"
        :title="t('workshop.locatorSkillMarkdown')"
        :description="t('workshop.locatorSkillMarkdownDescription')"
        default-mode="split"
        :copy-label="t('workshop.locatorSkill')"
        :min-height="520"
        show-save
        :save-label="t('workshop.saveLocatorSkill')"
        @update:model-value="emit('updateLocatorSkillText', $event)"
        @save="emit('saveLocatorSkill')"
      />
    </a-modal>
    <a-modal
      :visible="locatorModuleModalVisible"
      :footer="false"
      :title="locatorModuleModalTitle"
      :width="880"
      unmount-on-close
      @cancel="locatorModuleModalVisible = false"
    >
      <div class="processing-step-drawer__skill-modal">
        <div class="processing-step-drawer__skill-modal-head">
              <span>{{ locatorModuleModalMeta || t('workshop.matchedDocumentTreeContent') }}</span>
              <a-button size="mini" @click="copyText(locatorModuleModalText, t('workshop.matchedContent'))">
            {{ t('common.copy') }}
          </a-button>
        </div>
        <pre>{{ locatorModuleModalText }}</pre>
      </div>
    </a-modal>
  </a-drawer>
</template>

<style scoped>
.processing-step-drawer {
  display: grid;
  gap: 10px;
}

.processing-step-drawer__asset-header,
.processing-step-drawer__intro,
.processing-step-drawer__main,
.processing-step-drawer__section {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #d7dee8;
  background: #fff;
}

.processing-step-drawer__asset-header {
  gap: 6px;
  padding: 0 2px 8px;
  border: 0;
  border-bottom: 1px solid #e2e8f0;
  background: transparent;
}

.processing-step-drawer__asset-header > div {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.processing-step-drawer__asset-header span {
  color: #475569;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__asset-header strong {
  min-width: 0;
  color: #0f172a;
  font-size: 16px;
  font-weight: 900;
  line-height: 1.35;
}

.processing-step-drawer__asset-header p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.processing-step-drawer__intro {
  border-left: 3px solid #2563eb;
  background: #fbfdff;
}

.processing-step-drawer__intro-head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.processing-step-drawer__intro-head > span {
  flex: 0 0 auto;
  width: fit-content;
  padding: 3px 7px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__intro-head > strong {
  min-width: 0;
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__intro > p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.65;
}

.processing-step-drawer__tabs {
  display: flex;
  gap: 8px;
  padding: 0 0 2px;
}

.processing-step-drawer__tabs button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
  min-height: 38px;
  padding: 6px 10px;
  border: 1px solid #d7dee8;
  border-radius: 3px;
  background: #fff;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.processing-step-drawer__tabs button.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px #2563eb;
}

.processing-step-drawer__tabs i {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
}

.processing-step-drawer__tabs strong {
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
}

.processing-step-drawer__tabs span {
  display: grid;
  gap: 1px;
  min-width: 0;
}

.processing-step-drawer__tabs em {
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__tabs button.is-active strong,
.processing-step-drawer__tabs button.is-active em {
  color: #1d4ed8;
}

.processing-step-drawer__tabs button.is-active i {
  background: #2563eb;
  color: #fff;
}

.processing-step-drawer__tab-panel {
  display: grid;
  gap: 10px;
}

.processing-step-drawer__subtabs {
  display: flex;
  gap: 8px;
  padding: 8px;
  border: 1px solid #d7dee8;
  background: #fff;
}

.processing-step-drawer__subtabs button {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #d7dee8;
  border-radius: 3px;
  background: #fff;
  color: #334155;
  cursor: pointer;
  font: inherit;
}

.processing-step-drawer__subtabs button.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px #2563eb;
}

.processing-step-drawer__subtabs button:disabled {
  cursor: not-allowed;
  opacity: .48;
}

.processing-step-drawer__subtabs strong {
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.processing-step-drawer__subtabs span {
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__subtabs button.is-active strong,
.processing-step-drawer__subtabs button.is-active span {
  color: #1d4ed8;
}

.processing-step-drawer__section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.processing-step-drawer__section--validation,
.processing-step-drawer__section--sample-result,
.processing-step-drawer__section--locator {
  padding: 0;
}

.processing-step-drawer__section--sample-result,
.processing-step-drawer__section--locator {
  border-color: #bfdbfe;
  background: #fbfdff;
}

.processing-step-drawer__validation-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 44px;
  padding: 0 12px;
  cursor: pointer;
  list-style: none;
}

.processing-step-drawer__static-summary {
  cursor: default;
}

.processing-step-drawer__static-summary::before {
  display: none;
  content: none;
}

.processing-step-drawer__validation-summary::-webkit-details-marker {
  display: none;
}

.processing-step-drawer__validation-summary::before {
  content: '▸';
  flex: 0 0 auto;
  color: #64748b;
  font-size: 12px;
}

.processing-step-drawer__section--validation[open] .processing-step-drawer__validation-summary::before,
.processing-step-drawer__section--sample-result[open] .processing-step-drawer__validation-summary::before,
.processing-step-drawer__section--locator[open] .processing-step-drawer__validation-summary::before {
  content: '▾';
}

.processing-step-drawer__validation-summary > span {
  display: grid;
  gap: 2px;
  min-width: 0;
  margin-right: auto;
}

.processing-step-drawer__validation-summary strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 850;
}

.processing-step-drawer__validation-summary em {
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__summary-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex: 0 0 auto;
}

.processing-step-drawer__validation-body {
  display: grid;
  gap: 10px;
  padding: 10px 12px 12px;
  border-top: 1px solid #e2e8f0;
}

.processing-step-drawer__meta-line {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.processing-step-drawer__trace-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.processing-step-drawer__trace-line span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__locator-summary,
.processing-step-drawer__locator-overview,
.processing-step-drawer__located-source,
.processing-step-drawer__candidate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.processing-step-drawer__locator-summary {
  padding: 9px 10px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
}

.processing-step-drawer__locator-overview {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(96px, .6fr);
  padding: 9px 10px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
}

.processing-step-drawer__locator-overview > div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.processing-step-drawer__locator-summary span {
  color: #2563eb;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__locator-summary strong,
.processing-step-drawer__locator-overview strong {
  min-width: 0;
  color: #0f172a;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__locator-overview span {
  color: #2563eb;
  font-size: 11px;
  font-weight: 850;
}

.processing-step-drawer__located-stack {
  display: grid;
  gap: 5px;
}

.processing-step-drawer__located-source {
  min-height: 48px;
  padding: 7px 10px;
  border: 1px solid #d7dee8;
  background: #fff;
}

.processing-step-drawer__located-source-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex: 0 0 auto;
}

.processing-step-drawer__asset-card,
.processing-step-drawer__review-card,
.processing-step-drawer__empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border: 1px solid #bfdbfe;
  background: #f8fbff;
}

.processing-step-drawer__asset-card > div,
.processing-step-drawer__review-card,
.processing-step-drawer__empty {
  min-width: 0;
}

.processing-step-drawer__asset-card span {
  display: block;
  margin-bottom: 2px;
  color: #2563eb;
  font-size: 11px;
  font-weight: 850;
}

.processing-step-drawer__asset-card strong,
.processing-step-drawer__review-card strong,
.processing-step-drawer__empty strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
}

.processing-step-drawer__asset-card p,
.processing-step-drawer__review-card p,
.processing-step-drawer__empty p {
  margin: 3px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.processing-step-drawer__review-card,
.processing-step-drawer__empty {
  display: grid;
  justify-items: start;
}

.processing-step-drawer__empty-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.processing-step-drawer__located-source > div,
.processing-step-drawer__candidate > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.processing-step-drawer__located-source strong,
.processing-step-drawer__candidate strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 850;
  overflow: hidden;
  text-overflow: ellipsis;
}

.processing-step-drawer__located-source span,
.processing-step-drawer__located-source em,
.processing-step-drawer__candidate span,
.processing-step-drawer__candidate em,
.processing-step-drawer__locator-reason {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.5;
}

.processing-step-drawer__located-source span,
.processing-step-drawer__candidate span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__candidate-list {
  display: grid;
  gap: 8px;
}

.processing-step-drawer__locator-skill {
  border: 1px solid #d7dee8;
  background: #fff;
}

.processing-step-drawer__locator-skill .processing-step-drawer__locator-reason {
  padding: 0 10px 8px;
}

.processing-step-drawer__locator-skill :deep(.arco-alert) {
  margin: 0 10px 8px;
}

.processing-step-drawer__locator-skill summary {
  padding: 9px 10px;
  color: #1d4ed8;
  cursor: pointer;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__locator-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 10px 10px;
}

.processing-step-drawer__locator-chips span {
  max-width: 100%;
  padding: 4px 7px;
  color: #475569;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  font-size: 11px;
  line-height: 1.4;
}

.processing-step-drawer__locator-skill pre {
  max-height: 220px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border-top: 1px solid #e2e8f0;
  color: #334155;
  background: #f8fafc;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.processing-step-drawer__candidate {
  padding: 8px 10px;
  border: 1px solid #d7dee8;
  background: #fff;
}

.processing-step-drawer__candidate-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.processing-step-drawer__section--skill-check .processing-step-drawer__validation-body {
  padding-top: 10px;
}

.processing-step-drawer__skill-modal {
  display: grid;
  gap: 10px;
}

.processing-step-drawer__skill-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.processing-step-drawer__skill-modal-head span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__skill-modal pre {
  max-height: min(68vh, 640px);
  margin: 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid #d7dee8;
  border-radius: 3px;
  color: #334155;
  background: #f8fafc;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.processing-step-drawer__section-title strong,
.processing-step-drawer__draft b {
  color: #0f172a;
  font-weight: 850;
}

.processing-step-drawer__section-title span,
.processing-step-drawer__field > span,
.processing-step-drawer__sample span,
.processing-step-drawer__draft span,
.processing-step-drawer__result span,
.processing-step-drawer__preview span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.processing-step-drawer__source-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.processing-step-drawer__source-switch button {
  display: grid;
  gap: 4px;
  min-height: 54px;
  padding: 9px 10px;
  border: 1px solid #d7dee8;
  border-radius: 3px;
  background: #fff;
  color: #334155;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.processing-step-drawer__source-switch button strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 850;
}

.processing-step-drawer__source-switch button span {
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.processing-step-drawer__source-switch button:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.processing-step-drawer__source-switch button.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #fff;
  box-shadow: inset 0 0 0 1px #2563eb;
}

.processing-step-drawer__source-switch button.is-active strong,
.processing-step-drawer__source-switch button.is-active span {
  color: #1d4ed8;
}

.processing-step-drawer__sample {
  display: grid;
  gap: 4px;
  padding: 8px;
  border-left: 3px solid #2563eb;
  background: #f8fbff;
}

.processing-step-drawer__sample strong {
  color: #0f172a;
  font-weight: 850;
}

.processing-step-drawer__note {
  margin: 0;
  padding: 7px 9px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1e40af;
  font-size: 12px;
  line-height: 1.55;
}

.processing-step-drawer__source-more {
  border-top: 1px solid #e2e8f0;
  padding-top: 8px;
}

.processing-step-drawer__source-more summary {
  width: fit-content;
  color: #2563eb;
  cursor: pointer;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__source-more[open] summary {
  margin-bottom: 8px;
}

.processing-step-drawer__source-more p {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.processing-step-drawer__guided {
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid #bfdbfe;
  background: #f8fbff;
}

.processing-step-drawer__guided > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.processing-step-drawer__guided span {
  color: #2563eb;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__guided strong {
  color: #0f172a;
  font-size: 16px;
  font-weight: 900;
}

.processing-step-drawer__guided p {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.processing-step-drawer__recommendation {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 8px;
  row-gap: 4px;
  align-items: center;
  padding: 10px;
  border: 1px solid #bfdbfe;
  background: #f8fbff;
}

.processing-step-drawer__recommendation span {
  color: #2563eb;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__recommendation strong {
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
}

.processing-step-drawer__recommendation p {
  grid-column: 1 / -1;
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.processing-step-drawer__main--compact {
  gap: 10px;
  padding: 12px;
}

.processing-step-drawer__compact-status {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 6px 9px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.processing-step-drawer__compact-status span {
  color: #2563eb;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__compact-status strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
}

.processing-step-drawer__prompt-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.processing-step-drawer__prompt-grid--locate {
  grid-template-columns: minmax(220px, .78fr) minmax(0, 1.22fr);
}

.processing-step-drawer__action-row {
  display: flex;
  justify-content: flex-end;
}

.processing-step-drawer__action-row :deep(.arco-btn) {
  min-width: 180px;
}

.processing-step-drawer__field {
  display: grid;
  gap: 5px;
}

.processing-step-drawer__field :deep(.arco-input-wrapper),
.processing-step-drawer__field :deep(.arco-textarea-wrapper),
.processing-step-drawer :deep(.arco-btn) {
  border-radius: 3px;
}

.processing-step-drawer__optional {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.processing-step-drawer__optional summary {
  padding: 9px 10px;
  color: #334155;
  cursor: pointer;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__optional .processing-step-drawer__field {
  padding: 0 10px 10px;
}

.processing-step-drawer__optional .processing-step-drawer__recommendation {
  margin: 0 10px 10px;
}

@media (max-width: 760px) {
  .processing-step-drawer__tabs {
    display: grid;
    grid-template-columns: 1fr;
  }

  .processing-step-drawer__subtabs {
    display: grid;
    grid-template-columns: 1fr;
  }

  .processing-step-drawer__prompt-grid,
  .processing-step-drawer__prompt-grid--locate {
    grid-template-columns: 1fr;
  }

  .processing-step-drawer__action-row :deep(.arco-btn) {
    width: 100%;
  }
}

.processing-step-drawer__draft {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid #dfe6ef;
  background: #fbfdff;
}

.processing-step-drawer__draft > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.processing-step-drawer__draft-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}

.processing-step-drawer__action-note {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.processing-step-drawer__dev-stages {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}

.processing-step-drawer__dev-stage {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid #dfe6ef;
  background: #f8fafc;
}

.processing-step-drawer__dev-stage strong,
.processing-step-drawer__dev-stage em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__dev-stage strong {
  color: #0f172a;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__dev-stage em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.processing-step-drawer__dev-stage.is-done {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.processing-step-drawer__dev-stage.is-failed {
  border-color: #fed7aa;
  background: #fff7ed;
}

.processing-step-drawer__dev-stage.is-needs_review {
  border-color: #fde68a;
  background: #fffbeb;
}

.processing-step-drawer__dev-stage.is-running {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.processing-step-drawer__step-run-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}

.processing-step-drawer__step-run-status > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.processing-step-drawer__step-run-status strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 850;
}

.processing-step-drawer__step-run-status span,
.processing-step-drawer__step-run-status em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}

.processing-step-drawer__step-run-status em {
  flex: 0 0 auto;
  padding: 2px 6px;
  border: 1px solid #d7dee8;
  background: #fff;
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.processing-step-drawer__step-run-status.is-completed {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.processing-step-drawer__step-run-status.is-failed {
  border-color: #fed7aa;
  background: #fff7ed;
}

.processing-step-drawer__step-run-status.is-needs_review {
  border-color: #fde68a;
  background: #fffbeb;
}

.processing-step-drawer__check-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.processing-step-drawer__check-list > span {
  display: grid;
  gap: 3px;
  padding: 7px 8px;
  border: 1px solid #e2e8f0;
  background: #fff;
}

.processing-step-drawer__check-list strong {
  color: #0f172a;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__check-list em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}

.processing-step-drawer__check-list > span.is-failed {
  border-color: #fed7aa;
  background: #fff7ed;
}

.processing-step-drawer__check-list > span.is-passed {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.processing-step-drawer__result {
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
}

.processing-step-drawer__result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.processing-step-drawer__preview-list {
  display: grid;
  gap: 10px;
}

.processing-step-drawer__sample-metrics {
  width: fit-content;
  padding: 5px 8px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
}

.processing-step-drawer__business-editor {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #dbeafe;
  background: #f8fbff;
}

.processing-step-drawer__field-editor,
.processing-step-drawer__table-editor {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.processing-step-drawer__field-row {
  display: grid;
  grid-template-columns: minmax(110px, .8fr) minmax(130px, 1fr) minmax(92px, .55fr) 48px;
  gap: 6px;
  align-items: center;
}

.processing-step-drawer__editor-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.processing-step-drawer__header-editor {
  display: grid;
  gap: 4px;
  min-width: 120px;
}

.processing-step-drawer__action-cell {
  width: 56px;
  min-width: 56px;
  text-align: center;
}

.processing-step-drawer__preview {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.processing-step-drawer__preview pre {
  max-height: 260px;
  margin: 0;
  overflow: auto;
  padding: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #0f172a;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.processing-step-drawer__table-wrap {
  max-height: min(50vh, 520px);
  overflow: auto;
  border: 1px solid #e2e8f0;
  background: #fff;
}

.processing-step-drawer__table-wrap--editor {
  max-height: min(46vh, 420px);
}

.processing-step-drawer__table-wrap table {
  width: 100%;
  min-width: 620px;
  border-collapse: collapse;
  font-size: 12px;
}

.processing-step-drawer__table-wrap th,
.processing-step-drawer__table-wrap td {
  max-width: 220px;
  padding: 8px 9px;
  border-bottom: 1px solid #e2e8f0;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-step-drawer__table-wrap th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8fafc;
  color: #64748b;
  font-weight: 850;
  text-align: left;
}

.processing-step-drawer__table-semantics {
  display: grid;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid #dbeafe;
  background: #f8fbff;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

.processing-step-drawer__table-semantics > div {
  display: grid;
  gap: 3px;
}

.processing-step-drawer__table-semantics strong {
  color: #1e3a8a;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__table-wrap :deep(.arco-input-wrapper) {
  min-width: 96px;
  border-radius: 3px;
}

.processing-step-drawer__kv-list {
  display: grid;
  gap: 6px;
}

.processing-step-drawer__kv-list > div {
  display: grid;
  grid-template-columns: minmax(120px, .42fr) minmax(0, 1fr);
  gap: 8px;
  padding: 8px 9px;
  border: 1px solid #e2e8f0;
  background: #fff;
}

.processing-step-drawer__kv-list strong {
  color: #0f172a;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__json-editor {
  border: 1px solid #e2e8f0;
  background: #fff;
}

.processing-step-drawer__json-editor summary {
  padding: 9px 10px;
  color: #334155;
  cursor: pointer;
  font-size: 12px;
  font-weight: 850;
}

.processing-step-drawer__raw-json-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border-top: 1px solid #e2e8f0;
  color: #64748b;
  font-size: 12px;
}

.processing-step-drawer__json-editor pre {
  max-height: 260px;
  margin: 0;
  overflow: auto;
  padding: 10px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.processing-step-drawer__result pre {
  max-height: min(52vh, 520px);
  margin: 0;
  overflow: auto;
  color: #14532d;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.processing-step-drawer__capability-alert {
  border-radius: 4px;
}

.processing-step-drawer__capability-alert-body {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  line-height: 1.5;
}

.processing-step-drawer__capability-alert-body a {
  color: #2563eb;
  font-weight: 800;
}

</style>
