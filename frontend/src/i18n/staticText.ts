// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
import { nextTick, watch } from 'vue'
import { currentLocale } from './index'
import { phraseReplacements, staticText as enStaticText } from './locales/en-US'

const HAN_RE = /[\u3400-\u9fff]/
const textOriginals = new WeakMap<Text, string>()
const attrOriginals = new WeakMap<Element, Map<string, string>>()
const LOCALIZABLE_ATTRS = ['title', 'aria-label', 'placeholder']
const SKIP_SELECTOR = [
  '[data-i18n-skip]',
  'input',
  'textarea',
  'pre',
  'code',
  'kbd',
  'samp',
  '[contenteditable="true"]',
  '.json-tree',
  '.skill-markdown-editor__textarea',
  '.skill-markdown-editor__preview',
  '.preview-pane__file-name',
  '.preview-pane__text-layer',
  '.preview-pane__overlay',
  '.document-source-pane__content',
  '.source-preview-pane__content',
  '.ocr-text',
].join(',')

function hasHan(text: string) {
  return HAN_RE.test(text)
}

function compact(text: string) {
  return text.replace(/\s+/g, ' ').trim()
}

function exactTranslate(text: string) {
  const trimmed = compact(text)
  return enStaticText[trimmed]
}

function replaceDynamicPatterns(text: string) {
  return text
    .replace(/步骤\s*(\d+)/g, 'Step $1')
    .replace(/页码\s*(.+)$/g, 'Pages $1')
    .replace(/证据页码：(.+)$/g, 'Evidence pages: $1')
    .replace(/查看其余\s*(\d+)\s*个命中模块/g, 'View $1 more matched modules')
    .replace(/相关模块\s*(\d+)\s*个（不参与抽取）/g, '$1 related modules (not used for extraction)')
    .replace(/JSON\s*暂不可确认：(.+)$/g, 'JSON cannot be confirmed yet: $1')
    .replace(/试跑校验：(.+)$/g, 'Trial validation: $1')
    .replace(/输出契约：(.+)$/g, 'Output contract: $1')
    .replace(/证据包：(.+)$/g, 'Evidence package: $1')
    .replace(/期望\s*(.+?)，实际\s*(.+?)。/g, 'Expected $1, actual $2.')
    .replace(/Skill frontmatter output\.type=(.+?)，运行契约=(.+?)。/g, 'Skill frontmatter output.type=$1, runtime contract=$2.')
    .replace(/基于样例材料制作的文档应用，包含\s*(\d+)\s*个数据提取步骤。/g, 'Document application created from sample material, containing $1 data extraction steps.')
    .replace(/基于样例材料制作的文档应用，包含\s*(\d+)\s*个数据提取步骤和\s*(\d+)\s*个业务处理步骤。/g, 'Document application created from sample material, containing $1 data extraction steps and $2 business processing steps.')
    .replace(/用样例材料沉淀\s*(\d+)\s*个可复用处理步骤/g, 'Create $1 reusable processing steps from sample material')
    .replace(/运行\s*(.+?)\s*仍在执行。/g, 'Run $1 is still executing.')
    .replace(/查询：(.+)$/g, 'Query: $1')
    .replace(/对象：(.+)$/g, 'Object: $1')
    .replace(/正向：(.+)$/g, 'Positive: $1')
    .replace(/排除：(.+)$/g, 'Exclude: $1')
    .replace(/(.+?)，例如：查询记录、订单明细、检测结果/g, '$1, e.g. query records, order details, inspection results')
    .replace(/已整理\s*(\d+)\s*个样例对象，样本文本\s*(\d+)\s*字。生成内容只是初稿，可以继续编辑。/g, '$1 sample objects organized; sample text $2 characters. Generated content is only a draft and can still be edited.')
    .replace(/样例运行：(.+?)\s*·\s*输出：(.+)/g, 'Sample run: $1 · Output: $2')
    .replace(/负责人：(.+?)。从这里查看该客户下全部文档、解析状态与最近更新时间，并直接进入对应任务。/g, 'Owner: $1. View all documents, parse status, and latest update time for this customer, and open the related task directly.')
    .replace(/(.+?)\s*上传后会自动创建识别任务，并进入工作台。/g, '$1 will create a recognition task automatically after upload and open the workbench.')
    .replace(/已选择\s*(.+?)，正在上传验证。/g, 'Selected $1. Uploading for validation.')
    .replace(/客户与登录账号已创建，可直接使用账号\s*(.+?)\s*登录。/g, 'Customer and login account created. You can log in with account $1.')
    .replace(/应用\s*(.+?)\s*已发布。/g, 'Application $1 published.')
    .replace(/每页\s*(\d+)\s*个\s*·\s*第\s*(\d+)\s*\/\s*(\d+)\s*页/g, '$1 per page · Page $2 / $3')
    .replace(/(\d+)\s*个结果/g, '$1 results')
    .replace(/(\d+)\s*个客户空间/g, '$1 customer workspaces')
    .replace(/(\d+)\s*个步骤/g, '$1 steps')
    .replace(/(\d+)\s*步链路/g, '$1-step flow')
    .replace(/(\d+)\s*页\s*·\s*(\d+)\s*次识别/g, '$1 pages · $2 recognition runs')
    .replace(/当前第\s*(\d+)\s*\/\s*(\d+)\s*页/g, 'Current page $1 / $2')
    .replace(/共\s*(\d+)\s*个。?/g, '$1 total.')
    .replace(/(\d+)\s*个\s*HTML\s*表格，默认展示前\s*(\d+)\s*个。?/g, '$1 HTML tables. Showing the first $2 by default.')
    .replace(/当前范围：(.+?)。可直接按任务、客户、文档、状态与更新时间进入工作台。/g, 'Current scope: $1. Open the workbench by task, customer, document, status, or update time.')
    .replace(/发布于\s*(\d{4}-\d{2}-\d{2})/g, 'Published $1')
    .replace(/上传于\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)/g, 'Uploaded $1')
    .replace(/样本\s*(\d+)/g, 'Samples $1')
    .replace(/试跑\s*(\d+)/g, 'Trials $1')
    .replace(/最近\s*(\d{4}-\d{2}-\d{2})/g, 'Latest $1')
    .replace(/更新\s*(\d{4}-\d{2}-\d{2})/g, 'Updated $1')
    .replace(/更新于\s*(\d{4}-\d{2}-\d{2})/g, 'Updated $1')
    .replace(/最近更新\s*(.+)$/g, 'Latest update $1')
    .replace(/还差\s*(\d+)\s*项/g, '$1 items remaining')
    .replace(/输入\s*(\d+)\s*字符\s*·\s*输出\s*(\d+)\s*字符/g, 'Input $1 chars · Output $2 chars')
    .replace(/(\d+(?:\.\d+)?)\s*秒/g, '$1s')
}

function isHanChar(value: string) {
  return HAN_RE.test(value)
}

function replaceBoundedPhrase(text: string, source: string, target: string) {
  if (!source || !hasHan(source)) {
    return text.split(source).join(target)
  }
  let result = ''
  let cursor = 0
  while (cursor < text.length) {
    const index = text.indexOf(source, cursor)
    if (index < 0) {
      result += text.slice(cursor)
      break
    }
    const before = index > 0 ? text[index - 1] : ''
    const afterIndex = index + source.length
    const after = afterIndex < text.length ? text[afterIndex] : ''
    const bounded = (!before || !isHanChar(before)) && (!after || !isHanChar(after))
    result += text.slice(cursor, index)
    result += bounded ? target : source
    cursor = afterIndex
  }
  return result
}

function replacePhrases(text: string) {
  let translated = replaceDynamicPatterns(text)
  const staticReplacements = Object.entries(enStaticText)
    .filter(([source]) => hasHan(source) && source.length >= 6)
    .sort((a, b) => b[0].length - a[0].length)
  for (const [source, target] of staticReplacements) {
    translated = replaceBoundedPhrase(translated, source, target)
  }
  const sorted = [...phraseReplacements].sort((a, b) => b[0].length - a[0].length)
  for (const [source, target] of sorted) {
    translated = replaceBoundedPhrase(translated, source, target)
  }
  translated = replaceDynamicPatterns(translated)
  translated = translated
    .replace(/第\s*(\d+)\s*页/g, 'Page $1')
    .replace(/共\s*(\d+)\s*页/g, '$1 pages total')
    .replace(/(\d+)\s*页/g, '$1 pages')
    .replace(/(\d+)\s*条\/页/g, '$1 / page')
    .replace(/(\d+)\s*条/g, '$1 items')
    .replace(/(\d+)\s*个/g, '$1')
    .replace(/(\d+)\s*步/g, '$1 steps')
    .replace(/(\d+)\s*次/g, '$1 times')
  return translated
}

export function translateStaticText(value: string) {
  if (currentLocale.value !== 'en-US') return value
  if (!hasHan(value)) return value
  const exact = exactTranslate(value)
  if (exact) return value.replace(compact(value), exact)
  return replacePhrases(value)
}

function shouldSkip(node: Node) {
  const element = node.nodeType === Node.ELEMENT_NODE
    ? node as Element
    : node.parentElement
  return Boolean(element?.closest(SKIP_SELECTOR))
}

function shouldSkipAttributes(element: Element) {
  return Boolean(element.closest([
    '[data-i18n-skip]',
    'pre',
    'code',
    'kbd',
    'samp',
    '[contenteditable="true"]',
    '.json-tree',
    '.skill-markdown-editor__textarea',
    '.skill-markdown-editor__preview',
    '.preview-pane__file-name',
    '.preview-pane__text-layer',
    '.preview-pane__overlay',
    '.document-source-pane__content',
    '.source-preview-pane__content',
    '.ocr-text',
  ].join(',')))
}

function localizeTextNode(node: Text) {
  if (shouldSkip(node)) return
  const current = node.nodeValue ?? ''
  const original = textOriginals.get(node) ?? current
  if (!textOriginals.has(node)) {
    textOriginals.set(node, original)
  }
  if (!hasHan(original)) return
  const next = currentLocale.value === 'en-US' ? translateStaticText(original) : original
  if (node.nodeValue !== next) {
    node.nodeValue = next
  }
}

function originalAttrMap(element: Element) {
  let map = attrOriginals.get(element)
  if (!map) {
    map = new Map<string, string>()
    attrOriginals.set(element, map)
  }
  return map
}

function localizeAttributes(element: Element) {
  if (shouldSkipAttributes(element)) return
  const originals = originalAttrMap(element)
  for (const attr of LOCALIZABLE_ATTRS) {
    const current = element.getAttribute(attr)
    if (!current) continue
    const original = originals.get(attr) ?? current
    if (!originals.has(attr)) {
      originals.set(attr, original)
    }
    if (!hasHan(original)) continue
    const next = currentLocale.value === 'en-US' ? translateStaticText(original) : original
    if (current !== next) {
      element.setAttribute(attr, next)
    }
  }
}

function walk(root: ParentNode) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    localizeTextNode(node as Text)
    node = walker.nextNode()
  }
  if (root instanceof Element) {
    localizeAttributes(root)
  }
  root.querySelectorAll?.('[title], [aria-label], [placeholder]').forEach(localizeAttributes)
}

export function installStaticTextI18n(root: ParentNode = document.body) {
  let scheduled = false
  const run = () => {
    scheduled = false
    walk(root)
  }
  const schedule = () => {
    if (scheduled) return
    scheduled = true
    window.requestAnimationFrame(run)
  }
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === 'characterData') {
        localizeTextNode(mutation.target as Text)
        continue
      }
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.TEXT_NODE) {
          localizeTextNode(node as Text)
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          walk(node as Element)
        }
      }
    }
  })
  observer.observe(root, {
    childList: true,
    characterData: true,
    subtree: true,
  })
  watch(currentLocale, async () => {
    await nextTick()
    schedule()
  })
  schedule()
  return () => observer.disconnect()
}
