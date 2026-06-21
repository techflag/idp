export function cloneJson<T>(value: T | null | undefined): Record<string, unknown> | T | null {
  if (value === undefined || value === null) return null
  return JSON.parse(JSON.stringify(value))
}

export function plainRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
