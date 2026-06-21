import type {
  ApplicationRunDetail,
  ApplicationRunPlanResponse,
  ApplicationRunPlanStep,
  ApplicationRunStepSummary,
} from '../types/workbench'

export type ApplicationPlanCandidate = {
  nodeId: string
  title: string
  excerpt: string
  pageNo: number
  score: number
  reasons: string[]
  warnings: string[]
}

export type ApplicationStepEvidenceItem = {
  sourceType: string
  pageNo: number
  title: string
  excerpt: string
  selectedRowCount?: number
  totalRowCount?: number
  uncertainties: string[]
}

export type ApplicationStepTableRiskItem = {
  pageNo: number
  title: string
  rowCount?: number
  columnCount?: number
  severity: string
  uncertainties: string[]
}

export function formatApplicationRunStatus(run: ApplicationRunDetail | null | undefined) {
  const status = run?.status
  if (status === 'completed') return '已完成'
  if (status === 'running') return '运行中'
  if (status === 'failed') return '失败'
  if (status === 'needs_review') return '需复核'
  if (status === 'pending') return '等待中'
  return '未运行'
}

export function formatApplicationStepKind(kind: string) {
  if (kind === 'extraction') return '抽取'
  if (kind === 'operation') return '处理'
  return kind || '步骤'
}

export function formatApplicationStepStatus(status: string) {
  if (status === 'completed') return '已完成'
  if (status === 'running') return '运行中'
  if (status === 'failed') return '失败'
  if (status === 'needs_review') return '需复核'
  if (status === 'pending') return '等待中'
  return status || '未知'
}

export function getApplicationStepScope(
  step: Pick<ApplicationRunStepSummary, 'inputMapping' | 'targetMapping'>,
) {
  const inputMapping = step.inputMapping ?? {}
  const targetMapping = step.targetMapping ?? {}
  const contentRefs = Array.isArray(inputMapping.contentRefs) ? inputMapping.contentRefs : []
  const matchedPageNos = Array.isArray(inputMapping.matchedPageNos) ? inputMapping.matchedPageNos : []
  const locatorResult = targetMapping.locatorResult && typeof targetMapping.locatorResult === 'object'
    ? targetMapping.locatorResult as Record<string, unknown>
    : {}
  const selectedNodeIds = Array.isArray(locatorResult.selectedNodeIds) ? locatorResult.selectedNodeIds : []
  const parts = [
    contentRefs.length ? `${contentRefs.length} 个命中模块` : '',
    matchedPageNos.length ? `页码 ${matchedPageNos.join('、')}` : '',
    selectedNodeIds.length && !contentRefs.length ? `${selectedNodeIds.length} 个定位节点` : '',
  ].filter(Boolean)
  return parts.join(' · ') || '按应用步骤配置执行'
}

export function getApplicationStepOutput(
  step: Pick<ApplicationRunStepSummary, 'outputSummary' | 'executionRunId'>,
) {
  const summary = step.outputSummary ?? {}
  const direct = String(summary.summary || summary.resultSummary || summary.preview || '').trim()
  if (direct) return direct
  const parts = [
    typeof summary.outputCount === 'number' ? `${summary.outputCount} 个输出` : '',
    typeof summary.recordCount === 'number' ? `${summary.recordCount} 条记录` : '',
    typeof summary.rowCount === 'number' ? `${summary.rowCount} 行` : '',
  ].filter(Boolean)
  if (parts.length) return parts.join(' · ')
  return step.executionRunId ? `运行结果：${step.executionRunId}` : '尚无输出'
}

export function getApplicationStepEvidenceScope(
  step: Pick<ApplicationRunStepSummary, 'outputSummary'>,
) {
  const summary = step.outputSummary ?? {}
  const selection = toRecord(summary.evidenceSelection)
  if (!Object.keys(selection).length) return ''
  const parts = [
    formatEvidenceMode(selection.mode),
    selection.expansionLevel ? `范围 ${String(selection.expansionLevel)}` : '',
    formatEvidencePages(selection.selectedPageNos),
    typeof selection.selectedBlockCount === 'number' ? `${selection.selectedBlockCount} 个证据块` : '',
    formatEvidenceRows(selection),
  ].filter(Boolean)
  return parts.join(' · ')
}

export function getApplicationStepEvidenceMetrics(
  step: Pick<ApplicationRunStepSummary, 'outputSummary'>,
) {
  const metrics = toRecord(step.outputSummary?.runMetrics)
  const tableReviewRisk = toRecord(metrics.tableReviewRisk)
  const evidenceSelectMs = (
    typeof metrics.evidenceBuildMs === 'number' || typeof metrics.candidateSelectMs === 'number'
  )
    ? Number(metrics.evidenceBuildMs || 0) + Number(metrics.candidateSelectMs || 0)
    : null
  const items = [
    typeof metrics.durationMs === 'number' ? `耗时 ${formatDuration(metrics.durationMs)}` : '',
    typeof metrics.totalTokens === 'number' ? `Token ${metrics.totalTokens}` : '',
    typeof metrics.inputPayloadBytes === 'number' ? `模型输入 ${formatBytes(metrics.inputPayloadBytes)}` : '',
    typeof metrics.factsBytes === 'number' && typeof metrics.fullFactsBytes === 'number'
      ? `证据 ${formatBytes(metrics.factsBytes)}/${formatBytes(metrics.fullFactsBytes)}`
      : '',
    typeof metrics.tableRowCount === 'number' && typeof metrics.fullTableRowCount === 'number'
      ? `表格行 ${metrics.tableRowCount}/${metrics.fullTableRowCount}`
      : '',
    typeof metrics.selectedEvidenceCount === 'number' ? `选中 ${metrics.selectedEvidenceCount} 块` : '',
    typeof metrics.skippedEvidenceCount === 'number' ? `跳过 ${metrics.skippedEvidenceCount} 块` : '',
    evidenceSelectMs !== null ? `证据选择 ${formatDuration(evidenceSelectMs)}` : '',
    typeof metrics.modelCallMs === 'number' ? `主模型 ${formatDuration(metrics.modelCallMs)}` : '',
    typeof metrics.reviewCallMs === 'number' && metrics.reviewCallMs > 0
      ? `复核模型 ${formatDuration(metrics.reviewCallMs)}`
      : '',
    typeof metrics.fastPathPreviewMs === 'number' && metrics.fastPathPreviewMs > 0
      ? `列判断 ${formatDuration(metrics.fastPathPreviewMs)}`
      : '',
    typeof metrics.localStructuredBuildMs === 'number' && metrics.localStructuredBuildMs > 0
      ? `本地生成 ${formatDuration(metrics.localStructuredBuildMs)}`
      : '',
    typeof tableReviewRisk.riskTableCount === 'number' && tableReviewRisk.riskTableCount > 0
      ? `风险表格 ${tableReviewRisk.riskTableCount}`
      : '',
    typeof tableReviewRisk.criticalTableCount === 'number' && tableReviewRisk.criticalTableCount > 0
      ? `需复核表格 ${tableReviewRisk.criticalTableCount}`
      : '',
    typeof metrics.reviewCount === 'number' && metrics.reviewCount > 0 ? `复核 ${metrics.reviewCount} 次` : '',
  ].filter(Boolean)
  return items
}

export function hasApplicationStepDiagnostics(
  step: Pick<ApplicationRunStepSummary, 'outputSummary'>,
) {
  return Boolean(
    getApplicationStepEvidenceScope(step)
    || getApplicationStepEvidenceMetrics(step).length
    || getApplicationStepEvidenceItems(step).length
    || getApplicationStepEvidenceWarnings(step).length
    || getApplicationStepTableRiskItems(step).length,
  )
}

export function getApplicationStepEvidenceWarnings(
  step: Pick<ApplicationRunStepSummary, 'outputSummary'>,
) {
  const warnings = step.outputSummary?.evidenceWarnings
  if (!Array.isArray(warnings)) return []
  return warnings.map(String).filter(Boolean).slice(0, 3)
}

export function getApplicationStepTableRiskItems(
  step: Pick<ApplicationRunStepSummary, 'outputSummary'>,
): ApplicationStepTableRiskItem[] {
  const metrics = toRecord(step.outputSummary?.runMetrics)
  const risk = toRecord(metrics.tableReviewRisk)
  const risks = Array.isArray(risk.risks) ? risk.risks : []
  return risks
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .slice(0, 4)
    .map((item) => ({
      pageNo: typeof item.pageNo === 'number' ? item.pageNo : Number(item.pageNo || 0),
      title: String(item.title || item.blockId || item.sourceOrdinal || '表格'),
      rowCount: typeof item.rowCount === 'number' ? item.rowCount : undefined,
      columnCount: typeof item.columnCount === 'number' ? item.columnCount : undefined,
      severity: String(item.severity || ''),
      uncertainties: Array.isArray(item.uncertainties) ? item.uncertainties.map(String).filter(Boolean) : [],
    }))
}

export function getApplicationStepEvidenceItems(
  step: Pick<ApplicationRunStepSummary, 'outputSummary'>,
): ApplicationStepEvidenceItem[] {
  const selection = toRecord(step.outputSummary?.evidenceSelection)
  const items = Array.isArray(selection.selectedEvidence) ? selection.selectedEvidence : []
  return items
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .slice(0, 4)
    .map((item) => ({
      sourceType: String(item.sourceType || ''),
      pageNo: typeof item.pageNo === 'number' ? item.pageNo : Number(item.pageNo || 0),
      title: String(item.title || item.sourceOrdinal || ''),
      excerpt: String(item.excerpt || ''),
      selectedRowCount: typeof item.selectedRowCount === 'number' ? item.selectedRowCount : undefined,
      totalRowCount: typeof item.totalRowCount === 'number' ? item.totalRowCount : undefined,
      uncertainties: Array.isArray(item.uncertainties) ? item.uncertainties.map(String).filter(Boolean) : [],
    }))
}

function toRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function formatEvidenceMode(value: unknown) {
  const mode = String(value || '')
  if (mode === 'field_list_selected_evidence') return '字段证据包'
  if (mode === 'record_collection_selected_evidence') return '记录证据预览'
  if (mode === 'full_facts') return '完整事实'
  return mode || '证据包'
}

function formatEvidencePages(value: unknown) {
  if (Array.isArray(value) && value.length) {
    return `页码 ${value.map(String).join('、')}`
  }
  if (value === 'all') return '全部页'
  return ''
}

function formatEvidenceRows(selection: Record<string, unknown>) {
  const selected = selection.selectedTableRowCount
  const total = selection.totalTableRowCount
  if (typeof selected === 'number' && typeof total === 'number' && total > 0) {
    return `表格行 ${selected}/${total}`
  }
  return ''
}

function formatDuration(value: number) {
  if (value < 1000) return `${Math.round(value)}ms`
  return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}s`
}

function formatBytes(value: number) {
  if (value < 1024) return `${Math.max(0, Math.round(value))}B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value >= 10 * 1024 ? 0 : 1)}KB`
  return `${(value / 1024 / 1024).toFixed(1)}MB`
}

export function formatApplicationPlanStatus(status: ApplicationRunPlanResponse['status']) {
  if (status === 'ready') return '可执行'
  if (status === 'needs_review') return '需确认'
  if (status === 'blocked') return '已阻断'
  return status
}

export function getApplicationPlanStepScope(step: ApplicationRunPlanStep) {
  const targetCount = step.targets?.length ?? 0
  const candidateCount = getApplicationPlanCandidates(step).length
  const parts = [
    targetCount ? `${targetCount} 个自动命中` : '',
    candidateCount ? `${candidateCount} 个候选` : '',
    typeof step.confidence === 'number' ? `置信度 ${Math.round(step.confidence * 100)}%` : '',
    step.candidateGap ? `差距 ${step.candidateGap}` : '',
  ].filter(Boolean)
  return parts.join(' · ') || '未召回候选'
}

export function getApplicationPlanStepPreview(step: ApplicationRunPlanStep) {
  const firstTarget = step.targets?.[0]
  const firstCandidate = getApplicationPlanCandidates(step)[0]
  const label = firstTarget?.label || ''
  const excerpt = firstTarget?.excerpt || firstCandidate?.excerpt || ''
  const warning = step.warnings?.[0] || ''
  return [label || firstCandidate?.title, warning || step.reason, excerpt].filter(Boolean).slice(0, 3).join(' / ')
}

export function getApplicationPlanCandidates(step: ApplicationRunPlanStep): ApplicationPlanCandidate[] {
  const locatorResult = step.locatorResult && typeof step.locatorResult === 'object'
    ? step.locatorResult as Record<string, unknown>
    : {}
  const candidates = Array.isArray(locatorResult.candidates) ? locatorResult.candidates : []
  return candidates
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      nodeId: String(item.nodeId || item.targetId || ''),
      title: String(item.title || item.label || ''),
      excerpt: String(item.excerpt || ''),
      pageNo: typeof item.pageNo === 'number' ? item.pageNo : Number(item.pageNo || 0),
      score: typeof item.score === 'number' ? item.score : Number(item.score || 0),
      reasons: Array.isArray(item.reasons) ? item.reasons.map(String) : [],
      warnings: Array.isArray(item.warnings) ? item.warnings.map(String) : [],
    }))
}

export function formatApplicationPlanCandidate(candidate: ApplicationPlanCandidate) {
  const parts = [
    candidate.pageNo ? `第 ${candidate.pageNo} 页` : '',
    Number.isFinite(candidate.score) ? `分数 ${Math.round(candidate.score * 100)}%` : '',
    candidate.reasons[0] || '',
    candidate.warnings[0] ? `风险：${candidate.warnings[0]}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}
