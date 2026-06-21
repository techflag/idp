<script setup lang="ts">
import ParseResultPanel from './ParseResultPanel.vue'
import type {
  OperationTarget,
  PageResultDetail,
  ResultStatus,
  WorkbenchDocumentTree,
  WorkbenchPage,
} from '../types/workbench'
import type { DocumentTreeSource } from '../types/applicationWorkshop'

type ParsePanelTabKey = 'recognition' | 'tree' | 'extract'

defineProps<{
  title: string
  subtitle?: string
  page: WorkbenchPage | null
  documentTree?: WorkbenchDocumentTree | null
  result: PageResultDetail | null
  resultStatus?: ResultStatus | null
  activeTab?: ParsePanelTabKey
  operationTargets?: OperationTarget[]
  selectedTargetId?: string
  selectedTreeNodeId?: string
}>()

const emit = defineEmits<{
  'update:activeTab': [value: ParsePanelTabKey]
  selectTarget: [target: OperationTarget]
  selectTreeNode: [node: DocumentTreeSource]
}>()
</script>

<template>
  <section class="document-data-pane">
    <header class="document-data-pane__head">
      <div>
        <h3>{{ title }}</h3>
        <span v-if="subtitle">{{ subtitle }}</span>
      </div>
      <div class="document-data-pane__actions">
        <slot name="actions" />
      </div>
    </header>

    <ParseResultPanel
      :active-tab="activeTab"
      :page="page"
      :document-tree="documentTree"
      :result="result"
      :result-status="resultStatus"
      :operation-targets="operationTargets"
      :selected-target-id="selectedTargetId"
      :selected-tree-node-id="selectedTreeNodeId"
      @update:active-tab="emit('update:activeTab', $event)"
      @select-target="emit('selectTarget', $event)"
      @select-tree-node="emit('selectTreeNode', $event)"
    />
  </section>
</template>

<style scoped>
.document-data-pane {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}

.document-data-pane__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 46px;
  padding: 9px 12px;
  border-bottom: 1px solid #d7dee8;
  background: #fff;
}

.document-data-pane__head > div:first-child {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.document-data-pane__head h3 {
  margin: 0;
  color: #0f172a;
  font-size: 15px;
  font-weight: 850;
  line-height: 1.3;
}

.document-data-pane__head span {
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-data-pane__actions {
  display: inline-flex;
  flex-shrink: 0;
  gap: 6px;
}

.document-data-pane :deep(.parse-result-panel) {
  min-height: 0;
  overflow: auto;
}
</style>
