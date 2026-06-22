"""Business operation skill registry.

Skills are SKILL.md documents: frontmatter is machine-readable metadata and
the Markdown body is the human-maintained instruction contract.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import ProgrammingError, OperationalError

from app.core.config import AppSettings
from app.domain.models import BusinessSkillRecord
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import BusinessSkillConfigField, BusinessSkillDetail
from app.services.skill_loader import (
    ALLOWED_SKILL_EXECUTORS,
    as_string_list,
    extract_fenced_code,
    extract_markdown_rules,
    parse_skill_markdown,
    validate_controlled_python_code,
)
from app.services.oss import OssStorageService
from app.services.skill_text_store import (
    build_skill_text_asset,
    read_skill_text_asset,
    strip_stored_skill_text,
    upload_skill_text_asset,
)

ALLOWED_TARGET_TYPES = {"field", "table", "structured_object", "record_collection", "record", "output"}
ALLOWED_EXECUTORS = ALLOWED_SKILL_EXECUTORS
ALLOWED_RESULT_KINDS = {"decision", "object", "table", "text"}
ALLOWED_SKILL_STATUSES = {"draft", "active", "disabled", "deprecated"}
ALLOWED_RENDERERS = {
    "processed_objects",
    "issue_cards",
    "data_table",
    "field_cards",
    "text_block",
    "extraction_result",
    "field_grid",
    "record_cards",
    "nested_records",
    "json_view",
    "auto",
}


class BusinessSkillRegistry:
    def __init__(
        self,
        *,
        repository: WorkbenchRepository,
        settings: AppSettings,
        oss_service: OssStorageService | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._oss_service = oss_service

    def list_skills(self, *, customer_id: str | None = None, include_inactive: bool = False) -> list[BusinessSkillDetail]:
        records_by_id: dict[str, BusinessSkillRecord] = {}
        for record in self._load_platform_skills():
            if include_inactive or _is_active_skill(record):
                records_by_id.setdefault(record.id, record)
        if customer_id:
            customer_seen: set[str] = set()
            for record in self._list_customer_skills_safely(customer_id):
                if record.category == "extraction" or record.executor not in ALLOWED_EXECUTORS:
                    continue
                if (include_inactive or _is_active_skill(record)) and record.id not in customer_seen:
                    records_by_id[record.id] = record
                    customer_seen.add(record.id)
        return [
            self._to_detail(record, include_text=False)
            for record in sorted(records_by_id.values(), key=lambda item: (item.category, item.name))
            if include_inactive or _is_active_skill(record)
        ]

    def list_skills_for_customers(self, *, customer_ids: list[str], include_inactive: bool = False) -> list[BusinessSkillDetail]:
        scoped_records = self._list_business_skills_for_customers_safely(customer_ids)
        platform_records = [
            record
            for record in scoped_records
            if record.customerId is None and record.category != "extraction" and record.executor in ALLOWED_EXECUTORS
        ]

        records_by_key: dict[str, BusinessSkillRecord] = {}
        for record in platform_records:
            if include_inactive or _is_active_skill(record):
                records_by_key.setdefault(f"platform:{record.id}", record)
        for record in scoped_records:
            if (
                record.customerId
                and (include_inactive or _is_active_skill(record))
                and record.category != "extraction"
                and record.executor in ALLOWED_EXECUTORS
            ):
                records_by_key.setdefault(f"{record.customerId}:{record.id}", record)

        return [
            self._to_detail(record, include_text=False)
            for record in sorted(records_by_key.values(), key=lambda item: (item.customerId or "", item.name))
        ]

    def resolve_skill(
        self,
        *,
        skill_id: str,
        customer_id: str | None = None,
        version: str | None = None,
    ) -> BusinessSkillRecord:
        candidates: list[BusinessSkillRecord] = []
        if customer_id:
            candidates.extend(
                item
                for item in self._list_customer_skills_safely(customer_id)
                if item.id == skill_id
                and _is_active_skill(item)
                and item.category != "extraction"
                and item.executor in ALLOWED_EXECUTORS
            )
        candidates.extend(item for item in self._load_platform_skills() if item.id == skill_id and _is_active_skill(item))
        if version:
            candidates = [item for item in candidates if item.version == version]
        if not candidates:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business skill not found")
        return self._with_loaded_skill_text(candidates[0])

    def get_detail(
        self,
        *,
        skill_id: str,
        scope: str,
        customer_id: str | None = None,
        include_text: bool = True,
        include_inactive: bool = False,
    ) -> BusinessSkillDetail:
        return self._to_detail(
            self._get_exact_skill(
                skill_id=skill_id,
                scope=scope,
                customer_id=customer_id,
                include_inactive=include_inactive,
            ),
            include_text=include_text,
        )

    def parse_markdown(self, skill_text: str, *, customer_id: str | None = None) -> BusinessSkillRecord:
        return parse_business_skill_markdown(skill_text, customer_id=customer_id)

    def save_customer_skill(self, skill_text: str, *, customer_id: str, updated_by: Optional[str] = None) -> BusinessSkillDetail:
        record = self.parse_markdown(skill_text, customer_id=customer_id)
        if updated_by:
            record = replace(record, createdBy=updated_by, updatedBy=updated_by)
        record = self._with_uploaded_skill_text(record, kind="operation")
        saved = self._repository.save_business_skill(record)
        return self._to_detail(self._with_loaded_skill_text(saved), include_text=True)

    def _load_platform_skills(self) -> list[BusinessSkillRecord]:
        return [
            record
            for record in self._list_platform_skills_safely()
            if record.category != "extraction" and record.executor in ALLOWED_EXECUTORS
        ]

    def _get_exact_skill(
        self,
        *,
        skill_id: str,
        scope: str,
        customer_id: str | None,
        include_inactive: bool = False,
    ) -> BusinessSkillRecord:
        if scope == "customer":
            if not customer_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="读取客户 Skill 必须提供 customerId。")
            candidates = [
                item
                for item in self._list_customer_skills_safely(customer_id)
                if item.id == skill_id
                and (include_inactive or _is_active_skill(item))
                and item.category != "extraction"
                and item.executor in ALLOWED_EXECUTORS
            ]
        elif scope == "platform":
            candidates = [
                item
                for item in self._load_platform_skills()
                if item.id == skill_id and (include_inactive or _is_active_skill(item))
            ]
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope 只支持 platform 或 customer。")
        if not candidates:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business skill not found")
        return self._with_loaded_skill_text(candidates[0])

    def _list_customer_skills_safely(self, customer_id: str) -> list[BusinessSkillRecord]:
        try:
            return self._repository.list_business_skills(customer_id)
        except (ProgrammingError, OperationalError) as exc:
            if "business_skills" in str(exc):
                return []
            raise

    def _list_business_skills_for_customers_safely(self, customer_ids: list[str]) -> list[BusinessSkillRecord]:
        try:
            list_for_customers = getattr(self._repository, "list_business_skills_for_customers", None)
            if callable(list_for_customers):
                return list_for_customers(customer_ids)
            records = list(self._repository.list_business_skills(None))
            for customer_id in customer_ids:
                records.extend(self._repository.list_business_skills(customer_id))
            return records
        except (ProgrammingError, OperationalError) as exc:
            if "business_skills" in str(exc):
                return []
            raise

    def _list_platform_skills_safely(self) -> list[BusinessSkillRecord]:
        try:
            return self._repository.list_business_skills(None)
        except (ProgrammingError, OperationalError) as exc:
            if "business_skills" in str(exc):
                return []
            raise

    def _with_uploaded_skill_text(self, record: BusinessSkillRecord, *, kind: str) -> BusinessSkillRecord:
        skill_text = record.skillText
        if not skill_text.strip():
            return record
        try:
            asset = upload_skill_text_asset(
                storage=self._oss_service,
                customer_id=record.customerId,
                kind=kind,
                skill_id=record.id,
                version=record.version,
                skill_text=skill_text,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"OSS 未配置，无法保存 SKILL.md：{exc}",
            ) from exc
        return replace(
            record,
            defaults=strip_stored_skill_text(record.defaults),
            skillTextObjectKey=asset.objectKey,
            skillTextHash=asset.sha256,
            skillTextSizeBytes=asset.sizeBytes,
            skillTextPreview=asset.preview,
            skillText=skill_text,
        )

    def _with_loaded_skill_text(self, record: BusinessSkillRecord) -> BusinessSkillRecord:
        if record.skillText:
            return record
        if record.skillTextObjectKey:
            try:
                return replace(record, skillText=read_skill_text_asset(storage=self._oss_service, object_key=record.skillTextObjectKey))
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"OSS 未配置，无法读取 SKILL.md：{exc}",
                ) from exc
        return record

    def _to_detail(self, record: BusinessSkillRecord, *, include_text: bool = True) -> BusinessSkillDetail:
        config_schema = {
            key: BusinessSkillConfigField.model_validate(value)
            for key, value in (record.configSchema or {}).items()
            if isinstance(value, dict)
        }
        return BusinessSkillDetail(
            id=record.id,
            version=record.version,
            name=record.name,
            category=record.category,
            targetTypes=record.targetTypes,  # type: ignore[arg-type]
            customerScope="customer" if record.customerId else "platform",
            scope="customer" if record.customerId else "platform",
            customerId=record.customerId,
            enabled=record.enabled,
            status=_normalize_record_status(record),
            tags=list(record.tags or []),
            sourceTypes=list(record.sourceTypes or []),
            executor=record.executor,  # type: ignore[arg-type]
            resultKind=record.resultKind,  # type: ignore[arg-type]
            renderer=record.renderer,  # type: ignore[arg-type]
            configSchema=config_schema,
            outputSchema=record.outputSchema,
            promptTemplate=record.promptTemplate,
            examples=record.examples,
            defaults=strip_stored_skill_text(record.defaults),
            latestTestStatus=record.latestTestStatus,
            sampleCount=record.sampleCount,
            testRunCount=record.testRunCount,
            lastTestedAt=record.lastTestedAt,
            createdBy=record.createdBy,
            updatedBy=record.updatedBy,
            createdAt=record.createdAt,
            skillText=record.skillText if include_text else "",
            skillTextObjectKey=record.skillTextObjectKey,
            skillTextHash=record.skillTextHash,
            skillTextSizeBytes=record.skillTextSizeBytes,
            skillTextPreview=record.skillTextPreview,
            updatedAt=record.updatedAt,
        )


def parse_business_skill_markdown(skill_text: str, *, customer_id: str | None = None) -> BusinessSkillRecord:
    parsed = parse_skill_markdown(skill_text)
    payload = parsed.frontmatter

    required_fields = ["id", "version", "name", "kind", "executor", "resultKind", "renderer"]
    missing = [field for field in required_fields if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError(f"缺少必填字段：{', '.join(missing)}。")
    if str(payload.get("kind") or "").strip() != "operation":
        raise ValueError("业务处理 Skill 的 kind 必须是 operation。")

    target_types = as_string_list(payload.get("targetTypes"))
    if not target_types:
        raise ValueError("targetTypes 至少需要一个目标类型。")
    invalid_targets = [item for item in target_types if item not in ALLOWED_TARGET_TYPES]
    if invalid_targets:
        raise ValueError(f"targetTypes 不支持：{', '.join(invalid_targets)}。")

    executor = str(payload.get("executor") or "").strip()
    result_kind = str(payload.get("resultKind") or "").strip()
    renderer = str(payload.get("renderer") or "auto").strip()
    skill_status = _status_from_payload(payload)
    if executor not in ALLOWED_EXECUTORS:
        raise ValueError(f"executor 不支持：{executor}。")
    if executor == "external_connector":
        raise ValueError("external_connector 仅为预留类型，当前版本暂不支持发布。")
    if result_kind not in ALLOWED_RESULT_KINDS:
        raise ValueError(f"resultKind 不支持：{result_kind}。")
    if renderer not in ALLOWED_RENDERERS:
        raise ValueError(f"renderer 不支持：{renderer}。")

    config_schema = payload.get("configSchema") or {}
    if not isinstance(config_schema, dict):
        raise ValueError("configSchema 必须是对象。")
    for key, value in config_schema.items():
        if not isinstance(value, dict):
            raise ValueError(f"configSchema.{key} 必须是对象。")
        BusinessSkillConfigField.model_validate(value)

    output_schema = payload.get("outputSchema") or {}
    if not isinstance(output_schema, dict):
        raise ValueError("outputSchema 必须是对象。")

    examples = payload.get("examples") or []
    if not isinstance(examples, list):
        raise ValueError("examples 必须是数组。")

    defaults = payload.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("defaults 必须是对象。")
    defaults = dict(defaults)
    body_rules = extract_markdown_rules(parsed.body)
    if body_rules and not defaults.get("rules"):
        defaults["rules"] = body_rules
    http_config = payload.get("http")
    if http_config is not None:
        if not isinstance(http_config, dict):
            raise ValueError("http 必须是对象。")
        defaults["http"] = http_config
    if executor == "http_connector":
        _validate_http_connector_payload(defaults.get("http"))
    if executor == "controlled_python":
        python_code = extract_fenced_code(parsed.body, "python")
        validate_controlled_python_code(python_code)
        defaults["pythonCode"] = python_code
    asset = build_skill_text_asset(skill_text=parsed.text)

    return BusinessSkillRecord(
        id=str(payload["id"]).strip(),
        version=str(payload["version"]).strip(),
        name=str(payload["name"]).strip(),
        category=str(payload.get("category") or "business_operation").strip(),
        status=skill_status,
        sourceTypes=as_string_list(payload.get("sourceTypes")),
        targetTypes=target_types,
        executor=executor,
        resultKind=result_kind,
        renderer=renderer,
        configSchema=config_schema,
        outputSchema=output_schema,
        promptTemplate=parsed.body or str(payload.get("promptTemplate") or "").strip(),
        examples=[item for item in examples if isinstance(item, dict)],
        defaults=strip_stored_skill_text(defaults),
        skillTextHash=asset.sha256,
        skillTextSizeBytes=asset.sizeBytes,
        skillTextPreview=asset.preview,
        skillText=parsed.text,
        enabled=skill_status == "active",
        customerId=customer_id,
        tags=as_string_list(payload.get("tags")),
    )


def merge_skill_config(skill: BusinessSkillRecord, config: dict[str, Any] | None) -> dict[str, Any]:
    merged = {
        key: value
        for key, value in (skill.defaults or {}).items()
        if not str(key).startswith("_") and key not in {"http", "pythonCode"}
    }
    if isinstance(config, dict):
        merged.update(config)
    return merged


def with_customer_scope(record: BusinessSkillRecord, customer_id: str) -> BusinessSkillRecord:
    return replace(record, customerId=customer_id)


def _normalize_record_status(record: BusinessSkillRecord) -> str:
    status = str(record.status or "").strip()
    if status in ALLOWED_SKILL_STATUSES:
        return status
    return "active" if record.enabled else "disabled"


def _is_active_skill(record: BusinessSkillRecord) -> bool:
    return bool(record.enabled) and _normalize_record_status(record) == "active"


def _status_from_payload(payload: dict[str, Any]) -> str:
    raw_status = str(payload.get("status") or "").strip()
    if raw_status:
        if raw_status not in ALLOWED_SKILL_STATUSES:
            raise ValueError(f"status 不支持：{raw_status}。")
        return raw_status
    return "active" if bool(payload.get("enabled", True)) else "disabled"


def _as_string_list(value: Any) -> list[str]:
    return as_string_list(value)


def _validate_http_connector_payload(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("http_connector Skill 必须声明 http 配置。")
    method = str(value.get("method") or "").strip().upper()
    url = str(value.get("url") or "").strip()
    if method not in {"GET", "POST", "PUT", "PATCH"}:
        raise ValueError("http.method 只支持 GET、POST、PUT、PATCH。")
    if not url.startswith(("https://", "http://")):
        raise ValueError("http.url 必须是 http/https URL。")
