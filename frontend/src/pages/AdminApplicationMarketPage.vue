<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ApplicationTemplateSkillEditor from '../components/ApplicationTemplateSkillEditor.vue'
import {
  loadApplicationDetail,
  loadApplications,
  loadPromptRunDetail,
  loadWorkbenchTaskDetail,
  publishApplicationDetail,
  runApplication,
  updateApplicationDetail,
} from '../services/workbenchApi'
import type { ApplicationAsset, ApplicationStepDefinition, DocumentTreeNode, PageResultDetail, WorkbenchTaskDetail } from '../types/workbench'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const detailLoading = ref(false)
const running = ref(false)
const saving = ref(false)
const publishing = ref(false)
const statusChanging = ref(false)
const applications = ref<ApplicationAsset[]>([])
const selectedApplication = ref<ApplicationAsset | null>(null)
const keyword = ref('')
const statusFilter = ref<'all' | 'draft' | 'published' | 'disabled'>('published')
const useDrawerVisible = ref(false)
const uploadInputRef = ref<HTMLInputElement | null>(null)
const useForm = reactive({
  file: null as File | null,
  note: '',
})
const detailEditorVisible = ref(false)
const stepSkillEditorVisible = ref(false)
const stepSkillEditorSaving = ref(false)
const stepSkillEditIndex = ref(-1)
const stepSkillEditMode = ref<'locator' | 'extraction'>('locator')
const sourceTaskLoading = ref(false)
const sourceTaskDetail = ref<WorkbenchTaskDetail | null>(null)
const sourceRunLoading = ref(false)
const sourceRunDetail = ref<PageResultDetail | null>(null)
const stepSkillEditForm = reactive({
  locatorSkillText: '',
  locatorProfileJson: '',
  extractionPrompt: '',
  skillSnapshotJson: '',
})
const detailForm = reactive({
  scope: 'private' as 'public' | 'private',
  name: '',
  summary: '',
  documentType: '',
  scenario: '',
  coverText: '',
  releaseNotes: '',
})

const selectedApplicationId = computed(() => String(route.params.applicationId ?? ''))
const isDetailPage = computed(() => Boolean(selectedApplicationId.value))
const editingStep = computed(() => {
  const current = selectedApplication.value
  if (!current || stepSkillEditIndex.value < 0) return null
  return current.steps[stepSkillEditIndex.value] || null
})
const editingSemanticLocator = computed(() => editingStep.value ? getStepSemanticLocator(editingStep.value) : {})
const editingLocatedModules = computed(() => buildLocatedModuleRows(editingSemanticLocator.value))
const editingCandidateRows = computed(() => buildCandidateRows(editingSemanticLocator.value))
const sourceTreeRows = computed(() => {
  const tree = sourceTaskDetail.value?.documentTree?.tree
  if (!tree) return []
  const rows: Array<{ key: string; title: string; summary: string; page: string; level: number }> = []
  collectTreeRows(tree, [], rows)
  return rows.slice(0, 80)
})
const templateEditorTitle = computed(() => {
  const step = editingStep.value
  if (!step) return '编辑模板资产'
  return `编辑模板资产 · ${step.skillName || `步骤 ${step.stepOrder}`}`
})
const templateEditorSourceSummary = computed(() => {
  const step = editingStep.value
  if (!step) return ''
  const sourceName = sourceTaskDetail.value?.document.fileName || selectedApplication.value?.sourceTask.documentName || ''
  return [
    sourceName,
    step.sourceRunId ? `runId: ${step.sourceRunId}` : '',
    step.snapshot.sourcePageNo ? `样例页码: ${step.snapshot.sourcePageNo}` : '',
  ].filter(Boolean).join(' · ')
})
const sourceRunOutputText = computed(() => {
  const detail = sourceRunDetail.value
  if (!detail) return ''
  if (detail.extractionResult) return JSON.stringify(detail.extractionResult, null, 2)
  if (detail.schemaOutput) return JSON.stringify(detail.schemaOutput, null, 2)
  if (detail.schemaProcessResult) return JSON.stringify(detail.schemaProcessResult, null, 2)
  return detail.outputText || ''
})

const visibleApplications = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  return applications.value.filter((item) => {
    if (statusFilter.value !== 'all' && item.status !== statusFilter.value) {
      return false
    }
    if (!normalizedKeyword) {
      return true
    }
    return [
      item.name,
      item.applicationId,
      item.summary,
      item.documentType,
      item.scenario,
    ].join(' ').toLowerCase().includes(normalizedKeyword)
  })
})

const marketStats = computed(() => {
  const published = applications.value.filter((item) => item.status === 'published').length
  const draft = applications.value.filter((item) => item.status === 'draft').length
  const documentTypes = new Set(applications.value.map((item) => item.documentType).filter(Boolean)).size
  return [
    { label: '已发布', value: String(published) },
    { label: '草稿中', value: String(draft) },
    { label: '文档类型', value: String(documentTypes) },
  ]
})

watch(selectedApplicationId, async (value) => {
  if (!value) {
    selectedApplication.value = null
    return
  }
  await openApplication(value)
}, { immediate: true })

onMounted(async () => {
  await reloadApplications()
})

async function reloadApplications() {
  loading.value = true
  try {
    applications.value = await loadApplications({
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      keyword: keyword.value.trim(),
    })
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '应用列表加载失败。')
    applications.value = []
    selectedApplication.value = null
  } finally {
    loading.value = false
  }
}

async function openApplication(applicationId: string) {
  detailLoading.value = true
  try {
    selectedApplication.value = await loadApplicationDetail(applicationId, {
      version: 'draft',
      includeDraft: true,
    })
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '应用详情加载失败。')
    selectedApplication.value = null
  } finally {
    detailLoading.value = false
  }
}

async function chooseApplication(item: ApplicationAsset) {
  await router.push({ name: 'admin-applications-detail', params: { applicationId: item.applicationId } })
}

async function backToList() {
  await router.push({ name: 'admin-applications' })
}

async function editApplicationTemplate() {
  const current = selectedApplication.value
  if (!current) return
  await router.push({
    name: 'admin-applications-edit',
    params: { applicationId: current.applicationId },
  })
}

function openUseDrawer() {
  useForm.file = null
  useForm.note = ''
  useDrawerVisible.value = true
}

function closeUseDrawer() {
  useDrawerVisible.value = false
}

function openFilePicker() {
  uploadInputRef.value?.click()
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  useForm.file = input.files?.[0] || null
}

async function submitRun() {
  const current = selectedApplication.value
  if (!current) {
    return
  }
  if (!useForm.file) {
    Message.warning('请先选择待处理文件。')
    return
  }

  running.value = true
  try {
    const result = await runApplication(current.applicationId, current.version, {
      customerId: current.sourceTask.customerId,
      file: useForm.file,
      note: useForm.note,
    })
    if (result.taskId && result.runId) {
      await router.push({ name: 'task-detail', params: { taskId: result.taskId } })
      Message.success('已开始运行应用，结果将在任务详情中更新。')
      return
    }
    throw new Error(result.message || '应用运行接口未返回有效运行记录。')
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '应用运行失败。')
  } finally {
    running.value = false
    useDrawerVisible.value = false
  }
}

watch(selectedApplication, (value) => {
  detailForm.name = value?.name || ''
  detailForm.scope = value?.scope || 'private'
  detailForm.summary = value?.summary || ''
  detailForm.documentType = value?.documentType || ''
  detailForm.scenario = value?.scenario || ''
  detailForm.coverText = value?.coverText || ''
  detailForm.releaseNotes = value?.releaseNotes || ''
}, { immediate: true })

async function saveApplicationChanges(options: { silent?: boolean } = {}) {
  const current = selectedApplication.value
  if (!current) {
    return null
  }
  saving.value = true
  try {
    const updated = await updateApplicationDetail(current.applicationId, {
      scope: detailForm.scope,
      name: detailForm.name,
      summary: detailForm.summary,
      documentType: detailForm.documentType,
      scenario: detailForm.scenario,
      coverText: detailForm.coverText,
      releaseNotes: detailForm.releaseNotes,
      steps: current.steps,
    })
    selectedApplication.value = updated
    await reloadApplications()
    if (!options.silent) {
      Message.success('应用详情已保存。')
    }
    return updated
  } catch (error) {
    if (!options.silent) {
      Message.error(error instanceof Error ? error.message : '应用详情保存失败。')
    }
    throw error
  } finally {
    saving.value = false
  }
}

async function handlePublish() {
  const current = selectedApplication.value
  if (!current) {
    return
  }
  publishing.value = true
  try {
    await saveApplicationChanges({ silent: true })
    const published = await publishApplicationDetail(current.applicationId, {
      setAsDefault: true,
    })
    selectedApplication.value = await loadApplicationDetail(published.applicationId, {
      version: 'draft',
      includeDraft: true,
    })
    await reloadApplications()
    Message.success(`应用 ${published.name} 已发布。`)
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '应用发布失败。')
  } finally {
    publishing.value = false
  }
}

async function changeApplicationStatus(status: 'draft' | 'published' | 'disabled') {
  const current = selectedApplication.value
  if (!current) {
    return
  }
  statusChanging.value = true
  try {
    const updated = await updateApplicationDetail(current.applicationId, { status })
    selectedApplication.value = updated
    await reloadApplications()
    Message.success(status === 'disabled' ? '应用已停用。' : status === 'published' ? '应用已恢复发布状态。' : '应用已切换为草稿状态。')
  } catch (error) {
    Message.error(error instanceof Error ? error.message : '应用状态更新失败。')
  } finally {
    statusChanging.value = false
  }
}

function statusLabel(status: ApplicationAsset['status']) {
  if (status === 'draft') return '草稿'
  if (status === 'disabled') return '停用'
  return '已发布'
}

function scopeLabel(application: ApplicationAsset) {
  return application.scope === 'public' ? '平台公共' : '客户私有'
}

function openDetailEditor() {
  detailEditorVisible.value = true
}

function closeDetailEditor() {
  detailEditorVisible.value = false
}

async function saveDetailEditor() {
  await saveApplicationChanges()
  detailEditorVisible.value = false
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function cloneRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? JSON.parse(JSON.stringify(value)) as Record<string, unknown> : {}
}

function asText(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function formatJson(value: unknown) {
  return JSON.stringify(isRecord(value) ? value : {}, null, 2)
}

function parseJsonObject(text: string, label: string): Record<string, unknown> {
  const trimmed = text.trim()
  if (!trimmed) {
    return {}
  }
  const parsed = JSON.parse(trimmed) as unknown
  if (!isRecord(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象。`)
  }
  return parsed
}

function getStepSemanticLocator(step: ApplicationStepDefinition): Record<string, unknown> {
  const dependencyLocator = cloneRecord(step.dependencyRefs?.semanticLocator)
  if (Object.keys(dependencyLocator).length) {
    return dependencyLocator
  }
  return cloneRecord(step.snapshot.semanticLocator)
}

function skillMarkdownFromStep(step: ApplicationStepDefinition) {
  const skillSnapshot = cloneRecord(step.skillSnapshot)
  return String(
    skillSnapshot.skillText
    || skillSnapshot.skillMarkdown
    || skillSnapshot.markdown
    || skillSnapshot.promptTemplate
    || skillSnapshot.prompt
    || step.snapshot.promptSnapshot
    || '',
  )
}

function hasLocatorSkill(step: ApplicationStepDefinition) {
  return Boolean(Object.keys(getStepSemanticLocator(step)).length)
}

function pageTextFromNode(node: DocumentTreeNode) {
  const pages = (node.location || [])
    .map((item) => item.page)
    .filter((item): item is number => typeof item === 'number')
  if (!pages.length) return ''
  const min = Math.min(...pages)
  const max = Math.max(...pages)
  return min === max ? `第 ${min} 页` : `第 ${min}-${max} 页`
}

function collectTreeRows(
  node: DocumentTreeNode,
  path: string[],
  rows: Array<{ key: string; title: string; summary: string; page: string; level: number }>,
) {
  const title = node.title || node.type || '未命名节点'
  const summary = node.content || node.metadata || ''
  if (title !== 'root' || summary) {
    rows.push({
      key: `${path.join('/')}/${rows.length}`,
      title,
      summary,
      page: pageTextFromNode(node),
      level: typeof node.level === 'number' ? node.level : path.length,
    })
  }
  for (const child of node.children || []) {
    collectTreeRows(child, [...path, title], rows)
  }
}

function buildLocatedModuleRows(locator: Record<string, unknown>) {
  const locatedSource = cloneRecord(locator.locatedSource)
  const refs = asList(locatedSource.contentRefs)
  const rows = refs
    .map((item, index) => {
      const record = cloneRecord(item)
      return {
        key: asText(record.nodeId || record.blockId || record.id, `located-${index}`),
        title: asText(record.title, asText(record.label, asText(locatedSource.title, '命中模块'))),
        summary: asText(record.text, asText(record.excerpt, asText(record.summary, ''))),
        page: asText(record.pageRange, asText(record.sourcePage, asText(record.pageNo, ''))),
      }
    })
    .filter((item) => item.title || item.summary)
  if (rows.length) return rows
  if (Object.keys(locatedSource).length) {
    return [{
      key: asText(locatedSource.treeNodeId, 'located-source'),
      title: asText(locatedSource.title, '命中文档树模块'),
      summary: asText(locatedSource.sourceText, asText(locatedSource.summary, '')),
      page: asText(locatedSource.pageRange, ''),
    }]
  }
  return []
}

function buildCandidateRows(locator: Record<string, unknown>) {
  return asList(locator.candidates)
    .map((item, index) => {
      const record = cloneRecord(item)
      return {
        key: asText(record.nodeId || record.id, `candidate-${index}`),
        title: asText(record.title, '候选模块'),
        summary: asText(record.excerpt, asText(record.summary, '')),
        page: asText(record.pageRange, asText(record.pageNo, '')),
      }
    })
    .filter((item) => item.title || item.summary)
}

async function ensureSourceTaskLoaded() {
  const current = selectedApplication.value
  if (!current?.sourceTask.taskId) return
  if (sourceTaskDetail.value?.task.id === current.sourceTask.taskId) return
  sourceTaskLoading.value = true
  try {
    sourceTaskDetail.value = await loadWorkbenchTaskDetail(current.sourceTask.taskId)
  } catch (error) {
    sourceTaskDetail.value = null
    Message.warning(error instanceof Error ? `来源样例加载失败：${error.message}` : '来源样例加载失败。')
  } finally {
    sourceTaskLoading.value = false
  }
}

async function ensureSourceRunLoaded(step: ApplicationStepDefinition) {
  const taskId = step.snapshot.sourceTaskId || selectedApplication.value?.sourceTask.taskId
  const runId = step.sourceRunId || step.snapshot.runId
  if (!taskId || !runId) return
  if (sourceRunDetail.value?.id === runId) return
  sourceRunLoading.value = true
  try {
    sourceRunDetail.value = await loadPromptRunDetail(taskId, runId)
  } catch (error) {
    sourceRunDetail.value = null
    Message.warning(error instanceof Error ? `来源抽取结果加载失败：${error.message}` : '来源抽取结果加载失败。')
  } finally {
    sourceRunLoading.value = false
  }
}

async function openStepSkillEditor(step: ApplicationStepDefinition, mode: 'locator' | 'extraction') {
  const current = selectedApplication.value
  if (!current) {
    return
  }
  const index = current.steps.findIndex((item) => item.id === step.id)
  if (index < 0) {
    return
  }
  stepSkillEditIndex.value = index
  stepSkillEditMode.value = mode
  const semanticLocator = getStepSemanticLocator(step)
  const locatorProfile = isRecord(semanticLocator.locatorProfile) ? semanticLocator.locatorProfile : {}
  stepSkillEditForm.locatorSkillText = String(semanticLocator.locatorSkillText || '')
  stepSkillEditForm.locatorProfileJson = formatJson(locatorProfile)
  const skillSnapshot = cloneRecord(step.skillSnapshot)
  stepSkillEditForm.extractionPrompt = skillMarkdownFromStep(step)
  stepSkillEditForm.skillSnapshotJson = formatJson(skillSnapshot)
  stepSkillEditorVisible.value = true
  await Promise.all([
    ensureSourceTaskLoaded(),
    ensureSourceRunLoaded(step),
  ])
}
void openStepSkillEditor

async function saveStepSkillEdit() {
  const current = selectedApplication.value
  const index = stepSkillEditIndex.value
  if (!current || index < 0 || !current.steps[index]) {
    return
  }
  stepSkillEditorSaving.value = true
  try {
    const step = current.steps[index]
    const locatorProfile = parseJsonObject(stepSkillEditForm.locatorProfileJson, '定位画像')
    const existingLocator = getStepSemanticLocator(step)
    const semanticLocator = {
      ...existingLocator,
      locatorProfile,
      locatorSkillText: stepSkillEditForm.locatorSkillText.trim(),
      source: 'detail_editor',
    }
    const skillSnapshot = parseJsonObject(stepSkillEditForm.skillSnapshotJson, 'Skill 快照')
    const skillText = stepSkillEditForm.extractionPrompt.trim()
    if (skillText) {
      skillSnapshot.skillText = skillText
      skillSnapshot.promptTemplate = skillText
    }
    const nextStep: ApplicationStepDefinition = {
      ...step,
      skillSnapshot,
      snapshot: {
        ...step.snapshot,
        semanticLocator,
        promptSnapshot: skillText,
      },
      dependencyRefs: {
        ...cloneRecord(step.dependencyRefs),
        semanticLocator,
      },
    }

    selectedApplication.value = {
      ...current,
      steps: current.steps.map((item, itemIndex) => itemIndex === index ? nextStep : item),
    }
    await saveApplicationChanges({ silent: true })
    Message.success('模板资产已保存到草稿。')
    stepSkillEditorVisible.value = false
  } catch (error) {
    Message.error(error instanceof Error ? error.message : 'Skill 保存失败。')
  } finally {
    stepSkillEditorSaving.value = false
  }
}
</script>

<template>
  <section class="application-market">
    <template v-if="!isDetailPage">
      <header class="application-market__hero">
        <div class="application-market__hero-main">
          <p class="application-market__eyebrow">文档应用中心</p>
          <h2>文档应用</h2>
          <p>把一类材料的解析、提取和业务处理步骤沉淀下来，发布后同类材料可以自动执行。</p>
        </div>
        <div class="application-market__hero-side">
          <div class="application-market__entry-links">
            <a-button
              type="primary"
              @click="router.push({ name: 'admin-applications-new' })"
            >
              新建应用
            </a-button>
            <a-button @click="router.push({ name: 'admin-extraction-skills' })">基础 Skill·数据解析</a-button>
            <a-button @click="router.push({ name: 'admin-operation-skills' })">基础 Skill·业务处理</a-button>
          </div>
          <div class="application-market__filters">
            <a-input v-model="keyword" placeholder="搜索名称、ID、场景、文档类型" @change="reloadApplications" />
            <a-select v-model="statusFilter" @change="reloadApplications">
              <a-option value="all">全部状态</a-option>
              <a-option value="published">已发布</a-option>
              <a-option value="draft">草稿</a-option>
              <a-option value="disabled">停用</a-option>
            </a-select>
          </div>
        </div>
      </header>

      <section class="application-market__summary">
        <article v-for="item in marketStats" :key="item.label" class="application-market__summary-card">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </section>

      <section class="application-market__catalog">
        <header class="application-market__section-head">
          <div>
            <p class="application-market__eyebrow">应用列表</p>
            <h3>已沉淀的文档应用</h3>
          </div>
          <span>{{ visibleApplications.length }} 个结果</span>
        </header>

        <div v-if="loading" class="application-market__empty">正在加载应用列表。</div>
        <div v-else-if="visibleApplications.length" class="application-market__grid">
          <button
            v-for="item in visibleApplications"
            :key="item.id"
            type="button"
            class="application-market__card"
            @click="chooseApplication(item)"
          >
            <span class="application-market__card-badge">{{ statusLabel(item.status) }}</span>
            <strong>{{ item.name }}</strong>
            <p>{{ item.coverText || item.summary }}</p>
            <div class="application-market__card-meta">
              <span>{{ scopeLabel(item) }}</span>
              <span>{{ item.documentType || '未标注文档类型' }}</span>
              <span>{{ item.stepCount }} 步链路</span>
              <span>{{ item.version }}</span>
            </div>
            <div class="application-market__card-footer">
              <small>{{ item.publishedAt ? `发布于 ${item.publishedAt.slice(0, 10)}` : `更新于 ${item.updatedAt.slice(0, 10)}` }}</small>
              <span>进入详情</span>
            </div>
          </button>
        </div>
        <div v-else class="application-market__empty">当前没有匹配的应用。</div>
      </section>
    </template>

    <template v-else>
      <div v-if="detailLoading" class="application-market__empty">正在读取应用详情。</div>
      <main v-else-if="selectedApplication" class="application-market__detail-page">
        <header class="application-market__detail-topbar">
          <a-button @click="backToList">返回列表</a-button>
          <div class="application-market__detail-topbar-actions">
            <span class="application-market__status">{{ statusLabel(selectedApplication.status) }}</span>
            <span class="application-market__status application-market__status--scope">{{ scopeLabel(selectedApplication) }}</span>
            <a-button @click="openDetailEditor">编辑基础信息</a-button>
            <a-button type="primary" @click="editApplicationTemplate">编辑模板资产</a-button>
            <a-button :loading="saving" @click="saveApplicationChanges()">保存草稿</a-button>
            <a-button
              type="primary"
              :loading="publishing"
              @click="handlePublish"
            >
              发布应用
            </a-button>
            <a-button
              v-if="selectedApplication.status === 'published'"
              :loading="statusChanging"
              @click="changeApplicationStatus('disabled')"
            >
              停用
            </a-button>
            <a-button
              v-else-if="selectedApplication.latestPublishedVersion"
              :loading="statusChanging"
              @click="changeApplicationStatus('published')"
            >
              恢复发布
            </a-button>
            <a-button type="primary" :disabled="selectedApplication.status !== 'published'" @click="openUseDrawer">
              使用应用
            </a-button>
          </div>
        </header>

        <section class="application-market__detail-hero">
          <div>
            <p class="application-market__eyebrow">应用详情</p>
            <h3>{{ selectedApplication.name }}</h3>
            <p>{{ selectedApplication.summary || selectedApplication.coverText || '这个应用会复用已保存的定位 Skill 和抽取 Skill 处理同类文档。' }}</p>
          </div>
          <div class="application-market__detail-id">
            <span>应用 ID</span>
            <strong>{{ selectedApplication.applicationId }}</strong>
          </div>
        </section>

        <section class="application-market__asset-overview">
          <article>
            <span>来源任务</span>
            <strong>{{ selectedApplication.sourceTask.taskName }}</strong>
          </article>
          <article>
            <span>文档类型</span>
            <strong>{{ selectedApplication.documentType || '未填写' }}</strong>
          </article>
          <article>
            <span>发布范围</span>
            <strong>{{ scopeLabel({ ...selectedApplication, scope: detailForm.scope }) }}</strong>
          </article>
          <article>
            <span>默认版本</span>
            <strong>{{ selectedApplication.latestPublishedVersion || selectedApplication.version }}</strong>
          </article>
        </section>

        <section class="application-market__panel application-market__panel--steps">
          <header class="application-market__panel-title">
            <div>
              <h4>模板步骤资产</h4>
              <p>定位 Skill 负责在新文档里找内容范围；抽取 Skill 只基于命中内容生成结构化结果。</p>
            </div>
            <span>{{ selectedApplication.steps.length }} 个步骤</span>
          </header>
          <div class="application-market__steps">
            <article v-for="step in selectedApplication.steps" :key="step.id" class="application-market__step">
              <div class="application-market__step-head">
                <div>
                  <span>步骤 {{ step.stepOrder }} · {{ step.kind === 'operation' ? '业务处理' : '数据提取' }}</span>
                  <strong>{{ step.skillName }}</strong>
                </div>
                <a-button type="primary" size="small" @click="openStepSkillEditor(step, step.kind === 'extraction' ? 'locator' : 'extraction')">
                  编辑模板资产
                </a-button>
              </div>
              <p>{{ step.sourceSummary }}</p>
              <div class="application-market__step-assets">
                <button
                  v-if="step.kind === 'extraction'"
                  type="button"
                  class="application-market__step-asset"
                  @click="openStepSkillEditor(step, 'locator')"
                >
                  <span>定位 Skill</span>
                  <strong>{{ hasLocatorSkill(step) ? '已保存' : '缺少定位资产' }}</strong>
                </button>
                <button
                  type="button"
                  class="application-market__step-asset"
                  @click="openStepSkillEditor(step, 'extraction')"
                >
                  <span>{{ step.kind === 'operation' ? '处理 Skill' : '抽取 Skill' }}</span>
                  <strong>{{ step.outputSummary?.summary || step.snapshot.resultPreview || '已保存' }}</strong>
                </button>
              </div>
              <small>runId: {{ step.snapshot.runId }} · alias: {{ step.outputAlias }}</small>
            </article>
          </div>
        </section>

        <section v-if="selectedApplication.versions?.length" class="application-market__panel">
          <header class="application-market__panel-title">
            <div>
              <h4>已发布版本</h4>
              <p>保存草稿后需重新发布，新的定位和抽取资产才会用于后续上传文件。</p>
            </div>
          </header>
          <div class="application-market__versions">
            <article
              v-for="version in selectedApplication.versions"
              :key="version.version"
              class="application-market__version"
            >
              <div class="application-market__step-head">
                <strong>{{ version.version }}</strong>
                <span>{{ version.isDefault ? '默认版本' : statusLabel(version.status) }}</span>
              </div>
              <small>
                {{ version.publishedAt ? `发布于 ${version.publishedAt.slice(0, 10)}` : `更新于 ${version.updatedAt.slice(0, 10)}` }}
              </small>
            </article>
          </div>
        </section>
      </main>
      <div v-else class="application-market__empty">
        <p>没有找到这个应用。</p>
        <a-button type="primary" @click="backToList">返回应用列表</a-button>
      </div>
    </template>

    <a-drawer
      :visible="useDrawerVisible"
      :width="520"
      title="使用应用"
      @cancel="closeUseDrawer"
    >
      <div class="application-market__use-form">
        <a-alert type="info">
          <template #title>当前应用</template>
          {{ selectedApplication?.name }} · {{ selectedApplication?.documentType }}
        </a-alert>
        <label>
          <span>待处理文件</span>
          <div class="application-market__upload-row">
            <a-button @click="openFilePicker">选择文件</a-button>
            <strong>{{ useForm.file?.name || '未选择文件' }}</strong>
          </div>
          <input ref="uploadInputRef" class="application-market__upload-input" type="file" @change="handleFileChange" />
        </label>
        <label>
          <span>补充说明</span>
          <a-textarea v-model="useForm.note" :auto-size="{ minRows: 3, maxRows: 6 }" />
        </label>
      </div>
      <template #footer>
        <div class="application-market__drawer-footer">
          <a-button @click="closeUseDrawer">取消</a-button>
          <a-button type="primary" :loading="running" @click="submitRun">上传并执行</a-button>
        </div>
      </template>
    </a-drawer>

    <a-drawer
      :visible="detailEditorVisible"
      :width="640"
      title="编辑应用基础信息"
      @cancel="closeDetailEditor"
    >
      <div class="application-market__use-form">
        <label>
          <span>应用标题</span>
          <a-input v-model="detailForm.name" placeholder="请输入应用标题" />
        </label>
        <label>
          <span>发布范围</span>
          <a-select v-model="detailForm.scope">
            <a-option value="private">客户私有</a-option>
            <a-option value="public">平台公共</a-option>
          </a-select>
        </label>
        <label>
          <span>文档类型</span>
          <a-input v-model="detailForm.documentType" placeholder="例如：采购订单、合同、发票" />
        </label>
        <label>
          <span>应用简介</span>
          <a-textarea v-model="detailForm.summary" :auto-size="{ minRows: 3, maxRows: 6 }" />
        </label>
        <label>
          <span>适用场景</span>
          <a-textarea v-model="detailForm.scenario" :auto-size="{ minRows: 3, maxRows: 6 }" />
        </label>
        <label>
          <span>封面文案</span>
          <a-textarea v-model="detailForm.coverText" :auto-size="{ minRows: 3, maxRows: 6 }" />
        </label>
        <label>
          <span>发布说明</span>
          <a-textarea v-model="detailForm.releaseNotes" :auto-size="{ minRows: 4, maxRows: 8 }" />
        </label>
      </div>
      <template #footer>
        <div class="application-market__drawer-footer">
          <a-button @click="closeDetailEditor">取消</a-button>
          <a-button type="primary" :loading="saving" @click="saveDetailEditor">保存草稿</a-button>
        </div>
      </template>
    </a-drawer>

    <ApplicationTemplateSkillEditor
      v-model:visible="stepSkillEditorVisible"
      v-model:mode="stepSkillEditMode"
      v-model:locator-skill-text="stepSkillEditForm.locatorSkillText"
      v-model:locator-profile-json="stepSkillEditForm.locatorProfileJson"
      v-model:extraction-prompt="stepSkillEditForm.extractionPrompt"
      v-model:skill-snapshot-json="stepSkillEditForm.skillSnapshotJson"
      :saving="stepSkillEditorSaving"
      :modal-title="templateEditorTitle"
      :source-summary="templateEditorSourceSummary"
      :editing-step="editingStep"
      :located-modules="editingLocatedModules"
      :candidate-rows="editingCandidateRows"
      :source-tree-rows="sourceTreeRows"
      :source-task-loading="sourceTaskLoading"
      :source-run-loading="sourceRunLoading"
      :source-run-output-text="sourceRunOutputText"
      @save="saveStepSkillEdit"
    />
  </section>
</template>

<style scoped>
.application-market {
  display: grid;
  gap: 10px;
}

.application-market__hero,
.application-market__summary-card,
.application-market__catalog,
.application-market__detail-page,
.application-market__panel {
  border: 1px solid #d7dde5;
  background: #fff;
}

.application-market__hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(340px, 0.8fr);
  gap: 16px;
  padding: 14px 16px;
}

.application-market__hero-main {
  display: grid;
  gap: 12px;
}

.application-market__eyebrow {
  margin: 0 0 6px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.application-market__hero h2,
.application-market__section-head h3,
.application-market__detail-hero h3,
.application-market__panel h4 {
  margin: 0;
  color: #111827;
}

.application-market__hero h2 {
  font-size: 28px;
  line-height: 1.15;
}

.application-market__hero p,
.application-market__detail-hero p,
.application-market__panel p,
.application-market__card p {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
}

.application-market__hero-side,
.application-market__entry-links {
  display: grid;
  gap: 10px;
}

.application-market__filters {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 140px;
  gap: 10px;
}

.application-market__summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.application-market__summary-card {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
}

.application-market__summary-card span,
.application-market__section-head span,
.application-market__card-meta,
.application-market__card-footer small,
.application-market__detail-grid span,
.application-market__step span,
.application-market__step small,
.application-market__status,
.application-market__detail-id span {
  color: #64748b;
  font-size: 12px;
}

.application-market__summary-card strong {
  color: #111827;
  font-size: 18px;
  font-weight: 700;
}

.application-market__catalog,
.application-market__detail-page {
  padding: 14px 16px;
}

.application-market__section-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.application-market__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.application-market__card {
  display: grid;
  gap: 8px;
  min-height: 152px;
  padding: 14px;
  border: 1px solid #d7dde5;
  background: #fbfcfe;
  text-align: left;
  cursor: pointer;
  transition: border-color 140ms ease, background 140ms ease;
}

.application-market__card:hover {
  border-color: #2563eb;
  background: #f8fbff;
}

.application-market__card-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  min-height: 22px;
  padding: 0 7px;
  border: 1px solid #d7dde5;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
}

.application-market__card strong,
.application-market__detail-grid strong,
.application-market__step strong,
.application-market__upload-row strong,
.application-market__detail-id strong {
  color: #111827;
  font-weight: 700;
}

.application-market__card-meta,
.application-market__card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.application-market__card-footer span {
  color: #165dff;
  font-size: 12px;
  font-weight: 700;
}

.application-market__detail-page {
  display: grid;
  gap: 12px;
}

.application-market__detail-topbar,
.application-market__detail-topbar-actions,
.application-market__detail-hero,
.application-market__step-head,
.application-market__upload-row,
.application-market__drawer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.application-market__detail-hero {
  align-items: flex-start;
  padding-bottom: 8px;
  border-bottom: 1px solid #d7dde5;
}

.application-market__detail-id {
  display: grid;
  gap: 6px;
  min-width: 220px;
  padding: 10px 12px;
  border: 1px solid #d7dde5;
  background: #f8fafc;
}

.application-market__status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid #d7dde5;
  background: #f8fafc;
}

.application-market__detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.application-market__asset-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.application-market__asset-overview article {
  display: grid;
  gap: 5px;
  padding: 12px 14px;
  border: 1px solid #d7dde5;
  background: #fbfcfe;
}

.application-market__asset-overview span,
.application-market__panel-title span {
  color: #64748b;
  font-size: 12px;
}

.application-market__asset-overview strong {
  min-width: 0;
  overflow: hidden;
  color: #111827;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-market__detail-grid article,
.application-market__step {
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #f8fafc;
}

.application-market__steps,
.application-market__versions,
.application-market__use-form {
  display: grid;
  gap: 10px;
}

.application-market__panel-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.application-market__panel-title p {
  margin-top: 4px;
}

.application-market__panel--steps {
  padding: 16px;
}

.application-market__step-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.application-market__step-head > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.application-market__step-assets {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.application-market__step-asset {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #d7dde5;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.application-market__step-asset:hover {
  border-color: #2563eb;
  background: #f8fbff;
}

.application-market__step-asset span {
  color: #165dff;
  font-size: 12px;
  font-weight: 800;
}

.application-market__step-asset strong {
  overflow: hidden;
  color: #111827;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-market__form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.application-market__form-grid label,
.application-market__version {
  display: grid;
  gap: 8px;
}

.application-market__form-grid label.is-full {
  grid-column: 1 / -1;
}

.application-market__form-grid label span {
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.application-market__panel {
  padding: 14px 16px;
}

.application-market__panel pre {
  margin: 8px 0 0;
  white-space: pre-wrap;
  color: #334155;
  font-size: 12px;
  line-height: 1.7;
}

.application-market__empty {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 240px;
  border: 1px dashed #d7dde5;
  background: #fff;
  color: #64748b;
  font-size: 13px;
}

.application-market__use-form label {
  display: grid;
  gap: 8px;
}

.application-market__use-form label span,
.application-market__version small {
  color: #334155;
  font-size: 12px;
}

.application-market__use-form label span {
  font-weight: 600;
}

.application-market__version {
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #f8fafc;
}

.application-market__upload-input {
  display: none;
}

@media (max-width: 1180px) {
  .application-market__hero,
  .application-market__grid,
  .application-market__detail-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 768px) {
  .application-market__hero,
  .application-market__summary,
  .application-market__grid,
  .application-market__detail-grid,
  .application-market__form-grid,
  .application-market__filters {
    grid-template-columns: 1fr;
  }

  .application-market__detail-hero,
  .application-market__detail-topbar,
  .application-market__detail-topbar-actions,
  .application-market__card-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
