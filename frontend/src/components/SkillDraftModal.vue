<script setup lang="ts">
import SkillMarkdownEditor from './SkillMarkdownEditor.vue'

defineProps<{
  visible: boolean
  loading: boolean
  modelValue: string
  summary: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'update:modelValue': [value: string]
  copy: []
}>()

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="860"
    title="Skill 草稿"
    unmount-on-close
    @cancel="close"
  >
    <div class="skill-draft-modal">
      <a-spin v-if="loading" tip="正在根据样例生成可复用能力..." />
      <SkillMarkdownEditor
        v-else
        :model-value="modelValue"
        title="从当前样例沉淀处理能力"
        :description="`已整理 ${summary?.matchedTargetCount ?? 0} 个样例对象，样本文本 ${summary?.sampleChars ?? 0} 字。生成内容只是初稿，可以继续编辑。`"
        default-mode="split"
        copy-label="Skill 草稿"
        :min-height="520"
        placeholder="生成后的 SKILL.md 会显示在这里。"
        @update:model-value="emit('update:modelValue', $event)"
      />
    </div>
    <template #footer>
      <a-button @click="close">关闭</a-button>
      <a-button type="primary" :disabled="!modelValue" @click="emit('copy')">复制到 Skill 中心使用</a-button>
    </template>
  </a-modal>
</template>

<style scoped>
.skill-draft-modal {
  display: grid;
  gap: 12px;
  min-height: 300px;
}
</style>
