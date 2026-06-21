<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SkillAuthorPanel from '../components/skill-center/SkillAuthorPanel.vue'
import SkillCenterTopbar from '../components/skill-center/SkillCenterTopbar.vue'
import SkillListPanel from '../components/skill-center/SkillListPanel.vue'
import SkillQualitySummary from '../components/skill-center/SkillQualitySummary.vue'
import SkillTestPanel from '../components/skill-center/SkillTestPanel.vue'
import SkillValidationDrawer from '../components/skill-center/SkillValidationDrawer.vue'
import { useSkillCenterController } from '../components/skill-center/useSkillCenterController'
import { useCapabilitiesStore } from '../stores/capabilities'
import type { SkillKind } from '../types/workbench'
import type { SkillItem } from '../components/skill-center/types'
import '../styles/skill-center.css'

const props = defineProps<{
  skillKind: SkillKind
}>()

const route = useRoute()
const router = useRouter()
const capabilities = useCapabilitiesStore()

const {
  activeKind,
  viewMode,
  keyword,
  customerFilter,
  statusFilter,
  currentPage,
  pageSize,
  skillTotal,
  pageCount,
  loading,
  detailLoading,
  skillTextLoading,
  saving,
  testRunning,
  assistRunning,
  authorMode,
  testTab,
  validationMessage,
  validationState,
  testSampleText,
  testInstruction,
  assistInstruction,
  testResult,
  skillSamples,
  skillTestRuns,
  validationDrawerOpen,
  validationDrawerTab,
  selectedTestRunId,
  selectedTestRunDetail,
  validationDetailLoading,
  validationDetailError,
  editor,
  draftForm,
  paginatedSkillItems,
  customerOptions,
  currentSkillInfo,
  selectedSkill,
  publishChecks,
  publishIssues,
  pageCopy,
  outputContract,
  ensureCurrentSkillTextLoaded,
  reloadSkills,
  newSkill,
  backToList,
  openSkillByRoute,
  applySeededSkillTestSample,
  updateDraftForm,
  generateDraftFromForm,
  fillGoalFromTestInstruction,
  setAuthorMode,
  requestSkillAssist,
  validateCurrentSkill,
  runRealSampleTest,
  saveSkill,
  openValidationDrawer,
  closeValidationDrawer,
  openTestRunDetail,
  copySelectedSkillToCustomer,
  moveSelectedSkillOwnership,
} = useSkillCenterController(props.skillKind)

const listRouteName = computed(() =>
  props.skillKind === 'extraction' ? 'admin-extraction-skills' : 'admin-operation-skills',
)
const detailRouteName = computed(() =>
  props.skillKind === 'extraction' ? 'admin-extraction-skill-detail' : 'admin-operation-skill-detail',
)
const newRouteName = computed(() =>
  props.skillKind === 'extraction' ? 'admin-extraction-skill-new' : 'admin-operation-skill-new',
)
const applicationAuthoringAvailable = computed(() => capabilities.isCapabilityAvailable('application.authoring'))

const detailCustomerId = computed({
  get: () => editor.customerId || (selectedSkill.value?.customerScope === 'customer' ? selectedSkill.value.customerId || '' : ''),
  set: (value: string) => {
    editor.customerId = value
  },
})

const topbarCustomerLabel = computed(() => {
  if (viewMode.value !== 'detail') return '客户'
  if (selectedSkill.value) return '目标客户'
  return '归属客户'
})

watch(
  () => [
    props.skillKind,
    route.name,
    route.params.scope,
    route.params.skillId,
    route.query.customerId,
    route.query.sampleSeedToken,
  ],
  async () => {
    const value = props.skillKind
    if (activeKind.value !== value) {
      activeKind.value = value
    }
    if (route.name === newRouteName.value) {
      newSkill()
      return
    }
    const scope = route.params.scope
    const skillId = route.params.skillId
    if (
      route.name === detailRouteName.value &&
      (scope === 'platform' || scope === 'customer') &&
      typeof skillId === 'string'
    ) {
      const customerId = typeof route.query.customerId === 'string' ? route.query.customerId : null
      const sampleSeedToken = typeof route.query.sampleSeedToken === 'string' ? route.query.sampleSeedToken : null
      await openSkillByRoute(scope, skillId, customerId)
      applySeededSkillTestSample(sampleSeedToken)
      return
    }
    backToList()
  },
  { immediate: true },
)

function goToList() {
  router.push({ name: listRouteName.value })
}

function goToNewSkill() {
  router.push({ name: newRouteName.value })
}

function goToSkillDetail(item: SkillItem) {
  const query =
    item.customerScope === 'customer' && item.customerId
      ? { customerId: item.customerId }
      : {}
  router.push({
    name: detailRouteName.value,
    params: {
      scope: item.customerScope,
      skillId: item.id,
    },
    query,
  })
}

function copyToCurrentCustomer() {
  if (!editor.customerId) return
  copySelectedSkillToCustomer(editor.customerId)
}

function moveToCurrentCustomer() {
  if (!editor.customerId) return
  moveSelectedSkillOwnership(editor.customerId)
}
</script>

<template>
  <div class="skill-center">
    <SkillCenterTopbar
      v-model:customer-id="detailCustomerId"
      :active-kind="activeKind"
      :view-mode="viewMode"
      :customer-options="customerOptions"
      :show-customer-picker="viewMode === 'detail'"
      :customer-label="topbarCustomerLabel"
      :allow-empty-customer="false"
      :current-title="selectedSkill?.name || currentSkillInfo.name"
      :current-subtitle="selectedSkill ? `${selectedSkill.id} · v${selectedSkill.version}` : '新建草稿'"
      :show-copy="Boolean(selectedSkill)"
      :show-move="selectedSkill?.customerScope === 'customer'"
      :can-copy="Boolean(selectedSkill && editor.customerId)"
      :can-move="Boolean(selectedSkill && editor.customerId && selectedSkill.customerId !== editor.customerId)"
      @customer-change="reloadSkills"
      @new-skill="goToNewSkill"
      @back-list="goToList"
      @copy-current="copyToCurrentCustomer"
      @move-current="moveToCurrentCustomer"
    />

    <a-alert v-if="applicationAuthoringAvailable" class="skill-center__kind-hint" type="info">
      <template #title>当前页管理的是基础 Skill，不是应用</template>
      这里维护单个解析或业务处理能力；如果要查看由多个步骤串联后的可执行能力，请前往
      <a-link @click="router.push({ name: 'admin-applications' })">文档应用</a-link>
      。
    </a-alert>

    <section class="skill-center__workspace">
      <div v-if="loading && viewMode === 'list'" class="skill-center__empty">正在加载 Skill。</div>
      <SkillListPanel
        v-else-if="viewMode === 'list'"
        v-model:keyword="keyword"
        v-model:customer-filter="customerFilter"
        v-model:status-filter="statusFilter"
        v-model:page="currentPage"
        :active-kind="activeKind"
        :items="paginatedSkillItems"
        :total="skillTotal"
        :page-size="pageSize"
        :page-count="pageCount"
        :customer-options="customerOptions"
        @open="goToSkillDetail"
        @create="goToNewSkill"
      />
      <div v-else-if="detailLoading" class="skill-center__detail-loading">
        <strong>正在读取 Skill 详情</strong>
        <span>正在从数据库和文件存储读取规则、样本和最近试跑结果。</span>
      </div>
      <div v-else>
        <SkillQualitySummary
          :selected-skill="selectedSkill"
          :sample-count="skillSamples.length"
          :test-run-count="skillTestRuns.length"
          @open="openValidationDrawer('runs')"
        />
        <div class="skill-center__workflow">
          <SkillAuthorPanel
            v-model:author-mode="authorMode"
            v-model:assist-instruction="assistInstruction"
            :skill-text-loading="skillTextLoading"
            :selected-skill-id="selectedSkill?.id || ''"
            :selected-skill-version="selectedSkill?.version || ''"
            :page-copy="pageCopy"
            :assist-running="assistRunning"
            :draft-form="draftForm"
            :output-contract="outputContract"
            :skill-text="editor.skillText"
            @update-draft="updateDraftForm"
            @request-assist="requestSkillAssist()"
            @fill-goal-from-test="fillGoalFromTestInstruction"
            @generate-draft="generateDraftFromForm"
            @load-skill-text="ensureCurrentSkillTextLoaded"
            @update:skill-text="(value) => (editor.skillText = value)"
          />

          <SkillTestPanel
            v-model:test-tab="testTab"
            v-model:test-instruction="testInstruction"
            v-model:test-sample-text="testSampleText"
            :page-copy="pageCopy"
            :test-running="testRunning"
            :saving="saving"
            :test-result="testResult"
            :current-skill-info="currentSkillInfo"
            :publish-checks="publishChecks"
            :publish-issues="publishIssues"
            :validation-state="validationState"
            :validation-message="validationMessage"
            @run="runRealSampleTest"
            @validate="validateCurrentSkill"
            @save="saveSkill"
            @return-to-form="setAuthorMode('guided')"
          />
        </div>
      </div>
    </section>
    <SkillValidationDrawer
      v-model:active-tab="validationDrawerTab"
      :open="validationDrawerOpen"
      :active-kind="activeKind"
      :selected-skill="selectedSkill"
      :samples="skillSamples"
      :test-runs="skillTestRuns"
      :selected-run-id="selectedTestRunId"
      :selected-run-detail="selectedTestRunDetail"
      :detail-loading="validationDetailLoading"
      :detail-error="validationDetailError"
      @close="closeValidationDrawer"
      @open-run="openTestRunDetail"
    />
  </div>
</template>
