import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  assistSkill,
  copySkillDraft,
  createSkill,
  loadSkillDetail,
  loadSkillTestRunDetail,
  loadCustomers,
  loadSkills,
  loadSkillSamples,
  loadSkillTestRuns,
  moveSkillOwnership,
  saveSkillSample,
  testRunSkill,
  updateSkill,
  validateSkill,
} from '../../services/workbenchApi'
import type {
  CustomerSummary,
  ExtractionResult,
  SkillKind,
  SkillSample,
  SkillTestRunResponse,
  SkillTestRunSummary,
  UnifiedSkill,
} from '../../types/workbench'
import type { AuthorMode, SkillDraftForm, SkillItem, TestTab } from './types'
import {
  assignDraftForm,
  buildPageCopy,
  buildSkillTextFromDraft,
  defaultDraftForm,
  defaultSkillText,
  formatExecutorLabel,
  inferOutputContractFromJson,
  parseSkillSummary,
  syncDraftFormFromSkillText,
} from './skillCenterModel'
import { consumeSkillTestSeed } from '../../utils/skillTestSeed'

export function useSkillCenterController(initialKind: SkillKind = 'extraction') {
  const activeKind = ref<SkillKind>(initialKind)
  const customers = ref<CustomerSummary[]>([])
  const skills = ref<UnifiedSkill[]>([])
  const selectedKey = ref('')
  const viewMode = ref<'list' | 'detail'>('list')
  const keyword = ref('')
  const customerFilter = ref('all')
  const statusFilter = ref('all')
  const currentPage = ref(1)
  const pageSize = ref(8)
  const skillTotal = ref(0)
  const loading = ref(false)
  const detailLoading = ref(false)
  const skillTextLoading = ref(false)
  const saving = ref(false)
  const testRunning = ref(false)
  const assistRunning = ref(false)
  const authorMode = ref<AuthorMode>('guided')
  const testTab = ref<TestTab>('config')
  const validationMessage = ref('')
  const validationState = ref<'idle' | 'ok' | 'error'>('idle')
  const testSampleText = ref('')
  const testInstruction = ref('')
  const assistInstruction = ref('')
  const testResult = ref<SkillTestRunResponse | null>(null)
  const skillSamples = ref<SkillSample[]>([])
  const skillTestRuns = ref<SkillTestRunSummary[]>([])
  const validationDrawerOpen = ref(false)
  const validationDrawerTab = ref<'samples' | 'runs'>('runs')
  const selectedTestRunId = ref('')
  const selectedTestRunDetail = ref<SkillTestRunSummary | null>(null)
  const validationDetailLoading = ref(false)
  const validationDetailError = ref('')
  let suppressNextSampleResultReset = false
  const editor = reactive({
    customerId: '',
    skillText: '',
  })
  const draftForm = reactive<SkillDraftForm>(defaultDraftForm('extraction'))

  const skillItems = computed<SkillItem[]>(() => skills.value)
  const filteredSkillItems = computed(() => skillItems.value)
  const pageCount = computed(() => Math.max(1, Math.ceil(skillTotal.value / pageSize.value)))
  const paginatedSkillItems = computed(() => skillItems.value)

  const customerOptions = computed(() => customers.value.map((item) => ({ label: item.name, value: item.id })))
  function resolveCustomerName(customerId: string | null | undefined) {
    if (!customerId) return '平台内置'
    return customerOptions.value.find((item) => item.value === customerId)?.label || customerId
  }
  const selectedOwnerCustomerId = computed(() =>
    selectedSkill.value?.customerScope === 'customer' ? selectedSkill.value.customerId || '' : '',
  )
  const publishOwnerCustomerId = computed(() => selectedOwnerCustomerId.value || editor.customerId || '')
  const publishOwnerCustomerName = computed(() => resolveCustomerName(publishOwnerCustomerId.value))
  const publishScopeLabel = computed(() => {
    if (selectedSkill.value?.customerScope === 'platform') {
      return '平台内置'
    }
    return '客户归属'
  })
  const currentSkillInfo = computed(() => {
    if (!editor.skillText.trim() && selectedSkill.value) {
      return {
        id: selectedSkill.value.id,
        name: selectedSkill.value.name,
        version: selectedSkill.value.version,
        executor: selectedSkill.value.executor,
      }
    }
    const parsed = parseSkillSummary(editor.skillText)
    if (authorMode.value !== 'guided') return parsed
    return {
      ...parsed,
      id: draftForm.id.trim() || parsed.id,
      name: draftForm.name.trim() || parsed.name,
      version: draftForm.version.trim() || parsed.version,
    }
  })
  const selectedSkill = computed(() => skillItems.value.find((item) => skillKey(item) === selectedKey.value) || null)
  const publishChecks = computed(() => {
    const info = currentSkillInfo.value
    return [
      {
        label: 'Skill 名称',
        value: info.name === '未填写名称' ? '未填写' : info.name,
        ok: info.name !== '未填写名称',
      },
      {
        label: '版本',
        value: info.version === '未填写版本' ? '未填写' : info.version,
        ok: info.version !== '未填写版本',
      },
      {
        label: '运行方式',
        value: formatExecutorLabel(info.executor),
        ok: Boolean(info.executor && info.executor !== '未填写执行器'),
      },
      {
        label: '归属客户',
        value: publishOwnerCustomerId.value ? publishOwnerCustomerName.value : '未选择归属',
        ok: Boolean(publishOwnerCustomerId.value),
      },
      {
        label: '发布范围',
        value: publishScopeLabel.value,
        ok: true,
      },
    ]
  })
  const publishIssues = computed(() => publishChecks.value.filter((item) => !item.ok).map((item) => item.label))
  const pageCopy = computed(() => buildPageCopy(activeKind.value))
  const outputContract = computed(() => inferOutputContractFromJson(draftForm.outputJson, activeKind.value))

  onMounted(async () => {
    await loadCustomerOptions()
    await reloadSkills()
  })

  watch(activeKind, async () => {
    selectedKey.value = ''
    viewMode.value = 'list'
    currentPage.value = 1
    statusFilter.value = 'all'
    editor.skillText = defaultSkillText(activeKind.value)
    resetDraftForm(activeKind.value)
    authorMode.value = 'guided'
    validationState.value = 'idle'
    validationMessage.value = ''
    testResult.value = null
    skillSamples.value = []
    skillTestRuns.value = []
    closeValidationDrawer()
    detailLoading.value = false
    testTab.value = 'config'
    await reloadSkills()
  })

  watch([keyword, customerFilter, statusFilter], () => {
    if (currentPage.value === 1) {
      void reloadSkills()
      return
    }
    currentPage.value = 1
  })

  watch(currentPage, () => {
    void reloadSkills()
  })

  watch(pageCount, (value) => {
    if (currentPage.value > value) currentPage.value = value
  })

  watch(
    () => editor.skillText,
    (value) => {
      syncDraftFormFromSkillText(draftForm, value)
    },
  )

  watch(testSampleText, () => {
    if (suppressNextSampleResultReset) {
      suppressNextSampleResultReset = false
      return
    }
    testResult.value = null
  })

  async function loadCustomerOptions() {
    try {
      const response = await loadCustomers(1, 100)
      customers.value = response.items
    } catch {
      customers.value = []
    }
  }

  async function reloadSkills() {
    loading.value = true
    try {
      const response = await loadAllSkillsForKind()
      skills.value = response.items
      skillTotal.value = response.total
      if (response.page !== currentPage.value) {
        currentPage.value = response.page
      }
      if (response.pageSize !== pageSize.value) {
        pageSize.value = response.pageSize
      }
      if (!editor.skillText && viewMode.value === 'list') {
        editor.skillText = defaultSkillText(activeKind.value)
      }
    } finally {
      loading.value = false
    }
  }

  async function loadAllSkillsForKind() {
    const scope =
      customerFilter.value === 'platform'
        ? 'platform'
        : customerFilter.value === 'all'
          ? 'all'
          : 'customer'
    const customerId = scope === 'customer' ? customerFilter.value : null
    return loadSkills(activeKind.value, {
      scope,
      customerId,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      keyword: keyword.value.trim(),
      page: currentPage.value,
      pageSize: pageSize.value,
    })
  }

  function buildSkillKey(kind: SkillKind, scope: 'platform' | 'customer', customerId: string | null | undefined, id: string) {
    return `${kind}:${scope}:${customerId || 'platform'}:${id}`
  }

  function skillKey(item: SkillItem | UnifiedSkill) {
    return buildSkillKey(item.kind, item.customerScope, item.customerId, item.id)
  }

  async function selectSkill(item: SkillItem) {
    await openSkillByRoute(item.customerScope, item.id, item.customerId || null)
  }

  async function openSkillByRoute(
    scope: 'platform' | 'customer',
    skillId: string,
    customerId: string | null = null,
  ) {
    if (!skillId) return
    selectedKey.value = buildSkillKey(activeKind.value, scope, customerId, skillId)
    viewMode.value = 'detail'
    testResult.value = null
    skillSamples.value = []
    skillTestRuns.value = []
    closeValidationDrawer()
    testTab.value = 'config'
    testInstruction.value = ''
    testSampleText.value = ''
    detailLoading.value = true
    try {
      const detail = await loadSkillDetail(
        activeKind.value,
        skillId,
        scope,
        scope === 'customer' ? customerId : null,
        false,
      )
      const merged = { ...detail, kind: activeKind.value }
      const mergedKey = skillKey(merged)
      const exists = skills.value.some((candidate) => skillKey(candidate) === mergedKey)
      skills.value = exists
        ? skills.value.map((candidate) => (skillKey(candidate) === mergedKey ? merged : candidate))
        : [merged, ...skills.value]
      selectedKey.value = mergedKey
      editor.customerId = merged.customerScope === 'customer' ? merged.customerId || '' : ''
      editor.skillText = ''
      assignDraftForm(draftForm, {
        ...defaultDraftForm(activeKind.value),
        id: merged.id,
        version: merged.version,
        name: merged.name,
      })
      await loadPersistedSkillState(merged)
    } catch (error) {
      validationState.value = 'error'
      validationMessage.value = error instanceof Error ? error.message : '读取 Skill 详情失败。'
      editor.customerId = scope === 'customer' ? customerId || '' : ''
      editor.skillText = defaultSkillText(activeKind.value, {
        id: skillId,
        name: skillId,
        version: '1.0.0',
        kind: activeKind.value,
        customerScope: scope,
        customerId,
      } as SkillItem)
      syncDraftFormFromSkillText(draftForm, editor.skillText)
    } finally {
      detailLoading.value = false
    }
    authorMode.value = 'advanced'
    if (validationState.value !== 'error') {
      validationState.value = 'idle'
      validationMessage.value = ''
    }
  }

  function newSkill() {
    selectedKey.value = ''
    viewMode.value = 'detail'
    detailLoading.value = false
    editor.customerId = editor.customerId || customers.value[0]?.id || ''
    editor.skillText = defaultSkillText(activeKind.value)
    resetDraftForm(activeKind.value)
    syncDraftFormFromSkillText(draftForm, editor.skillText)
    authorMode.value = 'guided'
    validationState.value = 'idle'
    validationMessage.value = ''
    testResult.value = null
    testTab.value = 'config'
    skillSamples.value = []
    skillTestRuns.value = []
    closeValidationDrawer()
  }

  function backToList() {
    viewMode.value = 'list'
    detailLoading.value = false
  }

  function openSkillDetail(item: SkillItem) {
    void selectSkill(item)
  }

  function resetDraftForm(kind: SkillKind) {
    assignDraftForm(draftForm, defaultDraftForm(kind))
  }

  function updateDraftForm(field: keyof SkillDraftForm, value: string) {
    draftForm[field] = value
  }

  function syncEditorFromGuidedForm() {
    if (authorMode.value === 'guided' && (!selectedSkill.value || editor.skillText.trim())) {
      editor.skillText = buildSkillTextFromDraft(activeKind.value, draftForm)
    }
  }

  function generateDraftFromForm() {
    syncEditorFromGuidedForm()
    validationState.value = 'idle'
    validationMessage.value = '已同步为 SKILL.md 草稿，可继续试跑或发布。'
  }

  function fillGoalFromTestInstruction() {
    const instruction = testInstruction.value.trim()
    if (!instruction) {
      validationState.value = 'error'
      validationMessage.value = pageCopy.value.fillInstructionMissing
      return
    }
    draftForm.goal = instruction
    validationState.value = 'ok'
    validationMessage.value = pageCopy.value.fillInstructionDone
  }

  function setAuthorMode(mode: AuthorMode) {
    if (mode === 'advanced') {
      if (!selectedSkill.value || editor.skillText.trim()) {
        syncEditorFromGuidedForm()
      }
    } else {
      syncDraftFormFromSkillText(draftForm, editor.skillText)
    }
    authorMode.value = mode
  }

  function handleSkillSelect() {
    if (!selectedKey.value) {
      newSkill()
      return
    }
    const item = skillItems.value.find((candidate) => skillKey(candidate) === selectedKey.value)
    if (item) {
      void selectSkill(item)
    }
  }

  async function requestSkillAssist(instructionOverride = '', includeSampleContext = false) {
    await ensureCurrentSkillTextLoaded()
    syncEditorFromGuidedForm()
    const instruction = instructionOverride.trim() || assistInstruction.value.trim()
    if (!instruction) {
      validationState.value = 'error'
      validationMessage.value = '请先写清楚希望 AI 如何优化当前草稿。'
      return
    }
    assistRunning.value = true
    validationState.value = 'idle'
    validationMessage.value = ''
    try {
      const response = await assistSkill({
        kind: activeKind.value,
        skillText: editor.skillText,
        instruction,
        sampleText: includeSampleContext ? buildSampleContextForAssist() : '',
        customerId: editor.customerId || null,
      })
      editor.skillText = response.skillText
      syncDraftFormFromSkillText(draftForm, response.skillText)
      authorMode.value = 'advanced'
      validationState.value = response.valid ? 'ok' : 'error'
      validationMessage.value = response.valid
        ? `AI 已生成 SKILL.md，模型 ${response.model}，耗时 ${formatDuration(response.durationMs)}。`
        : `AI 已返回草稿，但校验未通过：${response.errors.join('；') || '请继续修正。'}`
    } catch (error) {
      validationState.value = 'error'
      validationMessage.value = error instanceof Error ? error.message : 'AI 辅助调用失败。'
    } finally {
      assistRunning.value = false
    }
  }

  async function validateCurrentSkill() {
    await ensureCurrentSkillTextLoaded()
    syncEditorFromGuidedForm()
    validationState.value = 'idle'
    validationMessage.value = ''
    const response = await validateSkill({
      kind: activeKind.value,
      skillText: editor.skillText,
      customerId: editor.customerId || null,
    })
    validationState.value = response.valid ? 'ok' : 'error'
    validationMessage.value = response.valid
      ? `校验通过：${response.name || response.skillId || 'Skill'}`
      : response.errors.join('；') || '校验失败。'
    return response.valid
  }

  async function runRealSampleTest() {
    await ensureCurrentSkillTextLoaded()
    syncEditorFromGuidedForm()
    validationState.value = 'idle'
    validationMessage.value = ''
    testResult.value = null
    if (!testSampleText.value.trim()) {
      validationState.value = 'error'
      validationMessage.value = pageCopy.value.missingSampleMessage
      testTab.value = 'config'
      return
    }
    testTab.value = 'result'
    testRunning.value = true
    try {
      const response = await testRunSkill({
        kind: activeKind.value,
        skillText: editor.skillText,
        sampleText: testSampleText.value,
        config: {
          userInstruction: testInstruction.value.trim(),
          testInstruction: testInstruction.value.trim(),
        },
        customerId: editor.customerId || null,
        persist: true,
        sampleId: await saveCurrentSampleSnapshot(),
      })
      testResult.value = response
      await refreshCurrentSkillTestRuns()
      validationState.value = response.valid ? 'ok' : 'error'
      validationMessage.value = response.valid
        ? `${pageCopy.value.runSuccess}，耗时 ${formatDuration(response.durationMs)}。`
        : response.errors.join('；') || pageCopy.value.runFailure
    } finally {
      testRunning.value = false
    }
  }

  function formatDuration(value?: number | null) {
    if (!value) return '0 秒'
    return `${(value / 1000).toFixed(2)} 秒`
  }

  function buildSampleContextForAssist() {
    const instruction = testInstruction.value.trim()
    if (!instruction) {
      return testSampleText.value
    }
    return `${pageCopy.value.contextRequirementLabel}：\n${instruction}\n\n样本：\n${testSampleText.value}`
  }

  async function saveSkill() {
    await ensureCurrentSkillTextLoaded()
    const selected = selectedSkill.value
    if (selected?.customerScope === 'platform') {
      validationState.value = 'error'
      validationMessage.value = '平台 Skill 不能直接发布，请先复制到客户后再保存。'
      return
    }
    const targetCustomerId = selected?.customerScope === 'customer' ? selected.customerId || editor.customerId : editor.customerId
    if (!targetCustomerId) {
      validationState.value = 'error'
      validationMessage.value = '请先确定 Skill 归属客户。'
      return
    }
    saving.value = true
    try {
      const valid = await validateCurrentSkill()
      if (!valid) return
      let saved: { id: string }
      if (selected) {
        saved = await updateSkill(selected.id, {
          kind: activeKind.value,
          skillText: editor.skillText,
          customerId: targetCustomerId,
        })
      } else {
        saved = await createSkill({
          kind: activeKind.value,
          skillText: editor.skillText,
          customerId: targetCustomerId,
        })
      }
      editor.customerId = targetCustomerId
      selectedKey.value = buildSkillKey(activeKind.value, 'customer', targetCustomerId, saved.id)
      validationState.value = 'ok'
      validationMessage.value = '已发布，工作台会在刷新 Skill 列表后使用该版本。'
      await reloadSkills()
    } finally {
      saving.value = false
    }
  }

  async function loadPersistedSkillState(item = selectedSkill.value) {
    if (!item?.id) return
    const customerId = item.customerScope === 'customer' ? item.customerId || null : null
    try {
      const [samples, runs] = await Promise.all([
        loadSkillSamples({
          kind: activeKind.value,
          skillId: item.id,
          customerId,
          includeContent: true,
        }),
        loadSkillTestRuns({
          kind: activeKind.value,
          skillId: item.id,
          customerId,
        }),
      ])
      skillSamples.value = samples
      skillTestRuns.value = runs
      selectedTestRunId.value = ''
      selectedTestRunDetail.value = null
      validationDetailError.value = ''
      const latestSample = samples[0]
      if (latestSample) {
        testInstruction.value = latestSample.instruction || testInstruction.value
        const restoredSample = latestSample.content || latestSample.preview || testSampleText.value
        suppressNextSampleResultReset = restoredSample !== testSampleText.value
        testSampleText.value = restoredSample
      }
      if (runs[0]) {
        testResult.value = testRunSummaryToResponse(runs[0])
      }
    } catch {
      skillSamples.value = []
      skillTestRuns.value = []
      selectedTestRunId.value = ''
      selectedTestRunDetail.value = null
      validationDetailError.value = ''
    }
  }

  function applySeededSkillTestSample(seedToken: string | null | undefined) {
    if (!seedToken) {
      return false
    }
    const seed = consumeSkillTestSeed(seedToken)
    if (!seed || seed.kind !== 'operation') {
      return false
    }
    if (seed.skillId !== (selectedSkill.value?.id || currentSkillInfo.value.id)) {
      return false
    }
    testTab.value = 'config'
    testInstruction.value = seed.instruction || testInstruction.value
    suppressNextSampleResultReset = seed.sampleText !== testSampleText.value
    testSampleText.value = seed.sampleText
    testResult.value = null
    validationState.value = 'ok'
    validationMessage.value = '已带入当前任务的提取结果，可直接试跑验证。'
    return true
  }

  async function ensureCurrentSkillTextLoaded() {
    const item = selectedSkill.value
    if (!item?.id || editor.skillText.trim()) return
    skillTextLoading.value = true
    try {
      const detail = await loadSkillDetail(
        activeKind.value,
        item.id,
        item.customerScope,
        item.customerScope === 'customer' ? item.customerId || null : null,
        true,
      )
      const merged = { ...detail, kind: activeKind.value }
      const mergedKey = skillKey(merged)
      const exists = skills.value.some((candidate) => skillKey(candidate) === mergedKey)
      skills.value = exists
        ? skills.value.map((candidate) => (skillKey(candidate) === mergedKey ? merged : candidate))
        : [merged, ...skills.value]
      selectedKey.value = mergedKey
      editor.skillText = merged.skillText || defaultSkillText(activeKind.value, merged)
      syncDraftFormFromSkillText(draftForm, editor.skillText)
    } catch (error) {
      validationState.value = 'error'
      validationMessage.value = error instanceof Error ? error.message : '读取 SKILL.md 正文失败。'
      throw error
    } finally {
      skillTextLoading.value = false
    }
  }

  async function refreshCurrentSkillTestRuns() {
    const info = currentSkillInfo.value
    if (!info.id || info.id === '未命名') return
    const item = selectedSkill.value
    const customerId =
      item?.customerScope === 'customer'
        ? item.customerId || editor.customerId || null
        : item?.customerScope === 'platform'
          ? null
          : editor.customerId || null
    try {
      skillTestRuns.value = await loadSkillTestRuns({
        kind: activeKind.value,
        skillId: info.id,
        customerId,
      })
      selectedTestRunId.value = ''
      selectedTestRunDetail.value = null
      validationDetailError.value = ''
    } catch {
      skillTestRuns.value = []
      selectedTestRunId.value = ''
      selectedTestRunDetail.value = null
      validationDetailError.value = ''
    }
  }

  function openValidationDrawer(tab: 'samples' | 'runs' = 'runs') {
    validationDrawerTab.value = tab
    validationDrawerOpen.value = true
  }

  function closeValidationDrawer() {
    validationDrawerOpen.value = false
    selectedTestRunId.value = ''
    selectedTestRunDetail.value = null
    validationDetailError.value = ''
  }

  async function openTestRunDetail(run: SkillTestRunSummary) {
    const item = selectedSkill.value
    if (!item?.id || !run.id) return
    selectedTestRunId.value = run.id
    validationDetailLoading.value = true
    validationDetailError.value = ''
    try {
      selectedTestRunDetail.value = await loadSkillTestRunDetail({
        kind: activeKind.value,
        skillId: item.id,
        runId: run.id,
        customerId: item.customerScope === 'customer' ? item.customerId || null : null,
      })
    } catch (error) {
      selectedTestRunDetail.value = null
      validationDetailError.value = error instanceof Error ? error.message : '读取试跑详情失败。'
    } finally {
      validationDetailLoading.value = false
    }
  }

  async function saveCurrentSampleSnapshot() {
    const info = currentSkillInfo.value
    const item = selectedSkill.value
    const customerId = item?.customerScope === 'customer' ? item.customerId || editor.customerId : editor.customerId
    if (!customerId || !info.id || info.id === '未命名' || !testSampleText.value.trim()) {
      return null
    }
    try {
      const saved = await saveSkillSample(info.id, {
        kind: activeKind.value,
        skillId: info.id,
        version: info.version || '1.0.0',
        customerId,
        instruction: testInstruction.value.trim(),
        content: testSampleText.value,
        fileName: `${info.id}-sample.txt`,
        contentType: 'text/plain; charset=utf-8',
      })
      skillSamples.value = [saved, ...skillSamples.value.filter((item) => item.id !== saved.id)]
      return saved.id
    } catch {
      return null
    }
  }

  function testRunSummaryToResponse(run: SkillTestRunSummary): SkillTestRunResponse {
    const result = run.result || run.summary || null
    const maybeExtraction = result as unknown as Partial<ExtractionResult> | null
    const extractionResult =
      activeKind.value === 'extraction' && maybeExtraction && Array.isArray(maybeExtraction.outputs)
        ? (result as unknown as ExtractionResult)
        : null
    return {
      valid: run.valid,
      errors: run.errors || [],
      facts: run.facts || {},
      rawOutput: extractionResult ? null : result,
      extractionResult,
      durationMs: run.durationMs,
      provider: run.provider,
      model: run.model,
      inputChars: run.inputChars,
      outputChars: run.outputChars,
    }
  }

  async function copySelectedSkillToCustomer(targetCustomerId: string) {
    const item = selectedSkill.value
    if (!item?.id || !targetCustomerId) return
    const response = await copySkillDraft({
      kind: activeKind.value,
      sourceSkillId: item.id,
      sourceCustomerId: item.customerScope === 'customer' ? item.customerId || null : null,
      targetCustomerId,
    })
    editor.customerId = response.targetCustomerId
    selectedKey.value = ''
    editor.skillText = response.skillText
    syncDraftFormFromSkillText(draftForm, editor.skillText)
    authorMode.value = 'advanced'
    validationState.value = 'ok'
    validationMessage.value = '已复制为目标客户的新草稿，可修改 ID、名称后发布。'
    viewMode.value = 'detail'
  }

  async function moveSelectedSkillOwnership(targetCustomerId: string) {
    const item = selectedSkill.value
    if (!item?.id || item.customerScope !== 'customer' || !item.customerId || !targetCustomerId) return
    const moved = await moveSkillOwnership(item.id, {
      kind: activeKind.value,
      sourceCustomerId: item.customerId,
      targetCustomerId,
    })
    editor.customerId = targetCustomerId
    selectedKey.value = buildSkillKey(activeKind.value, 'customer', targetCustomerId, moved.id)
    editor.skillText = moved.skillText || editor.skillText
    validationState.value = 'ok'
    validationMessage.value = '已修改 Skill 归属。'
    await reloadSkills()
  }

  return {
    activeKind,
    selectedId: computed(() => selectedSkill.value?.id || ''),
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
    skillItems,
    filteredSkillItems,
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
    openSkillDetail,
    openSkillByRoute,
    applySeededSkillTestSample,
    updateDraftForm,
    generateDraftFromForm,
    fillGoalFromTestInstruction,
    setAuthorMode,
    handleSkillSelect,
    requestSkillAssist,
    validateCurrentSkill,
    runRealSampleTest,
    saveSkill,
    openValidationDrawer,
    closeValidationDrawer,
    openTestRunDetail,
    copySelectedSkillToCustomer,
    moveSelectedSkillOwnership,
  }
}
