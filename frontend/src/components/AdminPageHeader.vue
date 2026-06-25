<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    breadcrumb: string
    title: string
    subtitle: string
    metaLabel?: string
    metaValue?: string | number
    metaMinWidth?: string
  }>(),
  {
    metaLabel: '',
    metaValue: '',
    metaMinWidth: '180px',
  },
)

const breadcrumbParts = computed(() => {
  const parts = props.breadcrumb
    .split('/')
    .map((item) => item.trim())
    .filter(Boolean)
  const last = parts[parts.length - 1]
  if (props.title && props.title !== last) {
    return [...parts, props.title]
  }
  return parts
})
</script>

<template>
  <section class="admin-page-header">
    <div class="admin-page-header__main">
      <nav class="admin-page-header__breadcrumb" aria-label="页面导航">
        <template v-for="(item, index) in breadcrumbParts" :key="`${item}-${index}`">
          <span
            :class="[
              'admin-page-header__breadcrumb-item',
              { 'admin-page-header__breadcrumb-item--current': index === breadcrumbParts.length - 1 },
            ]"
          >
            {{ item }}
          </span>
          <span v-if="index < breadcrumbParts.length - 1" class="admin-page-header__breadcrumb-separator">/</span>
        </template>
      </nav>
      <p class="admin-page-header__subtitle">{{ subtitle }}</p>
    </div>

    <div class="admin-page-header__side">
      <div
        v-if="metaLabel || metaValue"
        class="admin-page-header__meta"
        :style="{ minWidth: metaMinWidth }"
      >
        <span>{{ metaLabel }}</span>
        <strong>{{ metaValue }}</strong>
      </div>
      <div v-if="$slots.actions" class="admin-page-header__actions">
        <slot name="actions" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.admin-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 44px;
  padding: 6px 2px 10px;
  border-bottom: 1px solid #d7dde5;
  background: transparent;
}

.admin-page-header__main {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.admin-page-header__breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 700;
}

.admin-page-header__breadcrumb-item {
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-page-header__breadcrumb-item--current {
  color: #334155;
  font-weight: 800;
}

.admin-page-header__breadcrumb-separator {
  color: #cbd5e1;
}

.admin-page-header__subtitle {
  max-width: 820px;
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-page-header__side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.admin-page-header__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid #d7dde5;
  background: #ffffff;
}

.admin-page-header__meta span {
  color: #64748b;
  font-size: 11px;
}

.admin-page-header__meta strong {
  color: #111827;
  font-size: 13px;
  line-height: 1.2;
  letter-spacing: -0.01em;
  word-break: break-word;
}

.admin-page-header__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.admin-page-header__actions :deep(.arco-btn) {
  height: 30px;
  padding: 0 12px;
}

@media (max-width: 960px) {
  .admin-page-header {
    align-items: stretch;
    flex-direction: column;
  }

  .admin-page-header__side {
    min-width: 0;
    flex-wrap: wrap;
  }

  .admin-page-header__actions {
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
</style>
