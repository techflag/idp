<script setup lang="ts">
import type { SkillKind } from '../../types/workbench'
import type { SkillOption } from './types'

defineProps<{
  activeKind: SkillKind
  viewMode: 'list' | 'detail'
  customerId: string
  customerOptions: SkillOption[]
  showCustomerPicker?: boolean
  customerLabel?: string
  allowEmptyCustomer?: boolean
  emptyCustomerLabel?: string
  currentTitle?: string
  currentSubtitle?: string
  showCopy?: boolean
  showMove?: boolean
  canCopy?: boolean
  canMove?: boolean
}>()

const emit = defineEmits<{
  'update:customerId': [value: string]
  'customer-change': []
  'new-skill': []
  'back-list': []
  'copy-current': []
  'move-current': []
}>()

function handleCustomerChange(event: Event) {
  emit('update:customerId', (event.target as HTMLSelectElement).value)
  emit('customer-change')
}
</script>

<template>
  <section class="skill-center__topbar">
    <div class="skill-center__topbar-main">
      <nav class="skill-center__breadcrumbs" aria-label="页面导航">
        <span>管理后台</span>
        <span>/</span>
        <button type="button" @click="$emit('back-list')">
          {{ activeKind === 'extraction' ? '数据解析' : '业务处理' }}
        </button>
        <span>/</span>
        <strong>{{ viewMode === 'list' ? '列表页' : currentTitle || '详情页' }}</strong>
      </nav>
      <span v-if="viewMode === 'detail' && currentSubtitle" class="skill-center__breadcrumb-meta">
        {{ currentSubtitle }}
      </span>
    </div>
    <div class="skill-center__topbar-actions">
      <label v-if="showCustomerPicker" class="skill-center__customer">
        <span>{{ customerLabel || '客户' }}</span>
        <select :value="customerId" @change="handleCustomerChange">
          <option v-if="allowEmptyCustomer" value="">{{ emptyCustomerLabel || '全部客户' }}</option>
          <option v-for="item in customerOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
      </label>
      <button
        v-if="showCopy"
        type="button"
        class="skill-center__text-action"
        :disabled="!canCopy"
        @click="$emit('copy-current')"
      >
        复制到当前客户
      </button>
      <button
        v-if="showMove"
        type="button"
        class="skill-center__text-action"
        :disabled="!canMove"
        @click="$emit('move-current')"
      >
        修改归属
      </button>
      <button v-if="viewMode === 'list'" type="button" class="skill-center__text-action" @click="$emit('new-skill')">
        新建 Skill
      </button>
    </div>
  </section>
</template>
