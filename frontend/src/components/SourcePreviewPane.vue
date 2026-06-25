<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
/**
 * 负责左侧原文预览区的 PDF 页渲染、页码切换与 bbox 叠加高亮。
 *
 * 数据边界说明：
 * - 输入：当前任务详情、当前页索引、当前选中的识别块 id
 * - 输出：当前页变更事件、识别块选中事件
 *
 * 这里直接把 PDF 渲染收口在组件内部，避免继续依赖浏览器内嵌 PDF 插件，
 * 同时让 bbox 高亮和中间列/第三列的联动落在同一个应用状态里。
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowRef,
  watch,
} from 'vue'
import {
  GlobalWorkerOptions,
  getDocument,
  type PDFDocumentLoadingTask,
  type PDFDocumentProxy,
  type RenderTask,
} from 'pdfjs-dist/legacy/build/pdf.mjs'
import PdfWorker from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?worker'
import PanelCard from './PanelCard.vue'
import type { WorkbenchBlock, WorkbenchPage, WorkbenchTaskDetail } from '../types/workbench'

export interface SourcePreviewContentRange {
  id: string
  pageIndex: number
  pageNo: number
  label: string
  kind: string
  bbox: [number, number, number, number]
  blockIds: string[]
  confidence?: number
}
type PreviewPage = Pick<WorkbenchPage, 'pageIndex' | 'pageNo' | 'pageSize' | 'blocks'>

// Let Vite bundle the pdf.js worker as a normal worker chunk so deployment
// does not depend on the web server serving `.mjs` assets with the right MIME.
const pdfWorkerPort = new PdfWorker()
GlobalWorkerOptions.workerPort = pdfWorkerPort

const props = defineProps<{
  detail: WorkbenchTaskDetail
  currentPageIndex: number
  selectedBlockId: string
  overlayMode?: 'blocks' | 'ranges'
  contentRanges?: SourcePreviewContentRange[]
  selectedRangeId?: string
}>()

const emit = defineEmits<{
  changePage: [pageIndex: number]
  selectBlock: [blockId: string, pageIndex?: number]
  selectRange: [rangeId: string, pageIndex?: number]
}>()

const viewerRef = ref<HTMLDivElement | null>(null)
const scrollRef = ref<HTMLDivElement | null>(null)
const pdfDocument = shallowRef<PDFDocumentProxy | null>(null)
const viewerWidth = ref(0)
const isDocumentLoading = ref(false)
const isPageRendering = ref(false)
const renderError = ref('')
const pdfPageCount = ref(0)
const pageRenderDone = ref<Record<number, boolean>>({})
const zoomScale = ref(1)
const pageRotations = ref<Record<number, number>>({})

let resizeObserver: ResizeObserver | null = null
let documentLoadingTask: PDFDocumentLoadingTask | null = null
let renderTask: RenderTask | null = null
let renderLoopPromise: Promise<void> | null = null
let documentTransitionPromise: Promise<void> = Promise.resolve()
let documentTransitionId = 0
let previewIntentId = 0
let documentRequestId = 0
let renderRequestId = 0
let scrollFrameId = 0
let lastScrollDrivenPageIndex: number | null = null

const canvasMap = new Map<number, HTMLCanvasElement>()
const stageMap = new Map<number, HTMLDivElement>()
const bboxMap = new Map<string, HTMLButtonElement>()
const previewFileUrl = computed(() => normalizePreviewFileUrl(props.detail.document.pdfUrl))
const previewKind = computed<'pdf' | 'image' | 'unsupported'>(() => {
  if (isImageDocument(props.detail.document.fileType, props.detail.document.fileName)) {
    return 'image'
  }
  if (isPdfDocument(props.detail.document.fileType, props.detail.document.fileName)) {
    return 'pdf'
  }
  return 'unsupported'
})

const fallbackPageCount = computed(() => {
  if (props.detail.pages.length) return 0
  if (previewKind.value === 'image') return 1
  if (previewKind.value === 'pdf') {
    return pdfPageCount.value || props.detail.document.pageCount || props.detail.document.sampledPageCount || 1
  }
  return 0
})
const previewPages = computed<PreviewPage[]>(() => {
  if (props.detail.pages.length) return props.detail.pages
  return Array.from({ length: fallbackPageCount.value }, (_, index) => ({
    pageIndex: index,
    pageNo: index + 1,
    pageSize: [595, 842],
    blocks: [],
  }))
})
const activePage = computed(
  () => previewPages.value.find((page) => page.pageIndex === props.currentPageIndex) ?? previewPages.value[0],
)
const preferredRenderPageIndexes = computed(() =>
  new Set(
    previewPages.value
      .filter((page) => Math.abs(page.pageIndex - props.currentPageIndex) <= 1)
      .map((page) => page.pageIndex),
  ),
)

const pagePosition = computed(() => {
  const page = activePage.value
  const index = previewPages.value.findIndex((item) => item.pageIndex === page?.pageIndex)
  return index >= 0 ? index + 1 : 1
})

const activeBlocks = computed(() => activePage.value?.blocks ?? [])
const activeBlock = computed(
  () => activeBlocks.value.find((block) => block.id === props.selectedBlockId) ?? null,
)
const selectedRange = computed(
  () => (props.contentRanges ?? []).find((range) => range.id === props.selectedRangeId) ?? null,
)
const activePageRanges = computed(() =>
  (props.contentRanges ?? []).filter((range) => range.pageIndex === activePage.value?.pageIndex),
)
const canPrev = computed(() => pagePosition.value > 1)
const canNext = computed(() => pagePosition.value < previewPages.value.length)
const visiblePageCount = computed(
  () => props.detail.document.sampledPageCount || props.detail.document.pageCount || previewPages.value.length,
)
const zoomPercent = computed(() => `${Math.round(zoomScale.value * 100)}%`)
const currentPageRotation = computed(() => {
  const pageIndex = activePage.value?.pageIndex
  return typeof pageIndex === 'number' ? getPageRotation(pageIndex) : 0
})
const rotationSignature = computed(() => JSON.stringify(pageRotations.value))
const imageStageStyle = computed(() => {
  const page = activePage.value
  const fallbackWidth = Math.max(Math.floor((viewerWidth.value || 352) - 32), 320)
  const stageWidth = fallbackWidth * zoomScale.value
  const pageWidth = page?.pageSize?.[0] || 1000
  const pageHeight = page?.pageSize?.[1] || 1414

  return {
    width: `${stageWidth}px`,
    height: `${(stageWidth * pageHeight) / pageWidth}px`,
  }
})

function buildPreviewSnapshot(
  fileUrl: string,
  kind: 'pdf' | 'image' | 'unsupported',
  currentIntentId: number,
) {
  return {
    taskId: props.detail.task.id,
    currentPageIndex: props.currentPageIndex,
    pageCount: previewPages.value.length,
    previewIntentId: currentIntentId,
    fileUrl,
    kind,
  }
}

function normalizePreviewFileUrl(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function changePage(pageIndex: number, source: 'direct' | 'scroll' = 'direct') {
  if (source === 'direct') {
    lastScrollDrivenPageIndex = null
  }
  emit('changePage', pageIndex)
}

function goPrev() {
  if (!canPrev.value) {
    return
  }

  const prev = previewPages.value[pagePosition.value - 2]
  if (prev) {
    scrollToPage(prev.pageIndex, 'smooth')
    changePage(prev.pageIndex, 'direct')
  }
}

function goNext() {
  if (!canNext.value) {
    return
  }

  const next = previewPages.value[pagePosition.value]
  if (next) {
    scrollToPage(next.pageIndex, 'smooth')
    changePage(next.pageIndex, 'direct')
  }
}

function zoomIn() {
  zoomScale.value = Math.min(Number((zoomScale.value + 0.15).toFixed(2)), 2)
}

function zoomOut() {
  zoomScale.value = Math.max(Number((zoomScale.value - 0.15).toFixed(2)), 0.7)
}

function resetZoom() {
  zoomScale.value = 1
}

function toPercent(value: number, total: number) {
  return `${(value / total) * 100}%`
}

function isNormalizedBbox(bbox: [number, number, number, number]) {
  return bbox.every((value) => value >= 0 && value <= 1.2)
}

function getPageRotation(pageIndex: number) {
  return pageRotations.value[pageIndex] ?? 0
}

function rotateCurrentPage() {
  if (!activePage.value) {
    return
  }

  const pageIndex = activePage.value.pageIndex
  pageRotations.value = {
    ...pageRotations.value,
    [pageIndex]: (getPageRotation(pageIndex) + 90) % 360,
  }
}

function resetCurrentPageRotation() {
  if (!activePage.value) {
    return
  }

  const pageIndex = activePage.value.pageIndex
  pageRotations.value = {
    ...pageRotations.value,
    [pageIndex]: 0,
  }
}

function getRotatedPageSize(pageSize: [number, number], rotation: number): [number, number] {
  return rotation === 90 || rotation === 270 ? [pageSize[1], pageSize[0]] : pageSize
}

function rotateBbox(
  bbox: [number, number, number, number],
  pageSize: [number, number],
  rotation: number,
): [number, number, number, number] {
  const [x1, y1, x2, y2] = bbox
  const [pageWidth, pageHeight] = pageSize

  if (rotation === 90) {
    return [pageHeight - y2, x1, pageHeight - y1, x2]
  }

  if (rotation === 180) {
    return [pageWidth - x2, pageHeight - y2, pageWidth - x1, pageHeight - y1]
  }

  if (rotation === 270) {
    return [y1, pageWidth - x2, y2, pageWidth - x1]
  }

  return bbox
}

function getBlockStyle(block: WorkbenchBlock, pageSize: [number, number], rotation = 0) {
  if (isNormalizedBbox(block.bbox)) {
    const [x1, y1, x2, y2] = block.bbox
    return {
      left: `${x1 * 100}%`,
      top: `${y1 * 100}%`,
      width: `${Math.max(x2 - x1, 0) * 100}%`,
      height: `${Math.max(y2 - y1, 0) * 100}%`,
    }
  }

  const nextBbox = rotateBbox(block.bbox, pageSize, rotation)
  const [stageWidth, stageHeight] = getRotatedPageSize(pageSize, rotation)

  return {
    left: toPercent(nextBbox[0], stageWidth),
    top: toPercent(nextBbox[1], stageHeight),
    width: toPercent(nextBbox[2] - nextBbox[0], stageWidth),
    height: toPercent(nextBbox[3] - nextBbox[1], stageHeight),
  }
}

function getRangeStyle(range: SourcePreviewContentRange, pageSize: [number, number], rotation = 0) {
  return getBlockStyle({
    id: range.id,
    pageIndex: range.pageIndex,
    pageNo: range.pageNo,
    blockPosition: '',
    type: range.kind,
    title: range.label,
    content: '',
    bbox: range.bbox,
  }, pageSize, rotation)
}

function getPageRanges(pageIndex: number) {
  return (props.contentRanges ?? []).filter((range) => range.pageIndex === pageIndex)
}

function hasRangeOverlay(pageIndex: number) {
  return props.overlayMode === 'ranges' && getPageRanges(pageIndex).length > 0
}

function formatBlockTypeLabel(type: string) {
  const normalizedType = type.trim().toLowerCase()

  if (normalizedType === 'table' || normalizedType === 'table_body' || normalizedType === 'table_caption') {
    return '表格'
  }

  if (normalizedType === 'title') {
    return '标题'
  }

  if (normalizedType === 'text' || normalizedType === 'paragraph') {
    return '文本'
  }

  if (normalizedType === 'list') {
    return '列表'
  }

  if (normalizedType === 'image') return '图片'
  if (normalizedType === 'chart') return '图表'
  if (normalizedType === 'code') return '代码'
  if (normalizedType === 'algorithm') return '算法'
  if (normalizedType === 'equation_interline') return '公式'
  if (normalizedType === 'page_header' || normalizedType === 'header') return '页眉'
  if (normalizedType === 'page_footer' || normalizedType === 'footer') return '页脚'
  if (normalizedType === 'page_number') return '页码'
  if (normalizedType === 'page_aside_text') return '旁注'
  if (normalizedType === 'page_footnote') return '脚注'

  return type
}

function formatRangeKindLabel(kind: string) {
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

function isPdfDocument(fileType: string, fileName: string) {
  return fileType.trim().toUpperCase() === 'PDF' || /\.pdf$/i.test(fileName)
}

function isImageDocument(fileType: string, fileName: string) {
  return fileType.trim().toUpperCase().startsWith('IMAGE/') || /\.(png|jpe?g|gif|webp)$/i.test(fileName)
}

function updateViewerWidth() {
  viewerWidth.value = scrollRef.value?.clientWidth ?? viewerRef.value?.clientWidth ?? 0
}

function cancelActiveRender() {
  renderTask?.cancel()
  renderTask = null
}

function invalidateActiveRender() {
  renderRequestId += 1
  cancelActiveRender()
}

async function waitForActiveRenderLoop() {
  const pending = renderLoopPromise
  if (!pending) {
    return
  }

  try {
    await pending
  } catch {
    // The render loop already surfaces user-facing errors through `renderError`.
  }
}

async function enqueueDocumentTransition(
  _reason: 'load' | 'dispose',
  _payload: Record<string, unknown>,
  operation: () => Promise<void>,
) {
  const runOperation = async () => {
    documentTransitionId += 1
    await operation()
  }

  const nextTransition = documentTransitionPromise.then(runOperation, runOperation)
  documentTransitionPromise = nextTransition.catch(() => {})
  return nextTransition
}

function setCanvasRef(pageIndex: number, element: HTMLCanvasElement | null) {
  if (!element) {
    canvasMap.delete(pageIndex)
    return
  }
  canvasMap.set(pageIndex, element)
}

function setStageRef(pageIndex: number, element: HTMLDivElement | null) {
  if (!element) {
    stageMap.delete(pageIndex)
    return
  }
  stageMap.set(pageIndex, element)
}

function getBboxRefKey(pageIndex: number, blockId: string) {
  return `${pageIndex}:${blockId}`
}

function setBboxRef(pageIndex: number, blockId: string, element: HTMLButtonElement | null) {
  const key = getBboxRefKey(pageIndex, blockId)
  if (!element) {
    bboxMap.delete(key)
    return
  }
  bboxMap.set(key, element)
}

function getDesiredFocusZoom(block: WorkbenchBlock, pageSize: [number, number]) {
  const blockWidth = Math.max(block.bbox[2] - block.bbox[0], 1)
  const blockHeight = Math.max(block.bbox[3] - block.bbox[1], 1)
  const widthRatio = blockWidth / Math.max(pageSize[0], 1)
  const heightRatio = blockHeight / Math.max(pageSize[1], 1)
  const scaleFromWidth = 0.78 / widthRatio
  const scaleFromHeight = 0.68 / heightRatio
  return Math.max(1, Math.min(2.6, Number(Math.min(scaleFromWidth, scaleFromHeight).toFixed(2))))
}

async function focusSelectedBlock(allowZoom = true) {
  const page = activePage.value
  const block = activeBlock.value
  const container = scrollRef.value
  if (!page || !block || !container) {
    return
  }

  if (allowZoom) {
    const desiredZoom = getDesiredFocusZoom(block, page.pageSize)
    if (desiredZoom > zoomScale.value + 0.05) {
      zoomScale.value = desiredZoom
      await nextTick()
      requestAnimationFrame(() => {
        void focusSelectedBlock(false)
      })
      return
    }
  }

  scrollToPage(page.pageIndex, 'smooth')

  await nextTick()
  requestAnimationFrame(() => {
    const bboxElement = bboxMap.get(getBboxRefKey(page.pageIndex, block.id))
    if (!bboxElement || !scrollRef.value) {
      return
    }

    const scroller = scrollRef.value
    const containerRect = scroller.getBoundingClientRect()
    const bboxRect = bboxElement.getBoundingClientRect()
    const nextTop = scroller.scrollTop + (bboxRect.top - containerRect.top) - (containerRect.height - bboxRect.height) / 2
    const nextLeft = scroller.scrollLeft + (bboxRect.left - containerRect.left) - (containerRect.width - bboxRect.width) / 2

    scroller.scrollTo({
      top: Math.max(nextTop, 0),
      left: Math.max(nextLeft, 0),
      behavior: 'smooth',
    })
  })
}

async function focusSelectedRange() {
  const range = selectedRange.value
  const container = scrollRef.value
  if (!range || !container) {
    return
  }

  scrollToPage(range.pageIndex, 'smooth')

  await nextTick()
  requestAnimationFrame(() => {
    const bboxElement = bboxMap.get(getBboxRefKey(range.pageIndex, `range:${range.id}`))
    if (!bboxElement || !scrollRef.value) {
      return
    }

    const scroller = scrollRef.value
    const containerRect = scroller.getBoundingClientRect()
    const bboxRect = bboxElement.getBoundingClientRect()
    const nextTop = scroller.scrollTop + (bboxRect.top - containerRect.top) - (containerRect.height - bboxRect.height) / 2
    const nextLeft = scroller.scrollLeft + (bboxRect.left - containerRect.left) - (containerRect.width - bboxRect.width) / 2

    scroller.scrollTo({
      top: Math.max(nextTop, 0),
      left: Math.max(nextLeft, 0),
      behavior: 'smooth',
    })
  })
}

/**
 * 在文档 URL 变化时重新加载 PDF，并销毁上一次的文档实例。
 *
 * 这里把 worker 请求和旧文档清理集中在一处，避免页码切换时重复加载整份 PDF，
 * 也避免旧请求回写到新任务上。
 */
async function loadPdfDocument(
  pdfUrl: string,
  context: {
    previewIntentId: number
    taskId: string
    currentPageIndex: number
    pageCount: number
    fileUrl: string
    kind: 'pdf'
  },
) {
  const requestId = ++documentRequestId

  invalidateActiveRender()
  await waitForActiveRenderLoop()
  renderError.value = ''
  isDocumentLoading.value = true
  pdfPageCount.value = 0
  pageRenderDone.value = {}
  pageRotations.value = {}

  if (documentLoadingTask) {
    await documentLoadingTask.destroy()
    documentLoadingTask = null
  }

  if (pdfDocument.value) {
    await pdfDocument.value.destroy()
    pdfDocument.value = null
  }

  const normalizedPdfUrl = normalizePreviewFileUrl(pdfUrl)
  if (!normalizedPdfUrl) {
    if (requestId === documentRequestId) {
      renderError.value = '原始 PDF 文件地址缺失，无法预览。请从来源任务打开或重新上传样例。'
      isDocumentLoading.value = false
    }
    return
  }

  try {
    const loadingTask = getDocument({ url: normalizedPdfUrl })
    documentLoadingTask = loadingTask
    const nextDocument = await loadingTask.promise

    if (requestId !== documentRequestId || context.previewIntentId !== previewIntentId) {
      await nextDocument.destroy()
      return
    }

    pdfDocument.value = nextDocument
    pdfPageCount.value = nextDocument.numPages
  } catch (error) {
    if (requestId === documentRequestId) {
      renderError.value = error instanceof Error ? error.message : 'PDF 文档加载失败。'
    }
  } finally {
    if (requestId === documentRequestId) {
      isDocumentLoading.value = false
      documentLoadingTask = null
    }
  }
}

async function disposePdfDocument() {
  invalidateActiveRender()
  await waitForActiveRenderLoop()
  isDocumentLoading.value = false
  isPageRendering.value = false
  pdfPageCount.value = 0
  pageRenderDone.value = {}
  pageRotations.value = {}

  if (documentLoadingTask) {
    await documentLoadingTask.destroy()
    documentLoadingTask = null
  }

  if (pdfDocument.value) {
    await pdfDocument.value.destroy()
    pdfDocument.value = null
  }
}

function handleImageLoad() {
  renderError.value = ''
}

function handleImageError() {
  renderError.value = '图片加载失败。'
}

/**
 * 只渲染当前激活页，并按当前容器宽度重新计算缩放。
 *
 * 输入字段说明：
 * - `activePage.pageNo`：决定向 PDF.js 取哪一页
 * - `viewerWidth`：决定当前页在左栏里的实际展示宽度
 *
 * 输出字段说明：
 * - `canvas`：当前页的位图结果
 * - 覆盖层：与 `page.pageSize` 同比例的 bbox 高亮层
 *
 * 这样做的目的是把“当前页阅读”和“块级高亮”收口成同一套坐标系，
 * 避免再依赖浏览器 PDF 插件提供的页内定位能力。
 */
async function renderAllPages() {
  const documentProxy = pdfDocument.value
  const width = viewerWidth.value

  if (!documentProxy || width <= 0 || previewPages.value.length === 0) {
    return
  }

  const requestId = ++renderRequestId

  cancelActiveRender()
  isPageRendering.value = true
  renderError.value = ''

  try {
    const baseWidth = Math.max(Math.floor(width - 32), 320)

    for (const page of previewPages.value) {
      if (!preferredRenderPageIndexes.value.has(page.pageIndex)) {
        continue
      }

      const canvas = canvasMap.get(page.pageIndex)
      if (!canvas) {
        continue
      }

      const pdfPage = await documentProxy.getPage(page.pageNo)

      if (requestId !== renderRequestId) {
        return
      }

      const rotation = getPageRotation(page.pageIndex)
      const baseViewport = pdfPage.getViewport({ scale: 1, rotation })
      const scale = (baseWidth * zoomScale.value) / baseViewport.width
      const viewport = pdfPage.getViewport({ scale, rotation })
      const outputScale = window.devicePixelRatio || 1
      const context = canvas.getContext('2d')

      if (!context) {
        throw new Error('无法初始化 PDF 渲染上下文。')
      }

      canvas.width = Math.floor(viewport.width * outputScale)
      canvas.height = Math.floor(viewport.height * outputScale)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`

      context.setTransform(1, 0, 0, 1, 0, 0)
      context.clearRect(0, 0, canvas.width, canvas.height)

      const currentRenderTask = pdfPage.render({
        canvas,
        canvasContext: context,
        viewport,
        transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      })

      renderTask = currentRenderTask
      await currentRenderTask.promise

      if (requestId !== renderRequestId) {
        return
      }

      pageRenderDone.value = {
        ...pageRenderDone.value,
        [page.pageIndex]: true,
      }
      renderTask = null
    }
  } catch (error) {
    const isCancelled =
      typeof error === 'object'
      && error !== null
      && 'name' in error
      && error.name === 'RenderingCancelledException'

    if (!isCancelled && requestId === renderRequestId) {
      renderError.value = error instanceof Error ? error.message : 'PDF 页面渲染失败。'
    }
  } finally {
    if (requestId === renderRequestId) {
      isPageRendering.value = false
    }
  }
}

function scrollToPage(pageIndex: number, behavior: ScrollBehavior = 'auto') {
  const container = scrollRef.value
  const stage = stageMap.get(pageIndex)

  if (!container || !stage) {
    return
  }

  const targetTop = Math.max(stage.offsetTop - 16, 0)
  if (Math.abs(container.scrollTop - targetTop) < 32) {
    return
  }

  container.scrollTo({
    top: targetTop,
    behavior,
  })
}

function updateCurrentPageFromScroll() {
  const container = scrollRef.value
  if (!container) {
    return
  }

  const anchor = container.scrollTop + 40
  let nextPageIndex = props.currentPageIndex
  let bestDistance = Number.POSITIVE_INFINITY

  for (const page of previewPages.value) {
    const stage = stageMap.get(page.pageIndex)
    if (!stage) {
      continue
    }

    const distance = Math.abs(stage.offsetTop - anchor)
    if (distance < bestDistance) {
      bestDistance = distance
      nextPageIndex = page.pageIndex
    }
  }

  if (nextPageIndex !== props.currentPageIndex) {
    lastScrollDrivenPageIndex = nextPageIndex
    changePage(nextPageIndex, 'scroll')
  }
}

function handleScroll() {
  if (scrollFrameId) {
    cancelAnimationFrame(scrollFrameId)
  }

  scrollFrameId = requestAnimationFrame(() => {
    scrollFrameId = 0
    updateCurrentPageFromScroll()
  })
}

watch(
  () => [previewFileUrl.value, previewKind.value] as const,
  async ([fileUrl, kind]) => {
    const currentIntentId = ++previewIntentId
    const snapshot = buildPreviewSnapshot(fileUrl, kind, currentIntentId)
    if (kind !== 'pdf') {
      await enqueueDocumentTransition('dispose', snapshot, async () => {
        await disposePdfDocument()
      })
      renderError.value = ''
      return
    }

    await enqueueDocumentTransition('load', snapshot, async () => {
      await loadPdfDocument(fileUrl, {
        ...snapshot,
        kind: 'pdf',
      })
    })
  },
  { immediate: true },
)

watch(
  [
    pdfDocument,
    viewerWidth,
    zoomScale,
    rotationSignature,
    () => previewPages.value.length,
    () => props.currentPageIndex,
  ],
  async ([documentProxy, width]) => {
    if (!documentProxy || width <= 0) {
      return
    }

    const currentPromise = (async () => {
      await nextTick()
      await renderAllPages()
    })()

    renderLoopPromise = currentPromise
    try {
      await currentPromise
    } finally {
      if (renderLoopPromise === currentPromise) {
        renderLoopPromise = null
      }
    }
  },
  { immediate: true },
)

watch(
  () => props.currentPageIndex,
  async (pageIndex) => {
    if (lastScrollDrivenPageIndex === pageIndex) {
      lastScrollDrivenPageIndex = null
      return
    }
    await nextTick()
    scrollToPage(pageIndex, 'auto')
  },
)

watch(
  () => props.selectedBlockId,
  async (blockId) => {
    if (!blockId) {
      return
    }
    await focusSelectedBlock(false)
  },
)

watch(
  () => props.selectedRangeId,
  async (rangeId) => {
    if (!rangeId) {
      return
    }
    await focusSelectedRange()
  },
)

onMounted(() => {
  updateViewerWidth()
  resizeObserver = new ResizeObserver(() => {
    updateViewerWidth()
  })

  if (viewerRef.value) {
    resizeObserver.observe(viewerRef.value)
  }
})

onBeforeUnmount(async () => {
  resizeObserver?.disconnect()
  invalidateActiveRender()
  await waitForActiveRenderLoop()
  if (scrollFrameId) {
    cancelAnimationFrame(scrollFrameId)
    scrollFrameId = 0
  }

  if (documentLoadingTask) {
    await documentLoadingTask.destroy()
    documentLoadingTask = null
  }

  if (pdfDocument.value) {
    await pdfDocument.value.destroy()
    pdfDocument.value = null
  }
})
</script>

<template>
  <div class="preview-pane">
    <PanelCard
      title="原文"
    >
      <template #extra>
        <div class="preview-pane__toolbar">
          <a-button size="mini" type="text" :disabled="!canPrev" title="上一页" @click="goPrev">上页</a-button>
          <span class="preview-pane__pager">{{ activePage?.pageNo ?? 1 }} / {{ visiblePageCount }}</span>
          <a-button size="mini" type="text" :disabled="!canNext" title="下一页" @click="goNext">下页</a-button>
          <span class="preview-pane__toolbar-separator" />
          <a-button size="mini" type="text" title="缩小" @click="zoomOut">-</a-button>
          <a-button size="mini" type="text" title="恢复 100%" @click="resetZoom">{{ zoomPercent }}</a-button>
          <a-button size="mini" type="text" title="放大" @click="zoomIn">+</a-button>
          <span v-if="previewKind === 'pdf'" class="preview-pane__toolbar-separator" />
          <a-button v-if="previewKind === 'pdf'" size="mini" type="text" title="旋转当前页" @click="rotateCurrentPage">旋转</a-button>
          <a-button
            v-if="previewKind === 'pdf' && currentPageRotation !== 0"
            size="mini"
            type="text"
            title="复位方向"
            @click="resetCurrentPageRotation"
          >
            复位
          </a-button>
        </div>
      </template>

      <div class="preview-pane__viewer">
        <div class="preview-pane__viewer-header">
          <span class="preview-pane__file-name" :title="detail.document.fileName">{{ detail.document.fileName }}</span>
          <div class="preview-pane__viewer-meta">
            <span>{{ activePage?.pageNo ?? 1 }} / {{ visiblePageCount }}</span>
            <span>{{ zoomPercent }}</span>
            <span v-if="currentPageRotation !== 0">{{ currentPageRotation }}°</span>
            <span>{{ selectedRange?.label || (activeBlock ? formatBlockTypeLabel(activeBlock.type) : '未选中') }}</span>
          </div>
        </div>
        <div ref="scrollRef" class="preview-pane__scroller" @scroll="handleScroll">
          <div ref="viewerRef" class="preview-pane__viewport">
            <div v-if="renderError" class="preview-pane__state preview-pane__state--error">
              {{ renderError }}
            </div>
            <div v-else-if="previewKind === 'unsupported'" class="preview-pane__state">
              当前文件类型暂不支持原文预览，请在中间列查看识别结果。
            </div>
            <div v-else-if="previewKind === 'image' && activePage" class="preview-pane__stack">
              <div class="preview-pane__page-shell">
                <div class="preview-pane__page-label">
                  <span>{{ activePage.pageNo }} / {{ visiblePageCount }}</span>
                  <span>{{ activeBlock ? formatBlockTypeLabel(activeBlock.type) : '未选中' }}</span>
                </div>
                <div class="preview-pane__stage is-current" :style="imageStageStyle">
                  <img
                    :src="previewFileUrl"
                    :alt="detail.document.fileName"
                    class="preview-pane__image"
                    @load="handleImageLoad"
                    @error="handleImageError"
                  />
                  <div class="preview-pane__overlay">
                    <template v-if="hasRangeOverlay(activePage.pageIndex)">
                      <button
                        v-for="range in activePageRanges"
                        :key="range.id"
                        :ref="(element) => setBboxRef(activePage.pageIndex, `range:${range.id}`, element as HTMLButtonElement | null)"
                        type="button"
                        class="preview-pane__bbox preview-pane__range-bbox"
                        :class="{ 'is-active': range.id === selectedRangeId }"
                        :style="getRangeStyle(range, activePage.pageSize)"
                        :title="`${formatRangeKindLabel(range.kind)} · ${range.label}`"
                        @click="emit('selectRange', range.id, activePage.pageIndex)"
                      >
                        <span>{{ formatRangeKindLabel(range.kind) }}</span>
                      </button>
                    </template>
                    <template v-else>
                      <button
                        v-for="block in activePage.blocks"
                        :key="block.id"
                        :ref="(element) => setBboxRef(activePage.pageIndex, block.id, element as HTMLButtonElement | null)"
                        type="button"
                        class="preview-pane__bbox"
                        :class="{ 'is-active': block.id === selectedBlockId }"
                        :style="getBlockStyle(block, activePage.pageSize)"
                        :title="`${formatBlockTypeLabel(block.type)} · ${block.title}`"
                        @click="emit('selectBlock', block.id, activePage.pageIndex)"
                      >
                        <span>{{ formatBlockTypeLabel(block.type) }}</span>
                      </button>
                    </template>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="preview-pane__stack">
              <div
                v-for="page in previewPages"
                :key="page.pageIndex"
                :ref="(element) => setStageRef(page.pageIndex, element as HTMLDivElement | null)"
                class="preview-pane__page-shell"
              >
                <div class="preview-pane__page-label">
                  <span>{{ page.pageNo }} / {{ visiblePageCount }}</span>
                  <span v-if="getPageRotation(page.pageIndex) !== 0">{{ getPageRotation(page.pageIndex) }}°</span>
                </div>
                <div class="preview-pane__stage" :class="{ 'is-current': page.pageIndex === currentPageIndex }">
                  <canvas
                    :ref="(element) => setCanvasRef(page.pageIndex, element as HTMLCanvasElement | null)"
                    class="preview-pane__canvas"
                  />
                  <div class="preview-pane__overlay">
                    <template v-if="hasRangeOverlay(page.pageIndex)">
                      <button
                        v-for="range in getPageRanges(page.pageIndex)"
                        :key="range.id"
                        :ref="(element) => setBboxRef(page.pageIndex, `range:${range.id}`, element as HTMLButtonElement | null)"
                        type="button"
                        class="preview-pane__bbox preview-pane__range-bbox"
                        :class="{ 'is-active': range.id === selectedRangeId }"
                        :style="getRangeStyle(range, page.pageSize, getPageRotation(page.pageIndex))"
                        :title="`${formatRangeKindLabel(range.kind)} · ${range.label}`"
                        @click="emit('selectRange', range.id, page.pageIndex)"
                      >
                        <span>{{ formatRangeKindLabel(range.kind) }}</span>
                      </button>
                    </template>
                    <template v-else>
                      <button
                        v-for="block in page.blocks"
                        :key="block.id"
                        :ref="(element) => setBboxRef(page.pageIndex, block.id, element as HTMLButtonElement | null)"
                        type="button"
                        class="preview-pane__bbox"
                        :class="{ 'is-active': block.id === selectedBlockId }"
                        :style="getBlockStyle(block, page.pageSize, getPageRotation(page.pageIndex))"
                        :title="`${formatBlockTypeLabel(block.type)} · ${block.title}`"
                        @click="emit('selectBlock', block.id, page.pageIndex)"
                      >
                        <span>{{ formatBlockTypeLabel(block.type) }}</span>
                      </button>
                    </template>
                  </div>
                  <div
                    v-if="!pageRenderDone[page.pageIndex]"
                    class="preview-pane__loading-mask"
                  >
                    <a-spin :loading="true" tip="正在渲染页面..." />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </PanelCard>
  </div>
</template>

<style scoped>
.preview-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: var(--workbench-column-height, 860px);
  overflow: hidden;
}

.preview-pane :deep(.panel-card) {
  height: 100%;
  min-width: 0;
  overflow: hidden;
}

.preview-pane :deep(.panel-card__header) {
  padding: 8px 10px;
  border-bottom: 1px solid #d8dee8;
  background: #f8fafc;
}

.preview-pane :deep(.panel-card__title) {
  font-size: 12px;
  font-weight: 600;
  color: #111827;
}

.preview-pane :deep(.panel-card__body) {
  display: flex;
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.preview-pane__viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #d8dee8;
  border-radius: 0;
  background: #edf0f3;
}

.preview-pane__toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.preview-pane__toolbar :deep(.arco-btn) {
  min-width: 28px;
  height: 24px;
  padding: 0 6px;
  border-radius: 0;
  color: #475569;
}

.preview-pane__toolbar-separator {
  width: 1px;
  height: 14px;
  background: #d8dee8;
}

.preview-pane__pager {
  min-width: 54px;
  text-align: center;
  font-size: 12px;
  color: #4b5563;
}

.preview-pane__viewer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid #d8dee8;
  background: #fff;
  color: #111827;
  font-size: 12px;
}

.preview-pane__file-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-pane__viewer-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #6b7280;
  min-width: 0;
  flex-shrink: 0;
}

.preview-pane__scroller {
  flex: 1;
  overflow: auto;
  min-width: 0;
}

.preview-pane__viewport {
  position: relative;
  width: 100%;
  min-width: 100%;
  min-height: 100%;
  padding: 12px;
  box-sizing: border-box;
}

.preview-pane__stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
  align-items: center;
  width: 100%;
  min-width: 0;
}

.preview-pane__page-shell {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  width: fit-content;
  min-width: min(100%, 320px);
  max-width: none;
}

.preview-pane__page-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  max-width: 1000px;
  color: #6b7280;
  font-size: 12px;
}

.preview-pane__stage {
  position: relative;
  display: inline-flex;
  line-height: 0;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.08);
}

.preview-pane__stage.is-current {
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.12),
    0 8px 24px rgba(15, 23, 42, 0.04);
}

.preview-pane__canvas {
  display: block;
  max-width: none;
  background: #fff;
}

.preview-pane__image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #fff;
}

.preview-pane__overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.preview-pane__bbox {
  position: absolute;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  padding: 0;
  border: 2px solid transparent;
  background: transparent;
  color: transparent;
  cursor: pointer;
  pointer-events: auto;
  transition:
    border-color 0.14s ease,
    background 0.14s ease,
    box-shadow 0.14s ease;
}

.preview-pane__bbox span {
  display: inline-flex;
  padding: 1px 4px;
  background: transparent;
  color: transparent;
  font-size: 10px;
  line-height: 1.2;
  opacity: 0;
  transition:
    opacity 0.14s ease,
    background 0.14s ease,
    color 0.14s ease;
}

.preview-pane__bbox:hover,
.preview-pane__bbox:focus-visible {
  border-color: rgba(37, 99, 235, 0.45);
  background: rgba(37, 99, 235, 0.05);
  color: #1d4ed8;
  outline: none;
}

.preview-pane__bbox:hover span,
.preview-pane__bbox:focus-visible span {
  background: rgba(37, 99, 235, 0.86);
  color: #fff;
  opacity: 1;
}

.preview-pane__bbox.is-active {
  border-color: rgba(37, 99, 235, 0.95);
  background: rgba(37, 99, 235, 0.12);
  box-shadow:
    inset 0 0 0 1px rgba(37, 99, 235, 0.36),
    0 0 0 3px rgba(37, 99, 235, 0.14);
  color: #1d4ed8;
}

.preview-pane__bbox.is-active span {
  background: rgba(37, 99, 235, 0.96);
  color: #fff;
  opacity: 1;
}

.preview-pane__range-bbox {
  border-color: transparent;
  background: transparent;
  color: transparent;
}

.preview-pane__range-bbox span {
  background: transparent;
  color: transparent;
  opacity: 0;
}

.preview-pane__range-bbox:hover,
.preview-pane__range-bbox:focus-visible {
  border-color: rgba(37, 99, 235, 0.48);
  background: rgba(37, 99, 235, 0.05);
}

.preview-pane__range-bbox:hover span,
.preview-pane__range-bbox:focus-visible span {
  background: rgba(37, 99, 235, 0.86);
  color: #fff;
  opacity: 1;
}

.preview-pane__range-bbox.is-active {
  border-color: rgba(37, 99, 235, 0.96);
  background: rgba(37, 99, 235, 0.14);
  box-shadow:
    inset 0 0 0 1px rgba(37, 99, 235, 0.42),
    0 0 0 3px rgba(37, 99, 235, 0.16);
}

.preview-pane__range-bbox.is-active span {
  background: rgba(37, 99, 235, 0.96);
  color: #fff;
  opacity: 1;
}

.preview-pane__state {
  display: grid;
  place-items: center;
  width: 100%;
  min-height: 760px;
  padding: 24px;
  color: #4b5563;
  text-align: center;
}

.preview-pane__state--error {
  color: #b42318;
}

.preview-pane__loading-mask {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.48);
}

@media (max-width: 960px) {
  .preview-pane {
    height: 720px;
  }

  .preview-pane__viewer,
  .preview-pane__scroller,
  .preview-pane__state {
    min-height: 620px;
  }

  .preview-pane__viewer-header {
    flex-direction: column;
    align-items: flex-start;
  }

}
</style>
