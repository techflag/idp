<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PanelCard from '../components/PanelCard.vue'
import TaskListTable from '../components/TaskListTable.vue'
import { loadMyTasks } from '../services/workbenchApi'
import { useAuthStore } from '../stores/auth'
import { useWorkbenchStore } from '../stores/workbench'
import type { TaskSummary } from '../types/workbench'
import { formatDisplayDateTime } from '../utils/dateTime'

const store = useWorkbenchStore()
const auth = useAuthStore()
const router = useRouter()
const uploadInputRef = ref<HTMLInputElement | null>(null)
const loadError = ref('')
const tasks = ref<TaskSummary[]>([])
const tasksLoading = ref(false)
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)

onMounted(async () => {
  store.setRole('customer')
  try {
    await auth.bootstrap()
    await refreshTasks()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '任务数据加载失败。'
  }
})

const userTasks = computed(() => tasks.value)
const currentUserName = computed(() => auth.currentUser?.displayName || auth.currentUser?.username || '当前账号')
const currentCustomerId = computed(() => auth.currentUser?.customerIds[0] || userTasks.value[0]?.customerId || '--')
const runningCount = computed(() => userTasks.value.filter((task) => task.status === 'running').length)
const completedCount = computed(() => userTasks.value.filter((task) => task.status === 'completed').length)
const pendingCount = computed(() => userTasks.value.filter((task) => task.status === 'pending').length)
const failedCount = computed(() => userTasks.value.filter((task) => task.status === 'failed').length)
const latestUpdatedAt = computed(() => formatDisplayDateTime(userTasks.value[0]?.updatedAt))
const hasTasks = computed(() => total.value > 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

async function refreshTasks(page = currentPage.value, size = pageSize.value) {
  if (!auth.currentUser?.username) {
    throw new Error('当前登录信息不存在，请重新登录后刷新。')
  }
  tasksLoading.value = true
  loadError.value = ''
  try {
    const response = await loadMyTasks(page, size)
    tasks.value = response.items
    total.value = response.total
    currentPage.value = response.page
    pageSize.value = response.pageSize
  } finally {
    tasksLoading.value = false
  }
}

async function handlePageChange(page: number) {
  await refreshTasks(page, pageSize.value)
}

async function handlePageSizeChange(size: number) {
  await refreshTasks(1, size)
}

function openUploadPicker() {
  uploadInputRef.value?.click()
}

async function handleUploadChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  const customerId = auth.currentUser?.customerIds[0] ?? userTasks.value[0]?.customerId
  if (!customerId) {
    Message.warning('当前没有可用客户空间，无法上传识别。')
    input.value = ''
    return
  }

  try {
    const result = await store.uploadAndParseDocument(customerId, file)
    await refreshTasks()
    await router.push({ name: 'task-detail', params: { taskId: result.response.createdTask.id } })
    if (result.parseStatus?.state === 'completed') {
      Message.success('上传并识别完成，已进入新任务。')
    } else {
      Message.success('已上传并开始识别，已进入新任务。')
    }
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '上传识别失败。')
  } finally {
    input.value = ''
  }
}
</script>

<template>
  <div class="user-page">
    <section class="user-page__toolbar">
      <div class="user-page__toolbar-title">
        <p class="user-page__toolbar-label">客户任务工作台</p>
        <h2>{{ currentUserName }}</h2>
        <p class="user-page__toolbar-description">以任务清单为中心处理上传识别、结果核验与失败排查，首屏直接进入工作列表。</p>
      </div>
      <div class="user-page__toolbar-metrics">
        <div class="user-page__toolbar-metric">
          <span>任务总数</span>
          <strong>{{ total }}</strong>
        </div>
        <div class="user-page__toolbar-metric">
          <span>处理中</span>
          <strong>{{ runningCount }}</strong>
        </div>
        <div class="user-page__toolbar-metric">
          <span>已完成</span>
          <strong>{{ completedCount }}</strong>
        </div>
        <div class="user-page__toolbar-metric">
          <span>待处理</span>
          <strong>{{ pendingCount + failedCount }}</strong>
        </div>
      </div>
      <div class="user-page__toolbar-actions">
        <div class="user-page__toolbar-meta">
          <span>客户空间 {{ currentCustomerId }}</span>
          <span>当前第 {{ currentPage }} / {{ totalPages }} 页</span>
          <span>最近更新 {{ latestUpdatedAt }}</span>
        </div>
        <div class="user-page__toolbar-action-row">
          <a-button type="primary" size="large" :loading="store.processing" @click="openUploadPicker">上传并识别</a-button>
        </div>
        <p class="user-page__upload-tip">支持 PDF、Word、图片，上传后自动开始识别并进入工作台。</p>
        <input
          ref="uploadInputRef"
          class="user-page__file-input"
          type="file"
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
          @change="handleUploadChange"
        />
      </div>
    </section>

    <PanelCard
      v-if="loadError"
      title="任务数据加载失败"
      :description="loadError"
    >
      <div class="user-page__state user-page__state--error">
        <a-empty description="后端任务列表暂不可用，请先恢复 8002 服务后再刷新。" />
      </div>
    </PanelCard>

    <PanelCard
      v-else-if="!hasTasks && !tasksLoading"
      title="还没有识别任务"
      description="先上传一份客户文档，系统会自动创建首个识别任务。"
    >
      <div class="user-page__state">
        <a-empty description="当前账号下还没有任务，建议先上传文件开始识别。" />
        <a-button type="primary" size="large" :loading="store.processing" @click="openUploadPicker">立即上传第一份文档</a-button>
      </div>
    </PanelCard>

    <TaskListTable
      v-else
      title="客户识别任务"
      description="按任务、文档、状态和更新时间查看当前账号的工作清单，点击即可进入任务工作台。"
      :tasks="userTasks"
      :total="total"
      :current="currentPage"
      :page-size="pageSize"
      :loading="tasksLoading"
      @page-change="handlePageChange"
      @page-size-change="handlePageSizeChange"
    />
  </div>
</template>

<style scoped>
.user-page {
  display: grid;
  gap: 12px;
}

.user-page__toolbar {
  display: grid;
  grid-template-columns: minmax(260px, 1.1fr) minmax(320px, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid #d8e1ec;
  background: #ffffff;
}

.user-page__toolbar-title {
  display: grid;
  gap: 4px;
}

.user-page__toolbar-label {
  margin: 0;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.user-page__toolbar-title h2 {
  margin: 0;
  color: #0f172a;
  font-size: 24px;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.user-page__toolbar-description {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
}

.user-page__toolbar-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  border-left: 1px solid #e2e8f0;
  border-right: 1px solid #e2e8f0;
}

.user-page__toolbar-metric {
  display: grid;
  gap: 3px;
  padding: 0 14px;
  min-height: 48px;
  align-content: center;
  border-right: 1px solid #e2e8f0;
}

.user-page__toolbar-metric:last-child {
  border-right: 0;
}

.user-page__toolbar-metric span {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.user-page__toolbar-metric strong {
  color: #0f172a;
  font-size: 18px;
  line-height: 1.1;
}

.user-page__toolbar-actions {
  display: grid;
  justify-items: end;
  gap: 6px;
}

.user-page__toolbar-meta {
  display: flex;
  gap: 12px;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.user-page__toolbar-action-row {
  display: flex;
  align-items: center;
}

.user-page__toolbar-actions :deep(.arco-btn) {
  min-width: 148px;
  height: 38px;
  font-weight: 700;
}

.user-page__upload-tip {
  margin: 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.user-page__state {
  display: grid;
  justify-items: center;
  gap: 16px;
  padding: 18px 0 8px;
}

.user-page__state--error {
  justify-items: stretch;
}

.user-page__state :deep(.arco-btn) {
  min-width: 220px;
  height: 46px;
  font-weight: 700;
}

@media (max-width: 960px) {
  .user-page__toolbar {
    grid-template-columns: 1fr;
    padding: 16px;
  }

  .user-page__toolbar-title h2 {
    font-size: 20px;
  }

  .user-page__toolbar-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    border-right: 0;
    border-left: 0;
    border-top: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
    padding: 8px 0;
  }

  .user-page__toolbar-metric {
    padding: 8px 0;
    border-right: 0;
  }

  .user-page__toolbar-actions {
    justify-items: stretch;
  }

  .user-page__toolbar-meta {
    flex-wrap: wrap;
    white-space: normal;
  }
}
</style>
