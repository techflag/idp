<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { computed } from 'vue'
import type { ApplicationStepDefinition } from '../types/workbench'
import SkillMarkdownEditor from './SkillMarkdownEditor.vue'

export type ApplicationTemplateSkillEditMode = 'locator' | 'extraction'

export type ApplicationTemplateModuleRow = {
  key: string
  title: string
  summary: string
  page: string
}

export type ApplicationTemplateTreeRow = ApplicationTemplateModuleRow & {
  level: number
}

const props = withDefaults(defineProps<{
  visible: boolean
  mode: ApplicationTemplateSkillEditMode
  saving?: boolean
  modalTitle: string
  sourceSummary: string
  editingStep: ApplicationStepDefinition | null
  locatedModules: ApplicationTemplateModuleRow[]
  candidateRows: ApplicationTemplateModuleRow[]
  sourceTreeRows: ApplicationTemplateTreeRow[]
  sourceTaskLoading?: boolean
  sourceRunLoading?: boolean
  sourceRunOutputText: string
  locatorSkillText: string
  locatorProfileJson: string
  extractionPrompt: string
  skillSnapshotJson: string
}>(), {
  saving: false,
  sourceTaskLoading: false,
  sourceRunLoading: false,
})

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'update:mode': [value: ApplicationTemplateSkillEditMode]
  'update:locatorSkillText': [value: string]
  'update:locatorProfileJson': [value: string]
  'update:extractionPrompt': [value: string]
  'update:skillSnapshotJson': [value: string]
  save: []
}>()

const isOperationStep = computed(() => props.editingStep?.kind === 'operation')
const fallbackOutputText = computed(() => JSON.stringify(props.editingStep?.outputSummary || {}, null, 2))

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="'min(1420px, calc(100vw - 40px))'"
    :footer="false"
    :mask-closable="false"
    :title="modalTitle"
    unmount-on-close
    @cancel="close"
  >
    <section class="application-template-skill-editor">
      <header class="application-template-skill-editor__head">
        <div>
          <span>来源样例</span>
          <strong>{{ sourceSummary || '正在读取来源样例' }}</strong>
        </div>
        <a-tag :color="isOperationStep ? 'purple' : 'blue'">
          {{ isOperationStep ? '处理步骤' : '提取步骤' }}
        </a-tag>
      </header>

      <nav
        class="application-template-skill-editor__tabs"
        :class="{ 'application-template-skill-editor__tabs--single': isOperationStep }"
      >
        <button
          v-if="!isOperationStep"
          type="button"
          :class="{ 'is-active': mode === 'locator' }"
          @click="emit('update:mode', 'locator')"
        >
          <span>1</span>
          <strong>定位 Skill</strong>
          <em>{{ locatedModules.length ? `${locatedModules.length} 个命中模块` : '查看定位资产' }}</em>
        </button>
        <button
          type="button"
          :class="{ 'is-active': mode === 'extraction' }"
          @click="emit('update:mode', 'extraction')"
        >
          <span>{{ isOperationStep ? '1' : '2' }}</span>
          <strong>{{ isOperationStep ? '处理 Skill' : '抽取 Skill' }}</strong>
          <em>{{ editingStep?.outputSummary?.summary || editingStep?.snapshot.resultPreview || '编辑提取规则' }}</em>
        </button>
      </nav>

      <div v-if="mode === 'locator'" class="application-template-skill-editor__grid">
        <aside class="application-template-skill-editor__context">
          <section>
            <h4>命中内容</h4>
            <p>这些模块来自制作模板时的文档树定位结果，编辑定位 Skill 时要对照它们。</p>
            <div v-if="locatedModules.length" class="application-template-skill-editor__module-list">
              <article v-for="module in locatedModules" :key="module.key">
                <strong>{{ module.title }}</strong>
                <span>{{ module.summary || '暂无摘要' }}</span>
                <em v-if="module.page">{{ module.page }}</em>
              </article>
            </div>
            <div v-else class="application-template-skill-editor__mini-empty">暂无命中模块。</div>
          </section>

          <details v-if="candidateRows.length" open>
            <summary>相关候选 {{ candidateRows.length }} 个</summary>
            <div class="application-template-skill-editor__module-list application-template-skill-editor__module-list--compact">
              <article v-for="candidate in candidateRows.slice(0, 8)" :key="candidate.key">
                <strong>{{ candidate.title }}</strong>
                <span>{{ candidate.summary }}</span>
                <em v-if="candidate.page">{{ candidate.page }}</em>
              </article>
            </div>
          </details>

          <details>
            <summary>原始文档树</summary>
            <div v-if="sourceTaskLoading" class="application-template-skill-editor__mini-empty">正在加载来源文档树。</div>
            <div v-else-if="sourceTreeRows.length" class="application-template-skill-editor__tree-list">
              <article v-for="row in sourceTreeRows" :key="row.key" :style="{ paddingLeft: `${Math.min(row.level, 4) * 12}px` }">
                <strong>{{ row.title }}</strong>
                <span>{{ row.summary }}</span>
                <em v-if="row.page">{{ row.page }}</em>
              </article>
            </div>
            <div v-else class="application-template-skill-editor__mini-empty">来源任务暂无文档树。</div>
          </details>
        </aside>

        <main class="application-template-skill-editor__editing">
          <SkillMarkdownEditor
            :model-value="locatorSkillText"
            title="定位 SKILL.md"
            description="描述如何在新文档的文档树里找到同类内容。不要写死页码，生成内容只是初稿。"
            placeholder="描述如何在新文档的文档树里找到同类内容。不要写死页码。"
            default-mode="split"
            copy-label="定位 Skill"
            :min-height="460"
            @update:model-value="emit('update:locatorSkillText', $event)"
          />
          <details class="application-template-skill-editor__advanced">
            <summary>高级：定位画像 JSON</summary>
            <a-textarea
              :model-value="locatorProfileJson"
              class="application-template-skill-editor__code-editor"
              :auto-size="{ minRows: 10, maxRows: 18 }"
              placeholder="locatorProfile JSON"
              @update:model-value="emit('update:locatorProfileJson', String($event))"
            />
          </details>
        </main>
      </div>

      <div v-else class="application-template-skill-editor__grid">
        <aside class="application-template-skill-editor__context">
          <section>
            <h4>抽取输入</h4>
            <p>抽取只应基于定位 Skill 命中的内容执行。修改抽取规则时先确认这里是否是正确范围。</p>
            <div v-if="locatedModules.length" class="application-template-skill-editor__module-list">
              <article v-for="module in locatedModules" :key="module.key">
                <strong>{{ module.title }}</strong>
                <span>{{ module.summary || '暂无摘要' }}</span>
                <em v-if="module.page">{{ module.page }}</em>
              </article>
            </div>
            <div v-else class="application-template-skill-editor__mini-empty">暂无定位输入，请先完善定位 Skill。</div>
          </section>
          <section>
            <h4>样例输出</h4>
            <div v-if="sourceRunLoading" class="application-template-skill-editor__mini-empty">正在加载来源抽取结果。</div>
            <pre v-else-if="sourceRunOutputText">{{ sourceRunOutputText }}</pre>
            <pre v-else>{{ fallbackOutputText }}</pre>
          </section>
        </aside>

        <main class="application-template-skill-editor__editing">
          <SkillMarkdownEditor
            :model-value="extractionPrompt"
            :title="isOperationStep ? '处理 SKILL.md' : '抽取 SKILL.md'"
            description="编辑完整 SKILL.md，包括 YAML frontmatter、目标、适用条件、执行规则和输出格式。"
            placeholder="写清楚从命中内容里抽取或处理什么、不要做什么，以及输出要求。"
            default-mode="split"
            :copy-label="isOperationStep ? '处理 Skill' : '抽取 Skill'"
            :min-height="460"
            @update:model-value="emit('update:extractionPrompt', $event)"
          />
          <details class="application-template-skill-editor__advanced">
            <summary>高级：Skill 快照 JSON</summary>
            <a-textarea
              :model-value="skillSnapshotJson"
              class="application-template-skill-editor__code-editor"
              :auto-size="{ minRows: 10, maxRows: 18 }"
              placeholder="skillSnapshot JSON"
              @update:model-value="emit('update:skillSnapshotJson', String($event))"
            />
          </details>
        </main>
      </div>

      <footer class="application-template-skill-editor__footer">
        <span>保存后更新草稿；需要影响“使用应用”时，请回到详情页重新发布。</span>
        <div>
          <a-button @click="close">取消</a-button>
          <a-button type="primary" :loading="saving" @click="emit('save')">保存模板资产</a-button>
        </div>
      </footer>
    </section>
  </a-modal>
</template>

<style scoped>
.application-template-skill-editor {
  display: grid;
  gap: 12px;
  max-height: calc(100vh - 150px);
  overflow: hidden;
}

.application-template-skill-editor__head,
.application-template-skill-editor__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.application-template-skill-editor__head > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.application-template-skill-editor__head span,
.application-template-skill-editor__tabs em,
.application-template-skill-editor__module-list em,
.application-template-skill-editor__tree-list em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.application-template-skill-editor__head strong {
  overflow: hidden;
  color: #111827;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-template-skill-editor__tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.application-template-skill-editor__tabs--single {
  grid-template-columns: minmax(0, 1fr);
}

.application-template-skill-editor__tabs button {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 2px 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.application-template-skill-editor__tabs button.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px #2563eb;
}

.application-template-skill-editor__tabs button span {
  grid-row: span 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #edf2f7;
  color: #64748b;
  font-weight: 800;
}

.application-template-skill-editor__tabs button.is-active span {
  background: #2563eb;
  color: #fff;
}

.application-template-skill-editor__tabs strong {
  color: #111827;
  font-size: 15px;
}

.application-template-skill-editor__grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(520px, 1.3fr);
  gap: 12px;
  min-height: 0;
}

.application-template-skill-editor__context,
.application-template-skill-editor__editing {
  display: grid;
  align-content: start;
  gap: 12px;
  min-height: 0;
  max-height: calc(100vh - 360px);
  overflow: auto;
  padding: 12px;
  border: 1px solid #d7dde5;
  background: #fbfcfe;
}

.application-template-skill-editor__context h4 {
  margin: 0 0 4px;
  color: #111827;
}

.application-template-skill-editor__context p {
  margin: 0 0 10px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.application-template-skill-editor__module-list,
.application-template-skill-editor__tree-list {
  display: grid;
  gap: 8px;
}

.application-template-skill-editor__module-list article,
.application-template-skill-editor__tree-list article {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
  border: 1px solid #d7dde5;
  background: #fff;
}

.application-template-skill-editor__module-list--compact article {
  padding: 8px;
}

.application-template-skill-editor__module-list strong,
.application-template-skill-editor__tree-list strong {
  overflow: hidden;
  color: #111827;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-template-skill-editor__module-list span,
.application-template-skill-editor__tree-list span {
  display: -webkit-box;
  overflow: hidden;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.application-template-skill-editor__mini-empty {
  padding: 14px;
  border: 1px dashed #d7dde5;
  color: #64748b;
  font-size: 12px;
  text-align: center;
}

.application-template-skill-editor__advanced {
  border: 1px solid #d7dde5;
  background: #fff;
}

.application-template-skill-editor__advanced summary {
  padding: 10px 12px;
  color: #334155;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.application-template-skill-editor__advanced .application-template-skill-editor__code-editor {
  padding: 0 12px 12px;
}

.application-template-skill-editor__code-editor :deep(textarea) {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1.65;
}

.application-template-skill-editor__footer {
  padding-top: 10px;
  border-top: 1px solid #d7dde5;
}

.application-template-skill-editor__footer span {
  color: #64748b;
  font-size: 12px;
}

.application-template-skill-editor__footer > div {
  display: flex;
  gap: 8px;
}
</style>
