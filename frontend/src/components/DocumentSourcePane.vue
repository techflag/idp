<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import SourcePreviewPane from './SourcePreviewPane.vue'
import type { WorkbenchTaskDetail } from '../types/workbench'

type SourcePaneContentRange = {
  id: string
  pageIndex: number
  pageNo: number
  label: string
  kind: string
  bbox: [number, number, number, number]
  blockIds: string[]
  confidence?: number
}

withDefaults(defineProps<{
  detail: WorkbenchTaskDetail
  currentPageIndex: number
  selectedBlockId: string
  overlayMode?: 'blocks' | 'ranges'
  contentRanges?: SourcePaneContentRange[]
  selectedRangeId?: string
}>(), {
  overlayMode: 'blocks',
  contentRanges: () => [],
  selectedRangeId: '',
})

const emit = defineEmits<{
  changePage: [pageIndex: number]
  selectBlock: [blockId: string, pageIndex?: number]
  selectRange: [rangeId: string, pageIndex?: number]
}>()
</script>

<template>
  <div class="document-source-pane">
    <SourcePreviewPane
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
  </div>
</template>

<style scoped>
.document-source-pane {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}

.document-source-pane :deep(.source-preview-pane) {
  height: 100%;
}

.document-source-pane :deep(.source-preview-pane__scroll) {
  height: calc(100% - 96px);
}
</style>
