<script setup lang="ts">
import { ref, watch } from 'vue'
import type { WorkbenchPage } from '../types/workbench'

const QUICK_EXAMPLES = [
  '检查当前页关键字段是否一致，并列出问题。',
  '把当前页结果整理成适合导出 Excel 的表格结构。',
  '统一日期和数字格式，输出整理后的 JSON。',
]

const PROCESS_PLACEHOLDER = [
  '例如：',
  '1. 检查当前页关键字段是否一致，并列出问题',
  '2. 把当前页结果整理成适合导出 Excel 的表格结构',
  '3. 统一日期和数字格式，输出整理后的 JSON',
].join('\n')

const props = defineProps<{
  visible: boolean
  page: WorkbenchPage | null
  initialRequirement?: string
  processing?: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: [requirement: string]
}>()

const requirement = ref('')

function applyExample(example: string) {
  requirement.value = example
}

watch(
  () => props.visible,
  (value) => {
    if (value) {
      requirement.value = props.initialRequirement ?? ''
      return
    }

    requirement.value = ''
  },
)
</script>

<template>
  <a-drawer
    :visible="visible"
    :footer="false"
    :mask-closable="!processing"
    width="520px"
    unmount-on-close
    @cancel="emit('close')"
  >
    <template #title>处理</template>

    <div v-if="page" class="process-editor">
      <div class="process-editor__header">
        <div class="process-editor__meta">
          <a-tag color="arcoblue">当前页 {{ page.pageNo }}</a-tag>
        </div>
      </div>

      <div class="process-editor__field">
        <div class="process-editor__label">快捷示例</div>
        <div class="process-editor__examples">
          <a-button
            v-for="example in QUICK_EXAMPLES"
            :key="example"
            size="small"
            @click="applyExample(example)"
          >
            {{ example }}
          </a-button>
        </div>
      </div>

      <div class="process-editor__field">
        <div class="process-editor__label">二次处理要求</div>
        <a-textarea
          v-model="requirement"
          :auto-size="{ minRows: 6, maxRows: 12 }"
          :placeholder="PROCESS_PLACEHOLDER"
        />
      </div>

      <div class="process-editor__footer">
        <a-button @click="emit('close')">取消</a-button>
        <a-button type="primary" :loading="processing" @click="emit('submit', requirement)">
          {{ requirement.trim() ? '开始二次处理' : '再次处理' }}
        </a-button>
      </div>
    </div>

    <a-empty v-else description="请选择一个任务页后再处理。" />
  </a-drawer>
</template>

<style scoped>
.process-editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.process-editor__meta,
.process-editor__footer {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.process-editor__field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.process-editor__examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.process-editor__label {
  color: #111827;
  font-size: 12px;
  font-weight: 600;
}

.process-editor :deep(.arco-textarea-wrapper),
.process-editor :deep(.arco-btn),
:deep(.arco-drawer),
:deep(.arco-drawer-header),
:deep(.arco-drawer-footer),
:deep(.arco-drawer-body) {
  border-radius: 0;
}

.process-editor :deep(.arco-textarea) {
  line-height: 1.6;
}
</style>
