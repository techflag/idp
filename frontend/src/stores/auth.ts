import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchCurrentUser, login as loginRequest, logout as logoutRequest } from '../services/workbenchApi'
import type { AuthUser } from '../types/auth'

export const useAuthStore = defineStore('auth', () => {
  const initialized = ref(false)
  const bootstrapping = ref(false)
  const loginLoading = ref(false)
  const currentUser = ref<AuthUser | null>(null)

  const isAuthenticated = computed(() => Boolean(currentUser.value))
  const homeRouteName = computed(() => (currentUser.value?.role === 'admin' ? 'admin' : 'tasks'))

  async function bootstrap() {
    if (initialized.value || bootstrapping.value) {
      return
    }

    bootstrapping.value = true
    try {
      currentUser.value = await fetchCurrentUser()
    } catch {
      currentUser.value = null
    } finally {
      initialized.value = true
      bootstrapping.value = false
    }
  }

  async function login(username: string, password: string) {
    loginLoading.value = true
    try {
      const user = await loginRequest({ username, password })
      currentUser.value = user
      initialized.value = true
      return user
    } finally {
      loginLoading.value = false
    }
  }

  async function logout() {
    try {
      await logoutRequest()
    } finally {
      currentUser.value = null
      initialized.value = true
    }
  }

  function clear() {
    currentUser.value = null
    initialized.value = true
  }

  return {
    initialized,
    bootstrapping,
    loginLoading,
    currentUser,
    isAuthenticated,
    homeRouteName,
    bootstrap,
    login,
    logout,
    clear,
  }
})

