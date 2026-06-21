<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import JsonTreeView from './JsonTreeView.vue'
import { startHorizontalDragScroll } from '../utils/dragScroll'
import { buildLlmTraceDisplayItems } from '../utils/llmTrace'
import { t } from '../i18n'
import type {
  ExtractionOutputItem,
  ExtractionStructuredObjectItem,
  ExtractionTableItem,
  OperationTarget,
  OperationTargetType,
  PageResultDetail,
  ResultStatus,
  WorkbenchMarkdownSegment,
  WorkbenchMarkdownSegmentLike,
  DocumentTreeNode,
  WorkbenchPage,
  WorkbenchDocumentTree,
} from '../types/workbench'
import type { DocumentTreeSource } from '../types/applicationWorkshop'

type ParseResultTabKey = 'recognition' | 'tree' | 'extract'

interface TableViewModel {
  key: string
  title: string
  headers: string[]
  rows: string[][]
}

interface OcrSegmentViewModel {
  id: string
  html: string
  type: string
  table: TableViewModel | null
}

interface DocumentTreeItem extends DocumentTreeSource {
  id: string
  depth: number
  type: string
  typeLabel: string
  label: string
  meta: string
  preview: string
  rawNode: DocumentTreeNode
}

const props = defineProps<{
  page: WorkbenchPage | null
  documentTree?: WorkbenchDocumentTree | null
  result: PageResultDetail | null
  resultStatus?: ResultStatus | null
  activeTab?: ParseResultTabKey
  operationTargets?: OperationTarget[]
  selectedTargetId?: string
  selectedTreeNodeId?: string
}>()

const emit = defineEmits<{
  'update:activeTab': [value: ParseResultTabKey]
  'selectTarget': [target: OperationTarget]
  'selectTreeNode': [node: DocumentTreeSource]
}>()

const tabOptions = computed(() => [
  { key: 'recognition' as const, label: t('parse.recognitionResult') },
  { key: 'tree' as const, label: t('parse.documentTree') },
  { key: 'extract' as const, label: t('parse.extractionResult') },
])

const internalActiveTab = ref<ParseResultTabKey>('recognition')
const activeTab = computed({
  get: () => props.activeTab ?? internalActiveTab.value,
  set: (value: ParseResultTabKey) => {
    internalActiveTab.value = value
    emit('update:activeTab', value)
  },
})

const extractionResult = computed(() => props.result?.extractionResult ?? null)
const extractionOutputs = computed(() => extractionResult.value?.outputs ?? [])
const extractionFields = computed(() => extractionResult.value?.fields ?? [])
const extractionTables = computed(() => extractionResult.value?.tables ?? [])
const extractionStructuredObjects = computed(() => extractionResult.value?.structuredObjects ?? [])
const extractionSummary = computed(() => extractionResult.value?.summary?.trim() ?? '')
const extractionValidationErrors = computed(() => extractionResult.value?.validationErrors ?? [])
const extractionErrors = computed(() => uniqueStrings([
  ...(extractionResult.value?.errors ?? []),
  ...extractionValidationErrors.value,
]))
const isStructureProcessing = computed(() => props.resultStatus === 'processing')
const llmTraceItems = computed(() => buildLlmTraceDisplayItems(props.result?.llmTraceSummary))

const hasExtractContent = computed(
  () =>
    extractionOutputs.value.length > 0
    || extractionFields.value.length > 0
    || extractionTables.value.length > 0
    || extractionStructuredObjects.value.length > 0
    || Boolean(extractionSummary.value)
    || extractionErrors.value.length > 0,
)

const expandedPaths = reactive(new Set<string>())
const copiedJsonAction = ref('')
const fullscreenTable = ref<TableViewModel | null>(null)
const documentTreeItems = computed(() => buildDocumentTreeItems(props.documentTree?.tree ?? null))
const documentTreeStatusText = computed(() => {
  if (!props.documentTree?.tree) return t('parse.documentTreeNotGenerated')
  return t('parse.structureNodeCount', { count: documentTreeItems.value.length })
})

let copyJsonFeedbackTimer: number | undefined

function toggleJsonPath(path: string) {
  if (expandedPaths.has(path)) {
    expandedPaths.delete(path)
  } else {
    expandedPaths.add(path)
  }
}

function getJsonText(data: unknown) {
  return JSON.stringify(data, null, 2)
}

function getOutputCopyActionKey(output: ExtractionOutputItem, index: number) {
  return `extract-output-${output.id || index}`
}

function getOutputCopyData(output: ExtractionOutputItem) {
  return output.data === undefined ? output : output.data
}

function fallbackCopyText(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'readonly')
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    document.execCommand('copy')
  } finally {
    document.body.removeChild(textarea)
  }
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  fallbackCopyText(value)
}

async function copyJsonData(actionKey: string, data: unknown) {
  await copyText(getJsonText(data))
  copiedJsonAction.value = actionKey
  if (copyJsonFeedbackTimer) {
    window.clearTimeout(copyJsonFeedbackTimer)
  }
  copyJsonFeedbackTimer = window.setTimeout(() => {
    copiedJsonAction.value = ''
  }, 1400)
}

const tableCount = computed(() =>
  Array.isArray(props.page?.rawItems) ? props.page.rawItems.filter((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return false
    const record = item as Record<string, unknown>
    return String(record.type ?? '').toLowerCase() === 'table' && Boolean(getRawTableHtml(record))
  }).length : 0,
)

function sanitizeRawTableHtml(value: string) {
  return value.replace(/<img[\s\S]*?>/gi, '').replace(/\s{2,}/g, ' ')
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function getContentPayload(record: Record<string, unknown>) {
  const content = record.content
  return content && typeof content === 'object' && !Array.isArray(content)
    ? content as Record<string, unknown>
    : {}
}

function collectTextParts(value: unknown): string[] {
  if (value === null || value === undefined) return []
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    const text = String(value).trim()
    return text ? [text] : []
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectTextParts(item)).filter(Boolean)
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    const keys = [
      'content',
      'text',
      'item_content',
      'children',
      'title_content',
      'paragraph_content',
      'page_header_content',
      'page_footer_content',
      'page_number_content',
      'page_aside_text_content',
      'page_footnote_content',
      'image_caption',
      'image_footnote',
      'chart_caption',
      'chart_footnote',
      'table_caption',
      'table_footnote',
      'math_content',
      'code_caption',
      'code_content',
      'code_footnote',
      'algorithm_caption',
      'algorithm_content',
      'algorithm_footnote',
      'list_items',
    ]
    return keys.flatMap((key) => collectTextParts(record[key])).filter(Boolean)
  }
  return []
}

function collectListItemLines(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      const parts = collectTextParts(item)
      return parts.join('').trim()
    })
    .filter(Boolean)
}

function toRawItemTextLines(value: unknown): string[] {
  return collectTextParts(value)
}

function renderOcrTextBlock(lines: string[], className: string) {
  if (!lines.length) return ''
  return lines
    .map((line) => `<div class="${className}">${escapeHtml(line)}</div>`)
    .join('')
}

function buildRawTableSegmentHtml(record: Record<string, unknown>) {
  const content = getContentPayload(record)
  const captionLines = toRawItemTextLines(record.table_caption ?? content.table_caption)
  const footnoteLines = toRawItemTextLines(record.table_footnote ?? content.table_footnote)
  const tableType = String(record.table_type ?? content.table_type ?? '').trim()
  const nestLevel = String(record.table_nest_level ?? content.table_nest_level ?? '').trim()
  const tableBody = getRawTableHtml(record)
  const tableEvidence = getMediaPath(record.image_source ?? content.image_source)
  if (!tableBody) {
    return [
      renderOcrTextBlock(captionLines, 'parse-result-panel__ocr-caption'),
      buildRawTableMetaHtml(tableType, nestLevel, tableEvidence),
      tableEvidence ? `<div class="parse-result-panel__ocr-empty">${escapeHtml(t('parse.emptyTableHtmlWithEvidence', { path: tableEvidence }))}</div>` : '',
      renderOcrTextBlock(footnoteLines, 'parse-result-panel__ocr-footnote'),
    ].filter(Boolean).join('')
  }
  return [
    renderOcrTextBlock(captionLines, 'parse-result-panel__ocr-caption'),
    buildRawTableMetaHtml(tableType, nestLevel, tableEvidence),
    `<div class="parse-result-panel__ocr-table-scroll">${sanitizeRawTableHtml(tableBody)}</div>`,
    renderOcrTextBlock(footnoteLines, 'parse-result-panel__ocr-footnote'),
  ].filter(Boolean).join('')
}

function buildRawTableMetaHtml(tableType: string, nestLevel: string, evidencePath = '') {
  const numericNestLevel = Number(nestLevel)
  const tableMeta = [
    tableType === 'complex_table'
      ? numericNestLevel > 1
        ? t('parse.nestedTable')
        : t('parse.mergedCellTable')
      : tableType === 'simple_table'
        ? t('parse.simpleTable')
        : '',
    numericNestLevel > 1 ? t('parse.nestedLevel', { level: nestLevel }) : '',
    evidencePath ? t('parse.hasTableImageEvidence') : '',
  ].filter(Boolean).join(' · ')
  return tableMeta ? `<div class="parse-result-panel__ocr-table-meta">${escapeHtml(tableMeta)}</div>` : ''
}

function getRawTableHtml(record: Record<string, unknown>) {
  const content = getContentPayload(record)
  return String(record.table_body ?? record.html ?? content.html ?? '').trim()
}

function getMediaPath(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  return String((value as Record<string, unknown>).path ?? '').trim()
}

function buildRawImageSegmentHtml(record: Record<string, unknown>) {
  const content = getContentPayload(record)
  const captionLines = toRawItemTextLines(record.image_caption ?? content.image_caption)
  const contentLines = toRawItemTextLines(record.content ?? content.content)
  const footnoteLines = toRawItemTextLines(record.image_footnote ?? content.image_footnote)
  const imagePath = getMediaPath(record.image_source ?? content.image_source)
  const subType = String(record.sub_type ?? content.sub_type ?? '').trim()
  return [
    subType ? `<div class="parse-result-panel__ocr-table-meta">${escapeHtml(formatSubTypeLabel(subType))}</div>` : '',
    renderOcrTextBlock(captionLines, 'parse-result-panel__ocr-caption'),
    renderOcrTextBlock(contentLines, 'parse-result-panel__ocr-text'),
    imagePath ? `<div class="parse-result-panel__ocr-empty">${escapeHtml(t('parse.imageEvidence', { path: imagePath }))}</div>` : '',
    renderOcrTextBlock(footnoteLines, 'parse-result-panel__ocr-footnote'),
  ].filter(Boolean).join('')
}

function rawRecordText(record: Record<string, unknown>) {
  const content = getContentPayload(record)
  const listLines = collectListItemLines(record.list_items ?? content.list_items)
  const candidates = [
    record.text,
    record.content,
    content.title_content,
    content.paragraph_content,
    content.page_header_content,
    content.page_footer_content,
    content.page_number_content,
    content.page_aside_text_content,
    content.page_footnote_content,
    content.image_caption,
    content.image_footnote,
    content.chart_caption,
    content.chart_footnote,
    content.table_caption,
    content.table_footnote,
    content.math_content,
    content.code_caption,
    content.code_content,
    content.code_footnote,
    content.algorithm_caption,
    content.algorithm_content,
    content.algorithm_footnote,
    record.lines,
    record.list,
    record.items,
    record.text_lines,
    record.description,
  ]
  const lines: string[] = [...listLines]
  for (const candidate of candidates) {
    lines.push(...toRawItemTextLines(candidate))
  }
  return uniqueStrings(lines).join('\n')
}

function isIgnorableOcrSegmentType(type: string) {
  return ['page_number'].includes(type)
}

function buildRawGenericSegmentHtml(record: Record<string, unknown>, type: string) {
  const text = rawRecordText(record)
  if (!text) return ''
  if (type === 'list') {
    const content = getContentPayload(record)
    const listType = String(record.list_type ?? content.list_type ?? '').trim()
    const attribute = String(record.attribute ?? content.attribute ?? '').trim()
    const meta = [formatListTypeLabel(listType), formatListAttributeLabel(attribute)].filter(Boolean).join(' · ')
    const lines = text.split('\n').map((line) => line.trim()).filter(Boolean)
    return `${meta ? `<div class="parse-result-panel__ocr-table-meta">${escapeHtml(meta)}</div>` : ''}<div class="parse-result-panel__ocr-list">${lines
      .map((line) => `<div class="parse-result-panel__ocr-list-item">${escapeHtml(line)}</div>`)
      .join('')}</div>`
  }
  if (type === 'title') {
    const content = getContentPayload(record)
    const level = String(record.level ?? content.level ?? '').trim()
    return `${level ? `<div class="parse-result-panel__ocr-table-meta">${escapeHtml(formatTitleLevelLabel(level))}</div>` : ''}${normalizeOcrContent(escapeHtml(text))}`
  }
  return normalizeOcrContent(escapeHtml(text))
}

function formatTitleLevelLabel(level: string) {
  const normalized = Number(level)
  if (!Number.isFinite(normalized) || normalized <= 0) return ''
  return t('parse.titleLevel', { level: normalized })
}

function formatListTypeLabel(value: string) {
  const labelMap: Record<string, string> = {
    text_list: t('parse.plainList'),
    reference_list: t('parse.referenceList'),
  }
  return labelMap[value] ?? value
}

function formatListAttributeLabel(value: string) {
  const labelMap: Record<string, string> = {
    ordered: t('parse.orderedList'),
    unordered: t('parse.unorderedList'),
  }
  return labelMap[value] ?? value
}

function formatSubTypeLabel(value: string) {
  const labelMap: Record<string, string> = {
    seal: t('parse.seal'),
    text: t('parse.text'),
    ref_text: t('parse.referenceText'),
    code: t('parse.code'),
    algorithm: t('parse.algorithm'),
  }
  return labelMap[value] ?? value
}

function buildBlockSegmentHtml(block: WorkbenchPage['blocks'][number]) {
  if (block.type === 'table') {
    return block.htmlContent || block.content || ''
  }
  if (block.type === 'list') {
    return `<pre>${escapeHtml(block.content || block.title || '')}</pre>`
  }
  if (block.type === 'title') {
    return `<h3>${escapeHtml(block.content || block.title || '')}</h3>`
  }
  return normalizeOcrContent(escapeHtml(block.content || block.title || ''))
}

function normalizeTableRows(rows: string[][]) {
  const columnCount = Math.max(...rows.map((row) => row.length), 0)
  return rows.map((row) => Array.from({ length: columnCount }, (_, index) => row[index] || ''))
}

function buildTableModel(key: string, title: string, headers: string[], rows: string[][]): TableViewModel {
  const normalizedRows = normalizeTableRows(rows)
  const columnCount = Math.max(headers.length, ...normalizedRows.map((row) => row.length), 0)
  const safeHeaders = Array.from(
    { length: columnCount },
    (_, index) => headers[index] || t('parse.columnFallback', { index: index + 1 }),
  )
  return {
    key,
    title,
    headers: safeHeaders,
    rows: normalizedRows.map((row) => safeHeaders.map((_, index) => row[index] || '')),
  }
}

function tableModelFromHtml(html: string, key: string, title: string): TableViewModel | null {
  if (typeof DOMParser === 'undefined') return null
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const table = doc.querySelector('table')
  if (!table) return null

  const sourceRows = Array.from(table.querySelectorAll('tr'))
    .map((row) => Array.from(row.querySelectorAll('th,td')).map((cell) => String(cell.textContent || '').trim()))
    .filter((row) => row.some(Boolean))
  if (!sourceRows.length) return null

  const firstRow = table.querySelector('tr')
  const firstRowHasHeader = Boolean(firstRow?.querySelector('th'))
  const headers = firstRowHasHeader ? sourceRows[0] : []
  const rows = firstRowHasHeader ? sourceRows.slice(1) : sourceRows
  return buildTableModel(key, title, headers, rows)
}

function openFullscreenTable(table: TableViewModel | null) {
  if (!table) return
  fullscreenTable.value = table
}

function closeFullscreenTable() {
  fullscreenTable.value = null
}

function sanitizeFileName(value: string) {
  return (value || 'table')
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 80)
}

function escapeExcelCell(value: string) {
  return escapeHtml(value).replace(/\n/g, '<br />')
}

function downloadTableAsExcel(table: TableViewModel | null) {
  if (!table) return
  const tableHtml = [
    '<table>',
    '<thead><tr>',
    ...table.headers.map((header) => `<th>${escapeExcelCell(header)}</th>`),
    '</tr></thead>',
    '<tbody>',
    ...table.rows.map((row) => [
      '<tr>',
      ...table.headers.map((_, index) => `<td>${escapeExcelCell(row[index] || '')}</td>`),
      '</tr>',
    ].join('')),
    '</tbody>',
    '</table>',
  ].join('')
  const workbook = `<!doctype html>
<html>
<head>
  <meta charset="UTF-8" />
  <style>
    table { border-collapse: collapse; }
    th, td { border: 1px solid #999; padding: 4px 8px; mso-number-format:"\\@"; }
    th { background: #eef2f7; font-weight: 700; }
  </style>
</head>
<body>${tableHtml}</body>
</html>`
  const blob = new Blob([`\ufeff${workbook}`], {
    type: 'application/vnd.ms-excel;charset=utf-8;',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${sanitizeFileName(table.title)}.xls`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

const rawTextItems = computed(() => {
  const rawItems = Array.isArray(props.page?.rawItems) ? props.page.rawItems : []
  return rawItems
    .map((item, index) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return null
      const record = item as Record<string, unknown>
      const text = String(record.text ?? '').trim()
      if (!text) return null
      const type = String(record.type ?? '').toLowerCase()
      if (type && type !== 'text') return null
      const textLevelValue = Number(record.text_level)
      return {
        id: `raw-text-${index}`,
        text,
        textLevel: Number.isFinite(textLevelValue) ? textLevelValue : null,
      }
    })
    .filter((item): item is { id: string; text: string; textLevel: number | null } => Boolean(item))
})

function normalizeOcrContent(content: string) {
  return content
    .replace(/<table[\s\S]*?<\/table>/g, (tableHtml) => `<div class="parse-result-panel__ocr-table-scroll">${tableHtml}</div>`)
    .replace(/\n/g, '<br />')
}

function isStructuredSegment(
  segment: WorkbenchMarkdownSegmentLike,
): segment is WorkbenchMarkdownSegment {
  return typeof segment !== 'string'
}

function hasRenderableRawItems(rawItems: unknown[]): boolean {
  return rawItems.some((item) => item && typeof item === 'object' && !Array.isArray(item))
}

const ocrSegments = computed<OcrSegmentViewModel[]>(() => {
  const page = props.page
  if (!page) {
    return []
  }

  const rawItems = Array.isArray(page.rawItems) ? page.rawItems : []
  if (hasRenderableRawItems(rawItems)) {
    const rawSegments = rawItems
      .map((item, index) => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) return null
        const record = item as Record<string, unknown>
        const type = String(record.type ?? '').toLowerCase()

        if (type === 'table') {
          const html = buildRawTableSegmentHtml(record)
          if (!html) return null
          return {
            id: `raw-table-segment-${index}`,
            html,
            type,
            table: tableModelFromHtml(html, `raw-table-segment-${index}`, t('parse.recognitionTableTitle', { index: index + 1 })),
          }
        }

        if (type === 'image') {
          const html = buildRawImageSegmentHtml(record)
          if (!html) return null
          return {
            id: `raw-image-segment-${index}`,
            html,
            type,
            table: null,
          }
        }

        const html = buildRawGenericSegmentHtml(record, type)
        if (!html) return null

        return {
          id: `raw-text-segment-${index}`,
          html,
          type: type || 'text',
          table: null,
        }
      })
      .filter((segment): segment is OcrSegmentViewModel => Boolean(segment))

    if (rawSegments.some((segment) => !isIgnorableOcrSegmentType(String(segment.type).toLowerCase()))) {
      return rawSegments
    }
  }

  if (page.markdownSegments.length) {
    const markdownSegments = page.markdownSegments
      .map((segment, index) => {
        if (isStructuredSegment(segment)) {
          const html = normalizeOcrContent(segment.html ?? '')
          return {
            id: segment.id,
            html,
            type: segment.type,
            table: tableModelFromHtml(html, `ocr-segment-${segment.id}`, t('parse.recognitionTableTitle', { index: index + 1 })),
          }
        }

        const html = normalizeOcrContent(segment ?? '')
        return {
          id: `${page.pageIndex}-ocr-${index}`,
          html,
          type: page.blocks[index]?.type ?? 'text',
          table: tableModelFromHtml(html, `${page.pageIndex}-ocr-${index}`, t('parse.recognitionTableTitle', { index: index + 1 })),
        }
      })
      .filter((segment): segment is OcrSegmentViewModel => Boolean(segment.html.trim()))

    if (markdownSegments.length) {
      return markdownSegments
    }
  }

  return page.blocks
    .map((block, index) => {
      const html = buildBlockSegmentHtml(block)
      if (!html.trim()) return null
      return {
        id: `block-segment-${block.id || index}`,
        html,
        type: block.type || 'text',
        table: tableModelFromHtml(html, `block-table-${block.id || index}`, block.title || t('parse.recognitionTableTitle', { index: index + 1 })),
      }
    })
    .filter((segment): segment is OcrSegmentViewModel => Boolean(segment))
})

const ocrTextLines = computed(() => {
  return rawTextItems.value.map((item, index) => {
    const raw = item.text.trim()
    const separator = raw.includes('：') ? '：' : raw.includes(':') ? ':' : null
    if (separator) {
      const parts = raw.split(separator)
      const key = parts[0]?.trim()
      const value = parts.slice(1).join(separator).trim()
      if (key && value) {
        return {
          id: item.id,
          kind: 'kv' as const,
          key,
          value,
          raw,
          isTitle: false,
        }
      }
    }
    const isTitle = index === 0 && raw.length >= 8
    return {
      id: item.id,
      kind: 'raw' as const,
      raw,
      isTitle,
    }
  })
})

const ocrBlockCount = computed(() => {
  if (Array.isArray(props.page?.rawItems) && hasRenderableRawItems(props.page.rawItems)) {
    return props.page.rawItems.length
  }
  if (props.page?.markdownSegments?.length) {
    return props.page.markdownSegments.length
  }
  if (props.page?.blocks?.length) {
    return props.page.blocks.length
  }
  return rawTextItems.value.length
})
const fieldCount = computed(() => {
  if (extractionOutputs.value.length) {
    return extractionOutputs.value.reduce((count, output) => count + countOutputFields(output), 0)
  }
  return extractionFields.value.length
})
const structuredObjectCount = computed(() => extractionStructuredObjects.value.length)
const outputCount = computed(() => extractionOutputs.value.length)
const operationTargets = computed(() => props.operationTargets ?? [])

function uniqueStrings(values: string[]) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const normalized = String(value ?? '').trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    result.push(normalized)
  }
  return result
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function formatTargetTypeLabel(type: OperationTargetType) {
  const labelMap: Record<OperationTargetType, string> = {
    field: t('parse.field'),
    table: t('parse.table'),
    structured_object: t('parse.structuredObject'),
    record_collection: t('parse.recordCollection'),
    record: t('parse.record'),
    output: t('parse.processingOutput'),
  }
  return labelMap[type] ?? type
}

function formatOutputTypeLabel(type: string) {
  const labelMap: Record<string, string> = {
    field_list: t('parse.fieldList'),
    kv_table: t('parse.keyValueResult'),
    kv_record_table: t('parse.keyValueWithDetails'),
    data_table: t('parse.dataTable'),
    record_collection: t('parse.recordCollection'),
    structured_object: t('parse.structuredObject'),
    custom: t('parse.customStructure'),
  }
  return labelMap[type] ?? t('parse.structuredResult')
}

function summarizeTarget(target: OperationTarget) {
  const text = target.excerpt || target.valueText || target.headers?.join(' / ') || target.label
  return String(text || '').replace(/\s+/g, ' ').slice(0, 80)
}

function summarizeText(text: string, maxLength: number) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim()
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength)}...`
}

function stringifyCell(value: unknown) {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function normalizeDataTableHeader(value: unknown, index: number) {
  const text = stringifyCell(value).trim()
  if (text === 'source_page' || text === 'sourcePage') return t('parse.sourcePage')
  if (!text) return index === 0 ? t('parse.item') : t('parse.columnFallback', { index: index + 1 })
  return text
}

function countOutputFields(output: ExtractionOutputItem) {
  if (output.type === 'field_list' || output.type === 'kv_table') {
    return getOutputKvEntries(output).length
  }
  if (output.type === 'kv_record_table') {
    return getOutputKvEntries(output).length
  }
  if (output.type === 'record_collection') {
    return getRecordCollection(output).length
  }
  return 0
}

function getOutputTitle(output: ExtractionOutputItem, index: number) {
  return output.title || t('parse.extractionResultTitle', { index: index + 1 })
}

function getOutputData(output: ExtractionOutputItem) {
  return asRecord(output.data)
}

function getOutputKvEntries(output: ExtractionOutputItem): Array<[string, string]> {
  const data = getOutputData(output)
  const kv = asRecord(data.kv)
  if (Object.keys(kv).length) {
    return Object.entries(kv)
      .filter(([key]) => key.trim())
      .map(([key, value]) => [key, stringifyCell(value)] as [string, string])
  }

  const fields = Array.isArray(data.fields) ? data.fields : []
  if (fields.length) {
    return fields
      .map((item) => asRecord(item))
      .map((item) => [String(item.label ?? item.key ?? '').trim(), stringifyCell(item.value)] as [string, string])
      .filter(([key]) => key)
  }

  if (output.type === 'field_list' || output.type === 'kv_table') {
    return Object.entries(data)
      .filter(([key, value]) => key !== 'summary' && key !== 'errors' && value !== null && value !== undefined)
      .map(([key, value]) => [key, stringifyCell(value)] as [string, string])
  }

  return []
}

function getOutputTableRawHeaders(output: ExtractionOutputItem) {
  const data = getOutputData(output)
  const configured = Array.isArray(data.headers)
    ? data.headers.map((item) => stringifyCell(item))
    : []
  const rows = Array.isArray(data.rows) ? data.rows : Array.isArray(data.table) ? data.table : []
  const hasRowSourcePage = rows.some((row) => {
    const record = asRecord(row)
    return Boolean(record.source_page || record.sourcePage)
  })
  if (configured.length) {
    const headers = [...configured]
    if (hasRowSourcePage && !headers.includes('source_page') && !headers.includes('sourcePage')) {
      headers.push('source_page')
    }
    return headers
  }

  const headers: string[] = []
  for (const row of rows) {
    if (Array.isArray(row)) {
      row.forEach((_, index) => headers.push(t('parse.columnFallback', { index: index + 1 })))
    } else if (row && typeof row === 'object') {
      headers.push(...Object.keys(row as Record<string, unknown>))
    }
  }
  return uniqueStrings(headers)
}

function getOutputTableHeaders(output: ExtractionOutputItem) {
  return getOutputTableRawHeaders(output).map((header, index) => normalizeDataTableHeader(header, index))
}

function getOutputTableRows(output: ExtractionOutputItem) {
  const data = getOutputData(output)
  const rows = Array.isArray(data.rows) ? data.rows : Array.isArray(data.table) ? data.table : []
  const headers = getOutputTableRawHeaders(output)
  return rows.map((row) => {
    if (Array.isArray(row)) {
      return headers.map((_, index) => stringifyCell(row[index]))
    }
    const record = asRecord(row)
    return headers.map((header) => {
      if (header === 'source_page' && record.sourcePage !== undefined && record.source_page === undefined) {
        return stringifyCell(record.sourcePage)
      }
      return stringifyCell(record[header])
    })
  })
}

function getOutputTableModel(output: ExtractionOutputItem, outputIndex: number) {
  return buildTableModel(
    `output-table-${output.id || outputIndex}`,
    getOutputTitle(output, outputIndex),
    getOutputTableHeaders(output),
    getOutputTableRows(output),
  )
}

function normalizeOutputNoteText(note: unknown) {
  if (!note) return ''
  if (typeof note === 'string') return note.trim()
  const record = asRecord(note)
  const text = stringifyCell(record.text || record.note || record.description || record.summary).trim()
  const page = stringifyCell(record.source_page || record.sourcePage || record.page || record.pageNo).trim()
  if (text && page) return `${text}（${page}）`
  return text || page
}

function getOutputTableMergeNotes(output: ExtractionOutputItem) {
  const notes = getOutputData(output).mergeNotes
  return Array.isArray(notes) ? notes.map(normalizeOutputNoteText).filter(Boolean) : []
}

function getOutputTableEvidenceNotes(output: ExtractionOutputItem) {
  const evidence = getOutputData(output).evidence
  return Array.isArray(evidence) ? evidence.map(normalizeOutputNoteText).filter(Boolean) : []
}

function hasOutputTableSemantics(output: ExtractionOutputItem) {
  return getOutputTableMergeNotes(output).length > 0 || getOutputTableEvidenceNotes(output).length > 0
}

function getRecordCollection(output: ExtractionOutputItem) {
  if (Array.isArray(output.data)) {
    return output.data.map((item) => asRecord(item)).filter((item) => Object.keys(item).length)
  }

  const records = getOutputData(output).records
  return Array.isArray(records)
    ? records.map((item) => asRecord(item)).filter((item) => Object.keys(item).length)
    : []
}

function isPrimitiveRecordValue(value: unknown) {
  return value === null || value === undefined || typeof value !== 'object'
}

function getRecordCollectionTableHeaders(output: ExtractionOutputItem) {
  const data = getOutputData(output)
  const configured = Array.isArray(data.headers)
    ? data.headers.map((item) => stringifyCell(item)).filter(Boolean)
    : []
  if (configured.length) return configured

  const schema = asRecord(output.schema)
  const required = Array.isArray(schema.required)
    ? schema.required.map((item) => stringifyCell(item)).filter(Boolean)
    : []
  const headers: string[] = [...required]
  for (const record of getRecordCollection(output)) {
    for (const [key, value] of Object.entries(record)) {
      if (!isPrimitiveRecordValue(value)) continue
      headers.push(key)
    }
  }
  return uniqueStrings(headers)
}

function getRecordCollectionTableRows(output: ExtractionOutputItem) {
  const headers = getRecordCollectionTableHeaders(output)
  return getRecordCollection(output).map((record) => headers.map((header) => stringifyCell(record[header])))
}

function getRecordCollectionTableModel(output: ExtractionOutputItem, outputIndex: number) {
  return buildTableModel(
    `record-collection-${output.id || outputIndex}`,
    getOutputTitle(output, outputIndex),
    getRecordCollectionTableHeaders(output),
    getRecordCollectionTableRows(output),
  )
}

function isTabularRecordCollection(output: ExtractionOutputItem) {
  const records = getRecordCollection(output)
  if (!records.length) return false
  if (!getRecordCollectionTableHeaders(output).length) return false
  return records.every((record) => Object.values(record).every((value) => isPrimitiveRecordValue(value)))
}

function getRecordKvEntries(record: Record<string, unknown>) {
  return Object.entries(record)
    .filter(([, value]) => isPrimitiveRecordValue(value))
    .map(([key, value]) => [key, stringifyCell(value)] as [string, string])
    .filter(([key]) => key.trim())
}

function getRecordComponents(record: Record<string, unknown>) {
  const detailKeys = ['components', '组件明细', 'children', 'items', 'details', '明细', 'table', 'rows']
  for (const key of detailKeys) {
    const value = record[key]
    if (Array.isArray(value)) {
      return value.map((item) => asRecord(item)).filter((item) => Object.keys(item).length)
    }
  }
  return []
}

function getRecordComponentHeaders(record: Record<string, unknown>) {
  const headers: string[] = []
  for (const component of getRecordComponents(record)) {
    headers.push(...Object.keys(component))
  }
  return uniqueStrings(headers)
}

function getRecordComponentCell(row: Record<string, unknown>, header: string) {
  return stringifyCell(row[header])
}

function getRecordComponentTableModel(output: ExtractionOutputItem, record: Record<string, unknown>, recordIndex: number) {
  const title = String(record['调色号'] || record.name || record.title || t('parse.recordTitle', { index: recordIndex + 1 }))
  const headers = getRecordComponentHeaders(record)
  const rows = getRecordComponents(record).map((row) => headers.map((header) => getRecordComponentCell(row, header)))
  return buildTableModel(
    `record-component-${output.id}-${recordIndex}`,
    t('parse.recordDetailTitle', { title: getOutputTitle(output, 0), record: title }),
    headers,
    rows,
  )
}

function buildDocumentTreeItems(root: DocumentTreeNode | null): DocumentTreeItem[] {
  if (!root) return []
  const treeItems: DocumentTreeItem[] = []
  const startNodes = root.type === 'root' ? (root.children ?? []) : [root]

  function visit(node: DocumentTreeNode, depth: number, path: number[]) {
    const type = normalizeDocumentTreeType(node.type)
    const shouldRenderNode = shouldShowDocumentTreeNode(node, type)
    const nextDepth = shouldRenderNode ? depth + 1 : depth
    if (shouldRenderNode) {
      const title = normalizeDocumentTreeText(node.title)
      const content = normalizeDocumentTreeText(node.content)
      const label = summarizeText(title || content || t('parse.unnamedContent'), 56)
      const preview = title && content ? summarizeText(content, 96) : ''
      const pageNos = collectDocumentTreeDirectPages(node)
      treeItems.push({
        id: `document-tree-${path.join('-')}`,
        depth: Math.min(depth, 7),
        type,
        typeLabel: formatDocumentTypeLabel(type),
        label,
        meta: buildDocumentTreeMeta(node),
        preview,
        pageNos,
        locations: [],
        sourceScope: formatPageRangeLabel(pageNos.map(String)) || t('parse.documentTreeNode'),
        sourceText: '',
        rawNode: node,
      })
    }
    ;(node.children ?? []).forEach((child, index) => visit(child, nextDepth, [...path, index + 1]))
  }

  startNodes.forEach((node, index) => visit(node, 0, [index + 1]))
  return treeItems
}

function normalizeDocumentTreeText(value: unknown) {
  return String(value ?? '')
    .replace(/<\|txt_split\|>?/g, ' / ')
    .replace(/\s+/g, ' ')
    .trim()
}

function buildDocumentTreeTableSource(node: DocumentTreeNode) {
  const rows = Array.isArray(node.rows) ? node.rows : []
  const tableLines: string[] = []
  if (rows.length) {
    const width = Math.max(...rows.map((row) => Array.isArray(row) ? row.length : 0), 0)
    const normalizedRows = rows
      .slice(0, 12)
      .map((row) => Array.from({ length: width }, (_, index) => normalizeDocumentTreeText(row[index])))
    const header = normalizedRows[0] ?? []
    tableLines.push('| ' + header.join(' | ') + ' |')
    tableLines.push('| ' + Array.from({ length: width }, () => '---').join(' | ') + ' |')
    for (const row of normalizedRows.slice(1)) {
      tableLines.push('| ' + row.join(' | ') + ' |')
    }
    if (rows.length > normalizedRows.length) {
      tableLines.push(t('parse.omittedRows', { count: rows.length - normalizedRows.length }))
    }
  }
  const mergeDescriptions = (node.mergeDescriptions ?? [])
    .map((item) => normalizeDocumentTreeText(item.description))
    .filter(Boolean)
    .slice(0, 12)
  if (mergeDescriptions.length) {
    tableLines.push(t('parse.mergeCellNotes') + t('parse.labelSeparator'))
    tableLines.push(...mergeDescriptions.map((item) => `- ${item}`))
  }
  return tableLines.join('\n')
}

function collectDocumentTreeDirectPages(node: DocumentTreeNode): number[] {
  const pages = new Set<number>()
  for (const location of node.location ?? []) {
    const page = Number(location.page)
    if (Number.isFinite(page) && page > 0) pages.add(page)
  }
  return Array.from(pages).sort((left, right) => left - right)
}

function collectDocumentTreePages(node: DocumentTreeNode): number[] {
  const pages = new Set<number>()
  function visit(current: DocumentTreeNode) {
    for (const location of current.location ?? []) {
      const page = Number(location.page)
      if (Number.isFinite(page) && page > 0) pages.add(page)
    }
    ;(current.children ?? []).forEach(visit)
  }
  visit(node)
  return Array.from(pages).sort((left, right) => left - right)
}

function collectDocumentTreeLocations(node: DocumentTreeNode) {
  const locations: DocumentTreeSource['locations'] = []
  const seen = new Set<string>()
  function visit(current: DocumentTreeNode) {
    for (const location of current.location ?? []) {
      const pageNo = Number(location.page)
      const rawBbox = Array.isArray(location.bbox) ? location.bbox.slice(0, 4).map(Number) : []
      if (!Number.isFinite(pageNo) || pageNo <= 0 || rawBbox.length !== 4 || rawBbox.some((value) => !Number.isFinite(value))) {
        continue
      }
      const bbox: [number, number, number, number] = [
        rawBbox[0],
        rawBbox[1],
        rawBbox[2],
        rawBbox[3],
      ]
      if (bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) {
        continue
      }
      const key = `${pageNo}:${bbox.map((value) => Number(value).toFixed(4)).join(',')}`
      if (seen.has(key)) {
        continue
      }
      seen.add(key)
      locations.push({ pageNo, bbox })
    }
    ;(current.children ?? []).forEach(visit)
  }
  visit(node)
  return locations
}

function buildDocumentTreeSourceText(node: DocumentTreeNode) {
  const lines: string[] = []
  function visit(current: DocumentTreeNode, depth: number) {
    const type = normalizeDocumentTreeType(current.type)
    if (['header', 'footer', 'page_number'].includes(type)) return
    const title = normalizeDocumentTreeText(current.title)
    const content = normalizeDocumentTreeText(current.content)
    const pages = collectDocumentTreePages(current)
    const prefix = `${'  '.repeat(Math.min(depth, 5))}- ${formatDocumentTypeLabel(type)}`
    const pageLabel = formatPageRangeLabel(pages.map(String))
    const text = [title, content && content !== title ? content : ''].filter(Boolean).join('：')
    if (text) {
      lines.push(`${prefix}${pageLabel ? `(${pageLabel})` : ''}${t('parse.labelSeparator')}${text}`)
    }
    const tableSource = buildDocumentTreeTableSource(current)
    if (tableSource) {
      lines.push(tableSource)
    }
    ;(current.children ?? []).forEach((child) => visit(child, depth + 1))
  }
  visit(node, 0)
  return lines.join('\n').slice(0, 8000)
}

function buildFullDocumentTreeSource(item: DocumentTreeItem): DocumentTreeSource {
  const { rawNode, ...source } = item
  const pageNos = collectDocumentTreePages(rawNode)
  const locations = collectDocumentTreeLocations(rawNode)
  return {
    ...source,
    pageNos,
    locations,
    sourceScope: formatPageRangeLabel(pageNos.map(String)) || source.sourceScope || t('parse.documentTreeNode'),
    sourceText: buildDocumentTreeSourceText(rawNode),
  }
}

function handleDocumentTreeItemSelect(item: DocumentTreeItem) {
  emit('selectTreeNode', buildFullDocumentTreeSource(item))
}

function normalizeDocumentTreeType(type: unknown) {
  const normalized = String(type ?? '').trim().toLowerCase()
  return normalized || 'content'
}

function shouldShowDocumentTreeNode(node: DocumentTreeNode, type: string) {
  if (['header', 'footer', 'page_number'].includes(type)) return false
  const level = typeof node.level === 'number' ? node.level : Number(node.level)
  const renderableLooseLevelTypes = new Set(['table', 'image', 'chart', 'seal', 'image_block', 'list'])
  if (Number.isFinite(level) && level < 0 && !renderableLooseLevelTypes.has(type)) return false
  return Boolean(normalizeDocumentTreeText(node.title) || normalizeDocumentTreeText(node.content) || node.children?.length)
}

function formatDocumentTypeLabel(type: string) {
  const labelMap: Record<string, string> = {
    root: t('parse.document'),
    content: t('parse.content'),
    page: t('parse.page'),
    title: t('parse.title'),
    paragraph: t('parse.paragraph'),
    paragraph_group: t('parse.paragraphGroup'),
    text: t('parse.text'),
    list: t('parse.list'),
    table: t('parse.table'),
    image: t('parse.image'),
    chart: t('parse.chart'),
    code: t('parse.code'),
    algorithm: t('parse.algorithm'),
    equation_interline: t('parse.formula'),
    index: t('parse.catalog'),
    header: t('parse.header'),
    footer: t('parse.footer'),
    page_number: t('parse.pageNumber'),
  }
  return labelMap[type] ?? t('parse.content')
}

function buildDocumentTreeMeta(node: DocumentTreeNode) {
  const pages = uniqueStrings((node.location ?? []).map((item) => item.page ? String(item.page) : '').filter(Boolean))
  const level = typeof node.level === 'number' ? node.level : Number(node.level)
  const parts = [
    formatPageRangeLabel(pages),
    Number.isFinite(level) && level > 0 ? t('parse.levelLabel', { level }) : '',
    node.children?.length ? t('parse.childNodeCount', { count: node.children.length }) : '',
  ].filter(Boolean)
  return parts.join(' · ')
}

function formatPageRangeLabel(pages: string[]) {
  if (!pages.length) return ''
  const numbers = pages.map((page) => Number(page)).filter((page) => Number.isFinite(page)).sort((a, b) => a - b)
  if (!numbers.length) return ''
  const ranges: string[] = []
  let start = numbers[0]
  let previous = numbers[0]
  for (const page of numbers.slice(1)) {
    if (page === previous + 1) {
      previous = page
      continue
    }
    ranges.push(start === previous
      ? t('parse.pageLabel', { page: start })
      : t('parse.pageRangeLabel', { start, end: previous }))
    start = page
    previous = page
  }
  ranges.push(start === previous
    ? t('parse.pageLabel', { page: start })
    : t('parse.pageRangeLabel', { start, end: previous }))
  return ranges.join(t('parse.listSeparator'))
}

function treeIndentStyle(item: DocumentTreeItem) {
  return { paddingLeft: `${8 + item.depth * 16}px` }
}

function getTableColumnCount(table: ExtractionTableItem) {
  return Math.max(table.headers.length, ...table.rows.map((row) => row.length), 0)
}

function getTableHeader(table: ExtractionTableItem, columnIndex: number) {
  return table.headers[columnIndex] || t('parse.columnFallback', { index: columnIndex + 1 })
}

function getTableCell(row: string[], columnIndex: number) {
  return row[columnIndex] || ''
}

function getExtractionTableModel(table: ExtractionTableItem, tableIndex: number) {
  const columnCount = getTableColumnCount(table)
  const headers = Array.from({ length: columnCount }, (_, index) => getTableHeader(table, index))
  const rows = table.rows.map((row) => headers.map((_, index) => getTableCell(row, index)))
  return buildTableModel(
    `extraction-table-${tableIndex}`,
    table.title || t('parse.tableTitle', { index: tableIndex + 1 }),
    headers,
    rows,
  )
}

function getStructuredObjectKvEntries(item: ExtractionStructuredObjectItem) {
  return Object.entries(item.kv ?? {}).filter(([key]) => key.trim())
}

function getStructuredObjectHeaders(item: ExtractionStructuredObjectItem) {
  const headers: string[] = []
  const seen = new Set<string>()
  for (const row of item.table ?? []) {
    for (const key of Object.keys(row)) {
      const normalized = key.trim()
      if (!normalized || seen.has(normalized)) continue
      seen.add(normalized)
      headers.push(normalized)
    }
  }
  return headers
}

function getStructuredObjectCell(row: Record<string, string>, header: string) {
  return row[header] || ''
}

function getStructuredObjectTableModel(item: ExtractionStructuredObjectItem, objectIndex: number) {
  const headers = getStructuredObjectHeaders(item)
  const rows = item.table.map((row) => headers.map((header) => getStructuredObjectCell(row, header)))
  return buildTableModel(
    `structured-object-${item.id || objectIndex}`,
    item.title || t('parse.structuredObjectTitle', { index: objectIndex + 1 }),
    headers,
    rows,
  )
}
</script>

<template>
  <section class="parse-result-panel">
    <header class="parse-result-panel__header">
      <div class="parse-result-panel__tabs">
        <button
          v-for="option in tabOptions"
          :key="option.key"
          type="button"
          class="parse-result-panel__tab"
          :class="{ 'is-active': activeTab === option.key }"
          @click="activeTab = option.key"
        >
          {{ option.label }}
        </button>
      </div>
      <div class="parse-result-panel__header-side">
        <span v-if="activeTab === 'tree'" class="parse-result-panel__meta">
          {{ documentTreeStatusText }}
        </span>
        <span v-else-if="page" class="parse-result-panel__meta">
          {{ t('parse.tableCount', { count: tableCount }) }} · {{ t('parse.ocrBlockCount', { count: ocrBlockCount }) }} · {{ t('parse.fieldCount', { count: fieldCount }) }}<span v-if="outputCount"> · {{ t('parse.outputCount', { count: outputCount }) }}</span><span v-else-if="structuredObjectCount"> · {{ t('parse.objectCount', { count: structuredObjectCount }) }}</span>
        </span>
      </div>
    </header>

    <div class="parse-result-panel__content">
      <template v-if="activeTab === 'recognition'">
        <div v-if="ocrSegments.length" class="parse-result-panel__ocr-segments">
          <div
            v-for="segment in ocrSegments"
            :key="segment.id"
            :class="[
              'parse-result-panel__ocr-segment',
              { 'is-table': String(segment.type).toLowerCase().includes('table') },
            ]"
            >
              <div v-if="segment.table" class="parse-result-panel__table-toolbar">
              <span>{{ t('parse.rowColumnCount', { rows: segment.table.rows.length, columns: segment.table.headers.length }) }}</span>
              <span class="parse-result-panel__table-title-actions">
                <button
                  type="button"
                  class="parse-result-panel__table-action"
                  @click="openFullscreenTable(segment.table)"
                >
                  {{ t('parse.fullscreen') }}
                </button>
                <button
                  type="button"
                  class="parse-result-panel__table-action"
                  @click="downloadTableAsExcel(segment.table)"
                >
                  {{ t('parse.exportExcel') }}
                </button>
              </span>
            </div>
            <div v-html="segment.html"></div>
          </div>
        </div>
        <div v-else-if="rawTextItems.length" class="parse-result-panel__ocr-lines">
          <div
            v-for="line in ocrTextLines"
            :key="line.id"
            class="parse-result-panel__ocr-line"
            :class="{ 'is-title': line.isTitle, 'is-kv': line.kind === 'kv' }"
          >
            <template v-if="line.kind === 'kv'">
              <div class="parse-result-panel__ocr-key">{{ line.key }}</div>
              <div class="parse-result-panel__ocr-value">{{ line.value }}</div>
            </template>
            <template v-else>
              {{ line.raw }}
            </template>
          </div>
        </div>
        <div v-else class="parse-result-panel__empty">{{ t('parse.noRecognitionContent') }}</div>
      </template>

      <template v-else-if="activeTab === 'tree'">
        <section v-if="documentTreeItems.length" class="parse-result-panel__document-tree">
          <div class="parse-result-panel__document-tree-head">
            <strong>{{ t('parse.documentTree') }}</strong>
            <span>{{ t('parse.structureNodeCount', { count: documentTreeItems.length }) }} · {{ props.documentTree?.docId }}</span>
          </div>
          <div class="parse-result-panel__document-tree-list">
            <button
              v-for="item in documentTreeItems"
              :key="item.id"
              type="button"
              class="parse-result-panel__document-tree-item"
              :class="[`is-${item.type}`, { 'is-selected': selectedTreeNodeId === item.id }]"
              :style="treeIndentStyle(item)"
              @click="handleDocumentTreeItemSelect(item)"
            >
              <span class="parse-result-panel__document-tree-type">{{ item.typeLabel }}</span>
              <span class="parse-result-panel__document-tree-main">
                <b>{{ item.label }}</b>
                <small v-if="item.preview">{{ item.preview }}</small>
              </span>
              <em v-if="item.meta">{{ item.meta }}</em>
            </button>
          </div>
        </section>
        <div v-else class="parse-result-panel__empty">{{ t('parse.documentTreeNotGenerated') }}</div>
      </template>

      <template v-else-if="activeTab === 'extract'">
        <div v-if="isStructureProcessing" class="parse-result-panel__notice">
          {{ t('parse.structureProcessing') }}
        </div>
        <div v-else-if="!result" class="parse-result-panel__empty">{{ t('parse.structureNotRun') }}</div>
        <div v-else-if="!hasExtractContent" class="parse-result-panel__empty">{{ t('parse.noStructuredResult') }}</div>
        <template v-else>
          <div v-if="llmTraceItems.length" class="parse-result-panel__trace">
            <span
              v-for="item in llmTraceItems"
              :key="item.label"
              class="parse-result-panel__trace-item"
            >
              {{ item.label }}{{ t('parse.labelSeparator') }}{{ item.value }}
            </span>
          </div>
          <p v-if="extractionSummary" class="parse-result-panel__extract-summary">
            {{ extractionSummary }}
          </p>
          <div v-if="extractionErrors.length" class="parse-result-panel__errors">
            <div
              v-for="error in extractionErrors"
              :key="error"
              class="parse-result-panel__error"
            >
              {{ error }}
            </div>
          </div>
          <details
            v-if="operationTargets.length"
            class="parse-result-panel__target-disclosure"
            :open="!extractionOutputs.length"
          >
            <summary>
              <span>{{ t('parse.extractionObjectCount', { count: operationTargets.length }) }}</span>
              <em>{{ t('parse.expandForProcessing') }}</em>
            </summary>
            <div class="parse-result-panel__target-list">
              <button
                v-for="target in operationTargets"
                :key="target.id"
                type="button"
                class="parse-result-panel__target-button"
                :class="{ 'is-active': target.id === selectedTargetId }"
                @click="emit('selectTarget', target)"
              >
                <b>{{ formatTargetTypeLabel(target.type) }}</b>
                <span>{{ target.label }}</span>
                <em>{{ summarizeTarget(target) }}</em>
              </button>
            </div>
          </details>
          <template v-if="extractionOutputs.length">
            <section
              v-for="(output, outputIndex) in extractionOutputs"
              :key="output.id || `output-${outputIndex}`"
              class="parse-result-panel__output"
            >
              <div class="parse-result-panel__table-title-row">
                <strong>{{ getOutputTitle(output, outputIndex) }}</strong>
                <span class="parse-result-panel__table-title-actions">
                  <span>{{ formatOutputTypeLabel(output.type) }}</span>
                  <button
                    v-if="(output.type === 'data_table' || output.type === 'kv_record_table') && getOutputTableRows(output).length"
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="openFullscreenTable(getOutputTableModel(output, outputIndex))"
	                  >
	                    {{ t('parse.fullscreen') }}
	                  </button>
                  <button
                    v-if="(output.type === 'data_table' || output.type === 'kv_record_table') && getOutputTableRows(output).length"
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="downloadTableAsExcel(getOutputTableModel(output, outputIndex))"
	                  >
	                    {{ t('parse.exportExcel') }}
	                  </button>
                  <button
                    v-if="output.type === 'record_collection' && isTabularRecordCollection(output)"
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="openFullscreenTable(getRecordCollectionTableModel(output, outputIndex))"
	                  >
	                    {{ t('parse.fullscreen') }}
	                  </button>
                  <button
                    v-if="output.type === 'record_collection' && isTabularRecordCollection(output)"
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="downloadTableAsExcel(getRecordCollectionTableModel(output, outputIndex))"
	                  >
	                    {{ t('parse.exportExcel') }}
	                  </button>
                  <button
                    type="button"
                    class="parse-result-panel__copy-action"
                    @click="copyJsonData(getOutputCopyActionKey(output, outputIndex), getOutputCopyData(output))"
	                  >
	                    {{ copiedJsonAction === getOutputCopyActionKey(output, outputIndex) ? t('parse.copied') : t('parse.copyData') }}
	                  </button>
                </span>
              </div>

              <div
                v-if="output.type === 'field_list' || output.type === 'kv_table'"
                class="parse-result-panel__field-table-wrap"
                @pointerdown="startHorizontalDragScroll"
              >
                <table class="parse-result-panel__field-table">
                  <thead>
                    <tr>
	                      <th>{{ t('parse.field') }}</th>
	                      <th>{{ t('parse.value') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="[key, value] in getOutputKvEntries(output)"
                      :key="`output-kv-${output.id}-${key}`"
                    >
                      <th>{{ key }}</th>
                      <td>{{ value || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <template v-else-if="output.type === 'data_table'">
                <div class="parse-result-panel__field-table-wrap" @pointerdown="startHorizontalDragScroll">
                  <table class="parse-result-panel__field-table parse-result-panel__data-table">
                    <thead>
                      <tr>
                        <th
                          v-for="header in getOutputTableHeaders(output)"
                          :key="`output-header-${output.id}-${header}`"
                        >
                          {{ header }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(row, rowIndex) in getOutputTableRows(output)"
                        :key="`output-row-${output.id}-${rowIndex}`"
                      >
                        <td
                          v-for="(cell, cellIndex) in row"
                          :key="`output-cell-${output.id}-${rowIndex}-${cellIndex}`"
                        >
                          {{ cell || '—' }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="hasOutputTableSemantics(output)" class="parse-result-panel__table-semantics">
                  <div v-if="getOutputTableMergeNotes(output).length">
	                    <strong>{{ t('parse.structureNotes') }}</strong>
                    <span
                      v-for="note in getOutputTableMergeNotes(output)"
                      :key="`merge-note-${output.id}-${note}`"
                    >
                      {{ note }}
                    </span>
                  </div>
                  <div v-if="getOutputTableEvidenceNotes(output).length">
	                    <strong>{{ t('parse.evidenceSummary') }}</strong>
                    <span
                      v-for="note in getOutputTableEvidenceNotes(output)"
                      :key="`evidence-note-${output.id}-${note}`"
                    >
                      {{ note }}
                    </span>
                  </div>
                </div>
              </template>

              <template v-else-if="output.type === 'kv_record_table'">
                <dl v-if="getOutputKvEntries(output).length" class="parse-result-panel__structured-kv">
                  <template
                    v-for="[key, value] in getOutputKvEntries(output)"
                    :key="`output-object-kv-${output.id}-${key}`"
                  >
                    <dt>{{ key }}</dt>
                    <dd>{{ value || '—' }}</dd>
                  </template>
                </dl>
                <div class="parse-result-panel__field-table-wrap" @pointerdown="startHorizontalDragScroll">
                  <table class="parse-result-panel__field-table parse-result-panel__data-table">
                    <thead>
                      <tr>
                        <th
                          v-for="header in getOutputTableHeaders(output)"
                          :key="`output-object-header-${output.id}-${header}`"
                        >
                          {{ header }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(row, rowIndex) in getOutputTableRows(output)"
                        :key="`output-object-row-${output.id}-${rowIndex}`"
                      >
                        <td
                          v-for="(cell, cellIndex) in row"
                          :key="`output-object-cell-${output.id}-${rowIndex}-${cellIndex}`"
                        >
                          {{ cell || '—' }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>

              <div v-else-if="output.type === 'record_collection'" class="parse-result-panel__records">
                <template v-if="isTabularRecordCollection(output)">
                  <div class="parse-result-panel__record-table-meta">
	                    <span>{{ t('parse.recordCount', { count: getRecordCollection(output).length }) }}</span>
	                    <span>{{ t('parse.columnCount', { count: getRecordCollectionTableHeaders(output).length }) }}</span>
                  </div>
                  <div
                    class="parse-result-panel__field-table-wrap"
                    @pointerdown="startHorizontalDragScroll"
                  >
                    <table class="parse-result-panel__field-table parse-result-panel__data-table">
                      <thead>
                        <tr>
                          <th
                            v-for="header in getRecordCollectionTableHeaders(output)"
                            :key="`record-table-header-${output.id}-${header}`"
                          >
                            {{ header }}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="(row, rowIndex) in getRecordCollectionTableRows(output)"
                          :key="`record-table-row-${output.id}-${rowIndex}`"
                        >
                          <td
                            v-for="(cell, cellIndex) in row"
                            :key="`record-table-cell-${output.id}-${rowIndex}-${cellIndex}`"
                          >
                            {{ cell || '—' }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </template>
                <template v-else>
                  <article
                    v-for="(record, recordIndex) in getRecordCollection(output)"
                    :key="`record-${output.id}-${recordIndex}`"
                    class="parse-result-panel__record"
                  >
                    <div class="parse-result-panel__record-head">
	                      <strong>{{ record['调色号'] || record.name || record.title || t('parse.recordTitle', { index: recordIndex + 1 }) }}</strong>
                      <span class="parse-result-panel__record-head-actions">
	                        <span>{{ t('parse.detailRowCount', { count: getRecordComponents(record).length }) }}</span>
                        <button
                          v-if="getRecordComponents(record).length"
                          type="button"
                          class="parse-result-panel__table-action"
                          @click="openFullscreenTable(getRecordComponentTableModel(output, record, recordIndex))"
                        >
	                          {{ t('parse.fullscreen') }}
                        </button>
                        <button
                          v-if="getRecordComponents(record).length"
                          type="button"
                          class="parse-result-panel__table-action"
                          @click="downloadTableAsExcel(getRecordComponentTableModel(output, record, recordIndex))"
                        >
	                          {{ t('parse.exportExcel') }}
                        </button>
                      </span>
                    </div>
                    <dl class="parse-result-panel__structured-kv">
                      <template
                        v-for="[key, value] in getRecordKvEntries(record)"
                        :key="`record-kv-${output.id}-${recordIndex}-${key}`"
                      >
                        <dt>{{ key }}</dt>
                        <dd>{{ value || '—' }}</dd>
                      </template>
                    </dl>
                    <div
                      v-if="getRecordComponents(record).length"
                      class="parse-result-panel__field-table-wrap"
                      @pointerdown="startHorizontalDragScroll"
                    >
                      <table class="parse-result-panel__field-table parse-result-panel__data-table">
                        <thead>
                          <tr>
                            <th
                              v-for="header in getRecordComponentHeaders(record)"
                              :key="`record-header-${output.id}-${recordIndex}-${header}`"
                            >
                              {{ header }}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr
                            v-for="(row, rowIndex) in getRecordComponents(record)"
                            :key="`record-row-${output.id}-${recordIndex}-${rowIndex}`"
                          >
                            <td
                              v-for="header in getRecordComponentHeaders(record)"
                              :key="`record-cell-${output.id}-${recordIndex}-${rowIndex}-${header}`"
                            >
                              {{ getRecordComponentCell(row, header) || '—' }}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </article>
                </template>
              </div>

	              <div v-else class="parse-result-panel__json-block">
	                <div class="parse-result-panel__json-title">
	                  <span>{{ t('parse.customStructure') }}</span>
	                </div>
                <JsonTreeView
                  root-key="output"
                  :data="output.data"
                  :expanded-paths="expandedPaths"
                  @toggle="toggleJsonPath"
                />
              </div>
            </section>
          </template>

          <template v-else>
            <div
              v-for="(structuredObject, objectIndex) in extractionStructuredObjects"
              :key="`structured-object-${objectIndex}-${structuredObject.id}`"
              class="parse-result-panel__structured-object"
            >
	              <div class="parse-result-panel__table-title-row">
	                <strong>{{ structuredObject.title || t('parse.structuredObjectTitle', { index: objectIndex + 1 }) }}</strong>
	                <span class="parse-result-panel__table-title-actions">
	                  <span>
	                    {{ t('parse.kvItemCount', { count: getStructuredObjectKvEntries(structuredObject).length }) }} ·
	                    {{ t('parse.detailRowCount', { count: structuredObject.table.length }) }}
	                  </span>
                  <button
                    v-if="structuredObject.table.length"
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="openFullscreenTable(getStructuredObjectTableModel(structuredObject, objectIndex))"
                  >
	                    {{ t('parse.fullscreen') }}
                  </button>
                  <button
                    v-if="structuredObject.table.length"
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="downloadTableAsExcel(getStructuredObjectTableModel(structuredObject, objectIndex))"
                  >
	                    {{ t('parse.exportExcel') }}
                  </button>
                </span>
              </div>
              <dl
                v-if="getStructuredObjectKvEntries(structuredObject).length"
                class="parse-result-panel__structured-kv"
              >
                <template
                  v-for="[key, value] in getStructuredObjectKvEntries(structuredObject)"
                  :key="`kv-${objectIndex}-${key}`"
                >
                  <dt>{{ key }}</dt>
                  <dd>{{ value || '—' }}</dd>
                </template>
              </dl>
              <div
                v-if="structuredObject.table.length"
                class="parse-result-panel__field-table-wrap"
                @pointerdown="startHorizontalDragScroll"
              >
                <table class="parse-result-panel__field-table parse-result-panel__data-table">
                  <thead>
                    <tr>
                      <th
                        v-for="header in getStructuredObjectHeaders(structuredObject)"
                        :key="`structured-header-${objectIndex}-${header}`"
                      >
                        {{ header }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(row, rowIndex) in structuredObject.table"
                      :key="`structured-row-${objectIndex}-${rowIndex}`"
                    >
                      <td
                        v-for="header in getStructuredObjectHeaders(structuredObject)"
                        :key="`structured-cell-${objectIndex}-${rowIndex}-${header}`"
                      >
                        {{ getStructuredObjectCell(row, header) || '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div
              v-if="extractionFields.length"
              class="parse-result-panel__field-table-wrap"
              @pointerdown="startHorizontalDragScroll"
            >
              <table class="parse-result-panel__field-table">
                <thead>
                  <tr>
	                    <th>{{ t('parse.field') }}</th>
	                    <th>{{ t('parse.value') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="field in extractionFields"
                    :key="`field-${field.label}-${field.value}`"
                  >
                    <th>{{ field.label }}</th>
                    <td>{{ field.value || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div
              v-for="(table, tableIndex) in extractionTables"
              :key="`extraction-table-${tableIndex}-${table.title}`"
              class="parse-result-panel__extraction-table-block"
	            >
	              <div class="parse-result-panel__table-title-row">
	                <strong>{{ table.title || t('parse.tableTitle', { index: tableIndex + 1 }) }}</strong>
	                <span class="parse-result-panel__table-title-actions">
	                  <span>{{ t('parse.rowColumnCount', { rows: table.rows.length, columns: getTableColumnCount(table) }) }}</span>
                  <button
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="openFullscreenTable(getExtractionTableModel(table, tableIndex))"
                  >
	                    {{ t('parse.fullscreen') }}
                  </button>
                  <button
                    type="button"
                    class="parse-result-panel__table-action"
                    @click="downloadTableAsExcel(getExtractionTableModel(table, tableIndex))"
                  >
	                    {{ t('parse.exportExcel') }}
                  </button>
                </span>
              </div>
              <div class="parse-result-panel__field-table-wrap" @pointerdown="startHorizontalDragScroll">
                <table class="parse-result-panel__field-table parse-result-panel__data-table">
                  <thead>
                    <tr>
                      <th
                        v-for="columnIndex in getTableColumnCount(table)"
                        :key="`header-${tableIndex}-${columnIndex}`"
                      >
                        {{ getTableHeader(table, columnIndex - 1) }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in table.rows" :key="`row-${tableIndex}-${rowIndex}`">
                      <td
                        v-for="columnIndex in getTableColumnCount(table)"
                        :key="`cell-${tableIndex}-${rowIndex}-${columnIndex}`"
                      >
                        {{ getTableCell(row, columnIndex - 1) || '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>
        </template>
      </template>

    </div>
  </section>
  <teleport to="body">
    <div
      v-if="fullscreenTable"
      class="parse-result-panel__fullscreen"
      tabindex="0"
      @click.self="closeFullscreenTable"
      @keydown.esc="closeFullscreenTable"
    >
      <section class="parse-result-panel__fullscreen-panel">
        <header class="parse-result-panel__fullscreen-head">
          <div>
            <strong>{{ fullscreenTable.title }}</strong>
	            <span>{{ t('parse.rowColumnCount', { rows: fullscreenTable.rows.length, columns: fullscreenTable.headers.length }) }}</span>
          </div>
          <span class="parse-result-panel__table-title-actions">
            <button
              type="button"
              class="parse-result-panel__table-action"
              @click="downloadTableAsExcel(fullscreenTable)"
            >
	              {{ t('parse.exportExcel') }}
            </button>
            <button
              type="button"
              class="parse-result-panel__table-action parse-result-panel__table-action--plain"
              @click="closeFullscreenTable"
            >
	              {{ t('parse.close') }}
            </button>
          </span>
        </header>
        <div class="parse-result-panel__fullscreen-table-wrap">
          <table class="parse-result-panel__field-table parse-result-panel__data-table parse-result-panel__fullscreen-table">
            <thead>
              <tr>
                <th
                  v-for="header in fullscreenTable.headers"
                  :key="`fullscreen-header-${fullscreenTable.key}-${header}`"
                >
                  {{ header }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, rowIndex) in fullscreenTable.rows"
                :key="`fullscreen-row-${fullscreenTable.key}-${rowIndex}`"
              >
                <td
                  v-for="(cell, cellIndex) in row"
                  :key="`fullscreen-cell-${fullscreenTable.key}-${rowIndex}-${cellIndex}`"
                >
                  {{ cell || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </teleport>
</template>

<style scoped>
.parse-result-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 0;
  height: 100%;
  padding: 0;
  border: 1px solid #d8dee8;
  background: #fff;
  overflow: hidden;
}

.parse-result-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 0 12px;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
}

.parse-result-panel__tabs {
  display: flex;
  align-items: center;
  gap: 20px;
  min-width: 0;
  min-height: 44px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}

.parse-result-panel__tabs::-webkit-scrollbar {
  display: none;
}

.parse-result-panel__header-side {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.parse-result-panel__tab {
  position: relative;
  flex: 0 0 auto;
  padding: 0;
  border: 0;
  background: transparent;
  color: #475569;
  font-size: 12px;
  line-height: 44px;
  white-space: nowrap;
  cursor: pointer;
}

.parse-result-panel__tab.is-active {
  color: #111827;
  font-weight: 600;
}

.parse-result-panel__tab.is-active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: #2563eb;
}

.parse-result-panel__meta {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: #94a3b8;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parse-result-panel__content {
  display: grid;
  gap: 6px;
  min-height: 0;
  overflow: auto;
  align-content: start;
  padding: 10px 12px 12px;
}

.parse-result-panel__target-disclosure {
  margin: -2px 0 4px;
  border: 1px solid #e2e8f0;
  background: #fbfdff;
}

.parse-result-panel__target-disclosure summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 6px 10px;
  color: #334155;
  cursor: pointer;
  list-style: none;
}

.parse-result-panel__target-disclosure summary::-webkit-details-marker {
  display: none;
}

.parse-result-panel__target-disclosure summary::before {
  content: '▸';
  color: #2563eb;
  font-size: 11px;
  line-height: 1;
}

.parse-result-panel__target-disclosure[open] summary::before {
  content: '▾';
}

.parse-result-panel__target-disclosure summary span {
  font-size: 12px;
  font-weight: 700;
}

.parse-result-panel__target-disclosure summary em {
  min-width: 0;
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parse-result-panel__target-list {
  display: flex;
  gap: 6px;
  overflow: auto;
  padding: 6px 0;
}

.parse-result-panel__target-disclosure .parse-result-panel__target-list {
  padding: 0 10px 10px 28px;
}

.parse-result-panel__document-tree {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  background: #fbfdff;
}

.parse-result-panel__document-tree-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #0f172a;
}

.parse-result-panel__document-tree-head strong {
  font-size: 13px;
  font-weight: 700;
}

.parse-result-panel__document-tree-head span {
  color: #64748b;
  font-size: 11px;
}

.parse-result-panel__document-tree-list {
  display: grid;
  gap: 1px;
  border-top: 1px solid #e2e8f0;
}

.parse-result-panel__document-tree-item {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding-top: 5px;
  padding-right: 8px;
  padding-bottom: 5px;
  border-bottom: 1px solid #eef2f7;
  border-top: 0;
  border-left: 0;
  border-right: 0;
  background: transparent;
  color: #1e293b;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  text-align: left;
}

.parse-result-panel__document-tree-item:hover {
  background: #f8fbff;
}

.parse-result-panel__document-tree-item.is-selected {
  background: #eff6ff;
  box-shadow: inset 3px 0 0 #2563eb;
}

.parse-result-panel__document-tree-item.is-page {
  grid-template-columns: 48px minmax(0, 1fr) auto;
  margin-top: 6px;
  background: #f8fafc;
  border-bottom-color: #dbe4f0;
}

.parse-result-panel__document-tree-item.is-page:first-child {
  margin-top: 0;
}

.parse-result-panel__document-tree-item b {
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parse-result-panel__document-tree-item em {
  color: #64748b;
  font-style: normal;
  white-space: nowrap;
}

.parse-result-panel__document-tree-type {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 42px;
  padding: 1px 6px;
  background: #eef2ff;
  color: #3157d7;
  font-size: 11px;
  font-weight: 700;
}

.parse-result-panel__document-tree-item.is-table .parse-result-panel__document-tree-type {
  background: #e8f7ef;
  color: #16834a;
}

.parse-result-panel__document-tree-item.is-list .parse-result-panel__document-tree-type {
  background: #fff7ed;
  color: #b45309;
}

.parse-result-panel__document-tree-item.is-page .parse-result-panel__document-tree-type {
  background: #e0f2fe;
  color: #0369a1;
}

.parse-result-panel__document-tree-item.is-paragraph_group .parse-result-panel__document-tree-type {
  background: #f1f5f9;
  color: #475569;
}

.parse-result-panel__target-button {
  display: grid;
  grid-template-columns: auto minmax(80px, 1fr);
  gap: 2px 6px;
  min-width: 180px;
  max-width: 260px;
  padding: 7px 8px;
  border: 1px solid #d8dee8;
  border-radius: 4px;
  background: #f8fafc;
  color: #1e293b;
  cursor: pointer;
  text-align: left;
}

.parse-result-panel__target-button:hover,
.parse-result-panel__target-button.is-active {
  border-color: #2563eb;
  background: #eff6ff;
}

.parse-result-panel__target-button b {
  color: #2563eb;
  font-size: 11px;
}

.parse-result-panel__target-button span,
.parse-result-panel__target-button em {
  overflow: hidden;
  color: #334155;
  font-size: 11px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parse-result-panel__target-button em {
  grid-column: 1 / -1;
  color: #64748b;
}

.parse-result-panel__table-block {
  display: grid;
  gap: 8px;
  overflow: auto;
}

.parse-result-panel__raw-table {
  overflow-x: auto;
}

.parse-result-panel__raw-table :deep(table) {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  background: #fff;
  font-size: 12px;
}

.parse-result-panel__raw-table :deep(td),
.parse-result-panel__raw-table :deep(th) {
  min-width: 72px;
  padding: 6px 8px;
  border: 1px solid #e5e7eb;
  color: #111827;
  font-size: 11px;
  line-height: 1.45;
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
}

.parse-result-panel__raw-table :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

.parse-result-panel__ocr-lines {
  display: grid;
  border-top: 1px solid #e5e7eb;
}

.parse-result-panel__ocr-segments {
  display: grid;
  gap: 0;
}

.parse-result-panel__ocr-segment {
  padding: 10px 0;
  border-bottom: 1px solid #e5e7eb;
  color: #111827;
  font-size: 12px;
  line-height: 1.7;
  word-break: break-word;
}

.parse-result-panel__ocr-segment.is-table {
  padding: 10px 0 14px;
}

.parse-result-panel__table-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.parse-result-panel__ocr-segment :deep(p),
.parse-result-panel__ocr-segment :deep(ul),
.parse-result-panel__ocr-segment :deep(ol),
.parse-result-panel__ocr-segment :deep(pre) {
  margin: 0 0 8px;
}

.parse-result-panel__ocr-segment :deep(p:last-child),
.parse-result-panel__ocr-segment :deep(ul:last-child),
.parse-result-panel__ocr-segment :deep(ol:last-child),
.parse-result-panel__ocr-segment :deep(pre:last-child) {
  margin-bottom: 0;
}

.parse-result-panel__ocr-caption,
.parse-result-panel__ocr-footnote,
.parse-result-panel__ocr-text {
  margin-bottom: 8px;
  color: #334155;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.parse-result-panel__ocr-caption {
  color: #0f172a;
  font-weight: 600;
}

.parse-result-panel__ocr-table-meta {
  display: inline-flex;
  align-items: center;
  margin: 0 0 8px;
  padding: 2px 8px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #2563eb;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.6;
}

.parse-result-panel__ocr-footnote {
  margin-top: 8px;
  margin-bottom: 0;
  color: #475569;
}

.parse-result-panel__ocr-empty {
  margin: 6px 0 8px;
  padding: 8px 10px;
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-all;
}

.parse-result-panel__ocr-segment :deep(table) {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  background: #fff;
  font-size: 12px;
}

.parse-result-panel__ocr-segment :deep(td),
.parse-result-panel__ocr-segment :deep(th) {
  min-width: 72px;
  padding: 6px 8px;
  border: 1px solid #e5e7eb;
  color: #111827;
  font-size: 11px;
  line-height: 1.45;
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
}

.parse-result-panel__ocr-segment :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

.parse-result-panel__ocr-table-scroll {
  overflow-x: auto;
}

.parse-result-panel__ocr-list {
  display: grid;
  gap: 0;
  border: 1px solid #e2e8f0;
  background: #fff;
}

.parse-result-panel__ocr-list-item {
  padding: 8px 10px;
  border-bottom: 1px solid #e2e8f0;
  color: #111827;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.parse-result-panel__ocr-list-item:last-child {
  border-bottom: 0;
}

.parse-result-panel__ocr-line {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid #e5e7eb;
  background: transparent;
  color: #111827;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.parse-result-panel__ocr-line.is-title {
  grid-template-columns: 1fr;
  padding: 14px 0 10px;
  border-top: 0;
  border-bottom: 1px solid #d8dee8;
  font-weight: 700;
  font-size: 14px;
  background: transparent;
}

.parse-result-panel__ocr-line:not(.is-kv) {
  grid-template-columns: 1fr;
  color: #0f172a;
}

.parse-result-panel__ocr-key {
  color: #64748b;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.parse-result-panel__ocr-value {
  color: #0f172a;
  font-size: 12px;
  font-weight: 500;
  min-width: 0;
}

.parse-result-panel__notice {
  padding: 8px 0;
  color: #2563eb;
  font-size: 12px;
  line-height: 1.6;
}

.parse-result-panel__trace {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.parse-result-panel__trace-item {
  padding: 2px 8px;
  border: 1px solid #dbe6f5;
  border-radius: 4px;
  background: #f8fbff;
  color: #5d6f89;
  font-size: 12px;
  line-height: 18px;
}

.parse-result-panel__extract-summary {
  margin: 0;
  padding: 0 0 8px;
  color: #334155;
  font-size: 12px;
  line-height: 1.7;
}

.parse-result-panel__errors {
  display: grid;
  gap: 6px;
  margin-bottom: 8px;
}

.parse-result-panel__error {
  padding: 7px 10px;
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #9a3412;
  font-size: 11px;
  line-height: 1.5;
}

.parse-result-panel__structured-object {
  display: grid;
  gap: 7px;
  padding: 9px 0 12px;
  border-top: 1px solid #edf2f7;
}

.parse-result-panel__structured-object:first-of-type {
  border-top: 0;
}

.parse-result-panel__output {
  display: grid;
  gap: 8px;
  padding: 9px 0 12px;
  border-top: 1px solid #edf2f7;
}

.parse-result-panel__output:first-of-type {
  border-top: 0;
}

.parse-result-panel__records {
  display: grid;
  gap: 6px;
}

.parse-result-panel__record-table-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.parse-result-panel__record {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e5e7eb;
  background: #fff;
}

.parse-result-panel__record-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.parse-result-panel__record-head strong {
  min-width: 0;
  color: #111827;
  font-size: 12px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parse-result-panel__record-head > span:not(.parse-result-panel__record-head-actions) {
  flex-shrink: 0;
  padding: 2px 6px;
  background: #ecfdf5;
  color: #047857;
  font-size: 11px;
  line-height: 1.35;
}

.parse-result-panel__record-head-actions {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
}

.parse-result-panel__record-head-actions > span {
  padding: 2px 6px;
  background: #ecfdf5;
  color: #047857;
  font-size: 11px;
  line-height: 1.35;
}

.parse-result-panel__structured-kv {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 0;
  margin: 0;
  border: 1px solid #e5e7eb;
  background: #fff;
}

.parse-result-panel__structured-kv dt,
.parse-result-panel__structured-kv dd {
  margin: 0;
  padding: 7px 10px;
  border-bottom: 1px solid #edf2f7;
  color: #111827;
  font-size: 12px;
  line-height: 1.5;
}

.parse-result-panel__structured-kv dt {
  min-width: 96px;
  background: #fbfdff;
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
}

.parse-result-panel__structured-kv dd {
  min-width: 0;
  word-break: break-word;
}

.parse-result-panel__structured-kv dt:nth-last-child(2),
.parse-result-panel__structured-kv dd:last-child {
  border-bottom: 0;
}

.parse-result-panel__field-table-wrap {
  max-height: min(52vh, 560px);
  overflow: auto;
  border: 1px solid #e5e7eb;
  background: #fff;
  cursor: grab;
  overscroll-behavior: contain;
  overscroll-behavior-x: contain;
  scrollbar-gutter: stable;
}

.parse-result-panel__field-table-wrap.is-dragging {
  cursor: grabbing;
  user-select: none;
}

.parse-result-panel__field-table {
  width: 100%;
  min-width: 520px;
  border-collapse: collapse;
  background: #fff;
}

.parse-result-panel__field-table th,
.parse-result-panel__field-table td {
  padding: 7px 10px;
  border-bottom: 1px solid #edf2f7;
  color: #111827;
  font-size: 12px;
  line-height: 1.55;
  text-align: left;
  vertical-align: top;
}

.parse-result-panel__field-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8fafc;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.parse-result-panel__field-table tbody th {
  width: 156px;
  background: #fbfdff;
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
}

.parse-result-panel__field-table td {
  word-break: break-word;
}

.parse-result-panel__field-table tr:last-child th,
.parse-result-panel__field-table tr:last-child td {
  border-bottom: 0;
}

.parse-result-panel__table-semantics {
  display: grid;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid #dbeafe;
  background: #f8fbff;
  color: #475569;
  font-size: 11px;
  line-height: 1.55;
}

.parse-result-panel__table-semantics > div {
  display: grid;
  gap: 3px;
}

.parse-result-panel__table-semantics strong {
  color: #1e3a8a;
  font-size: 11px;
  font-weight: 800;
}

.parse-result-panel__extraction-table-block {
  display: grid;
  gap: 6px;
  padding-top: 4px;
}

.parse-result-panel__table-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #64748b;
  font-size: 11px;
}

.parse-result-panel__table-title-row strong {
  min-width: 0;
  overflow: hidden;
  color: #111827;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parse-result-panel__table-title-actions {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
}

.parse-result-panel__table-action {
  padding: 2px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #fff;
  color: #334155;
  font-size: 10px;
  line-height: 1.5;
  white-space: nowrap;
  cursor: pointer;
}

.parse-result-panel__table-action:hover {
  border-color: #94a3b8;
  background: #f8fafc;
  color: #0f172a;
}

.parse-result-panel__table-action--plain {
  border-color: #e5e7eb;
}

.parse-result-panel__copy-action {
  padding: 2px 8px;
  border: 1px solid #bfdbfe;
  border-radius: 4px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 10px;
  line-height: 1.5;
  cursor: pointer;
}

.parse-result-panel__copy-action:hover {
  border-color: #93c5fd;
  background: #dbeafe;
}

.parse-result-panel__data-table {
  width: max-content;
  min-width: 100%;
}

.parse-result-panel__data-table th,
.parse-result-panel__data-table td {
  min-width: 96px;
  white-space: nowrap;
}

.parse-result-panel__fullscreen {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: stretch;
  padding: 18px;
  background: rgba(15, 23, 42, 0.52);
}

.parse-result-panel__fullscreen-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  border: 1px solid #cbd5e1;
  background: #fff;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.24);
}

.parse-result-panel__fullscreen-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e7eb;
  background: #f8fafc;
}

.parse-result-panel__fullscreen-head div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.parse-result-panel__fullscreen-head strong {
  overflow: hidden;
  color: #111827;
  font-size: 13px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parse-result-panel__fullscreen-head span {
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.parse-result-panel__fullscreen-table-wrap {
  min-height: 0;
  overflow: auto;
  background: #fff;
}

.parse-result-panel__fullscreen-table {
  min-width: 100%;
}

.parse-result-panel__json-block {
  display: grid;
  gap: 6px;
}

.parse-result-panel__json-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #6b7280;
  font-size: 11px;
  font-weight: 600;
  padding-bottom: 4px;
  border-bottom: 1px solid #e5e7eb;
}


.parse-result-panel__empty {
  color: #94a3b8;
  font-size: 11px;
  padding: 12px 0;
}

@media (max-width: 960px) {
  .parse-result-panel__header {
    flex-direction: column;
    align-items: flex-start;
    padding-bottom: 8px;
  }

  .parse-result-panel__header-side {
    justify-content: flex-start;
  }

  .parse-result-panel__tabs {
    gap: 14px;
    min-height: 36px;
  }

  .parse-result-panel__tab {
    line-height: 36px;
  }

  .parse-result-panel__ocr-line {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>
