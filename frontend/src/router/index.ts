// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
import { createRouter, createWebHistory } from 'vue-router'
import AdminCustomerWorkspacePage from '../pages/AdminCustomerWorkspacePage.vue'
import AdminCustomersPage from '../pages/AdminCustomersPage.vue'
import AdminOverviewPage from '../pages/AdminOverviewPage.vue'
import AdminRecognitionTasksPage from '../pages/AdminRecognitionTasksPage.vue'
import AdminApplicationMarketPage from '../pages/AdminApplicationMarketPage.vue'
import AdminApplicationWorkshopPage from '../pages/AdminApplicationWorkshopPage.vue'
import AdminSkillCenterPage from '../pages/AdminSkillCenterPage.vue'
import EntryPage from '../pages/EntryPage.vue'
import UserTaskListPage from '../pages/UserTaskListPage.vue'
import WorkbenchPage from '../pages/WorkbenchPage.vue'
import { useAuthStore } from '../stores/auth'
import { useCapabilitiesStore } from '../stores/capabilities'
import { pinia } from '../stores/pinia'

const router = createRouter({
  // Respect Vite's deployed base path such as /idp/.
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'entry',
      component: EntryPage,
      meta: {
        guestOnly: true,
        publicCore: true,
      },
    },
    {
      path: '/admin',
      name: 'admin',
      component: AdminOverviewPage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/admin/customers',
      name: 'admin-customers',
      component: AdminCustomersPage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/admin/customers/:customerId',
      name: 'admin-customer',
      component: AdminCustomerWorkspacePage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/admin/tasks',
      name: 'admin-tasks',
      component: AdminRecognitionTasksPage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        capability: 'document.parse',
      },
    },
    {
      path: '/admin/skills',
      name: 'admin-skills',
      redirect: { name: 'admin-extraction-skills' },
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/admin/skills/applications',
      name: 'admin-applications',
      component: AdminApplicationMarketPage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        capability: 'application.authoring',
      },
    },
    {
      path: '/admin/skills/applications/new',
      name: 'admin-applications-new',
      component: AdminApplicationWorkshopPage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        capability: 'application.authoring',
      },
    },
    {
      path: '/admin/skills/applications/:applicationId/edit',
      name: 'admin-applications-edit',
      component: AdminApplicationWorkshopPage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        capability: 'application.authoring',
      },
    },
    {
      path: '/admin/skills/applications/:applicationId',
      name: 'admin-applications-detail',
      component: AdminApplicationMarketPage,
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        capability: 'application.authoring',
      },
    },
    {
      path: '/admin/skills/extraction',
      name: 'admin-extraction-skills',
      component: AdminSkillCenterPage,
      props: { skillKind: 'extraction' },
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        capability: 'llm.extract',
      },
    },
    {
      path: '/admin/skills/extraction/new',
      name: 'admin-extraction-skill-new',
      component: AdminSkillCenterPage,
      props: { skillKind: 'extraction' },
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        capability: 'llm.extract',
      },
    },
    {
      path: '/admin/skills/extraction/:scope(platform|customer)/:skillId',
      name: 'admin-extraction-skill-detail',
      component: AdminSkillCenterPage,
      props: { skillKind: 'extraction' },
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/admin/skills/operation',
      name: 'admin-operation-skills',
      component: AdminSkillCenterPage,
      props: { skillKind: 'operation' },
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/admin/skills/operation/new',
      name: 'admin-operation-skill-new',
      component: AdminSkillCenterPage,
      props: { skillKind: 'operation' },
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/admin/skills/operation/:scope(platform|customer)/:skillId',
      name: 'admin-operation-skill-detail',
      component: AdminSkillCenterPage,
      props: { skillKind: 'operation' },
      meta: {
        requiresAuth: true,
        roles: ['admin'],
        publicCore: true,
      },
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: UserTaskListPage,
      meta: {
        requiresAuth: true,
        roles: ['customer', 'user'],
        publicCore: true,
      },
    },
    {
      path: '/tasks/:taskId',
      name: 'task-detail',
      component: WorkbenchPage,
      props: true,
      meta: {
        requiresAuth: true,
        roles: ['admin', 'customer', 'user'],
        publicCore: true,
      },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore(pinia)
  const capabilities = useCapabilitiesStore(pinia)
  if (!capabilities.initialized) {
    await capabilities.load()
  }

  if (!auth.initialized) {
    await auth.bootstrap()
  }

  const requiresAuth = Boolean(to.meta.requiresAuth)
  const guestOnly = Boolean(to.meta.guestOnly)
  const roles = Array.isArray(to.meta.roles) ? (to.meta.roles as string[]) : []

  if (guestOnly && auth.isAuthenticated) {
    return { name: auth.homeRouteName }
  }

  if (requiresAuth && !auth.isAuthenticated) {
    return { name: 'entry', query: { redirect: to.fullPath } }
  }

  if (requiresAuth && roles.length > 0 && auth.currentUser && !roles.includes(auth.currentUser.role)) {
    return { name: auth.homeRouteName }
  }

  const capability = typeof to.meta.capability === 'string' ? to.meta.capability : ''
  if (capability && !capabilities.isCapabilityAvailable(capability)) {
    if (auth.currentUser?.role === 'admin') {
      return { name: 'admin-tasks' }
    }
    return { name: auth.homeRouteName }
  }

  return true
})

export default router
