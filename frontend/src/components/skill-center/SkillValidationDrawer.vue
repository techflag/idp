<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import type { SkillKind, SkillSample, SkillTestRunSummary } from '../../types/workbench'
import type { SkillItem } from './types'

defineProps<{
  open: boolean
  activeKind: SkillKind
  selectedSkill: SkillItem | null
  samples: SkillSample[]
  testRuns: SkillTestRunSummary[]
  activeTab: 'samples' | 'runs'
  selectedRunId: string
  selectedRunDetail: SkillTestRunSummary | null
  detailLoading: boolean
  detailError: string
}>()

const emit = defineEmits<{
  close: []
  'update:activeTab': [value: 'samples' | 'runs']
  openRun: [run: SkillTestRunSummary]
}>()

function statusLabel(status?: string | null, valid?: boolean) {
  if (status === 'completed' || valid) return '通过'
  if (status === 'failed') return '失败'
  return status || '未知'
}

function statusClass(status?: string | null, valid?: boolean) {
  if (status === 'completed' || valid) return 'is-passed'
  if (status === 'failed') return 'is-failed'
  return 'is-unknown'
}

function formatDuration(value?: number | null) {
  if (!value) return '0 秒'
  return `${(value / 1000).toFixed(2)} 秒`
}

function formatSize(value?: number | null) {
  const size = Number(value || 0)
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

function stringifyPreview(value: unknown) {
  if (value == null) return ''
  return JSON.stringify(value, null, 2)
}

function resultPreview(run: SkillTestRunSummary | null) {
  if (!run) return ''
  return stringifyPreview(run.result || run.summary || {})
}
</script>

<template>
  <teleport to="body">
    <div v-if="open" class="skill-center__drawer-backdrop" @click.self="emit('close')">
      <aside class="skill-center__validation-drawer" aria-label="验证记录">
        <header class="skill-center__drawer-head">
          <div>
            <span>验证记录</span>
            <strong>{{ selectedSkill?.name || 'Skill' }}</strong>
            <em>{{ activeKind === 'extraction' ? '解析 Skill' : '处理 Skill' }}</em>
          </div>
          <button type="button" aria-label="关闭验证记录" @click="emit('close')">关闭</button>
        </header>

        <div class="skill-center__drawer-tabs" role="tablist" aria-label="验证记录类型">
          <button
            type="button"
            role="tab"
            :aria-selected="activeTab === 'runs'"
            :class="{ 'is-active': activeTab === 'runs' }"
            @click="emit('update:activeTab', 'runs')"
          >
            试跑历史
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="activeTab === 'samples'"
            :class="{ 'is-active': activeTab === 'samples' }"
            @click="emit('update:activeTab', 'samples')"
          >
            样本
          </button>
        </div>

        <section v-if="activeTab === 'samples'" class="skill-center__drawer-body">
          <div v-if="samples.length" class="skill-center__drawer-list">
            <article v-for="sample in samples" :key="sample.id" class="skill-center__drawer-item">
              <div class="skill-center__drawer-item-head">
                <strong>{{ sample.fileName || sample.id }}</strong>
                <span>{{ formatSize(sample.sizeBytes) }}</span>
              </div>
              <p v-if="sample.instruction">{{ sample.instruction }}</p>
              <pre>{{ sample.content || sample.preview || '无预览' }}</pre>
              <span class="skill-center__drawer-time">{{ sample.updatedAt?.slice(0, 19).replace('T', ' ') }}</span>
            </article>
          </div>
          <div v-else class="skill-center__drawer-empty">
            <strong>还没有样本</strong>
            <span>保存试跑样本后会出现在这里。</span>
          </div>
        </section>

        <section v-else class="skill-center__drawer-body skill-center__drawer-body--runs">
          <div class="skill-center__drawer-run-list">
            <div v-if="testRuns.length" class="skill-center__drawer-list">
              <article
                v-for="run in testRuns"
                :key="run.id"
                :class="['skill-center__drawer-item', { 'is-active': selectedRunId === run.id }]"
              >
                <div class="skill-center__drawer-item-head">
                  <strong :class="['skill-center__quality-pill', statusClass(run.status, run.valid)]">
                    {{ statusLabel(run.status, run.valid) }}
                  </strong>
                  <span>{{ run.updatedAt?.slice(0, 19).replace('T', ' ') }}</span>
                </div>
                <p>{{ run.model || 'unknown model' }} · {{ formatDuration(run.durationMs) }}</p>
                <p>输入 {{ run.inputChars }} 字符 · 输出 {{ run.outputChars }} 字符</p>
                <pre v-if="run.errors?.length">{{ run.errors.join('\n') }}</pre>
                <button type="button" :disabled="detailLoading" @click="emit('openRun', run)">
                  {{ selectedRunId === run.id ? '已选择' : '查看输出' }}
                </button>
              </article>
            </div>
            <div v-else class="skill-center__drawer-empty">
              <strong>还没有试跑</strong>
              <span>在详情页完成试跑后，历史记录会保存在这里。</span>
            </div>
          </div>

          <aside class="skill-center__drawer-detail-pane" aria-label="试跑输出详情">
            <div v-if="detailLoading" class="skill-center__drawer-detail-empty">
              <strong>正在读取输出</strong>
              <span>正在读取这次试跑的完整结果。</span>
            </div>
            <div v-else-if="detailError" class="skill-center__drawer-error">{{ detailError }}</div>
            <article v-else-if="selectedRunDetail" class="skill-center__drawer-detail">
              <div class="skill-center__drawer-item-head">
                <strong>输出详情</strong>
                <span>{{ selectedRunDetail.id }}</span>
              </div>
              <pre>{{ resultPreview(selectedRunDetail) || '无输出内容' }}</pre>
            </article>
            <div v-else class="skill-center__drawer-detail-empty">
              <strong>暂无输出详情</strong>
              <span>完整输出将在这里展示。</span>
            </div>
          </aside>
        </section>
      </aside>
    </div>
  </teleport>
</template>
