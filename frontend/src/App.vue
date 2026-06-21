<template>
  <a-config-provider :locale="arcoLocale">
    <div
      class="app-shell"
      :class="{
        'app-shell--admin': isAdminLayout,
        'app-shell--entry': isEntryLayout,
        'app-shell--bootstrapping': showAuthBootstrap,
      }"
    >
    <template v-if="isAdminLayout">
      <AppShellHeader />
      <div
        class="app-shell__admin-layout"
        :class="{ 'app-shell__admin-layout--workbench': isAdminWorkbenchLayout }"
      >
        <aside v-if="!isAdminWorkbenchLayout" class="app-shell__admin-sidebar">
          <AdminSidebar />
        </aside>
        <section
          class="app-shell__admin-content"
          :class="{ 'app-shell__admin-content--workbench': isAdminWorkbenchLayout }"
        >
          <main
            class="app-shell__main app-shell__main--admin"
            :class="{ 'app-shell__main--admin-workbench': isAdminWorkbenchLayout }"
          >
            <RouterView />
          </main>
        </section>
      </div>
    </template>
    <template v-else>
      <AppShellHeader v-if="showGlobalHeader" />
      <main class="app-shell__main" :class="{ 'app-shell__main--entry': !showGlobalHeader }">
        <RouterView />
      </main>
    </template>

      <div v-if="showAuthBootstrap" class="app-shell__bootstrap">
        <div class="app-shell__bootstrap-card">
          <div class="app-shell__bootstrap-title">{{ t('app.title') }}</div>
          <div class="app-shell__bootstrap-text">{{ t('app.bootstrapText') }}</div>
          <a-spin :loading="true" />
        </div>
      </div>
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AdminSidebar from './components/AdminSidebar.vue'
import AppShellHeader from './components/AppShellHeader.vue'
import { arcoLocale } from './i18n/arco'
import { t } from './i18n'
import { installStaticTextI18n } from './i18n/staticText'
import { useAuthStore } from './stores/auth'

const route = useRoute()
const auth = useAuthStore()
const adminRouteNames = [
  'admin',
  'admin-customers',
  'admin-customer',
  'admin-tasks',
  'admin-skills',
  'admin-applications',
  'admin-applications-new',
  'admin-applications-detail',
  'admin-extraction-skills',
  'admin-operation-skills',
]
const isEntryLayout = computed(() => route.name === 'entry')
const isAdminWorkbenchLayout = computed(
  () => (
    String(route.name ?? '') === 'task-detail' ||
    String(route.name ?? '') === 'admin-applications-new'
  ) && auth.currentUser?.role === 'admin',
)
const isAdminLayout = computed(() => {
  const routeName = String(route.name ?? '')
  if (adminRouteNames.includes(routeName)) {
    return true
  }
  if (isAdminWorkbenchLayout.value) {
    return true
  }
  return false
})
const showGlobalHeader = computed(() => route.name !== 'entry' && !isAdminLayout.value)
const showAuthBootstrap = computed(() => auth.bootstrapping && !auth.initialized)

let uninstallStaticTextI18n: (() => void) | null = null
onMounted(() => {
  uninstallStaticTextI18n = installStaticTextI18n()
})
onUnmounted(() => {
  uninstallStaticTextI18n?.()
})
</script>

<style scoped>
.app-shell {
  position: relative;
  min-height: 100vh;
  padding: 18px 22px 28px;
  background: #eef2f6;
}

.app-shell--bootstrapping {
  overflow: hidden;
}

.app-shell--admin {
  padding: 0;
  background: #f2f3f5;
}

.app-shell--entry {
  padding: 0;
  background: #edf2f7;
}

.app-shell__admin-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  min-height: calc(100vh - 56px);
}

.app-shell__admin-layout--workbench {
  grid-template-columns: 1fr;
  min-height: calc(100vh - 52px);
}

.app-shell__admin-sidebar {
  border-right: 1px solid #e5e6eb;
  background: #ffffff;
}

.app-shell__admin-content {
  min-width: 0;
  padding: 16px 20px 24px;
  background: #f2f3f5;
}

.app-shell__admin-content--workbench {
  padding: 6px 8px 8px;
}

.app-shell__main {
  max-width: 1500px;
  margin: 16px auto 0;
}

.app-shell__main--admin {
  max-width: none;
  margin: 0;
}

.app-shell__main--admin-workbench {
  width: 100%;
}

.app-shell__main--entry {
  max-width: none;
  margin-top: 0;
}

.app-shell__bootstrap {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(233, 239, 245, 0.9);
  backdrop-filter: blur(2px);
}

.app-shell__bootstrap-card {
  display: grid;
  gap: 10px;
  min-width: min(420px, calc(100vw - 48px));
  padding: 24px 28px;
  border: 1px solid #d7dde5;
  background: #ffffff;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.08);
}

.app-shell__bootstrap-title {
  color: #111827;
  font-size: 22px;
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.app-shell__bootstrap-text {
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.app-shell__main--admin :deep(.panel-card) {
  border-radius: 4px !important;
  background: #ffffff !important;
  box-shadow: none !important;
  border: 1px solid #e5e6eb !important;
  backdrop-filter: none !important;
}

.app-shell__main--admin :deep(.panel-card::before) {
  display: none !important;
}

.app-shell__main--admin :deep(.admin-page__hero),
.app-shell__main--admin :deep(.admin-customers-page__hero),
.app-shell__main--admin :deep(.admin-recognition-page__hero),
.app-shell__main--admin :deep(.admin-customer-page__hero) {
  border-radius: 4px !important;
  background: #ffffff !important;
  border: 1px solid #e5e6eb !important;
  box-shadow: none !important;
}

.app-shell__main--admin :deep(.admin-page__hero-copy h2),
.app-shell__main--admin :deep(.admin-customers-page__hero h2),
.app-shell__main--admin :deep(.admin-recognition-page__hero h2),
.app-shell__main--admin :deep(.admin-customer-page__hero h2) {
  color: #111827 !important;
}

.app-shell__main--admin :deep(.admin-page__hero-summary),
.app-shell__main--admin :deep(.admin-customers-page__summary),
.app-shell__main--admin :deep(.admin-recognition-page__summary),
.app-shell__main--admin :deep(.admin-customer-page__summary) {
  color: #64748b !important;
}

.app-shell__main--admin :deep(.admin-page__hero-eyebrow),
.app-shell__main--admin :deep(.admin-customers-page__eyebrow),
.app-shell__main--admin :deep(.admin-recognition-page__eyebrow),
.app-shell__main--admin :deep(.admin-customer-page__eyebrow) {
  color: #2563eb !important;
}

.app-shell__main--admin :deep(.admin-page__hero-aside) {
  border-radius: 4px !important;
  background: #f8fafc !important;
  border: 1px solid #e5e6eb !important;
}

.app-shell__main--admin :deep(.admin-page__hero-aside span) {
  color: #64748b !important;
}

.app-shell__main--admin :deep(.admin-page__hero-aside strong) {
  color: #111827 !important;
}

.app-shell__main--admin :deep(.admin-page__metric-card),
.app-shell__main--admin :deep(.admin-page__status-item) {
  border-radius: 4px !important;
  box-shadow: none !important;
}

.app-shell__main--admin :deep(.admin-page__metric-card--accent) {
  background: #f3f6fb !important;
}

.app-shell__main--admin :deep(.arco-table),
.app-shell__main--admin :deep(.task-list-table .arco-table) {
  border-radius: 0 !important;
  box-shadow: none !important;
}

.app-shell__main--admin :deep(.arco-btn),
.app-shell__main--admin :deep(.arco-tag) {
  border-radius: 4px !important;
}

.app-shell__main--admin :deep(.arco-btn-primary) {
  background: #2563eb !important;
  border-color: #2563eb !important;
}

@media (max-width: 960px) {
  .app-shell {
    padding: 12px;
  }

  .app-shell--admin {
    padding: 0;
  }

  .app-shell__admin-layout {
    grid-template-columns: 1fr;
  }

  .app-shell__admin-content {
    padding: 10px;
  }

  .app-shell__admin-content--workbench {
    padding: 8px;
  }
}
</style>
