<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import type { ProcessingStepDraft } from '../types/applicationWorkshop'
import { t } from '../i18n'
import SkillMarkdownEditor from './SkillMarkdownEditor.vue'

defineProps<{
  visible: boolean
  draft: ProcessingStepDraft | null
  running?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'update:skillText': [value: string]
  save: []
  saveAndTest: []
}>()

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="'min(1180px, calc(100vw - 48px))'"
    :footer="false"
    :mask-closable="false"
    :title="t('workshop.writeSkillMarkdown')"
    unmount-on-close
    @cancel="close"
  >
    <section v-if="draft" class="step-skill-editor-modal">
      <header class="step-skill-editor-modal__head">
        <div>
          <span>{{ draft.status === 'verified' ? t('workshop.verifiedStep') : t('workshop.pendingTrialStep') }}</span>
          <strong>{{ draft.skillName || draft.dataTypeName }}</strong>
          <p>{{ draft.sourceTitle }} · {{ draft.sourceScope }}</p>
        </div>
        <div class="step-skill-editor-modal__actions">
          <a-button @click="emit('save')">{{ t('common.save') }}</a-button>
          <a-button type="primary" :loading="running" @click="emit('saveAndTest')">
            {{ t('workshop.saveAndRunTrial') }}
          </a-button>
        </div>
      </header>

      <SkillMarkdownEditor
        :model-value="draft.skillText"
        :title="t('workshop.stepSkillMarkdown')"
        :description="t('workshop.stepSkillMarkdownDescription')"
        default-mode="split"
        :copy-label="draft.kind === 'operation' ? t('workshop.processingSkill') : t('workshop.extractionSkill')"
        :min-height="560"
        @update:model-value="emit('update:skillText', $event)"
      />

      <details v-if="draft.runOption" class="step-skill-editor-modal__result">
        <summary>{{ t('workshop.viewLatestSampleOutput') }}</summary>
        <pre>{{ draft.runOption.resultPreview || t('workshop.noOutput') }}</pre>
      </details>
    </section>
  </a-modal>
</template>

<style scoped>
.step-skill-editor-modal {
  display: grid;
  gap: 12px;
}

.step-skill-editor-modal__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid #d7dde5;
  background: #f8fafc;
}

.step-skill-editor-modal__head > div:first-child {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.step-skill-editor-modal__head span {
  width: fit-content;
  padding: 2px 7px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 11px;
  font-weight: 850;
}

.step-skill-editor-modal__head strong {
  overflow: hidden;
  color: #111827;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-skill-editor-modal__head p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}

.step-skill-editor-modal__actions {
  display: flex;
  gap: 8px;
}

.step-skill-editor-modal__result {
  border: 1px solid #d7dde5;
  background: #fff;
}

.step-skill-editor-modal__result summary {
  padding: 10px 12px;
  color: #334155;
  font-size: 12px;
  font-weight: 850;
  cursor: pointer;
}

.step-skill-editor-modal__result pre {
  max-height: 220px;
  margin: 0;
  overflow: auto;
  padding: 0 12px 12px;
  color: #334155;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}
</style>
