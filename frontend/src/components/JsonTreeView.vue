<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  rootKey: string
  data: unknown
  expandedPaths?: Set<string>
}>()

const emit = defineEmits<{
  toggle: [path: string]
}>()

function getNodeKind(data: unknown): 'primitive' | 'object' | 'array' {
  if (data === null || data === undefined) return 'primitive'
  if (Array.isArray(data)) return 'array'
  if (typeof data === 'object') return 'object'
  return 'primitive'
}

const isCollapsed = computed(() => {
  const kind = getNodeKind(props.data)
  if (kind === 'primitive') return false
  return !props.expandedPaths?.has(props.rootKey)
})

const entries = computed(() => {
  const kind = getNodeKind(props.data)
  if (kind === 'object') {
    return Object.entries(props.data as Record<string, unknown>).map(([key, value]) => ({
      key,
      path: props.rootKey ? `${props.rootKey}.${key}` : key,
      value,
    }))
  }
  if (kind === 'array') {
    return (props.data as unknown[]).map((value, index) => ({
      key: String(index),
      path: props.rootKey ? `${props.rootKey}[${index}]` : `[${index}]`,
      value,
    }))
  }
  return []
})

const itemCount = computed(() => entries.value.length)

const collapsedPreview = computed(() => {
  const kind = getNodeKind(props.data)
  if (kind === 'object') {
    const keys = entries.value.slice(0, 6).map((e) => e.key)
    if (entries.value.length > 6) keys.push('...')
    return `{ ${keys.join(', ')} }`
  }
  if (kind === 'array') {
    const previewItems = entries.value.slice(0, 6).map((e) => {
      const v = e.value
      if (v === null) return 'null'
      if (typeof v === 'string') return `"${v.substring(0, 20)}${v.length > 20 ? '…' : ''}"`
      if (typeof v === 'number' || typeof v === 'boolean') return String(v)
      if (Array.isArray(v)) return '[...]'
      if (typeof v === 'object') return '{...}'
      return String(v)
    })
    if (entries.value.length > 6) previewItems.push('...')
    return `[ ${previewItems.join(', ')} ]`
  }
  return ''
})

function formatPrimitive(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string') return `"${value}"`
  return String(value)
}

function primClass(value: unknown): string {
  if (value === null || value === undefined) return 'json-tree__null'
  if (typeof value === 'string') return 'json-tree__string'
  if (typeof value === 'number') return 'json-tree__number'
  if (typeof value === 'boolean') return 'json-tree__bool'
  return ''
}

function handleToggle() {
  emit('toggle', props.rootKey)
}
</script>

<template>
  <div class="json-tree">
    <div
      v-if="getNodeKind(data) === 'primitive'"
      class="json-tree__leaf"
    >
      <span class="json-tree__key">{{ rootKey }}</span>
      <span class="json-tree__sep">: </span>
      <span :class="primClass(data)">{{ formatPrimitive(data) }}</span>
    </div>

    <div v-else class="json-tree__branch">
      <button
        type="button"
        class="json-tree__toggle"
        @click="handleToggle"
      >
        <span class="json-tree__arrow" :class="{ 'is-open': !isCollapsed }">▶</span>
        <span class="json-tree__key">{{ rootKey }}</span>
        <span class="json-tree__sep">: </span>
        <span v-if="isCollapsed" class="json-tree__preview">{{ collapsedPreview }}</span>
        <span v-else>{{ getNodeKind(data) === 'object' ? '{' : '[' }} <span class="json-tree__count">{{ itemCount }}</span></span>
      </button>

      <div v-if="!isCollapsed" class="json-tree__children">
        <JsonTreeView
          v-for="entry in entries"
          :key="entry.path"
          :root-key="entry.key"
          :data="entry.value"
          :expanded-paths="expandedPaths"
          @toggle="emit('toggle', $event)"
        />

        <div class="json-tree__closing">
          {{ getNodeKind(data) === 'object' ? '}' : ']' }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.json-tree {
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', Menlo, monospace;
  font-size: 12px;
  line-height: 1.7;
}

.json-tree__leaf {
  display: flex;
  align-items: baseline;
  padding-left: 20px;
}

.json-tree__branch {
  display: grid;
}

.json-tree__toggle {
  display: flex;
  align-items: baseline;
  gap: 0;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
  width: 100%;
  color: inherit;
  font: inherit;
}

.json-tree__toggle:hover {
  background: rgba(148, 163, 184, 0.12);
}

.json-tree__arrow {
  width: 16px;
  flex-shrink: 0;
  color: #64748b;
  font-size: 10px;
  transition: transform 0.16s ease;
  display: inline-block;
  line-height: inherit;
}

.json-tree__arrow.is-open {
  transform: rotate(90deg);
}

.json-tree__key {
  color: #93c5fd;
  flex-shrink: 0;
}

.json-tree__sep {
  color: #94a3b8;
  white-space: pre;
}

.json-tree__string {
  color: #86efac;
  word-break: break-word;
}

.json-tree__number {
  color: #fde68a;
}

.json-tree__bool {
  color: #c4b5fd;
}

.json-tree__null {
  color: #94a3b8;
  font-style: italic;
}

.json-tree__preview {
  color: #94a3b8;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}

.json-tree__count {
  color: #94a3b8;
  font-size: 10px;
}

.json-tree__children {
  display: grid;
}

.json-tree__closing {
  padding-left: 0;
  color: #e2e8f0;
}
</style>
