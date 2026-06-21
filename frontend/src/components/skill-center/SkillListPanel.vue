<script setup lang="ts">
import { computed } from 'vue'
import type { SkillKind, SkillStatus } from '../../types/workbench'
import type { SkillItem, SkillOption } from './types'
import { formatExecutorLabel } from './skillCenterModel'

const props = defineProps<{
  activeKind: SkillKind
  items: SkillItem[]
  total: number
  keyword: string
  customerFilter: string
  statusFilter: string
  customerOptions: SkillOption[]
  page: number
  pageSize: number
  pageCount: number
}>()

const emit = defineEmits<{
  'update:keyword': [value: string]
  'update:customerFilter': [value: string]
  'update:statusFilter': [value: string]
  'update:page': [value: number]
  open: [item: SkillItem]
  create: []
}>()

const title = computed(() => (props.activeKind === 'extraction' ? '数据解析 Skill' : '业务处理 Skill'))
const subtitle = computed(() =>
  props.activeKind === 'extraction'
    ? '用于把识别结果转换成可处理的提取结果。'
    : '用于对提取结果做转换、校验、导出和对接。',
)

function updateKeyword(event: Event) {
  emit('update:keyword', (event.target as HTMLInputElement).value)
}

function updateCustomer(event: Event) {
  emit('update:customerFilter', (event.target as HTMLSelectElement).value)
}

function updateStatus(event: Event) {
  emit('update:statusFilter', (event.target as HTMLSelectElement).value)
}

function goPage(page: number) {
  emit('update:page', Math.max(1, Math.min(page, props.pageCount)))
}

function customerLabel(customerId?: string | null) {
  if (!customerId) return '平台'
  return props.customerOptions.find((item) => item.value === customerId)?.label || customerId
}

function statusLabel(status?: SkillStatus | string) {
  const labels: Record<string, string> = {
    draft: '草稿',
    active: '可用',
    disabled: '停用',
    deprecated: '旧版',
  }
  return labels[status || 'active'] || status || '可用'
}

function statusClass(status?: SkillStatus | string) {
  return `is-${status || 'active'}`
}

function latestTestLabel(status?: string | null) {
  if (!status) return '未测试'
  return status === 'completed' ? '最近通过' : status === 'failed' ? '最近失败' : status
}

function latestTestClass(status?: string | null) {
  if (!status) return 'is-unknown'
  return status === 'completed' ? 'is-passed' : status === 'failed' ? 'is-failed' : 'is-unknown'
}
</script>

<template>
  <section class="skill-center__list-page">
    <div class="skill-center__list-head">
      <div>
        <strong>{{ title }}</strong>
        <span>{{ subtitle }} 共 {{ total }} 个。</span>
      </div>
      <button type="button" class="skill-center__primary-action" @click="$emit('create')">新建 Skill</button>
    </div>

    <div class="skill-center__list-filters">
      <label>
        <span>搜索</span>
        <input :value="keyword" placeholder="名称、ID、执行器、客户" @input="updateKeyword" />
      </label>
      <label>
        <span>客户</span>
        <select :value="customerFilter" @change="updateCustomer">
          <option value="all">全部</option>
          <option value="platform">平台</option>
          <option v-for="item in customerOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
      </label>
      <label>
        <span>状态</span>
        <select :value="statusFilter" @change="updateStatus">
          <option value="all">全部</option>
          <option value="active">可用</option>
          <option value="draft">草稿</option>
          <option value="disabled">停用</option>
          <option value="deprecated">旧版</option>
        </select>
      </label>
    </div>

    <div v-if="items.length" class="skill-center__list-grid">
      <button
        v-for="item in items"
        :key="`${item.kind}-${item.customerScope}-${item.customerId || 'platform'}-${item.id}-${item.version}`"
        type="button"
        class="skill-center__list-card"
        @click="$emit('open', item)"
      >
        <span class="skill-center__list-card-top">
          <span class="skill-center__list-card-scope">{{ customerLabel(item.customerId) }}</span>
          <span :class="['skill-center__status-pill', statusClass(item.status)]">
            {{ statusLabel(item.status) }}
          </span>
        </span>
        <strong>{{ item.name }}</strong>
        <span class="skill-center__list-card-id">
          <span>{{ item.id }}</span>
          <span class="skill-center__version-pill">v{{ item.version }}</span>
        </span>
        <span class="skill-center__list-card-meta">
          {{ formatExecutorLabel(item.executor) }}
        </span>
        <span v-if="item.tags?.length" class="skill-center__tag-row">
          <span v-for="tag in item.tags.slice(0, 3)" :key="tag">{{ tag }}</span>
        </span>
        <span class="skill-center__list-card-stats">
          <span :class="['skill-center__quality-pill', latestTestClass(item.latestTestStatus)]">
            {{ latestTestLabel(item.latestTestStatus) }}
          </span>
        </span>
        <span v-if="item.updatedAt" class="skill-center__list-card-time">更新 {{ item.updatedAt.slice(0, 10) }}</span>
      </button>
    </div>

    <div v-if="total" class="skill-center__pagination">
      <span>每页 {{ pageSize }} 个 · 第 {{ page }} / {{ pageCount }} 页</span>
      <div>
        <button type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button type="button" :disabled="page >= pageCount" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>

    <div v-else class="skill-center__empty skill-center__empty--stage">
      <strong>没有匹配的 Skill</strong>
      <span>调整筛选条件，或新建一个客户 Skill。</span>
    </div>
  </section>
</template>
