<script setup lang="ts">
import { computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconPoweroff } from '@arco-design/web-vue/es/icon'
import { useRoute, useRouter } from 'vue-router'
import { currentLocale, setLocale, t, type SupportedLocale } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useWorkbenchStore } from '../stores/workbench'

const store = useWorkbenchStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const currentUser = computed(() => auth.currentUser)
const isCustomerTaskSection = computed(() => {
  return currentUser.value?.role !== 'admin' && (route.name === 'tasks' || route.name === 'task-detail')
})
const roleLabel = computed(() => (currentUser.value?.role === 'admin' ? t('auth.adminRole') : t('auth.customerRole')))
const headerTitle = computed(() => (currentUser.value?.role === 'admin' ? t('app.title') : t('app.customerTitle')))
const isWorkbenchRoute = computed(() => route.name === 'task-detail')
const currentSection = computed(() => {
  if (route.name === 'admin') {
    return t('nav.adminOverview')
  }
  if (route.name === 'admin-customer') {
    return t('nav.customerSpace')
  }
  if (route.name === 'admin-customers') {
    return t('nav.customers')
  }
  if (route.name === 'admin-tasks') {
    return t('nav.recognitionTasks')
  }
  if (
    route.name === 'admin-applications' ||
    route.name === 'admin-applications-new' ||
    route.name === 'admin-applications-detail'
  ) {
    return t('nav.documentApplications')
  }
  if (
    route.name === 'admin-extraction-skills' ||
    route.name === 'admin-extraction-skill-new' ||
    route.name === 'admin-extraction-skill-detail' ||
    route.name === 'admin-skills'
  ) {
    return t('nav.extractionSkill')
  }
  if (
    route.name === 'admin-operation-skills' ||
    route.name === 'admin-operation-skill-new' ||
    route.name === 'admin-operation-skill-detail'
  ) {
    return t('nav.operationSkill')
  }
  if (route.name === 'tasks') {
    return t('nav.customerTasks')
  }
  return t('nav.taskWorkbench')
})

const localeOptions: Array<{ locale: SupportedLocale; label: string }> = [
  { locale: 'zh-CN', label: t('locale.zhCN') },
  { locale: 'en-US', label: t('locale.enUS') },
]

function goToHome() {
  if (auth.currentUser?.role === 'admin') {
    router.push({ name: 'admin' })
    return
  }
  if (auth.currentUser) {
    router.push({ name: 'tasks' })
    return
  }
  router.push({ name: 'entry' })
}

async function logout() {
  await auth.logout()
  store.reset()
  Message.success(t('auth.logoutSuccess'))
  router.push({ name: 'entry' })
}
</script>

<template>
  <header
    :class="[
      'app-header',
      currentUser?.role === 'admin' ? 'app-header--admin' : 'app-header--customer',
      { 'app-header--workbench': isWorkbenchRoute },
    ]"
  >
    <template v-if="currentUser?.role === 'admin'">
      <div class="app-header__brand" @click="goToHome">
        <span class="app-header__brand-mark" aria-hidden="true">
          <span></span>
        </span>
        <span class="app-header__brand-copy">
          <strong class="app-header__admin-title">{{ headerTitle }}</strong>
          <span class="app-header__admin-section">{{ currentSection }}</span>
        </span>
      </div>

      <div class="app-header__actions">
        <div class="app-header__locale" :aria-label="t('locale.switchLabel')">
          <button
            v-for="item in localeOptions"
            :key="item.locale"
            type="button"
            :class="{ 'is-active': currentLocale === item.locale }"
            @click="setLocale(item.locale)"
          >
            {{ item.label }}
          </button>
        </div>
        <div class="app-header__user-meta">
          <span class="app-header__user-role">{{ roleLabel }}</span>
          <span class="app-header__user">{{ currentUser?.displayName }}</span>
        </div>
        <a-button type="secondary" size="small" @click="logout">
          <template #icon>
            <IconPoweroff />
          </template>
          {{ t('auth.logout') }}
        </a-button>
      </div>
    </template>

    <template v-else>
      <div class="app-header__customer-main">
        <button type="button" class="app-header__customer-home" @click="goToHome">
          <span class="app-header__customer-section">{{ currentSection }}</span>
          <strong>{{ currentUser?.displayName || headerTitle }}</strong>
        </button>
        <nav class="app-header__customer-nav" :aria-label="t('nav.customerTasks')">
          <button
            type="button"
            :class="['app-header__customer-tab', { 'app-header__customer-tab--active': isCustomerTaskSection }]"
            @click="store.setRole('customer'); router.push({ name: 'tasks' })"
          >
            {{ t('nav.customerTasks') }}
          </button>
        </nav>
      </div>

      <div class="app-header__customer-actions">
        <div class="app-header__locale" :aria-label="t('locale.switchLabel')">
          <button
            v-for="item in localeOptions"
            :key="item.locale"
            type="button"
            :class="{ 'is-active': currentLocale === item.locale }"
            @click="setLocale(item.locale)"
          >
            {{ item.label }}
          </button>
        </div>
        <div class="app-header__customer-user">
          <span>{{ currentUser?.displayName }}</span>
          <em>{{ currentUser?.username }}</em>
        </div>
        <a-button type="secondary" @click="logout">
          {{ t('auth.logout') }}
        </a-button>
      </div>
    </template>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  position: sticky;
  top: 0;
  z-index: 10;
  overflow: hidden;
}

.app-header--admin {
  min-height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid #e5e6eb;
  background: #ffffff;
  color: #1d2129;
  box-shadow: none;
}

.app-header--admin.app-header--workbench {
  min-height: 52px;
}

.app-header--customer {
  align-items: center;
  min-height: 52px;
  padding: 6px 14px;
  border: 1px solid #dbe1e8;
  background: #ffffff;
  color: #0f172a;
  box-shadow: none;
}

.app-header__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  min-width: 0;
  position: relative;
  z-index: 1;
}

.app-header__brand-mark {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: linear-gradient(135deg, #165dff 0%, #14c9c9 100%);
  box-shadow: 0 8px 18px rgba(22, 93, 255, 0.16);
  flex: 0 0 auto;
}

.app-header__brand-mark span {
  width: 14px;
  height: 14px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.92);
  transform: rotate(45deg);
}

.app-header__brand-copy {
  display: inline-flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.app-header__brand h1 {
  margin: 0;
  font-size: 14px;
  line-height: 1.15;
  letter-spacing: -0.01em;
  font-weight: 700;
}

.app-header--admin .app-header__brand h1 {
  color: #1d2129;
}

.app-header--customer .app-header__brand h1 {
  color: #0f172a;
  font-size: 22px;
  letter-spacing: -0.02em;
}

.app-header__eyebrow {
  margin: 0 0 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.app-header--customer .app-header__eyebrow {
  color: #64748b;
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}

.app-header__admin-title {
  color: #1d2129;
  font-size: 20px;
  line-height: 1;
  font-weight: 700;
  white-space: nowrap;
  letter-spacing: -0.02em;
}

.app-header--workbench .app-header__admin-title {
  font-size: 18px;
}

.app-header__admin-section {
  color: #86909c;
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
}

.app-header__brand p {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.6;
}

.app-header--admin .app-header__brand p {
  color: #86909c;
}

.app-header--customer .app-header__brand p {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.app-header__customer-main {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.app-header__customer-home {
  display: inline-grid;
  gap: 2px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.app-header__customer-home strong {
  color: #0f172a;
  font-size: 17px;
  line-height: 1.15;
  letter-spacing: -0.01em;
  font-weight: 700;
}

.app-header__customer-section {
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.app-header__customer-nav {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding-left: 16px;
  border-left: 1px solid #e2e8f0;
}

.app-header__customer-tab {
  height: 30px;
  padding: 0 12px;
  border: 1px solid #dbe1e8;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.app-header__customer-tab--active {
  border-color: #0f172a;
  background: #0f172a;
  color: #ffffff;
}

.app-header__customer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-header__customer-user {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding-right: 8px;
  border-right: 1px solid #e2e8f0;
  background: transparent;
}

.app-header__customer-user span {
  color: #0f172a;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
}

.app-header__customer-user em {
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.2;
}

.app-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  position: relative;
  z-index: 1;
}

.app-header__locale {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 30px;
  padding: 2px;
  border: 1px solid #d7dde5;
  border-radius: 4px;
  background: #f8fafc;
  flex: 0 0 auto;
}

.app-header__locale button {
  min-width: 38px;
  height: 24px;
  padding: 0 8px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  line-height: 24px;
  cursor: pointer;
}

.app-header__locale button.is-active {
  background: #ffffff;
  color: #165dff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}

.app-header__user-meta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: 2px;
  min-height: 30px;
  padding: 0 10px;
  border-radius: 6px;
}

.app-header--admin .app-header__user-meta {
  border: 1px solid #e5e6eb;
  background: #f7f8fa;
}

.app-header--customer .app-header__user-meta {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.app-header__user {
  font-size: 12px;
}

.app-header--admin .app-header__user {
  color: #1d2129;
}

.app-header--customer .app-header__user {
  color: #334155;
}

.app-header__actions :deep(.arco-btn) {
  min-width: 72px;
  font-weight: 600;
}

.app-header--admin .app-header__actions :deep(.arco-btn-secondary) {
  color: #4e5969;
  background: #ffffff;
  border-color: #e5e6eb;
}

.app-header--admin .app-header__actions :deep(.arco-btn-secondary:hover) {
  color: #165dff;
  background: #f2f5fb;
  border-color: #bedaff;
}

.app-header__user-role {
  color: #86909c;
  font-size: 12px;
  line-height: 1;
}

.app-header--customer .app-header__actions :deep(.arco-btn-secondary) {
  color: #334155;
  background: #ffffff;
  border-color: #dbe1e8;
}

.app-header--customer .app-header__actions :deep(.arco-btn-primary) {
  background: #2563eb;
  color: #ffffff;
  border-color: #2563eb;
}

.app-header__actions :deep(.arco-tag) {
  font-weight: 700;
}

@media (max-width: 960px) {
  .app-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .app-header--admin {
    min-height: auto;
    padding: 10px 12px;
  }

  .app-header--customer {
    align-items: flex-start;
    padding: 12px;
  }

  .app-header__customer-main {
    width: 100%;
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .app-header__customer-nav {
    width: 100%;
    padding-left: 0;
    border-left: 0;
  }

  .app-header__customer-actions {
    width: 100%;
    justify-content: space-between;
  }

  .app-header__customer-user {
    padding-right: 0;
    border-right: 0;
  }

  .app-header__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .app-header__user-meta {
    width: 100%;
  }

  .app-header__brand {
    align-items: flex-start;
    flex-direction: row;
    gap: 6px;
  }

  .app-header__brand-copy {
    display: grid;
    gap: 4px;
  }

  .app-header__admin-title {
    font-size: 16px;
  }

  .app-header__customer-main,
  .app-header__customer-actions {
    width: 100%;
  }

  .app-header__customer-main {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .app-header__customer-nav {
    width: 100%;
    padding-left: 0;
    border-left: 0;
  }

  .app-header__customer-actions {
    justify-content: space-between;
  }

  .app-header__customer-home strong {
    font-size: 16px;
  }
}
</style>
