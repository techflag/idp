<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import SkillMarkdownEditor from '../SkillMarkdownEditor.vue'
import type { AuthorMode, SkillDraftForm, SkillOutputContract, SkillPageCopy } from './types'

defineProps<{
  authorMode: AuthorMode
  selectedSkillId: string
  selectedSkillVersion: string
  pageCopy: SkillPageCopy
  assistInstruction: string
  assistRunning: boolean
  draftForm: SkillDraftForm
  outputContract: SkillOutputContract
  skillText: string
  skillTextLoading: boolean
}>()

const emit = defineEmits<{
  'update:authorMode': [value: AuthorMode]
  'update:assistInstruction': [value: string]
  'update:skillText': [value: string]
  'update-draft': [field: keyof SkillDraftForm, value: string]
  'request-assist': []
  'fill-goal-from-test': []
  'generate-draft': []
  'load-skill-text': []
}>()

function updateAssist(event: Event) {
  emit('update:assistInstruction', (event.target as HTMLTextAreaElement).value)
}

function updateDraft(field: keyof SkillDraftForm, event: Event) {
  emit('update-draft', field, (event.target as HTMLInputElement | HTMLTextAreaElement).value)
}
</script>

<template>
  <section class="skill-center__column skill-center__column--write">
    <div class="skill-center__column-head">
      <div>
        <span>01</span>
        <strong>编写</strong>
        <em class="skill-center__column-meta">
          <span>{{ selectedSkillId || '新建草稿' }}</span>
          <span v-if="selectedSkillVersion" class="skill-center__version-pill">v{{ selectedSkillVersion }}</span>
        </em>
      </div>
    </div>

    <div class="skill-center__mode-tabs" role="tablist" aria-label="编写方式">
      <button
        type="button"
        role="tab"
        :aria-selected="authorMode === 'guided'"
        :class="{ 'is-active': authorMode === 'guided' }"
        @click="$emit('update:authorMode', 'guided')"
      >
        表单编写
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="authorMode === 'advanced'"
        :class="{ 'is-active': authorMode === 'advanced' }"
        @click="$emit('update:authorMode', 'advanced')"
      >
        高级编辑
      </button>
    </div>

    <div class="skill-center__assist">
      <label>
        <span>{{ pageCopy.assistTitle }}</span>
        <textarea
          :value="assistInstruction"
          :placeholder="pageCopy.assistPlaceholder"
          @input="updateAssist"
        />
      </label>
      <button type="button" :disabled="assistRunning" @click="$emit('request-assist')">
        {{ assistRunning ? '优化中' : '优化草稿' }}
      </button>
    </div>

    <div v-if="authorMode === 'guided'" class="skill-center__guided">
      <div class="skill-center__guided-head">
        <div>
          <strong>{{ pageCopy.guidedTitle }}</strong>
          <span>{{ pageCopy.guidedDescription }}</span>
        </div>
        <button type="button" @click="$emit('fill-goal-from-test')">带入试跑要求</button>
      </div>
      <div class="skill-center__guided-grid skill-center__guided-grid--identity">
        <label>
          <span>Skill ID</span>
          <input
            :value="draftForm.id"
            placeholder="例如：extraction_test_report"
            @input="updateDraft('id', $event)"
          />
        </label>
        <label>
          <span>版本</span>
          <input
            :value="draftForm.version"
            placeholder="1.0.0"
            @input="updateDraft('version', $event)"
          />
        </label>
        <label>
          <span>Skill 名称</span>
          <input
            :value="draftForm.name"
            placeholder="例如：检测报告提取"
            @input="updateDraft('name', $event)"
          />
        </label>
      </div>
      <label class="skill-center__guided-block">
        <span>{{ pageCopy.goalLabel }}</span>
        <textarea
          :value="draftForm.goal"
          :placeholder="pageCopy.goalPlaceholder"
          @input="updateDraft('goal', $event)"
        />
      </label>
      <label class="skill-center__guided-block">
        <span>{{ pageCopy.rulesLabel }}</span>
        <textarea
          :value="draftForm.rules"
          :placeholder="pageCopy.rulesPlaceholder"
          @input="updateDraft('rules', $event)"
        />
      </label>
      <label class="skill-center__guided-block skill-center__guided-block--output">
        <span>{{ pageCopy.outputLabel }}</span>
        <textarea
          :value="draftForm.outputJson"
          :placeholder="pageCopy.outputPlaceholder"
          @input="updateDraft('outputJson', $event)"
        />
      </label>
      <div
        class="skill-center__output-contract"
        :class="{ 'is-warning': !outputContract.valid }"
      >
        <span>输出协议</span>
        <strong>{{ outputContract.label }}</strong>
        <em>{{ outputContract.description }}</em>
      </div>
      <button type="button" class="skill-center__generate" @click="$emit('generate-draft')">
        生成草稿
      </button>
    </div>

    <div v-else-if="selectedSkillId && !skillText.trim()" class="skill-center__editor-placeholder">
      <div>
        <strong>SKILL.md 正文已存储</strong>
        <span>当前只加载了数据库中的元数据；打开编辑器时再读取完整正文。</span>
      </div>
      <button type="button" :disabled="skillTextLoading" @click="$emit('load-skill-text')">
        {{ skillTextLoading ? '读取中' : '打开编辑器' }}
      </button>
    </div>

    <SkillMarkdownEditor
      v-else
      :model-value="skillText"
      title="SKILL.md"
      description="这里编辑的是完整 Skill 正文。生成内容只是初稿，保存前可以继续调整目标、适用条件、规则和输出格式。"
      default-mode="split"
      copy-label="Skill 正文"
      :min-height="620"
      @update:model-value="emit('update:skillText', $event)"
    />
  </section>
</template>
