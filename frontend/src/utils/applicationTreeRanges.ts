// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
import type { ContentRange, DocumentTreeSource } from '../types/applicationWorkshop'
import type { WorkbenchPage } from '../types/workbench'
import { clamp01 } from './applicationWorkshopContent'

export function buildTreeNodePreviewRanges(
  node: DocumentTreeSource,
  pages: WorkbenchPage[],
): ContentRange[] {
  if (!node.locations?.length) {
    return []
  }
  return node.locations.map((location, index) => {
    const pageIndex = pageIndexFromPageNo(location.pageNo, pages)
    const page = pages.find((item) => item.pageNo === location.pageNo) ?? null
    return {
      id: `tree:${node.id}:${index}`,
      pageIndex,
      pageNo: location.pageNo,
      label: cleanTreeRangeLabel(node.label) || node.typeLabel,
      kind: node.type,
      bbox: normalizeTreeBbox(location.bbox, page),
      blockIds: [],
      pageRange: node.sourceScope || `第 ${location.pageNo} 页`,
      summary: node.preview || node.label,
      text: node.sourceText,
    }
  })
}

export function findBestRangeForTreeNode(
  node: DocumentTreeSource,
  ranges: ContentRange[],
): ContentRange | null {
  const allowedPages = new Set(node.pageNos)
  const nodeText = normalizeMatchText([node.label, node.preview, node.sourceText].join(' '))
  const candidates = ranges.filter((range) => !allowedPages.size || allowedPages.has(range.pageNo))
  let best: { range: ContentRange; score: number } | null = null

  for (const range of candidates) {
    const rangeText = normalizeMatchText([range.label, range.summary, range.text].join(' '))
    const score = scoreTreeRangeMatch(nodeText, rangeText, allowedPages.has(range.pageNo))
    if (!best || score > best.score) {
      best = { range, score }
    }
  }

  return best && best.score >= 0.22 ? best.range : null
}

function cleanTreeRangeLabel(value: string) {
  return value.replace(/^(文本|表格|列表|标题|图片)\s*·\s*/, '').trim() || value
}

function pageIndexFromPageNo(pageNo: number, pages: WorkbenchPage[]) {
  const page = pages.find((item) => item.pageNo === pageNo)
  return page?.pageIndex ?? Math.max(0, pageNo - 1)
}

function normalizeTreeBbox(bbox: [number, number, number, number], page: WorkbenchPage | null): [number, number, number, number] {
  if (bbox.every((value) => value >= 0 && value <= 1.2)) {
    return [clamp01(bbox[0]), clamp01(bbox[1]), clamp01(bbox[2]), clamp01(bbox[3])]
  }

  const pageSize = page?.pageSize
  const pageWidth = pageSize?.[0] ?? 0
  const pageHeight = pageSize?.[1] ?? 0
  const maxX = Math.max(bbox[0], bbox[2])
  const maxY = Math.max(bbox[1], bbox[3])

  if (pageWidth > 0 && pageHeight > 0 && maxX <= pageWidth * 1.2 && maxY <= pageHeight * 1.2) {
    return normalizeBboxBySize(bbox, pageWidth, pageHeight)
  }

  const rawScale = inferRawBboxScale(page, bbox)
  if (rawScale) {
    return normalizeBboxBySize(bbox, rawScale[0], rawScale[1])
  }

  return normalizeBboxBySize(bbox, Math.max(maxX, 1), Math.max(maxY, 1))
}

function normalizeBboxBySize(
  bbox: [number, number, number, number],
  width: number,
  height: number,
): [number, number, number, number] {
  return [
    clamp01(bbox[0] / width),
    clamp01(bbox[1] / height),
    clamp01(bbox[2] / width),
    clamp01(bbox[3] / height),
  ]
}

function inferRawBboxScale(page: WorkbenchPage | null, bbox: [number, number, number, number]): [number, number] | null {
  const maxX = Math.max(bbox[0], bbox[2])
  const maxY = Math.max(bbox[1], bbox[3])

  if (maxX <= 1200 && maxY <= 1200) {
    return [1000, 1000]
  }

  const rawExtent = getRawItemBboxExtent(page)
  if (!rawExtent) {
    return null
  }

  return [
    Math.max(rawExtent[0], maxX, 1),
    Math.max(rawExtent[1], maxY, 1),
  ]
}

function getRawItemBboxExtent(page: WorkbenchPage | null): [number, number] | null {
  const boxes = (page?.rawItems ?? [])
    .map((item) => readRawItemBbox(item))
    .filter((bbox): bbox is [number, number, number, number] => Boolean(bbox))
  if (!boxes.length) {
    return null
  }

  return [
    Math.max(...boxes.map((item) => Math.max(item[0], item[2]))),
    Math.max(...boxes.map((item) => Math.max(item[1], item[3]))),
  ]
}

function readRawItemBbox(value: unknown): [number, number, number, number] | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const raw = (value as Record<string, unknown>).bbox
  if (!Array.isArray(raw) || raw.length < 4) {
    return null
  }
  const values = raw.slice(0, 4).map((item) => Number(item))
  if (values.some((item) => !Number.isFinite(item))) {
    return null
  }
  return [values[0], values[1], values[2], values[3]]
}

export function normalizeMatchText(value: string) {
  return value
    .replace(/<\|txt_split\|>?/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, '')
    .toLowerCase()
    .slice(0, 5000)
}

function scoreTreeRangeMatch(nodeText: string, rangeText: string, samePage: boolean) {
  if (!nodeText || !rangeText) return 0
  let score = samePage ? 0.08 : 0
  if (nodeText.includes(rangeText) || rangeText.includes(nodeText)) {
    score += 0.6
  }

  const shorter = nodeText.length <= rangeText.length ? nodeText : rangeText
  const longer = shorter === nodeText ? rangeText : nodeText
  const sample = shorter.slice(0, 180)
  if (sample && longer.includes(sample)) {
    score += 0.22
  }

  const shorterChars = new Set(shorter.slice(0, 800))
  const longerChars = new Set(longer.slice(0, 1600))
  let intersection = 0
  shorterChars.forEach((char) => {
    if (longerChars.has(char)) intersection += 1
  })
  score += Math.min(0.32, (intersection / Math.max(shorterChars.size, 1)) * 0.32)
  return score
}
