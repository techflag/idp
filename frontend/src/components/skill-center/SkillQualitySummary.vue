<!--
SPDX-FileCopyrightText: 2026 TechFlag
SPDX-License-Identifier: MIT
-->

<script setup lang="ts">
import type { SkillItem } from './types'

defineProps<{
  selectedSkill: SkillItem | null
  sampleCount: number
  testRunCount: number
}>()

const emit = defineEmits<{
  open: []
}>()

function latestTestLabel(status?: string | null) {
  if (!status) return '未测试'
  return status === 'completed' ? '最近通过' : status === 'failed' ? '最近失败' : status
}

function latestTestClass(status?: string | null) {
  if (!status) return 'is-unknown'
  return status === 'completed' ? 'is-passed' : status === 'failed' ? 'is-failed' : 'is-unknown'
}
</script>

<template>
  <section v-if="selectedSkill" class="skill-center__quality-summary">
    <div class="skill-center__quality-main">
      <span>质量摘要</span>
      <strong :class="['skill-center__quality-pill', latestTestClass(selectedSkill.latestTestStatus)]">
        {{ latestTestLabel(selectedSkill.latestTestStatus) }}
      </strong>
    </div>
    <div class="skill-center__quality-metrics">
      <span>样本 {{ sampleCount || selectedSkill.sampleCount || 0 }}</span>
      <span>试跑 {{ testRunCount || selectedSkill.testRunCount || 0 }}</span>
      <span v-if="selectedSkill.lastTestedAt">最近 {{ selectedSkill.lastTestedAt.slice(0, 10) }}</span>
    </div>
    <button type="button" @click="emit('open')">查看验证记录</button>
  </section>
</template>
