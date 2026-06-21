<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { computed, ref } from 'vue'
import type {
  ApplicationRunDetail,
  ApplicationRunPlanResponse,
  ApplicationRunStepSummary,
} from '../types/workbench'
import {
  formatApplicationPlanCandidate,
  formatApplicationPlanStatus,
  formatApplicationRunStatus,
  formatApplicationStepKind,
  formatApplicationStepStatus,
  getApplicationPlanCandidates,
  getApplicationPlanStepPreview,
  getApplicationPlanStepScope,
  getApplicationStepEvidenceItems,
  getApplicationStepEvidenceMetrics,
  getApplicationStepEvidenceScope,
  getApplicationStepEvidenceWarnings,
  getApplicationStepOutput,
  getApplicationStepScope,
  getApplicationStepTableRiskItems,
  hasApplicationStepDiagnostics,
} from '../utils/applicationRunDisplay'

const props = withDefaults(defineProps<{
  run: ApplicationRunDetail
  plan?: ApplicationRunPlanResponse | null
  loading?: boolean
  disabled?: boolean
}>(), {
  plan: null,
  loading: false,
  disabled: false,
})

const emit = defineEmits<{
  openApplication: []
  rerun: []
  uploadAndRun: []
  confirm: []
  submitReviewFeedback: [payload: {
    stepOrder: number
    note: string
    correctedOutput: Record<string, unknown>
    evidenceRefs: Array<Record<string, unknown>>
    markAsRegression: boolean
  }]
}>()

const runStatusText = computed(() => formatApplicationRunStatus(props.run))
const applicationTitle = computed(() => props.run.applicationName || props.run.applicationId)
const planSelectedCount = computed(() => props.plan?.steps.filter((item) => item.selected).length ?? 0)
const planTargetCount = computed(() => props.plan?.steps.reduce((total, item) => total + (item.targets?.length ?? 0), 0) ?? 0)
const planCandidateCount = computed(() => (
  props.plan?.steps.reduce((total, item) => total + getApplicationPlanCandidates(item).length, 0) ?? 0
))
const planCanConfirm = computed(() => Boolean(props.plan) && props.plan?.status !== 'blocked' && planSelectedCount.value > 0)
const reviewModalVisible = ref(false)
const reviewStepOrder = ref<number | null>(null)
const reviewNote = ref('')
const reviewCorrectedOutputText = ref('{\n  \n}')
const reviewTargetStep = computed(() => (
  props.run.steps.find((item) => item.stepOrder === reviewStepOrder.value) ?? null
))

function defaultCorrectedOutput(step: ApplicationRunStepSummary) {
  const summary = step.outputSummary || {}
  const shapes = Array.isArray(summary.outputShapes) ? summary.outputShapes : []
  return shapes.length ? { outputShapes: shapes } : {}
}

function openReviewFeedback(step: ApplicationRunStepSummary) {
  reviewStepOrder.value = step.stepOrder
  reviewNote.value = ''
  reviewCorrectedOutputText.value = JSON.stringify(defaultCorrectedOutput(step), null, 2)
  reviewModalVisible.value = true
}

function submitReviewFeedback() {
  const step = reviewTargetStep.value
  if (!step) {
    reviewModalVisible.value = false
    return
  }
  let correctedOutput: Record<string, unknown>
  try {
    const parsed = JSON.parse(reviewCorrectedOutputText.value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      Message.warning('修正结果需要是 JSON 对象。')
      return
    }
    correctedOutput = parsed as Record<string, unknown>
  } catch {
    Message.warning('修正结果不是有效 JSON。')
    return
  }
  emit('submitReviewFeedback', {
    stepOrder: step.stepOrder,
    note: reviewNote.value,
    correctedOutput,
    evidenceRefs: getApplicationStepEvidenceItems(step) as Array<Record<string, unknown>>,
    markAsRegression: true,
  })
  reviewModalVisible.value = false
}
</script>

<template>
  <section class="application-run-panel">
    <header class="application-run-panel__head">
      <div>
        <h3>应用运行追踪</h3>
        <span>{{ applicationTitle }}</span>
      </div>
      <div class="application-run-panel__head-actions">
        <a-button size="mini" :disabled="disabled" @click="emit('openApplication')">
          查看应用
        </a-button>
        <a-button
          size="mini"
          :disabled="disabled || loading"
          title="上传新文件会先识别，再运行当前应用。"
          @click="emit('uploadAndRun')"
        >
          上传新文件运行
        </a-button>
        <a-button
          size="mini"
          type="primary"
          :loading="loading"
          :disabled="disabled"
          title="复用当前识别结果，只重新执行应用定位、抽取和后续处理。"
          @click="emit('rerun')"
        >
          重新提取
        </a-button>
      </div>
    </header>

    <div class="application-run-panel__body">
      <div class="application-run-panel__summary">
        <div>
          <strong>{{ runStatusText }}</strong>
          <span>{{ run.completedStepCount }}/{{ run.stepCount }} 个步骤 · 版本 {{ run.version }}</span>
          <small>应用 {{ run.applicationId }}</small>
          <small>运行 {{ run.id }}</small>
        </div>
      </div>

      <section v-if="plan" class="application-run-panel__plan">
        <div class="application-run-panel__plan-header">
          <div>
            <strong>待确认定位计划</strong>
            <span>
              {{ formatApplicationPlanStatus(plan.status) }}
              · {{ planSelectedCount }}/{{ plan.steps.length }} 个步骤
              · {{ planTargetCount }} 个自动命中
              · {{ planCandidateCount }} 个候选
              <template v-if="plan.traceId"> · 日志 {{ plan.traceId }}</template>
            </span>
          </div>
          <a-button
            size="mini"
            type="primary"
            :disabled="!planCanConfirm || loading"
            :loading="loading"
            @click="emit('confirm')"
          >
            确认运行
          </a-button>
        </div>

        <article
          v-for="step in plan.steps"
          :key="step.planStepId"
          class="application-run-panel__plan-step"
          :class="{ 'is-muted': !step.selected }"
        >
          <div class="application-run-panel__plan-step-title">
            <strong :title="step.skillName || step.skillId">{{ step.skillName || step.skillId }}</strong>
            <span>{{ formatApplicationStepKind(step.kind) }} Skill</span>
            <em>{{ step.selected ? '已命中' : '未命中' }}</em>
          </div>
          <p>{{ getApplicationPlanStepScope(step) }}</p>
          <p v-if="getApplicationPlanStepPreview(step)">{{ getApplicationPlanStepPreview(step) }}</p>
          <div
            v-if="getApplicationPlanCandidates(step).length"
            class="application-run-panel__plan-candidates"
          >
            <div
              v-for="candidate in getApplicationPlanCandidates(step).slice(0, 4)"
              :key="candidate.nodeId || candidate.title"
              class="application-run-panel__plan-candidate"
            >
              <strong>{{ candidate.title || candidate.nodeId || '候选节点' }}</strong>
              <span>{{ formatApplicationPlanCandidate(candidate) }}</span>
              <small v-if="candidate.excerpt">{{ candidate.excerpt }}</small>
            </div>
          </div>
        </article>

        <a-alert
          v-if="plan.warnings.length"
          type="warning"
          :content="plan.warnings[0]"
          show-icon
        />
      </section>

      <div class="application-run-panel__steps">
        <article
          v-for="step in run.steps"
          :key="`${run.id}-${step.stepOrder}`"
          class="application-run-panel__step"
        >
          <div class="application-run-panel__step-index">{{ step.stepOrder }}</div>
          <div class="application-run-panel__step-main">
            <div class="application-run-panel__step-title">
              <div class="application-run-panel__step-label">
                <strong :title="step.skillName || step.skillId">{{ step.skillName || step.skillId }}</strong>
                <span>{{ formatApplicationStepKind(step.kind) }} Skill</span>
              </div>
              <div class="application-run-panel__step-actions">
                <a-button
                  size="mini"
                  :disabled="disabled || loading"
                  @click="openReviewFeedback(step)"
                >
                  记录复核样例
                </a-button>
                <span class="application-run-panel__step-status">{{ formatApplicationStepStatus(step.status) }}</span>
              </div>
            </div>
            <p>{{ getApplicationStepScope(step) }}</p>
            <p>{{ getApplicationStepOutput(step) }}</p>
            <details
              v-if="hasApplicationStepDiagnostics(step)"
              class="application-run-panel__diagnostics"
            >
              <summary>
                <span>运行诊断</span>
                <em>{{ getApplicationStepEvidenceScope(step) || '查看证据与耗时' }}</em>
              </summary>
              <div class="application-run-panel__diagnostics-body">
                <p
                  v-if="getApplicationStepEvidenceScope(step)"
                  class="application-run-panel__step-evidence"
                >
                  {{ getApplicationStepEvidenceScope(step) }}
                </p>
                <div
                  v-if="getApplicationStepEvidenceMetrics(step).length"
                  class="application-run-panel__step-metrics"
                >
                  <span
                    v-for="metric in getApplicationStepEvidenceMetrics(step)"
                    :key="metric"
                  >
                    {{ metric }}
                  </span>
                </div>
                <div
                  v-if="getApplicationStepEvidenceItems(step).length"
                  class="application-run-panel__step-evidence-items"
                >
                  <div
                    v-for="item in getApplicationStepEvidenceItems(step)"
                    :key="`${item.pageNo}-${item.title}-${item.excerpt}`"
                  >
                    <strong>{{ item.title || item.sourceType || '证据块' }}</strong>
                    <span>
                      {{ item.pageNo ? `第 ${item.pageNo} 页` : '未标页码' }}
                      <template v-if="item.totalRowCount">
                        · 行 {{ item.selectedRowCount }}/{{ item.totalRowCount }}
                      </template>
                      <template v-if="item.uncertainties.length">
                        · {{ item.uncertainties[0] }}
                      </template>
                    </span>
                    <small v-if="item.excerpt">{{ item.excerpt }}</small>
                  </div>
                </div>
                <div
                  v-if="getApplicationStepEvidenceWarnings(step).length"
                  class="application-run-panel__step-warnings"
                >
                  <span
                    v-for="warning in getApplicationStepEvidenceWarnings(step)"
                    :key="warning"
                  >
                    {{ warning }}
                  </span>
                </div>
                <div
                  v-if="getApplicationStepTableRiskItems(step).length"
                  class="application-run-panel__step-table-risks"
                >
                  <div
                    v-for="risk in getApplicationStepTableRiskItems(step)"
                    :key="`${risk.pageNo}-${risk.title}-${risk.uncertainties.join('-')}`"
                  >
                    <strong>{{ risk.title }}</strong>
                    <span>
                      {{ risk.pageNo ? `第 ${risk.pageNo} 页` : '未标页码' }}
                      <template v-if="risk.rowCount || risk.columnCount">
                        · {{ risk.rowCount || 0 }} 行 · {{ risk.columnCount || 0 }} 列
                      </template>
                      <template v-if="risk.severity === 'critical'"> · 需复核</template>
                    </span>
                    <small v-if="risk.uncertainties.length">{{ risk.uncertainties.join('、') }}</small>
                  </div>
                </div>
              </div>
            </details>
          </div>
        </article>
      </div>

      <a-alert
        v-if="run.errorMessage"
        type="error"
        :content="run.errorMessage"
        show-icon
      />
    </div>

    <a-modal
      v-model:visible="reviewModalVisible"
      title="记录复核样例"
      :width="640"
      simple
      @ok="submitReviewFeedback"
    >
      <div class="application-run-panel__review-form">
        <label>
          <span>复核说明</span>
          <a-textarea
            v-model="reviewNote"
            :auto-size="{ minRows: 2, maxRows: 4 }"
            placeholder="复核依据"
          />
        </label>
        <label>
          <span>修正后的结构化 JSON</span>
          <a-textarea
            v-model="reviewCorrectedOutputText"
            :auto-size="{ minRows: 8, maxRows: 14 }"
          />
        </label>
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.application-run-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  background: #fff;
}

.application-run-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  min-height: 42px;
  padding: 10px 12px;
  border-bottom: 1px solid #dbe4f0;
}

.application-run-panel__head > div:first-child {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.application-run-panel__head h3 {
  margin: 0;
  color: #0f172a;
  font-size: 15px;
}

.application-run-panel__head span {
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__head-actions {
  display: inline-flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 6px;
}

.application-run-panel__body {
  display: grid;
  align-content: start;
  gap: 12px;
  min-height: 0;
  min-width: 0;
  overflow: auto;
  padding: 12px;
  border-top: 1px solid #dbe4f0;
  background: #fff;
}

.application-run-panel__summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid #dbe4f0;
  background: #f8fbff;
}

.application-run-panel__summary > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.application-run-panel__summary strong {
  color: #0f172a;
  font-size: 15px;
}

.application-run-panel__summary span {
  color: #64748b;
  font-size: 12px;
}

.application-run-panel__summary small {
  display: block;
  overflow: hidden;
  color: #94a3b8;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__plan {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}

.application-run-panel__plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.application-run-panel__plan-header > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.application-run-panel__plan-header strong {
  color: #0f172a;
  font-size: 14px;
}

.application-run-panel__plan-header span {
  color: #475569;
  font-size: 12px;
}

.application-run-panel__plan-step {
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid #dbe4f0;
  background: #fff;
}

.application-run-panel__plan-step.is-muted {
  opacity: 0.72;
}

.application-run-panel__plan-step-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.application-run-panel__plan-step-title strong {
  min-width: min(180px, 100%);
  max-width: 100%;
  color: #0f172a;
  font-size: 14px;
  font-weight: 900;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__plan-step p {
  min-width: 0;
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__plan-step-title span {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  height: 22px;
  padding: 0 7px;
  border: 1px solid #dbe4f0;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
}

.application-run-panel__plan-step-title em {
  margin-left: auto;
  color: #2563eb;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  white-space: nowrap;
}

.application-run-panel__plan-candidates {
  display: grid;
  gap: 6px;
  margin-top: 4px;
}

.application-run-panel__plan-candidate {
  display: grid;
  gap: 2px;
  padding: 6px 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.application-run-panel__plan-candidate strong,
.application-run-panel__plan-candidate span,
.application-run-panel__plan-candidate small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__plan-candidate strong {
  color: #0f172a;
  font-size: 12px;
}

.application-run-panel__plan-candidate span,
.application-run-panel__plan-candidate small {
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.application-run-panel__steps {
  display: grid;
  gap: 8px;
}

.application-run-panel__step {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 10px;
  border: 1px solid #dbe4f0;
  background: #fff;
}

.application-run-panel__step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: #eff6ff;
  color: #2563eb;
  font-weight: 900;
}

.application-run-panel__step-main {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.application-run-panel__step-title {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px 10px;
  min-width: 0;
}

.application-run-panel__step-label {
  display: flex;
  flex: 1 1 220px;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.application-run-panel__step-title strong {
  flex: 0 1 auto;
  max-width: min(280px, 100%);
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__step-main p {
  min-width: 0;
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__step-label span {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  height: 22px;
  padding: 0 7px;
  border: 1px solid #dbe4f0;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
}

.application-run-panel__step-actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 100%;
}

.application-run-panel__step-actions .arco-btn {
  flex: 0 0 auto;
}

.application-run-panel__step-main .application-run-panel__step-evidence {
  color: #334155;
  font-weight: 700;
}

.application-run-panel__diagnostics {
  min-width: 0;
  margin-top: 3px;
  border: 1px solid #dbe4f0;
  background: #f8fafc;
}

.application-run-panel__diagnostics summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 6px 8px;
  color: #334155;
  cursor: pointer;
  list-style: none;
}

.application-run-panel__diagnostics summary::-webkit-details-marker {
  display: none;
}

.application-run-panel__diagnostics summary::before {
  content: '▸';
  flex: 0 0 auto;
  color: #64748b;
  font-size: 10px;
}

.application-run-panel__diagnostics[open] summary::before {
  content: '▾';
}

.application-run-panel__diagnostics summary span {
  flex: 0 0 auto;
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
}

.application-run-panel__diagnostics summary em {
  min-width: 0;
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__diagnostics-body {
  display: grid;
  gap: 5px;
  min-width: 0;
  max-height: min(340px, 45vh);
  overflow: auto;
  padding: 0 8px 8px;
}

.application-run-panel__step-metrics,
.application-run-panel__step-warnings {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.application-run-panel__step-evidence-items {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.application-run-panel__step-evidence-items > div,
.application-run-panel__step-table-risks > div {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 5px 6px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.application-run-panel__step-table-risks {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.application-run-panel__step-table-risks > div {
  border-color: #fed7aa;
  background: #fff7ed;
}

.application-run-panel__step-evidence-items strong,
.application-run-panel__step-evidence-items span,
.application-run-panel__step-evidence-items small,
.application-run-panel__step-table-risks strong,
.application-run-panel__step-table-risks span,
.application-run-panel__step-table-risks small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-run-panel__step-evidence-items strong,
.application-run-panel__step-table-risks strong {
  color: #0f172a;
  font-size: 11px;
}

.application-run-panel__step-evidence-items span,
.application-run-panel__step-evidence-items small,
.application-run-panel__step-table-risks span,
.application-run-panel__step-table-risks small {
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.application-run-panel__step-metrics span,
.application-run-panel__step-warnings span {
  display: inline-flex;
  max-width: 100%;
  padding: 2px 6px;
  border: 1px solid #dbe4f0;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  line-height: 1.4;
}

.application-run-panel__step-warnings span {
  border-color: #fed7aa;
  background: #fff7ed;
  color: #9a3412;
}

.application-run-panel__step-status {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  background: #ecfdf5;
  color: #047857;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
}

.application-run-panel__review-form {
  display: grid;
  gap: 12px;
}

.application-run-panel__review-form label {
  display: grid;
  gap: 6px;
}

.application-run-panel__review-form span {
  color: #334155;
  font-size: 12px;
  font-weight: 800;
}
</style>
