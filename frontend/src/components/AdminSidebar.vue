<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import {
  IconCode,
  IconDashboard,
  IconFile,
  IconLayers,
  IconTool,
  IconUserGroup,
} from '@arco-design/web-vue/es/icon'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { t } from '../i18n'
import { useCapabilitiesStore } from '../stores/capabilities'

const route = useRoute()
const router = useRouter()
const capabilities = useCapabilitiesStore()

const navItems = [
  { name: 'admin', labelKey: 'nav.adminOverview', icon: IconDashboard },
  { name: 'admin-customers', labelKey: 'nav.customers', icon: IconUserGroup },
  { name: 'admin-tasks', labelKey: 'nav.recognitionTasks', icon: IconFile, capability: 'document.parse' },
  { name: 'admin-applications', labelKey: 'nav.documentApplications', icon: IconLayers, capability: 'application.authoring' },
  { name: 'admin-extraction-skills', labelKey: 'nav.extractionSkill', icon: IconCode },
  { name: 'admin-operation-skills', labelKey: 'nav.operationSkill', icon: IconTool },
]

const visibleNavItems = computed(() =>
  navItems.filter((item) => !item.capability || capabilities.isCapabilityAvailable(item.capability)),
)

function isActive(name: string) {
  if (name === 'admin-customers') {
    return route.name === 'admin-customers' || route.name === 'admin-customer'
  }
  if (name === 'admin-extraction-skills') {
    return (
      route.name === 'admin-extraction-skills' ||
      route.name === 'admin-extraction-skill-new' ||
      route.name === 'admin-extraction-skill-detail' ||
      route.name === 'admin-skills'
    )
  }
  if (name === 'admin-applications') {
    return (
      route.name === 'admin-applications' ||
      route.name === 'admin-applications-new' ||
      route.name === 'admin-applications-detail'
    )
  }
  if (name === 'admin-operation-skills') {
    return (
      route.name === 'admin-operation-skills' ||
      route.name === 'admin-operation-skill-new' ||
      route.name === 'admin-operation-skill-detail'
    )
  }
  return route.name === name
}

</script>

<template>
  <aside class="admin-sidebar">
    <div class="admin-sidebar__section">{{ t('nav.adminOverview') }}</div>
    <nav class="admin-sidebar__nav">
      <button
        v-for="item in visibleNavItems"
        :key="item.name"
        type="button"
        class="admin-sidebar__nav-item"
        :class="{ 'is-active': isActive(item.name) }"
        @click="router.push({ name: item.name })"
      >
        <span class="admin-sidebar__nav-icon">
          <component :is="item.icon" />
        </span>
        <span class="admin-sidebar__nav-label">{{ t(item.labelKey) }}</span>
      </button>
    </nav>
  </aside>
</template>

<style scoped>
.admin-sidebar {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 16px 12px 0;
  background: #ffffff;
  color: #1e293b;
}

.admin-sidebar__section {
  height: 28px;
  padding: 0 12px;
  color: #86909c;
  font-size: 12px;
  font-weight: 600;
  line-height: 28px;
}

.admin-sidebar__nav {
  display: grid;
  gap: 4px;
  padding: 0;
}

.admin-sidebar__nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 42px;
  padding: 0 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #4e5969;
  text-align: left;
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}

.admin-sidebar__nav-item:hover {
  background: #f2f5fb;
  color: #165dff;
}

.admin-sidebar__nav-item.is-active {
  background: #e8f3ff;
  color: #165dff;
  font-weight: 600;
}

.admin-sidebar__nav-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  color: #86909c;
  font-size: 18px;
  flex: 0 0 auto;
}

.admin-sidebar__nav-item:hover .admin-sidebar__nav-icon,
.admin-sidebar__nav-item.is-active .admin-sidebar__nav-icon {
  color: #165dff;
}

.admin-sidebar__nav-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 960px) {
  .admin-sidebar {
    min-height: auto;
    padding: 10px;
  }

  .admin-sidebar__nav {
    grid-template-columns: repeat(7, minmax(0, 1fr));
  }

  .admin-sidebar__section {
    display: none;
  }

  .admin-sidebar__nav-item {
    justify-content: center;
    padding: 0 8px;
  }
}
</style>
