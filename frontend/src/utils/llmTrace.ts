import type { LlmCallTraceSummary } from '../types/workbench'
import { t } from '../i18n'

export interface LlmTraceDisplayItem {
  label: string
  value: string
}

export function buildLlmTraceDisplayItems(summary?: LlmCallTraceSummary | null): LlmTraceDisplayItem[] {
  if (!summary || summary.callCount <= 0) {
    return []
  }
  const items: LlmTraceDisplayItem[] = [
    { label: t('trace.calls'), value: t('trace.times', { count: summary.callCount }) },
  ]
  if (summary.model || summary.provider) {
    items.push({ label: t('trace.model'), value: [summary.provider, summary.model].filter(Boolean).join(' / ') })
  }
  if (summary.totalMs > 0) {
    items.push({ label: t('trace.duration'), value: formatDuration(summary.totalMs) })
  }
  if (summary.totalTokens !== null && summary.totalTokens !== undefined) {
    items.push({ label: 'Token', value: String(summary.totalTokens) })
  } else if (summary.inputChars || summary.outputChars) {
    items.push({ label: t('trace.characters'), value: t('trace.inputOutputChars', { input: summary.inputChars, output: summary.outputChars }) })
  }
  if (summary.slowCallCount > 0) {
    items.push({ label: t('trace.slowCalls'), value: t('trace.times', { count: summary.slowCallCount }) })
  }
  return items
}

function formatDuration(ms: number) {
  if (ms < 1000) {
    return `${ms}ms`
  }
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) {
    return `${seconds}s`
  }
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`
}
