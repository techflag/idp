from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.dependencies import require_capability_available, require_capability_level
from app.core.config import get_settings
from app.core.edition_policy import MINERU_APPLY_URL, build_system_capabilities, is_capability_available
from app.services.oss import AliyunOssStorageService, LocalObjectStorageService, build_oss_storage_service
from app.services.skill_assist_service import call_sample_extraction_assistant


def test_community_capabilities_report_missing_provider_configuration(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MINERU_TOKEN", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "")

    try:
        capabilities = build_system_capabilities(get_settings())
    finally:
        get_settings.cache_clear()

    providers = {provider.key: provider for provider in capabilities.providers}
    assert capabilities.edition == "community"
    assert providers["mineru"].status == "not_configured"
    assert providers["mineru"].applyUrl == MINERU_APPLY_URL
    assert providers["llm.dashscope"].status == "not_configured"

    by_key = {capability.key: capability for capability in capabilities.capabilities}
    assert by_key["document.run"].level == "limited"
    assert by_key["document.run"].requiresConfiguration is True
    assert by_key["document.run"].enabled is False
    assert by_key["document.longRun"].level == "unavailable"
    assert by_key["document.longRun"].enabled is False
    assert by_key["document.longRun"].requiresConfiguration is False
    assert by_key["application.authoring"].level == "limited"
    assert by_key["application.authoring"].executionMode == "single_page_lite_authoring"
    assert by_key["application.authoring"].enabled is False
    assert by_key["application.authoring"].requiresConfiguration is True
    assert by_key["application.run"].level == "limited"
    assert by_key["application.run"].executionMode == "single_page_lite_run"
    assert by_key["application.run"].enabled is False
    assert by_key["application.run"].requiresConfiguration is True
    assert by_key["skill.prototypeOptimization"].level == "unavailable"
    assert by_key["skill.prototypeOptimization"].enabled is False
    assert by_key["skill.prototypeOptimization"].executionMode == "stub_only"
    assert by_key["skill.prototypeOptimization"].implementation == "public_stub"

    limits = {limit.key: limit for limit in capabilities.limits}
    assert limits["maxPagesPerRun"].value == 1
    assert limits["longDocument"].value == "not_shipped"


def test_community_configured_providers_do_not_enable_long_document(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MINERU_TOKEN", "token")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "key")

    try:
        settings = get_settings()
        capabilities = build_system_capabilities(settings)
    finally:
        get_settings.cache_clear()

    by_key = {capability.key: capability for capability in capabilities.capabilities}
    assert by_key["document.run"].level == "limited"
    assert by_key["document.run"].enabled is True
    assert is_capability_available(settings, "document.run") is True
    assert by_key["document.longRun"].level == "unavailable"
    assert by_key["document.longRun"].enabled is False
    assert by_key["document.longRun"].requiresConfiguration is False
    assert by_key["application.authoring"].level == "limited"
    assert by_key["application.authoring"].executionMode == "single_page_lite_authoring"
    assert by_key["application.authoring"].enabled is True
    assert is_capability_available(settings, "application.authoring") is True
    assert by_key["application.run"].level == "limited"
    assert by_key["application.run"].executionMode == "single_page_lite_run"
    assert by_key["application.run"].enabled is True
    assert is_capability_available(settings, "application.run") is True
    assert by_key["skill.prototypeOptimization"].level == "unavailable"
    assert by_key["skill.prototypeOptimization"].enabled is False
    assert by_key["skill.prototypeOptimization"].executionMode == "stub_only"
    assert by_key["skill.prototypeOptimization"].implementation == "public_stub"


def test_community_application_authoring_full_dependency_is_blocked(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MINERU_TOKEN", "token")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "key")

    try:
        settings = get_settings()
        require_capability_available("application.authoring")(settings)
        with pytest.raises(HTTPException) as exc_info:
            require_capability_level("application.authoring", "full")(settings)
    finally:
        get_settings.cache_clear()

    assert exc_info.value.status_code == 403
    assert "不包含 full 完整链路" in str(exc_info.value.detail)
    assert "单页 Lite" in str(exc_info.value.detail)


def test_community_skill_prototype_optimization_is_unavailable(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MINERU_TOKEN", "token")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "key")

    try:
        settings = get_settings()
        capabilities = build_system_capabilities(settings)
        by_key = {capability.key: capability for capability in capabilities.capabilities}
        with pytest.raises(HTTPException) as exc_info:
            require_capability_available("skill.prototypeOptimization")(settings)
    finally:
        get_settings.cache_clear()

    assert by_key["skill.prototypeOptimization"].level == "unavailable"
    assert by_key["skill.prototypeOptimization"].executionMode == "stub_only"
    assert by_key["skill.prototypeOptimization"].implementation == "public_stub"
    assert by_key["skill.prototypeOptimization"].enabled is False
    assert exc_info.value.status_code == 403
    assert "SkillOpt" in str(exc_info.value.detail)


def test_commercial_capabilities_can_report_full_long_document(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "commercial")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MINERU_TOKEN", "token")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "key")

    try:
        capabilities = build_system_capabilities(get_settings())
    finally:
        get_settings.cache_clear()

    by_key = {capability.key: capability for capability in capabilities.capabilities}
    assert capabilities.edition == "commercial"
    assert by_key["document.longRun"].level == "full"
    assert by_key["document.longRun"].enabled is True
    assert by_key["document.longRun"].executionMode == "full_long_document_run"
    assert by_key["application.authoring"].level == "full"
    assert by_key["application.authoring"].enabled is True
    assert by_key["application.authoring"].executionMode == "full_application_authoring"
    assert by_key["application.run"].level == "full"
    assert by_key["application.run"].enabled is True
    assert by_key["application.run"].executionMode == "full_application_run"
    assert by_key["skill.prototypeOptimization"].level == "full"
    assert by_key["skill.prototypeOptimization"].enabled is True
    assert by_key["skill.prototypeOptimization"].executionMode == "full_skill_optimization"
    assert by_key["skill.prototypeOptimization"].implementation == "commercial_extension"

    limits = {limit.key: limit for limit in capabilities.limits}
    assert limits["maxPagesPerRun"].value == "unlimited"
    assert limits["longDocument"].value == "full"


def test_sample_extraction_missing_llm_key_returns_configuration_error(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")

    try:
        with pytest.raises(HTTPException) as exc_info:
            call_sample_extraction_assistant(
                instruction="提取字段",
                expected_output="JSON",
                sample_text="样例文本",
            )
    finally:
        get_settings.cache_clear()

    assert exc_info.value.status_code == 400
    assert "BYO OpenAI-compatible" in str(exc_info.value.detail)


def test_community_storage_falls_back_to_local_when_oss_is_missing(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "auto")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "")

    try:
        settings = get_settings()
        storage = build_oss_storage_service(settings)
    finally:
        get_settings.cache_clear()

    assert isinstance(storage, LocalObjectStorageService)
    uploaded = storage.upload_file(
        customerId="community-scenario-app",
        fileName="sample.txt",
        contentType="text/plain; charset=utf-8",
        data="本地对象".encode("utf-8"),
    )
    assert uploaded.provider == "local-object-storage"
    assert uploaded.publicUrl.startswith("/api/objects/")


def test_local_storage_can_emit_public_backend_urls(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "local")
    monkeypatch.setenv("BACKEND_PUBLIC_BASE_URL", "https://idp-public.example.com")

    try:
        settings = get_settings()
        storage = build_oss_storage_service(settings)
    finally:
        get_settings.cache_clear()

    assert isinstance(storage, LocalObjectStorageService)
    content = "公网地址对象"
    uploaded = storage.upload_file(
        customerId="community-scenario-app",
        fileName="sample.txt",
        contentType="text/plain; charset=utf-8",
        data=content.encode("utf-8"),
    )
    assert uploaded.publicUrl.startswith("https://idp-public.example.com/api/objects/")
    assert storage.read_text_object(objectKey=uploaded.objectKey) == content


def test_storage_uses_aliyun_when_oss_credentials_are_configured(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "auto")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "test-access-key-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "test-access-key-secret")
    monkeypatch.setenv("OSS_BUCKET", "test-bucket")
    monkeypatch.setenv("OSS_REGION", "cn-test")
    monkeypatch.setenv("OSS_PUBLIC_BASE_URL", "https://oss.example.test")

    try:
        storage = build_oss_storage_service(get_settings())
    finally:
        get_settings.cache_clear()

    assert isinstance(storage, AliyunOssStorageService)


def test_storage_provider_local_overrides_configured_oss(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "local")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "test-access-key-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "test-access-key-secret")

    try:
        storage = build_oss_storage_service(get_settings())
    finally:
        get_settings.cache_clear()

    assert isinstance(storage, LocalObjectStorageService)
