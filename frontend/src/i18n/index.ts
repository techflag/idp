// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
import { computed, ref, watch } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'

export type SupportedLocale = 'zh-CN' | 'en-US'

export const SUPPORTED_LOCALES: SupportedLocale[] = ['zh-CN', 'en-US']
export const LOCALE_STORAGE_KEY = 'idp.locale'

function normalizeLocale(value: unknown): SupportedLocale | '' {
  const raw = String(value || '').trim().toLowerCase()
  if (!raw) return ''
  if (raw === 'zh' || raw === 'zh-cn' || raw.startsWith('zh-')) return 'zh-CN'
  if (raw === 'en' || raw === 'en-us' || raw.startsWith('en-')) return 'en-US'
  return ''
}

function detectInitialLocale(): SupportedLocale {
  const stored = normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY))
  if (stored) return stored
  const configured = normalizeLocale(import.meta.env.VITE_DEFAULT_LOCALE)
  if (configured) return configured
  const browserLocale = normalizeLocale(window.navigator.language)
  if (browserLocale) return browserLocale
  for (const language of window.navigator.languages || []) {
    const locale = normalizeLocale(language)
    if (locale) return locale
  }
  return 'zh-CN'
}

export const currentLocale = ref<SupportedLocale>(detectInitialLocale())

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: currentLocale.value,
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

export const isEnglishLocale = computed(() => currentLocale.value === 'en-US')

export function setLocale(locale: SupportedLocale) {
  if (!SUPPORTED_LOCALES.includes(locale)) return
  currentLocale.value = locale
}

export function toggleLocale() {
  setLocale(currentLocale.value === 'zh-CN' ? 'en-US' : 'zh-CN')
}

watch(
  currentLocale,
  (locale) => {
    i18n.global.locale.value = locale
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
    document.documentElement.lang = locale
    document.title = String(i18n.global.t('app.title'))
  },
  { immediate: true },
)

export function t(key: string, values?: Record<string, unknown>) {
  return String(i18n.global.t(key, values ?? {}))
}
