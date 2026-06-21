<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useSlots, type StyleValue } from 'vue'
import type {
  OperationTarget,
  PageResultDetail,
  ResultStatus,
  WorkbenchDocumentTree,
  WorkbenchPage,
  WorkbenchTaskDetail,
} from '../types/workbench'
import type { DocumentTreeSource } from '../types/applicationWorkshop'
import DocumentDataPane from './DocumentDataPane.vue'
import DocumentSourcePane from './DocumentSourcePane.vue'

type ParsePanelTabKey = 'recognition' | 'tree' | 'extract'
type WorkspaceLayout = 'fixed' | 'resizable'
type WorkspaceContentRange = {
  id: string
  pageIndex: number
  pageNo: number
  label: string
  kind: string
  bbox: [number, number, number, number]
  blockIds: string[]
  confidence?: number
}

const RESIZER_WIDTH = 14

const props = withDefaults(defineProps<{
  layout?: WorkspaceLayout
  height?: string
  detail: WorkbenchTaskDetail
  currentPageIndex: number
  selectedBlockId: string
  overlayMode?: 'blocks' | 'ranges'
  contentRanges?: WorkspaceContentRange[]
  selectedRangeId?: string
  dataTitle: string
  dataSubtitle?: string
  page: WorkbenchPage | null
  documentTree?: WorkbenchDocumentTree | null
  result: PageResultDetail | null
  resultStatus?: ResultStatus | null
  activeTab?: ParsePanelTabKey
  operationTargets?: OperationTarget[]
  selectedTargetId?: string
  selectedTreeNodeId?: string
  initialColumnWidths?: [number, number, number]
  minColumnWidths?: [number, number, number]
}>(), {
  layout: 'fixed',
  height: '',
  overlayMode: 'blocks',
  contentRanges: () => [],
  selectedRangeId: '',
  dataSubtitle: '',
  documentTree: null,
  resultStatus: null,
  activeTab: undefined,
  operationTargets: () => [],
  selectedTargetId: '',
  selectedTreeNodeId: '',
  initialColumnWidths: () => [29, 43, 28],
  minColumnWidths: () => [22, 30, 20],
})

const emit = defineEmits<{
  changePage: [pageIndex: number]
  selectBlock: [blockId: string, pageIndex?: number]
  selectRange: [rangeId: string, pageIndex?: number]
  'update:activeTab': [value: ParsePanelTabKey]
  selectTarget: [target: OperationTarget]
  selectTreeNode: [node: DocumentTreeSource]
}>()

const slots = useSlots()
const rootRef = ref<HTMLElement | null>(null)
const columnWidths = ref<[number, number, number]>([...props.initialColumnWidths])
let activeResizeIndex: 0 | 1 | null = null
let resizeStartX = 0
let resizeStartWidths: [number, number, number] = [...props.initialColumnWidths]

const hasSide = computed(() => Boolean(slots.side))
const isResizable = computed(() => props.layout === 'resizable')
const rootStyle = computed<StyleValue>(() => ({
  '--document-review-height': props.height || undefined,
}))

function columnStyle(index: number): StyleValue {
  if (!isResizable.value) return {}
  const resizerCount = hasSide.value ? 2 : 1
  const widthTotal = hasSide.value ? 100 : columnWidths.value[0] + columnWidths.value[1]
  const ratio = columnWidths.value[index] / widthTotal
  const width = `calc((100% - ${RESIZER_WIDTH * resizerCount}px) * ${ratio})`
  return {
    flex: `0 0 ${width}`,
    width,
  }
}

function handleResizeMove(event: PointerEvent) {
  if (activeResizeIndex === null || !rootRef.value) return
  const containerWidth = rootRef.value.getBoundingClientRect().width
  if (containerWidth <= 0) return

  const deltaPercent = ((event.clientX - resizeStartX) / containerWidth) * 100
  const nextWidths = [...resizeStartWidths] as [number, number, number]
  const leftIndex = activeResizeIndex
  const rightIndex = activeResizeIndex + 1
  const pairTotal = resizeStartWidths[leftIndex] + resizeStartWidths[rightIndex]
  const nextLeft = Math.min(
    Math.max(resizeStartWidths[leftIndex] + deltaPercent, props.minColumnWidths[leftIndex]),
    pairTotal - props.minColumnWidths[rightIndex],
  )

  nextWidths[leftIndex] = Number(nextLeft.toFixed(2))
  nextWidths[rightIndex] = Number((pairTotal - nextLeft).toFixed(2))
  columnWidths.value = nextWidths
}

function stopResize() {
  if (activeResizeIndex === null) return
  activeResizeIndex = null
  window.removeEventListener('pointermove', handleResizeMove)
  window.removeEventListener('pointerup', stopResize)
  document.body.classList.remove('document-review-resizing')
}

function startResize(index: 0 | 1, event: PointerEvent) {
  if (!isResizable.value) return
  event.preventDefault()
  activeResizeIndex = index
  resizeStartX = event.clientX
  resizeStartWidths = [...columnWidths.value] as [number, number, number]
  window.addEventListener('pointermove', handleResizeMove)
  window.addEventListener('pointerup', stopResize)
  document.body.classList.add('document-review-resizing')
}

onBeforeUnmount(() => {
  stopResize()
})
</script>

<template>
  <section
    ref="rootRef"
    class="document-review-workspace"
    :class="[`document-review-workspace--${layout}`, { 'document-review-workspace--with-side': hasSide }]"
    :style="rootStyle"
  >
    <DocumentSourcePane
      class="document-review-workspace__pane document-review-workspace__pane--source"
      :style="columnStyle(0)"
      :detail="detail"
      :current-page-index="currentPageIndex"
      :selected-block-id="selectedBlockId"
      :overlay-mode="overlayMode"
      :content-ranges="contentRanges"
      :selected-range-id="selectedRangeId"
      @change-page="emit('changePage', $event)"
      @select-block="(...args) => emit('selectBlock', args[0], args[1])"
      @select-range="(...args) => emit('selectRange', args[0], args[1])"
    />

    <button
      v-if="isResizable"
      type="button"
      class="document-review-workspace__resizer"
      title="拖动调整原文和数据列宽度"
      aria-label="拖动调整原文和数据列宽度"
      @pointerdown="startResize(0, $event)"
    />

    <DocumentDataPane
      class="document-review-workspace__pane document-review-workspace__pane--data"
      :style="columnStyle(1)"
      :title="dataTitle"
      :subtitle="dataSubtitle"
      :page="page"
      :document-tree="documentTree"
      :result="result"
      :result-status="resultStatus"
      :active-tab="activeTab"
      :operation-targets="operationTargets"
      :selected-target-id="selectedTargetId"
      :selected-tree-node-id="selectedTreeNodeId"
      @update:active-tab="emit('update:activeTab', $event)"
      @select-target="emit('selectTarget', $event)"
      @select-tree-node="emit('selectTreeNode', $event)"
    >
      <template #actions>
        <slot name="data-actions" />
      </template>
    </DocumentDataPane>

    <template v-if="hasSide">
      <button
        v-if="isResizable"
        type="button"
        class="document-review-workspace__resizer"
        title="拖动调整数据和操作列宽度"
        aria-label="拖动调整数据和操作列宽度"
        @pointerdown="startResize(1, $event)"
      />

      <aside
        class="document-review-workspace__pane document-review-workspace__pane--side"
        :style="columnStyle(2)"
      >
        <slot name="side" />
      </aside>
    </template>
  </section>
</template>

<style scoped>
.document-review-workspace {
  min-width: 0;
  overflow: hidden;
}

.document-review-workspace--fixed {
  display: grid;
  grid-template-columns: minmax(320px, 32fr) minmax(480px, 42fr) minmax(360px, 26fr);
  gap: 8px;
  height: var(--document-review-height, calc(100vh - 106px));
  min-height: 0;
  padding: 0 8px 8px;
}

.document-review-workspace--fixed:not(.document-review-workspace--with-side) {
  grid-template-columns: minmax(320px, 42fr) minmax(480px, 58fr);
}

.document-review-workspace--resizable {
  display: flex;
  align-items: stretch;
  width: 100%;
  height: var(--document-review-height, var(--workbench-column-height, calc(100vh - 106px)));
  min-height: 0;
  padding: 8px;
  border: 1px solid #d7dde5;
  background: #f8fafc;
}

.document-review-workspace__pane {
  min-width: 0;
  min-height: 0;
  background: #fff;
}

.document-review-workspace--fixed .document-review-workspace__pane {
  border: 1px solid #d7dee8;
}

.document-review-workspace__pane--side {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.document-review-workspace--resizable .document-review-workspace__pane--side {
  height: 100%;
}

.document-review-workspace__resizer {
  position: relative;
  flex: 0 0 14px;
  min-width: 14px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
  transition: background-color 0.16s ease;
}

.document-review-workspace__resizer::before {
  content: '';
  position: absolute;
  top: 6px;
  bottom: 6px;
  left: 50%;
  width: 1px;
  background: #d8dee8;
  transform: translateX(-50%);
  transition: background-color 0.16s ease;
}

.document-review-workspace__resizer::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 4px;
  height: 28px;
  background:
    radial-gradient(circle, #94a3b8 1.1px, transparent 1.2px) center top / 4px 8px repeat-y;
  transform: translate(-50%, -50%);
  opacity: 0.38;
  transition:
    opacity 0.16s ease,
    background-color 0.16s ease;
}

.document-review-workspace__resizer:hover {
  background: rgba(148, 163, 184, 0.1);
}

.document-review-workspace__resizer:hover::before {
  background: #94a3b8;
}

.document-review-workspace__resizer:hover::after {
  opacity: 0.82;
}

.document-review-workspace__resizer:active {
  background: rgba(59, 130, 246, 0.1);
}

.document-review-workspace__resizer:active::before {
  background: #3b82f6;
}

.document-review-workspace__resizer:active::after {
  opacity: 1;
  background:
    radial-gradient(circle, #3b82f6 1.1px, transparent 1.2px) center top / 4px 8px repeat-y;
}

:global(body.document-review-resizing) {
  cursor: col-resize;
  user-select: none;
}

@media (max-width: 1120px) {
  .document-review-workspace--resizable {
    flex-direction: column;
    height: auto;
  }

  .document-review-workspace--resizable .document-review-workspace__pane {
    width: 100% !important;
    flex-basis: auto !important;
  }

  .document-review-workspace--resizable .document-review-workspace__pane--source,
  .document-review-workspace--resizable .document-review-workspace__pane--data,
  .document-review-workspace--resizable .document-review-workspace__pane--side {
    height: var(--workbench-column-height, 720px);
  }

  .document-review-workspace__resizer {
    display: none;
  }
}

@media (max-width: 1180px) {
  .document-review-workspace--fixed {
    grid-template-columns: minmax(0, 1fr);
    height: auto;
    overflow: visible;
  }
}
</style>
