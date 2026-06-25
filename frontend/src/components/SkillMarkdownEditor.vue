<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import MarkdownIt from 'markdown-it'
import { computed, ref, watch } from 'vue'

type EditorMode = 'edit' | 'preview' | 'split'

const props = withDefaults(defineProps<{
  modelValue: string
  title?: string
  description?: string
  defaultMode?: EditorMode
  minHeight?: number
  placeholder?: string
  readonly?: boolean
  showSave?: boolean
  showOpenFull?: boolean
  saveLoading?: boolean
  saveLabel?: string
  copyLabel?: string
}>(), {
  title: '',
  description: '',
  defaultMode: 'edit',
  minHeight: 420,
  placeholder: '在这里编辑 SKILL.md',
  readonly: false,
  showSave: false,
  showOpenFull: false,
  saveLoading: false,
  saveLabel: '保存修改',
  copyLabel: 'SKILL.md',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  save: []
  openFull: []
}>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const mode = ref<EditorMode>(props.defaultMode)

watch(
  () => props.defaultMode,
  (value) => {
    mode.value = value
  },
)

const renderedHtml = computed(() => renderSkillMarkdown(props.modelValue || ''))
const shellStyle = computed(() => ({
  minHeight: `${Math.max(260, props.minHeight)}px`,
}))

async function copyMarkdown() {
  if (!props.modelValue.trim()) {
    Message.info(`${props.copyLabel} 内容为空。`)
    return
  }
  try {
    await navigator.clipboard.writeText(props.modelValue)
    Message.success(`${props.copyLabel} 已复制。`)
  } catch {
    Message.warning('复制失败，请手动选择文本复制。')
  }
}

function renderSkillMarkdown(value: string) {
  const match = value.match(/^---\n([\s\S]*?)\n---(?:\n|$)/)
  if (!match) {
    return markdown.render(value || '暂无内容。')
  }
  const frontmatter = match[1] || ''
  const body = value.slice(match[0].length)
  return [
    '<section class="skill-markdown-editor__frontmatter">',
    '<span>frontmatter</span>',
    `<pre>${escapeHtml(frontmatter)}</pre>`,
    '</section>',
    markdown.render(body || '暂无正文内容。'),
  ].join('')
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
</script>

<template>
  <div class="skill-markdown-editor">
    <header v-if="title || description" class="skill-markdown-editor__head">
      <div>
        <strong v-if="title">{{ title }}</strong>
        <p v-if="description">{{ description }}</p>
      </div>
      <slot name="meta" />
    </header>

    <div class="skill-markdown-editor__toolbar">
      <div class="skill-markdown-editor__modes" aria-label="Markdown 编辑模式">
        <button type="button" :class="{ 'is-active': mode === 'edit' }" @click="mode = 'edit'">编辑</button>
        <button type="button" :class="{ 'is-active': mode === 'preview' }" @click="mode = 'preview'">预览</button>
        <button type="button" :class="{ 'is-active': mode === 'split' }" @click="mode = 'split'">分屏</button>
      </div>
      <div class="skill-markdown-editor__actions">
        <a-button size="mini" @click="copyMarkdown">复制</a-button>
        <a-button v-if="showOpenFull" size="mini" @click="emit('openFull')">放大编辑</a-button>
        <a-button v-if="showSave" size="mini" type="primary" :loading="saveLoading" @click="emit('save')">
          {{ saveLabel }}
        </a-button>
      </div>
    </div>

    <div
      class="skill-markdown-editor__body"
      :class="`skill-markdown-editor__body--${mode}`"
      :style="shellStyle"
    >
      <textarea
        v-if="mode !== 'preview'"
        class="skill-markdown-editor__textarea"
        :value="modelValue"
        :placeholder="placeholder"
        :readonly="readonly"
        spellcheck="false"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      />
      <article
        v-if="mode !== 'edit'"
        class="skill-markdown-editor__preview"
        v-html="renderedHtml"
      />
    </div>
  </div>
</template>

<style scoped>
.skill-markdown-editor {
  display: grid;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #dfe6ef;
  background: #fff;
}

.skill-markdown-editor__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 10px 12px;
  border-bottom: 1px solid #dfe6ef;
  background: #ffffff;
}

.skill-markdown-editor__head > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.skill-markdown-editor__head strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-markdown-editor__head p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.skill-markdown-editor__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid #dfe6ef;
  background: #f8fafc;
}

.skill-markdown-editor__modes,
.skill-markdown-editor__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.skill-markdown-editor__modes button {
  min-width: 48px;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid #d7dee8;
  border-radius: 3px;
  background: #fff;
  color: #475569;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 800;
}

.skill-markdown-editor__modes button.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
  box-shadow: inset 0 0 0 1px #2563eb;
}

.skill-markdown-editor__body {
  display: grid;
  min-height: 260px;
  overflow: hidden;
}

.skill-markdown-editor__body--split {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.skill-markdown-editor__textarea {
  width: 100%;
  min-width: 0;
  min-height: 100%;
  resize: none;
  border: 0;
  outline: 0;
  padding: 14px 16px;
  color: #0f172a;
  background: #ffffff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.65;
}

.skill-markdown-editor__body--split .skill-markdown-editor__textarea {
  border-right: 1px solid #dfe6ef;
}

.skill-markdown-editor__preview {
  min-width: 0;
  overflow: auto;
  padding: 16px 18px 24px;
  color: #162033;
  background: #fbfdff;
  font-size: 13px;
  line-height: 1.72;
}

.skill-markdown-editor__preview :deep(h1),
.skill-markdown-editor__preview :deep(h2),
.skill-markdown-editor__preview :deep(h3) {
  margin: 18px 0 8px;
  color: #0f172a;
  line-height: 1.35;
}

.skill-markdown-editor__preview :deep(h1) {
  font-size: 22px;
}

.skill-markdown-editor__preview :deep(h2) {
  font-size: 17px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 5px;
}

.skill-markdown-editor__preview :deep(h3) {
  font-size: 15px;
}

.skill-markdown-editor__preview :deep(p),
.skill-markdown-editor__preview :deep(ul),
.skill-markdown-editor__preview :deep(ol) {
  margin: 8px 0;
}

.skill-markdown-editor__preview :deep(code) {
  padding: 1px 4px;
  border: 1px solid #dbe4ef;
  background: #f1f5f9;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.skill-markdown-editor__preview :deep(pre),
.skill-markdown-editor__preview :deep(.skill-markdown-editor__frontmatter pre) {
  overflow: auto;
  margin: 8px 0;
  padding: 10px 12px;
  border: 1px solid #d8e0ea;
  background: #f8fafc;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.58;
}

.skill-markdown-editor__preview :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
}

.skill-markdown-editor__preview :deep(th),
.skill-markdown-editor__preview :deep(td) {
  padding: 7px 8px;
  border: 1px solid #dbe4ef;
  text-align: left;
}

.skill-markdown-editor__preview :deep(th) {
  background: #f1f5f9;
  color: #334155;
  font-weight: 850;
}

.skill-markdown-editor__preview :deep(.skill-markdown-editor__frontmatter) {
  display: grid;
  gap: 6px;
  margin-bottom: 14px;
}

.skill-markdown-editor__preview :deep(.skill-markdown-editor__frontmatter span) {
  width: fit-content;
  padding: 2px 7px;
  background: #ecfdf5;
  color: #047857;
  font-size: 11px;
  font-weight: 850;
}
</style>
