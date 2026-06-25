<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ObjectOperationResult } from '../types/workbench'
import { startHorizontalDragScroll } from '../utils/dragScroll'
import { buildLlmTraceDisplayItems } from '../utils/llmTrace'

type PlainRecord = Record<string, unknown>

interface TaskCard {
  key: string
  title: string
  conclusion: string
  details: PlainRecord[]
  suggestion: string
  extraEntries: Array<{ key: string; label: string; value: string }>
}

interface ProcessedObjectTable {
  key: string
  title: string
  kvEntries: Array<{ key: string; label: string; value: unknown }>
  headers: string[]
  rows: PlainRecord[]
}

interface RecordArrayTable {
  key: string
  title: string
  headers: string[]
  rows: PlainRecord[]
}

interface TableViewModel {
  key: string
  title: string
  headers: string[]
  rows: string[][]
}

const props = defineProps<{
  result: ObjectOperationResult
  title?: string
}>()

const displayTitle = computed(() => props.title || '处理结果')
const fullscreenTable = ref<TableViewModel | null>(null)
const outputPayload = computed(() => props.result.outputPayload)
const traceItems = computed(() => buildLlmTraceDisplayItems(props.result.llmTraceSummary))
const objectPayload = computed<PlainRecord | null>(() => (
  isPlainRecord(outputPayload.value) ? outputPayload.value : null
))

const tablePayload = computed(() => {
  if (props.result.resultKind !== 'table' || !isPlainRecord(outputPayload.value)) {
    return null
  }
  const headers = Array.isArray(outputPayload.value.headers)
    ? outputPayload.value.headers.map((item) => String(item ?? '').trim()).filter(Boolean)
    : []
  const rows = Array.isArray(outputPayload.value.rows)
    ? outputPayload.value.rows.filter(isPlainRecord)
    : []
  return { headers, rows }
})

const tableRows = computed(() => {
  const table = tablePayload.value
  if (!table) {
    return []
  }
  return table.rows.map((row) => table.headers.map((header) => formatValue(row[header])))
})

const taskCards = computed<TaskCard[]>(() => {
  const payload = objectPayload.value
  if (!payload || processedObjectTables.value.length || props.result.resultKind === 'table') {
    return []
  }

  const taskEntries = Object.entries(payload).filter(([key, value]) =>
    isPlainRecord(value) && (/^task[_-]?\d+/i.test(key) || hasTaskShape(value)),
  )
  if (taskEntries.length) {
    return taskEntries.map(([key, value], index) => normalizeTaskCard(key, value as PlainRecord, index))
  }
  if (hasTaskShape(payload)) {
    return [normalizeTaskCard('task', payload, 0)]
  }
  return []
})

const processedObjectTables = computed<ProcessedObjectTable[]>(() => {
  const payload = objectPayload.value
  if (!payload || props.result.resultKind === 'table') {
    return []
  }
  const source = payload.processed_objects ?? payload.processedObjects
  if (!Array.isArray(source)) {
    return []
  }
  return source
    .filter(isPlainRecord)
    .map((item, index) => {
      const rows = normalizeProcessedRows(item)
      return {
        key: String(item.id || item.key || `processed-object-${index}`),
        title: String(item.label || item.title || `处理对象 ${index + 1}`),
        kvEntries: normalizeProcessedKvEntries(item),
        headers: uniqueStrings(rows.flatMap((row) => Object.keys(row))),
        rows,
      }
    })
    .filter((item) => item.headers.length && item.rows.length)
})

const recordArrayTables = computed<RecordArrayTable[]>(() => {
  const payload = objectPayload.value
  if (!payload || processedObjectTables.value.length || props.result.resultKind === 'table') {
    return []
  }
  return Object.entries(payload)
    .filter(([key, value]) => shouldRenderRecordArray(key, value))
    .map(([key, value], index) => {
      const rows = (value as unknown[])
        .filter(isPlainRecord)
        .map((row) => flattenRecord(row))
      return {
        key,
        title: recordArrayTitle(key, index),
        headers: orderRecordHeaders(uniqueStrings(rows.flatMap((row) => Object.keys(row)))),
        rows,
      }
    })
    .filter((item) => item.headers.length && item.rows.length)
})

const genericEntries = computed(() => {
  const payload = objectPayload.value
  if (
    !payload
    || processedObjectTables.value.length
    || recordArrayTables.value.length
    || taskCards.value.length
    || props.result.resultKind === 'table'
  ) {
    return []
  }
  return Object.entries(payload).map(([key, value]) => ({
    key,
    label: humanizeKey(key),
    value: formatValue(value),
  }))
})

const displayText = computed(() => (
  props.result.resultKind === 'text' && typeof outputPayload.value === 'string'
    ? outputPayload.value.trim()
    : ''
))

function normalizeTaskCard(key: string, value: PlainRecord, index: number): TaskCard {
  const details = Array.isArray(value.details)
    ? value.details.filter(isPlainRecord)
    : []
  return {
    key,
    title: String(value.title || `任务 ${index + 1}`),
    conclusion: String(value.conclusion || value.result || value.status || ''),
    details,
    suggestion: String(value.suggestion || value.recommendation || value.next_step || ''),
    extraEntries: normalizeExtraEntries(value),
  }
}

function normalizeExtraEntries(value: PlainRecord) {
  const reservedKeys = new Set([
    'title',
    'conclusion',
    'result',
    'status',
    'details',
    'suggestion',
    'recommendation',
    'next_step',
  ])
  return Object.entries(value)
    .filter(([key, entryValue]) => !reservedKeys.has(key) && isRenderableValue(entryValue))
    .slice(0, 8)
    .map(([key, entryValue]) => ({
      key,
      label: humanizeKey(key),
      value: formatValue(entryValue),
    }))
}

function hasTaskShape(value: PlainRecord) {
  return Boolean(value.title || value.conclusion || value.details || value.suggestion || value.recommendation)
}

function isPlainRecord(value: unknown): value is PlainRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isRenderableValue(value: unknown) {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value)
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
    (_, index) => headers[index] || `列${index + 1}`,
  )
  return {
    key,
    title,
    headers: safeHeaders,
    rows: normalizedRows.map((row) => safeHeaders.map((_, index) => row[index] || '')),
  }
}

function openFullscreenTable(table: TableViewModel | null) {
  if (!table) {
    return
  }
  fullscreenTable.value = table
}

function closeFullscreenTable() {
  fullscreenTable.value = null
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
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
  if (!table) {
    return
  }
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

function shouldRenderRecordArray(key: string, value: unknown) {
  if (!Array.isArray(value) || !value.some(isPlainRecord)) {
    return false
  }
  return /^(records?|items?|rows?|data|results?|list)$/i.test(key) || value.filter(isPlainRecord).length >= 2
}

function flattenRecord(record: PlainRecord) {
  const flattened: PlainRecord = {}
  for (const [key, value] of Object.entries(record)) {
    flattenRecordEntry(flattened, key, value)
  }
  return flattened
}

function flattenRecordEntry(target: PlainRecord, key: string, value: unknown, parentKey = '') {
  const cleanKey = String(key || '').trim()
  if (!cleanKey) {
    return
  }
  if (isPlainRecord(value)) {
    for (const [childKey, childValue] of Object.entries(value)) {
      flattenRecordEntry(target, childKey, childValue, cleanKey)
    }
    return
  }
  const outputKey = parentKey && target[cleanKey] !== undefined
    ? `${parentKey}_${cleanKey}`
    : cleanKey
  target[outputKey] = value
}

function normalizeProcessedRows(item: PlainRecord) {
  const tableRows = item.table_data ?? item.tableData ?? item.rows
  if (Array.isArray(tableRows)) {
    return tableRows.filter(isPlainRecord)
  }
  const kv = item.kv ?? item.fields
  if (isPlainRecord(kv)) {
    return [kv]
  }
  return []
}

function normalizeProcessedKvEntries(item: PlainRecord) {
  const kv = item.kv_data ?? item.kvData ?? item.kv
  if (!isPlainRecord(kv)) {
    return []
  }
  return Object.entries(kv)
    .filter(([key]) => String(key || '').trim())
    .map(([key, value]) => ({
      key,
      label: String(key),
      value,
    }))
}

function uniqueStrings(values: string[]) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const normalized = String(value || '').trim()
    if (!normalized || seen.has(normalized)) {
      continue
    }
    seen.add(normalized)
    result.push(normalized)
  }
  return result
}

function orderRecordHeaders(headers: string[]) {
  const preferred = [
    'item_code',
    'item_name',
    'specification',
    'quantity',
    'unit_price',
    'structure_type',
    'efficiency_grade',
    'efficiency_class',
    'width',
    'height',
    'depth',
    'thickness',
    'bag_count',
    'filter_material',
    'frame_material',
  ]
  const rank = new Map(preferred.map((key, index) => [key, index]))
  return [...headers].sort((left, right) => {
    const leftRank = rank.get(normalizeHeaderKey(left)) ?? Number.MAX_SAFE_INTEGER
    const rightRank = rank.get(normalizeHeaderKey(right)) ?? Number.MAX_SAFE_INTEGER
    if (leftRank !== rightRank) {
      return leftRank - rightRank
    }
    return headers.indexOf(left) - headers.indexOf(right)
  })
}

function normalizeHeaderKey(key: string) {
  return key.replace(/^parsed_spec[._-]/i, '').trim()
}

function recordArrayTitle(key: string, index: number) {
  if (/^records?$/i.test(key)) {
    return '解析记录'
  }
  if (/^rows?$/i.test(key)) {
    return '数据行'
  }
  if (/^items?$/i.test(key)) {
    return '明细项'
  }
  if (/^results?$/i.test(key)) {
    return '处理明细'
  }
  return humanizeKey(key) || `记录表 ${index + 1}`
}

function humanizeKey(key: string) {
  const normalizedKey = normalizeHeaderKey(key)
  const labels: Record<string, string> = {
    records: '记录',
    item_code: '物料编码',
    item_name: '物料名称',
    specification: '规格描述',
    quantity: '数量',
    unit_price: '单价',
    structure_type: '机构形式',
    efficiency_grade: '效率等级',
    efficiency_class: '效率等级',
    width: '宽',
    height: '高',
    depth: '深',
    thickness: '厚',
    bag_count: '滤袋数量',
    filter_material: '滤料材质',
    frame_material: '外框材质',
    problem_location: '位置',
    problem_cause: '原因',
    target_field: '字段',
    current_value: '当前值',
  }
  return labels[normalizedKey] || labels[key] || key.replace(/_/g, ' ')
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  if (typeof value === 'string') {
    return value
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (Array.isArray(value)) {
    if (value.every(isRenderableValue)) {
      return value.map(formatValue).filter(Boolean).join('、')
    }
    return `共 ${value.length} 项`
  }
  return JSON.stringify(value)
}

function isLongRecordColumn(header: string) {
  return ['specification', 'item_name'].includes(normalizeHeaderKey(header))
}

function getMainTableModel() {
  const table = tablePayload.value
  if (!table || !tableRows.value.length) {
    return null
  }
  return buildTableModel('main-table', displayTitle.value, table.headers, tableRows.value)
}

function getProcessedObjectTableModel(item: ProcessedObjectTable) {
  return buildTableModel(
    item.key,
    item.title,
    item.headers,
    item.rows.map((row) => item.headers.map((header) => getProcessedCell(row[header]).displayValue)),
  )
}

function getRecordArrayTableModel(item: RecordArrayTable) {
  return buildTableModel(
    item.key,
    item.title,
    item.headers.map((header) => humanizeKey(header)),
    item.rows.map((row) => item.headers.map((header) => formatValue(row[header]))),
  )
}

function getTaskDetailsTableModel(task: TaskCard) {
  const headers = taskDetailHeaders(task.details)
  return buildTableModel(
    task.key,
    task.title,
    headers.map((header) => taskDetailLabel(header)),
    task.details.map((detail) => headers.map((header) => formatValue(detail[header]))),
  )
}

function getProcessedCell(value: unknown) {
  if (isPlainRecord(value) && ('rawValue' in value || 'displayValue' in value || 'normalizedValue' in value)) {
    const rawValue = formatValue(value.rawValue)
    const displayValue = formatValue(value.displayValue ?? value.rawValue)
    const normalizedValue = formatValue(value.normalizedValue ?? value.displayValue ?? value.rawValue)
    return {
      rawValue,
      displayValue,
      normalizedValue,
      changed: Boolean(displayValue && rawValue && displayValue !== rawValue),
    }
  }
  const text = formatValue(value)
  return {
    rawValue: text,
    displayValue: text,
    normalizedValue: text,
    changed: false,
  }
}

function processedCellMeta(value: unknown) {
  const cell = getProcessedCell(value)
  const parts: string[] = []
  if (cell.rawValue && cell.rawValue !== cell.displayValue) {
    parts.push(`原值 ${cell.rawValue}`)
  }
  if (
    cell.normalizedValue
    && cell.normalizedValue !== cell.displayValue
    && cell.normalizedValue !== cell.rawValue
  ) {
    parts.push(`标准 ${cell.normalizedValue}`)
  }
  return parts.join(' · ')
}

function conclusionTone(value: string) {
  if (/疑点|异常|风险|失败|错误|问题/.test(value)) {
    return 'warning'
  }
  if (/未发现|正常|通过|完成/.test(value)) {
    return 'success'
  }
  return 'neutral'
}

function taskDetailHeaders(details: PlainRecord[]) {
  const first = details[0]
  if (!first) {
    return []
  }
  const preferred = ['field', 'value', 'status', 'problem', 'suggestion']
  const headers = preferred.filter((key) => key in first)
  return headers.length ? headers : Object.keys(first).slice(0, 6)
}

function taskDetailLabel(key: string) {
  const labels: Record<string, string> = {
    field: '字段',
    value: '值',
    status: '状态',
    problem: '问题',
    suggestion: '建议',
  }
  return labels[key] || humanizeKey(key)
}
</script>

<template>
  <div class="process-result-card">
    <div class="process-result-card__head">
      <div class="process-result-card__title">{{ displayTitle }}</div>
      <div class="process-result-card__head-side">
        <a-tag size="small" color="arcoblue">业务处理</a-tag>
        <a-tag size="small" color="green">{{ result.resultKind }}</a-tag>
      </div>
    </div>
    <div class="process-result-card__summary">{{ result.summary }}</div>
    <div v-if="traceItems.length" class="process-result-card__trace">
      <span
        v-for="item in traceItems"
        :key="item.label"
        class="process-result-card__trace-item"
      >
        {{ item.label }}：{{ item.value }}
      </span>
    </div>

    <div v-if="result.validationErrors.length" class="process-result-card__warnings">
      <div
        v-for="(item, index) in result.validationErrors"
        :key="`${index}-${item}`"
        class="process-result-card__warning"
      >
        {{ item }}
      </div>
    </div>

    <template v-if="tablePayload && tableRows.length">
      <div class="process-result-card__table-toolbar">
        <span>{{ tableRows.length }} 行 · {{ tablePayload.headers.length }} 列</span>
        <span class="process-result-card__table-actions">
          <button type="button" class="process-result-card__table-action" @click="openFullscreenTable(getMainTableModel())">
            全屏
          </button>
          <button type="button" class="process-result-card__table-action" @click="downloadTableAsExcel(getMainTableModel())">
            导出 Excel
          </button>
        </span>
      </div>
      <div
        class="process-result-card__table-scroll"
        @pointerdown="startHorizontalDragScroll"
      >
        <table class="process-result-card__table">
          <thead>
            <tr>
              <th v-for="header in tablePayload.headers" :key="header">{{ header }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in tableRows" :key="rowIndex">
              <td v-for="(value, valueIndex) in row" :key="`${rowIndex}-${valueIndex}`">
                {{ value || '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-else-if="processedObjectTables.length" class="process-result-card__tasks">
      <article v-for="item in processedObjectTables" :key="item.key" class="process-result-card__task">
        <div class="process-result-card__task-head">
          <strong>{{ item.title }}</strong>
          <span class="process-result-card__table-actions">
            <span class="process-result-card__status process-result-card__status--success">
              {{ item.rows.length }} 行
            </span>
            <button type="button" class="process-result-card__table-action" @click="openFullscreenTable(getProcessedObjectTableModel(item))">
              全屏
            </button>
            <button type="button" class="process-result-card__table-action" @click="downloadTableAsExcel(getProcessedObjectTableModel(item))">
              导出 Excel
            </button>
          </span>
        </div>
        <div v-if="item.kvEntries.length" class="process-result-card__processed-kv">
          <div
            v-for="entry in item.kvEntries"
            :key="entry.key"
            class="process-result-card__processed-kv-item"
          >
            <span>{{ entry.label }}</span>
            <strong :class="{ 'is-changed': getProcessedCell(entry.value).changed }">
              {{ getProcessedCell(entry.value).displayValue || '—' }}
            </strong>
            <small v-if="processedCellMeta(entry.value)">{{ processedCellMeta(entry.value) }}</small>
          </div>
        </div>
        <div class="process-result-card__table-scroll" @pointerdown="startHorizontalDragScroll">
          <table class="process-result-card__table">
            <thead>
              <tr>
                <th v-for="header in item.headers" :key="header">{{ header }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rowIndex) in item.rows" :key="rowIndex">
                <td v-for="header in item.headers" :key="`${rowIndex}-${header}`">
                  <div
                    class="process-result-card__processed-cell"
                    :class="{ 'is-changed': getProcessedCell(row[header]).changed }"
                  >
                    <strong>{{ getProcessedCell(row[header]).displayValue || '—' }}</strong>
                    <span v-if="processedCellMeta(row[header])">
                      {{ processedCellMeta(row[header]) }}
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>

    <div v-else-if="recordArrayTables.length" class="process-result-card__tasks">
      <article v-for="item in recordArrayTables" :key="item.key" class="process-result-card__task">
        <div class="process-result-card__task-head">
          <strong>{{ item.title }}</strong>
          <span class="process-result-card__table-actions">
            <span class="process-result-card__status process-result-card__status--success">
              {{ item.rows.length }} 条
            </span>
            <button type="button" class="process-result-card__table-action" @click="openFullscreenTable(getRecordArrayTableModel(item))">
              全屏
            </button>
            <button type="button" class="process-result-card__table-action" @click="downloadTableAsExcel(getRecordArrayTableModel(item))">
              导出 Excel
            </button>
          </span>
        </div>
        <div class="process-result-card__table-scroll" @pointerdown="startHorizontalDragScroll">
          <table class="process-result-card__table process-result-card__table--records">
            <thead>
              <tr>
                <th
                  v-for="header in item.headers"
                  :key="header"
                  :class="{ 'process-result-card__table-cell--long': isLongRecordColumn(header) }"
                >
                  {{ humanizeKey(header) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rowIndex) in item.rows" :key="rowIndex">
                <td
                  v-for="header in item.headers"
                  :key="`${rowIndex}-${header}`"
                  :class="{ 'process-result-card__table-cell--long': isLongRecordColumn(header) }"
                >
                  {{ formatValue(row[header]) || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>

    <div v-else-if="taskCards.length" class="process-result-card__tasks">
      <article v-for="task in taskCards" :key="task.key" class="process-result-card__task">
        <div class="process-result-card__task-head">
          <strong>{{ task.title }}</strong>
          <span
            v-if="task.conclusion"
            class="process-result-card__status"
            :class="`process-result-card__status--${conclusionTone(task.conclusion)}`"
          >
            {{ task.conclusion }}
          </span>
        </div>
        <template v-if="task.details.length">
          <div class="process-result-card__table-toolbar">
            <span>{{ task.details.length }} 行 · {{ taskDetailHeaders(task.details).length }} 列</span>
            <span class="process-result-card__table-actions">
              <button type="button" class="process-result-card__table-action" @click="openFullscreenTable(getTaskDetailsTableModel(task))">
                全屏
              </button>
              <button type="button" class="process-result-card__table-action" @click="downloadTableAsExcel(getTaskDetailsTableModel(task))">
                导出 Excel
              </button>
            </span>
          </div>
          <div
            class="process-result-card__table-scroll"
            @pointerdown="startHorizontalDragScroll"
          >
            <table class="process-result-card__table">
              <thead>
                <tr>
                  <th v-for="header in taskDetailHeaders(task.details)" :key="header">
                    {{ taskDetailLabel(header) }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(detail, detailIndex) in task.details" :key="detailIndex">
                  <td
                    v-for="header in taskDetailHeaders(task.details)"
                    :key="`${detailIndex}-${header}`"
                  >
                    {{ formatValue(detail[header]) || '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <dl v-if="task.extraEntries.length || task.suggestion" class="process-result-card__kv-list">
          <template v-for="entry in task.extraEntries" :key="entry.key">
            <dt>{{ entry.label }}</dt>
            <dd>{{ entry.value || '—' }}</dd>
          </template>
          <template v-if="task.suggestion">
            <dt>建议</dt>
            <dd>{{ task.suggestion }}</dd>
          </template>
        </dl>
      </article>
    </div>

    <dl v-else-if="genericEntries.length" class="process-result-card__kv-list">
      <template v-for="entry in genericEntries" :key="entry.key">
        <dt>{{ entry.label }}</dt>
        <dd>{{ entry.value || '—' }}</dd>
      </template>
    </dl>

    <pre v-else-if="displayText" class="process-result-card__output">{{ displayText }}</pre>
  </div>
  <teleport to="body">
    <div
      v-if="fullscreenTable"
      class="process-result-card__fullscreen"
      tabindex="0"
      @click.self="closeFullscreenTable"
      @keydown.esc="closeFullscreenTable"
    >
      <section class="process-result-card__fullscreen-panel">
        <header class="process-result-card__fullscreen-head">
          <div>
            <strong>{{ fullscreenTable.title }}</strong>
            <span>{{ fullscreenTable.rows.length }} 行 · {{ fullscreenTable.headers.length }} 列</span>
          </div>
          <span class="process-result-card__table-actions">
            <button
              type="button"
              class="process-result-card__table-action"
              @click="downloadTableAsExcel(fullscreenTable)"
            >
              导出 Excel
            </button>
            <button
              type="button"
              class="process-result-card__table-action process-result-card__table-action--plain"
              @click="closeFullscreenTable"
            >
              关闭
            </button>
          </span>
        </header>
        <div class="process-result-card__fullscreen-table-wrap">
          <table class="process-result-card__table process-result-card__fullscreen-table">
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
.process-result-card {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
  background: transparent;
}

.process-result-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.process-result-card__head-side {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.process-result-card__title {
  color: #111827;
  font-size: 12px;
  font-weight: 600;
}

.process-result-card__summary {
  margin-top: 8px;
  color: #111827;
  font-size: 12px;
  line-height: 1.6;
}

.process-result-card__trace {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.process-result-card__trace-item {
  padding: 2px 8px;
  border: 1px solid #dbe6f5;
  border-radius: 4px;
  background: #f8fbff;
  color: #5d6f89;
  font-size: 12px;
  line-height: 18px;
}

.process-result-card__warnings,
.process-result-card__tasks {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.process-result-card__warning {
  padding: 7px 10px;
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #9a3412;
  font-size: 11px;
  line-height: 1.5;
}

.process-result-card__task {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e5e7eb;
  background: #fff;
}

.process-result-card__task-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.process-result-card__task-head strong {
  min-width: 0;
  color: #111827;
  font-size: 12px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-result-card__processed-kv {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: 6px;
}

.process-result-card__processed-kv-item {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid #e5e7eb;
  background: #f8fafc;
}

.process-result-card__processed-kv-item span {
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.process-result-card__processed-kv-item strong {
  color: #111827;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.45;
  word-break: break-word;
}

.process-result-card__processed-kv-item strong.is-changed {
  color: #166534;
  font-weight: 600;
}

.process-result-card__processed-kv-item small {
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.process-result-card__status {
  flex: 0 0 auto;
  max-width: 160px;
  padding: 2px 6px;
  overflow: hidden;
  font-size: 11px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-result-card__status--success {
  background: #ecfdf3;
  color: #067647;
}

.process-result-card__status--warning {
  background: #fff7ed;
  color: #b45309;
}

.process-result-card__status--neutral {
  background: #f1f5f9;
  color: #475569;
}

.process-result-card__table-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.process-result-card__table-actions {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
}

.process-result-card__table-action {
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

.process-result-card__table-action:hover {
  border-color: #94a3b8;
  background: #f8fafc;
  color: #0f172a;
}

.process-result-card__table-action--plain {
  border-color: #e5e7eb;
}

.process-result-card__table-scroll {
  margin-top: 10px;
  overflow: auto;
  border: 1px solid #e5e7eb;
  cursor: grab;
  overscroll-behavior-x: contain;
  scrollbar-gutter: stable;
}

.process-result-card__table-scroll.is-dragging {
  cursor: grabbing;
  user-select: none;
}

.process-result-card__table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  background: #fff;
}

.process-result-card__table th,
.process-result-card__table td {
  min-width: 96px;
  padding: 6px 8px;
  border-bottom: 1px solid #e5e7eb;
  color: #111827;
  font-size: 12px;
  line-height: 1.45;
  text-align: left;
  white-space: nowrap;
}

.process-result-card__table th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 600;
}

.process-result-card__table--records th,
.process-result-card__table--records td {
  vertical-align: top;
}

.process-result-card__table-cell--long {
  min-width: 180px;
  max-width: 260px;
  white-space: normal;
  word-break: break-word;
}

.process-result-card__fullscreen {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: stretch;
  padding: 18px;
  background: rgba(15, 23, 42, 0.52);
}

.process-result-card__fullscreen-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  border: 1px solid #cbd5e1;
  background: #fff;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.24);
}

.process-result-card__fullscreen-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e7eb;
  background: #f8fafc;
}

.process-result-card__fullscreen-head div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.process-result-card__fullscreen-head strong {
  overflow: hidden;
  color: #111827;
  font-size: 13px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-result-card__fullscreen-head span {
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.process-result-card__fullscreen-table-wrap {
  min-height: 0;
  overflow: auto;
  background: #fff;
}

.process-result-card__fullscreen-table {
  min-width: 100%;
}

.process-result-card__fullscreen-table th {
  position: sticky;
  top: 0;
  z-index: 1;
}

.process-result-card__processed-cell {
  display: grid;
  gap: 2px;
  min-width: 112px;
}

.process-result-card__processed-cell strong {
  color: #111827;
  font-size: 12px;
  font-weight: 500;
}

.process-result-card__processed-cell span {
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.process-result-card__processed-cell.is-changed strong {
  color: #166534;
  font-weight: 600;
}

.process-result-card__kv-list {
  display: grid;
  grid-template-columns: minmax(80px, 160px) minmax(0, 1fr);
  gap: 8px 12px;
  margin: 10px 0 0;
}

.process-result-card__kv-list dt {
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.process-result-card__kv-list dd {
  min-width: 0;
  margin: 0;
  color: #111827;
  font-size: 12px;
  line-height: 1.55;
  word-break: break-word;
}

.process-result-card__output {
  margin: 8px 0 0;
  padding: 10px 0 0;
  border-top: 1px solid #e5e7eb;
  background: transparent;
  color: #334155;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 960px) {
  .process-result-card__kv-list {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>
