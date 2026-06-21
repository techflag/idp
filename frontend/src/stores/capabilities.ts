import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchSystemCapabilities } from '../services/workbenchApi'
import type {
  CapabilityResponse,
  LimitPolicyResponse,
  ProviderRequirementResponse,
  SystemCapabilitiesResponse,
} from '../types/system'

export const useCapabilitiesStore = defineStore('capabilities', () => {
  const initialized = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const snapshot = ref<SystemCapabilitiesResponse | null>(null)

  const edition = computed(() => snapshot.value?.edition ?? 'community')
  const capabilitiesByKey = computed<Record<string, CapabilityResponse>>(() => {
    const result: Record<string, CapabilityResponse> = {}
    for (const capability of snapshot.value?.capabilities ?? []) {
      result[capability.key] = capability
    }
    return result
  })
  const providersByKey = computed<Record<string, ProviderRequirementResponse>>(() => {
    const result: Record<string, ProviderRequirementResponse> = {}
    for (const provider of snapshot.value?.providers ?? []) {
      result[provider.key] = provider
    }
    return result
  })
  const limitsByKey = computed<Record<string, LimitPolicyResponse>>(() => {
    const result: Record<string, LimitPolicyResponse> = {}
    for (const limit of snapshot.value?.limits ?? []) {
      result[limit.key] = limit
    }
    return result
  })

  async function load() {
    if (initialized.value || loading.value) {
      return
    }

    loading.value = true
    error.value = null
    try {
      snapshot.value = await fetchSystemCapabilities()
      initialized.value = true
    } catch (err) {
      error.value = err instanceof Error ? err.message : '系统能力加载失败'
      initialized.value = true
    } finally {
      loading.value = false
    }
  }

  function getCapability(key: string): CapabilityResponse | undefined {
    return capabilitiesByKey.value[key]
  }

  function isCapabilityEnabled(key: string): boolean {
    return Boolean(getCapability(key)?.enabled)
  }

  function isCapabilityAvailable(key: string): boolean {
    const capability = getCapability(key)
    return capability ? capability.level !== 'unavailable' : true
  }

  function getProvider(key: string): ProviderRequirementResponse | undefined {
    return providersByKey.value[key]
  }

  function getLimit(key: string): LimitPolicyResponse | undefined {
    return limitsByKey.value[key]
  }

  return {
    initialized,
    loading,
    error,
    snapshot,
    edition,
    capabilitiesByKey,
    providersByKey,
    limitsByKey,
    load,
    getCapability,
    isCapabilityEnabled,
    isCapabilityAvailable,
    getProvider,
    getLimit,
  }
})
