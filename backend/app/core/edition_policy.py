"""Central edition capability registry.

Business code should consume capability decisions from this module instead of
scattering edition checks across route handlers and services.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import AppSettings
from app.schemas.system import (
    CapabilityResponse,
    LimitPolicyResponse,
    ProviderRequirementResponse,
    SystemCapabilitiesResponse,
)

CAPABILITY_REGISTRY_VERSION = "2026-06-21.v1"
MINERU_APPLY_URL = "https://mineru.net/?source=github"


@dataclass(frozen=True)
class ProviderRequirement:
    key: str
    label: str
    required: bool
    env_vars: tuple[str, ...]
    apply_url: str | None
    docs_url: str | None
    message_configured: str
    message_not_configured: str


@dataclass(frozen=True)
class LimitPolicy:
    key: str
    community_value: int | str | bool | None
    commercial_value: int | str | bool | None
    unit: str | None
    community_message: str
    commercial_message: str


@dataclass(frozen=True)
class EditionCapability:
    key: str
    label: str
    community_level: str
    commercial_level: str
    community_mode: str
    commercial_mode: str
    community_implementation: str
    commercial_implementation: str
    provider_keys: tuple[str, ...]
    limit_keys: tuple[str, ...]
    community_boundary: str
    commercial_boundary: str
    no_configuration_behavior: str | None = None


PROVIDER_REQUIREMENTS: tuple[ProviderRequirement, ...] = (
    ProviderRequirement(
        key="mineru",
        label="MinerU Document Parser",
        required=True,
        env_vars=("MINERU_TOKEN",),
        apply_url=MINERU_APPLY_URL,
        docs_url=None,
        message_configured="MinerU Token 已配置，可发起真实文档解析。",
        message_not_configured="未配置 MinerU Token，请先申请并配置后再发起真实解析。",
    ),
    ProviderRequirement(
        key="llm.dashscope",
        label="OpenAI-compatible LLM",
        required=True,
        env_vars=("DASHSCOPE_API_KEY",),
        apply_url=None,
        docs_url=None,
        message_configured="LLM Key 已配置，可发起真实 AI 抽取。",
        message_not_configured="未配置 LLM Key，可浏览样例；真实 AI 抽取需要配置 BYO Model。",
    ),
    ProviderRequirement(
        key="storage.oss",
        label="Object Storage",
        required=False,
        env_vars=("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"),
        apply_url=None,
        docs_url=None,
        message_configured="OSS 已配置，可使用对象存储。",
        message_not_configured="OSS 未配置；系统将使用本地 runtime 对象存储。",
    ),
)


LIMIT_POLICIES: tuple[LimitPolicy, ...] = (
    LimitPolicy(
        key="maxPagesPerRun",
        community_value=1,
        commercial_value="unlimited",
        unit="page",
        community_message="社区版每次运行只能选择 1 页，不能静默截断整份文档。",
        commercial_message="商业版支持整份长文档运行，具体上限由部署策略决定。",
    ),
    LimitPolicy(
        key="longDocument",
        community_value="not_shipped",
        commercial_value="full",
        unit=None,
        community_message="社区仓库不包含完整长文档链路；公开体验只保留单页/基础流程。",
        commercial_message="商业版通过私有扩展提供完整长文档链路。",
    ),
    LimitPolicy(
        key="batchRun",
        community_value=False,
        commercial_value=True,
        unit=None,
        community_message="社区版不提供生产级批量任务编排。",
        commercial_message="商业版可提供批量、并发和失败恢复。",
    ),
)


CAPABILITIES: tuple[EditionCapability, ...] = (
    EditionCapability(
        key="document.parse",
        label="文档解析",
        community_level="limited",
        commercial_level="full",
        community_mode="single_page_lite",
        commercial_mode="full_document_parse",
        community_implementation="shared_core",
        commercial_implementation="commercial_extension",
        provider_keys=("mineru",),
        limit_keys=("maxPagesPerRun", "longDocument"),
        community_boundary="MinerU 可配置，社区仓库保留单页/基础解析体验。",
        commercial_boundary="商业版可提供托管解析、长文档和批量解析。",
        no_configuration_behavior=f"缺少 MinerU Token 时提示申请链接 {MINERU_APPLY_URL}，不进入 pending。",
    ),
    EditionCapability(
        key="document.run",
        label="文档运行",
        community_level="limited",
        commercial_level="full",
        community_mode="single_page_lite",
        commercial_mode="full_document_run",
        community_implementation="public_lite",
        commercial_implementation="commercial_extension",
        provider_keys=("mineru", "llm.dashscope"),
        limit_keys=("maxPagesPerRun", "longDocument"),
        community_boundary="允许上传多页文档但每次只能选择 1 页运行，社区仓库不包含完整长文档链路。",
        commercial_boundary="商业版支持整份长文档异步运行、跨页证据选择和完整审计。",
        no_configuration_behavior="缺少解析或 LLM 配置时展示配置指引，不发起会长期 pending 的真实运行。",
    ),
    EditionCapability(
        key="llm.extract",
        label="AI 抽取",
        community_level="basic",
        commercial_level="full",
        community_mode="basic_byo_llm",
        commercial_mode="full_llm_extract",
        community_implementation="shared_core",
        commercial_implementation="commercial_extension",
        provider_keys=("llm.dashscope",),
        limit_keys=(),
        community_boundary="社区版使用 BYO OpenAI-compatible 模型，缺少 Key 时可浏览样例。",
        commercial_boundary="商业版可提供托管模型、成本控制和企业模型治理。",
        no_configuration_behavior="缺少 LLM Key 时提示 BYO Model 配置，不发起真实抽取。",
    ),
    EditionCapability(
        key="skill.prototypeOptimization",
        label="Skill 候选优化",
        community_level="unavailable",
        commercial_level="full",
        community_mode="stub_only",
        commercial_mode="full_skill_optimization",
        community_implementation="public_stub",
        commercial_implementation="commercial_extension",
        provider_keys=("llm.dashscope",),
        limit_keys=(),
        community_boundary="社区版不暴露 SkillOpt/SkillNet 候选优化链路，公开体验以手工确认和样例试跑为准。",
        commercial_boundary="商业版或内部版本可启用候选优化、训练评测、发布门禁和私有 SkillNet 流程。",
        no_configuration_behavior="社区版隐藏入口；商业版未配置模型提供方时不得启动会长期 pending 的候选优化任务。",
    ),
    EditionCapability(
        key="document.longRun",
        label="长文档运行",
        community_level="unavailable",
        commercial_level="full",
        community_mode="stub_only",
        commercial_mode="full_long_document_run",
        community_implementation="public_stub",
        commercial_implementation="commercial_extension",
        provider_keys=("mineru", "llm.dashscope"),
        limit_keys=("maxPagesPerRun", "longDocument"),
        community_boundary="社区仓库不包含完整长文档执行器、跨页计划器或商业恢复链路；公开体验只保留单页/基础流程。",
        commercial_boundary="跨页证据索引、长文档队列、长表格复核、完整审计和失败恢复属于商业私有扩展。",
    ),
    EditionCapability(
        key="application.authoring",
        label="文档应用制作",
        community_level="limited",
        commercial_level="full",
        community_mode="single_page_lite_authoring",
        commercial_mode="full_application_authoring",
        community_implementation="public_lite_or_stub",
        commercial_implementation="commercial_extension",
        provider_keys=("mineru", "llm.dashscope"),
        limit_keys=("longDocument",),
        community_boundary="社区版只开放单页 Lite 应用体验；完整工作坊、步骤编排、样板固化、发布和应用市场属于商业完整链路。",
        commercial_boundary="商业版提供完整文档应用制作、步骤编排、样板资产固化、发布和版本管理。",
        no_configuration_behavior="缺少 provider 配置时展示配置提示；社区版不得启动完整应用制作或发布链路。",
    ),
    EditionCapability(
        key="application.run",
        label="文档应用运行",
        community_level="limited",
        commercial_level="full",
        community_mode="single_page_lite_run",
        commercial_mode="full_application_run",
        community_implementation="public_lite_or_stub",
        commercial_implementation="commercial_extension",
        provider_keys=("mineru", "llm.dashscope"),
        limit_keys=("longDocument", "batchRun"),
        community_boundary="社区版只允许单页 Lite 或样例运行；完整文档应用运行、跨页定位、长文档执行和商业恢复链路不进入社区仓库。",
        commercial_boundary="商业版提供应用运行、跨页证据定位、多步骤执行、失败恢复和审计。",
        no_configuration_behavior="缺少 provider 配置时展示配置提示；社区版不得启动完整应用运行链路。",
    ),
    EditionCapability(
        key="batch.run",
        label="批量运行",
        community_level="unavailable",
        commercial_level="full",
        community_mode="stub_only",
        commercial_mode="full_batch_run",
        community_implementation="public_stub",
        commercial_implementation="commercial_extension",
        provider_keys=(),
        limit_keys=("batchRun",),
        community_boundary="社区版不展示生产级批量运行入口。",
        commercial_boundary="商业版可提供批量任务编排、并发控制和失败恢复。",
    ),
    EditionCapability(
        key="audit.compliance",
        label="审计合规",
        community_level="basic",
        commercial_level="full",
        community_mode="basic_runtime_log",
        commercial_mode="full_compliance_audit",
        community_implementation="shared_core",
        commercial_implementation="commercial_extension",
        provider_keys=(),
        limit_keys=(),
        community_boundary="社区版仅提供基础运行日志，不宣称合规审计。",
        commercial_boundary="商业版可提供审计时间线、权限追溯和合规导出。",
    ),
)


def get_capability_policy(key: str) -> EditionCapability | None:
    for capability in CAPABILITIES:
        if capability.key == key:
            return capability
    return None


def capability_level(settings: AppSettings, key: str) -> str:
    capability = get_capability_policy(key)
    if capability is None:
        return "unavailable"
    return capability.commercial_level if settings.idp_edition == "commercial" else capability.community_level


def capability_execution_mode(settings: AppSettings, key: str) -> str:
    capability = get_capability_policy(key)
    if capability is None:
        return "stub_only"
    return capability.commercial_mode if settings.idp_edition == "commercial" else capability.community_mode


def capability_implementation(settings: AppSettings, key: str) -> str:
    capability = get_capability_policy(key)
    if capability is None:
        return "public_stub"
    return (
        capability.commercial_implementation
        if settings.idp_edition == "commercial"
        else capability.community_implementation
    )


def is_capability_available(settings: AppSettings, key: str) -> bool:
    return capability_level(settings, key) != "unavailable"


def capability_unavailable_message(settings: AppSettings, key: str) -> str:
    capability = get_capability_policy(key)
    if capability is None:
        return f"当前部署未注册能力：{key}"
    if settings.idp_edition == "commercial":
        return capability.commercial_boundary
    return capability.community_boundary


def _provider_status(provider: ProviderRequirement, settings: AppSettings) -> str:
    if settings.idp_edition == "commercial" and provider.key in {"llm.dashscope"}:
        # Commercial deployments can replace public BYO keys with managed/private providers.
        return "configured" if _provider_configured(provider, settings) else "managed"
    if provider.required:
        return "configured" if _provider_configured(provider, settings) else "not_configured"
    return "configured" if _provider_configured(provider, settings) else "optional"


def _provider_configured(provider: ProviderRequirement, settings: AppSettings) -> bool:
    values = {
        "MINERU_TOKEN": settings.mineru_token,
        "DASHSCOPE_API_KEY": settings.dashscope_api_key,
        "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
        "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
    }
    return all(values.get(env_name) for env_name in provider.env_vars)


def _provider_response(provider: ProviderRequirement, settings: AppSettings) -> ProviderRequirementResponse:
    status = _provider_status(provider, settings)
    configured = status in {"configured", "managed"}
    return ProviderRequirementResponse(
        key=provider.key,
        label=provider.label,
        status=status,  # type: ignore[arg-type]
        required=provider.required,
        envVars=list(provider.env_vars),
        applyUrl=provider.apply_url,
        docsUrl=provider.docs_url,
        message=provider.message_configured if configured else provider.message_not_configured,
    )


def _limit_response(limit: LimitPolicy, settings: AppSettings) -> LimitPolicyResponse:
    if settings.idp_edition == "commercial":
        return LimitPolicyResponse(
            key=limit.key,
            value=limit.commercial_value,
            unit=limit.unit,
            message=limit.commercial_message,
        )
    return LimitPolicyResponse(
        key=limit.key,
        value=limit.community_value,
        unit=limit.unit,
        message=limit.community_message,
    )


def _capability_response(capability: EditionCapability, settings: AppSettings) -> CapabilityResponse:
    level = capability.commercial_level if settings.idp_edition == "commercial" else capability.community_level
    execution_mode = capability.commercial_mode if settings.idp_edition == "commercial" else capability.community_mode
    implementation = (
        capability.commercial_implementation
        if settings.idp_edition == "commercial"
        else capability.community_implementation
    )
    providers = {provider.key: _provider_status(provider, settings) for provider in PROVIDER_REQUIREMENTS}
    unavailable = level == "unavailable"
    requires_configuration = False if unavailable else any(providers.get(key) == "not_configured" for key in capability.provider_keys)
    return CapabilityResponse(
        key=capability.key,
        label=capability.label,
        level=level,  # type: ignore[arg-type]
        executionMode=execution_mode,
        implementation=implementation,
        enabled=not unavailable and not requires_configuration,
        requiresConfiguration=requires_configuration,
        providerKeys=list(capability.provider_keys),
        limitKeys=list(capability.limit_keys),
        communityBoundary=capability.community_boundary,
        commercialBoundary=capability.commercial_boundary,
        noConfigurationBehavior=capability.no_configuration_behavior,
    )


def build_system_capabilities(settings: AppSettings) -> SystemCapabilitiesResponse:
    """Return the capability matrix for the current deployment."""

    return SystemCapabilitiesResponse(
        edition=settings.idp_edition,  # type: ignore[arg-type]
        capabilityRegistryVersion=CAPABILITY_REGISTRY_VERSION,
        capabilities=[_capability_response(capability, settings) for capability in CAPABILITIES],
        limits=[_limit_response(limit, settings) for limit in LIMIT_POLICIES],
        providers=[_provider_response(provider, settings) for provider in PROVIDER_REQUIREMENTS],
    )
