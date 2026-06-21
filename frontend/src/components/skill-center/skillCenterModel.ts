import type { SkillKind } from '../../types/workbench'
import type { SkillDraftForm, SkillItem, SkillOutputContract, SkillPageCopy, SkillSummary } from './types'

export function buildPageCopy(kind: SkillKind): SkillPageCopy {
  if (kind === 'operation') {
    return {
      assistTitle: 'AI 优化处理规则',
      assistPlaceholder: '例如：把处理结果导出为表格；或补充空值、重复值、日期格式检查规则。',
      guidedTitle: '表单生成处理 Skill',
      guidedDescription: '填写处理目标、适用对象和输出样子；系统字段会自动生成。',
      goalLabel: '要处理什么',
      goalPlaceholder: '例如：检查字段空值和日期格式；或把 records 整理成可导出的表格。',
      rulesLabel: '处理规则，每行一条',
      rulesPlaceholder: '例如：只处理用户选中的提取结果；保留字段名和原始值；不要编造输入中不存在的数据。',
      outputLabel: '期望处理结果 JSON',
      outputPlaceholder: '{\n  "summary": "",\n  "result_kind": "object",\n  "output_payload": {}\n}',
      testTitle: '处理对象试跑',
      testSubtitle: '验证处理规则',
      runButton: '处理试跑',
      configTab: '配置对象',
      resultTab: '处理结果',
      requirementLabel: '本次处理要求',
      requirementPlaceholder: '例如：检查空值、重复值和日期格式；或导出 records 为表格。',
      sampleTitle: '提取结果样本',
      sampleHint: '粘贴字段、表格、records 或处理目标 JSON。',
      rawClosed: '编辑处理对象',
      rawOpen: '粘贴处理对象',
      rawPlaceholder: '粘贴提取结果、字段、表格、records 或处理目标 JSON。',
      previewTitle: '处理对象预览',
      previewEmpty: '上传或粘贴提取结果样本后，会在这里预览。',
      inferButton: '用处理对象反推 Skill',
      missingSampleMessage: '请先上传或粘贴提取结果样本。',
      missingInstructionMessage: '请先填写本次处理要求，再用样本反推 Skill。',
      fillInstructionMissing: '请先在处理对象试跑里填写本次处理要求。',
      fillInstructionDone: '已把本次处理要求带入表单，可继续补充规则和输出结构。',
      runSuccess: '处理对象试跑通过',
      runFailure: '处理对象试跑失败。',
      runningTitle: '正在处理',
      runningText: '正在按当前 Skill 处理样本，完成后会显示处理结果。',
      noResultTitle: '还没有处理结果',
      noResultText: '先在“配置对象”里放入提取结果样本，再点击右上角“处理试跑”。',
      publishAdvice: '发布前建议先用提取结果样本试跑，确认处理输出符合预期。',
      contextRequirementLabel: '本次处理要求',
    }
  }

  return {
    assistTitle: 'AI 优化解析规则',
    assistPlaceholder: '例如：把输出结构改成 basic_info + test_results；或补充更严格的行数保留规则。',
    guidedTitle: '表单生成解析 Skill',
    guidedDescription: '填写提取目标、保留规则和输出样子；系统字段会自动生成。',
    goalLabel: '要提取什么',
    goalPlaceholder: '例如：提取检测报告，样品信息、试验条件是 KV，试验结果按列表返回。',
    rulesLabel: '提取规则，每行一条',
    rulesPlaceholder: '例如：实验结果必须保留所有有效序号；“以下空白”后面的空行不作为数据。',
    outputLabel: '期望输出 JSON',
    outputPlaceholder: '{\n  "basic_info": {},\n  "test_results": []\n}',
    testTitle: '识别样本试跑',
    testSubtitle: '验证当前解析规则',
    runButton: '试跑',
    configTab: '配置样本',
    resultTab: '试跑结果',
    requirementLabel: '本次提取要求',
    requirementPlaceholder: '例如：提取 6 个调色小表，输出 records；每条记录包含调色号、色系、调色价和 components 明细。',
    sampleTitle: '识别结果样本',
    sampleHint: '粘贴识别 JSON、HTML table 或 OCR 文本。',
    rawClosed: '编辑原始内容',
    rawOpen: '粘贴原始内容',
    rawPlaceholder: '粘贴识别结果、HTML table 或 OCR 文本。',
    previewTitle: '识别结果预览',
    previewEmpty: '上传或粘贴识别结果后，会在这里预览。',
    inferButton: '根据样本生成草稿',
    missingSampleMessage: '请先上传或粘贴识别结果样本。',
    missingInstructionMessage: '请先填写本次提取要求，再用样本反推 Skill。',
    fillInstructionMissing: '请先在识别样本试跑里填写本次提取要求。',
    fillInstructionDone: '已把本次提取要求带入表单，可继续补充规则和输出结构。',
    runSuccess: '识别样本试跑通过',
    runFailure: '识别样本试跑失败。',
    runningTitle: '正在试跑',
    runningText: '正在按当前 Skill 和识别样本生成结构化输出，完成后会显示在这里。',
    noResultTitle: '还没有试跑结果',
    noResultText: '先在“配置样本”里放入识别结果样本，再点击右上角“试跑”。',
    publishAdvice: '发布前建议先用识别样本试跑，确认输出符合预期。',
    contextRequirementLabel: '本次提取要求',
  }
}

export function defaultDraftForm(kind: SkillKind): SkillDraftForm {
  if (kind === 'operation') {
    return {
      id: 'custom_operation_sample',
      version: '1.0.0',
      name: '自定义业务处理',
      goal: '描述这个 Skill 要完成的业务处理。',
      rules: '只处理用户选中的提取结果。\n保留字段名和原始值。\n不要编造输入中不存在的数据。',
      outputJson: '{\n  "summary": "",\n  "result_kind": "object",\n  "output_payload": {}\n}',
    }
  }
  return {
    id: 'custom_extraction_sample',
    version: '1.0.0',
    name: '自定义结构化解析',
    goal: '描述要从当前页识别结果中提取什么。',
    rules: '只基于当前页识别结果。\n不要编造。',
    outputJson: '{\n  "headers": [],\n  "rows": []\n}',
  }
}

export function assignDraftForm(target: SkillDraftForm, source: SkillDraftForm) {
  target.id = source.id
  target.version = source.version
  target.name = source.name
  target.goal = source.goal
  target.rules = source.rules
  target.outputJson = source.outputJson
}

export function inferOutputContractFromJson(outputJson: string, kind: SkillKind): SkillOutputContract {
  if (kind === 'operation') {
    return {
      renderer: 'auto',
      outputType: 'object',
      required: [],
      label: 'object / auto',
      description: '业务处理结果由 result_kind 和 output_payload 约束。',
      valid: true,
    }
  }

  const parsed = parseJsonExample(outputJson)
  if (!parsed.valid) {
    return {
      renderer: 'auto',
      outputType: 'custom',
      required: [],
      label: 'custom / auto',
      description: '期望输出 JSON 暂时无法解析，系统会按自定义结构生成草稿。',
      valid: false,
    }
  }

  const value = parsed.value
  if (Array.isArray(value)) {
    const required = inferObjectKeys(value[0])
    return {
      renderer: 'nested_records',
      outputType: 'record_collection',
      required,
      label: 'record_collection / nested_records',
      description: required.length
        ? `根数组会按 records 记录集处理，必填字段：${required.join('、')}。`
        : '根数组会按 records 记录集处理。',
      valid: true,
    }
  }

  if (!isPlainObject(value)) {
    return {
      renderer: 'auto',
      outputType: 'custom',
      required: [],
      label: 'custom / auto',
      description: '期望输出不是对象或数组，系统会按自定义结构生成草稿。',
      valid: true,
    }
  }

  if (Array.isArray(value.records)) {
    const required = inferObjectKeys(value.records[0])
    return {
      renderer: 'nested_records',
      outputType: 'record_collection',
      required,
      label: 'record_collection / nested_records',
      description: required.length
        ? `records 会按记录集处理，必填字段：${required.join('、')}。`
        : 'records 会按记录集处理。',
      valid: true,
    }
  }

  if (Array.isArray(value.headers) && Array.isArray(value.rows)) {
    return {
      renderer: 'data_table',
      outputType: 'data_table',
      required: ['headers', 'rows'],
      label: 'data_table / data_table',
      description: 'headers + rows 会按二维表格处理。',
      valid: true,
    }
  }

  if (Array.isArray(value.fields)) {
    return {
      renderer: 'field_list',
      outputType: 'field_list',
      required: ['fields'],
      label: 'field_list / field_list',
      description: 'fields 会按字段列表处理。',
      valid: true,
    }
  }

  if (isPlainObject(value.kv) && Array.isArray(value.table)) {
    return {
      renderer: 'kv_record_table',
      outputType: 'kv_record_table',
      required: ['kv', 'table'],
      label: 'kv_record_table / kv_record_table',
      description: 'kv + table 会按“键值 + 明细表”处理。',
      valid: true,
    }
  }

  if (isPlainObject(value.kv)) {
    return {
      renderer: 'kv_table',
      outputType: 'kv_table',
      required: ['kv'],
      label: 'kv_table / kv_table',
      description: 'kv 会按键值字段处理。',
      valid: true,
    }
  }

  return {
    renderer: 'custom',
    outputType: 'custom',
    required: [],
    label: 'custom / custom',
    description: '未识别到平台内置结构，系统会按自定义 JSON 处理。',
    valid: true,
  }
}

export function buildSkillTextFromDraft(kind: SkillKind, draftForm: SkillDraftForm): string {
  const rules = draftForm.rules
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => `- ${item}`)
    .join('\n')
  const normalizedId = draftForm.id.trim() || (kind === 'operation' ? 'custom_operation_sample' : 'custom_extraction_sample')
  const normalizedVersion = draftForm.version.trim() || '1.0.0'
  const normalizedName = draftForm.name.trim() || (kind === 'operation' ? '自定义业务处理' : '自定义结构化解析')

  if (kind === 'operation') {
    return `---
id: ${normalizedId}
version: ${normalizedVersion}
name: ${normalizedName}
kind: operation
category: business_operation
status: active
tags: []
targetTypes: [field, table, structured_object, record_collection, record, output]
executor: llm_structured
resultKind: object
renderer: auto
configSchema:
  customInstruction:
    type: textarea
    label: 处理要求
outputSchema:
  type: object
---

# 目标

${draftForm.goal.trim() || '描述这个 Skill 要完成的业务处理。'}

# 规则

${rules || '- 只处理用户选中的提取结果。'}

# 输出格式

\`\`\`json
${draftForm.outputJson.trim() || '{}'}
\`\`\`
`
  }

  const outputContract = inferOutputContractFromJson(draftForm.outputJson, kind)
  const requiredYaml = formatYamlStringList(outputContract.required)

  return `---
id: ${normalizedId}
version: ${normalizedVersion}
name: ${normalizedName}
kind: extraction
category: extraction
enabled: true
status: active
tags: []
sourceTypes: [text, html_table]
executor: llm_structured
input:
  builder: page_compact
renderer: ${outputContract.renderer}
output:
  type: ${outputContract.outputType}${requiredYaml ? `\n  required: ${requiredYaml}` : ''}
---

# 目标

${draftForm.goal.trim() || '描述要从当前页识别结果中提取什么。'}

# 规则

${rules || '- 只基于当前页识别结果。'}

# 输出格式

\`\`\`json
${draftForm.outputJson.trim() || '{}'}
\`\`\`
`
}

function parseJsonExample(value: string): { valid: true; value: unknown } | { valid: false } {
  const trimmed = value.trim()
  if (!trimmed) return { valid: false }
  try {
    return { valid: true, value: JSON.parse(trimmed) }
  } catch {
    return { valid: false }
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function inferObjectKeys(value: unknown) {
  if (!isPlainObject(value)) return []
  return Object.keys(value).filter((key) => key.trim())
}

function formatYamlStringList(values: string[]) {
  if (!values.length) return ''
  return `[${values.map((value) => JSON.stringify(value)).join(', ')}]`
}

export function defaultSkillText(kind: SkillKind, seed?: SkillItem): string {
  if (seed?.skillText) return seed.skillText
  return buildSkillTextFromDraft(kind, defaultDraftForm(kind))
}

export function formatExecutorLabel(executor: string) {
  const labels: Record<string, string> = {
    llm_structured: 'AI 结构化处理',
    local_transform: '本地规则转换',
    quality_check: '质量检查',
    export_data: '数据导出',
    http_connector: '第三方接口',
    controlled_python: '受控脚本',
    external_connector: '外部连接器',
  }
  return labels[executor] || executor || '自动选择'
}

export function parseSkillSummary(skillText: string): SkillSummary {
  const frontmatter = skillText.match(/^---\n([\s\S]*?)\n---/)?.[1] || ''
  const read = (key: string) => {
    const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return frontmatter.match(new RegExp(`^${escapedKey}:\\s*(.+)$`, 'm'))?.[1]?.trim() || ''
  }
  return {
    id: read('id') || '未命名',
    name: read('name') || '未填写名称',
    version: read('version') || '未填写版本',
    executor: read('executor') || '未填写执行器',
  }
}

export function syncDraftFormFromSkillText(draftForm: SkillDraftForm, skillText: string) {
  const summary = parseSkillSummary(skillText)
  if (summary.id !== '未命名') draftForm.id = summary.id
  if (summary.version !== '未填写版本') draftForm.version = summary.version
  if (summary.name !== '未填写名称') draftForm.name = summary.name
  const goal = extractMarkdownSection(skillText, '目标')
  if (goal) {
    draftForm.goal = goal
  }
  const rules = extractRulesFromSkillText(skillText)
  if (rules.length) {
    draftForm.rules = rules.join('\n')
  }
  const outputJson = extractJsonCodeBlock(skillText)
  if (outputJson) {
    draftForm.outputJson = outputJson
  }
}

function extractMarkdownSection(skillText: string, heading: string) {
  const match = skillText.match(new RegExp(`^#\\s+${heading}\\s*\\n([\\s\\S]*?)(?=\\n#\\s+|$)`, 'm'))
  return match?.[1]?.trim() || ''
}

function extractRulesFromSkillText(skillText: string) {
  const frontmatter = skillText.match(/^---\n([\s\S]*?)\n---/)?.[1] || ''
  const rules: string[] = []
  const frontRules = frontmatter.match(/^rules:\s*\n([\s\S]*?)(?=\n\S|$)/m)?.[1] || ''
  frontRules.split('\n').forEach((line) => {
    const value = line.match(/^\s*-\s*(.+)$/)?.[1]?.trim()
    if (value) rules.push(value)
  })
  if (rules.length) return rules
  const bodyRules = extractMarkdownSection(skillText, '规则')
  bodyRules.split('\n').forEach((line) => {
    const value = line.match(/^\s*-\s*(.+)$/)?.[1]?.trim()
    if (value) rules.push(value)
  })
  return rules
}

function extractJsonCodeBlock(skillText: string) {
  return skillText.match(/```json\s*([\s\S]*?)```/i)?.[1]?.trim() || ''
}
