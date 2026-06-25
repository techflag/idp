<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type {
  ApplicationAsset,
  SkillSampleLocateAndExtractResponse,
} from '../types/workbench'

const props = withDefaults(defineProps<{
  applications: ApplicationAsset[]
  applicationsLoading?: boolean
  applicationRunEnabled?: boolean
  applicationRunDisabledReason?: string
  applicationActionLoading?: boolean
  temporaryExtractionEnabled?: boolean
  temporaryExtractionDisabledReason?: string
  temporaryExtractionLoading?: boolean
  temporaryExtractionResult?: SkillSampleLocateAndExtractResponse | null
  temporaryExtractionError?: string
  disabled?: boolean
  documentName?: string
  pageNo?: number | null
  pageCount?: number
}>(), {
  applicationsLoading: false,
  applicationRunEnabled: true,
  applicationRunDisabledReason: '',
  applicationActionLoading: false,
  temporaryExtractionEnabled: true,
  temporaryExtractionDisabledReason: '',
  temporaryExtractionLoading: false,
  temporaryExtractionResult: null,
  temporaryExtractionError: '',
  disabled: false,
  documentName: '',
  pageNo: null,
  pageCount: 0,
})

const emit = defineEmits<{
  runApplication: [payload: { applicationId: string; version: string | null }]
  temporaryExtract: [payload: { query: string; expectedOutput: string }]
  openApplicationAuthoring: []
  refreshApplications: []
}>()

const { t } = useI18n()

const selectedApplicationId = ref('')
const extractionQuery = ref('')
const extractionExpectedOutput = ref('')
const activeTab = ref<'application' | 'temporary'>('application')

const applicationKey = computed(() => props.applications
  .map((item) => `${item.applicationId}:${applicationVersion(item) || ''}`)
  .join('|'))

watch(
  applicationKey,
  () => {
    if (!props.applications.length) {
      selectedApplicationId.value = ''
      return
    }
    if (!props.applications.some((item) => item.applicationId === selectedApplicationId.value)) {
      selectedApplicationId.value = props.applications[0]?.applicationId ?? ''
    }
  },
  { immediate: true },
)

const selectedApplication = computed(() => (
  props.applications.find((item) => item.applicationId === selectedApplicationId.value) ?? null
))
const extractionTargetPlaceholder = computed(() => (
  props.pageNo
    ? t('taskActions.temporaryQueryPlaceholderWithPage', { page: props.pageNo })
    : t('taskActions.temporaryQueryPlaceholder')
))
const documentScopeLabel = computed(() => props.documentName || t('taskActions.currentDocumentScope'))
const scopeLabel = computed(() => {
  if (props.pageNo && props.pageCount) {
    return t('taskActions.currentScopeWithTotal', { page: props.pageNo, total: props.pageCount })
  }
  if (props.pageNo) {
    return t('taskActions.currentScope', { page: props.pageNo })
  }
  return documentScopeLabel.value
})
const applicationRunBlockedReason = computed(() => {
  if (!props.applicationRunEnabled) {
    return props.applicationRunDisabledReason || t('taskActions.applicationRunUnavailable')
  }
  if (!props.applications.length) {
    return t('taskActions.noApplicationHint')
  }
  return ''
})
const canRunSelectedApplication = computed(() => Boolean(
  selectedApplication.value
  && props.applicationRunEnabled
  && !props.disabled
  && !props.applicationActionLoading,
))
const canStartTemporaryExtraction = computed(() => Boolean(
  extractionQuery.value.trim()
  && props.temporaryExtractionEnabled
  && !props.disabled
  && !props.temporaryExtractionLoading,
))
const resultStatusText = computed(() => {
  const status = props.temporaryExtractionResult?.status
  if (status === 'extracted') return t('taskActions.temporaryStatusExtracted')
  if (status === 'located') return t('taskActions.temporaryStatusLocated')
  if (status === 'needs_review') return t('taskActions.temporaryStatusNeedsReview')
  if (status === 'not_found') return t('taskActions.temporaryStatusNotFound')
  return ''
})
const resultMetricText = computed(() => {
  const result = props.temporaryExtractionResult?.extractionResult
  if (!result) return ''
  const outputCount = result.outputs.length
  const fieldCount = result.fields.length
  const tableCount = result.tables.length
  return t('taskActions.temporaryResultMetrics', {
    outputs: outputCount,
    fields: fieldCount,
    tables: tableCount,
  })
})
const candidateCountText = computed(() => {
  const count = props.temporaryExtractionResult?.candidates.length ?? 0
  return count ? t('taskActions.candidateCount', { count }) : ''
})
const visibleCandidates = computed(() => props.temporaryExtractionResult?.candidates.slice(0, 3) ?? [])
const hasTemporaryExtractionResult = computed(() => Boolean(props.temporaryExtractionResult))
const hasUsableExtractionResult = computed(() => Boolean(props.temporaryExtractionResult?.extractionResult))

function applicationVersion(application: ApplicationAsset) {
  return application.latestPublishedVersion
    || application.resolvedVersion
    || application.defaultVersion
    || application.version
    || null
}

function selectApplication(application: ApplicationAsset) {
  selectedApplicationId.value = application.applicationId
}

function runSelectedApplication() {
  const application = selectedApplication.value
  if (!application || !canRunSelectedApplication.value) return
  emit('runApplication', {
    applicationId: application.applicationId,
    version: applicationVersion(application),
  })
}

function startTemporaryExtraction() {
  if (!canStartTemporaryExtraction.value) return
  emit('temporaryExtract', {
    query: extractionQuery.value.trim(),
    expectedOutput: extractionExpectedOutput.value.trim(),
  })
}
</script>

<template>
  <section class="task-action-panel">
    <header class="task-action-panel__header">
      <div>
        <h3>{{ t('taskActions.title') }}</h3>
        <span>{{ scopeLabel }}</span>
      </div>
    </header>

    <a-tabs
      v-model:active-key="activeTab"
      class="task-action-panel__tabs"
      type="line"
      lazy-load
    >
      <a-tab-pane key="application" :title="t('taskActions.applicationTab')">
        <section class="task-action-panel__tab-body">
          <div class="task-action-panel__section-head">
            <div>
              <strong>{{ t('taskActions.runApplication') }}</strong>
              <span>{{ t('taskActions.runApplicationDescription') }}</span>
            </div>
            <div class="task-action-panel__section-actions">
              <a-button
                size="small"
                :disabled="applicationsLoading"
                :loading="applicationsLoading"
                @click="emit('refreshApplications')"
              >
                {{ t('taskActions.refreshApplications') }}
              </a-button>
              <a-button
                size="small"
                type="primary"
                :disabled="!canRunSelectedApplication"
                :loading="applicationActionLoading"
                @click="runSelectedApplication"
              >
                {{ t('taskActions.runSelectedApplication') }}
              </a-button>
            </div>
          </div>

          <a-alert
            v-if="applicationRunBlockedReason"
            type="info"
            :content="applicationRunBlockedReason"
            show-icon
          />

          <div v-if="applications.length" class="task-action-panel__application-list">
            <button
              v-for="application in applications"
              :key="application.applicationId"
              type="button"
              class="task-action-panel__application"
              :class="{ 'is-selected': application.applicationId === selectedApplicationId }"
              @click="selectApplication(application)"
            >
              <strong>{{ application.name || application.applicationId }}</strong>
              <span>
                {{ application.documentType || t('taskActions.documentApplication') }}
                · {{ t('taskActions.stepCount', { count: application.stepCount }) }}
              </span>
              <small>{{ application.summary || application.scenario || t('taskActions.applicationSummaryFallback') }}</small>
            </button>
          </div>

          <div v-else class="task-action-panel__empty">
            <strong>{{ t('taskActions.noApplications') }}</strong>
            <span>{{ t('taskActions.noApplicationsDescription') }}</span>
            <a-button size="small" @click="emit('openApplicationAuthoring')">
              {{ t('taskActions.makeApplication') }}
            </a-button>
          </div>
        </section>
      </a-tab-pane>

      <a-tab-pane key="temporary" :title="t('taskActions.temporaryTab')">
        <section class="task-action-panel__tab-body">
          <div class="task-action-panel__section-head">
            <div>
              <strong>{{ t('taskActions.temporaryExtraction') }}</strong>
              <span>{{ t('taskActions.temporaryExtractionDescription') }}</span>
            </div>
            <a-button
              size="small"
              type="primary"
              :disabled="!canStartTemporaryExtraction"
              :loading="temporaryExtractionLoading"
              @click="startTemporaryExtraction"
            >
              {{ t('taskActions.startTemporaryExtraction') }}
            </a-button>
          </div>

          <a-alert
            v-if="!temporaryExtractionEnabled"
            type="warning"
            :content="temporaryExtractionDisabledReason || t('taskActions.temporaryExtractionUnavailable')"
            show-icon
          />

          <label class="task-action-panel__field">
            <span>{{ t('taskActions.extractTarget') }}</span>
            <a-textarea
              v-model="extractionQuery"
              :auto-size="{ minRows: 2, maxRows: 4 }"
              :placeholder="extractionTargetPlaceholder"
            />
          </label>

          <label class="task-action-panel__field">
            <span>{{ t('taskActions.outputRequirement') }}</span>
            <a-textarea
              v-model="extractionExpectedOutput"
              :auto-size="{ minRows: 2, maxRows: 4 }"
              :placeholder="t('taskActions.outputRequirementPlaceholder')"
            />
          </label>

          <div
            v-if="temporaryExtractionError"
            class="task-action-panel__result is-error"
          >
            <strong>{{ t('taskActions.temporaryExtractionFailed') }}</strong>
            <span>{{ temporaryExtractionError }}</span>
          </div>

          <div
            v-else-if="hasTemporaryExtractionResult"
            class="task-action-panel__result"
            :class="`is-${temporaryExtractionResult?.status || 'idle'}`"
          >
            <div>
              <strong>{{ resultStatusText }}</strong>
              <span>
                {{ temporaryExtractionResult?.dataTypeName || temporaryExtractionResult?.query }}
                <template v-if="resultMetricText"> · {{ resultMetricText }}</template>
                <template v-if="candidateCountText"> · {{ candidateCountText }}</template>
              </span>
            </div>
            <small v-if="temporaryExtractionResult?.model || temporaryExtractionResult?.provider">
              {{ temporaryExtractionResult?.provider || '-' }} / {{ temporaryExtractionResult?.model || '-' }}
            </small>
            <div v-if="visibleCandidates.length" class="task-action-panel__candidates">
              <span
                v-for="candidate in visibleCandidates"
                :key="candidate.nodeId"
              >
                {{ candidate.title || candidate.nodeId }}
              </span>
            </div>
            <div class="task-action-panel__result-actions">
              <a-button
                v-if="hasUsableExtractionResult"
                size="small"
                type="primary"
                @click="emit('openApplicationAuthoring')"
              >
                {{ t('taskActions.saveAsApplicationStep') }}
              </a-button>
              <a-button size="small" @click="emit('openApplicationAuthoring')">
                {{ t('taskActions.openApplicationAuthoring') }}
              </a-button>
            </div>
          </div>
        </section>
      </a-tab-pane>
    </a-tabs>
  </section>
</template>

<style scoped>
.task-action-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: #fff;
}

.task-action-panel__header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 48px;
  padding: 10px 12px;
  border-bottom: 1px solid #dbe4f0;
}

.task-action-panel__header > div,
.task-action-panel__section-head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.task-action-panel__header h3 {
  margin: 0;
  color: #0f172a;
  font-size: 15px;
}

.task-action-panel__header span,
.task-action-panel__section-head span,
.task-action-panel__application span,
.task-action-panel__application small,
.task-action-panel__empty span,
.task-action-panel__result span,
.task-action-panel__result small {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.task-action-panel__tabs {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
}

.task-action-panel__tabs :deep(.arco-tabs-content) {
  min-height: 0;
  overflow: hidden;
}

.task-action-panel__tabs :deep(.arco-tabs-content-list),
.task-action-panel__tabs :deep(.arco-tabs-pane) {
  height: 100%;
  min-height: 0;
}

.task-action-panel__tabs :deep(.arco-tabs-nav) {
  margin: 0;
  padding: 0 12px;
  border-bottom: 1px solid #dbe4f0;
}

.task-action-panel__tabs :deep(.arco-tabs-tab) {
  padding: 10px 0;
  color: #64748b;
  font-size: 13px;
  font-weight: 800;
}

.task-action-panel__tabs :deep(.arco-tabs-tab-active) {
  color: #1d4ed8;
}

.task-action-panel__tab-body {
  display: grid;
  align-content: start;
  gap: 10px;
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: 12px;
}

.task-action-panel__section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.task-action-panel__section-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.task-action-panel__section-head strong,
.task-action-panel__empty strong,
.task-action-panel__result strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 900;
}

.task-action-panel__application-list {
  display: grid;
  gap: 8px;
  min-height: 0;
}

.task-action-panel__application {
  display: grid;
  gap: 4px;
  width: 100%;
  min-width: 0;
  padding: 10px;
  border: 1px solid #dbe4f0;
  background: #f8fafc;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.task-action-panel__application.is-selected {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 3px 0 0 #2563eb;
}

.task-action-panel__application strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-action-panel__application small {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.task-action-panel__empty,
.task-action-panel__result {
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
}

.task-action-panel__field {
  display: grid;
  gap: 6px;
}

.task-action-panel__field > span {
  color: #475569;
  font-size: 12px;
  font-weight: 800;
}

.task-action-panel__result {
  border-style: solid;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.task-action-panel__result.is-extracted {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.task-action-panel__result.is-needs_review,
.task-action-panel__result.is-located {
  border-color: #fde68a;
  background: #fffbeb;
}

.task-action-panel__result.is-not_found,
.task-action-panel__result.is-error {
  border-color: #fecaca;
  background: #fef2f2;
}

.task-action-panel__candidates,
.task-action-panel__result-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.task-action-panel__candidates span {
  max-width: 100%;
  padding: 2px 6px;
  overflow: hidden;
  background: rgba(37, 99, 235, 0.08);
  color: #1e40af;
  font-size: 11px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
