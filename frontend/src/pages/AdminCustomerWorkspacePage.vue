<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import PanelCard from '../components/PanelCard.vue'
import { loadCustomerDocuments, loadCustomerWorkspace } from '../services/workbenchApi'
import { useWorkbenchStore } from '../stores/workbench'
import type { CustomerWorkspaceResponse, DocumentSummary } from '../types/workbench'
import { formatDisplayDateTime } from '../utils/dateTime'
import { buildTablePagination } from '../utils/tablePagination'

const route = useRoute()
const router = useRouter()
const store = useWorkbenchStore()
const uploadInputRef = ref<HTMLInputElement | null>(null)

const customerId = computed(() => String(route.params.customerId || ''))
const workspaceLoading = ref(false)
const documentsLoading = ref(false)
const workspaceError = ref('')
const workspace = ref<CustomerWorkspaceResponse | null>(null)
const documents = ref<DocumentSummary[]>([])
const currentPage = ref(1)
const pageSize = ref(10)
const totalDocuments = ref(0)

const customer = computed(() => workspace.value?.customer ?? null)
const customerTasks = computed(() => workspace.value?.tasks ?? [])
const customerDocuments = computed(() => documents.value)
const runningCount = computed(() => customerTasks.value.filter((task) => task.status === 'running').length)
const failedCount = computed(() => customerTasks.value.filter((task) => task.status === 'failed').length)
const documentTablePagination = computed(() =>
  buildTablePagination({
    total: totalDocuments.value,
    current: currentPage.value,
    pageSize: pageSize.value,
  }),
)

const documentColumns = [
  { title: '文档名称', dataIndex: 'fileName' },
  { title: '类型', dataIndex: 'fileType', width: 110 },
  { title: '页数', dataIndex: 'pageCount', width: 90 },
  { title: '解析状态', slotName: 'parseStatus', width: 120 },
  { title: '上传人', dataIndex: 'uploadedByName', width: 120 },
  { title: '更新时间', slotName: 'updatedAt', width: 160 },
  { title: '操作', slotName: 'actions', width: 120 },
]

onMounted(async () => {
  store.setRole('admin')
  try {
    await refreshWorkspace()
  } catch (error) {
    workspaceError.value = error instanceof Error ? error.message : '客户空间加载失败。'
  }
})

watch(customerId, async () => {
  if (!customerId.value) {
    workspace.value = null
    documents.value = []
    workspaceError.value = ''
    return
  }
  currentPage.value = 1
  await refreshWorkspace()
})

async function refreshWorkspace() {
  if (!customerId.value) {
    workspace.value = null
    documents.value = []
    return
  }

  workspaceLoading.value = true
  workspaceError.value = ''
  try {
    workspace.value = await loadCustomerWorkspace(customerId.value)
    await refreshDocuments()
  } catch (error) {
    workspace.value = null
    documents.value = []
    workspaceError.value = error instanceof Error ? error.message : '客户空间加载失败。'
  } finally {
    workspaceLoading.value = false
  }
}

async function refreshDocuments(page = currentPage.value, size = pageSize.value) {
  if (!customerId.value) {
    documents.value = []
    totalDocuments.value = 0
    return
  }

  documentsLoading.value = true
  try {
    const response = await loadCustomerDocuments(customerId.value, page, size)
    documents.value = response.items
    totalDocuments.value = response.total
    currentPage.value = response.page
    pageSize.value = response.pageSize
  } finally {
    documentsLoading.value = false
  }
}

async function handlePageChange(page: number) {
  await refreshDocuments(page, pageSize.value)
}

async function handlePageSizeChange(size: number) {
  await refreshDocuments(1, size)
}

function goBackToAdminOverview() {
  router.push({ name: 'admin' })
}

function goBackToCustomers() {
  router.push({ name: 'admin-customers' })
}

function openUploadPicker() {
  uploadInputRef.value?.click()
}

async function handleUploadChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]

  if (!file || !customerId.value) {
    input.value = ''
    return
  }

  try {
    const result = await store.uploadAndParseDocument(customerId.value, file)
    Message.success(result.parseStatus?.state === 'completed' ? '新 POC 验证已上传并完成识别。' : '新 POC 验证已上传，识别已启动。')
    await refreshWorkspace()
    await router.push({ name: 'task-detail', params: { taskId: result.response.createdTask.id } })
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '上传新的 POC 验证失败。')
  } finally {
    input.value = ''
  }
}

function openDocumentTask(document: DocumentSummary) {
  if (!document.latestTaskId) {
    Message.warning('当前文档尚未生成可进入的任务。')
    return
  }
  router.push({ name: 'task-detail', params: { taskId: document.latestTaskId } })
}

function getParseTagColor(status: string) {
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

function getParseLabel(status: string) {
  if (status === 'completed') {
    return '已完成'
  }
  if (status === 'running') {
    return '解析中'
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
  <div class="admin-customer-page">
    <PanelCard
      v-if="workspaceError"
      title="客户空间加载失败"
      :description="workspaceError"
    >
      <a-empty description="后端客户数据暂不可用，请先恢复 8002 服务后再刷新。" />
    </PanelCard>

    <PanelCard
      v-else-if="!customer"
      title="客户不存在"
      description="当前客户空间未找到，可能已经失效或无访问权限。"
    >
      <div class="admin-customer-page__empty">
        <a-button type="primary" @click="goBackToAdminOverview">返回管理总览</a-button>
      </div>
    </PanelCard>

    <template v-else>
      <AdminPageHeader
        :breadcrumb="`管理后台 / 客户管理 / ${customer.name}`"
        :title="customer.name"
        :subtitle="`${customer.description}。当前页面只保留上传入口和文档主表。`"
        meta-label="项目编号"
        :meta-value="customer.projectCode"
        meta-min-width="220px"
      >
        <template #actions>
          <a-button type="primary" :loading="store.processing" @click="openUploadPicker">上传新 POC 验证</a-button>
          <a-button type="secondary" @click="goBackToCustomers">返回客户管理</a-button>
        </template>
      </AdminPageHeader>

      <section class="admin-customer-page__metric-grid">
        <article class="admin-customer-page__metric-card">
          <span>文档数</span>
          <strong>{{ customer.documentCount }}</strong>
          <p>当前客户下累计文档数</p>
        </article>
        <article class="admin-customer-page__metric-card">
          <span>任务数</span>
          <strong>{{ customer.taskCount }}</strong>
          <p>当前客户下累计任务数</p>
        </article>
        <article class="admin-customer-page__metric-card admin-customer-page__metric-card--accent">
          <span>处理中</span>
          <strong>{{ runningCount }}</strong>
          <p>当前仍在流转中的任务数量</p>
        </article>
        <article class="admin-customer-page__metric-card">
          <span>失败任务</span>
          <strong>{{ failedCount }}</strong>
          <p>需要继续跟进的异常任务</p>
        </article>
      </section>

      <PanelCard
        title="客户文档"
        :description="`负责人：${customer.owner}。从这里查看该客户下全部文档、解析状态与最近更新时间，并直接进入对应任务。`"
      >
        <a-table
          :columns="documentColumns"
          :data="customerDocuments"
          row-key="id"
          :pagination="documentTablePagination"
          :loading="workspaceLoading || documentsLoading"
          @page-change="handlePageChange"
          @page-size-change="handlePageSizeChange"
        >
          <template #parseStatus="{ record }">
            <a-tag :color="getParseTagColor(record.parseStatus)">{{ getParseLabel(record.parseStatus) }}</a-tag>
          </template>
          <template #updatedAt="{ record }">
            <span>{{ formatDisplayDateTime(record.updatedAt) }}</span>
          </template>
          <template #actions="{ record }">
            <a-button type="text" @click="openDocumentTask(record)">
              {{ record.latestTaskId ? '进入任务' : '暂无任务' }}
            </a-button>
          </template>
        </a-table>
        <input
          ref="uploadInputRef"
          class="admin-customer-page__file-input"
          type="file"
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
          @change="handleUploadChange"
        />
      </PanelCard>
    </template>
  </div>
</template>

<style scoped>
.admin-customer-page {
  display: grid;
  gap: 12px;
}

.admin-customer-page__metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.admin-customer-page__metric-card {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #ffffff;
}

.admin-customer-page__metric-card--accent {
  border-left: 2px solid #2563eb;
}

.admin-customer-page__metric-card span {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.admin-customer-page__metric-card strong {
  color: #111827;
  font-size: 22px;
  line-height: 1.15;
  letter-spacing: -0.02em;
}

.admin-customer-page__metric-card p {
  margin: 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.admin-customer-page__file-input {
  display: none;
}

.admin-customer-page__empty {
  display: flex;
  justify-content: flex-start;
}

.admin-customer-page :deep(.arco-table-th),
.admin-customer-page :deep(.arco-table-td) {
  white-space: nowrap;
}

@media (max-width: 960px) {
  .admin-customer-page__metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
