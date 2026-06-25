<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import ProcessResultCard from './ProcessResultCard.vue'
import type {
  BusinessSkill,
  ObjectOperationResult,
  OperationTarget,
  OperationTargetType,
} from '../types/workbench'

type OperationScope = 'all' | 'fields' | 'structured_objects' | 'records' | 'table_columns'
type OperationIntent = string
type PanelTab = 'config' | 'result'

interface PlanItem {
  id: string
  title: string
  summary: string
  instruction: string
  targetIds: string[]
  skillId: string
  skillVersion: string
  config: Record<string, unknown>
}

interface OperationSubmitPayload {
  skillId: string
  skillVersion: string
  targetIds: string[]
  config: Record<string, unknown>
}

const props = defineProps<{
  target: OperationTarget | null
  targets: OperationTarget[]
  skills: BusinessSkill[]
  result?: ObjectOperationResult | null
  error?: string | null
  processing?: boolean
}>()

const emit = defineEmits<{
  'submit-operation': [OperationSubmitPayload]
  'submit-operation-chain': [OperationSubmitPayload[]]
  'open-skill-test': [{
    skillId: string
    skillVersion: string
    customerScope: 'platform' | 'customer'
    customerId: string | null
    instruction: string
    sampleText: string
  }]
  'draft-skill-from-sample': [{
    kind: 'operation'
    instruction: string
    targetIds: string[]
    expectedOutput: string
    pageNo?: number | null
  }]
  'locate-target': [targetId: string]
  'open-object-list': []
}>()

const draft = reactive<{
  scope: OperationScope
  intent: OperationIntent
  selectedTargetIds: string[]
  selectedTableId: string
  selectedColumns: string[]
  selectedFieldNames: string[]
}>({
  scope: 'all',
  intent: '',
  selectedTargetIds: [],
  selectedTableId: '',
  selectedColumns: [],
  selectedFieldNames: [],
})

const panelRef = ref<HTMLElement | null>(null)
const showDetails = ref(false)
const showGeneratedPrompt = ref(false)
const showTargetEditor = ref(false)
const showAdvancedPlan = ref(false)
const activeTab = ref<PanelTab>('config')
const planItems = ref<PlanItem[]>([])
const skillConfig = reactive<Record<string, any>>({})
const restoredResultConfigKey = ref('')
const skipIntentConfigReset = ref(false)

const rawFieldTargets = computed(() => props.targets.filter((item) => item.type === 'field'))
const rawStructuredObjectTargets = computed(() => props.targets.filter((item) => item.type === 'structured_object'))
const rawTableTargets = computed(() => props.targets.filter((item) => item.type === 'table'))
const rawRecordCollectionTargets = computed(() => props.targets.filter((item) => item.type === 'record_collection'))
const operationTargets = computed(() => {
  const hideDuplicateTables = rawStructuredObjectTargets.value.length > 0
    && rawStructuredObjectTargets.value.length === rawTableTargets.value.length
  const baseTargets = hideDuplicateTables
    ? [...rawFieldTargets.value, ...rawStructuredObjectTargets.value]
    : props.targets
  return rawRecordCollectionTargets.value.length
    ? baseTargets.filter((item) => item.type !== 'record')
    : baseTargets
})
const fieldTargets = computed(() => operationTargets.value.filter((item) => item.type === 'field'))
const structuredObjectTargets = computed(() => operationTargets.value.filter((item) => item.type === 'structured_object'))
const tableTargets = computed(() => operationTargets.value.filter((item) => item.type === 'table'))
const recordTargets = computed(() =>
  props.targets.filter((item) => item.type === 'record_collection' || item.type === 'record' || item.type === 'output'),
)
const primaryTarget = computed(() => {
  const currentTarget = props.target && operationTargets.value.some((item) => item.id === props.target?.id)
    ? props.target
    : null
  return currentScopeTargets.value[0] ?? currentTarget ?? operationTargets.value[0] ?? null
})
const selectedTable = computed(() =>
  tableTargets.value.find((item) => item.id === draft.selectedTableId) ?? tableTargets.value[0] ?? null,
)
const tableColumnOptions = computed(() => uniqueStrings(selectedTable.value?.headers ?? []))
const allFieldNameOptions = computed(() => {
  const values: string[] = []
  for (const target of operationTargets.value) {
    if (target.type === 'field') {
      values.push(target.label)
    } else {
      values.push(...(target.headers ?? []))
      values.push(...collectDataFieldNames(target.data))
    }
  }
  return uniqueStrings(values)
})

const scopeOptions = computed<Array<{ value: OperationScope; label: string; hint: string; disabled: boolean }>>(() => [
  { value: 'all', label: '全部结果', hint: `${operationTargets.value.length} 项`, disabled: !operationTargets.value.length },
  { value: 'fields', label: '指定字段', hint: `${fieldTargets.value.length} 字段`, disabled: !fieldTargets.value.length },
  { value: 'structured_objects', label: '复合表', hint: `${structuredObjectTargets.value.length} 个`, disabled: !structuredObjectTargets.value.length },
  { value: 'records', label: '记录集合', hint: `${recordTargets.value.length} 项`, disabled: !recordTargets.value.length },
  { value: 'table_columns', label: '表格列', hint: `${tableTargets.value.length} 表`, disabled: !tableTargets.value.length },
])

const availableSkills = computed(() =>
  props.skills.filter((skill) =>
    skill.enabled && operationTargets.value.some((target) => skill.targetTypes.includes(target.type)),
  ),
)

const historicalSkill = computed(() => {
  const result = props.result
  if (!result?.skillId || result.executionSource === 'application_step') {
    return null
  }
  return availableSkills.value.find((item) =>
    item.id === result.skillId && (!result.skillVersion || item.version === result.skillVersion),
  ) ?? availableSkills.value.find((item) => item.id === result.skillId) ?? null
})

const intentOptions = computed(() => {
  const prioritizedSkills = [...availableSkills.value].sort((left, right) => {
    const leftPriority = historicalSkill.value && left.id === historicalSkill.value.id && left.version === historicalSkill.value.version ? 0 : 1
    const rightPriority = historicalSkill.value && right.id === historicalSkill.value.id && right.version === historicalSkill.value.version ? 0 : 1
    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority
    }
    return 0
  })
  return prioritizedSkills.map((skill) => ({
    value: skill.id,
    label: skill.name,
    description: skill.promptTemplate || skill.name,
    skill,
  }))
})

const selectedIntent = computed(() =>
  intentOptions.value.find((item) => item.value === draft.intent) ?? intentOptions.value[0] ?? null,
)
const selectedSkill = computed(() => selectedIntent.value?.skill ?? null)
const compatibleOperationTargets = computed(() => {
  const skill = selectedSkill.value
  if (!skill) return operationTargets.value
  return operationTargets.value.filter((target) => skill.targetTypes.includes(target.type))
})
const visibleScopeOptions = computed(() =>
  scopeOptions.value.filter((option) => !option.disabled && isScopeCompatibleWithSkill(option.value, selectedSkill.value)),
)
const selectedSkillTargetCount = computed(() => compatibleOperationTargets.value.length)
const selectedSkillDescription = computed(() =>
  selectedSkill.value
    ? `当前版本 v${selectedSkill.value.version} · ${formatSkillDescription(selectedSkill.value)}`
    : '请选择一个业务处理 Skill。',
)
const selectedSkillConfigEntries = computed(() =>
  selectedSkill.value ? Object.entries(selectedSkill.value.configSchema) : [],
)
const compatibleFieldCount = computed(() => countCompatibleTargetsByType(['field']))
const compatibleStructuredObjectCount = computed(() => countCompatibleTargetsByType(['structured_object']))
const compatibleRecordCount = computed(() => countCompatibleTargetsByType(['record_collection', 'record', 'output']))
const compatibleTableCount = computed(() => countCompatibleTargetsByType(['table']))

const currentScopeTargets = computed(() => {
  if (draft.scope === 'all') {
    return compatibleOperationTargets.value
  }
  if (draft.scope === 'fields') {
    return fieldTargets.value.filter((item) => draft.selectedTargetIds.includes(item.id))
  }
  if (draft.scope === 'structured_objects') {
    return structuredObjectTargets.value.filter((item) => draft.selectedTargetIds.includes(item.id))
  }
  if (draft.scope === 'records') {
    return recordTargets.value.filter((item) => draft.selectedTargetIds.includes(item.id))
  }
  return selectedTable.value ? [selectedTable.value] : []
})

const selectedFieldNames = computed(() => {
  const configuredFields = _configuredFieldNames()
  if (configuredFields.length) {
    return configuredFields
  }
  if (draft.scope === 'table_columns') {
    return uniqueStrings(draft.selectedColumns)
  }
  if (draft.scope === 'fields') {
    const selectedTargets = currentScopeTargets.value.map((item) => item.label)
    const selectedNames = uniqueStrings(draft.selectedFieldNames)
    return selectedNames.length ? selectedNames : selectedTargets
  }
  if (draft.scope === 'structured_objects') {
    return uniqueStrings(draft.selectedFieldNames).filter((name) => allFieldNameOptions.value.includes(name))
  }
  if (draft.scope === 'records') {
    return uniqueStrings(draft.selectedFieldNames).filter((name) => allFieldNameOptions.value.includes(name))
  }
  return uniqueStrings(draft.selectedFieldNames).filter((name) => allFieldNameOptions.value.includes(name))
})

const scopeSummary = computed(() => {
  if (draft.scope === 'all') {
    const parts = [
      `${compatibleOperationTargets.value.length} 项`,
      compatibleFieldCount.value ? `${compatibleFieldCount.value} 字段` : '',
      compatibleStructuredObjectCount.value ? `${compatibleStructuredObjectCount.value} 复合表` : '',
      compatibleRecordCount.value ? `${compatibleRecordCount.value} 记录` : '',
      compatibleTableCount.value ? `${compatibleTableCount.value} 表格` : '',
    ].filter(Boolean)
    return parts.join(' · ')
  }
  if (draft.scope === 'fields') {
    return draft.selectedTargetIds.length ? `${draft.selectedTargetIds.length} 个字段` : '未选择字段'
  }
  if (draft.scope === 'structured_objects') {
    return draft.selectedTargetIds.length ? `${draft.selectedTargetIds.length} 个复合表` : '未选择复合表'
  }
  if (draft.scope === 'records') {
    return draft.selectedTargetIds.length ? `${draft.selectedTargetIds.length} 个记录目标` : '未选择记录'
  }
  const table = selectedTable.value
  if (!table) return '未选择表格'
  const columnText = draft.selectedColumns.length ? `${draft.selectedColumns.length} 列` : '整表'
  return `${table.label} · ${columnText}`
})

const currentInstruction = computed(() => buildInstruction())

const canUseCurrentConfig = computed(() => {
  if (!operationTargets.value.length || props.processing || !selectedSkill.value) return false
  if (!currentScopeTargets.value.length) return false
  if (draft.scope === 'fields' && !draft.selectedTargetIds.length) return false
  if (draft.scope === 'structured_objects' && !draft.selectedTargetIds.length) return false
  if (draft.scope === 'records' && !draft.selectedTargetIds.length) return false
  if (draft.scope === 'table_columns' && !selectedTable.value) return false
  for (const [key, field] of Object.entries(selectedSkill.value.configSchema)) {
    if (!field.required) continue
    if (field.type === 'field_multi_select' && selectedFieldNames.value.length) continue
    const value = skillConfig[key]
    if (Array.isArray(value) && value.length) continue
    if (typeof value === 'string' && value.trim()) continue
    if (typeof value === 'boolean') continue
    return false
  }
  return true
})

const canSubmit = computed(() => canUseCurrentConfig.value || planItems.value.length > 0)

watch(
  () => operationTargets.value.map((item) => item.id).join('|'),
  () => {
    resetDraft()
    planItems.value = []
  },
  { immediate: true },
)

watch(
  () => props.skills.map((skill) => `${skill.id}:${skill.version}`).join('|'),
  () => {
    if (!draft.intent || !availableSkills.value.some((skill) => skill.id === draft.intent)) {
      draft.intent = availableSkills.value[0]?.id ?? ''
    }
    resetSkillConfig()
    applyRecommendedScope()
  },
  { immediate: true },
)

watch(
  () => draft.intent,
  () => {
    if (skipIntentConfigReset.value) {
      skipIntentConfigReset.value = false
      return
    }
    resetSkillConfig()
    applyRecommendedScope()
  },
)

watch(
  () => [
    props.result?.id ?? '',
    props.skills.map((skill) => `${skill.id}:${skill.version}`).join('|'),
    operationTargets.value.map((item) => item.id).join('|'),
  ].join('::'),
  () => {
    restoreConfigFromResult()
  },
  { immediate: true },
)

watch(
  () => [props.result?.id ?? '', historicalSkill.value?.id ?? '', historicalSkill.value?.version ?? ''].join('::'),
  () => {
    if (!historicalSkill.value || !props.result?.id) {
      return
    }
    if (draft.intent === historicalSkill.value.id) {
      return
    }
    skipIntentConfigReset.value = true
    draft.intent = historicalSkill.value.id
  },
  { immediate: true },
)

watch(
  () => props.processing,
  (processing) => {
    if (processing) {
      activeTab.value = 'result'
    }
  },
)

watch(
  () => props.result?.id,
  (resultId) => {
    if (resultId) {
      activeTab.value = 'result'
    }
  },
)

watch(
  () => props.error,
  (error) => {
    if (error) {
      activeTab.value = 'result'
    }
  },
)

function uniqueStrings(values: string[]) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const normalized = String(value ?? '').trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    result.push(normalized)
  }
  return result
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function collectDataFieldNames(data: unknown): string[] {
  const record = asRecord(data)
  const values: string[] = []
  for (const [key, value] of Object.entries(record)) {
    if (key !== 'records' && key !== 'components' && key !== 'rows' && key !== 'table') {
      values.push(key)
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        const child = asRecord(item)
        values.push(...Object.keys(child).filter((childKey) => childKey !== 'components'))
        if (Array.isArray(child.components)) {
          for (const component of child.components) {
            values.push(...Object.keys(asRecord(component)))
          }
        }
      }
    }
  }
  return values
}

function _configuredFieldNames() {
  const key = currentFieldMultiSelectKey()
  const value = key ? skillConfig[key] : null
  return Array.isArray(value)
    ? uniqueStrings(value.map((item) => String(item)))
    : []
}

function resetDraft() {
  draft.scope = operationTargets.value.length ? 'all' : 'fields'
  draft.intent = availableSkills.value[0]?.id ?? ''
  draft.selectedTargetIds = []
  draft.selectedTableId = tableTargets.value[0]?.id ?? ''
  draft.selectedColumns = []
  draft.selectedFieldNames = []
  restoredResultConfigKey.value = ''
  showDetails.value = false
  showGeneratedPrompt.value = false
  showTargetEditor.value = false
  showAdvancedPlan.value = false
  activeTab.value = 'config'
  resetSkillConfig()
  applyRecommendedScope()
}

function chooseScope(scope: OperationScope) {
  const option = scopeOptions.value.find((item) => item.value === scope)
  if (option?.disabled || !isScopeCompatibleWithSkill(scope, selectedSkill.value)) return
  draft.scope = scope
  seedScopeSelection(scope)
}

function seedScopeSelection(scope: OperationScope) {
  if (scope === 'table_columns' && !draft.selectedTableId) {
    draft.selectedTableId = tableTargets.value[0]?.id ?? ''
  }
  if (
    scope === 'structured_objects'
    && !draft.selectedTargetIds.some((id) => structuredObjectTargets.value.some((item) => item.id === id))
  ) {
    draft.selectedTargetIds = structuredObjectTargets.value.map((item) => item.id)
  }
  if (
    scope === 'records'
    && !draft.selectedTargetIds.some((id) => recordTargets.value.some((item) => item.id === id))
  ) {
    draft.selectedTargetIds = recordTargets.value.map((item) => item.id)
  }
  if (
    scope === 'fields'
    && !draft.selectedTargetIds.some((id) => fieldTargets.value.some((item) => item.id === id))
  ) {
    draft.selectedTargetIds = fieldTargets.value.map((item) => item.id)
  }
}

function chooseIntent(intent: OperationIntent) {
  if (draft.intent === intent) return
  draft.intent = intent
}

function applyRecommendedScope() {
  const scope = recommendScopeForSkill(selectedSkill.value)
  if (!scope) return
  draft.scope = scope
  draft.selectedTargetIds = []
  draft.selectedColumns = []
  seedScopeSelection(scope)
}

function restoreConfigFromResult() {
  const result = props.result
  if (!result || !result.skillId || result.executionSource === 'application_step') {
    return
  }
  const restoreKey = [
    result.id,
    result.skillId,
    result.skillVersion ?? '',
    props.skills.length,
    operationTargets.value.length,
  ].join(':')
  if (restoredResultConfigKey.value === restoreKey) {
    return
  }

  const skill = props.skills.find((item) =>
    item.id === result.skillId && (!result.skillVersion || item.version === result.skillVersion),
  ) ?? props.skills.find((item) => item.id === result.skillId)
  if (!skill) {
    return
  }

  if (draft.intent !== skill.id) {
    skipIntentConfigReset.value = true
    draft.intent = skill.id
  }
  resetSkillConfig()
  restoreScopeFromResult(result)
  applyConfigSnapshot(result.configSnapshot)
  restoredResultConfigKey.value = restoreKey
}

function restoreScopeFromResult(result: ObjectOperationResult) {
  const targetIds = uniqueStrings([result.targetId, ...(result.relatedTargetIds ?? [])])
  const selectedTargets = targetIds
    .map((id) => operationTargets.value.find((item) => item.id === id))
    .filter((item): item is OperationTarget => Boolean(item))
  if (!selectedTargets.length) {
    applyRecommendedScope()
    return
  }

  const selectedTargetIds = selectedTargets.map((item) => item.id)
  const selectedTypes = new Set(selectedTargets.map((item) => item.type))
  const coversAllCompatibleTargets = compatibleOperationTargets.value.length > 0
    && compatibleOperationTargets.value.every((item) => selectedTargetIds.includes(item.id))
  if (coversAllCompatibleTargets) {
    draft.scope = 'all'
  } else if ([...selectedTypes].every((type) => type === 'field')) {
    draft.scope = 'fields'
  } else if ([...selectedTypes].every((type) => type === 'structured_object')) {
    draft.scope = 'structured_objects'
  } else if ([...selectedTypes].every((type) => ['record_collection', 'record', 'output'].includes(type))) {
    draft.scope = 'records'
  } else if (selectedTargets.length === 1 && selectedTargets[0].type === 'table') {
    draft.scope = 'table_columns'
  } else {
    draft.scope = 'all'
  }

  draft.selectedTargetIds = selectedTargetIds
  draft.selectedTableId = selectedTargets.find((item) => item.type === 'table')?.id ?? tableTargets.value[0]?.id ?? ''
  draft.selectedColumns = []
  draft.selectedFieldNames = []
  seedScopeSelection(draft.scope)
}

function applyConfigSnapshot(snapshot: Record<string, unknown> | null | undefined) {
  const config = asRecord(snapshot)
  for (const [key, value] of Object.entries(config)) {
    skillConfig[key] = cloneDefaultValue(value)
  }
  const fields = Array.isArray(config.fields)
    ? uniqueStrings(config.fields.map((item) => String(item)))
    : []
  if (fields.length) {
    draft.selectedColumns = [...fields]
    draft.selectedFieldNames = [...fields]
  }
}

function recommendScopeForSkill(skill: BusinessSkill | null): OperationScope | null {
  if (!skill) return null
  const preferredScopes: OperationScope[] = ['all', 'records', 'structured_objects', 'table_columns', 'fields']
  return preferredScopes.find((scope) => hasTargetsForScope(scope) && isScopeCompatibleWithSkill(scope, skill)) ?? null
}

function hasTargetsForScope(scope: OperationScope) {
  if (scope === 'all') return compatibleOperationTargets.value.length > 0
  if (scope === 'fields') return fieldTargets.value.length > 0
  if (scope === 'structured_objects') return structuredObjectTargets.value.length > 0
  if (scope === 'records') return recordTargets.value.length > 0
  return tableTargets.value.length > 0
}

function isScopeCompatibleWithSkill(scope: OperationScope, skill: BusinessSkill | null | undefined) {
  if (!skill) return false
  if (scope === 'all') {
    return operationTargets.value.some((target) => skill.targetTypes.includes(target.type))
  }
  return targetTypesForScope(scope).some((type) => skill.targetTypes.includes(type))
}

function targetTypesForScope(scope: OperationScope): OperationTargetType[] {
  if (scope === 'fields') return ['field']
  if (scope === 'structured_objects') return ['structured_object']
  if (scope === 'records') return ['record_collection', 'record', 'output']
  if (scope === 'table_columns') return ['table']
  return ['field', 'table', 'structured_object', 'record_collection', 'record', 'output']
}

function countCompatibleTargetsByType(types: OperationTargetType[]) {
  return compatibleOperationTargets.value.filter((target) => types.includes(target.type)).length
}

function countSkillTargets(skill: BusinessSkill) {
  return operationTargets.value.filter((target) => skill.targetTypes.includes(target.type)).length
}

function formatSkillDescription(skill: BusinessSkill) {
  if (skill.executor === 'local_transform') return '本地规则转换，适合编码规范化、映射、去空格等处理。'
  if (skill.executor === 'quality_check') return '检查空值、重复、格式和范围异常。'
  if (skill.executor === 'export_data') return '整理当前提取结果，生成可导出的表格或 JSON。'
  if (skill.executor === 'http_connector') return '调用外部接口补全或校验数据。'
  if (skill.executor === 'controlled_python') return '运行受控脚本完成复杂计算。'
  if (skill.executor === 'llm_structured') return '按 Skill 规则调用 AI 处理当前提取结果。'
  return '按 Skill 规则处理当前提取结果。'
}

function formatExecutorLabel(skill: BusinessSkill) {
  if (skill.executor === 'local_transform') return '本地规则'
  if (skill.executor === 'quality_check') return '质量检查'
  if (skill.executor === 'export_data') return '导出'
  if (skill.executor === 'http_connector') return '接口'
  if (skill.executor === 'controlled_python') return '脚本'
  if (skill.executor === 'llm_structured') return 'AI'
  return skill.executor
}

function resetSkillConfig() {
  for (const key of Object.keys(skillConfig)) {
    delete skillConfig[key]
  }
  const schema = selectedSkill.value?.configSchema ?? {}
  for (const [key, field] of Object.entries(schema)) {
    if (field.default !== undefined) {
      skillConfig[key] = cloneDefaultValue(field.default)
    } else if (field.type === 'checkbox') {
      skillConfig[key] = false
    } else if (field.type === 'checkbox_group' || field.type === 'field_multi_select') {
      skillConfig[key] = []
    } else {
      skillConfig[key] = ''
    }
  }
}

function cloneDefaultValue(value: unknown) {
  if (Array.isArray(value)) return [...value]
  if (value && typeof value === 'object') return { ...(value as Record<string, unknown>) }
  return value
}

function selectAllFields() {
  const key = currentFieldMultiSelectKey()
  if (key) {
    skillConfig[key] = [...allFieldNameOptions.value]
  }
  draft.selectedFieldNames = [...allFieldNameOptions.value]
}

function clearSelectedFields() {
  const key = currentFieldMultiSelectKey()
  if (key) {
    skillConfig[key] = []
  }
  draft.selectedFieldNames = []
}

function currentFieldMultiSelectKey() {
  const schema = selectedSkill.value?.configSchema ?? {}
  return Object.entries(schema).find(([, field]) => field.type === 'field_multi_select')?.[0] ?? ''
}

function selectAllColumns() {
  draft.selectedColumns = [...tableColumnOptions.value]
}

function clearSelectedColumns() {
  draft.selectedColumns = []
}

function formatTargetOption(target: OperationTarget) {
  if (
    target.type === 'table'
    || target.type === 'structured_object'
    || target.type === 'record_collection'
    || target.type === 'record'
    || target.type === 'output'
  ) {
    return `${target.label} · ${target.rowCount || '-'} 行 ${target.columnCount || '-'} 列`
  }
  return `${target.label}${target.valueText ? ` · ${target.valueText}` : ''}`
}

function buildScopeLines(targets: OperationTarget[]) {
  const lines = [`处理范围：${scopeSummary.value}。`]
  if (draft.scope === 'all') {
    lines.push(`范围说明：处理当前页全部提取结果，共 ${targets.length} 项。`)
  } else if (draft.scope === 'fields') {
    lines.push(`字段对象：${targets.map((item) => `「${item.label}」`).join('、')}。`)
  } else if (draft.scope === 'structured_objects') {
    lines.push(`复合表对象：${targets.map((item) => `「${item.label}」`).join('、')}。`)
  } else if (draft.scope === 'records') {
    lines.push(`记录对象：${targets.map((item) => `「${item.label}」`).join('、')}。`)
  } else if (selectedTable.value) {
    lines.push(`表格对象：「${selectedTable.value.label}」。`)
    if (draft.selectedColumns.length) {
      lines.push(`指定列：${draft.selectedColumns.map((item) => `「${item}」`).join('、')}。`)
    } else {
      lines.push('指定列：未限制，按整张表处理。')
    }
  }
  return lines
}

function buildInstruction() {
  const targets = currentScopeTargets.value
  if ((!targets.length && !primaryTarget.value) || !selectedSkill.value) return ''

  const lines = buildScopeLines(targets.length ? targets : [primaryTarget.value as OperationTarget])
  lines.push(`Skill：${selectedSkill.value.name}`)
  lines.push(selectedSkill.value.promptTemplate || '按配置处理选定范围。')
  lines.push('配置：')
  lines.push(JSON.stringify(buildCurrentConfig(), null, 2))

  return lines.filter(Boolean).join('\n')
}

function buildCurrentConfig(): Record<string, unknown> {
  const config: Record<string, unknown> = { ...skillConfig }
  if (draft.scope === 'table_columns') {
    config.fields = draft.selectedColumns.length ? [...draft.selectedColumns] : config.fields
  } else if (Array.isArray(config.fields) && !(config.fields as unknown[]).length && selectedFieldNames.value.length) {
    config.fields = [...selectedFieldNames.value]
  }
  return config
}

function cloneSampleData(value: unknown) {
  if (value === null || value === undefined) {
    return {}
  }
  try {
    return JSON.parse(JSON.stringify(value))
  } catch {
    return { text: String(value) }
  }
}

function buildTargetSampleOutput(target: OperationTarget) {
  if (target.type === 'field') {
    return {
      type: 'field_list',
      title: target.label,
      data: {
        fields: [
          {
            label: target.label,
            value: target.valueText,
          },
        ],
      },
    }
  }

  return {
    type: target.type === 'table'
      ? 'data_table'
      : target.type === 'structured_object'
        ? 'kv_record_table'
        : target.type === 'record_collection'
          ? 'record_collection'
          : 'output',
    title: target.label,
    data: cloneSampleData(target.data),
  }
}

function buildSkillTestSampleText() {
  const targets = currentScopeTargets.value.length
    ? currentScopeTargets.value
    : primaryTarget.value
      ? [primaryTarget.value]
      : []
  if (!targets.length) {
    return ''
  }
  return JSON.stringify({
    outputs: targets.map((target) => buildTargetSampleOutput(target)),
  }, null, 2)
}

function makePlanItem(): PlanItem | null {
  if (!canUseCurrentConfig.value || !selectedSkill.value) return null
  const targetIds = currentScopeTargets.value.map((item) => item.id)
  if (!targetIds.length) return null

  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    title: selectedSkill.value.name,
    summary: scopeSummary.value,
    instruction: currentInstruction.value,
    targetIds,
    skillId: selectedSkill.value.id,
    skillVersion: selectedSkill.value.version,
    config: buildCurrentConfig(),
  }
}

function addPlanItem() {
  const item = makePlanItem()
  if (!item) return
  planItems.value = [...planItems.value, item]
}

function removePlanItem(id: string) {
  planItems.value = planItems.value.filter((item) => item.id !== id)
}

function clearPlanItems() {
  planItems.value = []
}

function buildSubmitItems(): OperationSubmitPayload[] {
  const currentItem = makePlanItem()
  const items = planItems.value.length ? planItems.value : currentItem ? [currentItem] : []
  return items
    .map((item) => ({
      skillId: item.skillId,
      skillVersion: item.skillVersion,
      targetIds: uniqueStrings(item.targetIds),
      config: item.config,
    }))
    .filter((item) => item.skillId && item.skillVersion && item.targetIds.length)
}

function submit() {
  const payloads = buildSubmitItems()
  if (!payloads.length) return
  activeTab.value = 'result'
  if (payloads.length === 1) {
    emit('submit-operation', payloads[0])
    return
  }
  emit('submit-operation-chain', payloads)
}

function openSkillTest() {
  if (!selectedSkill.value) {
    return
  }
  const sampleText = buildSkillTestSampleText()
  if (!sampleText) {
    return
  }
  emit('open-skill-test', {
    skillId: selectedSkill.value.id,
    skillVersion: selectedSkill.value.version,
    customerScope: selectedSkill.value.customerScope,
    customerId: selectedSkill.value.customerId ?? null,
    instruction: currentInstruction.value,
    sampleText,
  })
}

function draftSkillFromSample() {
  if (!canUseCurrentConfig.value) {
    return
  }
  emit('draft-skill-from-sample', {
    kind: 'operation',
    instruction: currentInstruction.value,
    targetIds: currentScopeTargets.value.map((item) => item.id),
    expectedOutput: selectedSkill.value
      ? `参考当前「${selectedSkill.value.name}」的输出结构，生成可复用的数据处理能力。`
      : '输出业务人员可复核的处理结果。',
    pageNo: primaryTarget.value?.pageNo ?? null,
  })
}

function locateFirstTarget() {
  const target = currentScopeTargets.value[0] ?? primaryTarget.value
  if (target) {
    emit('locate-target', target.id)
  }
}

async function focusComposer() {
  panelRef.value?.focus()
}

defineExpose({
  focusComposer,
})
</script>

<template>
  <section ref="panelRef" class="object-operation-panel" tabindex="-1">
    <div v-if="!operationTargets.length" class="object-operation-panel__empty">
      <a-empty description="当前页还没有可处理的提取结果。" />
      <p>请先运行当前页结构化解析。</p>
      <a-button size="small" type="primary" @click="emit('open-object-list')">查看提取结果</a-button>
    </div>

    <template v-else>
      <header class="object-operation-panel__target">
        <div class="object-operation-panel__target-main">
          <div class="object-operation-panel__eyebrow">处理范围</div>
          <div class="object-operation-panel__target-title">{{ scopeSummary }}</div>
        </div>
        <div class="object-operation-panel__target-actions">
          <a-button v-if="selectedSkill" size="mini" type="text" @click="openSkillTest">
            去 Skill 试跑
          </a-button>
          <a-button size="mini" type="text" @click="showDetails = !showDetails">
            {{ showDetails ? '收起' : '详情' }}
          </a-button>
          <a-button size="mini" type="text" @click="locateFirstTarget">定位</a-button>
        </div>
      </header>

      <div v-if="showDetails" class="object-operation-panel__detail">
        <div class="object-operation-panel__detail-grid">
          <div><span>字段</span><strong>{{ fieldTargets.length }}</strong></div>
          <div><span>复合表</span><strong>{{ structuredObjectTargets.length }}</strong></div>
          <div><span>记录</span><strong>{{ recordTargets.length }}</strong></div>
          <div><span>表格</span><strong>{{ tableTargets.length }}</strong></div>
          <div><span>总数</span><strong>{{ operationTargets.length }} 项</strong></div>
          <div v-if="primaryTarget"><span>默认来源</span><strong>第 {{ primaryTarget.pageNo }} 页</strong></div>
        </div>
        <div class="object-operation-panel__headers">
          <span>当前页提取结果</span>
          <div>
            <a-tag
              v-for="item in operationTargets.slice(0, 12)"
              :key="item.id"
              size="small"
            >
              {{ item.label }}
            </a-tag>
            <a-tag v-if="operationTargets.length > 12" size="small">+{{ operationTargets.length - 12 }}</a-tag>
          </div>
        </div>
      </div>

      <nav class="object-operation-panel__tabs" aria-label="处理面板">
        <button
          type="button"
          class="object-operation-panel__tab"
          :class="{ 'is-active': activeTab === 'config' }"
          @click="activeTab = 'config'"
        >
          配置处理要求
        </button>
        <button
          type="button"
          class="object-operation-panel__tab"
          :class="{ 'is-active': activeTab === 'result' }"
          @click="activeTab = 'result'"
        >
          <span>处理结果</span>
          <span v-if="processing" class="object-operation-panel__tab-badge">处理中</span>
          <span v-else-if="error" class="object-operation-panel__tab-badge is-error">失败</span>
          <span v-else-if="result" class="object-operation-panel__tab-badge">已生成</span>
        </button>
      </nav>

      <main v-if="activeTab === 'config'" class="object-operation-panel__body">
        <section class="object-operation-panel__section">
          <div class="object-operation-panel__section-title">
            <div>
              <h3>选择处理方式</h3>
              <p>{{ selectedSkillDescription }}</p>
            </div>
          </div>
          <div v-if="intentOptions.length" class="object-operation-panel__skill-list">
            <button
              v-for="option in intentOptions"
              :key="option.value"
              type="button"
              class="object-operation-panel__skill"
              :class="{ 'is-active': draft.intent === option.value }"
              @click="chooseIntent(option.value)"
            >
              <strong>
                <span class="object-operation-panel__skill-name">{{ option.label }}</span>
                <em>v{{ option.skill.version }}</em>
              </strong>
              <span>{{ formatExecutorLabel(option.skill) }}</span>
              <small>{{ countSkillTargets(option.skill) }} 项可处理</small>
            </button>
          </div>
          <div v-else class="object-operation-panel__scope-note">
            当前提取结果没有可用的业务处理 Skill。
          </div>
        </section>

        <section v-if="selectedSkill" class="object-operation-panel__section">
          <div class="object-operation-panel__section-title">
            <div>
              <h3>处理对象</h3>
              <p>系统已根据 Skill 自动选择可处理范围。</p>
            </div>
            <a-button size="mini" type="text" @click="showTargetEditor = !showTargetEditor">
              {{ showTargetEditor ? '收起' : '修改范围' }}
            </a-button>
          </div>
          <div class="object-operation-panel__scope-note">
            <strong>{{ scopeSummary }}</strong>
            <span>当前 Skill 可处理 {{ selectedSkillTargetCount }} 项；需要限定字段或列时再修改范围。</span>
          </div>

          <div v-if="showTargetEditor" class="object-operation-panel__config">
            <div class="object-operation-panel__scope-list">
              <button
                v-for="option in visibleScopeOptions"
                :key="option.value"
                type="button"
                class="object-operation-panel__scope"
                :class="{ 'is-active': draft.scope === option.value }"
                @click="chooseScope(option.value)"
              >
                <strong>{{ option.label }}</strong>
                <span>{{ option.hint }}</span>
              </button>
            </div>

            <div v-if="draft.scope === 'fields'" class="object-operation-panel__control">
              <span>字段（可多选）</span>
              <a-select
                v-model="draft.selectedTargetIds"
                size="small"
                multiple
                allow-clear
                allow-search
                placeholder="请选择字段"
                popup-container="body"
                :max-tag-count="2"
              >
                <a-option v-for="item in fieldTargets" :key="item.id" :value="item.id">
                  {{ formatTargetOption(item) }}
                </a-option>
              </a-select>
            </div>

            <div v-else-if="draft.scope === 'structured_objects'" class="object-operation-panel__control">
              <span>复合表（可多选）</span>
              <a-select
                v-model="draft.selectedTargetIds"
                size="small"
                multiple
                allow-clear
                allow-search
                placeholder="请选择复合表"
                popup-container="body"
                :max-tag-count="2"
              >
                <a-option v-for="item in structuredObjectTargets" :key="item.id" :value="item.id">
                  {{ formatTargetOption(item) }}
                </a-option>
              </a-select>
            </div>

            <div v-else-if="draft.scope === 'records'" class="object-operation-panel__control">
              <span>记录目标（可多选）</span>
              <a-select
                v-model="draft.selectedTargetIds"
                size="small"
                multiple
                allow-clear
                allow-search
                placeholder="请选择记录或记录集合"
                popup-container="body"
                :max-tag-count="2"
              >
                <a-option v-for="item in recordTargets" :key="item.id" :value="item.id">
                  {{ formatTargetOption(item) }}
                </a-option>
              </a-select>
            </div>

            <template v-else-if="draft.scope === 'table_columns'">
              <div class="object-operation-panel__control">
                <span>表格</span>
                <a-select v-model="draft.selectedTableId" size="small" popup-container="body">
                  <a-option v-for="item in tableTargets" :key="item.id" :value="item.id">
                    {{ formatTargetOption(item) }}
                  </a-option>
                </a-select>
              </div>
              <div class="object-operation-panel__control">
                <div class="object-operation-panel__control-head">
                  <span>列（可多选，留空表示整表）</span>
                  <div>
                    <a-button size="mini" type="text" @click="selectAllColumns">全选</a-button>
                    <a-button size="mini" type="text" @click="clearSelectedColumns">清空</a-button>
                  </div>
                </div>
                <a-select
                  v-model="draft.selectedColumns"
                  size="small"
                  multiple
                  allow-clear
                  allow-search
                  placeholder="请选择列"
                  popup-container="body"
                  :max-tag-count="2"
                >
                  <a-option v-for="column in tableColumnOptions" :key="column" :value="column">{{ column }}</a-option>
                </a-select>
              </div>
            </template>
          </div>
        </section>

        <section v-if="selectedSkill" class="object-operation-panel__section">
          <div class="object-operation-panel__section-title">
            <div>
              <h3>处理参数</h3>
              <p>只配置当前 Skill 需要的参数。</p>
            </div>
          </div>
          <section class="object-operation-panel__config">
            <template v-if="selectedSkillConfigEntries.length">
              <div
                v-for="[key, field] in selectedSkillConfigEntries"
                :key="key"
                class="object-operation-panel__control"
              >
                <div class="object-operation-panel__control-head">
                  <span>{{ field.label }}</span>
                  <div v-if="field.type === 'field_multi_select'">
                    <a-button size="mini" type="text" @click="selectAllFields">全选</a-button>
                    <a-button size="mini" type="text" @click="clearSelectedFields">清空</a-button>
                  </div>
                </div>
                <a-select
                  v-if="field.type === 'field_multi_select'"
                  v-model="skillConfig[key]"
                  size="small"
                  multiple
                  allow-clear
                  allow-search
                  :placeholder="field.placeholder || '请选择字段或列'"
                  popup-container="body"
                  :max-tag-count="2"
                >
                  <a-option v-for="fieldName in allFieldNameOptions" :key="fieldName" :value="fieldName">
                    {{ fieldName }}
                  </a-option>
                </a-select>
                <a-select
                  v-else-if="field.type === 'select'"
                  v-model="skillConfig[key]"
                  size="small"
                  :placeholder="field.placeholder || '请选择'"
                  popup-container="body"
                >
                  <a-option v-for="option in field.options" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </a-option>
                </a-select>
                <div v-else-if="field.type === 'checkbox_group'" class="object-operation-panel__check-grid">
                  <a-checkbox-group v-model="skillConfig[key]">
                    <a-checkbox v-for="option in field.options" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </a-checkbox>
                  </a-checkbox-group>
                </div>
                <a-checkbox v-else-if="field.type === 'checkbox'" v-model="skillConfig[key]">
                  {{ field.helpText || field.label }}
                </a-checkbox>
                <a-textarea
                  v-else-if="field.type === 'textarea' || field.type === 'mapping_text'"
                  v-model="skillConfig[key]"
                  :placeholder="field.placeholder"
                  :auto-size="{ minRows: field.type === 'mapping_text' ? 3 : 2, maxRows: 6 }"
                />
                <a-input
                  v-else
                  v-model="skillConfig[key]"
                  size="small"
                  :placeholder="field.placeholder"
                />
                <p v-if="field.helpText" class="object-operation-panel__help">{{ field.helpText }}</p>
              </div>
            </template>
            <div v-else class="object-operation-panel__scope-note">这个 Skill 不需要额外参数。</div>
          </section>
        </section>

        <section class="object-operation-panel__folds">
          <div class="object-operation-panel__fold">
            <div class="object-operation-panel__fold-actions">
              <a-button size="mini" type="text" @click="showGeneratedPrompt = !showGeneratedPrompt">
                {{ showGeneratedPrompt ? '隐藏处理要求' : '查看处理要求' }}
              </a-button>
              <a-button size="mini" type="text" :disabled="!canUseCurrentConfig" @click="draftSkillFromSample">
                制作为可复用能力
              </a-button>
            </div>
            <pre v-if="showGeneratedPrompt" class="object-operation-panel__prompt">{{ currentInstruction }}</pre>
          </div>
        </section>

        <section class="object-operation-panel__plan">
          <div class="object-operation-panel__plan-head">
            <span>处理链</span>
            <div>
              <a-button size="mini" type="text" @click="showAdvancedPlan = !showAdvancedPlan">
                {{ showAdvancedPlan ? '收起' : '展开' }}
              </a-button>
              <a-button size="mini" type="text" :disabled="!canUseCurrentConfig" @click="addPlanItem">加入步骤</a-button>
            </div>
          </div>
          <template v-if="showAdvancedPlan || planItems.length">
            <div v-if="planItems.length" class="object-operation-panel__plan-list">
              <div v-for="(item, index) in planItems" :key="item.id" class="object-operation-panel__plan-item">
                <b>{{ index + 1 }}</b>
                <div>
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.summary }}</span>
                </div>
                <a-button size="mini" type="text" @click="removePlanItem(item.id)">移除</a-button>
              </div>
            </div>
            <p v-else>多页 PDF 或多类结果需要不同处理时，先配置一步，再加入处理链。</p>
            <p v-if="planItems.length">执行时会按顺序运行，并把上一步结果带给下一步。</p>
            <a-button v-if="planItems.length" size="mini" type="text" @click="clearPlanItems">清空处理链</a-button>
          </template>
        </section>
      </main>

      <section v-else class="object-operation-panel__result-tab">
        <div v-if="processing" class="object-operation-panel__result-notice">
          <a-spin :size="16" />
          <span>正在执行{{ selectedSkill ? `「${selectedSkill.name}」` : '业务处理' }}，完成后会显示在这里。</span>
        </div>
        <div v-else-if="error" class="object-operation-panel__result-error">
          <div>
            <strong>处理失败</strong>
            <span>{{ error }}</span>
          </div>
          <a-button size="small" type="secondary" @click="activeTab = 'config'">调整配置</a-button>
        </div>
        <ProcessResultCard v-else-if="result" :result="result" title="处理结果" />
        <div v-else-if="!processing" class="object-operation-panel__result-empty">
          <strong>还没有处理结果</strong>
          <span>配置好处理要求后点击执行，结果会自动切到这里。</span>
          <a-button size="small" type="primary" @click="activeTab = 'config'">去配置</a-button>
        </div>
      </section>

      <footer v-if="activeTab === 'config'" class="object-operation-panel__footer">
        <a-button
          v-if="processing || result"
          size="small"
          type="secondary"
          @click="activeTab = 'result'"
        >
          查看结果
        </a-button>
        <a-button type="primary" size="small" :disabled="!canSubmit" :loading="processing" @click="submit">
          {{ planItems.length ? `执行 ${planItems.length} 步处理链` : selectedSkill ? `执行「${selectedSkill.name}」` : '开始处理' }}
        </a-button>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.object-operation-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  outline: none;
  font-size: 12px;
  line-height: 1.45;
  --panel-border: #d8dee8;
  --panel-muted: #64748b;
  --panel-soft: #f8fafc;
}

.object-operation-panel__empty {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 8px;
  height: 100%;
  padding: 14px;
  border: 1px solid var(--panel-border);
  background: #fff;
  text-align: center;
}

.object-operation-panel__empty p,
.object-operation-panel__plan p {
  margin: 0;
  color: var(--panel-muted);
  font-size: 12px;
  line-height: 1.5;
}

.object-operation-panel__target,
.object-operation-panel__detail,
.object-operation-panel__tabs,
.object-operation-panel__body,
.object-operation-panel__footer,
.object-operation-panel__result-tab {
  border: 1px solid var(--panel-border);
  background: #fff;
}

.object-operation-panel__target {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 10px;
}

.object-operation-panel__target-main {
  min-width: 0;
  flex: 1 1 auto;
}

.object-operation-panel__target-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.object-operation-panel__eyebrow,
.object-operation-panel__detail-grid span,
.object-operation-panel__headers > span {
  color: var(--panel-muted);
  font-size: 11px;
  line-height: 1.35;
}

.object-operation-panel__target-title,
.object-operation-panel__detail-grid strong {
  color: #111827;
  font-size: 12px;
  line-height: 1.45;
  word-break: break-word;
}

.object-operation-panel__target-title {
  margin-top: 2px;
  font-weight: 600;
}

.object-operation-panel__detail {
  max-height: 130px;
  padding: 9px 10px;
  overflow: auto;
}

.object-operation-panel__detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
}

.object-operation-panel__detail-grid div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.object-operation-panel__headers {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.object-operation-panel__headers > div {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.object-operation-panel__tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  padding: 4px;
  gap: 4px;
  flex: 0 0 auto;
}

.object-operation-panel__tab {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 8px;
  border: 0;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.object-operation-panel__tab.is-active {
  background: #2563eb;
  color: #fff;
}

.object-operation-panel__tab-badge {
  max-width: 56px;
  padding: 1px 5px;
  background: rgba(255, 255, 255, 0.2);
  color: inherit;
  font-size: 10px;
  font-weight: 500;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.object-operation-panel__tab-badge.is-error {
  background: rgba(248, 113, 113, 0.18);
}

.object-operation-panel__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: 10px;
  overflow: auto;
}

.object-operation-panel__section {
  display: grid;
  gap: 8px;
}

.object-operation-panel__section + .object-operation-panel__section {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #e5e7eb;
}

.object-operation-panel__section-title {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.object-operation-panel__section-title h3 {
  margin: 0;
  color: #111827;
  font-size: 13px;
  line-height: 1.3;
}

.object-operation-panel__section-title p {
  margin: 2px 0 0;
  color: var(--panel-muted);
  font-size: 11px;
  line-height: 1.45;
}

.object-operation-panel__scope-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.object-operation-panel__scope {
  display: grid;
  gap: 2px;
  padding: 7px 8px;
  border: 1px solid #d8dee8;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.object-operation-panel__scope:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.object-operation-panel__scope.is-active {
  border-color: #2563eb;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #2563eb;
}

.object-operation-panel__scope strong {
  color: #111827;
  font-size: 12px;
}

.object-operation-panel__scope span {
  color: var(--panel-muted);
  font-size: 11px;
}

.object-operation-panel__skill-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.object-operation-panel__skill {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 2px 8px;
  min-height: 58px;
  padding: 8px 9px;
  border: 1px solid #d8dee8;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.object-operation-panel__skill.is-active {
  border-color: #2563eb;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #2563eb;
}

.object-operation-panel__skill strong {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: #111827;
  font-size: 12px;
  line-height: 1.35;
}

.object-operation-panel__skill-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.object-operation-panel__skill strong em {
  flex-shrink: 0;
  color: var(--panel-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 600;
}

.object-operation-panel__skill span,
.object-operation-panel__skill small {
  color: var(--panel-muted);
  font-size: 11px;
  line-height: 1.35;
}

.object-operation-panel__skill span {
  justify-self: end;
  padding: 1px 5px;
  background: #eef4ff;
  color: #2563eb;
}

.object-operation-panel__skill small {
  grid-column: 1 / -1;
}

.object-operation-panel__config,
.object-operation-panel__plan {
  display: grid;
  gap: 9px;
  padding: 10px;
  border: 1px solid #e5e7eb;
  background: var(--panel-soft);
}

.object-operation-panel__control {
  display: grid;
  gap: 5px;
}

.object-operation-panel__control > span {
  color: #334155;
  font-size: 12px;
}

.object-operation-panel__help {
  margin: 0;
  color: var(--panel-muted);
  font-size: 11px;
  line-height: 1.45;
}

.object-operation-panel__scope-note {
  display: grid;
  gap: 2px;
  padding: 7px 9px;
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #334155;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}

.object-operation-panel__scope-note strong {
  color: #111827;
  font-size: 12px;
}

.object-operation-panel__scope-note span {
  color: var(--panel-muted);
  font-size: 11px;
}

.object-operation-panel__control-head,
.object-operation-panel__plan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.object-operation-panel__control-head > span,
.object-operation-panel__plan-head > span {
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.object-operation-panel__control-head > div,
.object-operation-panel__plan-head > div {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.object-operation-panel__check-row,
.object-operation-panel__check-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 7px 12px;
}

.object-operation-panel__check-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.object-operation-panel__folds {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.object-operation-panel__fold {
  display: grid;
  gap: 6px;
}

.object-operation-panel__fold-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.object-operation-panel__prompt {
  max-height: 110px;
  margin: 0;
  padding: 8px 10px;
  overflow: auto;
  border: 1px solid #e5e7eb;
  background: #f8fafc;
  color: #334155;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.object-operation-panel__plan {
  margin-top: 10px;
}

.object-operation-panel__plan-list {
  display: grid;
  gap: 6px;
}

.object-operation-panel__plan-item {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 8px;
  border: 1px solid #e5e7eb;
  background: #fff;
}

.object-operation-panel__plan-item > b {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  background: #eef4ff;
  color: #2563eb;
  font-size: 11px;
  line-height: 1;
}

.object-operation-panel__plan-item div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.object-operation-panel__plan-item strong {
  color: #111827;
  font-size: 12px;
}

.object-operation-panel__plan-item span {
  color: var(--panel-muted);
  font-size: 11px;
}

.object-operation-panel__footer {
  display: flex;
  flex: 0 0 auto;
  justify-content: flex-end;
  gap: 8px;
  padding: 9px 10px;
}

.object-operation-panel__result-tab {
  flex: 1 1 auto;
  min-height: 0;
  padding: 10px;
  overflow: auto;
}

.object-operation-panel__result-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  color: var(--panel-muted);
  font-size: 12px;
  line-height: 1.6;
}

.object-operation-panel__result-empty,
.object-operation-panel__result-error {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 8px;
  min-height: 220px;
  padding: 18px;
  text-align: center;
}

.object-operation-panel__result-empty {
  color: var(--panel-muted);
}

.object-operation-panel__result-empty strong {
  color: #111827;
  font-size: 13px;
}

.object-operation-panel__result-empty span {
  max-width: 240px;
  font-size: 12px;
  line-height: 1.6;
}

.object-operation-panel__result-error {
  color: #7f1d1d;
}

.object-operation-panel__result-error > div {
  display: grid;
  justify-items: center;
  gap: 6px;
  max-width: 320px;
  padding: 12px;
  border: 1px solid #fecaca;
  background: #fff7f7;
}

.object-operation-panel__result-error strong {
  color: #991b1b;
  font-size: 13px;
}

.object-operation-panel__result-error span {
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.object-operation-panel :deep(.arco-btn) {
  border-radius: 2px;
}

.object-operation-panel :deep(.arco-checkbox-label),
.object-operation-panel :deep(.arco-select-view-single),
.object-operation-panel :deep(.arco-textarea) {
  font-size: 12px;
}

.object-operation-panel :deep(.arco-textarea-wrapper) {
  border-radius: 2px;
}

@media (max-width: 960px) {
  .object-operation-panel__detail-grid,
  .object-operation-panel__check-grid,
  .object-operation-panel__scope-list,
  .object-operation-panel__skill-list {
    grid-template-columns: 1fr;
  }
}
</style>
