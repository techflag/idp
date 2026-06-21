import type { ContentRange } from '../types/applicationWorkshop'
import type { WorkbenchBlock, WorkbenchPage } from '../types/workbench'

type RangeBuildItem = {
  block: WorkbenchBlock
  kind: string
  text: string
  bbox: [number, number, number, number]
}

export function buildPageSourceText(page: WorkbenchPage, limit = 12000) {
  const blocks = page.blocks
    .map((block, index) => buildPageBlockSourceText(block, index))
    .filter((item) => item.trim())
  const rawItems = page.rawItems.slice(0, 6).map((item) => `raw：${safeJson(item)}`)
  return [
    `第 ${page.pageNo} 页完整 OCR 内容`,
    `内容块数量：${page.blocks.length}`,
    '',
    ...blocks,
    rawItems.length ? '## 原始识别片段' : '',
    ...rawItems,
  ].filter(Boolean).join('\n\n').slice(0, limit)
}

export function buildPageContentRanges(page: WorkbenchPage): ContentRange[] {
  const items = page.blocks
    .map((block) => ({
      block,
      kind: block.type.trim().toLowerCase() || 'text',
      text: blockText(block),
      bbox: normalizeBbox(block, page),
    }))
    .filter((item) => !isAuxiliaryRangeKind(item.kind))
    .filter((item) => item.text || isTableRangeKind(item.kind))
    .sort((left, right) => left.bbox[1] - right.bbox[1] || left.bbox[0] - right.bbox[0])

  const groups: RangeBuildItem[][] = []
  let current: RangeBuildItem[] = []
  for (const item of items) {
    const previous = current[current.length - 1]
    if (previous && canMergeRangeItems(previous, item)) {
      current.push(item)
      continue
    }
    if (current.length) groups.push(current)
    current = [item]
  }
  if (current.length) groups.push(current)

  return groups.map((group, index) => {
    const kind = group[0].kind
    const text = group.map((item) => item.text).filter(Boolean).join(' ')
    const label = buildRangeTitle(kind, index, text)
    return {
      id: `range:${page.pageIndex}:${index}:${group.map((item) => item.block.id).join('-')}`,
      pageIndex: page.pageIndex,
      pageNo: page.pageNo,
      label,
      kind,
      bbox: unionBbox(group.map((item) => item.bbox)),
      blockIds: group.map((item) => item.block.id),
      pageRange: `第 ${page.pageNo} 页`,
      summary: summarizeText(text || label, 96),
      text,
    }
  })
}

export function buildPageBlockSourceText(block: WorkbenchBlock, index: number) {
  const typeLabel = formatRangeKindLabel(block.type)
  const title = [typeLabel, block.title || `内容块 ${index + 1}`].filter(Boolean).join('：')
  if (isTableRangeKind(block.type)) {
    const tableMarkdown = tableMarkdownFromHtml(block.htmlContent || block.content)
    const fallbackText = stripHtml([block.title, block.content, block.htmlContent].filter(Boolean).join('\n'))
    return [
      `## ${title}`,
      `blockId：${block.id}`,
      tableMarkdown ? `表格内容：\n${tableMarkdown}` : '',
      !tableMarkdown && fallbackText ? `表格文本：${fallbackText}` : '',
      block.htmlContent ? `原始表格 HTML：${block.htmlContent.slice(0, 1800)}` : '',
    ].filter(Boolean).join('\n')
  }
  const text = blockText(block)
  if (!text) return ''
  return [
    `## ${title}`,
    `blockId：${block.id}`,
    text,
  ].join('\n')
}

export function tableMarkdownFromHtml(html: string | undefined) {
  const rows = tableRowsFromHtml(html || '')
  if (!rows.length) return ''
  const width = Math.max(...rows.map((row) => row.length), 0)
  const normalizedRows = rows.map((row) => Array.from({ length: width }, (_, index) => markdownCell(row[index] || '')))
  const header = normalizedRows[0] ?? []
  const lines = [
    `| ${header.join(' | ')} |`,
    `| ${Array.from({ length: width }, () => '---').join(' | ')} |`,
    ...normalizedRows.slice(1).map((row) => `| ${row.join(' | ')} |`),
  ]
  return lines.join('\n')
}

export function tableRowsFromHtml(html: string) {
  if (typeof DOMParser === 'undefined' || !html.trim()) return []
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const table = doc.querySelector('table')
  if (!table) return []
  const pending = new Map<string, string>()
  const rows: string[][] = []
  Array.from(table.querySelectorAll('tr')).forEach((tr, rowIndex) => {
    const row: string[] = []
    let columnIndex = 0
    const advancePending = () => {
      while (pending.has(`${rowIndex}:${columnIndex}`)) {
        row.push(pending.get(`${rowIndex}:${columnIndex}`) || '')
        pending.delete(`${rowIndex}:${columnIndex}`)
        columnIndex += 1
      }
    }
    Array.from(tr.querySelectorAll('th,td')).forEach((cell) => {
      advancePending()
      const text = String(cell.textContent || '').replace(/\s+/g, ' ').trim()
      const rowSpan = Math.max(1, Number(cell.getAttribute('rowspan') || 1) || 1)
      const colSpan = Math.max(1, Number(cell.getAttribute('colspan') || 1) || 1)
      for (let offset = 0; offset < colSpan; offset += 1) {
        row.push(text)
        if (rowSpan > 1) {
          for (let rowOffset = 1; rowOffset < rowSpan; rowOffset += 1) {
            pending.set(`${rowIndex + rowOffset}:${columnIndex + offset}`, text)
          }
        }
      }
      columnIndex += colSpan
    })
    advancePending()
    if (row.some((cell) => cell.trim())) {
      rows.push(row)
    }
  })
  return rows
}

export function markdownCell(value: string) {
  return value.replace(/\|/g, '\\|').replace(/\n+/g, ' ').trim()
}

export function blockText(block: WorkbenchBlock) {
  return stripHtml([block.title, block.content, block.htmlContent].filter(Boolean).join('\n'))
}

export function stripHtml(value: string) {
  return value
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function safeJson(value: unknown) {
  try {
    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
    return String(text || '').slice(0, 1800)
  } catch {
    return ''
  }
}

export function normalizeBbox(block: WorkbenchBlock, page: WorkbenchPage): [number, number, number, number] {
  const [pageWidth, pageHeight] = page.pageSize
  const bbox = block.bbox
  const normalized = bbox.every((value) => value >= 0 && value <= 1.2)
    ? bbox
    : [bbox[0] / pageWidth, bbox[1] / pageHeight, bbox[2] / pageWidth, bbox[3] / pageHeight]
  return [
    clamp01(normalized[0]),
    clamp01(normalized[1]),
    clamp01(normalized[2]),
    clamp01(normalized[3]),
  ]
}

export function clamp01(value: number) {
  return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
}

export function isTableRangeKind(kind: string) {
  return kind.includes('table')
}

export function isAuxiliaryRangeKind(kind: string) {
  return ['page_header', 'page_footer', 'page_number', 'page_aside_text', 'page_footnote', 'header', 'footer'].includes(kind)
}

export function canMergeRangeItems(left: RangeBuildItem, right: RangeBuildItem) {
  if (left.kind !== right.kind) return false
  if (isTableRangeKind(left.kind)) return false
  const verticalGap = Math.max(0, right.bbox[1] - left.bbox[3])
  const horizontalOverlap = Math.max(0, Math.min(left.bbox[2], right.bbox[2]) - Math.max(left.bbox[0], right.bbox[0]))
  const minWidth = Math.max(Math.min(left.bbox[2] - left.bbox[0], right.bbox[2] - right.bbox[0]), 0.01)
  return verticalGap <= 0.026 && horizontalOverlap / minWidth >= 0.2
}

export function unionBbox(boxes: Array<[number, number, number, number]>): [number, number, number, number] {
  return [
    Math.min(...boxes.map((box) => box[0])),
    Math.min(...boxes.map((box) => box[1])),
    Math.max(...boxes.map((box) => box[2])),
    Math.max(...boxes.map((box) => box[3])),
  ]
}

export function buildRangeTitle(kind: string, index: number, text: string) {
  const leadText = summarizeText(text, 18)
  return leadText ? `${formatRangeKindLabel(kind)} · ${leadText}` : `${formatRangeKindLabel(kind)} ${index + 1}`
}

export function summarizeText(text: string, maxLength: number) {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength)}...`
}

export function formatRangeKindLabel(kind: string) {
  const labelMap: Record<string, string> = {
    text: '文本',
    paragraph: '文本',
    title: '标题',
    list: '列表',
    table: '表格',
    table_body: '表格',
    table_caption: '表格标题',
    image: '图片',
    chart: '图表',
    code: '代码',
    algorithm: '算法',
    equation_interline: '公式',
    header: '页眉',
    footer: '页脚',
    page_header: '页眉',
    page_footer: '页脚',
    page_number: '页码',
    page_aside_text: '旁注',
    page_footnote: '脚注',
  }
  return labelMap[kind] ?? kind
}
