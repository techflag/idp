// SPDX-FileCopyrightText: 2026 TechFlag
// SPDX-License-Identifier: MIT
export type CapabilityLevel = 'unavailable' | 'demo' | 'basic' | 'limited' | 'full'
export type ConfigurationStatus = 'configured' | 'not_configured' | 'optional' | 'managed'
export type IdpEdition = 'community' | 'commercial'

export interface ProviderRequirementResponse {
  key: string
  label: string
  status: ConfigurationStatus
  required: boolean
  envVars: string[]
  applyUrl?: string | null
  docsUrl?: string | null
  message: string
}

export interface LimitPolicyResponse {
  key: string
  value: number | string | boolean | null
  unit?: string | null
  message: string
}

export interface CapabilityResponse {
  key: string
  label: string
  level: CapabilityLevel
  enabled: boolean
  requiresConfiguration: boolean
  providerKeys: string[]
  limitKeys: string[]
  communityBoundary: string
  commercialBoundary: string
  noConfigurationBehavior?: string | null
}

export interface SystemCapabilitiesResponse {
  edition: IdpEdition
  capabilityRegistryVersion: string
  capabilities: CapabilityResponse[]
  limits: LimitPolicyResponse[]
  providers: ProviderRequirementResponse[]
}

