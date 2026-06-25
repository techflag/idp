<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import type { ApplicationAsset } from '../types/workbench'
import type { ApplicationPlanSummary, ProcessingStepDraft } from '../types/applicationWorkshop'
import { t } from '../i18n'

defineProps<{
  applicationName: string
  steps: ProcessingStepDraft[]
  canSave: boolean
  saveLoading?: boolean
  contextLoading?: boolean
  contextError?: string
  savedApplication?: ApplicationAsset | null
  planSummary?: ApplicationPlanSummary | null
}>()

const emit = defineEmits<{
  'update:applicationName': [value: string]
  create: []
  edit: [stepId: string]
  duplicate: [stepId: string]
  remove: [stepId: string]
  addExisting: []
  saveDraft: []
  publish: []
}>()

function formatStepStatus(step: ProcessingStepDraft) {
  if (step.status === 'verified') return t('workshop.verified')
  if (step.skillText) return t('workshop.pendingTrial')
  return t('workshop.pendingGenerate')
}

function statusColor(step: ProcessingStepDraft) {
  if (step.status === 'verified') return 'green'
  if (step.errors.length) return 'orange'
  return 'blue'
}

function formatStepKind(step: ProcessingStepDraft) {
  return step.kind === 'extraction' ? t('applicationSteps.extractData') : t('applicationSteps.processBusiness')
}

function planHasNoTargets(summary?: ApplicationPlanSummary | null) {
  return Boolean(summary && (!summary.selectedCount || !summary.targetCount))
}

function planStatusText(summary?: ApplicationPlanSummary | null) {
  if (planHasNoTargets(summary)) return t('applicationSteps.noExecutableStepLocated')
  if (summary?.status === 'ready') return t('applicationSteps.locationReady')
  if (summary?.status === 'needs_review') return t('applicationSteps.needsReview')
  if (summary?.status === 'blocked') return t('applicationSteps.blocked')
  return t('applicationSteps.notVerified')
}

function planStatusClass(summary?: ApplicationPlanSummary | null) {
  if (planHasNoTargets(summary) || summary?.status === 'blocked') return 'is-blocked'
  if (summary?.status === 'ready') return 'is-ready'
  if (summary?.status === 'needs_review') return 'is-review'
  return ''
}

function planSummaryLine(summary: ApplicationPlanSummary) {
  if (planHasNoTargets(summary)) return t('applicationSteps.noExecutableTarget')
  if (summary.status === 'ready') {
    return t('applicationSteps.planReadySummary', {
      selected: summary.selectedCount,
      total: summary.totalStepCount,
      targets: summary.targetCount,
    })
  }
  if (summary.status === 'needs_review') {
    return t('applicationSteps.planReviewSummary', {
      selected: summary.selectedCount,
      count: summary.reviewCount || summary.warnings,
    })
  }
  return t('applicationSteps.planBlockedSummary', { count: summary.blockedCount || 1 })
}

function planIssueLine(summary: ApplicationPlanSummary) {
  if (summary.firstIssue) return summary.firstIssue
  if (summary.status === 'ready') return summary.requiresConfirmation ? t('applicationSteps.reviewPlanBeforeRun') : t('applicationSteps.planCanRun')
  if (summary.status === 'needs_review') return t('applicationSteps.confirmCandidatesBeforeRun')
  return t('applicationSteps.adjustTemplateOrLocator')
}
</script>

<template>
  <aside class="application-step-manager">
    <header class="application-step-manager__head">
      <div>
        <p>{{ t('applicationSteps.applicationSteps') }}</p>
        <h3>{{ applicationName || savedApplication?.name || t('applicationSteps.sampleApplicationFallback') }}</h3>
      </div>
      <a-tag :color="canSave ? 'green' : 'blue'">{{ t('applicationSteps.stepCount', { count: steps.length }) }}</a-tag>
    </header>

    <section class="application-step-manager__section application-step-manager__section--primary">
      <div class="application-step-manager__section-title">
        <strong>{{ t('applicationSteps.dataTypeList') }}</strong>
        <a-button size="mini" type="text" :loading="contextLoading" @click="emit('addExisting')">
          {{ t('applicationSteps.addVerified') }}
        </a-button>
      </div>
      <a-button type="primary" long @click="emit('create')">{{ t('applicationSteps.addDataType') }}</a-button>

      <div v-if="contextError" class="application-step-manager__notice">
        {{ contextError }}
      </div>

      <div v-if="steps.length" class="application-step-manager__list">
        <article v-for="(step, index) in steps" :key="step.id" class="application-step-manager__item">
          <b>{{ index + 1 }}</b>
          <div class="application-step-manager__item-main">
            <strong>{{ step.dataTypeName || step.skillName }}</strong>
            <span>{{ formatStepKind(step) }} · {{ step.sourceScope }}</span>
            <em>{{ step.expectedOutput }}</em>
          </div>
          <a-tag size="small" :color="statusColor(step)">{{ formatStepStatus(step) }}</a-tag>
          <div class="application-step-manager__item-actions">
            <a-button size="mini" type="text" @click="emit('edit', step.id)">{{ t('common.edit') }}</a-button>
            <a-button size="mini" type="text" @click="emit('duplicate', step.id)">{{ t('common.copy') }}</a-button>
            <a-button size="mini" type="text" status="danger" @click="emit('remove', step.id)">{{ t('common.remove') }}</a-button>
          </div>
        </article>
      </div>
      <a-empty v-else :description="t('applicationSteps.noDataTypes')" />
    </section>

    <p v-if="!canSave" class="application-step-manager__hint">
      {{ t('applicationSteps.saveHint') }}
    </p>

    <section
      v-if="planSummary"
      class="application-step-manager__plan"
      :class="planStatusClass(planSummary)"
    >
      <strong>{{ planStatusText(planSummary) }}</strong>
      <span>{{ planSummaryLine(planSummary) }}</span>
      <em>{{ planIssueLine(planSummary) }}</em>
    </section>
  </aside>
</template>

<style scoped>
.application-step-manager {
  display: grid;
  align-content: start;
  gap: 8px;
  height: 100%;
  overflow: auto;
  padding: 8px;
  background: #f6f8fb;
}

.application-step-manager__head,
.application-step-manager__section {
  border: 1px solid #d7dee8;
  background: #fff;
}

.application-step-manager__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 54px;
  padding: 10px 12px;
}

.application-step-manager__head p {
  margin: 0 0 2px;
  color: #315cf5;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: .08em;
}

.application-step-manager__head h3,
.application-step-manager__section-title strong,
.application-step-manager__item-main strong {
  margin: 0;
  color: #0f172a;
  font-weight: 850;
}

.application-step-manager__head h3 {
  max-width: 260px;
  overflow: hidden;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-step-manager__section {
  display: grid;
  gap: 10px;
  padding: 10px;
}

.application-step-manager__section--primary {
  min-height: 320px;
}

.application-step-manager__section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.application-step-manager__section-title span,
.application-step-manager__field > span,
.application-step-manager__item-main span,
.application-step-manager__item-main em,
.application-step-manager__hint {
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.application-step-manager__list {
  display: grid;
  gap: 8px;
}

.application-step-manager__item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
  min-height: 78px;
  padding: 8px;
  border: 1px solid #dfe6ef;
  background: #fbfdff;
}

.application-step-manager__item > b {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  background: #edf4ff;
  color: #2563eb;
  font-weight: 900;
}

.application-step-manager__item-main {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.application-step-manager__item-main strong,
.application-step-manager__item-main span,
.application-step-manager__item-main em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-step-manager__item-main em {
  font-style: normal;
}

.application-step-manager__item-actions {
  grid-column: 2 / 4;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  border-top: 1px solid #eef2f7;
  padding-top: 6px;
}

.application-step-manager__field {
  display: grid;
  gap: 5px;
}

.application-step-manager__field :deep(.arco-input-wrapper),
.application-step-manager :deep(.arco-btn) {
  border-radius: 3px;
}

.application-step-manager__notice {
  padding: 8px;
  border: 1px solid #fee2e2;
  background: #fff1f2;
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.55;
}

.application-step-manager__plan {
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}

.application-step-manager__plan.is-review {
  border-color: #fed7aa;
  background: #fff7ed;
  color: #9a3412;
}

.application-step-manager__plan.is-blocked {
  border-color: #fecdd3;
  background: #fff1f2;
  color: #be123c;
}

.application-step-manager__plan strong {
  font-size: 13px;
}

.application-step-manager__plan span,
.application-step-manager__plan em {
  color: inherit;
  font-size: 12px;
  font-style: normal;
}

.application-step-manager__publish-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.application-step-manager__hint {
  margin: 0;
}
</style>
