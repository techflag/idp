<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import PanelCard from '../components/PanelCard.vue'
import TaskListTable from '../components/TaskListTable.vue'
import { loadAdminTasks, loadCustomers } from '../services/workbenchApi'
import { useWorkbenchStore } from '../stores/workbench'
import type { CustomerSummary, TaskSummary } from '../types/workbench'

const store = useWorkbenchStore()
const tasks = ref<TaskSummary[]>([])
const customers = ref<CustomerSummary[]>([])
const tasksLoading = ref(false)
const customersLoading = ref(false)
const loadError = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const selectedCustomerId = ref('')

onMounted(async () => {
  store.setRole('admin')
  try {
    await Promise.all([refreshCustomers(), refreshTasks()])
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '任务数据加载失败。'
  }
})

const adminTasks = computed(() => tasks.value)
const selectedCustomerName = computed(() => {
  if (!selectedCustomerId.value) {
    return '全部客户'
  }
  return customers.value.find((customer) => customer.id === selectedCustomerId.value)?.name || '当前客户'
})
const pendingCount = computed(() => adminTasks.value.filter((item) => item.status === 'pending').length)
const runningCount = computed(() => adminTasks.value.filter((item) => item.status === 'running').length)
const completedCount = computed(() => adminTasks.value.filter((item) => item.status === 'completed').length)
const failedCount = computed(() => adminTasks.value.filter((item) => item.status === 'failed').length)

async function refreshCustomers() {
  customersLoading.value = true
  try {
    const response = await loadCustomers(1, 100)
    customers.value = response.items
  } finally {
    customersLoading.value = false
  }
}

async function refreshTasks(page = currentPage.value, size = pageSize.value) {
  tasksLoading.value = true
  loadError.value = ''
  try {
    const response = await loadAdminTasks(page, size, selectedCustomerId.value || null)
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

async function handleCustomerChange(value: unknown) {
  selectedCustomerId.value = typeof value === 'string' ? value : ''
  await refreshTasks(1, pageSize.value)
}
</script>

<template>
  <div class="admin-recognition-page">
    <PanelCard
      v-if="loadError"
      title="任务数据加载失败"
      :description="loadError"
    >
      <a-empty description="后端任务数据暂不可用，请先恢复 8002 服务后再刷新。" />
    </PanelCard>

    <template v-else>
      <AdminPageHeader
        breadcrumb="管理后台 / 识别任务"
        title="识别任务"
        subtitle="按客户筛选识别任务，查看任务状态、文档与更新时间。"
        meta-label="任务总数"
        :meta-value="total"
      />

      <section class="admin-recognition-page__metric-grid">
        <article class="admin-recognition-page__metric-card">
          <span>当前页待开始</span>
          <strong>{{ pendingCount }}</strong>
          <p>尚未进入识别流程的任务</p>
        </article>
        <article class="admin-recognition-page__metric-card admin-recognition-page__metric-card--accent">
          <span>当前页处理中</span>
          <strong>{{ runningCount }}</strong>
          <p>当前正在识别或流转中的任务</p>
        </article>
        <article class="admin-recognition-page__metric-card">
          <span>当前页已完成</span>
          <strong>{{ completedCount }}</strong>
          <p>已生成结果并可审阅的任务</p>
        </article>
        <article class="admin-recognition-page__metric-card">
          <span>当前页失败</span>
          <strong>{{ failedCount }}</strong>
          <p>需要排查或重跑的异常任务</p>
        </article>
      </section>

      <TaskListTable
        title="识别任务"
        :description="`当前范围：${selectedCustomerName}。可直接按任务、客户、文档、状态与更新时间进入工作台。`"
        :tasks="adminTasks"
        :total="total"
        :current="currentPage"
        :page-size="pageSize"
        :loading="tasksLoading"
        @page-change="handlePageChange"
        @page-size-change="handlePageSizeChange"
      >
        <template #extra>
          <div class="admin-recognition-page__filters">
            <label for="admin-recognition-customer">客户</label>
            <a-select
              id="admin-recognition-customer"
              :model-value="selectedCustomerId"
              class="admin-recognition-page__customer-select"
              :loading="customersLoading"
              placeholder="全部客户"
              @change="handleCustomerChange"
            >
              <a-option value="">全部客户</a-option>
              <a-option
                v-for="customer in customers"
                :key="customer.id"
                :value="customer.id"
              >
                {{ customer.name }}
              </a-option>
            </a-select>
          </div>
        </template>
      </TaskListTable>
    </template>
  </div>
</template>

<style scoped>
.admin-recognition-page {
  display: grid;
  gap: 12px;
}

.admin-recognition-page__metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.admin-recognition-page__metric-card {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #ffffff;
}

.admin-recognition-page__metric-card--accent {
  border-left: 2px solid #2563eb;
}

.admin-recognition-page__metric-card span {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.admin-recognition-page__metric-card strong {
  color: #111827;
  font-size: 22px;
  line-height: 1.15;
  letter-spacing: -0.02em;
}

.admin-recognition-page__metric-card p {
  margin: 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.admin-recognition-page__filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-recognition-page__filters label {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.admin-recognition-page__customer-select {
  width: 220px;
}

@media (max-width: 960px) {
  .admin-recognition-page__metric-grid {
    grid-template-columns: 1fr;
  }

  .admin-recognition-page__filters,
  .admin-recognition-page__customer-select {
    width: 100%;
  }
}
</style>
