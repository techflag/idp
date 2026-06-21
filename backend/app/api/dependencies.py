"""Dependency providers shared by API routes."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from app.core.config import AppSettings, get_settings
from app.core.edition_policy import capability_level, capability_unavailable_message, is_capability_available
from app.repositories.mysql_repository import MysqlWorkbenchRepository
from app.repositories.protocols import WorkbenchRepository
from app.schemas.auth import AuthUserResponse
from app.services.auth import SessionUser
from app.services.business_skills import BusinessSkillRegistry
from app.services.db_auth import DbAuthService
from app.services.extraction_skills import ExtractionSkillRegistry
from app.services.llm import DashScopePromptLlmService, PromptLlmService
from app.services.mineru import MineruService, build_mineru_service
from app.services.oss import OssStorageService, build_oss_storage_service
from app.services.parse_pipeline import ParsePipelineService
from app.services.prompt_pipeline import PromptPipelineService
from app.services.runtime_store import JsonRuntimeStore
from app.services.semantic_locator import SemanticLocatorReranker
from app.services.semantic_locator_reranker import DashScopeSemanticLocatorReranker


@lru_cache(maxsize=1)
def get_repository() -> WorkbenchRepository:
    return MysqlWorkbenchRepository(get_runtime_store(), get_settings(), get_oss_service())


@lru_cache(maxsize=1)
def get_oss_service() -> OssStorageService:
    return build_oss_storage_service(get_settings())


@lru_cache(maxsize=1)
def get_mineru_service() -> MineruService:
    return build_mineru_service(get_settings())


@lru_cache(maxsize=1)
def get_runtime_store() -> JsonRuntimeStore:
    return JsonRuntimeStore(get_settings())


@lru_cache(maxsize=1)
def get_prompt_llm_service() -> PromptLlmService:
    return DashScopePromptLlmService(get_settings())


@lru_cache(maxsize=1)
def get_semantic_locator_reranker() -> SemanticLocatorReranker | None:
    settings = get_settings()
    if not settings.semantic_locator_llm_rerank_enabled or not settings.dashscope_api_key:
        return None
    return DashScopeSemanticLocatorReranker(settings)


@lru_cache(maxsize=1)
def get_parse_pipeline_service() -> ParsePipelineService:
    return ParsePipelineService(
        repository=get_repository(),
        oss_service=get_oss_service(),
        mineru_service=get_mineru_service(),
        runtime_store=get_runtime_store(),
        settings=get_settings(),
    )


@lru_cache(maxsize=1)
def get_prompt_pipeline_service() -> PromptPipelineService:
    return PromptPipelineService(
        repository=get_repository(),
        runtime_store=get_runtime_store(),
        llm_service=get_prompt_llm_service(),
        settings=get_settings(),
        oss_service=get_oss_service(),
    )


@lru_cache(maxsize=1)
def get_business_skill_registry() -> BusinessSkillRegistry:
    return BusinessSkillRegistry(
        repository=get_repository(),
        settings=get_settings(),
    )


@lru_cache(maxsize=1)
def get_extraction_skill_registry() -> ExtractionSkillRegistry:
    return ExtractionSkillRegistry(
        repository=get_repository(),
        settings=get_settings(),
    )


@lru_cache(maxsize=1)
def get_auth_service() -> DbAuthService:
    return DbAuthService()


def get_app_settings() -> AppSettings:
    return get_settings()


def get_current_user(
    request: Request,
    settings: AppSettings = Depends(get_app_settings),
    auth_service: DbAuthService = Depends(get_auth_service),
) -> SessionUser:
    token = request.cookies.get(settings.auth_cookie_name)
    user = auth_service.read_session_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user


def get_admin_user(current_user: SessionUser = Depends(get_current_user)) -> SessionUser:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无管理员权限")
    return current_user


def require_capability_available(capability_key: str):
    def dependency(settings: AppSettings = Depends(get_app_settings)) -> None:
        if not is_capability_available(settings, capability_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=capability_unavailable_message(settings, capability_key),
            )

    return dependency


def require_capability_level(capability_key: str, required_level: str):
    def dependency(settings: AppSettings = Depends(get_app_settings)) -> None:
        current_level = capability_level(settings, capability_key)
        if current_level == required_level:
            return
        if current_level == "unavailable":
            detail = capability_unavailable_message(settings, capability_key)
        else:
            detail = (
                f"当前部署的 {capability_key} 能力为 {current_level}，"
                f"不包含 {required_level} 完整链路。{capability_unavailable_message(settings, capability_key)}"
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    return dependency


def ensure_customer_access(customerId: str, current_user: SessionUser) -> None:
    if current_user.role == "admin":
        return
    if customerId not in current_user.customerIds:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权访问该客户数据")


def to_auth_user_response(user: SessionUser) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        displayName=user.displayName,
        customerIds=list(user.customerIds),
    )
