<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import PanelCard from './PanelCard.vue'
import type { TaskSummary } from '../types/workbench'
import { formatDisplayDateTime } from '../utils/dateTime'
import { buildTablePagination } from '../utils/tablePagination'

const props = defineProps<{
  title: string
  description: string
  tasks: TaskSummary[]
  total: number
  current: number
  pageSize: number
  loading?: boolean
}>()

const emit = defineEmits<{
  pageChange: [page: number]
  pageSizeChange: [pageSize: number]
}>()

const router = useRouter()

const columns = computed(() => [
  { title: '任务', slotName: 'task', width: 300 },
  { title: '客户', dataIndex: 'customerName' },
  { title: '文档', slotName: 'document', width: 260 },
  { title: '状态', slotName: 'status' },
  { title: '更新时间', slotName: 'updatedAt', width: 180 },
  { title: '操作', slotName: 'actions', width: 140 },
])

const pagination = computed(() =>
  buildTablePagination({
    total: props.total,
    current: props.current,
    pageSize: props.pageSize,
  }),
)

function openTask(taskId: string) {
  router.push({ name: 'task-detail', params: { taskId } })
}

function getTagColor(status: TaskSummary['status']) {
  if (status === 'completed') {
    return 'green'
  }

  if (status === 'running') {
    return 'arcoblue'
  }

  if (status === 'failed') {
    return 'red'
  }

  if (status === 'needs_review') {
    return 'orange'
  }

  return 'gold'
}

function getStatusLabel(status: TaskSummary['status']) {
  if (status === 'completed') {
    return '已完成'
  }

  if (status === 'running') {
    return '运行中'
  }

  if (status === 'failed') {
    return '失败'
  }

  if (status === 'needs_review') {
    return '需复核'
  }

  return '待开始'
}

</script>

<template>
  <PanelCard :title="title" :description="description">
    <template #extra>
      <slot name="extra" />
    </template>
    <div class="task-list-table">
      <a-table
        :columns="columns"
        :data="props.tasks"
        row-key="id"
        :pagination="pagination"
        :loading="props.loading"
        @page-change="emit('pageChange', $event)"
        @page-size-change="emit('pageSizeChange', $event)"
      >
        <template #task="{ record }">
          <div class="task-list-table__task-cell">
            <strong>{{ record.taskName }}</strong>
            
          </div>
        </template>
        <template #document="{ record }">
          <div class="task-list-table__doc-cell">
            <strong>{{ record.documentName }}</strong>
            <span>{{ record.pageCount }} 页 · {{ record.promptRunCount }} 次识别</span>
          </div>
        </template>
        <template #status="{ record }">
          <a-tag :color="getTagColor(record.status)">{{ getStatusLabel(record.status) }}</a-tag>
        </template>
        <template #updatedAt="{ record }">
          <div class="task-list-table__time-cell">
            <strong>{{ formatDisplayDateTime(record.updatedAt) }}</strong>
            <span>上传于 {{ formatDisplayDateTime(record.uploadTime) }}</span>
          </div>
        </template>
        <template #actions="{ record }">
          <a-button type="text" @click="openTask(record.id)">查看任务</a-button>
        </template>
      </a-table>
    </div>
  </PanelCard>
</template>

<style scoped>
.task-list-table__task-cell,
.task-list-table__doc-cell,
.task-list-table__time-cell {
  display: grid;
  gap: 4px;
}

.task-list-table__task-cell strong,
.task-list-table__doc-cell strong,
.task-list-table__time-cell strong {
  color: #0f172a;
  font-size: 13px;
  line-height: 1.35;
  font-weight: 700;
}

.task-list-table__task-cell p,
.task-list-table__doc-cell span,
.task-list-table__time-cell span {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.task-list-table :deep(.arco-table) {
  border: 1px solid #d8e1ec;
  overflow: hidden;
  background: #ffffff;
}

.task-list-table :deep(.arco-table-th) {
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border-bottom: 1px solid #e2e8f0;
}

.task-list-table :deep(.arco-table-td) {
  color: #111827;
  border-bottom: 1px solid #eef2f7;
  padding-top: 12px;
  padding-bottom: 12px;
}

.task-list-table :deep(.arco-table-tr:hover .arco-table-td) {
  background: #f8fbff;
}

.task-list-table :deep(.arco-table-pagination) {
  padding: 14px 16px 4px;
}

.task-list-table :deep(.arco-btn-text) {
  padding: 0;
  height: auto;
  color: #1d4ed8;
  font-weight: 600;
  background: transparent;
}

.task-list-table :deep(.arco-tag) {
  padding: 2px 10px;
  font-weight: 700;
}
</style>
