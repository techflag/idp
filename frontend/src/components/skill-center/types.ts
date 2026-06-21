import type { BusinessSkill, CustomerSummary, ExtractionSkill, SkillKind } from '../../types/workbench'

export type SkillItem = (BusinessSkill | ExtractionSkill) & { kind: SkillKind }
export type AuthorMode = 'guided' | 'advanced'
export type TestTab = 'config' | 'result' | 'publish'
export type ValidationState = 'idle' | 'ok' | 'error'

export interface SkillOption {
  label: string
  value: string
}

export interface SkillDraftForm {
  id: string
  version: string
  name: string
  goal: string
  rules: string
  outputJson: string
}

export interface SkillOutputContract {
  renderer: string
  outputType: string
  required: string[]
  label: string
  description: string
  valid: boolean
}

export interface SkillSummary {
  id: string
  name: string
  version: string
  executor: string
}

export interface SkillPublishCheck {
  label: string
  value: string
  ok: boolean
}

export interface SkillPageCopy {
  assistTitle: string
  assistPlaceholder: string
  guidedTitle: string
  guidedDescription: string
  goalLabel: string
  goalPlaceholder: string
  rulesLabel: string
  rulesPlaceholder: string
  outputLabel: string
  outputPlaceholder: string
  testTitle: string
  testSubtitle: string
  runButton: string
  configTab: string
  resultTab: string
  requirementLabel: string
  requirementPlaceholder: string
  sampleTitle: string
  sampleHint: string
  rawClosed: string
  rawOpen: string
  rawPlaceholder: string
  previewTitle: string
  previewEmpty: string
  inferButton: string
  missingSampleMessage: string
  missingInstructionMessage: string
  fillInstructionMissing: string
  fillInstructionDone: string
  runSuccess: string
  runFailure: string
  runningTitle: string
  runningText: string
  noResultTitle: string
  noResultText: string
  publishAdvice: string
  contextRequirementLabel: string
}

export type CustomerOption = Pick<CustomerSummary, 'id' | 'name'>
