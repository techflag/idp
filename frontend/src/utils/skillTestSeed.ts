export interface SkillTestSeedPayload {
  kind: 'operation'
  skillId: string
  skillVersion?: string
  skillScope: 'platform' | 'customer'
  customerId?: string | null
  instruction?: string
  sampleText: string
  sourceTaskId?: string
  sourcePageNo?: number
}

const STORAGE_PREFIX = 'idp.skill-test-seed:'

export function storeSkillTestSeed(payload: SkillTestSeedPayload): string {
  const token = `${Date.now()}-${Math.random().toString(16).slice(2)}`
  window.sessionStorage.setItem(`${STORAGE_PREFIX}${token}`, JSON.stringify(payload))
  return token
}

export function consumeSkillTestSeed(token: string): SkillTestSeedPayload | null {
  if (!token) {
    return null
  }
  const key = `${STORAGE_PREFIX}${token}`
  const raw = window.sessionStorage.getItem(key)
  if (!raw) {
    return null
  }
  window.sessionStorage.removeItem(key)
  try {
    const parsed = JSON.parse(raw) as Partial<SkillTestSeedPayload>
    if (parsed.kind !== 'operation' || typeof parsed.skillId !== 'string' || typeof parsed.sampleText !== 'string') {
      return null
    }
    return {
      kind: 'operation',
      skillId: parsed.skillId,
      skillVersion: typeof parsed.skillVersion === 'string' ? parsed.skillVersion : undefined,
      skillScope: parsed.skillScope === 'customer' ? 'customer' : 'platform',
      customerId: typeof parsed.customerId === 'string' ? parsed.customerId : null,
      instruction: typeof parsed.instruction === 'string' ? parsed.instruction : '',
      sampleText: parsed.sampleText,
      sourceTaskId: typeof parsed.sourceTaskId === 'string' ? parsed.sourceTaskId : undefined,
      sourcePageNo: typeof parsed.sourcePageNo === 'number' ? parsed.sourcePageNo : undefined,
    }
  } catch {
    return null
  }
}
