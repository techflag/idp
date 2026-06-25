<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import PanelCard from '../components/PanelCard.vue'
import { loadAdminOverview } from '../services/workbenchApi'
import { useWorkbenchStore } from '../stores/workbench'
import type { AdminOverviewResponse } from '../types/workbench'
import { formatDisplayDateTime } from '../utils/dateTime'

const router = useRouter()
const store = useWorkbenchStore()
const overview = ref<AdminOverviewResponse | null>(null)
const loadError = ref('')

onMounted(async () => {
  store.setRole('admin')
  try {
    overview.value = await loadAdminOverview()
  } catch {
    loadError.value = '管理总览加载失败。'
  }
})

const adminTasks = computed(() => overview.value?.tasks ?? [])
const totalDocuments = computed(() => overview.value?.totalDocuments ?? 0)
const totalRunningTasks = computed(() => adminTasks.value.filter((item) => item.status === 'running').length)
const latestUpdate = computed(() => formatDisplayDateTime(adminTasks.value[0]?.updatedAt))

const totalCustomers = computed(() => overview.value?.totalCustomers ?? 0)
const failedTasks = computed(() => adminTasks.value.filter((item) => item.status === 'failed').length)

const quickEntries = computed(() => [
  {
    id: 'customers',
    title: '客户管理',
    summary: '查看客户空间、负责人、文档规模，并直接上传新的 POC 验证。',
    value: `${totalCustomers.value} 个客户空间`,
    actionLabel: '进入客户管理',
    routeName: 'admin-customers',
  },
  {
    id: 'tasks',
    title: '识别任务',
    summary: '查看全部识别任务、状态与更新时间，直接进入具体工作台。',
    value: `${adminTasks.value.length} 个任务`,
    actionLabel: '进入识别任务',
    routeName: 'admin-tasks',
  },
  {
    id: 'extraction-skills',
    title: '数据解析',
    summary: '维护识别结果到提取结果的解析 Skill。',
    value: '解析 Skill',
    actionLabel: '进入数据解析',
    routeName: 'admin-extraction-skills',
  },
  {
    id: 'operation-skills',
    title: '业务处理',
    summary: '维护提取结果后的转换、检查、导出和对接 Skill。',
    value: '处理 Skill',
    actionLabel: '进入业务处理',
    routeName: 'admin-operation-skills',
  },
])

function openRoute(routeName: string) {
  router.push({ name: routeName })
}
</script>

<template>
  <div class="admin-page">
    <PanelCard
      v-if="loadError"
      title="任务数据加载失败"
      :description="loadError"
    >
      <a-empty description="后端任务总览暂不可用，请先恢复 8002 服务后再刷新。" />
    </PanelCard>

    <template v-else>
      <AdminPageHeader
        breadcrumb="管理后台 / 总览"
        title="运营总览"
        subtitle="这里只保留最上层概览和入口，不在总览页混放客户列表或任务列表。"
        meta-label="最近数据刷新"
        :meta-value="latestUpdate"
        meta-min-width="280px"
      >
        <template #actions>
          <a-button type="secondary" @click="openRoute('admin-customers')">客户管理</a-button>
          <a-button type="primary" @click="openRoute('admin-tasks')">识别任务</a-button>
        </template>
      </AdminPageHeader>

      <section class="admin-page__metric-grid">
        <article class="admin-page__metric-card">
          <span>客户</span>
          <strong>{{ totalCustomers }}</strong>
          <p>当前可管理客户空间总量</p>
        </article>
        <article class="admin-page__metric-card">
          <span>文档</span>
          <strong>{{ totalDocuments }}</strong>
          <p>当前纳入管理的文档总量</p>
        </article>
        <article class="admin-page__metric-card admin-page__metric-card--accent">
          <span>处理中</span>
          <strong>{{ totalRunningTasks }}</strong>
          <p>仍在流转中的识别任务数量</p>
        </article>
        <article class="admin-page__metric-card">
          <span>失败任务</span>
          <strong>{{ failedTasks }}</strong>
          <p>当前需要排查的异常任务数量</p>
        </article>
      </section>

      <PanelCard title="快捷入口" description="总览只做分流，从这里进入客户管理或识别任务。">
        <div class="admin-page__quick-list">
          <button
            v-for="entry in quickEntries"
            :key="entry.id"
            type="button"
            class="admin-page__quick-item"
            @click="openRoute(entry.routeName)"
          >
            <div>
              <span>{{ entry.title }}</span>
              <strong>{{ entry.value }}</strong>
              <p>{{ entry.summary }}</p>
            </div>
            <em>{{ entry.actionLabel }}</em>
          </button>
        </div>
      </PanelCard>
    </template>
  </div>
</template>

<style scoped>
.admin-page {
  display: grid;
  gap: 12px;
}

.admin-page__metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.admin-page__metric-card {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #ffffff;
}

.admin-page__metric-card--accent {
  border-left: 2px solid #2563eb;
}

.admin-page__metric-card span {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.admin-page__metric-card strong {
  color: #0f172a;
  font-size: 22px;
  line-height: 1.15;
  letter-spacing: -0.02em;
}

.admin-page__metric-card p {
  margin: 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.admin-page__quick-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.admin-page__quick-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
}

.admin-page__quick-item:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}

.admin-page__quick-item span {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.admin-page__quick-item strong {
  display: block;
  margin-top: 2px;
  color: #111827;
  font-size: 18px;
  letter-spacing: -0.02em;
}

.admin-page__quick-item p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.admin-page__quick-item em {
  color: #2563eb;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  white-space: nowrap;
}

@media (max-width: 960px) {
  .admin-page__metric-grid,
  .admin-page__quick-list {
    grid-template-columns: 1fr;
  }

  .admin-page__header-actions,
  .admin-page__quick-item {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
