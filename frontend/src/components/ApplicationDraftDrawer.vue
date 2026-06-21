<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type {
  ApplicationDraftContext,
  ApplicationDraftPayload,
  ApplicationSourceRunOption,
  ApplicationStepDefinition,
} from '../types/workbench'

const props = defineProps<{
  visible: boolean
  loading?: boolean
  context: ApplicationDraftContext | null
  defaultAction: 'draft' | 'published'
}>()

const emit = defineEmits<{
  close: []
  submit: [action: 'draft' | 'published', payload: ApplicationDraftPayload]
}>()

const form = reactive({
  scope: 'private' as 'public' | 'private',
  name: '',
  summary: '',
  documentType: '',
  scenario: '',
  coverText: '',
  releaseNotes: '',
  parseOptionId: '',
  operationOptionIds: [] as string[],
  operationOrder: [] as string[],
})

const operationOptionMap = computed(() => {
  const entries: Array<[string, ApplicationSourceRunOption]> = props.context?.operationOptions.map(
    (item): [string, ApplicationSourceRunOption] => [item.id, item],
  ) ?? []
  return new Map(entries)
})

const selectedParseOption = computed(() =>
  props.context?.parseOptions.find((item) => item.id === form.parseOptionId) ?? null,
)

const selectedOperationOptions = computed(() =>
  form.operationOrder
    .map((id) => operationOptionMap.value.get(id) ?? null)
    .filter((item): item is ApplicationSourceRunOption => item !== null)
    .filter((item) => form.operationOptionIds.includes(item.id)),
)

const missingRequirements = computed(() => props.context?.missingRequirements ?? [])

const validationMessage = computed(() => {
  if (!props.context) {
    return '正在读取当前任务上下文。'
  }
  if (missingRequirements.value.length) {
    return missingRequirements.value.join(' ')
  }
  if (!form.name.trim()) {
    return '请填写应用名称。'
  }
  if (!selectedParseOption.value) {
    return '请先选择一个解析来源运行。'
  }
  if (!selectedOperationOptions.value.length) {
    return '请至少选择一个业务处理来源运行。'
  }
  return ''
})

const canSubmit = computed(() => !validationMessage.value)

const stepPreview = computed<ApplicationStepDefinition[]>(() => {
  const parseStep = selectedParseOption.value
  const operationSteps = selectedOperationOptions.value
  const steps: ApplicationStepDefinition[] = []

  if (parseStep) {
    steps.push(toStepDefinition(parseStep, 1))
  }
  operationSteps.forEach((item, index) => {
    steps.push(toStepDefinition(item, index + 2))
  })
  return steps
})

watch(
  () => [props.visible, props.context] as const,
  ([visible, context]) => {
    if (!visible || !context) {
      return
    }
    form.name = context.suggestedName
    form.scope = 'private'
    form.summary = context.suggestedSummary
    form.documentType = context.suggestedDocumentType
    form.scenario = context.suggestedScenario
    form.coverText = context.suggestedCoverText
    form.releaseNotes = context.suggestedReleaseNotes
    form.parseOptionId = context.defaultParseOptionId
    form.operationOptionIds = [...context.defaultOperationOptionIds]
    form.operationOrder = [...context.operationOptions.map((item) => item.id)]
  },
  { immediate: true },
)

watch(
  () => form.operationOptionIds.slice(),
  (ids) => {
    const currentSet = new Set(ids)
    const kept = form.operationOrder.filter((id) => currentSet.has(id))
    const missing = ids.filter((id) => !kept.includes(id))
    form.operationOrder = [...kept, ...missing]
  },
)

function toStepDefinition(option: ApplicationSourceRunOption, stepOrder: number): ApplicationStepDefinition {
  return {
    id: `${option.kind}:${option.runId}`,
    kind: option.kind,
    stepOrder,
    skillId: option.skillId,
    skillVersion: option.skillVersion,
    skillName: option.skillName,
    executor: option.executor || '',
    outputAlias: option.outputAlias,
    sourceSummary: option.summary,
    snapshot: {
      runId: option.runId,
      promptSnapshot: option.promptSnapshot,
      configSnapshot: option.configSnapshot,
      inputMapping: option.inputMapping,
      targetMapping: option.targetMapping || null,
      resultPreview: option.resultPreview,
      sourceTaskId: props.context?.sourceTask.taskId || '',
      sourcePageNo: option.pageNo ?? null,
    },
  }
}

function moveOperation(id: string, delta: -1 | 1) {
  const currentIndex = form.operationOrder.findIndex((item) => item === id)
  if (currentIndex < 0) {
    return
  }
  const targetIndex = currentIndex + delta
  if (targetIndex < 0 || targetIndex >= form.operationOrder.length) {
    return
  }
  const next = [...form.operationOrder]
  const [item] = next.splice(currentIndex, 1)
  next.splice(targetIndex, 0, item)
  form.operationOrder = next
}

function submit(action: 'draft' | 'published') {
  if (!props.context || !canSubmit.value) {
    return
  }
  emit('submit', action, {
    scope: form.scope,
    name: form.name.trim(),
    summary: form.summary.trim(),
    documentType: form.documentType.trim(),
    scenario: form.scenario.trim(),
    coverText: form.coverText.trim(),
    releaseNotes: form.releaseNotes.trim(),
    sourceTask: props.context.sourceTask,
    steps: stepPreview.value,
    finalOutputAlias: stepPreview.value[stepPreview.value.length - 1]?.outputAlias || 'final_output',
  })
}
</script>

<template>
  <a-drawer
    :visible="visible"
    :width="760"
    unmount-on-close
    title="应用工坊：制作文档应用"
    @cancel="emit('close')"
  >
    <div class="application-draft-drawer">
      <section class="application-draft-drawer__workshop">
        <article>
          <b>1</b>
          <span>样例材料</span>
        </article>
        <article>
          <b>2</b>
          <span>生成步骤</span>
        </article>
        <article>
          <b>3</b>
          <span>文档应用</span>
        </article>
        <article>
          <b>4</b>
          <span>样例验证</span>
        </article>
        <article>
          <b>5</b>
          <span>发布复用</span>
        </article>
      </section>

      <a-alert
        v-if="context"
        type="info"
        class="application-draft-drawer__section"
      >
        <template #title>从当前样例沉淀一类文档应用</template>
        <div class="application-draft-drawer__meta-grid">
          <div><span>任务</span><strong>{{ context.sourceTask.taskName }}</strong></div>
          <div><span>任务 ID</span><strong>{{ context.sourceTask.taskId }}</strong></div>
          <div><span>客户</span><strong>{{ context.sourceTask.customerName }}</strong></div>
          <div><span>文档</span><strong>{{ context.sourceTask.documentName }}</strong></div>
        </div>
      </a-alert>

      <a-alert
        v-if="missingRequirements.length"
        type="warning"
        class="application-draft-drawer__section"
      >
        <template #title>当前还不能发布</template>
        <div class="application-draft-drawer__stack">
          <span v-for="item in missingRequirements" :key="item">{{ item }}</span>
        </div>
      </a-alert>

      <section class="application-draft-drawer__section">
        <div class="application-draft-drawer__section-head">
          <div>
            <h3>应用信息</h3>
            <p>一个应用对应一类文档。后续上传同类材料时，系统会先识别内容，再自动选择需要执行的能力。</p>
          </div>
        </div>
        <div class="application-draft-drawer__form-grid">
          <label>
            <span>发布范围</span>
            <a-radio-group v-model="form.scope" type="button">
              <a-radio value="private">客户私有</a-radio>
              <a-radio value="public">平台公共</a-radio>
            </a-radio-group>
            <small>发布状态与发布范围独立控制。公共应用会进入应用市场，私有应用仅限本客户使用。</small>
          </label>
          <label>
            <span>应用名称</span>
            <a-input v-model="form.name" placeholder="请输入应用名称" />
          </label>
          <label>
            <span>适用文档</span>
            <a-input v-model="form.documentType" placeholder="例如：合同 / 发票 / 报告" />
          </label>
          <label class="is-full">
            <span>简介</span>
            <a-textarea v-model="form.summary" :auto-size="{ minRows: 2, maxRows: 4 }" />
          </label>
          <label class="is-full">
            <span>适用场景</span>
            <a-input v-model="form.scenario" placeholder="请输入适用场景" />
          </label>
          <label class="is-full">
            <span>封面文案</span>
            <a-input v-model="form.coverText" placeholder="用于市场列表和详情页的短文案" />
          </label>
          <label class="is-full">
            <span>发布说明</span>
            <a-textarea v-model="form.releaseNotes" :auto-size="{ minRows: 5, maxRows: 8 }" />
          </label>
        </div>
      </section>

      <section class="application-draft-drawer__section">
        <div class="application-draft-drawer__section-head">
          <div>
            <h3>DocParser 解析能力</h3>
            <p>选择样例上已经跑通的解析结果，用于沉淀字段、表格、记录和证据位置。</p>
          </div>
        </div>
        <a-empty v-if="!context?.parseOptions.length" description="当前没有可用的解析 Skill 运行结果。" />
        <a-radio-group v-else v-model="form.parseOptionId" class="application-draft-drawer__choice-list">
          <a-radio v-for="item in context.parseOptions" :key="item.id" :value="item.id">
            <div class="application-draft-drawer__choice-card">
              <strong>{{ item.skillName }} · v{{ item.skillVersion }}</strong>
              <span>{{ item.summary }}</span>
              <small>{{ item.title }} · {{ item.createdAt || '最近结果' }}</small>
            </div>
          </a-radio>
        </a-radio-group>
      </section>

      <section class="application-draft-drawer__section">
        <div class="application-draft-drawer__section-head">
          <div>
            <h3>候选处理能力</h3>
            <p>勾选这类文档可能用到的 Skill。新文档运行时会按内容自动选择，不再固定第几页。</p>
          </div>
        </div>
        <a-empty v-if="!context?.operationOptions.length" description="当前没有可用的业务处理 Skill 运行结果。" />
        <template v-else>
          <a-checkbox-group v-model="form.operationOptionIds" class="application-draft-drawer__choice-list">
            <a-checkbox v-for="item in context.operationOptions" :key="item.id" :value="item.id">
              <div class="application-draft-drawer__choice-card">
                <strong>{{ item.skillName }} · v{{ item.skillVersion }}</strong>
                <span>{{ item.summary }}</span>
                <small>
                  {{ item.targetMapping?.targetLabels.join(' / ') || '当前结果' }} · {{ item.createdAt || '最近结果' }}
                </small>
              </div>
            </a-checkbox>
          </a-checkbox-group>

          <div v-if="selectedOperationOptions.length" class="application-draft-drawer__order-list">
            <article
              v-for="(item, index) in selectedOperationOptions"
              :key="item.id"
              class="application-draft-drawer__order-item"
            >
              <div>
                <span>步骤 {{ index + 2 }}</span>
                <strong>{{ item.skillName }}</strong>
                <small>{{ item.targetMapping?.targetLabels.join(' / ') || item.summary }}</small>
              </div>
              <div class="application-draft-drawer__order-actions">
                <a-button size="mini" @click="moveOperation(item.id, -1)">上移</a-button>
                <a-button size="mini" @click="moveOperation(item.id, 1)">下移</a-button>
              </div>
            </article>
          </div>
        </template>
      </section>

      <section class="application-draft-drawer__section">
        <div class="application-draft-drawer__section-head">
          <div>
            <h3>应用能力预览</h3>
            <p>保存后会固化候选 Skill、配置快照和样例线索；页码只作为样例证据展示。</p>
          </div>
        </div>
        <a-empty v-if="!stepPreview.length" description="选择来源运行后会生成步骤预览。" />
        <div v-else class="application-draft-drawer__step-list">
          <article v-for="item in stepPreview" :key="item.id" class="application-draft-drawer__step-card">
            <div class="application-draft-drawer__step-top">
              <span>步骤 {{ item.stepOrder }}</span>
              <strong>{{ item.skillName }}</strong>
            </div>
            <p>{{ item.sourceSummary }}</p>
            <small>样例运行：{{ item.snapshot.runId }} · 输出：{{ item.outputAlias }}</small>
          </article>
        </div>
      </section>
    </div>

    <template #footer>
      <div class="application-draft-drawer__footer">
        <span v-if="validationMessage" class="application-draft-drawer__error">{{ validationMessage }}</span>
        <div class="application-draft-drawer__footer-actions">
          <a-button @click="emit('close')">取消</a-button>
          <a-button
            :loading="loading"
            :disabled="!canSubmit"
            @click="submit(defaultAction === 'draft' ? 'published' : 'draft')"
          >
            {{ defaultAction === 'draft' ? '直接发布' : '先存草稿' }}
          </a-button>
          <a-button type="primary" :loading="loading" :disabled="!canSubmit" @click="submit(defaultAction)">
            {{ defaultAction === 'draft' ? '保存为应用' : '发布应用' }}
          </a-button>
        </div>
      </div>
    </template>
  </a-drawer>
</template>

<style scoped>
.application-draft-drawer {
  display: grid;
  gap: 12px;
}

.application-draft-drawer__workshop {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
  border: 1px solid #dbe6f4;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
}

.application-draft-drawer__workshop article {
  display: grid;
  gap: 6px;
  align-content: center;
  min-height: 58px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  background: #fff;
}

.application-draft-drawer__workshop b {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  background: #1d4ed8;
  color: #fff;
  font-size: 12px;
}

.application-draft-drawer__workshop span {
  color: #334155;
  font-size: 12px;
  font-weight: 700;
}

.application-draft-drawer__section {
  border: 1px solid #e5e7eb;
  background: #fff;
}

.application-draft-drawer__section-head {
  padding: 12px 14px 0;
}

.application-draft-drawer__section-head h3 {
  margin: 0;
  color: #111827;
  font-size: 14px;
}

.application-draft-drawer__section-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.application-draft-drawer__meta-grid,
.application-draft-drawer__form-grid,
.application-draft-drawer__step-list {
  display: grid;
  gap: 10px;
  padding: 12px 14px 14px;
}

.application-draft-drawer__meta-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.application-draft-drawer__meta-grid div,
.application-draft-drawer__form-grid label,
.application-draft-drawer__choice-card,
.application-draft-drawer__step-card,
.application-draft-drawer__order-item {
  display: grid;
  gap: 4px;
}

.application-draft-drawer__meta-grid span,
.application-draft-drawer__form-grid span,
.application-draft-drawer__choice-card small,
.application-draft-drawer__step-card small,
.application-draft-drawer__order-item span,
.application-draft-drawer__form-grid small,
.application-draft-drawer__order-item small {
  color: #64748b;
  font-size: 12px;
}

.application-draft-drawer__meta-grid strong,
.application-draft-drawer__choice-card strong,
.application-draft-drawer__step-card strong,
.application-draft-drawer__order-item strong {
  color: #111827;
  font-size: 13px;
}

.application-draft-drawer__form-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.application-draft-drawer__form-grid label.is-full {
  grid-column: 1 / -1;
}

.application-draft-drawer__choice-list,
.application-draft-drawer__order-list {
  display: grid;
  gap: 10px;
  padding: 12px 14px 14px;
}

.application-draft-drawer__choice-card,
.application-draft-drawer__step-card,
.application-draft-drawer__order-item {
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  background: #f8fafc;
}

.application-draft-drawer__step-top,
.application-draft-drawer__order-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.application-draft-drawer__step-card p {
  margin: 0;
  color: #334155;
  font-size: 12px;
  line-height: 1.6;
}

.application-draft-drawer__order-actions,
.application-draft-drawer__footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.application-draft-drawer__stack {
  display: grid;
  gap: 6px;
}

.application-draft-drawer__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.application-draft-drawer__error {
  color: #b91c1c;
  font-size: 12px;
}

@media (max-width: 720px) {
  .application-draft-drawer__workshop,
  .application-draft-drawer__meta-grid,
  .application-draft-drawer__form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
