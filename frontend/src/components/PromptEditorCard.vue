<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { ExtractionSkill, ExtractionSkillRunRequest, WorkbenchPage } from '../types/workbench'

const props = defineProps<{
  visible: boolean
  page: WorkbenchPage | null
  skills: ExtractionSkill[]
  previousConfig?: Omit<ExtractionSkillRunRequest, 'pageNo'> | null
  processing?: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: [payload: Omit<ExtractionSkillRunRequest, 'pageNo'>]
}>()

const selectedSkillKey = ref('')
const skillConfig = reactive<Record<string, any>>({})
const showDetails = ref(false)

const enabledSkills = computed(() => props.skills.filter((skill) => skill.enabled))
const selectedSkill = computed(() =>
  enabledSkills.value.find((skill) => makeSkillKey(skill) === selectedSkillKey.value) ?? enabledSkills.value[0] ?? null,
)
const latestVersionBySkillId = computed(() => {
  const versionMap = new Map<string, string>()
  for (const skill of enabledSkills.value) {
    const current = versionMap.get(skill.id)
    if (!current || compareVersions(skill.version, current) > 0) {
      versionMap.set(skill.id, skill.version)
    }
  }
  return versionMap
})

const canSubmit = computed(() => {
  if (!selectedSkill.value || props.processing) return false
  for (const [key, field] of Object.entries(selectedSkill.value.configSchema)) {
    if (!field.required) continue
    const value = skillConfig[key]
    if (Array.isArray(value) && value.length) continue
    if (typeof value === 'string' && value.trim()) continue
    if (typeof value === 'boolean') continue
    return false
  }
  return true
})

const sourceSummary = computed(() => {
  const page = props.page
  if (!page) return ''
  const tableCount = page.blocks.filter((block) => String(block.type).toLowerCase() === 'table').length
  return `第 ${page.pageNo} 页 · ${page.blocks.length} 个识别块 · ${tableCount} 个表格`
})

function skillCaption(skill: ExtractionSkill) {
  const outputType = String(skill.outputSchema?.type || skill.renderer || '结构化结果')
  const rule = skill.rules.find((item) => String(item || '').trim())
  return rule ? `${outputType} · ${rule}` : outputType
}

function makeSkillKey(skill: ExtractionSkill) {
  return `${skill.id}@@${skill.version}`
}

function compareVersions(left: string, right: string) {
  const leftParts = left.split(/[.-]/).map((part) => Number.parseInt(part, 10))
  const rightParts = right.split(/[.-]/).map((part) => Number.parseInt(part, 10))
  const length = Math.max(leftParts.length, rightParts.length)
  for (let index = 0; index < length; index += 1) {
    const leftPart = Number.isFinite(leftParts[index]) ? leftParts[index] : 0
    const rightPart = Number.isFinite(rightParts[index]) ? rightParts[index] : 0
    if (leftPart !== rightPart) return leftPart > rightPart ? 1 : -1
  }
  return left.localeCompare(right)
}

function isLatestVersion(skill: ExtractionSkill) {
  const latestVersion = latestVersionBySkillId.value.get(skill.id)
  return latestVersion ? skill.version === latestVersion : true
}

watch(
  () => [props.visible, props.skills.map((skill) => `${skill.id}:${skill.version}`).join('|')] as const,
  ([visible]) => {
    if (!visible) return
    const previous = props.previousConfig
    const previousSkill = previous
      ? enabledSkills.value.find((skill) => skill.id === previous.skillId && skill.version === previous.skillVersion)
      : null
    if (previous && previousSkill) {
      selectedSkillKey.value = makeSkillKey(previousSkill)
      resetConfig(previous.config)
      return
    }
    selectedSkillKey.value = enabledSkills.value[0] ? makeSkillKey(enabledSkills.value[0]) : ''
    resetConfig()
  },
  { immediate: true },
)

watch(selectedSkillKey, () => resetConfig())

function resetConfig(overrides?: Record<string, unknown>) {
  for (const key of Object.keys(skillConfig)) {
    delete skillConfig[key]
  }
  const schema = selectedSkill.value?.configSchema ?? {}
  for (const [key, field] of Object.entries(schema)) {
    if (overrides && key in overrides) {
      skillConfig[key] = cloneDefaultValue(overrides[key])
    } else if (field.default !== undefined) {
      skillConfig[key] = cloneDefaultValue(field.default)
    } else if (field.type === 'checkbox') {
      skillConfig[key] = false
    } else if (field.type === 'checkbox_group') {
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

function applyPreviousConfig() {
  const previous = props.previousConfig
  if (!previous) return
  const previousSkill = enabledSkills.value.find((skill) => skill.id === previous.skillId && skill.version === previous.skillVersion)
  if (!previousSkill) return
  selectedSkillKey.value = makeSkillKey(previousSkill)
  resetConfig(previous.config)
}

function submit() {
  const skill = selectedSkill.value
  if (!skill || !canSubmit.value) return
  emit('submit', {
    skillId: skill.id,
    skillVersion: skill.version,
    config: { ...skillConfig },
  })
}
</script>

<template>
  <a-drawer
    :visible="visible"
    :footer="false"
    :mask-closable="!processing"
    width="640px"
    unmount-on-close
    @cancel="emit('close')"
  >
    <template #title>配置结构化解析</template>

    <div v-if="page" class="extraction-skill-drawer">
      <header class="extraction-skill-drawer__hero">
        <div>
          <span>解析来源</span>
          <strong>{{ sourceSummary }}</strong>
        </div>
        <a-tag color="green">{{ page.promptStatus === 'ready' ? '已就绪' : '草稿' }}</a-tag>
      </header>

      <section class="extraction-skill-drawer__section">
        <div class="extraction-skill-drawer__section-head">
          <div>
            <h3>选择解析 Skill</h3>
            <p>Skill 会把当前页识别结果转成可处理的提取结果。</p>
          </div>
          <a-button
            v-if="previousConfig"
            size="small"
            type="text"
            @click="applyPreviousConfig"
          >
            复用上一页配置
          </a-button>
        </div>

        <div v-if="enabledSkills.length" class="extraction-skill-drawer__skills">
          <button
            v-for="skill in enabledSkills"
            :key="makeSkillKey(skill)"
            type="button"
            class="extraction-skill-drawer__skill"
            :class="{ 'is-active': selectedSkill && makeSkillKey(selectedSkill) === makeSkillKey(skill) }"
            @click="selectedSkillKey = makeSkillKey(skill)"
          >
            <div class="extraction-skill-drawer__skill-title">
              <strong>{{ skill.name }}</strong>
              <small>
                v{{ skill.version }}
                <b>{{ isLatestVersion(skill) ? '最新版' : '旧版' }}</b>
              </small>
            </div>
            <span>{{ skill.id }}</span>
            <em>{{ skillCaption(skill) }}</em>
          </button>
        </div>
        <a-empty v-else description="当前客户还没有可用解析 Skill。" />
      </section>

      <section v-if="selectedSkill" class="extraction-skill-drawer__section">
        <div class="extraction-skill-drawer__section-head">
          <div>
            <h3>配置参数</h3>
            <p>{{ selectedSkill.name }} · {{ selectedSkill.id }} · v{{ selectedSkill.version }}</p>
          </div>
          <a-button size="small" type="text" @click="showDetails = !showDetails">
            {{ showDetails ? '收起说明' : '查看说明' }}
          </a-button>
        </div>

        <div v-if="showDetails" class="extraction-skill-drawer__details">
          <div><span>ID</span><strong>{{ selectedSkill.id }}@{{ selectedSkill.version }}</strong></div>
          <div><span>输入</span><strong>{{ selectedSkill.inputBuilder }}</strong></div>
          <div><span>输出</span><strong>{{ selectedSkill.outputSchema?.type || 'custom' }}</strong></div>
          <ul v-if="selectedSkill.rules.length">
            <li v-for="rule in selectedSkill.rules.slice(0, 8)" :key="rule">{{ rule }}</li>
          </ul>
        </div>

        <div v-if="Object.keys(selectedSkill.configSchema).length" class="extraction-skill-drawer__form">
          <label
            v-for="(field, key) in selectedSkill.configSchema"
            :key="key"
            class="extraction-skill-drawer__control"
          >
            <span>{{ field.label }}</span>
            <a-select
              v-if="field.type === 'select'"
              v-model="skillConfig[key]"
              size="small"
              :placeholder="field.placeholder || '请选择'"
              popup-container="body"
            >
              <a-option v-for="option in field.options" :key="option.value" :value="option.value">
                {{ option.label }}
              </a-option>
            </a-select>
            <a-checkbox-group
              v-else-if="field.type === 'checkbox_group'"
              v-model="skillConfig[key]"
            >
              <a-checkbox v-for="option in field.options" :key="option.value" :value="option.value">
                {{ option.label }}
              </a-checkbox>
            </a-checkbox-group>
            <a-checkbox v-else-if="field.type === 'checkbox'" v-model="skillConfig[key]">
              {{ field.helpText || field.label }}
            </a-checkbox>
            <a-textarea
              v-else-if="field.type === 'textarea' || field.type === 'mapping_text'"
              v-model="skillConfig[key]"
              :placeholder="field.placeholder"
              :auto-size="{ minRows: 3, maxRows: 7 }"
            />
            <a-input
              v-else
              v-model="skillConfig[key]"
              size="small"
              :placeholder="field.placeholder"
            />
            <em v-if="field.helpText && field.type !== 'checkbox'">{{ field.helpText }}</em>
          </label>
        </div>
        <div v-else class="extraction-skill-drawer__no-config">这个 Skill 不需要额外配置。</div>
      </section>

      <footer class="extraction-skill-drawer__footer">
        <a-button @click="emit('close')">取消</a-button>
        <a-button type="primary" :disabled="!canSubmit" :loading="processing" @click="submit">
          运行当前页结构化解析
        </a-button>
      </footer>
    </div>

    <a-empty v-else description="请选择一个任务页后再配置解析 Skill。" />
  </a-drawer>
</template>

<style scoped>
.extraction-skill-drawer {
  display: grid;
  gap: 14px;
}

.extraction-skill-drawer__hero,
.extraction-skill-drawer__section,
.extraction-skill-drawer__footer {
  border: 1px solid #d8dee8;
  background: #fff;
}

.extraction-skill-drawer__hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
}

.extraction-skill-drawer__hero div,
.extraction-skill-drawer__section-head > div,
.extraction-skill-drawer__control {
  display: grid;
  gap: 4px;
}

.extraction-skill-drawer__hero span,
.extraction-skill-drawer__section-head p,
.extraction-skill-drawer__control > span,
.extraction-skill-drawer__details span,
.extraction-skill-drawer__control em,
.extraction-skill-drawer__no-config {
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.extraction-skill-drawer__hero strong,
.extraction-skill-drawer__section-head h3,
.extraction-skill-drawer__skill strong,
.extraction-skill-drawer__details strong {
  color: #111827;
  font-size: 13px;
  line-height: 1.45;
}

.extraction-skill-drawer__section {
  display: grid;
  gap: 12px;
  padding: 12px;
}

.extraction-skill-drawer__section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.extraction-skill-drawer__section-head h3,
.extraction-skill-drawer__section-head p {
  margin: 0;
}

.extraction-skill-drawer__skills {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.extraction-skill-drawer__skill {
  display: grid;
  gap: 4px;
  min-height: 64px;
  padding: 10px;
  border: 1px solid #d8dee8;
  background: #f8fafc;
  text-align: left;
  cursor: pointer;
}

.extraction-skill-drawer__skill-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.extraction-skill-drawer__skill-title small {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #1d4ed8;
  font-size: 11px;
  line-height: 1.45;
  font-weight: 700;
  white-space: nowrap;
}

.extraction-skill-drawer__skill-title b {
  padding: 1px 5px;
  background: #e8f1ff;
  color: #2563eb;
  font-size: 10px;
  font-weight: 700;
}

.extraction-skill-drawer__skill span,
.extraction-skill-drawer__skill em {
  color: #64748b;
  font-size: 11px;
}

.extraction-skill-drawer__skill em {
  overflow: hidden;
  max-height: 32px;
  line-height: 1.45;
  font-style: normal;
}

.extraction-skill-drawer__skill.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 3px 0 0 #2563eb;
}

.extraction-skill-drawer__details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 10px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
}

.extraction-skill-drawer__details ul {
  grid-column: 1 / -1;
  margin: 0;
  padding-left: 16px;
  color: #334155;
  font-size: 12px;
  line-height: 1.6;
}

.extraction-skill-drawer__form {
  display: grid;
  gap: 10px;
}

.extraction-skill-drawer__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 12px;
}

.extraction-skill-drawer :deep(.arco-drawer),
.extraction-skill-drawer :deep(.arco-btn),
.extraction-skill-drawer :deep(.arco-input-wrapper),
.extraction-skill-drawer :deep(.arco-textarea-wrapper) {
  border-radius: 0;
}
</style>
