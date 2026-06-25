<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SkillTestRunResponse } from '../../types/workbench'
import type { SkillPageCopy, SkillPublishCheck, SkillSummary, TestTab, ValidationState } from './types'

type SampleTableCell = {
  text: string
  colspan: number
  rowspan: number
  isHeader: boolean
}

type SampleTablePreview = {
  id: string
  rows: SampleTableCell[][]
}

const props = defineProps<{
  pageCopy: SkillPageCopy
  testTab: TestTab
  testRunning: boolean
  saving: boolean
  testInstruction: string
  testSampleText: string
  testResult: SkillTestRunResponse | null
  currentSkillInfo: SkillSummary
  publishChecks: SkillPublishCheck[]
  publishIssues: string[]
  validationState: ValidationState
  validationMessage: string
}>()

const emit = defineEmits<{
  'update:testTab': [value: TestTab]
  'update:testInstruction': [value: string]
  'update:testSampleText': [value: string]
  run: []
  validate: []
  save: []
  'return-to-form': []
}>()

const sampleHtmlTables = computed(() => parseHtmlSampleTables(props.testSampleText))
const sampleRawOpen = ref(true)
const sampleTextPreview = computed(() => {
  const text = props.testSampleText.trim()
  if (!text) return ''
  return text.length > 5000 ? `${text.slice(0, 5000)}\n...` : text
})

function setTab(value: TestTab) {
  emit('update:testTab', value)
}

function updateInstruction(event: Event) {
  emit('update:testInstruction', (event.target as HTMLTextAreaElement).value)
}

function updateSampleText(event: Event) {
  emit('update:testSampleText', (event.target as HTMLTextAreaElement).value)
}

async function handleSampleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  emit('update:testSampleText', await file.text())
  sampleRawOpen.value = true
  setTab('config')
  input.value = ''
}

function handleSampleRawToggle(event: Event) {
  sampleRawOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

function formatDuration(value?: number | null) {
  if (!value) return '0 秒'
  return `${(value / 1000).toFixed(2)} 秒`
}

function stringifyPreview(value: unknown) {
  if (value == null) return ''
  return JSON.stringify(value, null, 2)
}

function parseHtmlSampleTables(source: string): SampleTablePreview[] {
  if (typeof DOMParser === 'undefined') return []
  const htmlSources = extractHtmlSources(source)
  if (!htmlSources.length) return []
  const html = htmlSources.join('\n')
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return Array.from(doc.querySelectorAll('table'))
    .slice(0, 4)
    .map((table, tableIndex) => {
      const rows = Array.from(table.querySelectorAll('tr'))
        .slice(0, 80)
        .map((row) =>
          Array.from(row.children)
            .filter((cell) => cell.tagName === 'TD' || cell.tagName === 'TH')
            .map((cell) => ({
              text: (cell.textContent || '').replace(/\s+/g, ' ').trim() || ' ',
              colspan: Math.max(1, Number(cell.getAttribute('colspan')) || 1),
              rowspan: Math.max(1, Number(cell.getAttribute('rowspan')) || 1),
              isHeader: cell.tagName === 'TH',
            })),
        )
        .filter((row) => row.length)
      return { id: `sample-table-${tableIndex}`, rows }
    })
    .filter((table) => table.rows.length)
}

function extractHtmlSources(source: string): string[] {
  const trimmed = source.trim()
  if (!trimmed) return []
  const fragments = new Set<string>()
  const pushHtml = (value: string) => {
    const decoded = decodeHtmlEntities(value)
    const tableFragments = decoded.match(/<table[\s\S]*?<\/table>/gi)
    if (tableFragments?.length) {
      tableFragments.forEach((fragment) => fragments.add(fragment))
    }
  }
  const visit = (value: unknown) => {
    if (typeof value === 'string') {
      pushHtml(value)
      return
    }
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    if (value && typeof value === 'object') {
      Object.values(value as Record<string, unknown>).forEach(visit)
    }
  }
  try {
    visit(JSON.parse(trimmed))
  } catch {
    pushHtml(trimmed)
  }
  return Array.from(fragments)
}

function decodeHtmlEntities(value: string) {
  if (/<table[\s>]/i.test(value)) return value
  if (!/&(?:lt|gt|amp|quot|apos|#\d+|#x[0-9a-f]+);/i.test(value)) return value
  const doc = new DOMParser().parseFromString(value, 'text/html')
  return doc.documentElement.textContent || value
}
</script>

<template>
  <section class="skill-center__column skill-center__column--test">
    <div class="skill-center__column-head">
      <div>
        <span>02</span>
        <strong>{{ pageCopy.testTitle }}</strong>
        <em>{{ pageCopy.testSubtitle }}</em>
      </div>
      <button type="button" class="skill-center__primary-action" :disabled="testRunning" @click="$emit('run')">
        {{ testRunning ? '试跑中' : pageCopy.runButton }}
      </button>
    </div>

    <div class="skill-center__test-tabs" role="tablist" aria-label="试跑区域">
      <button
        type="button"
        role="tab"
        :aria-selected="testTab === 'config'"
        :class="{ 'is-active': testTab === 'config' }"
        @click="setTab('config')"
      >
        {{ pageCopy.configTab }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="testTab === 'result'"
        :class="{ 'is-active': testTab === 'result' }"
        @click="setTab('result')"
      >
        {{ pageCopy.resultTab }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="testTab === 'publish'"
        :class="{ 'is-active': testTab === 'publish' }"
        @click="setTab('publish')"
      >
        发布
      </button>
    </div>

    <div v-if="testTab === 'config'" class="skill-center__sample">
      <label class="skill-center__test-instruction">
        <span>{{ pageCopy.requirementLabel }}</span>
        <textarea
          :value="testInstruction"
          :placeholder="pageCopy.requirementPlaceholder"
          @input="updateInstruction"
        />
      </label>
      <div class="skill-center__sample-head">
        <div>
          <strong>{{ pageCopy.sampleTitle }}</strong>
          <span>{{ pageCopy.sampleHint }}</span>
        </div>
        <label class="skill-center__upload">
          上传
          <input type="file" accept=".json,.html,.htm,.txt,.md" @change="handleSampleFileChange" />
        </label>
      </div>
      <details class="skill-center__sample-raw" :open="sampleRawOpen" @toggle="handleSampleRawToggle">
        <summary>{{ testSampleText.trim() ? pageCopy.rawClosed : pageCopy.rawOpen }}</summary>
        <textarea
          :value="testSampleText"
          class="skill-center__sample-input"
          :placeholder="pageCopy.rawPlaceholder"
          @input="updateSampleText"
        />
      </details>
      <div class="skill-center__sample-preview">
        <div class="skill-center__sample-preview-head">
          <strong>{{ pageCopy.previewTitle }}</strong>
          <span v-if="sampleHtmlTables.length">{{ sampleHtmlTables.length }} 个 HTML 表格，默认展示前 4 个。</span>
          <span v-else-if="sampleTextPreview">文本预览</span>
          <span v-else>等待样本</span>
        </div>
        <template v-if="sampleHtmlTables.length">
          <div
            v-for="table in sampleHtmlTables"
            :key="table.id"
            class="skill-center__sample-table-scroll"
          >
            <table class="skill-center__sample-table">
              <tbody>
                <tr v-for="(row, rowIndex) in table.rows" :key="`${table.id}-${rowIndex}`">
                  <component
                    :is="cell.isHeader || rowIndex === 0 ? 'th' : 'td'"
                    v-for="(cell, cellIndex) in row"
                    :key="`${table.id}-${rowIndex}-${cellIndex}`"
                    :colspan="cell.colspan"
                    :rowspan="cell.rowspan"
                  >
                    {{ cell.text }}
                  </component>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <pre v-else-if="sampleTextPreview" class="skill-center__sample-text-preview">{{ sampleTextPreview }}</pre>
        <div v-else class="skill-center__sample-preview-empty">
          {{ pageCopy.previewEmpty }}
        </div>
      </div>
    </div>

    <div v-else-if="testTab === 'publish'" class="skill-center__publish-panel">
      <div class="skill-center__publish-brief">
        <strong>{{ currentSkillInfo.name }}</strong>
        <span class="skill-center__publish-skill-meta">
          <span>{{ currentSkillInfo.id }}</span>
          <span class="skill-center__version-pill">v{{ currentSkillInfo.version }}</span>
        </span>
      </div>

      <div class="skill-center__publish-checks">
        <div
          v-for="item in publishChecks"
          :key="item.label"
          :class="['skill-center__publish-check', { 'is-ok': item.ok, 'is-error': !item.ok }]"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>

      <div v-if="publishIssues.length" class="skill-center__publish-warning">
        <strong>还差 {{ publishIssues.length }} 项</strong>
        <span>{{ publishIssues.join('、') }}</span>
        <button type="button" @click="$emit('return-to-form')">回到表单</button>
      </div>

      <div class="skill-center__publish-actions">
        <button type="button" @click="$emit('validate')">语法校验</button>
        <button type="button" class="skill-center__primary-action" :disabled="saving" @click="$emit('save')">
          {{ saving ? '发布中' : '校验并发布' }}
        </button>
      </div>
      <p :class="`skill-center__validation skill-center__validation--${validationState}`">
        {{ validationMessage || pageCopy.publishAdvice }}
      </p>
    </div>

    <template v-else>
      <div v-if="testRunning" class="skill-center__run-state">
        <strong>{{ pageCopy.runningTitle }}</strong>
        <span>{{ pageCopy.runningText }}</span>
      </div>
      <div v-else-if="testResult" class="skill-center__test-result">
        <div class="skill-center__test-meta">
          <span :class="{ 'is-ok': testResult.valid, 'is-error': !testResult.valid }">
            {{ testResult.valid ? '通过' : '失败' }}
          </span>
          <span>{{ testResult.model || 'unknown model' }}</span>
          <span>{{ formatDuration(testResult.durationMs) }}</span>
          <span>输入 {{ testResult.inputChars }} 字符 · 输出 {{ testResult.outputChars }} 字符</span>
        </div>
        <pre v-if="testResult.errors.length" class="skill-center__test-errors">{{ testResult.errors.join('\n') }}</pre>
        <pre class="skill-center__test-json">{{ stringifyPreview(testResult.extractionResult || testResult.rawOutput) }}</pre>
      </div>
      <div v-else class="skill-center__empty skill-center__empty--stage">
        <strong>{{ pageCopy.noResultTitle }}</strong>
        <span>{{ pageCopy.noResultText }}</span>
      </div>
    </template>

    <p
      v-if="validationState !== 'idle' && validationMessage && testTab !== 'publish'"
      :class="`skill-center__validation skill-center__validation--${validationState}`"
    >
      {{ validationMessage }}
    </p>
  </section>
</template>
