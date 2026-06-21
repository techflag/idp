"""System capability and edition schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CapabilityLevel = Literal["unavailable", "demo", "basic", "limited", "full"]
ConfigurationStatus = Literal["configured", "not_configured", "optional", "managed"]
Edition = Literal["community", "commercial"]


class ProviderRequirementResponse(BaseModel):
    key: str
    label: str
    status: ConfigurationStatus
    required: bool
    envVars: list[str] = Field(default_factory=list)
    applyUrl: str | None = None
    docsUrl: str | None = None
    message: str


class LimitPolicyResponse(BaseModel):
    key: str
    value: int | str | bool | None
    unit: str | None = None
    message: str


class CapabilityResponse(BaseModel):
    key: str
    label: str
    level: CapabilityLevel
    executionMode: str
    implementation: str
    enabled: bool
    requiresConfiguration: bool = False
    providerKeys: list[str] = Field(default_factory=list)
    limitKeys: list[str] = Field(default_factory=list)
    communityBoundary: str
    commercialBoundary: str
    noConfigurationBehavior: str | None = None


class SystemCapabilitiesResponse(BaseModel):
    edition: Edition
    capabilityRegistryVersion: str
    capabilities: list[CapabilityResponse]
    limits: list[LimitPolicyResponse]
    providers: list[ProviderRequirementResponse]
