"""Unified SKILL.md management APIs."""

from __future__ import annotations

from typing import Any, Optional
import json
import os
import re
import time
from types import SimpleNamespace
from datetime import datetime, timezone
from urllib import error, request
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    ensure_customer_access,
    get_business_skill_registry,
    get_current_user,
    get_extraction_skill_registry,
    get_repository,
    get_prompt_llm_service,
    get_prompt_pipeline_service,
    get_runtime_store,
    get_semantic_locator_reranker,
)
from app.core.config import get_settings
from app.domain.models import SkillSampleRecord, SkillTestRunRecord
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    ExtractionResult,
    OperationTargetRef,
    SkillCopyDraftRequest,
    SkillCopyDraftResponse,
    SkillDraftFromSampleRequest,
    SkillDraftFromSampleResponse,
    SkillSampleLocateAndExtractRequest,
    SkillSampleLocateAndExtractResponse,
    SkillSampleLocatedSource,
    SkillSampleExtractFromSampleResponse,
    SkillSampleProcessFromSampleResponse,
    SkillOwnershipUpdateRequest,
    SkillSampleResponse,
    SkillSampleUpsertRequest,
    SkillAssistRequest,
    SkillAssistResponse,
    SkillTestRunRequest,
    SkillTestRunResponse,
    SkillTestRunSummary,
    SkillValidateRequest,
    SkillValidateResponse,
    UnifiedSkillUpsertRequest,
)
from app.services.auth import SessionUser
from app.services.business_skills import BusinessSkillRegistry, merge_skill_config
from app.services.document_tree_artifacts import load_document_tree
from app.services.document_tree_scope import expand_document_tree_modules
from app.services.extraction_skills import ExtractionSkillRegistry
from app.services.llm import PromptLlmService, _build_ssl_context
from app.services.oss import OssStorageService, build_oss_storage_service
from app.services.prompt_pipeline import (
    _attach_skill_metadata_to_output,
    _build_extraction_run_meta,
    _build_skill_instruction,
    _normalize_extraction_skill_output,
    _operation_type_for_skill_executor,
    _skill_payload_for_llm,
    _try_run_skill_object_operation,
    PromptPipelineService,
)
from app.services.extraction_runtime.sample_preview import build_sample_preview_runtime_request
from app.services.extraction_runtime.skill_test import build_skill_test_runtime_request
from app.services.skill_assist_service import (
    ensure_extraction_skill_semantic_governance,
    run_sample_extraction_assist,
    run_sample_process_assist,
    run_skill_assist,
)
from app.services.skill_loader import parse_skill_markdown
from app.services.runtime_store import JsonRuntimeStore
from app.services.semantic_locator import LocatorCandidate, LocatorRunResult, SemanticLocatorReranker, SemanticLocatorService
from app.services.semantic_locator_reranker import DashScopeSemanticLocatorReranker
from app.services.table_parser import parse_table_html

router = APIRouter(tags=["skills"])


def _new_sample_extraction_trace(
    *,
    task_id: str,
    customer_id: str | None,
    entrypoint: str,
    request_payload: Any,
) -> dict[str, Any]:
    return {
        "traceId": f"sample-trace-{uuid4().hex[:12]}",
        "traceLevel": "full",
        "taskId": task_id,
        "customerId": customer_id,
        "entrypoint": entrypoint,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "request": _sample_trace_request_summary(request_payload),
        "events": [],
    }


def _persist_sample_extraction_trace(
    runtime_store: JsonRuntimeStore,
    trace: dict[str, Any],
) -> dict[str, str]:
    trace_id = str(trace.get("traceId") or f"sample-trace-{uuid4().hex[:12]}")
    task_id = str(trace.get("taskId") or "unknown-task")
    trace["traceId"] = trace_id
    trace["traceLevel"] = "full"
    trace["updatedAt"] = datetime.now(timezone.utc).isoformat()
    trace_path = runtime_store.write_json_log(
        "sample-extraction",
        task_id,
        f"{_safe_object_segment(trace_id)}.json",
        _redact_sample_trace_payload(_jsonable_payload(trace)),
    )
    return {"traceId": trace_id, "tracePath": trace_path, "traceLevel": "full"}


def _jsonable_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if isinstance(value, dict):
        return {str(key): _jsonable_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable_payload(item) for item in value]
    if isinstance(value, (tuple, set)):
        return [_jsonable_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _redact_sample_trace_payload(value: Any) -> Any:
    sensitive_keys = {
        "authorization",
        "api_key",
        "apikey",
        "access_key",
        "secret_key",
        "dashscope_api_key",
        "cookie",
        "password",
        "bearer",
    }
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in sensitive_keys:
                redacted[key_text] = "***REDACTED***"
            else:
                redacted[key_text] = _redact_sample_trace_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sample_trace_payload(item) for item in value]
    return value


_SAMPLE_GEOMETRY_KEYS = {
    "bbox",
    "boundingbox",
    "box",
    "polygon",
    "points",
    "quad",
    "quads",
    "rect",
    "rotation",
}


def _sample_trace_request_summary(payload: Any) -> dict[str, Any]:
    sample_context = _get_payload_value(payload, "sampleContext")
    content_refs = _get_payload_value(payload, "contentRefs") or []
    target_ids = _get_payload_value(payload, "targetIds") or []
    source_text = str(_get_payload_value(payload, "sourceText") or "")
    instruction = str(_get_payload_value(payload, "instruction") or "")
    expected_output = str(_get_payload_value(payload, "expectedOutput") or "")
    summary: dict[str, Any] = {
        "taskId": _payload_task_id(payload),
        "applicationId": _payload_application_id(payload) or None,
        "kind": str(_get_payload_value(payload, "kind") or ""),
        "customerId": _get_payload_value(payload, "customerId"),
        "dataTypeName": _get_payload_value(payload, "dataTypeName"),
        "sourceScope": _get_payload_value(payload, "sourceScope"),
        "sourceLabel": _get_payload_value(payload, "sourceLabel"),
        "sourceTextChars": len(source_text),
        "instructionChars": len(instruction),
        "expectedOutputChars": len(expected_output),
        "targetIds": [str(item) for item in target_ids if str(item).strip()][:20],
        "pageNo": _get_payload_value(payload, "pageNo"),
        "treeNodeId": _get_payload_value(payload, "treeNodeId"),
        "treePath": _jsonable_payload(_get_payload_value(payload, "treePath") or [])[:20],
        "pageRange": _drop_sample_geometry(_jsonable_payload(_get_payload_value(payload, "pageRange") or {})),
        "contentRefCount": len(content_refs) if isinstance(content_refs, list) else 0,
        "contentRefs": _compact_sample_content_refs(content_refs, limit=20),
    }
    if sample_context is not None:
        pages = _get_payload_value(sample_context, "pages") or []
        document_tree = _get_payload_value(sample_context, "documentTree")
        operation_targets = _get_payload_value(sample_context, "operationTargets") or []
        sample_source = _get_payload_value(sample_context, "sampleSource") or {}
        summary["sampleContext"] = {
            "sampleId": _get_payload_value(sample_context, "sampleId"),
            "source": _get_payload_value(sample_context, "source"),
            "applicationId": _get_payload_value(sample_context, "applicationId"),
            "customerId": _get_payload_value(sample_context, "customerId"),
            "pageCount": len(pages) if isinstance(pages, list) else 0,
            "pageNos": _sample_context_page_nos(pages),
            "blockCount": _sample_context_block_count(pages),
            "hasDocumentTree": document_tree is not None,
            "documentTreeModuleCount": _document_tree_module_count(document_tree),
            "operationTargetCount": len(operation_targets) if isinstance(operation_targets, list) else 0,
            "sampleSource": _compact_sample_source_summary(sample_source),
        }
    return summary


def _get_payload_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _sample_context_page_nos(pages: Any) -> list[int]:
    if not isinstance(pages, list):
        return []
    page_nos: list[int] = []
    for page in pages[:50]:
        page_no = _coerce_int(_get_payload_value(page, "pageNo"))
        if page_no:
            page_nos.append(page_no)
    return page_nos


def _sample_context_block_count(pages: Any) -> int:
    if not isinstance(pages, list):
        return 0
    total = 0
    for page in pages:
        blocks = _get_payload_value(page, "blocks") or []
        if isinstance(blocks, list):
            total += len(blocks)
    return total


def _document_tree_module_count(document_tree: Any) -> int:
    modules = _get_payload_value(document_tree, "modules") if document_tree is not None else []
    return len(modules) if isinstance(modules, list) else 0


def _compact_sample_source_summary(sample_source: Any) -> dict[str, Any]:
    if not sample_source:
        return {}
    content_refs = _get_payload_value(sample_source, "contentRefs") or []
    source_text = str(_get_payload_value(sample_source, "sourceText") or "")
    return {
        "mode": _get_payload_value(sample_source, "mode"),
        "kind": _get_payload_value(sample_source, "kind"),
        "title": _sample_short_text(_get_payload_value(sample_source, "title"), limit=160),
        "summary": _sample_short_text(_get_payload_value(sample_source, "summary"), limit=300),
        "sourceScope": _get_payload_value(sample_source, "sourceScope"),
        "sourceTextChars": len(source_text),
        "pageNo": _get_payload_value(sample_source, "pageNo"),
        "treeNodeId": _get_payload_value(sample_source, "treeNodeId"),
        "treePath": _jsonable_payload(_get_payload_value(sample_source, "treePath") or [])[:20],
        "pageRange": _drop_sample_geometry(_jsonable_payload(_get_payload_value(sample_source, "pageRange") or {})),
        "contentRefCount": len(content_refs) if isinstance(content_refs, list) else 0,
        "contentRefs": _compact_sample_content_refs(content_refs, limit=20),
    }


def _compact_sample_content_refs(content_refs: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(content_refs, list):
        return []
    compact_refs: list[dict[str, Any]] = []
    for item in content_refs:
        if not isinstance(item, dict):
            continue
        compact = _drop_sample_geometry(_jsonable_payload(item))
        if isinstance(compact, dict):
            compact_refs.append(_truncate_sample_ref_text(compact))
        if len(compact_refs) >= limit:
            break
    return compact_refs


def _truncate_sample_ref_text(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"title", "summary", "excerpt"}:
            result[key] = _sample_short_text(item, limit=500 if key == "excerpt" else 220)
        elif key in {"sourceText", "content", "htmlContent", "rawText"}:
            result[f"{key}Chars"] = len(str(item or ""))
        else:
            result[key] = item
    return result


def _drop_sample_geometry(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _drop_sample_geometry(item)
            for key, item in value.items()
            if str(key).replace("_", "").lower() not in _SAMPLE_GEOMETRY_KEYS
        }
    if isinstance(value, list):
        return [_drop_sample_geometry(item) for item in value]
    return value


def _sample_short_text(value: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _payload_task_id(payload: Any) -> str:
    return str(getattr(payload, "taskId", "") or "").strip()


def _payload_application_id(payload: Any) -> str:
    sample_context = getattr(payload, "sampleContext", None)
    return str(
        getattr(payload, "applicationId", None)
        or getattr(sample_context, "applicationId", None)
        or ""
    ).strip()


def _sample_identity(payload: Any) -> str:
    task_id = _payload_task_id(payload)
    if task_id:
        return task_id
    sample_context = getattr(payload, "sampleContext", None)
    sample_id = str(getattr(sample_context, "sampleId", "") or "").strip()
    if sample_id:
        return sample_id
    application_id = _payload_application_id(payload)
    if application_id:
        return f"application-sample-{_safe_object_segment(application_id)}"
    return "inline-sample"


def _resolve_sample_customer(
    repository: WorkbenchRepository,
    payload: Any,
    current_user: SessionUser,
) -> tuple[str | None, Any | None]:
    task_id = _payload_task_id(payload)
    if task_id:
        task = repository.get_task_record(task_id)
        customer_id = str(getattr(payload, "customerId", None) or task.customerId or "").strip()
        ensure_customer_access(customer_id, current_user)
        ensure_customer_access(task.customerId, current_user)
        return customer_id, task

    sample_context = getattr(payload, "sampleContext", None)
    customer_id = str(
        getattr(payload, "customerId", None)
        or getattr(sample_context, "customerId", None)
        or ""
    ).strip()
    application_id = _payload_application_id(payload)
    if application_id:
        application = repository.get_application(application_id)
        ensure_customer_access(application.customerId, current_user)
        if customer_id and customer_id != application.customerId:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="样例客户与应用所属客户不一致。")
        customer_id = application.customerId
    if not customer_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="应用样例请求缺少 customerId 或 applicationId。")
    ensure_customer_access(customer_id, current_user)
    return customer_id, None


def _sample_context_pages(payload: Any) -> list[Any]:
    sample_context = getattr(payload, "sampleContext", None)
    pages = getattr(sample_context, "pages", None)
    return [_sample_namespace(page) for page in list(pages or [])]


def _sample_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{str(key): _sample_namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_sample_namespace(item) for item in value]
    return value


def _sample_context_document_tree(payload: Any) -> Any | None:
    sample_context = getattr(payload, "sampleContext", None)
    return getattr(sample_context, "documentTree", None) if sample_context is not None else None


def _sample_context_operation_targets(payload: Any) -> dict[int, list[OperationTargetRef]]:
    sample_context = getattr(payload, "sampleContext", None)
    targets = getattr(sample_context, "operationTargets", None) or []
    by_page: dict[int, list[OperationTargetRef]] = {}
    for target in targets:
        page_no = _coerce_int(getattr(target, "pageNo", None))
        if not page_no:
            continue
        by_page.setdefault(page_no, []).append(target)
    return by_page


def _sample_pages_and_target_loader(
    repository: WorkbenchRepository,
    payload: SkillDraftFromSampleRequest,
) -> tuple[list[Any], Any, dict[str, Any]]:
    task_id = _payload_task_id(payload)
    if task_id:
        detail = repository.get_task_execution_context(task_id)

        def load_task_targets(page_no: int) -> list[OperationTargetRef]:
            return repository.get_task_page_operation_targets(task_id, page_no).targets

        return list(detail.pages), load_task_targets, {
            "source": "task",
            "contextId": task_id,
        }

    targets_by_page = _sample_context_operation_targets(payload)

    def load_context_targets(page_no: int) -> list[OperationTargetRef]:
        return targets_by_page.get(page_no, [])

    sample_context = payload.sampleContext
    return _sample_context_pages(payload), load_context_targets, {
        "source": str(getattr(sample_context, "source", "") or "application_template"),
        "contextId": _sample_identity(payload),
        "operationTargetCount": sum(len(items) for items in targets_by_page.values()),
    }


_DOCUMENT_TREE_SOURCE_PREVIEW_MARKERS = (
    "模块预览已截断",
    "样例来源预览已截断",
)


def _hydrate_document_tree_sample_source(
    *,
    repository: WorkbenchRepository,
    runtime_store: JsonRuntimeStore | None,
    payload: SkillDraftFromSampleRequest,
    trace: dict[str, Any] | None = None,
) -> SkillDraftFromSampleRequest:
    if not (payload.treeNodeId or _content_refs_include_document_tree_modules(payload.contentRefs)):
        return payload

    document_tree, source = _load_sample_document_tree(repository, runtime_store, payload)
    if document_tree is None or not getattr(document_tree, "modules", None):
        if trace is not None:
            trace["sampleSourceHydration"] = {
                "used": False,
                "reason": "document_tree_not_available",
            }
        return payload

    module_ids = _sample_document_tree_module_ids(payload)
    full_source_text = _build_document_tree_sample_source_text(document_tree, module_ids)
    if not full_source_text:
        if trace is not None:
            trace["sampleSourceHydration"] = {
                "used": False,
                "reason": "document_tree_modules_not_found",
                "moduleIds": module_ids,
                "source": source,
            }
        return payload

    current_text = str(payload.sourceText or "").strip()
    preview_like = any(marker in current_text for marker in _DOCUMENT_TREE_SOURCE_PREVIEW_MARKERS)
    should_replace = preview_like or len(full_source_text) > len(current_text) + 200
    if not should_replace:
        if trace is not None:
            trace["sampleSourceHydration"] = {
                "used": False,
                "reason": "source_text_already_complete",
                "moduleIds": module_ids,
                "sourceTextChars": len(current_text),
                "fullSourceTextChars": len(full_source_text),
                "source": source,
            }
        return payload

    if trace is not None:
        trace["sampleSourceHydration"] = {
            "used": True,
            "source": source,
            "moduleIds": module_ids,
            "sourceTextCharsBefore": len(current_text),
            "sourceTextCharsAfter": len(full_source_text),
            "previewLike": preview_like,
        }
    return payload.model_copy(update={"sourceText": full_source_text})


def _load_sample_document_tree(
    repository: WorkbenchRepository,
    runtime_store: JsonRuntimeStore | None,
    payload: SkillDraftFromSampleRequest,
) -> tuple[Any | None, str]:
    context_tree = _sample_context_document_tree(payload)
    if context_tree is not None and getattr(context_tree, "modules", None):
        return context_tree, "sample_context"

    task_id = _payload_task_id(payload)
    if not task_id or runtime_store is None:
        return None, ""

    task = repository.get_task_record(task_id)
    document_id = str(getattr(task, "documentId", "") or "").strip()
    document = repository.get_document_record(document_id)
    return load_document_tree(runtime_store, task_id, document.id), "runtime_store"


def _sample_document_tree_module_ids(payload: SkillDraftFromSampleRequest) -> list[str]:
    module_ids: list[str] = []
    for ref in payload.contentRefs or []:
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get("kind") or ref.get("source") or "").strip()
        node_id = str(ref.get("nodeId") or ref.get("treeNodeId") or ref.get("id") or "").strip()
        if node_id and (kind == "document_tree_module" or ref.get("evidencePages") or ref.get("pages")):
            module_ids.append(node_id)
    if not module_ids and payload.treeNodeId:
        module_ids.append(str(payload.treeNodeId))
    return _unique_texts(module_ids, limit=80)


def _build_document_tree_sample_source_text(document_tree: Any, module_ids: list[str]) -> str:
    source_parts: list[str] = []
    for index, module_id in enumerate(module_ids, start=1):
        module = _find_document_tree_module(document_tree, module_id)
        if not module:
            continue
        title = str(module.get("title") or module_id).strip()
        source_text = _module_skill_input(module)
        if not source_text:
            continue
        heading = f"## 命中模块 {index}：{title or module_id}"
        source_parts.append("\n".join([heading, source_text]).strip())
    return "\n\n".join(part for part in source_parts if part).strip()


@router.get("/skills")
def list_skills(
    kind: str = Query("extraction"),
    scope: Optional[str] = Query(None),
    customerId: Optional[str] = Query(None),
    statusFilter: Optional[str] = Query(None, alias="status"),
    keyword: str = Query(""),
    page: int = Query(1, ge=1),
    pageSize: int = Query(8, ge=1, le=100),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> dict[str, Any]:
    if scope not in {None, "platform", "customer", "all"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope 只支持 platform、customer 或 all。")
    if customerId:
        ensure_customer_access(customerId, current_user)
    if scope == "customer" and not customerId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="读取客户 Skill 必须提供 customerId。")
    if scope == "all":
        customer_ids = _visible_customer_ids(current_user=current_user, repository=repository)
        if kind == "operation":
            return _paginate_skill_items(
                [
                    item.model_dump()
                    for item in business_registry.list_skills_for_customers(
                        customer_ids=customer_ids,
                        include_inactive=True,
                    )
                ],
                status_filter=statusFilter,
                keyword=keyword,
                page=page,
                page_size=pageSize,
            )
        if kind == "extraction":
            return _paginate_skill_items(
                [
                    item.model_dump()
                    for item in extraction_registry.list_skills_for_customers(
                        customer_ids=customer_ids,
                        include_inactive=True,
                    )
                ],
                status_filter=statusFilter,
                keyword=keyword,
                page=page,
                page_size=pageSize,
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kind 只支持 extraction 或 operation。")
    if scope == "platform":
        customerId = None
    if kind == "operation":
        return _paginate_skill_items(
            [
                item.model_dump()
                for item in business_registry.list_skills(
                    customer_id=customerId,
                    include_inactive=True,
                )
            ],
            status_filter=statusFilter,
            keyword=keyword,
            page=page,
            page_size=pageSize,
        )
    if kind == "extraction":
        return _paginate_skill_items(
            [
                item.model_dump()
                for item in extraction_registry.list_skills(
                    customer_id=customerId,
                    include_inactive=True,
                )
            ],
            status_filter=statusFilter,
            keyword=keyword,
            page=page,
            page_size=pageSize,
        )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kind 只支持 extraction 或 operation。")


def _paginate_skill_items(
    items: list[dict[str, Any]],
    *,
    status_filter: Optional[str],
    keyword: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if status_filter:
        normalized_status = status_filter.strip()
        if normalized_status not in {"draft", "active", "disabled", "deprecated"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status 只支持 draft、active、disabled、deprecated。")
        items = [item for item in items if str(item.get("status") or "active") == normalized_status]
    normalized_keyword = keyword.strip().lower()
    if normalized_keyword:
        items = [
            item
            for item in items
            if normalized_keyword
            in " ".join(
                str(value or "")
                for value in (
                    item.get("id"),
                    item.get("name"),
                    item.get("version"),
                    item.get("executor"),
                    item.get("category"),
                    item.get("customerId"),
                    item.get("customerScope"),
                    item.get("status"),
                    " ".join(str(value) for value in (item.get("tags") or [])),
                )
            ).lower()
        ]
    items = sorted(items, key=_skill_item_sort_key, reverse=True)
    total = len(items)
    safe_page = max(1, page)
    start = (safe_page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": safe_page,
        "pageSize": page_size,
    }


def _skill_item_sort_key(item: dict[str, Any]) -> datetime:
    for key in ("updatedAt", "createdAt"):
        value = item.get(key)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


@router.post("/skills/draft-from-sample", response_model=SkillDraftFromSampleResponse)
def draft_skill_from_sample(
    payload: SkillDraftFromSampleRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SkillDraftFromSampleResponse:
    customer_id, _task = _resolve_sample_customer(repository, payload, current_user)
    sample_text, sample_summary = _build_skill_sample(repository, payload)
    instruction_parts = [payload.instruction.strip()]
    if payload.expectedOutput.strip():
        instruction_parts.append(f"期望输出：{payload.expectedOutput.strip()}")
    if payload.confirmedSampleOutput is not None:
        protocol_lines = []
        if payload.kind == "operation":
            confirmed_result_kind = _confirmed_operation_result_kind(payload.confirmedSampleOutput)
            if confirmed_result_kind:
                protocol_lines.extend(
                    [
                        f"确认处理输出协议：result_kind={confirmed_result_kind}",
                        f"frontmatter resultKind 必须是 {confirmed_result_kind}。",
                        "最终执行输出必须包含 summary、result_kind、output_payload。",
                    ]
                )
                if confirmed_result_kind == "object":
                    protocol_lines.append("如果输出 records/items/issues 等集合，放入 output_payload 内，不要把 resultKind 写成 record_collection。")
                elif confirmed_result_kind == "table":
                    protocol_lines.append("表格处理结果应放在 output_payload.headers 和 output_payload.rows。")
                elif confirmed_result_kind == "decision":
                    protocol_lines.append("判断结果应放在 output_payload.decision、reason、evidence 等字段。")
        else:
            confirmed_output_type, confirmed_renderer = _confirmed_sample_output_contract(payload.confirmedSampleOutput)
            if confirmed_output_type:
                protocol_lines.extend(
                    [
                        f"确认输出协议：{confirmed_output_type}",
                        f"frontmatter renderer 必须是 {confirmed_renderer}。",
                        f"frontmatter output.type 必须是 {confirmed_output_type}。",
                    ]
                )
                if confirmed_output_type == "field_list":
                    protocol_lines.append("即使样例来源页面包含表格，也必须输出字段列表协议，不要改成 data_table。")
                    protocol_lines.append("输出格式应为 {\"fields\":[{\"label\":\"字段名\",\"value\":\"字段值\",\"source_page\":\"第 X 页\"}]}。")
                elif confirmed_output_type == "data_table":
                    protocol_lines.append("输出格式应为 {\"headers\":[...],\"rows\":[...],\"mergeNotes\":[],\"evidence\":[]}。")
                elif confirmed_output_type == "record_collection":
                    protocol_lines.append("输出格式应为 {\"records\":[...]}。")
        instruction_parts.append(
            "\n".join(
                [
                    "用户已确认的样例正确输出（gold output）：",
                    _compact_sample_value(payload.confirmedSampleOutput, limit=6000),
                    *protocol_lines,
                    "生成 Skill 时应学习这个输出结构、字段命名和数据组织方式；页码只能作为来源证据示例，不要写死为固定触发条件。",
                ]
            )
        )
    if payload.kind == "extraction":
        instruction_parts.append("默认不要输出 original_text 或原文片段；只保留 source_page/page 等轻量来源字段，除非用户确认输出中明确要求。")
        instruction_parts.append("运行时以应用确认的 runtimeContract 为最终输出契约；SKILL.md 正文是能力说明，不得用旧正文中的字段列表覆盖应用确认字段。")
    assist = run_skill_assist(
        SkillAssistRequest(
            kind=payload.kind,
            instruction="\n".join(instruction_parts),
            sampleText=sample_text,
            customerId=customer_id,
        )
    )
    skill_text = _personalize_sample_skill_text(assist.skillText, payload)
    if payload.kind == "operation" and payload.confirmedSampleOutput is not None:
        skill_text = _force_operation_result_kind(
            skill_text,
            _confirmed_operation_result_kind(payload.confirmedSampleOutput),
        )
    if skill_text != assist.skillText:
        assist = assist.model_copy(update={"skillText": skill_text})
    output_contract = _build_sample_output_contract_summary(payload, confirmed_output=payload.confirmedSampleOutput)
    validation_report = _build_sample_validation_report(
        kind=payload.kind,
        output_contract=output_contract,
        confirmed_output=payload.confirmedSampleOutput,
        skill_text=assist.skillText,
        errors=assist.errors,
    )
    evidence_diagnostics = _build_sample_evidence_diagnostics(payload, sample_summary)
    return SkillDraftFromSampleResponse(
        kind=payload.kind,
        taskId=_sample_identity(payload),
        customerId=customer_id,
        sampleSummary=sample_summary,
        assist=assist,
        evidenceDiagnostics=evidence_diagnostics,
        validationReport=validation_report,
        outputContractSummary=output_contract,
    )


@router.post("/skills/sample-extract-from-sample", response_model=SkillSampleExtractFromSampleResponse)
def sample_extract_from_sample(
    payload: SkillDraftFromSampleRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    runtime_store: JsonRuntimeStore = Depends(get_runtime_store),
    prompt_pipeline: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> SkillSampleExtractFromSampleResponse:
    if payload.kind != "extraction":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="样例试抽取仅支持 extraction 提取步骤。")
    customer_id, _task = _resolve_sample_customer(repository, payload, current_user)
    started_at = time.perf_counter()
    trace = _new_sample_extraction_trace(
        task_id=_sample_identity(payload),
        customer_id=customer_id,
        entrypoint="sample-extract-from-sample",
        request_payload=payload,
    )
    try:
        response = _run_sample_extraction_from_payload(
            payload=payload,
            customer_id=customer_id,
            repository=repository,
            runtime_store=runtime_store,
            prompt_pipeline=prompt_pipeline,
            started_at=started_at,
            trace=trace,
        )
    except Exception as exc:
        trace["error"] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }
        _persist_sample_extraction_trace(runtime_store, trace)
        raise
    trace["response"] = {
        "sampleSummary": response.sampleSummary,
        "rawOutput": response.rawOutput,
        "extractionResult": response.extractionResult.model_dump(),
        "errors": response.errors,
        "provider": response.provider,
        "model": response.model,
        "durationMs": response.durationMs,
        "inputChars": response.inputChars,
        "outputChars": response.outputChars,
        "promptTokens": response.promptTokens,
        "completionTokens": response.completionTokens,
        "totalTokens": response.totalTokens,
    }
    return response.model_copy(update=_persist_sample_extraction_trace(runtime_store, trace))


@router.post("/skills/sample-locate-and-extract", response_model=SkillSampleLocateAndExtractResponse)
def sample_locate_and_extract(
    payload: SkillSampleLocateAndExtractRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    runtime_store: JsonRuntimeStore = Depends(get_runtime_store),
    prompt_pipeline: PromptPipelineService = Depends(get_prompt_pipeline_service),
    semantic_locator_reranker: SemanticLocatorReranker | None = Depends(get_semantic_locator_reranker),
) -> SkillSampleLocateAndExtractResponse:
    customer_id, task = _resolve_sample_customer(repository, payload, current_user)
    sample_id = _sample_identity(payload)
    if task is not None:
        document = repository.get_document_record(task.documentId)
        document_tree = load_document_tree(runtime_store, task.id, document.id)
        document_id = document.id
        pages = []
    else:
        sample_context = payload.sampleContext
        document_tree = _sample_context_document_tree(payload)
        document_payload = getattr(sample_context, "document", {}) if sample_context is not None else {}
        document_id = str(document_payload.get("id") or document_payload.get("documentId") or sample_id)
        pages = _sample_context_pages(payload)
    started_at = time.perf_counter()
    query = payload.query.strip()
    trace = _new_sample_extraction_trace(
        task_id=sample_id,
        customer_id=customer_id,
        entrypoint="sample-locate-and-extract",
        request_payload=payload,
    )
    trace["documentTree"] = {
        "documentId": document_id,
        "moduleCount": len(document_tree.modules) if document_tree else 0,
        "hasTree": bool(document_tree and document_tree.modules),
    }
    if not document_tree or not document_tree.modules:
        trace["locator"] = {
            "status": "not_found",
            "errors": ["当前样例尚未生成可用于定位的文档树。"],
        }
        trace_fields = _persist_sample_extraction_trace(runtime_store, trace)
        return SkillSampleLocateAndExtractResponse(
            taskId=sample_id,
            customerId=customer_id,
            status="not_found",
            query=query,
            dataTypeName=query,
            outputPreference=payload.outputPreference,
            locatorProfile={},
            locatorSkillText="",
            durationMs=int((time.perf_counter() - started_at) * 1000),
            errors=["当前样例尚未生成可用于定位的文档树。"],
            **trace_fields,
        )

    settings = get_settings()
    effective_reranker = semantic_locator_reranker
    if effective_reranker is None and settings.dashscope_api_key:
        effective_reranker = DashScopeSemanticLocatorReranker(settings)
    locator_service = SemanticLocatorService(
        reranker=effective_reranker,
        rerank_top_k=settings.semantic_locator_llm_rerank_top_k,
        rerank_gap_threshold=settings.semantic_locator_llm_rerank_gap_threshold,
    )
    locator_profile = _build_sample_locator_profile(
        query=query,
        output_preference=payload.outputPreference,
        locator_instruction=payload.locatorInstruction,
    )
    locator_run = locator_service.locate(
        pages=pages,
        locator_profile=locator_profile,
        document_tree=document_tree,
    )
    candidates = [_sample_locate_candidate_payload(candidate) for candidate in locator_run.candidates[:8]]
    locator_result_payload = _sample_locator_result_payload(locator_run, selected_candidates=[])
    locator_skill_text = _build_sample_locator_skill_text(
        query=query,
        locator_profile=locator_profile,
        locator_result=locator_result_payload,
        located_source=None,
    )
    trace["locator"] = {
        "profile": locator_profile,
        "locatorSkillText": locator_skill_text,
        "selected": locator_run.selected,
        "confidence": locator_run.confidence,
        "reason": locator_run.reason,
        "candidateGap": locator_run.candidate_gap,
        "executionGate": locator_run.execution_gate,
        "warnings": list(locator_run.warnings),
        "candidates": candidates,
    }

    selected_candidates: list[LocatorCandidate] = []
    if payload.selectedCandidateId:
        selected_candidate = next((item for item in locator_run.candidates if item.node_id == payload.selectedCandidateId), None)
        if selected_candidate is None:
            trace["locator"]["status"] = "not_found"
            trace["locator"]["selectedCandidateId"] = payload.selectedCandidateId
            trace["locator"]["errors"] = ["所选候选节点已不存在，请重新定位。"]
            trace_fields = _persist_sample_extraction_trace(runtime_store, trace)
            return SkillSampleLocateAndExtractResponse(
                taskId=sample_id,
                customerId=customer_id,
                status="not_found",
                query=query,
                dataTypeName=query,
                outputPreference=payload.outputPreference,
                candidates=candidates,
                locatorResult=_sample_locator_result_payload(locator_run, selected_candidates=selected_candidates),
                locatorProfile=locator_profile,
                locatorSkillText=locator_skill_text,
                durationMs=int((time.perf_counter() - started_at) * 1000),
                errors=["所选候选节点已不存在，请重新定位。"],
                **trace_fields,
            )
        selected_candidates = [selected_candidate]
    elif locator_run.selected and locator_run.selected_candidates and effective_reranker is not None:
        selected_candidates = locator_run.selected_candidates[:4]
    initial_selected_ids = [candidate.node_id for candidate in selected_candidates]
    rejected_node_reasons = _locator_rejected_node_reasons(locator_run)
    classified_locator = _classify_locator_candidate_roles(
        selected_candidates=selected_candidates,
        candidates=locator_run.candidates,
        rejected_node_reasons=rejected_node_reasons,
    )
    selected_candidates = _sort_locator_candidates_by_document_order(
        classified_locator["extractionCandidates"]
    )
    trace["locator"].update(
        {
            "status": "selected" if selected_candidates else "needs_review",
            "selectedCandidateId": payload.selectedCandidateId,
            "initialSelectedNodeIds": initial_selected_ids,
            "selectedNodeIds": [candidate.node_id for candidate in selected_candidates],
            "expandedNodeIds": [
                item["nodeId"]
                for item in classified_locator["classifiedCandidates"]
                if item.get("role") == "continuation"
            ],
            "primaryNodeIds": [candidate.node_id for candidate in classified_locator["primaryCandidates"]],
            "continuationNodeIds": [candidate.node_id for candidate in classified_locator["continuationCandidates"]],
            "relatedNodeIds": [candidate.node_id for candidate in classified_locator["relatedCandidates"]],
            "rejectedNodeIds": [candidate.node_id for candidate in classified_locator["rejectedCandidates"]],
            "classifiedCandidates": classified_locator["classifiedCandidates"],
        }
    )
    locator_result_payload = _sample_locator_result_payload(
        locator_run,
        selected_candidates=selected_candidates,
        classified_locator=classified_locator,
    )
    locator_skill_text = _build_sample_locator_skill_text(
        query=query,
        locator_profile=locator_profile,
        locator_result=locator_result_payload,
        located_source=None,
    )
    trace["locator"]["locatorSkillText"] = locator_skill_text

    if not selected_candidates:
        status_value = "needs_review" if candidates else "not_found"
        trace["locator"]["status"] = status_value
        trace_fields = _persist_sample_extraction_trace(runtime_store, trace)
        return SkillSampleLocateAndExtractResponse(
            taskId=sample_id,
            customerId=customer_id,
            status=status_value,
            query=query,
            dataTypeName=query,
            outputPreference=payload.outputPreference,
            candidates=candidates,
            locatorResult=locator_result_payload,
            locatorProfile=locator_profile,
            locatorSkillText=locator_skill_text,
            durationMs=int((time.perf_counter() - started_at) * 1000),
            errors=list(locator_run.warnings),
            **trace_fields,
        )

    located_source = _build_sample_source_from_locator_candidates(
        query=query,
        candidates=selected_candidates,
        document_tree=document_tree,
    )
    trace["locatedSource"] = located_source.model_dump()
    locator_skill_text = _build_sample_locator_skill_text(
        query=query,
        locator_profile=locator_profile,
        locator_result=locator_result_payload,
        located_source=located_source.model_dump(),
    )
    trace["locator"]["locatorSkillText"] = locator_skill_text
    output_preference = _resolve_located_output_preference(payload.outputPreference, selected_candidates[0])
    sample_summary = {
        "locatedByQuery": True,
        "query": query,
        "locatorStatus": "selected_by_user" if payload.selectedCandidateId else "auto_selected",
        "locatorReason": locator_run.reason,
        "selectedCandidateId": selected_candidates[0].node_id,
        "selectedCandidateIds": [candidate.node_id for candidate in selected_candidates],
        "primaryCandidateIds": [candidate.node_id for candidate in classified_locator["primaryCandidates"]],
        "continuationCandidateIds": [
            candidate.node_id for candidate in classified_locator["continuationCandidates"]
        ],
        "relatedCandidateIds": [candidate.node_id for candidate in classified_locator["relatedCandidates"]],
        "rejectedCandidateIds": [candidate.node_id for candidate in classified_locator["rejectedCandidates"]],
        "sampleId": sample_id,
        "sampleChars": len(located_source.sourceText or ""),
        "sourceScope": located_source.sourceScope,
        "sourceLabel": located_source.title,
        "treeNodeId": located_source.treeNodeId,
        "treePath": located_source.treePath,
        "pageRange": located_source.pageRange,
        "contentRefs": located_source.contentRefs[:20],
    }
    user_expected_output = _normalize_sample_expected_output(payload.expectedOutput)
    expected_output = user_expected_output or _default_expected_output_for_preference(output_preference)
    extraction_payload = SkillDraftFromSampleRequest(
        taskId=payload.taskId,
        applicationId=payload.applicationId,
        sampleContext=payload.sampleContext,
        kind="extraction",
        instruction=_build_located_sample_instruction(
            query=query,
            output_preference=output_preference,
            source=located_source,
            extra_instruction=payload.extraInstruction,
            expected_output=user_expected_output,
        ),
        expectedOutput=expected_output,
        targetIds=[],
        pageNo=located_source.pageNo,
        customerId=customer_id,
        dataTypeName=query,
        sourceScope=located_source.sourceScope,
        sourceLabel=located_source.title,
        sourceText=located_source.sourceText,
        treeNodeId=located_source.treeNodeId,
        treePath=located_source.treePath,
        pageRange=located_source.pageRange,
        contentRefs=located_source.contentRefs,
    )
    if not payload.runExtraction:
        output_contract = _build_sample_output_contract_summary(extraction_payload)
        response = SkillSampleLocateAndExtractResponse(
            taskId=sample_id,
            customerId=customer_id,
            status="located",
            query=query,
            dataTypeName=query,
            outputPreference=output_preference,
            locatedSource=located_source,
            candidates=candidates,
            locatorResult=locator_result_payload,
            locatorProfile=locator_profile,
            locatorSkillText=locator_skill_text,
            sampleSummary=sample_summary,
            durationMs=int((time.perf_counter() - started_at) * 1000),
            inputChars=0,
            outputChars=0,
            errors=[],
            evidenceDiagnostics=_build_sample_evidence_diagnostics(extraction_payload, sample_summary),
            outputContractSummary=output_contract,
            validationReport=_build_sample_validation_report(
                kind="extraction",
                output_contract=output_contract,
            ),
        )
        trace["response"] = {
            "status": response.status,
            "sampleSummary": sample_summary,
            "errors": response.errors,
            "durationMs": response.durationMs,
        }
        return response.model_copy(update=_persist_sample_extraction_trace(runtime_store, trace))

    try:
        extraction_response = _run_sample_extraction_from_payload(
            payload=extraction_payload,
            customer_id=customer_id,
            repository=repository,
            runtime_store=runtime_store,
            prompt_pipeline=prompt_pipeline,
            started_at=started_at,
            trace=trace,
        )
    except Exception as exc:
        trace["error"] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }
        _persist_sample_extraction_trace(runtime_store, trace)
        raise
    sample_summary = {
        **sample_summary,
        **dict(extraction_response.sampleSummary or {}),
    }
    response = SkillSampleLocateAndExtractResponse(
        taskId=sample_id,
        customerId=customer_id,
        status="extracted",
        query=query,
        dataTypeName=query,
        outputPreference=output_preference,
        locatedSource=located_source,
        candidates=candidates,
        locatorResult=locator_result_payload,
        locatorProfile=locator_profile,
        locatorSkillText=locator_skill_text,
        sampleSummary=sample_summary,
        extractionResult=extraction_response.extractionResult,
        rawOutput=extraction_response.rawOutput,
        editableOutput=extraction_response.editableOutput,
        provider=extraction_response.provider,
        model=extraction_response.model,
        durationMs=extraction_response.durationMs,
        inputChars=extraction_response.inputChars,
        outputChars=extraction_response.outputChars,
        promptTokens=extraction_response.promptTokens,
        completionTokens=extraction_response.completionTokens,
        totalTokens=extraction_response.totalTokens,
        errors=extraction_response.errors,
        evidenceDiagnostics=extraction_response.evidenceDiagnostics,
        validationReport=extraction_response.validationReport,
        outputContractSummary=extraction_response.outputContractSummary,
    )
    trace["response"] = {
        "status": response.status,
        "sampleSummary": sample_summary,
        "rawOutput": response.rawOutput,
        "extractionResult": response.extractionResult.model_dump() if response.extractionResult else None,
        "errors": response.errors,
        "provider": response.provider,
        "model": response.model,
        "durationMs": response.durationMs,
        "inputChars": response.inputChars,
        "outputChars": response.outputChars,
        "promptTokens": response.promptTokens,
        "completionTokens": response.completionTokens,
        "totalTokens": response.totalTokens,
    }
    return response.model_copy(update=_persist_sample_extraction_trace(runtime_store, trace))


def _run_sample_extraction_from_payload(
    *,
    payload: SkillDraftFromSampleRequest,
    customer_id: str,
    repository: WorkbenchRepository,
    runtime_store: JsonRuntimeStore | None,
    prompt_pipeline: PromptPipelineService,
    started_at: float,
    trace: dict[str, Any] | None = None,
) -> SkillSampleExtractFromSampleResponse:
    payload = _hydrate_document_tree_sample_source(
        repository=repository,
        runtime_store=runtime_store,
        payload=payload,
        trace=trace,
    )
    sample_text, sample_summary = _build_skill_sample(repository, payload)
    if trace is not None:
        trace["sampleBuild"] = {
            "sampleText": sample_text,
            "sampleChars": len(sample_text),
            "sampleTextLimit": _skill_sample_text_limit(),
            "truncated": sample_text.endswith("...（样本已截断）"),
            "summary": sample_summary,
            "payloadSource": {
                "sourceScope": payload.sourceScope,
                "sourceLabel": payload.sourceLabel,
                "treeNodeId": payload.treeNodeId,
                "treePath": payload.treePath,
                "pageRange": payload.pageRange,
                "contentRefs": _compact_sample_content_refs(payload.contentRefs, limit=20),
                "targetIds": payload.targetIds,
            },
        }
    local_table_result = _try_local_table_sample_extraction(repository, payload, sample_summary, trace=trace)
    if local_table_result is not None:
        local_table_result = _sanitize_extraction_result_for_response(local_table_result)
        raw_payload = {
            "summary": local_table_result["summary"],
            "outputs": local_table_result["outputs"],
            "errors": local_table_result.get("errors", []),
        }
        output_chars = len(json.dumps(raw_payload, ensure_ascii=False, default=str))
        editable_output = _editable_output_from_extraction_result(local_table_result)
        errors = [
            str(item).strip()
            for item in (local_table_result.get("errors") or [])
            if str(item).strip()
        ]
        if trace is not None:
            trace["extraction"] = {
                "path": "local-table-parser",
                "rawOutput": raw_payload,
                "normalizedResult": local_table_result,
                "editableOutputChars": len(editable_output),
                "errors": errors,
            }
        output_contract = _build_sample_output_contract_summary(
            payload,
            extraction_result=local_table_result,
        )
        evidence_diagnostics = _build_sample_evidence_diagnostics(payload, sample_summary, trace=trace)
        validation_report = _build_sample_validation_report(
            kind=payload.kind,
            output_contract=output_contract,
            extraction_result=local_table_result,
            errors=errors,
        )
        return SkillSampleExtractFromSampleResponse(
            kind=payload.kind,
            taskId=_sample_identity(payload),
            customerId=customer_id,
            sampleSummary=sample_summary,
            extractionResult=ExtractionResult.model_validate(local_table_result),
            rawOutput=raw_payload,
            editableOutput=editable_output,
            provider="local",
            model="local-table-parser",
            durationMs=int((time.perf_counter() - started_at) * 1000),
            inputChars=len(sample_text),
            outputChars=output_chars,
            errors=errors,
            evidenceDiagnostics=evidence_diagnostics,
            validationReport=validation_report,
            outputContractSummary=output_contract,
        )
    runtime_kernel_response = _try_run_sample_extraction_with_runtime_kernel(
        payload=payload,
        customer_id=customer_id,
        repository=repository,
        prompt_pipeline=prompt_pipeline,
        sample_summary=sample_summary,
        started_at=started_at,
        trace=trace,
    )
    if runtime_kernel_response is not None:
        return runtime_kernel_response
    assist = run_sample_extraction_assist(
        instruction=payload.instruction,
        expected_output=payload.expectedOutput,
        sample_text=sample_text,
        data_type_name=payload.dataTypeName,
        source_scope=payload.sourceScope,
        source_label=payload.sourceLabel,
        customer_id=customer_id,
    )
    raw_payload = assist.get("rawPayload") if isinstance(assist.get("rawPayload"), dict) else {}
    extraction_result = _sanitize_extraction_result_for_response(
        _normalize_sample_extraction_result(raw_payload, payload, assist)
    )
    editable_output = _editable_output_from_extraction_result(extraction_result)
    errors = [
        str(item).strip()
        for item in (extraction_result.get("errors") or extraction_result.get("validationErrors") or [])
        if str(item).strip()
    ]
    if trace is not None:
        trace["extraction"] = {
            "path": "llm",
            "llmTrace": assist.get("trace") if isinstance(assist.get("trace"), dict) else {},
            "rawAnswer": assist.get("answer"),
            "reasoning": assist.get("reasoning"),
            "rawPayload": raw_payload,
            "normalizedResult": extraction_result,
            "editableOutputChars": len(editable_output),
            "provider": str(assist.get("provider") or "dashscope"),
            "model": str(assist.get("model") or ""),
            "durationMs": int(assist.get("durationMs") or 0),
            "inputChars": int(assist.get("inputChars") or 0),
            "outputChars": int(assist.get("outputChars") or 0),
            "promptTokens": assist.get("promptTokens") if isinstance(assist.get("promptTokens"), int) else None,
            "completionTokens": assist.get("completionTokens") if isinstance(assist.get("completionTokens"), int) else None,
            "totalTokens": assist.get("totalTokens") if isinstance(assist.get("totalTokens"), int) else None,
            "errors": errors,
        }
    output_contract = _build_sample_output_contract_summary(
        payload,
        extraction_result=extraction_result,
    )
    evidence_diagnostics = _build_sample_evidence_diagnostics(payload, sample_summary, trace=trace)
    validation_report = _build_sample_validation_report(
        kind=payload.kind,
        output_contract=output_contract,
        extraction_result=extraction_result,
        errors=errors,
    )
    return SkillSampleExtractFromSampleResponse(
        kind=payload.kind,
        taskId=_sample_identity(payload),
        customerId=customer_id,
        sampleSummary=sample_summary,
        extractionResult=ExtractionResult.model_validate(extraction_result),
        rawOutput=raw_payload,
        editableOutput=editable_output,
        provider=str(assist.get("provider") or "dashscope"),
        model=str(assist.get("model") or ""),
        durationMs=int(assist.get("durationMs") or 0),
        inputChars=int(assist.get("inputChars") or 0),
        outputChars=int(assist.get("outputChars") or 0),
        promptTokens=assist.get("promptTokens") if isinstance(assist.get("promptTokens"), int) else None,
        completionTokens=assist.get("completionTokens") if isinstance(assist.get("completionTokens"), int) else None,
        totalTokens=assist.get("totalTokens") if isinstance(assist.get("totalTokens"), int) else None,
        errors=errors,
        evidenceDiagnostics=evidence_diagnostics,
        validationReport=validation_report,
        outputContractSummary=output_contract,
    )


def _try_run_sample_extraction_with_runtime_kernel(
    *,
    payload: SkillDraftFromSampleRequest,
    customer_id: str,
    repository: WorkbenchRepository,
    prompt_pipeline: PromptPipelineService,
    sample_summary: dict[str, Any],
    started_at: float,
    trace: dict[str, Any] | None = None,
) -> SkillSampleExtractFromSampleResponse | None:
    if not (payload.contentRefs or payload.sampleContext is not None or payload.treeNodeId):
        return None
    pages, _load_page_targets, context_meta = _sample_pages_and_target_loader(repository, payload)
    if not pages:
        return None
    page_numbers = [
        int(getattr(page, "pageNo", 0) or 0)
        for page in pages
        if int(getattr(page, "pageNo", 0) or 0) > 0
    ]
    selected_page_numbers = _resolve_sample_page_numbers(payload, page_numbers)
    runtime_pages = [
        page
        for page in pages
        if int(getattr(page, "pageNo", 0) or 0) in selected_page_numbers
    ] or pages
    if not runtime_pages:
        return None
    output_type, renderer = _sample_output_contract(payload)
    if output_type not in {"field_list", "record_collection"}:
        if trace is not None:
            trace["runtimeKernel"] = {
                "used": False,
                "reason": "sample_output_type_uses_compact_llm_fallback",
                "outputType": output_type,
                "renderer": renderer,
            }
        return None
    runtime_build = build_sample_preview_runtime_request(
        pages=runtime_pages,
        selected_page_numbers=selected_page_numbers,
        sample_id=_sample_identity(payload),
        context_id=str(context_meta.get("contextId") or _sample_identity(payload)),
        instruction=payload.instruction,
        expected_output=payload.expectedOutput,
        data_type_name=payload.dataTypeName,
        source_label=payload.sourceLabel,
        source_text=payload.sourceText,
        tree_node_id=payload.treeNodeId,
        content_refs=payload.contentRefs,
        output_type=output_type,
        renderer=renderer,
    )
    result = prompt_pipeline.execute_extraction_runtime_request(
        runtime_build.request,
        started_at=started_at,
    )
    extraction_result = _sanitize_extraction_result_for_response(result.extraction_result)
    editable_output = _editable_output_from_extraction_result(extraction_result)
    errors = [
        str(item).strip()
        for item in (extraction_result.get("errors") or extraction_result.get("validationErrors") or result.errors)
        if str(item).strip()
    ]
    if trace is not None:
        trace["extraction"] = {
            "path": "extraction-runtime-kernel",
            "sourceMode": "sample_preview",
            "rawOutput": result.raw_payload,
            "normalizedResult": extraction_result,
            "provider": result.output.provider,
            "model": result.output.model,
            "durationMs": result.duration_ms,
            "inputChars": result.run_meta.get("inputChars"),
            "outputChars": result.run_meta.get("outputChars"),
            "metrics": result.metrics,
            "runtimeContract": runtime_build.runtime_contract,
            "errors": errors,
        }
    output_contract = _build_sample_output_contract_summary(
        payload,
        extraction_result=extraction_result,
    )
    evidence_diagnostics = _build_sample_evidence_diagnostics(payload, sample_summary, trace=trace)
    validation_report = _build_sample_validation_report(
        kind=payload.kind,
        output_contract=output_contract,
        extraction_result=extraction_result,
        errors=errors,
    )
    return SkillSampleExtractFromSampleResponse(
        kind=payload.kind,
        taskId=_sample_identity(payload),
        customerId=customer_id,
        sampleSummary=sample_summary,
        extractionResult=ExtractionResult.model_validate(extraction_result),
        rawOutput=result.raw_payload,
        editableOutput=editable_output,
        provider=result.output.provider,
        model=result.output.model,
        durationMs=result.duration_ms,
        inputChars=int(result.run_meta.get("inputChars") or 0),
        outputChars=int(result.run_meta.get("outputChars") or 0),
        promptTokens=result.run_meta.get("promptTokens") if isinstance(result.run_meta.get("promptTokens"), int) else None,
        completionTokens=result.run_meta.get("completionTokens") if isinstance(result.run_meta.get("completionTokens"), int) else None,
        totalTokens=result.run_meta.get("totalTokens") if isinstance(result.run_meta.get("totalTokens"), int) else None,
        errors=errors,
        evidenceDiagnostics=evidence_diagnostics,
        validationReport=validation_report,
        outputContractSummary=output_contract,
    )


def _build_sample_locator_profile(*, query: str, output_preference: str, locator_instruction: str = "") -> dict[str, Any]:
    positive_terms = _sample_query_positive_terms(query)
    query_terms = _sample_query_terms(query)
    locator_instruction = str(locator_instruction or "").strip()
    content_contracts = [
        f"目标节点需要承载用户想提取的数据块：{query}。",
        "优先选择标题、路径、摘要或内容与用户查询最直接一致的文档树节点。",
        "定位阶段不以表格或文本作为优先级；内容形态只在命中后用于抽取和预览。",
        "定位结果后续会用于生成可复用 Skill，因此节点应包含足够的样例结构和来源证据。",
    ]
    if locator_instruction:
        content_contracts.insert(1, f"用户定位要求：{locator_instruction}")
    return {
        "semanticSlot": query,
        "description": "由用户输入的数据块查询生成的样例制作定位画像。",
        "locatorInstruction": locator_instruction,
        "forceRerank": bool(locator_instruction),
        "positiveTerms": positive_terms,
        "queryTerms": query_terms,
        "negativeTerms": _sample_negative_terms(query),
        "expectedObjectTypes": [],
        "contentContracts": content_contracts,
        "confirmedOutputShape": [
            {
                "type": output_preference,
                "query": query,
                "preferredStructure": "table" if output_preference == "data_table" or _query_prefers_table(query) else "auto",
            }
        ],
        "reviewStatus": "draft",
        "gate": {
            "autoExecuteMinConfidence": 0.68,
            "minCandidateGap": 0.04,
        },
    }


def _sample_query_positive_terms(query: str) -> list[str]:
    values = [query]
    values.extend(item for item in re.split(r"\s+|/|,|，|、|;|；", query) if item.strip())
    return _unique_texts(values, limit=12)


def _sample_query_terms(query: str) -> list[str]:
    values = _sample_query_positive_terms(query)
    compact = re.sub(r"\s+", "", str(query or ""))
    if len(compact) > 3:
        values.extend(compact[index:index + 2] for index in range(0, len(compact) - 1))
    if len(compact) > 5:
        values.extend(compact[index:index + 3] for index in range(0, len(compact) - 2))
    return _unique_texts(values, limit=24)


def _sample_negative_terms(query: str) -> list[str]:
    return []


def _query_prefers_table(query: str) -> bool:
    return False


def _sample_locate_candidate_payload(candidate: LocatorCandidate) -> dict[str, Any]:
    payload = candidate.payload or {}
    pages = [int(item) for item in (payload.get("pages") or [candidate.page_no]) if _coerce_int(item)]
    return {
        "nodeId": candidate.node_id,
        "title": candidate.title,
        "type": candidate.type,
        "pageNo": candidate.page_no,
        "pageRange": _format_page_range(pages),
        "path": [str(item) for item in (payload.get("path") or []) if str(item).strip()],
        "excerpt": candidate.excerpt,
        "score": round(candidate.score, 3),
        "reasons": candidate.reasons[:8],
        "warnings": candidate.warnings[:8],
        "payload": {
            "source": payload.get("source"),
            "treeNodeId": payload.get("treeNodeId") or candidate.node_id,
            "pages": pages,
            "rowCount": payload.get("rowCount") or candidate.row_count,
            "columnCount": payload.get("columnCount") or candidate.column_count,
            "blockIds": list(payload.get("blockIds") or [])[:30],
            "tablePreviews": payload.get("tablePreviews") or [],
            "textPreviews": payload.get("textPreviews") or [],
        },
    }


def _sample_locator_result_payload(
    locator_run: LocatorRunResult,
    *,
    selected_candidates: list[LocatorCandidate] | None = None,
    classified_locator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = selected_candidates if selected_candidates is not None else locator_run.selected_candidates
    payload = {
        "selected": locator_run.selected,
        "confidence": locator_run.confidence,
        "reason": locator_run.reason,
        "candidateGap": locator_run.candidate_gap,
        "executionGate": locator_run.execution_gate,
        "selectedNodeIds": [item.node_id for item in selected],
        "candidates": [_sample_locate_candidate_payload(candidate) for candidate in locator_run.candidates[:8]],
    }
    if classified_locator:
        payload.update(
            {
                "extractionNodeIds": [item.node_id for item in classified_locator["extractionCandidates"]],
                "primaryNodeIds": [item.node_id for item in classified_locator["primaryCandidates"]],
                "continuationNodeIds": [item.node_id for item in classified_locator["continuationCandidates"]],
                "relatedNodeIds": [item.node_id for item in classified_locator["relatedCandidates"]],
                "rejectedNodeIds": [item.node_id for item in classified_locator["rejectedCandidates"]],
                "classifiedCandidates": classified_locator["classifiedCandidates"],
            }
        )
    return payload


def _build_sample_locator_skill_text(
    *,
    query: str,
    locator_profile: dict[str, Any],
    locator_result: dict[str, Any],
    located_source: dict[str, Any] | None,
) -> str:
    positive_terms = [str(item).strip() for item in (locator_profile.get("positiveTerms") or []) if str(item).strip()]
    negative_terms = [str(item).strip() for item in (locator_profile.get("negativeTerms") or []) if str(item).strip()]
    expected_types = [str(item).strip() for item in (locator_profile.get("expectedObjectTypes") or []) if str(item).strip()]
    contracts = [str(item).strip() for item in (locator_profile.get("contentContracts") or []) if str(item).strip()]
    locator_instruction = str(locator_profile.get("locatorInstruction") or "").strip()
    selected_node_ids = [str(item).strip() for item in (locator_result.get("selectedNodeIds") or []) if str(item).strip()]
    extraction_node_ids = [
        str(item).strip()
        for item in (locator_result.get("extractionNodeIds") or selected_node_ids)
        if str(item).strip()
    ]
    related_node_ids = [
        str(item).strip()
        for item in (locator_result.get("relatedNodeIds") or [])
        if str(item).strip()
    ]
    gate = locator_profile.get("gate") if isinstance(locator_profile.get("gate"), dict) else {}
    lines = [
        "# 定位 Skill",
        "",
        "## 目标",
        f"在新文档的文档树和内容对象中定位“{query}”对应的数据块，定位后再交给抽取 Skill 执行。",
        "",
        "## 定位画像",
        f"- 业务槽位：{locator_profile.get('semanticSlot') or query}",
        f"- 用户定位要求：{locator_instruction}" if locator_instruction else "- 用户定位要求：无",
        f"- 期望对象：{', '.join(expected_types) if expected_types else '表格、文本或结构化内容对象'}",
        f"- 正向信号：{', '.join(positive_terms[:16]) if positive_terms else '由样例节点和用户查询生成'}",
        f"- 排除信号：{', '.join(negative_terms[:16]) if negative_terms else '无'}",
        "",
        "## 内容契约",
    ]
    if contracts:
        lines.extend(f"- {item}" for item in contracts[:8])
    else:
        lines.append("- 候选节点必须包含足够的业务内容、结构和来源证据，不能只凭页码命中。")
    lines.extend(
        [
            "",
            "## 执行门禁",
            f"- 自动定位最低置信度：{gate.get('autoExecuteMinConfidence', '默认')}",
            f"- 候选差距阈值：{gate.get('minCandidateGap', '默认')}",
            "- 页码只能作为证据回看，不得作为定位规则。",
            "- 样例节点 ID、样例页码和样例标题只用于追溯制作过程，不得作为新文档定位规则。",
            "- 多个候选接近、存在排除信号、空表格或结构不完整时必须进入人工复核。",
            "",
            "## 样例定位结果（仅供追溯，不作为新文档固定规则）",
            f"- 状态：{'已命中' if extraction_node_ids else '待确认或未命中'}",
            f"- 样例抽取输入节点：{', '.join(extraction_node_ids) if extraction_node_ids else '无'}",
            f"- 样例相关但不混抽节点：{', '.join(related_node_ids) if related_node_ids else '无'}",
        ]
    )
    if located_source:
        tree_path = located_source.get("treePath")
        if isinstance(tree_path, list) and tree_path:
            lines.append(f"- 样例路径：{' / '.join(str(item) for item in tree_path)}")
        title = str(located_source.get("title") or "").strip()
        if title:
            lines.append(f"- 样例来源：{title}")
    reason = str(locator_result.get("reason") or "").strip()
    if reason:
        lines.extend(["", "## 样例定位理由（仅供追溯）", reason])
    return "\n".join(lines).strip() + "\n"


def _locator_rejected_node_reasons(locator_run: LocatorRunResult) -> dict[str, str]:
    gate = locator_run.execution_gate if isinstance(locator_run.execution_gate, dict) else {}
    rerank = gate.get("rerank") if isinstance(gate.get("rerank"), dict) else {}
    values = rerank.get("rejectedNodeIds") or rerank.get("rejected_node_ids") or []
    rejected: dict[str, str] = {}
    for item in values:
        if isinstance(item, dict):
            node_id = str(item.get("nodeId") or item.get("node_id") or item.get("id") or "").strip()
            reason = str(item.get("reason") or item.get("message") or "").strip()
        else:
            node_id = str(item).strip()
            reason = ""
        if node_id:
            rejected[node_id] = reason
    return rejected


def _locator_rejected_node_ids(locator_run: LocatorRunResult) -> set[str]:
    return set(_locator_rejected_node_reasons(locator_run))


def _classify_locator_candidate_roles(
    *,
    selected_candidates: list[LocatorCandidate],
    candidates: list[LocatorCandidate],
    rejected_node_reasons: dict[str, str],
) -> dict[str, Any]:
    ordered_selected = _sort_locator_candidates_by_document_order(selected_candidates)
    ordered_candidates = _sort_locator_candidates_by_document_order(candidates)
    if not ordered_selected:
        return {
            "extractionCandidates": [],
            "primaryCandidates": [],
            "continuationCandidates": [],
            "relatedCandidates": [],
            "rejectedCandidates": [],
            "classifiedCandidates": [],
        }

    primary_candidates = [ordered_selected[0]]
    continuation_candidates: list[LocatorCandidate] = []
    related_candidates: list[LocatorCandidate] = []
    rejected_candidates: list[LocatorCandidate] = []
    classified_by_id: dict[str, dict[str, Any]] = {}

    def add_candidate(candidate: LocatorCandidate, role: str, reason: str, *, extraction_input: bool) -> None:
        if candidate.node_id in classified_by_id:
            return
        classified_by_id[candidate.node_id] = _locator_candidate_role_payload(
            candidate=candidate,
            role=role,
            reason=reason,
            extraction_input=extraction_input,
            rejected_reason=rejected_node_reasons.get(candidate.node_id, ""),
        )
        if role == "primary":
            if candidate.node_id not in {item.node_id for item in primary_candidates}:
                primary_candidates.append(candidate)
        elif role == "continuation":
            continuation_candidates.append(candidate)
        elif role == "related":
            related_candidates.append(candidate)
        elif role == "rejected":
            rejected_candidates.append(candidate)

    primary = primary_candidates[0]
    add_candidate(primary, "primary", "LLM 或用户确认的主定位模块。", extraction_input=True)

    for candidate in ordered_selected[1:]:
        if candidate.node_id == primary.node_id:
            continue
        if _is_locator_continuation(primary, candidate):
            add_candidate(candidate, "continuation", "与主定位模块结构兼容，作为同一抽取对象的续表/连续模块。", extraction_input=True)
        elif _is_locator_related(primary, candidate):
            add_candidate(candidate, "related", "语义相关但结构不属于同一抽取对象，保留为相关定位资产。", extraction_input=False)
        else:
            add_candidate(candidate, "related", "LLM 选中多个模块，但该模块与主模块结构不兼容，需作为相关资产单独处理。", extraction_input=False)

    def extraction_anchors() -> list[LocatorCandidate]:
        return [*primary_candidates, *continuation_candidates]

    def relation_anchors() -> list[LocatorCandidate]:
        return [*primary_candidates, *continuation_candidates, *related_candidates]

    for candidate in ordered_candidates:
        if candidate.node_id in classified_by_id:
            continue
        if any(_is_locator_continuation(anchor, candidate) for anchor in extraction_anchors()):
            reason = "与已确认抽取输入结构兼容，作为同一抽取对象的续表/连续模块。"
            if candidate.node_id in rejected_node_reasons:
                reason += " LLM 复判曾排除该节点，本次保留结构证据供复核。"
            add_candidate(candidate, "continuation", reason, extraction_input=True)
            continue
        if any(_is_locator_related(anchor, candidate) for anchor in relation_anchors()):
            reason = "与定位主题存在文档树或结构关联，但不进入当前抽取输入。"
            if candidate.node_id in rejected_node_reasons:
                reason += " LLM 复判也将其排除出当前抽取对象。"
            add_candidate(candidate, "related", reason, extraction_input=False)
            continue
        if candidate.node_id in rejected_node_reasons:
            add_candidate(candidate, "rejected", "LLM 复判排除，且未发现同一结构或近邻语义关联。", extraction_input=False)

    extraction_candidates = _sort_locator_candidates_by_document_order([*primary_candidates, *continuation_candidates])
    classified_candidates = sorted(
        classified_by_id.values(),
        key=lambda item: (
            {"primary": 0, "continuation": 1, "related": 2, "rejected": 3}.get(str(item.get("role")), 9),
            int(item.get("pageNo") or 0),
            str(item.get("nodeId") or ""),
        ),
    )
    return {
        "extractionCandidates": extraction_candidates,
        "primaryCandidates": primary_candidates,
        "continuationCandidates": _sort_locator_candidates_by_document_order(continuation_candidates),
        "relatedCandidates": _sort_locator_candidates_by_document_order(related_candidates),
        "rejectedCandidates": _sort_locator_candidates_by_document_order(rejected_candidates),
        "classifiedCandidates": classified_candidates,
    }


def _locator_candidate_role_payload(
    *,
    candidate: LocatorCandidate,
    role: str,
    reason: str,
    extraction_input: bool,
    rejected_reason: str = "",
) -> dict[str, Any]:
    payload = _sample_locate_candidate_payload(candidate)
    payload.update(
        {
            "role": role,
            "roleLabel": {
                "primary": "主定位模块",
                "continuation": "同一抽取对象续表",
                "related": "相关模块",
                "rejected": "已排除模块",
            }.get(role, role),
            "roleReason": reason,
            "extractionInput": extraction_input,
        }
    )
    if rejected_reason:
        payload["rejectedReason"] = rejected_reason
    return payload


def _expand_locator_continuation_candidates(
    selected_candidates: list[LocatorCandidate],
    candidates: list[LocatorCandidate],
    *,
    rejected_node_ids: set[str] | None = None,
) -> list[LocatorCandidate]:
    if not selected_candidates:
        return []
    rejected = rejected_node_ids or set()
    expanded: list[LocatorCandidate] = list(selected_candidates)
    selected_ids = {item.node_id for item in expanded}
    for candidate in candidates:
        if len(expanded) >= 4:
            break
        if candidate.node_id in selected_ids or candidate.node_id in rejected:
            continue
        if any(_is_locator_continuation(base, candidate) for base in expanded):
            expanded.append(candidate)
            selected_ids.add(candidate.node_id)
    return expanded


def _sort_locator_candidates_by_document_order(candidates: list[LocatorCandidate]) -> list[LocatorCandidate]:
    return sorted(candidates, key=lambda item: (min(_candidate_pages(item) or [item.page_no]), item.node_id))


def _is_locator_continuation(base: LocatorCandidate, candidate: LocatorCandidate) -> bool:
    if base.type != "table" or candidate.type != "table":
        return False
    if candidate.warnings and any("阻断" in warning or "空表格" in warning for warning in candidate.warnings):
        return False
    base_pages = _candidate_pages(base)
    candidate_pages = _candidate_pages(candidate)
    if base_pages and candidate_pages:
        if min(candidate_pages) > max(base_pages) + 1 or max(candidate_pages) < min(base_pages) - 1:
            return False
    base_path = _candidate_path(base)
    candidate_path = _candidate_path(candidate)
    same_near_path = bool(
        base_path
        and candidate_path
        and (
            base_path == candidate_path
            or base_path[:-1] == candidate_path[:-1]
            or base_path[-1:] == candidate_path[-1:]
        )
    )
    base_headers = _candidate_header_values(base)
    candidate_headers = _candidate_header_values(candidate)
    if base_headers and candidate_headers:
        similarity = _header_similarity(base_headers, candidate_headers)
        if similarity >= 0.45:
            return True
        if similarity < 0.45 and not (base_path and candidate_path and base_path == candidate_path):
            return False
    base_tokens = _candidate_structure_tokens(base)
    candidate_tokens = _candidate_structure_tokens(candidate)
    overlap = len(base_tokens & candidate_tokens)
    if same_near_path and overlap >= 4:
        return True
    if overlap >= 6:
        return True
    return False


def _candidate_header_values(candidate: LocatorCandidate) -> list[str]:
    for row in _candidate_preview_rows(candidate)[:8]:
        cells = [str(cell or "").strip() for cell in row]
        non_empty = [cell for cell in cells if cell]
        if len(non_empty) >= 3 and not _is_detail_data_row(cells):
            return non_empty
    return []


def _candidate_preview_rows(candidate: LocatorCandidate) -> list[list[str]]:
    payload = candidate.payload or {}
    rows: list[list[str]] = []
    for key in ("rowPreview", "tablePreviews"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(_extract_preview_rows(value))
    return rows


def _extract_preview_rows(value: list[Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in value:
        if isinstance(item, dict):
            nested = item.get("rows") or item.get("rowPreview") or item.get("previewRows") or []
            if isinstance(nested, list):
                rows.extend(_extract_preview_rows(nested))
        elif isinstance(item, list):
            if any(isinstance(cell, list) for cell in item):
                rows.extend(_extract_preview_rows(item))
            else:
                normalized = [str(cell or "").strip() for cell in item]
                if any(normalized):
                    rows.append(normalized)
    return rows


def _is_locator_related(base: LocatorCandidate, candidate: LocatorCandidate) -> bool:
    if base.node_id == candidate.node_id:
        return False
    base_pages = _candidate_pages(base)
    candidate_pages = _candidate_pages(candidate)
    page_distance = None
    if base_pages and candidate_pages:
        page_distance = min(abs(left - right) for left in base_pages for right in candidate_pages)

    base_path = _candidate_path(base)
    candidate_path = _candidate_path(candidate)
    same_parent_path = bool(
        base_path
        and candidate_path
        and (
            base_path[:-1] == candidate_path[:-1]
            or base_path[:1] == candidate_path[:1]
            or base_path[-1:] == candidate_path[-1:]
        )
    )
    base_tokens = _candidate_structure_tokens(base)
    candidate_tokens = _candidate_structure_tokens(candidate)
    overlap = len(base_tokens & candidate_tokens)
    if same_parent_path and overlap >= 2:
        return True
    if overlap >= 3:
        return True
    if page_distance is not None and page_distance <= 2 and overlap >= 2:
        return True
    return False


def _candidate_pages(candidate: LocatorCandidate) -> list[int]:
    pages = [
        _coerce_int(item)
        for item in (candidate.payload or {}).get("pages", [])
    ]
    values = [page for page in pages if page]
    if not values and candidate.page_no:
        values = [candidate.page_no]
    return sorted(set(int(page) for page in values if int(page) > 0))


def _candidate_path(candidate: LocatorCandidate) -> list[str]:
    return [str(item).strip() for item in (candidate.payload or {}).get("path", []) if str(item).strip()]


def _candidate_structure_tokens(candidate: LocatorCandidate) -> set[str]:
    parts: list[str] = [candidate.title, candidate.excerpt]
    payload = candidate.payload or {}
    for key in ("rowPreview", "tablePreviews", "textPreviews"):
        value = payload.get(key)
        if isinstance(value, list):
            parts.extend(_flatten_preview_text(value))
        elif value:
            parts.append(str(value))
    return set(_split_structure_tokens(" ".join(parts)))


def _flatten_preview_text(value: list[Any]) -> list[str]:
    texts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            for nested in item.values():
                texts.extend(_preview_value_texts(nested))
        elif isinstance(item, list):
            texts.extend(_preview_value_texts(item))
        elif item is not None:
            texts.append(str(item))
    return texts


def _preview_value_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        texts: list[str] = []
        for nested in value.values():
            texts.extend(_preview_value_texts(nested))
        return texts
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            texts.extend(_preview_value_texts(item))
        return texts
    return [str(value)]


def _split_structure_tokens(text: str) -> list[str]:
    values = [
        token.strip()
        for token in re.split(r"\s+|/|,|，|、|;|；|\||：|:|\(|\)|（|）", str(text or ""))
        if token.strip()
    ]
    tokens: list[str] = []
    for value in values:
        if len(value) <= 24:
            tokens.append(value)
        if len(value) > 3:
            tokens.extend(value[index:index + 2] for index in range(0, min(len(value) - 1, 18)))
    return _unique_texts(tokens, limit=80)


def _build_sample_source_from_locator_candidate(
    *,
    query: str,
    candidate: LocatorCandidate,
    document_tree,
) -> SkillSampleLocatedSource:
    return _build_sample_source_from_locator_candidates(
        query=query,
        candidates=[candidate],
        document_tree=document_tree,
    )


def _build_sample_source_from_locator_candidates(
    *,
    query: str,
    candidates: list[LocatorCandidate],
    document_tree,
) -> SkillSampleLocatedSource:
    if not candidates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未选择可用于抽取的文档树模块。")
    document_modules = [module for module in (getattr(document_tree, "modules", []) or []) if isinstance(module, dict)]
    candidate_by_id = {candidate.node_id: candidate for candidate in candidates}
    scope_resolution = expand_document_tree_modules(document_modules, [candidate.node_id for candidate in candidates])
    module_items: list[tuple[LocatorCandidate, dict[str, Any], str, str]] = []
    if scope_resolution.items:
        for item in scope_resolution.items:
            candidate = candidate_by_id.get(item.module_id) or candidates[0]
            module_items.append((candidate, item.module, item.reason, item.reason_label))
    else:
        for candidate in candidates:
            module = _find_document_tree_module(document_tree, candidate.node_id)
            module_payload = module if module is not None else candidate.payload
            module_items.append((candidate, module_payload, "selected_node", "选中节点"))

    first_candidate, first_module, _, _ = module_items[0]
    first_title = str(first_module.get("title") or first_candidate.title or query).strip()
    first_summary = str(first_module.get("summary") or first_module.get("directSummary") or first_candidate.excerpt or "").strip()
    first_path = [str(item) for item in (first_module.get("path") or first_candidate.payload.get("path") or []) if str(item).strip()]
    content_refs: list[dict[str, Any]] = []
    source_parts: list[str] = []
    all_reasons: list[str] = []
    source_chars = 0
    source_limit = 16000
    module_preview_limit = 2200

    for index, (candidate, module_payload, scope_reason, scope_reason_label) in enumerate(module_items, start=1):
        pages = [
            int(item)
            for item in (module_payload.get("pages") or candidate.payload.get("pages") or [candidate.page_no])
            if _coerce_int(item)
        ]
        block_ids = _module_block_ids(module_payload)
        title = str(module_payload.get("title") or candidate.title or query).strip()
        source_text = _module_skill_input(module_payload)
        if len(source_text) > module_preview_limit:
            source_text = f"{source_text[:module_preview_limit]}\n...（模块预览已截断，完整证据范围见 contentRefs）"
        heading = f"## 命中模块 {index}：{title or candidate.node_id}"
        source_part = "\n".join([heading, source_text]).strip()
        if source_part and source_chars < source_limit:
            remaining = source_limit - source_chars
            if len(source_part) > remaining:
                source_parts.append(f"{source_part[:remaining]}\n...（样例来源预览已截断，完整证据范围见 contentRefs）")
                source_chars = source_limit
            else:
                source_parts.append(source_part)
                source_chars += len(source_part)
        content_refs.append(
            {
                "kind": "document_tree_module",
                "nodeId": str(module_payload.get("id") or candidate.node_id),
                "title": title,
                "path": list(module_payload.get("path") or candidate.payload.get("path") or []),
                "blockIds": block_ids,
                "evidencePages": pages,
                "role": "extraction_input",
                "scopeReason": scope_reason,
                "scopeReasonLabel": scope_reason_label,
            }
        )
        all_reasons.extend(candidate.reasons[:4])

    selected_count = len(module_items)
    title = f"文档树 · {first_title}" if selected_count == 1 else f"文档树 · {first_title} 等 {selected_count} 个模块"
    summary_parts = [first_summary or first_candidate.excerpt]
    if selected_count > 1:
        summary_parts.append(f"共命中 {selected_count} 个文档树模块，按逻辑范围合并作为样例来源。")
    source_scope = "文档树定位模块"
    if selected_count > 1:
        source_scope = f"文档树定位模块（含逻辑子集 {selected_count} 个模块）"
    return SkillSampleLocatedSource(
        mode="tree",
        kind="extraction",
        title=title,
        summary=" ".join(part for part in summary_parts if part).strip(),
        sourceScope=source_scope,
        sourceText="\n\n".join(part for part in source_parts if part).strip(),
        pageNo=None,
        pageIndex=None,
        targetIds=[],
        treeNodeId=str(first_module.get("id") or first_candidate.node_id),
        treePath=first_path,
        pageRange=None,
        contentRefs=content_refs,
        locatorReason="；".join(_unique_texts(all_reasons, limit=8)) or first_candidate.excerpt,
    )

def _find_document_tree_module(document_tree, node_id: str) -> dict[str, Any] | None:
    for module in getattr(document_tree, "modules", []) or []:
        if isinstance(module, dict) and str(module.get("id") or "") == node_id:
            return module
    return None


def _module_skill_input(module: dict[str, Any]) -> str:
    skill_input = str(module.get("skillInput") or module.get("directSkillInput") or "").strip()
    if skill_input:
        return skill_input
    content = module.get("content") if isinstance(module.get("content"), dict) else {}
    lines = [
        f"模块：{module.get('title') or ''}",
        f"路径：{' / '.join(str(item) for item in (module.get('path') or []))}",
        f"证据页码：{_format_page_range([int(item) for item in (module.get('pages') or []) if _coerce_int(item)])}",
    ]
    for text in (content.get("texts") or [])[:12]:
        if isinstance(text, dict):
            lines.append(f"- 文本：{str(text.get('content') or text.get('title') or '')[:1200]}")
    for table in (content.get("tables") or [])[:8]:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        lines.append(f"\n### {table.get('title') or '表格'}")
        lines.extend(_rows_to_markdown_lines(rows[:80]))
    return "\n".join(line for line in lines if str(line).strip()).strip()


def _module_block_ids(module: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(str(item) for item in (module.get("blockIds") or []) if str(item).strip())
    content = module.get("content") if isinstance(module.get("content"), dict) else {}
    for group_key in ("tables", "texts"):
        for item in content.get(group_key) or []:
            if not isinstance(item, dict):
                continue
            values.extend(str(block_id) for block_id in (item.get("blockIds") or []) if str(block_id).strip())
    return _unique_texts(values, limit=80)


def _rows_to_markdown_lines(rows: list[Any]) -> list[str]:
    normalized_rows = [
        [str(cell or "").strip() for cell in row]
        for row in rows
        if isinstance(row, list) and any(str(cell or "").strip() for cell in row)
    ]
    if not normalized_rows:
        return []
    width = max(len(row) for row in normalized_rows)
    normalized = [row + [""] * (width - len(row)) for row in normalized_rows]
    lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in normalized[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |")
    return lines


def _resolve_located_output_preference(preference: str, candidate: LocatorCandidate) -> str:
    _ = candidate
    if preference and preference != "auto":
        return preference
    return "auto"


def _default_expected_output_for_preference(preference: str) -> str:
    if preference == "data_table":
        return "表格：表头、行数据、合并单元格说明、来源页码。"
    if preference == "record_collection":
        return "记录集合：每条记录包含字段和值、来源页码。"
    if preference == "notes":
        return "说明列表：主题、说明内容、结论、来源页码。"
    if preference == "auto":
        return "按命中文档树模块的真实内容形态输出结构化 JSON；不要预设为表格或字段列表。若是章节段落，保留条款/说明/金额等要点和来源页码；若是表格，保留表头、行数据和来源页码。"
    return "字段列表：字段名、字段值、来源页码。"


def _build_located_sample_instruction(
    *,
    query: str,
    output_preference: str,
    source: SkillSampleLocatedSource,
    extra_instruction: str,
    expected_output: str = "",
) -> str:
    extra_instruction = _normalize_sample_extra_instruction(extra_instruction)
    user_expected_output = _normalize_sample_expected_output(expected_output)
    output_hint = user_expected_output or _default_expected_output_for_preference(output_preference)
    lines = [
        f"数据类型：{query}",
        f"样例来源：{source.title}",
        f"样例范围：{source.sourceScope}",
        "处理目标：从已定位的文档树模块中提取用户查询的数据块，形成可复用的结构化样例输出。",
        f"{'用户输出要求' if user_expected_output else '系统默认输出建议'}：{output_hint}",
        "",
        "定位约束：",
        "- 当前样例已经由文档树定位得到，只能基于该模块内容抽取。",
        "- 定位规则不得依赖固定页码；页码只能作为样例证据和复核信息。",
        "- 复用时应优先使用文档树节点标题、路径、表头、行列结构、相邻上下文和内容形态来重新定位。",
        "- 后续发布应用时应按相同语义和结构特征在新文档树中重新定位。",
        "- 不要抽取与用户查询数据块不属于同一语义槽位或同一结构范围的相邻内容。",
    ]
    if extra_instruction:
        lines.extend(["", "用户抽取要求：", extra_instruction])
    return "\n".join(lines)


def _normalize_sample_extra_instruction(value: str) -> str:
    text = str(value or "").strip()
    default_texts = {
        "提取这类内容中的关键字段和值，例如编号、名称、日期、主体、金额等；字段缺失时保持为空，并保留来源证据。",
        "把这类表格整理成结构化表格，保留表头、行列关系、合并单元格含义和来源证据。",
        "把这类连续文本或列表整理成多条记录，每条记录拆出主体、时间、金额、状态、说明等可识别字段。",
        "提取这类说明、备注、结论或异常提示，保留完整语义和来源证据，避免只截取片段。",
        "把这类内容整理成结构化数据，保留来源页码，后续同类材料可以自动提取。",
        "基于这类数据做核对、判断和异常提示，输出可以复核的处理结论。",
    }
    return "" if text in default_texts else text


def _normalize_sample_expected_output(value: str) -> str:
    text = str(value or "").strip()
    default_texts = {
        "字段列表：字段名、字段值、来源页码、原文片段。",
        "表格：表头、行数据、合并单元格说明、来源页码和原文片段。",
        "记录集合：每条记录包含字段和值、来源页码；跨页连续时保持同一组记录。",
        "说明列表：主题、说明内容、结论、来源页码。",
        "处理结果：结论、原因、证据、需要人工复核的异常项。",
        "可以不填。系统会按字段、表格、记录集合或说明列表自动生成。",
        "按命中文档树模块的真实内容形态输出结构化 JSON；不要预设为表格或字段列表。若是章节段落，保留条款/说明/金额等要点和来源页码；若是表格，保留表头、行数据和来源页码。",
    }
    return "" if text in default_texts else text


def _format_page_range(pages: list[int]) -> str:
    values = sorted({int(page) for page in pages if int(page) > 0})
    if not values:
        return ""
    if len(values) == 1:
        return f"第 {values[0]} 页"
    if values == list(range(values[0], values[-1] + 1)):
        return f"第 {values[0]}-{values[-1]} 页"
    return "第 " + "、".join(str(item) for item in values[:12]) + ("..." if len(values) > 12 else "") + " 页"


def _page_range_payload(pages: list[int]) -> dict[str, Any] | None:
    values = sorted({int(page) for page in pages if int(page) > 0})
    if not values:
        return None
    return {"start": values[0], "end": values[-1], "pages": values}


def _unique_texts(values: list[Any], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _coerce_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


@router.post("/skills/sample-process-from-sample", response_model=SkillSampleProcessFromSampleResponse)
def sample_process_from_sample(
    payload: SkillDraftFromSampleRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SkillSampleProcessFromSampleResponse:
    if payload.kind != "operation":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="样例试处理仅支持 operation 业务处理步骤。")
    customer_id, _task = _resolve_sample_customer(repository, payload, current_user)
    if not payload.targetIds and not payload.sourceText.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="样例试处理需要先选择一个提取结果或提供应用样例输入。")
    sample_text, sample_summary = _build_skill_sample(repository, payload)
    assist = run_sample_process_assist(
        instruction=payload.instruction,
        expected_output=payload.expectedOutput,
        sample_text=sample_text,
        data_type_name=payload.dataTypeName,
        source_scope=payload.sourceScope,
        source_label=payload.sourceLabel,
        customer_id=customer_id,
    )
    raw_payload = assist.get("rawPayload") if isinstance(assist.get("rawPayload"), dict) else {}
    processed = _normalize_sample_process_result(raw_payload)
    editable_output = _editable_output_from_process_result(processed)
    errors = [
        str(item).strip()
        for item in (processed.get("validationErrors") or [])
        if str(item).strip()
    ]
    output_contract = _build_sample_output_contract_summary(payload, process_result=processed)
    evidence_diagnostics = _build_sample_evidence_diagnostics(payload, sample_summary)
    validation_report = _build_sample_validation_report(
        kind=payload.kind,
        output_contract=output_contract,
        process_result=processed,
        errors=errors,
    )
    return SkillSampleProcessFromSampleResponse(
        kind=payload.kind,
        taskId=_sample_identity(payload),
        customerId=customer_id,
        sampleSummary=sample_summary,
        summary=str(processed.get("summary") or ""),
        resultKind=processed.get("resultKind") if processed.get("resultKind") in {"decision", "object", "table", "text"} else "object",  # type: ignore[arg-type]
        outputPayload=processed.get("outputPayload"),
        validationErrors=processed.get("validationErrors") if isinstance(processed.get("validationErrors"), list) else [],
        rawOutput=raw_payload,
        editableOutput=editable_output,
        provider=str(assist.get("provider") or "dashscope"),
        model=str(assist.get("model") or ""),
        durationMs=int(assist.get("durationMs") or 0),
        inputChars=int(assist.get("inputChars") or 0),
        outputChars=int(assist.get("outputChars") or 0),
        promptTokens=assist.get("promptTokens") if isinstance(assist.get("promptTokens"), int) else None,
        completionTokens=assist.get("completionTokens") if isinstance(assist.get("completionTokens"), int) else None,
        totalTokens=assist.get("totalTokens") if isinstance(assist.get("totalTokens"), int) else None,
        errors=errors,
        evidenceDiagnostics=evidence_diagnostics,
        validationReport=validation_report,
        outputContractSummary=output_contract,
    )


@router.get("/skills/{skillId}")
def get_skill_detail(
    skillId: str,
    kind: str = Query("extraction"),
    scope: Optional[str] = Query(None),
    customerId: Optional[str] = Query(None),
    includeText: bool = Query(False),
    current_user: SessionUser = Depends(get_current_user),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> dict[str, Any]:
    if scope not in {None, "platform", "customer"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope 只支持 platform 或 customer。")
    if scope == "customer" and not customerId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="读取客户 Skill 必须提供 customerId。")
    if scope == "platform":
        customerId = None
    if customerId:
        ensure_customer_access(customerId, current_user)
    return _resolve_skill_detail(
        kind=kind,
        skill_id=skillId,
        scope=scope or ("customer" if customerId else "platform"),
        customer_id=customerId,
        include_text=includeText,
        include_inactive=True,
        business_registry=business_registry,
        extraction_registry=extraction_registry,
    )


@router.post("/skills/copy-draft", response_model=SkillCopyDraftResponse)
def copy_skill_draft(
    payload: SkillCopyDraftRequest,
    current_user: SessionUser = Depends(get_current_user),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> SkillCopyDraftResponse:
    if payload.sourceCustomerId:
        ensure_customer_access(payload.sourceCustomerId, current_user)
    ensure_customer_access(payload.targetCustomerId, current_user)
    detail = _resolve_skill_detail(
        kind=payload.kind,
        skill_id=payload.sourceSkillId,
        scope="customer" if payload.sourceCustomerId else "platform",
        customer_id=payload.sourceCustomerId,
        include_text=True,
        include_inactive=True,
        business_registry=business_registry,
        extraction_registry=extraction_registry,
    )
    source_text = str(detail.get("skillText") or "")
    if not source_text.strip():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 内容不存在，无法复制。")
    draft_text = _rewrite_skill_identity_for_copy(source_text, source_id=payload.sourceSkillId)
    return SkillCopyDraftResponse(
        kind=payload.kind,
        sourceSkillId=payload.sourceSkillId,
        targetCustomerId=payload.targetCustomerId,
        skillText=draft_text,
    )


@router.patch("/skills/{skillId}/ownership")
def update_skill_ownership(
    skillId: str,
    payload: SkillOwnershipUpdateRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> dict[str, Any]:
    ensure_customer_access(payload.sourceCustomerId, current_user)
    ensure_customer_access(payload.targetCustomerId, current_user)
    record = repository.get_business_skill(skillId, payload.sourceCustomerId)
    if record.customerId is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="平台 Skill 不能修改归属，请使用复制到客户。")
    if payload.kind == "extraction" and record.category != "extraction":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill 类型不匹配。")
    if payload.kind == "operation" and record.category == "extraction":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill 类型不匹配。")
    moved = repository.move_business_skill(skillId, payload.sourceCustomerId, payload.targetCustomerId)
    detail = _resolve_skill_detail(
        kind=payload.kind,
        skill_id=moved.id,
        scope="customer",
        customer_id=payload.targetCustomerId,
        include_text=True,
        include_inactive=True,
        business_registry=business_registry,
        extraction_registry=extraction_registry,
    )
    return detail


@router.get("/skills/{skillId}/samples", response_model=list[SkillSampleResponse])
def list_skill_samples(
    skillId: str,
    kind: str = Query("extraction"),
    customerId: Optional[str] = Query(None),
    includeContent: bool = Query(False),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> list[SkillSampleResponse]:
    if customerId:
        ensure_customer_access(customerId, current_user)
    records = repository.list_skill_samples(kind=kind, skillId=skillId, customerId=customerId, limit=20)
    return [_skill_sample_response(record, include_content=includeContent) for record in records]


@router.post("/skills/{skillId}/samples", response_model=SkillSampleResponse)
def save_skill_sample(
    skillId: str,
    payload: SkillSampleUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SkillSampleResponse:
    customer_id = payload.customerId or _default_customer_id(current_user)
    ensure_customer_access(customer_id, current_user)
    if payload.skillId != skillId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="路径中的 skillId 与样本 skillId 不一致。")
    data = payload.content.encode("utf-8")
    preview = _sample_excerpt(payload.content, limit=2000)
    storage = _build_oss_storage()
    uploaded = storage.upload_file(
        customerId=customer_id,
        fileName=payload.fileName or "skill-sample.txt",
        contentType=payload.contentType or "text/plain; charset=utf-8",
        data=data,
    )
    now = datetime.now(timezone.utc).isoformat()
    record = SkillSampleRecord(
        id=f"sample-{uuid4().hex[:12]}",
        kind=payload.kind,
        skillId=skillId,
        version=payload.version or "1.0.0",
        customerId=customer_id,
        instruction=payload.instruction,
        objectKey=uploaded.objectKey,
        contentType=payload.contentType or "text/plain; charset=utf-8",
        fileName=payload.fileName or "skill-sample.txt",
        sizeBytes=len(data),
        preview=preview,
        createdAt=now,
        updatedAt=now,
    )
    saved = repository.save_skill_sample(record)
    return _skill_sample_response(saved, content=payload.content)


@router.get("/skills/{skillId}/test-runs", response_model=list[SkillTestRunSummary])
def list_skill_test_runs(
    skillId: str,
    kind: str = Query("extraction"),
    customerId: Optional[str] = Query(None),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> list[SkillTestRunSummary]:
    if customerId:
        ensure_customer_access(customerId, current_user)
    records = repository.list_skill_test_runs(kind=kind, skillId=skillId, customerId=customerId, limit=20)
    return [_skill_test_run_response(record, include_payload=False) for record in records]


@router.get("/skills/{skillId}/test-runs/{runId}", response_model=SkillTestRunSummary)
def get_skill_test_run_detail(
    skillId: str,
    runId: str,
    kind: str = Query("extraction"),
    customerId: Optional[str] = Query(None),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SkillTestRunSummary:
    if customerId:
        ensure_customer_access(customerId, current_user)
    records = repository.list_skill_test_runs(kind=kind, skillId=skillId, customerId=customerId, limit=100)
    for record in records:
        if record.id == runId:
            return _skill_test_run_response(record, include_payload=True)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill test run not found")


@router.post("/skills")
def create_skill(
    payload: UnifiedSkillUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> dict[str, Any]:
    customer_id = payload.customerId or _default_customer_id(current_user)
    ensure_customer_access(customer_id, current_user)
    try:
        if payload.kind == "operation":
            parsed = business_registry.parse_markdown(payload.skillText, customer_id=customer_id)
            _ensure_controlled_python_admin(parsed.executor, current_user)
            return business_registry.save_customer_skill(
                payload.skillText,
                customer_id=customer_id,
                updated_by=current_user.id,
            ).model_dump()
        skill_text = ensure_extraction_skill_semantic_governance(payload.skillText)
        return extraction_registry.save_customer_skill(
            skill_text,
            customer_id=customer_id,
            updated_by=current_user.id,
        ).model_dump()
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.patch("/skills/{skillId}")
def update_skill(
    skillId: str,
    payload: UnifiedSkillUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> dict[str, Any]:
    customer_id = payload.customerId or _default_customer_id(current_user)
    ensure_customer_access(customer_id, current_user)
    try:
        if payload.kind == "operation":
            parsed = business_registry.parse_markdown(payload.skillText, customer_id=customer_id)
            if parsed.id != skillId:
                raise ValueError("路径中的 skillId 与 SKILL.md id 不一致。")
            _ensure_controlled_python_admin(parsed.executor, current_user)
            return business_registry.save_customer_skill(
                payload.skillText,
                customer_id=customer_id,
                updated_by=current_user.id,
            ).model_dump()
        skill_text = ensure_extraction_skill_semantic_governance(payload.skillText)
        parsed = extraction_registry.parse_markdown(skill_text, customer_id=customer_id)
        if parsed.id != skillId:
            raise ValueError("路径中的 skillId 与 SKILL.md id 不一致。")
        return extraction_registry.save_customer_skill(
            skill_text,
            customer_id=customer_id,
            updated_by=current_user.id,
        ).model_dump()
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/skills/validate", response_model=SkillValidateResponse)
def validate_skill(
    payload: SkillValidateRequest,
    current_user: SessionUser = Depends(get_current_user),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> SkillValidateResponse:
    if payload.customerId:
        ensure_customer_access(payload.customerId, current_user)
    try:
        if payload.kind == "operation":
            record = business_registry.parse_markdown(payload.skillText, customer_id=payload.customerId)
        else:
            record = extraction_registry.parse_markdown(payload.skillText, customer_id=payload.customerId)
        return SkillValidateResponse(
            valid=True,
            skillId=record.id,
            version=record.version,
            name=record.name,
            executor=record.executor,
        )
    except ValueError as error:
        return SkillValidateResponse(valid=False, errors=[str(error)])


@router.post("/skills/assist", response_model=SkillAssistResponse)
def assist_skill(
    payload: SkillAssistRequest,
    current_user: SessionUser = Depends(get_current_user),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> SkillAssistResponse:
    if payload.customerId:
        ensure_customer_access(payload.customerId, current_user)
    response = run_skill_assist(payload)
    errors = list(response.errors)
    try:
        if payload.kind == "operation":
            business_registry.parse_markdown(response.skillText, customer_id=payload.customerId)
        else:
            extraction_registry.parse_markdown(response.skillText, customer_id=payload.customerId)
    except ValueError as error:
        errors.append(str(error))
    return response.model_copy(update={"valid": not errors, "errors": errors})


@router.post("/skills/test-run", response_model=SkillTestRunResponse)
def test_run_skill(
    payload: SkillTestRunRequest,
    current_user: SessionUser = Depends(get_current_user),
    business_registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
    extraction_registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
    llm_service: PromptLlmService = Depends(get_prompt_llm_service),
    prompt_pipeline: PromptPipelineService = Depends(get_prompt_pipeline_service),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SkillTestRunResponse:
    if payload.customerId:
        ensure_customer_access(payload.customerId, current_user)
    if payload.kind == "operation":
        response = _test_run_operation_skill(
            payload=payload,
            business_registry=business_registry,
            llm_service=llm_service,
        )
        _persist_skill_test_run_if_requested(payload, response, repository)
        return response
    try:
        skill = extraction_registry.parse_markdown(payload.skillText, customer_id=payload.customerId)
        config = dict(skill.defaults or {})
        config.update(payload.config or {})
        facts = _build_test_facts(payload.sampleText)
        skill_meta = {
            "id": skill.id,
            "version": skill.version,
            "name": skill.name,
            "category": skill.category,
            "sourceTypes": list(skill.sourceTypes),
            "executor": skill.executor,
            "inputBuilder": skill.inputBuilder,
            "renderer": skill.renderer,
            "outputSchema": skill.outputSchema,
            "summaryTemplate": skill.summaryTemplate,
            "promptTemplate": skill.promptTemplate,
            "rules": list(skill.rules),
            "examples": list(skill.examples),
        }
        runtime_result = prompt_pipeline.execute_extraction_runtime_request(
            build_skill_test_runtime_request(
                skill_meta=skill_meta,
                config=config,
                facts_payload=facts,
                sample_label="样本内容",
            )
        )
        response = SkillTestRunResponse(
            valid=not bool(runtime_result.errors),
            errors=[str(item) for item in runtime_result.errors],
            facts=facts,
            rawOutput=runtime_result.raw_payload,
            extractionResult=ExtractionResult.model_validate(runtime_result.extraction_result),
            durationMs=runtime_result.duration_ms,
            provider=runtime_result.output.provider,
            model=runtime_result.output.model,
            inputChars=int(runtime_result.run_meta.get("inputChars") or 0),
            outputChars=int(runtime_result.run_meta.get("outputChars") or 0),
        )
        _persist_skill_test_run_if_requested(payload, response, repository)
        return response
    except Exception as error:
        response = SkillTestRunResponse(
            valid=False,
            errors=[str(error)],
            facts=_safe_build_test_facts(payload.sampleText),
        )
        _persist_skill_test_run_if_requested(payload, response, repository)
        return response


def _test_run_operation_skill(
    *,
    payload: SkillTestRunRequest,
    business_registry: BusinessSkillRegistry,
    llm_service: PromptLlmService,
) -> SkillTestRunResponse:
    try:
        skill = business_registry.parse_markdown(payload.skillText, customer_id=payload.customerId)
        config = merge_skill_config(skill, payload.config)
        selected_targets = _build_operation_test_targets(payload.sampleText)
        if not selected_targets:
            raise RuntimeError("未能从样本中生成处理对象。")

        target = selected_targets[0]
        related_targets = selected_targets[1:]
        operation_type = _operation_type_for_skill_executor(skill.executor)
        result_mode = skill.resultKind if skill.resultKind in {"decision", "object", "table", "text"} else "auto"
        instruction = _build_skill_instruction(
            skill_name=skill.name,
            prompt_template=skill.promptTemplate,
            config=config,
            selected_targets=selected_targets,
        )
        skill_meta = {
            "id": skill.id,
            "version": skill.version,
            "name": skill.name,
            "executor": skill.executor,
            "resultKind": skill.resultKind,
            "renderer": skill.renderer,
            "config": config,
            "defaults": dict(skill.defaults or {}),
            "outputSchema": skill.outputSchema,
            "promptTemplate": skill.promptTemplate,
            "examples": skill.examples,
        }
        facts = {
            "page": {"pageNo": 1, "pageIndex": 0, "pageSize": []},
            "target": target.model_dump(),
            "relatedTargets": [item.model_dump() for item in related_targets],
            "latestExtractionResult": _compact_operation_sample_overview(selected_targets),
        }
        started = time.perf_counter()
        output = _try_run_skill_object_operation(
            page_no=1,
            operation_type=operation_type,
            result_mode=result_mode,
            target=target.model_dump(),
            related_targets=[item.model_dump() for item in related_targets],
            facts_payload=facts,
            skill_meta=skill_meta,
        )
        if output is None:
            output = llm_service.run_object_operation(
                taskId="skill-test-run",
                pageNo=1,
                operationType=operation_type,
                instruction=instruction,
                resultMode=result_mode,
                target=target.model_dump(),
                relatedTargets=[item.model_dump() for item in related_targets],
                factsPayload=facts,
            )
        output = _attach_skill_metadata_to_output(output, skill_meta)
        duration_ms = int((time.perf_counter() - started) * 1000)
        raw_payload = output.structuredProcessResult if isinstance(output.structuredProcessResult, dict) else {}
        validation_errors = [str(item) for item in (raw_payload.get("validationErrors") or output.validationErrors or [])]
        input_chars = len(json.dumps({"skill": skill_meta, "config": config, "facts": facts}, ensure_ascii=False))
        output_chars = len(json.dumps(raw_payload, ensure_ascii=False))
        return SkillTestRunResponse(
            valid=not validation_errors,
            errors=validation_errors,
            facts=facts,
            rawOutput=raw_payload,
            extractionResult=None,
            durationMs=duration_ms,
            provider=output.provider or ("local" if output.model.startswith("business-skill-") else None),
            model=output.model,
            inputChars=input_chars,
            outputChars=output_chars,
        )
    except (ValueError, RuntimeError) as error:
        return SkillTestRunResponse(
            valid=False,
            errors=[str(error)],
            facts={"sample": _sample_excerpt(payload.sampleText)},
        )


def _build_operation_test_targets(sample_text: str) -> list[OperationTargetRef]:
    sample_data = _parse_operation_sample(sample_text)
    targets = _operation_targets_from_sample_data(sample_data)
    if targets:
        return targets
    text = str(sample_text or "").strip()
    return [
        OperationTargetRef(
            id="sample-output",
            pageNo=1,
            type="output",
            label="处理样本",
            valueText="文本样本",
            excerpt=_sample_excerpt(text),
            data={"text": text},
        )
    ]


def _parse_operation_sample(sample_text: str) -> Any:
    text = str(sample_text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    table_match = re.search(r"<table[\s\S]*?</table>", text, flags=re.IGNORECASE)
    if table_match:
        parsed_table = parse_table_html(table_match.group(0))
        canonical_table = parsed_table.get("canonicalTable") if isinstance(parsed_table, dict) else None
        if isinstance(canonical_table, dict):
            return {
                "headers": [str(item) for item in (canonical_table.get("headers") or [])],
                "rows": [
                    [str(cell) for cell in row]
                    for row in (canonical_table.get("rows") or [])
                    if isinstance(row, list)
                ],
            }
    return {"text": text}


def _operation_targets_from_sample_data(data: Any) -> list[OperationTargetRef]:
    if isinstance(data, list):
        return [_operation_target_from_data("sample-records", "记录集合样本", {"records": data}, target_type="record_collection")]
    if not isinstance(data, dict):
        return []

    targets: list[OperationTargetRef] = []
    outputs = data.get("outputs")
    if isinstance(outputs, list):
        for index, output in enumerate(outputs):
            if isinstance(output, dict):
                targets.append(_operation_target_from_output(output, index))
        return [item for item in targets if item is not None]

    fields = data.get("fields")
    if isinstance(fields, list):
        field_row: dict[str, str] = {}
        for index, item in enumerate(fields):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("key") or f"字段 {index + 1}").strip()
            if label:
                field_row[label] = str(item.get("value") or "")
        if field_row:
            targets.append(_operation_target_from_data("sample-fields", "字段集合样本", field_row, target_type="output"))

    tables = data.get("tables")
    if isinstance(tables, list):
        for index, table in enumerate(tables):
            if isinstance(table, dict):
                targets.append(_operation_target_from_data(f"sample-table-{index + 1}", str(table.get("title") or f"表格 {index + 1}"), table, target_type="table"))

    structured_objects = data.get("structuredObjects")
    if isinstance(structured_objects, list):
        for index, item in enumerate(structured_objects):
            if isinstance(item, dict):
                targets.append(_operation_target_from_data(f"sample-structured-object-{index + 1}", str(item.get("title") or f"复合对象 {index + 1}"), item, target_type="structured_object"))

    if targets:
        return targets
    return [_operation_target_from_data("sample-output", "处理样本", data, target_type=_infer_operation_target_type(data))]


def _operation_target_from_output(output: dict[str, Any], index: int) -> OperationTargetRef:
    output_type = str(output.get("type") or "output").strip()
    title = str(output.get("title") or f"提取结果 {index + 1}").strip()
    data = output.get("data") if isinstance(output.get("data"), dict) else {}
    if output_type == "field_list" and isinstance(data.get("fields"), list):
        row: dict[str, str] = {}
        for field_index, item in enumerate(data.get("fields") or []):
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("key") or f"字段 {field_index + 1}").strip()
                if label:
                    row[label] = str(item.get("value") or "")
        data = row
    return _operation_target_from_data(
        f"sample-output-{index + 1}",
        title,
        data,
        target_type={
            "data_table": "table",
            "kv_record_table": "structured_object",
            "record_collection": "record_collection",
        }.get(output_type, "output"),
    )


def _operation_target_from_data(
    target_id: str,
    label: str,
    data: dict[str, Any],
    *,
    target_type: str,
) -> OperationTargetRef:
    headers = _headers_from_operation_data(data)
    row_count = _row_count_from_operation_data(data)
    return OperationTargetRef(
        id=target_id,
        pageNo=1,
        type=target_type,  # type: ignore[arg-type]
        label=label or "处理样本",
        valueText=_sample_value_text(row_count=row_count, headers=headers),
        excerpt=_sample_excerpt(json.dumps(data, ensure_ascii=False)),
        rowCount=row_count or None,
        columnCount=len(headers) or None,
        headers=headers,
        groupLabel="试跑样本",
        data=data,
    )


def _infer_operation_target_type(data: dict[str, Any]) -> str:
    if isinstance(data.get("records"), list):
        return "record_collection"
    if isinstance(data.get("table"), list) and isinstance(data.get("kv"), dict):
        return "structured_object"
    if isinstance(data.get("rows"), list):
        return "table"
    return "output"


def _headers_from_operation_data(data: dict[str, Any]) -> list[str]:
    headers = [str(item).strip() for item in (data.get("headers") or []) if str(item).strip()]
    if headers:
        return headers
    if isinstance(data.get("kv"), dict):
        return [str(item).strip() for item in data["kv"].keys() if str(item).strip()]
    if isinstance(data.get("records"), list):
        for record in data["records"]:
            if isinstance(record, dict):
                return [str(item).strip() for item in record.keys() if str(item).strip()]
    if isinstance(data.get("table"), list):
        for row in data["table"]:
            if isinstance(row, dict):
                return [str(item).strip() for item in row.keys() if str(item).strip()]
    return [str(item).strip() for item in data.keys() if str(item).strip()]


def _row_count_from_operation_data(data: dict[str, Any]) -> int:
    for key in ("records", "rows", "table"):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return 1 if data else 0


def _sample_value_text(*, row_count: int, headers: list[str]) -> str:
    parts: list[str] = []
    if row_count:
        parts.append(f"{row_count} 行")
    if headers:
        parts.append(f"{len(headers)} 字段")
    return " · ".join(parts) or "处理样本"


def _try_local_table_sample_extraction(
    repository: WorkbenchRepository,
    payload: SkillDraftFromSampleRequest,
    sample_summary: dict[str, Any],
    trace: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    output_type, renderer = _sample_output_contract(payload)
    local_trace: dict[str, Any] | None = None
    if trace is not None:
        local_trace = {
            "outputType": output_type,
            "renderer": renderer,
            "used": False,
            "reason": "",
            "selectedPages": [],
            "selectedBlockIds": [],
            "tableBlocks": [],
        }
        trace["localTableParser"] = local_trace
    if payload.kind != "extraction" or output_type != "data_table":
        if local_trace is not None:
            local_trace["reason"] = "not_extraction_or_output_type_not_data_table"
        return None
    if _has_user_controlled_sample_extraction(payload):
        if local_trace is not None:
            local_trace["reason"] = "user_custom_extraction_prompt"
        return None

    pages, _load_page_targets, context_meta = _sample_pages_and_target_loader(repository, payload)
    if not pages:
        if local_trace is not None:
            local_trace["reason"] = "no_sample_pages"
            local_trace["runtimeContext"] = context_meta
        return None
    selected_pages = _resolve_sample_page_numbers(payload, [page.pageNo for page in pages])
    selected_block_ids = _sample_content_ref_block_ids(payload.contentRefs)
    block_binding = _resolve_sample_runtime_block_binding(
        pages=pages,
        selected_pages=selected_pages,
        selected_block_ids=selected_block_ids,
        content_refs=payload.contentRefs,
    )
    active_block_ids = set(block_binding.get("activeBlockIds") or [])
    use_page_scope = bool(block_binding.get("usePageScope"))
    if local_trace is not None:
        local_trace["selectedPages"] = selected_pages
        local_trace["selectedBlockIds"] = sorted(selected_block_ids)
        local_trace["blockBinding"] = block_binding
        local_trace["activeBlockIds"] = sorted(active_block_ids)
        local_trace["runtimeContext"] = context_meta
    table_blocks: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(getattr(page, "pageNo", 0) or 0)
        if page_no not in selected_pages:
            continue
        for block in getattr(page, "blocks", []) or []:
            block_id = str(getattr(block, "id", "") or "")
            if active_block_ids and block_id not in active_block_ids:
                continue
            if selected_block_ids and not use_page_scope and not active_block_ids:
                continue
            block_type = str(getattr(block, "type", "") or "").lower()
            raw_html = str(getattr(block, "htmlContent", "") or getattr(block, "content", "") or "")
            if not _is_runtime_table_block(block):
                continue
            block_trace: dict[str, Any] = {
                "pageNo": page_no,
                "blockId": block_id,
                "title": str(getattr(block, "title", "") or "表格数据"),
                "blockType": block_type,
                "htmlChars": len(raw_html),
                "tableHtmlCount": 0,
                "tables": [],
            }
            for table_html in _extract_html_tables(raw_html):
                block_trace["tableHtmlCount"] = int(block_trace["tableHtmlCount"] or 0) + 1
                try:
                    parsed = parse_table_html(table_html, title=str(getattr(block, "title", "") or ""))
                except ValueError as error:
                    block_trace["tables"].append({"parseError": str(error), "htmlChars": len(table_html)})
                    continue
                canonical = parsed.get("canonicalTable") if isinstance(parsed, dict) else None
                if not isinstance(canonical, dict):
                    block_trace["tables"].append({"parseError": "missing_canonical_table", "htmlChars": len(table_html)})
                    continue
                headers = [str(item or "").strip() for item in (canonical.get("headers") or [])]
                rows = [
                    [str(cell or "").strip() for cell in row]
                    for row in (canonical.get("rows") or [])
                    if isinstance(row, list) and any(str(cell or "").strip() for cell in row)
                ]
                if not headers and not rows:
                    block_trace["tables"].append({"headers": headers, "rowCount": 0, "empty": True})
                    continue
                block_trace["tables"].append(
                    {
                        "headers": headers,
                        "rowCount": len(rows),
                        "firstRows": rows[:3],
                        "htmlChars": len(table_html),
                        "parseWarnings": parsed.get("parseWarnings") if isinstance(parsed, dict) else [],
                        "complexTableTodo": parsed.get("complexTableTodo") if isinstance(parsed, dict) else None,
                    }
                )
                table_blocks.append(
                    {
                        "pageNo": page_no,
                        "blockId": block_id,
                        "title": str(getattr(block, "title", "") or "表格数据"),
                        "headers": headers,
                        "rows": rows,
                        "parsed": parsed,
                        "parseWarnings": parsed.get("parseWarnings") if isinstance(parsed, dict) else [],
                        "complexTableTodo": parsed.get("complexTableTodo") if isinstance(parsed, dict) else None,
                    }
                )
            if local_trace is not None:
                local_trace["tableBlocks"].append(block_trace)

    should_use_local = bool(table_blocks and _should_use_local_table_sample(payload, table_blocks))
    if local_trace is not None:
        local_trace["candidateTableCount"] = len(table_blocks)
        local_trace["candidateRowCount"] = sum(len(table.get("rows") or []) for table in table_blocks)
        local_trace["shouldUseLocal"] = should_use_local
    if not table_blocks or not should_use_local:
        if local_trace is not None:
            local_trace["reason"] = "no_table_blocks" if not table_blocks else "local_parser_not_required"
            local_trace["todo"] = _complex_table_todo_summary(table_blocks)
        return None

    consolidated = _try_consolidate_continuation_tables(payload, table_blocks)
    if consolidated is not None:
        detail_rows = consolidated["rows"]
        source_pages = [int(page_no) for page_no in (consolidated.get("sourcePages") or []) if _coerce_int(page_no)]
        page_count = len(set(source_pages))
        raw_row_count = sum(len(table.get("rows") or []) for table in table_blocks)
        sample_summary.update(
            {
                "localSampleExtraction": True,
                "localSampleReason": "multi_or_long_table",
                "tableCount": int(consolidated.get("sourceTableCount") or len(table_blocks)),
                "examinedTableCount": len(table_blocks),
                "rawTableRowCount": raw_row_count,
                "candidateRowCount": len(detail_rows),
                "candidatePageCount": page_count,
                "consolidatedContinuationTable": True,
            }
        )
        if local_trace is not None:
            local_trace.update(
                {
                    "used": True,
                    "reason": "consolidated_continuation_table",
                    "mode": "consolidated",
                    "sourceTableCount": int(consolidated.get("sourceTableCount") or len(table_blocks)),
                    "examinedTableCount": len(table_blocks),
                    "skippedTables": consolidated.get("skippedTables") or [],
                    "sourcePages": consolidated["sourcePages"],
                    "rawTableRowCount": raw_row_count,
                    "outputRowCount": len(detail_rows),
                    "headers": consolidated["headers"],
                    "todo": _complex_table_todo_summary(table_blocks),
                }
            )
        output = {
            "id": "sample-local-table-merged-1",
            "title": consolidated["title"],
            "type": output_type,
            "renderer": renderer,
            "data": {
                "headers": consolidated["headers"],
                "rows": detail_rows,
                "mergeNotes": consolidated["mergeNotes"],
                "evidence": consolidated["evidence"],
            },
            "schema": {},
            "sourceRefs": [],
        }
        warning = "多页同结构表格已按表头和连续行合并为一张候选明细表；请确认行数和表头后再生成模板。"
        validation_errors = []
        complex_todo_warning = _complex_table_todo_warning(table_blocks)
        if complex_todo_warning:
            validation_errors.append(complex_todo_warning)
        return {
            "summary": f"本地合并解析到 1 个跨页明细表，共 {len(detail_rows)} 行数据。",
            "outputs": [output],
            "errors": [],
            "runMeta": {
                "provider": "local",
                "model": "local-table-parser",
                "sampleOnly": True,
                "localSampleExtraction": True,
                "consolidatedContinuationTable": True,
                "warnings": [warning],
            },
            "fields": [],
            "tables": [
                {
                    "title": consolidated["title"],
                    "headers": consolidated["headers"],
                    "rows": detail_rows,
                    "source": "parser",
                    "evidenceRefs": [],
                    "parserMeta": {
                        "localSampleExtraction": True,
                        "consolidatedContinuationTable": True,
                        "sourceTableCount": int(consolidated.get("sourceTableCount") or len(table_blocks)),
                        "examinedTableCount": len(table_blocks),
                        "skippedTables": consolidated.get("skippedTables") or [],
                        "sourcePages": consolidated["sourcePages"],
                    },
                }
            ],
            "structuredObjects": [],
            "validationErrors": validation_errors,
        }

    outputs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    total_rows = 0
    for index, table in enumerate(table_blocks, start=1):
        title = table["title"] or f"{payload.dataTypeName or '表格数据'} {index}"
        headers = table["headers"]
        rows = table["rows"]
        total_rows += len(rows)
        evidence = [{"source_page": _page_label(table["pageNo"]), "block_id": table["blockId"]}]
        data = {
            "headers": headers,
            "rows": rows,
            "mergeNotes": _table_merge_notes(table["parsed"]),
            "evidence": evidence,
        }
        outputs.append(
            {
                "id": f"sample-local-table-{index}",
                "title": title,
                "type": output_type,
                "renderer": renderer,
                "data": data,
                "schema": {},
                "sourceRefs": [],
            }
        )
        tables.append(
            {
                "title": title,
                "headers": headers,
                "rows": rows,
                "source": "parser",
                "evidenceRefs": [],
                "parserMeta": {
                    "pageNo": table["pageNo"],
                    "blockId": table["blockId"],
                    "localSampleExtraction": True,
                    "parseWarnings": table.get("parseWarnings") or [],
                    "complexTableTodo": table.get("complexTableTodo"),
                },
            }
        )

    page_count = len({int(table["pageNo"]) for table in table_blocks})
    sample_summary.update(
        {
            "localSampleExtraction": True,
            "localSampleReason": "multi_or_long_table",
            "tableCount": len(table_blocks),
            "candidateRowCount": total_rows,
            "candidatePageCount": page_count,
        }
    )
    if local_trace is not None:
        local_trace.update(
            {
                "used": True,
                "reason": "multi_or_long_table",
                "mode": "separate_tables",
                "sourceTableCount": len(table_blocks),
                "candidateRowCount": total_rows,
                "candidatePageCount": page_count,
                "outputCount": len(outputs),
                "todo": _complex_table_todo_summary(table_blocks),
            }
        )
    warning = "多表或长表样例已优先使用本地表格解析，AI 不再逐行搬运整表；请确认候选结果后再生成模板。"
    complex_todo_warning = _complex_table_todo_warning(table_blocks)
    validation_errors = [warning] if _has_high_cost_table_risk(payload, table_blocks) else []
    if complex_todo_warning:
        validation_errors.append(complex_todo_warning)
    return {
        "summary": f"本地解析到 {len(table_blocks)} 个表格，共 {total_rows} 行数据。",
        "outputs": outputs,
        "errors": [],
        "runMeta": {
            "provider": "local",
            "model": "local-table-parser",
            "sampleOnly": True,
            "localSampleExtraction": True,
            "warnings": [warning],
        },
        "fields": [],
        "tables": tables,
        "structuredObjects": [],
        "validationErrors": validation_errors,
    }


def _extract_html_tables(raw_html: str) -> list[str]:
    text = str(raw_html or "").strip()
    if not text:
        return []
    matches = [match.group(0) for match in re.finditer(r"<table[\s\S]*?</table>", text, flags=re.IGNORECASE)]
    if matches:
        return matches
    return [text] if "<tr" in text.lower() and "</tr>" in text.lower() else []


def _complex_table_todo_summary(tables: list[dict[str, Any]]) -> dict[str, Any]:
    todo_items = [
        item.get("complexTableTodo")
        for item in tables
        if isinstance(item.get("complexTableTodo"), dict) and item["complexTableTodo"].get("required")
    ]
    return {
        "complexTableTodo": bool(todo_items),
        "status": "todo" if todo_items else "not_required",
        "message": _complex_table_todo_warning(tables) or "",
        "tableCount": len(todo_items),
        "cellCount": sum(int(item.get("cellCount") or 0) for item in todo_items),
        "samples": todo_items[:3],
    }


def _complex_table_todo_warning(tables: list[dict[str, Any]]) -> str:
    if not any(
        isinstance(item.get("complexTableTodo"), dict) and item["complexTableTodo"].get("required")
        for item in tables
    ):
        return ""
    return (
        "检测到合并单元格/复杂表格结构：当前版本保留结构和来源证据，但复杂表格语义归属仍是 TODO，"
        "需要人工确认或后续复杂表格专项能力处理。"
    )


def _try_consolidate_continuation_tables(
    payload: SkillDraftFromSampleRequest,
    tables: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if len(tables) < 3:
        return None

    inferred_headers: list[str] = []
    merged_rows: list[list[str]] = []
    source_pages: list[int] = []
    source_block_ids: list[str] = []
    non_detail_rows: list[list[str]] = []
    header_found = False
    skipped_tables: list[dict[str, Any]] = []
    included_table_count = 0

    for table in tables:
        rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        if not rows:
            continue

        header_index = _find_embedded_header_row(rows)
        if header_index is not None and not header_found:
            inferred_headers = [str(cell or "").strip() for cell in rows[header_index]]
            header_found = True
        elif not header_found and not inferred_headers and not _headers_are_generic(table.get("headers") or []):
            inferred_headers = [str(cell or "").strip() for cell in (table.get("headers") or [])]
            header_found = bool(inferred_headers)

        candidate_headers = (
            [str(cell or "").strip() for cell in rows[header_index]]
            if header_index is not None
            else [str(cell or "").strip() for cell in (table.get("headers") or [])]
        )
        if header_found and inferred_headers and not _is_continuation_table_compatible(
            anchor_headers=inferred_headers,
            candidate_headers=candidate_headers,
            rows=rows,
        ):
            skipped_tables.append(
                {
                    "pageNo": table.get("pageNo"),
                    "blockId": table.get("blockId"),
                    "title": table.get("title"),
                    "reason": "incompatible_header_or_width",
                    "headers": candidate_headers[:12],
                }
            )
            continue

        if table.get("pageNo") not in source_pages:
            source_pages.append(int(table.get("pageNo") or 0))
        if table.get("blockId"):
            source_block_ids.append(str(table.get("blockId")))
        included_table_count += 1

        data_start = header_index + 1 if header_index is not None else 0
        for row in rows[data_start:]:
            normalized = [str(cell or "").strip() for cell in row]
            if _is_detail_data_row(normalized):
                merged_rows.append(normalized)
                continue
            if _is_non_detail_context_row(normalized):
                non_detail_rows.append(normalized)

    if not header_found or len(merged_rows) < 3:
        return None

    width = max(len(inferred_headers), max((len(row) for row in merged_rows), default=0))
    if width <= 1:
        return None
    headers = _normalize_table_width(inferred_headers, width, fill_prefix="列")
    rows = [_normalize_table_width(row, width, fill_prefix="") for row in merged_rows]
    merge_notes = [
        f"系统将 {included_table_count} 个同结构表格按嵌入表头和连续明细行合并为一张表。",
        f"明细行数：{len(rows)}；来源页：{', '.join(_page_label(page) for page in source_pages if page)}。",
    ]
    if non_detail_rows:
        merge_notes.append(f"检测到 {len(non_detail_rows)} 行非明细上下文，未并入明细行，已保留在证据中。")
    if skipped_tables:
        merge_notes.append(f"检测到 {len(skipped_tables)} 个相邻但结构不兼容的表格，未并入本明细表。")
    evidence: list[dict[str, Any]] = [
        {
            "source_page": _page_label(page),
            "block_ids": source_block_ids,
        }
        for page in source_pages
        if page
    ]
    if non_detail_rows:
        evidence.append({"source_page": _page_label(source_pages[-1] if source_pages else 0), "non_detail_rows": non_detail_rows[:5]})
    return {
        "title": payload.dataTypeName.strip() or "跨页明细表",
        "headers": headers,
        "rows": rows,
        "mergeNotes": merge_notes,
        "evidence": evidence,
        "sourcePages": source_pages,
        "sourceTableCount": included_table_count,
        "skippedTables": skipped_tables,
    }


def _find_embedded_header_row(rows: list[Any]) -> Optional[int]:
    for index, row in enumerate(rows[:8]):
        if not isinstance(row, list):
            continue
        cells = [str(cell or "").strip() for cell in row]
        non_empty = [cell for cell in cells if cell]
        if len(non_empty) < 3:
            continue
        if _is_detail_data_row(cells) or _row_numeric_ratio(non_empty) >= 0.5:
            continue
        if _row_unique_ratio(non_empty) < 0.6:
            continue
        next_rows = rows[index + 1:index + 4]
        has_numeric_following_row = any(
            isinstance(next_row, list) and _is_detail_data_row([str(cell or "").strip() for cell in next_row])
            for next_row in next_rows
        )
        if has_numeric_following_row:
            return index
    return None


def _is_continuation_table_compatible(
    *,
    anchor_headers: list[str],
    candidate_headers: list[str],
    rows: list[Any],
) -> bool:
    if not anchor_headers:
        return True
    anchor_width = len([item for item in anchor_headers if str(item or "").strip()])
    candidate_width = max(
        len([item for item in candidate_headers if str(item or "").strip()]),
        max((len(row) for row in rows if isinstance(row, list)), default=0),
    )
    if anchor_width and candidate_width and abs(candidate_width - anchor_width) > 2:
        return False

    candidate_values = [str(item or "").strip() for item in candidate_headers if str(item or "").strip()]
    if candidate_values and not _headers_are_generic(candidate_values) and not _is_detail_data_row(candidate_values):
        return _header_similarity(anchor_headers, candidate_values) >= 0.45

    return any(
        isinstance(row, list) and _is_detail_data_row([str(cell or "").strip() for cell in row])
        for row in rows[:5]
    )


def _header_similarity(left: list[Any], right: list[Any]) -> float:
    left_values = [_normalize_header_for_match(item) for item in left if _normalize_header_for_match(item)]
    right_values = [_normalize_header_for_match(item) for item in right if _normalize_header_for_match(item)]
    if not left_values or not right_values:
        return 0.0
    left_set = set(left_values)
    right_set = set(right_values)
    exact_hits = len(left_set & right_set)
    containment_hits = 0
    for left_item in left_set - right_set:
        if any(left_item in right_item or right_item in left_item for right_item in right_set):
            containment_hits += 1
    return (exact_hits + containment_hits * 0.5) / max(len(left_set), 1)


def _normalize_header_for_match(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).strip().lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def _is_detail_data_row(row: list[str]) -> bool:
    first = row[0].strip() if row else ""
    if not re.fullmatch(r"\d+(?:\.0+)?", first):
        return False
    non_empty_count = sum(1 for cell in row if cell.strip())
    return non_empty_count >= 3


def _is_non_detail_context_row(row: list[str]) -> bool:
    text = " ".join(cell for cell in row if cell).strip()
    return bool(text) and not _is_detail_data_row(row)


def _row_numeric_ratio(values: list[str]) -> float:
    if not values:
        return 0.0
    numeric_count = sum(1 for value in values if _looks_numeric_cell(value))
    return numeric_count / len(values)


def _row_unique_ratio(values: list[str]) -> float:
    normalized = [_normalize_header_for_match(value) for value in values if _normalize_header_for_match(value)]
    if not normalized:
        return 0.0
    return len(set(normalized)) / len(normalized)


def _looks_numeric_cell(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    compact = re.sub(r"[,\s￥¥$%]", "", text)
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", compact))


def _headers_are_generic(headers: list[Any]) -> bool:
    values = [str(item or "").strip() for item in headers if str(item or "").strip()]
    return bool(values) and all(re.fullmatch(r"列\d+", value) for value in values)


def _normalize_table_width(values: list[str], width: int, *, fill_prefix: str) -> list[str]:
    normalized = list(values[:width])
    while len(normalized) < width:
        normalized.append(f"{fill_prefix}{len(normalized) + 1}" if fill_prefix else "")
    return normalized


def _should_use_local_table_sample(payload: SkillDraftFromSampleRequest, tables: list[dict[str, Any]]) -> bool:
    if len(tables) > 1 or "整份" in payload.sourceScope:
        return True
    return _has_high_cost_table_risk(payload, tables)


def _has_user_controlled_sample_extraction(payload: SkillDraftFromSampleRequest) -> bool:
    instruction = str(payload.instruction or "")
    return "用户抽取要求：" in instruction or "用户输出要求：" in instruction


def _has_high_cost_table_risk(payload: SkillDraftFromSampleRequest, tables: list[dict[str, Any]]) -> bool:
    total_rows = sum(len(table.get("rows") or []) for table in tables)
    total_cells = sum(len(table.get("rows") or []) * max(len(table.get("headers") or []), 1) for table in tables)
    page_count = len({int(table.get("pageNo") or 0) for table in tables})
    return (
        total_rows >= 80
        or total_cells >= 500
        or page_count >= 3
        or len(payload.sourceText or "") >= 6000
    )


def _table_merge_notes(parsed: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    cells = parsed.get("cells") if isinstance(parsed, dict) else None
    if not isinstance(cells, list):
        return notes
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        rowspan = int(cell.get("rowspan") or 1)
        colspan = int(cell.get("colspan") or 1)
        if rowspan <= 1 and colspan <= 1:
            continue
        text = str(cell.get("text") or "").strip() or f"第 {cell.get('row')} 行第 {cell.get('col')} 列"
        parts = []
        if rowspan > 1:
            parts.append(f"跨 {rowspan} 行")
        if colspan > 1:
            parts.append(f"跨 {colspan} 列")
        notes.append(f"{text}：{'，'.join(parts)}")
        if len(notes) >= 20:
            break
    return notes


def _page_label(page_no: int) -> str:
    return f"第 {page_no} 页" if page_no else ""


def _compact_operation_sample_overview(targets: list[OperationTargetRef]) -> dict[str, Any]:
    return {
        "targetCount": len(targets),
        "targets": [
            {
                "id": item.id,
                "type": item.type,
                "label": item.label,
                "valueText": item.valueText,
                "headers": item.headers,
                "rowCount": item.rowCount,
                "data": item.data,
            }
            for item in targets[:20]
        ],
    }


def _sample_excerpt(value: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _build_skill_sample(
    repository: WorkbenchRepository,
    payload: SkillDraftFromSampleRequest,
) -> tuple[str, dict[str, Any]]:
    pages, load_page_targets, context_meta = _sample_pages_and_target_loader(repository, payload)
    target_ids = {str(item).strip() for item in payload.targetIds if str(item).strip()}
    selected_pages = _resolve_sample_page_numbers(payload, [page.pageNo for page in pages])
    selected_block_ids = _sample_content_ref_block_ids(payload.contentRefs)
    block_binding = _resolve_sample_runtime_block_binding(
        pages=pages,
        selected_pages=selected_pages,
        selected_block_ids=selected_block_ids,
        content_refs=payload.contentRefs,
    )
    active_block_ids = set(block_binding.get("activeBlockIds") or [])
    use_page_scope = bool(block_binding.get("usePageScope"))
    selected_source_only = _sample_uses_selected_source_only(payload)
    wants_table = _is_table_sample_request(payload)
    lines: list[str] = []
    source_text_limit = 1200 if payload.kind == "extraction" and "整份" in payload.sourceScope else 12000
    source_text = _sample_excerpt(payload.sourceText, limit=source_text_limit)
    if payload.dataTypeName.strip() or payload.sourceLabel.strip() or source_text:
        lines.append("## 用户选定样例")
        if payload.dataTypeName.strip():
            lines.append(f"- 数据类型：{payload.dataTypeName.strip()}")
        if payload.sourceScope.strip():
            lines.append(f"- 样例范围：{payload.sourceScope.strip()}")
        if payload.sourceLabel.strip():
            lines.append(f"- 样例名称：{payload.sourceLabel.strip()}")
        if payload.treeNodeId:
            lines.append(f"- 文档树节点ID：{payload.treeNodeId}")
        if payload.treePath:
            lines.append(f"- 文档树路径：{' / '.join(str(item).strip() for item in payload.treePath if str(item).strip())}")
        if payload.pageRange:
            lines.append(f"- 文档树证据页码：{_compact_sample_value(payload.pageRange, limit=300)}")
        if payload.treeNodeId or payload.contentRefs:
            lines.append("- 约束：样例页码仅用于证据回看，不得作为后续定位或触发条件。")
        if source_text:
            lines.append(f"- 样例内容：{source_text}")
    matched_targets = 0
    sampled_pages = 0

    if selected_source_only:
        sampled_pages = len(selected_pages)
    else:
        for page in pages:
            if page.pageNo not in selected_pages:
                continue
            sampled_pages += 1
            page_targets: list[OperationTargetRef] = []
            should_use_operation_targets = bool(target_ids) or payload.kind == "operation"
            if should_use_operation_targets:
                page_targets = list(load_page_targets(page.pageNo))
                if target_ids:
                    page_targets = [item for item in page_targets if item.id in target_ids]
                elif wants_table:
                    table_targets = [
                        item for item in page_targets
                        if item.type == "table" or item.headers or item.rowCount or item.columnCount
                    ]
                    page_targets = table_targets or page_targets
            if should_use_operation_targets and page_targets:
                lines.append(f"\n## 第 {page.pageNo} 页可处理对象")
                for target in page_targets[:24]:
                    matched_targets += 1
                    lines.extend(
                        [
                            f"- 对象：{target.label}",
                            f"  类型：{target.type}",
                            f"  字段标识：{target.fieldKey or ''}",
                            f"  分组：{target.groupLabel or ''}",
                            f"  表头：{' / '.join(target.headers[:12]) if target.headers else ''}",
                            f"  内容：{_compact_sample_value(target.data if target.data is not None else target.valueText, limit=1200)}",
                            f"  证据片段：{_sample_excerpt(target.excerpt or '', limit=500)}",
                        ]
                    )
                continue

            lines.append(f"\n## 第 {page.pageNo} 页识别片段")
            page_blocks = [
                block for block in page.blocks
                if use_page_scope
                or (active_block_ids and str(getattr(block, "id", "") or "") in active_block_ids)
                or (not selected_block_ids and not active_block_ids)
            ]
            for block in page_blocks[:18]:
                lines.extend(_skill_sample_block_lines(block, wants_table=wants_table))
            if not selected_block_ids:
                for item in page.rawItems[:8]:
                    lines.append(f"- raw: {_compact_sample_value(item, limit=600)}")

    sample_text = "\n".join(line for line in lines if line.strip()).strip()
    if not sample_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前样例没有可用于制作 Skill 的样本内容。")
    sample_limit = _skill_sample_text_limit()
    if len(sample_text) > sample_limit:
        sample_text = sample_text[:sample_limit] + "\n...（样本已截断）"
    return sample_text, {
        "taskId": _payload_task_id(payload),
        "applicationId": _payload_application_id(payload) or None,
        "sampleId": _sample_identity(payload),
        "sampleSource": context_meta.get("source"),
        "pageNo": payload.pageNo,
        "sampledPages": sampled_pages,
        "targetIds": list(target_ids),
        "matchedTargetCount": matched_targets,
        "sampleChars": len(sample_text),
        "dataTypeName": payload.dataTypeName,
        "sourceScope": payload.sourceScope,
        "sourceLabel": payload.sourceLabel,
        "treeNodeId": payload.treeNodeId,
        "treePath": payload.treePath,
        "pageRange": payload.pageRange,
        "contentRefs": _compact_sample_content_refs(payload.contentRefs, limit=20),
        "runtimeBlockBinding": block_binding,
        "selectedSourceOnly": selected_source_only,
        "runtimeContext": context_meta,
    }


def _build_skill_sample_from_task(
    repository: WorkbenchRepository,
    payload: SkillDraftFromSampleRequest,
) -> tuple[str, dict[str, Any]]:
    return _build_skill_sample(repository, payload)


def _skill_sample_text_limit() -> int:
    try:
        return max(12000, int(os.getenv("IDP_SKILL_SAMPLE_TEXT_LIMIT", "30000")))
    except ValueError:
        return 30000


def _skill_sample_block_lines(block: Any, *, wants_table: bool) -> list[str]:
    block_type = str(getattr(block, "type", "") or "text").strip()
    title = str(getattr(block, "title", "") or "").strip()
    content = str(getattr(block, "content", "") or "")
    html = str(getattr(block, "htmlContent", "") or "")
    if wants_table and "table" in block_type.lower():
        table_text = _compact_table_for_skill_sample(html or content)
        if table_text:
            return [
                f"## 表格：{title or '表格区域'}",
                f"blockId：{getattr(block, 'id', '')}",
                table_text,
            ]
    text_limit = 1000 if wants_table else 420
    text = _sample_excerpt(content or title, limit=text_limit)
    if not text:
        return []
    return [f"- {block_type}: {text}"]


def _compact_table_for_skill_sample(table_html: str) -> str:
    raw = str(table_html or "").strip()
    if not raw:
        return ""
    try:
        parsed = parse_table_html(raw)
    except ValueError:
        parsed = {}
    canonical = parsed.get("canonicalTable") if isinstance(parsed, dict) else None
    if not isinstance(canonical, dict):
        return f"原始表格：{_sample_excerpt(re.sub(r'<[^>]+>', ' ', raw), limit=4000)}"

    headers = [str(item or "").strip() for item in (canonical.get("headers") or [])]
    rows = [
        [str(cell or "").strip() for cell in row]
        for row in (canonical.get("rows") or [])
        if isinstance(row, list) and any(str(cell or "").strip() for cell in row)
    ]
    lines = [f"表格规模：{len(rows)} 行 · {len(headers)} 列"]
    if headers and not all(re.fullmatch(r"列\d+", header) for header in headers):
        lines.append(f"表头：{' | '.join(headers)}")
    lines.append("表格行：")
    lines.extend(f"| {' | '.join(_escape_markdown_cell(cell) for cell in row)} |" for row in rows)
    return "\n".join(lines)


def _escape_markdown_cell(value: str) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _resolve_sample_page_numbers(payload: SkillDraftFromSampleRequest, available_pages: list[int]) -> list[int]:
    if payload.pageNo:
        return [payload.pageNo]
    page_range = payload.pageRange if isinstance(payload.pageRange, dict) else {}
    explicit_pages = [int(item) for item in (page_range.get("pages") or []) if _coerce_int(item)]
    available = set(available_pages)
    if explicit_pages:
        selected = [page_no for page_no in explicit_pages if page_no in available]
        if selected:
            return sorted(set(selected))
    ref_pages: list[int] = []
    for ref in payload.contentRefs or []:
        if not isinstance(ref, dict):
            continue
        for page_value in (ref.get("evidencePages") or ref.get("pages") or []):
            page_no = _coerce_int(page_value)
            if page_no:
                ref_pages.append(page_no)
        page_no = _coerce_int(ref.get("pageNo"))
        if page_no:
            ref_pages.append(page_no)
    if ref_pages:
        selected = [page_no for page_no in ref_pages if page_no in available]
        if selected:
            return sorted(set(selected))
    start_page = _coerce_int(page_range.get("start"))
    end_page = _coerce_int(page_range.get("end"))
    if start_page and end_page:
        selected = [page_no for page_no in available_pages if start_page <= page_no <= end_page]
        if selected:
            return selected
    scope_pages = [
        int(match.group(1))
        for match in re.finditer(r"第\s*(\d+)\s*页", " ".join([payload.sourceScope, payload.sourceText, payload.sourceLabel]))
    ]
    selected = [page_no for page_no in scope_pages if page_no in set(available_pages)]
    if selected:
        return sorted(set(selected))
    return available_pages


def _sample_content_ref_block_ids(content_refs: list[dict[str, Any]]) -> set[str]:
    block_ids: set[str] = set()
    for ref in content_refs or []:
        if not isinstance(ref, dict):
            continue
        for block_id in ref.get("blockIds") or []:
            text = str(block_id or "").strip()
            if text:
                block_ids.add(text)
    return block_ids


def _resolve_sample_runtime_block_binding(
    *,
    pages: list[Any],
    selected_pages: list[int],
    selected_block_ids: set[str],
    content_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map document-tree references to executable OCR block ids.

    Document tree modules may store parser-side block ids, while runtime pages
    expose canonical OCR block ids. Exact runtime ids still win. When tree refs
    cannot be executed directly, bind by the already confirmed evidence pages
    and let the table parser inspect real table blocks on those pages.
    """

    selected_page_set = {int(page_no) for page_no in selected_pages if _coerce_int(page_no)}
    runtime_table_block_ids_by_page: dict[str, list[str]] = {}
    runtime_table_block_ids: set[str] = set()
    for page in pages:
        page_no = int(getattr(page, "pageNo", 0) or 0)
        if page_no not in selected_page_set:
            continue
        for block in getattr(page, "blocks", []) or []:
            if not _is_runtime_table_block(block):
                continue
            block_id = str(getattr(block, "id", "") or "").strip()
            if not block_id:
                continue
            runtime_table_block_ids.add(block_id)
            runtime_table_block_ids_by_page.setdefault(str(page_no), []).append(block_id)

    requested = {str(item or "").strip() for item in selected_block_ids if str(item or "").strip()}
    matched = requested & runtime_table_block_ids
    document_tree_ref = _content_refs_include_document_tree_modules(content_refs)
    if not requested:
        mode = "page_scope"
        active_block_ids: set[str] = set()
        use_page_scope = True
    elif matched:
        mode = "exact_runtime_block_ids"
        active_block_ids = matched
        use_page_scope = False
    elif document_tree_ref:
        mode = "document_tree_page_rebind"
        active_block_ids = set()
        use_page_scope = True
    else:
        mode = "unmatched_exact_block_ids"
        active_block_ids = requested
        use_page_scope = False

    return {
        "mode": mode,
        "documentTreeRef": document_tree_ref,
        "usePageScope": use_page_scope,
        "requestedBlockIds": sorted(requested),
        "activeBlockIds": sorted(active_block_ids),
        "matchedRuntimeBlockIds": sorted(matched),
        "unmatchedRequestedBlockIds": sorted(requested - runtime_table_block_ids),
        "runtimeTableBlockIdsByPage": runtime_table_block_ids_by_page,
    }


def _content_refs_include_document_tree_modules(content_refs: list[dict[str, Any]]) -> bool:
    for ref in content_refs or []:
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get("kind") or "").strip()
        if kind == "document_tree_module":
            return True
        if ref.get("nodeId") and (ref.get("evidencePages") or ref.get("pages")):
            return True
    return False


def _is_runtime_table_block(block: Any) -> bool:
    block_type = str(getattr(block, "type", "") or "").lower()
    raw_html = str(getattr(block, "htmlContent", "") or getattr(block, "content", "") or "")
    return "table" in block_type or "<table" in raw_html.lower()


def _is_table_sample_request(payload: SkillDraftFromSampleRequest) -> bool:
    text = "\n".join(
        [
            payload.instruction,
            payload.expectedOutput,
            payload.dataTypeName,
            payload.sourceLabel,
            payload.sourceText,
        ]
    )
    return any(keyword in text for keyword in ("表格", "表头", "行数据", "行列", "单元格", "合并单元格", "headers", "rows", "<table"))


def _sample_output_contract(payload: SkillDraftFromSampleRequest) -> tuple[str, str]:
    explicit_text = _sample_explicit_output_contract_text(payload).lower()
    if _has_record_collection_contract(explicit_text):
        return "record_collection", "nested_records"
    if _has_table_contract(explicit_text):
        return "data_table", "data_table"
    if _has_field_list_contract(explicit_text):
        return "field_list", "field_list"

    evidence_text = str(payload.sourceText or "").lower()
    if _has_table_contract(evidence_text):
        return "data_table", "data_table"
    if _has_record_collection_contract(evidence_text):
        return "record_collection", "nested_records"
    if _has_field_list_contract(evidence_text):
        return "field_list", "field_list"
    return "custom", "auto"


def _sample_uses_selected_source_only(payload: SkillDraftFromSampleRequest) -> bool:
    if payload.kind != "extraction":
        return False
    if not str(payload.sourceText or "").strip():
        return False
    return bool(payload.contentRefs or payload.treeNodeId)


def _sample_explicit_output_contract_text(payload: SkillDraftFromSampleRequest) -> str:
    parts: list[str] = []
    expected_output = _normalize_sample_expected_output(payload.expectedOutput)
    if expected_output:
        parts.append(expected_output)
    parts.extend(
        _extract_instruction_labeled_sections(
            payload.instruction,
            labels=("用户输出要求", "用户抽取要求"),
        )
    )
    return "\n".join(part for part in parts if str(part).strip())


def _extract_instruction_labeled_sections(value: str, *, labels: tuple[str, ...]) -> list[str]:
    sections: list[str] = []
    active = False
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            active = False
            continue
        matched = False
        for label in labels:
            for sep in ("：", ":"):
                prefix = f"{label}{sep}"
                if line.startswith(prefix):
                    tail = line[len(prefix):].strip()
                    if tail:
                        sections.append(tail)
                    active = True
                    matched = True
                    break
            if matched:
                break
        if matched:
            continue
        if _looks_like_sample_instruction_heading(line):
            active = False
            continue
        if active:
            sections.append(line)
    return sections


def _looks_like_sample_instruction_heading(value: str) -> bool:
    normalized = str(value or "").strip().rstrip("：:")
    return normalized in {
        "数据类型",
        "样例来源",
        "样例范围",
        "处理目标",
        "系统默认输出建议",
        "定位约束",
        "生成要求",
    }


def _has_table_contract(text: str) -> bool:
    return any(keyword in text for keyword in ("表格", "表头", "行数据", "行列", "单元格", "合并单元格", "headers", "rows", "<table"))


def _has_record_collection_contract(text: str) -> bool:
    return any(keyword in text for keyword in ("记录集合", "记录列表", "明细记录", "多条记录", "records", "record_collection"))


def _has_field_list_contract(text: str) -> bool:
    return any(keyword in text for keyword in ("字段", "字段名", "字段值", "基础信息", "key-value", "field"))


def _confirmed_sample_output_contract(value: Any) -> tuple[str, str]:
    output_type = _confirmed_sample_output_type(value)
    renderer = {
        "field_list": "field_list",
        "data_table": "data_table",
        "record_collection": "nested_records",
        "custom": "auto",
    }.get(output_type, "")
    return output_type, renderer


def _confirmed_sample_output_type(value: Any) -> str:
    if isinstance(value, list):
        return "record_collection"
    if not isinstance(value, dict):
        return ""

    explicit_type = str(value.get("type") or "").strip()
    if explicit_type in {"field_list", "data_table", "record_collection", "custom"}:
        return explicit_type

    outputs = value.get("outputs")
    if isinstance(outputs, list) and outputs:
        for output in outputs:
            output_type = _confirmed_sample_output_type(output)
            if output_type:
                return output_type

    data = value.get("data")
    if isinstance(data, dict):
        data_type = _confirmed_sample_output_type(data)
        if data_type:
            return data_type

    if isinstance(value.get("fields"), list):
        return "field_list"
    if isinstance(value.get("field_list"), dict) and isinstance(value["field_list"].get("fields"), list):
        return "field_list"
    if isinstance(value.get("headers"), list) and isinstance(value.get("rows"), list):
        return "data_table"
    if isinstance(value.get("data_table"), dict):
        table = value["data_table"]
        if isinstance(table.get("headers"), list) and isinstance(table.get("rows"), list):
            return "data_table"
    if isinstance(value.get("records"), list):
        return "record_collection"
    if isinstance(value.get("record_collection"), dict) and isinstance(value["record_collection"].get("records"), list):
        return "record_collection"
    return "custom" if value else ""


def _confirmed_operation_result_kind(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    explicit = str(value.get("resultKind") or value.get("result_kind") or "").strip()
    if explicit in {"decision", "object", "table", "text"}:
        return explicit
    output_payload = value.get("outputPayload") if "outputPayload" in value else value.get("output_payload")
    if isinstance(output_payload, dict):
        if isinstance(output_payload.get("headers"), list) and isinstance(output_payload.get("rows"), list):
            return "table"
        if "text" in output_payload and len(output_payload) <= 2:
            return "text"
        if "decision" in output_payload:
            return "decision"
        return "object"
    if isinstance(output_payload, str):
        return "text"
    if isinstance(value.get("headers"), list) and isinstance(value.get("rows"), list):
        return "table"
    if "decision" in value:
        return "decision"
    if "text" in value and len(value) <= 2:
        return "text"
    return "object" if value else ""


def _normalize_sample_process_result(raw_payload: dict[str, Any]) -> dict[str, Any]:
    result_kind = str(raw_payload.get("resultKind") or raw_payload.get("result_kind") or "").strip()
    if result_kind not in {"decision", "object", "table", "text"}:
        result_kind = _confirmed_operation_result_kind(raw_payload) or "object"

    if "outputPayload" in raw_payload:
        output_payload = raw_payload.get("outputPayload")
    elif "output_payload" in raw_payload:
        output_payload = raw_payload.get("output_payload")
    else:
        output_payload = {
            key: value
            for key, value in raw_payload.items()
            if key not in {"summary", "resultKind", "result_kind", "validationErrors", "validation_errors", "errors"}
        }

    if output_payload is None:
        output_payload = {}
    if result_kind == "table" and isinstance(output_payload, dict):
        output_payload = {
            "headers": output_payload.get("headers") if isinstance(output_payload.get("headers"), list) else [],
            "rows": output_payload.get("rows") if isinstance(output_payload.get("rows"), list) else [],
            **{
                key: value
                for key, value in output_payload.items()
                if key not in {"headers", "rows"}
            },
        }
    if result_kind == "text" and isinstance(output_payload, str):
        output_payload = {"text": output_payload}

    raw_errors = raw_payload.get("validationErrors")
    if not isinstance(raw_errors, list):
        raw_errors = raw_payload.get("validation_errors")
    if not isinstance(raw_errors, list):
        raw_errors = raw_payload.get("errors")
    validation_errors = [str(item).strip() for item in (raw_errors if isinstance(raw_errors, list) else []) if str(item).strip()]

    summary = str(raw_payload.get("summary") or "").strip()
    if not summary:
        summary = "样例处理完成。"

    return {
        "summary": summary,
        "resultKind": result_kind,
        "outputPayload": output_payload,
        "validationErrors": validation_errors,
    }


def _editable_output_from_process_result(process_result: dict[str, Any]) -> str:
    return json.dumps(
        {
            "summary": process_result.get("summary") or "",
            "result_kind": process_result.get("resultKind") or "object",
            "output_payload": process_result.get("outputPayload") if process_result.get("outputPayload") is not None else {},
            "validationErrors": process_result.get("validationErrors") if isinstance(process_result.get("validationErrors"), list) else [],
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def _normalize_sample_extraction_result(
    raw_payload: dict[str, Any],
    payload: SkillDraftFromSampleRequest,
    assist: dict[str, Any],
) -> dict[str, Any]:
    output_type, renderer = _sample_output_contract(payload)
    skill_meta = {
        "name": (payload.dataTypeName.strip() or "样例抽取结果"),
        "renderer": renderer,
        "outputSchema": {"type": output_type},
    }
    run_meta = {
        "provider": assist.get("provider") or "dashscope",
        "model": assist.get("model") or "",
        "durationMs": assist.get("durationMs") or 0,
        "inputChars": assist.get("inputChars") or 0,
        "outputChars": assist.get("outputChars") or 0,
        "sampleOnly": True,
    }
    try:
        return _normalize_extraction_skill_output(
            raw_payload=raw_payload,
            skill_meta=skill_meta,
            run_meta=run_meta,
        )
    except RuntimeError:
        fallback_meta = {
            **skill_meta,
            "renderer": "auto",
            "outputSchema": {"type": "custom"},
        }
        return _normalize_extraction_skill_output(
            raw_payload={
                "summary": raw_payload.get("summary") or f"已完成{payload.dataTypeName or '样例'}试抽取。",
                "outputs": [
                    {
                        "id": "sample-output-1",
                        "title": payload.dataTypeName or "样例抽取结果",
                        "type": "custom",
                        "renderer": "auto",
                        "data": raw_payload,
                        "schema": {},
                        "sourceRefs": [],
                    }
                ],
                "errors": ["样例试抽取结果已保留为自定义 JSON，请确认后再生成 Skill。"],
            },
            skill_meta=fallback_meta,
            run_meta=run_meta,
        )


def _sanitize_extraction_result_for_response(result: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(result or {})
    outputs: list[Any] = []
    for output in sanitized.get("outputs") or []:
        if not isinstance(output, dict):
            outputs.append(output)
            continue
        next_output = dict(output)
        next_output["sourceRefs"] = _coerce_evidence_refs(next_output.get("sourceRefs"))
        outputs.append(next_output)
    sanitized["outputs"] = outputs
    for key in ("fields", "tables", "structuredObjects"):
        values: list[Any] = []
        for item in sanitized.get(key) or []:
            if not isinstance(item, dict):
                values.append(item)
                continue
            next_item = dict(item)
            next_item["evidenceRefs"] = _coerce_evidence_refs(next_item.get("evidenceRefs"))
            values.append(next_item)
        sanitized[key] = values
    return sanitized


def _coerce_evidence_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        page_no = _coerce_int(item.get("pageNo") or item.get("source_page") or item.get("page"))
        if page_no is None:
            text = " ".join(str(item.get(key) or "") for key in ("source_page", "page", "text", "excerpt"))
            match = re.search(r"第\s*(\d+)\s*页", text)
            page_no = int(match.group(1)) if match else None
        if page_no is None:
            continue
        refs.append(
            {
                "pageNo": page_no,
                "blockId": str(item.get("blockId") or item.get("block_id") or ""),
                "blockPosition": str(item.get("blockPosition") or item.get("block_position") or ""),
                "excerpt": str(item.get("excerpt") or item.get("text") or item.get("original_text") or ""),
            }
        )
    return refs


def _editable_output_from_extraction_result(extraction_result: dict[str, Any]) -> str:
    outputs = extraction_result.get("outputs")
    payload: Any
    if isinstance(outputs, list) and len(outputs) == 1 and isinstance(outputs[0], dict):
        payload = outputs[0].get("data")
    else:
        payload = {
            "summary": extraction_result.get("summary") or "",
            "outputs": outputs if isinstance(outputs, list) else [],
        }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _build_sample_output_contract_summary(
    payload: SkillDraftFromSampleRequest,
    *,
    confirmed_output: Any = None,
    extraction_result: dict[str, Any] | None = None,
    process_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if payload.kind == "operation":
        confirmed_kind = _confirmed_operation_result_kind(confirmed_output) if confirmed_output is not None else ""
        result_kind = str((process_result or {}).get("resultKind") or "").strip()
        return {
            "kind": "operation",
            "resultKind": confirmed_kind or result_kind or "object",
            "source": "confirmed_output" if confirmed_kind else ("sample_result" if result_kind else "default"),
            "dataTypeName": payload.dataTypeName,
            "sourceScope": payload.sourceScope,
            "rules": [
                "业务处理输出必须包含 summary、result_kind、output_payload。",
                "确认样例输出结构优先于生成 Skill 正文中的旧描述。",
            ],
        }

    confirmed_type = ""
    confirmed_renderer = ""
    if confirmed_output is not None:
        confirmed_type, confirmed_renderer = _confirmed_sample_output_contract(confirmed_output)
    result_type = ""
    result_renderer = ""
    if extraction_result:
        result_type, result_renderer = _contract_from_extraction_result(extraction_result)
    inferred_type, inferred_renderer = _sample_output_contract(payload)
    output_type = confirmed_type or result_type or inferred_type
    renderer = confirmed_renderer or result_renderer or inferred_renderer
    return {
        "kind": "extraction",
        "outputType": output_type,
        "renderer": renderer,
        "source": "confirmed_output" if confirmed_type else ("sample_result" if result_type else "runtime_contract"),
        "dataTypeName": payload.dataTypeName,
        "sourceScope": payload.sourceScope,
        "runtimeContractPriority": "runtimeContract 高于 Skill 正文中的旧字段列表；Skill 正文是能力说明，不是最终运行契约。",
        "rules": [
            "只从识别事实和已选择证据中抽取。",
            "缺失字段保留空字符串，不编造。",
            "页码只能作为来源证据，不作为固定触发条件。",
        ],
    }


def _contract_from_extraction_result(extraction_result: dict[str, Any]) -> tuple[str, str]:
    outputs = extraction_result.get("outputs")
    if isinstance(outputs, list) and outputs:
        first = next((item for item in outputs if isinstance(item, dict)), None)
        if first:
            output_type = str(first.get("type") or "").strip()
            renderer = str(first.get("renderer") or "").strip()
            if output_type:
                return output_type, renderer or {
                    "field_list": "field_list",
                    "data_table": "data_table",
                    "record_collection": "nested_records",
                }.get(output_type, "auto")
    return _confirmed_sample_output_contract(extraction_result)


def _build_sample_evidence_diagnostics(
    payload: SkillDraftFromSampleRequest,
    sample_summary: dict[str, Any],
    *,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding = sample_summary.get("runtimeBlockBinding") if isinstance(sample_summary.get("runtimeBlockBinding"), dict) else {}
    content_refs = sample_summary.get("contentRefs") if isinstance(sample_summary.get("contentRefs"), list) else []
    pages = _diagnostic_pages(sample_summary)
    source_types = _unique_texts(
        [
            ref.get("kind") or ref.get("type") or ref.get("sourceType")
            for ref in content_refs
            if isinstance(ref, dict)
        ],
        limit=12,
    )
    diagnostics = {
        "version": "skill_development_evidence_v1",
        "status": "ready" if sample_summary.get("sampleChars") else "empty",
        "sampleId": sample_summary.get("sampleId") or _sample_identity(payload),
        "sampleSource": sample_summary.get("sampleSource"),
        "selectedPages": pages,
        "contentRefCount": len(content_refs),
        "contentRefTypes": source_types,
        "sampleChars": sample_summary.get("sampleChars") or 0,
        "sourceScope": sample_summary.get("sourceScope") or payload.sourceScope,
        "sourceLabel": sample_summary.get("sourceLabel") or payload.sourceLabel,
        "treeNodeId": sample_summary.get("treeNodeId") or payload.treeNodeId,
        "runtimeBlockBinding": {
            "mode": binding.get("mode"),
            "usePageScope": bool(binding.get("usePageScope")),
            "documentTreeRef": bool(binding.get("documentTreeRef")),
            "requestedBlockCount": len(binding.get("requestedBlockIds") or []),
            "activeBlockCount": len(binding.get("activeBlockIds") or []),
            "matchedRuntimeBlockCount": len(binding.get("matchedRuntimeBlockIds") or []),
        },
        "warnings": [],
    }
    if trace and isinstance(trace.get("sampleBuild"), dict):
        sample_build = trace["sampleBuild"]
        diagnostics["truncated"] = bool(sample_build.get("truncated"))
        diagnostics["sampleTextLimit"] = sample_build.get("sampleTextLimit")
    if binding.get("mode") == "document_tree_page_rebind":
        if sample_summary.get("selectedSourceOnly"):
            diagnostics["warnings"].append("已使用文档树定位模块文本作为样例证据，未扩展同页其他 OCR 块。")
        else:
            diagnostics["warnings"].append("文档树 block 引用已按证据页码重新绑定运行时表格块。")
    if not content_refs and not payload.targetIds:
        diagnostics["warnings"].append("当前样例未携带文档树 contentRefs，证据范围来自页面或 sourceText。")
    return diagnostics


def _diagnostic_pages(sample_summary: dict[str, Any]) -> list[int]:
    page_range = sample_summary.get("pageRange") if isinstance(sample_summary.get("pageRange"), dict) else {}
    pages = [_coerce_int(item) for item in (page_range.get("pages") or [])]
    values = [int(page) for page in pages if page]
    if not values:
        page_no = _coerce_int(sample_summary.get("pageNo"))
        if page_no:
            values.append(page_no)
    if not values:
        for ref in sample_summary.get("contentRefs") or []:
            if not isinstance(ref, dict):
                continue
            for page in ref.get("evidencePages") or ref.get("pages") or []:
                page_no = _coerce_int(page)
                if page_no:
                    values.append(page_no)
    return sorted(set(values))


def _build_sample_validation_report(
    *,
    kind: str,
    output_contract: dict[str, Any],
    confirmed_output: Any = None,
    extraction_result: dict[str, Any] | None = None,
    process_result: dict[str, Any] | None = None,
    skill_text: str = "",
    errors: list[str] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    warnings: list[str] = []
    raw_errors = [str(item).strip() for item in (errors or []) if str(item).strip()]
    checks.append(
        {
            "key": "runtime_errors",
            "label": "样例运行错误",
            "status": "failed" if raw_errors else "passed",
            "detail": "；".join(raw_errors[:5]) if raw_errors else "无运行错误。",
        }
    )
    if raw_errors:
        issues.extend(raw_errors[:5])

    if kind == "operation":
        _append_operation_validation_checks(
            checks=checks,
            issues=issues,
            warnings=warnings,
            output_contract=output_contract,
            confirmed_output=confirmed_output,
            process_result=process_result,
            skill_text=skill_text,
        )
    else:
        _append_extraction_validation_checks(
            checks=checks,
            issues=issues,
            warnings=warnings,
            output_contract=output_contract,
            confirmed_output=confirmed_output,
            extraction_result=extraction_result,
            skill_text=skill_text,
        )

    failed = any(check.get("status") == "failed" for check in checks)
    warning = any(check.get("status") == "warning" for check in checks) or bool(warnings)
    return {
        "version": "skill_development_validation_v1",
        "engine": "local_static_contract",
        "status": "failed" if failed else ("warning" if warning else "passed"),
        "checks": checks,
        "issues": _unique_texts(issues, limit=12),
        "warnings": _unique_texts(warnings, limit=12),
        "metrics": {
            "confirmed": _sample_output_metrics(confirmed_output),
            "actual": _sample_output_metrics(extraction_result or process_result or {}),
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _append_extraction_validation_checks(
    *,
    checks: list[dict[str, Any]],
    issues: list[str],
    warnings: list[str],
    output_contract: dict[str, Any],
    confirmed_output: Any,
    extraction_result: dict[str, Any] | None,
    skill_text: str,
) -> None:
    expected_type = str(output_contract.get("outputType") or "").strip()
    actual_type, _ = _contract_from_extraction_result(extraction_result or {}) if extraction_result else ("", "")
    if actual_type:
        status_value = "passed" if not expected_type or actual_type == expected_type else "failed"
        detail = f"期望 {expected_type or '未指定'}，实际 {actual_type}。"
        checks.append({"key": "output_contract", "label": "样例输出协议", "status": status_value, "detail": detail})
        if status_value == "failed":
            issues.append(detail)
    else:
        checks.append({"key": "output_contract", "label": "样例输出协议", "status": "warning", "detail": "未识别到明确输出协议。"})
        warnings.append("未识别到明确输出协议。")

    if confirmed_output is not None and extraction_result is not None:
        _append_metric_comparison_checks(checks, issues, warnings, confirmed_output, extraction_result)
    elif confirmed_output is None:
        checks.append({"key": "gold_output", "label": "确认样例输出", "status": "warning", "detail": "尚未提供确认样例输出，无法做 gold 对比。"})
        warnings.append("尚未提供确认样例输出，无法做 gold 对比。")

    if skill_text.strip():
        skill_contract = _skill_text_contract(skill_text)
        skill_output_type = str(skill_contract.get("outputType") or "").strip()
        if expected_type and skill_output_type:
            status_value = "passed" if skill_output_type == expected_type else "failed"
            detail = f"Skill frontmatter output.type={skill_output_type}，运行契约={expected_type}。"
            checks.append({"key": "skill_frontmatter_contract", "label": "Skill 输出协议", "status": status_value, "detail": detail})
            if status_value == "failed":
                issues.append(detail)
        elif expected_type:
            checks.append({"key": "skill_frontmatter_contract", "label": "Skill 输出协议", "status": "warning", "detail": "Skill frontmatter 未声明 output.type。"})
            warnings.append("Skill frontmatter 未声明 output.type。")


def _append_operation_validation_checks(
    *,
    checks: list[dict[str, Any]],
    issues: list[str],
    warnings: list[str],
    output_contract: dict[str, Any],
    confirmed_output: Any,
    process_result: dict[str, Any] | None,
    skill_text: str,
) -> None:
    expected_kind = str(output_contract.get("resultKind") or "").strip()
    actual_kind = str((process_result or {}).get("resultKind") or "").strip()
    if actual_kind:
        status_value = "passed" if not expected_kind or actual_kind == expected_kind else "failed"
        detail = f"期望 {expected_kind or '未指定'}，实际 {actual_kind}。"
        checks.append({"key": "operation_result_kind", "label": "处理输出协议", "status": status_value, "detail": detail})
        if status_value == "failed":
            issues.append(detail)
    if confirmed_output is None:
        checks.append({"key": "gold_output", "label": "确认样例输出", "status": "warning", "detail": "尚未提供确认样例输出，无法做 gold 对比。"})
        warnings.append("尚未提供确认样例输出，无法做 gold 对比。")
    if skill_text.strip():
        skill_contract = _skill_text_contract(skill_text)
        skill_result_kind = str(skill_contract.get("resultKind") or "").strip()
        if expected_kind and skill_result_kind:
            status_value = "passed" if skill_result_kind == expected_kind else "failed"
            detail = f"Skill frontmatter resultKind={skill_result_kind}，运行契约={expected_kind}。"
            checks.append({"key": "skill_frontmatter_result_kind", "label": "Skill 处理协议", "status": status_value, "detail": detail})
            if status_value == "failed":
                issues.append(detail)


def _append_metric_comparison_checks(
    checks: list[dict[str, Any]],
    issues: list[str],
    warnings: list[str],
    expected: Any,
    actual: Any,
) -> None:
    expected_metrics = _sample_output_metrics(expected)
    actual_metrics = _sample_output_metrics(actual)
    for key, label in (
        ("fieldCount", "字段数量"),
        ("recordCount", "记录数量"),
        ("rowCount", "表格行数"),
    ):
        expected_count = int(expected_metrics.get(key) or 0)
        actual_count = int(actual_metrics.get(key) or 0)
        if expected_count <= 0:
            continue
        if actual_count >= expected_count:
            checks.append({"key": key, "label": label, "status": "passed", "detail": f"{actual_count}/{expected_count}"})
        else:
            detail = f"{label}少于确认样例：{actual_count}/{expected_count}。"
            checks.append({"key": key, "label": label, "status": "failed", "detail": detail})
            issues.append(detail)
    expected_labels = set(expected_metrics.get("fieldLabels") or [])
    actual_labels = set(actual_metrics.get("fieldLabels") or [])
    if expected_labels:
        missing = sorted(expected_labels - actual_labels)
        if missing:
            detail = "字段缺失：" + "、".join(missing[:12])
            checks.append({"key": "field_labels", "label": "字段命名覆盖", "status": "failed", "detail": detail})
            issues.append(detail)
        else:
            checks.append({"key": "field_labels", "label": "字段命名覆盖", "status": "passed", "detail": "确认样例字段均已覆盖。"})
    if not expected_labels and not any(expected_metrics.get(key) for key in ("recordCount", "rowCount")):
        warnings.append("确认样例缺少可量化字段、记录或表格行，验证仅能检查协议。")


def _sample_output_metrics(value: Any) -> dict[str, Any]:
    metrics = {
        "fieldCount": 0,
        "recordCount": 0,
        "rowCount": 0,
        "columnCount": 0,
        "fieldLabels": [],
    }
    _accumulate_sample_output_metrics(value, metrics)
    metrics["fieldLabels"] = _unique_texts(metrics["fieldLabels"], limit=100)
    return metrics


def _accumulate_sample_output_metrics(value: Any, metrics: dict[str, Any]) -> None:
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            metrics["recordCount"] = int(metrics.get("recordCount") or 0) + len(value)
        for item in value:
            _accumulate_sample_output_metrics(item, metrics)
        return
    if not isinstance(value, dict):
        return
    outputs = value.get("outputs")
    if isinstance(outputs, list):
        for output in outputs:
            _accumulate_sample_output_metrics(output, metrics)
    data = value.get("data")
    if isinstance(data, (dict, list)):
        _accumulate_sample_output_metrics(data, metrics)
    fields = value.get("fields")
    if isinstance(fields, list):
        metrics["fieldCount"] = int(metrics.get("fieldCount") or 0) + len(fields)
        for field in fields:
            if isinstance(field, dict):
                label = str(field.get("label") or field.get("key") or field.get("field_name") or field.get("name") or "").strip()
                if label:
                    metrics.setdefault("fieldLabels", []).append(label)
    records = value.get("records")
    if isinstance(records, list):
        metrics["recordCount"] = int(metrics.get("recordCount") or 0) + len(records)
    rows = value.get("rows")
    if isinstance(rows, list):
        metrics["rowCount"] = max(int(metrics.get("rowCount") or 0), len(rows))
        width = max((len(row) for row in rows if isinstance(row, list)), default=0)
        metrics["columnCount"] = max(int(metrics.get("columnCount") or 0), width)
    headers = value.get("headers")
    if isinstance(headers, list):
        metrics["columnCount"] = max(int(metrics.get("columnCount") or 0), len(headers))


def _skill_text_contract(skill_text: str) -> dict[str, Any]:
    try:
        parsed = parse_skill_markdown(skill_text)
    except ValueError:
        return {}
    output = parsed.frontmatter.get("output")
    output_type = output.get("type") if isinstance(output, dict) else ""
    return {
        "kind": parsed.frontmatter.get("kind"),
        "renderer": parsed.frontmatter.get("renderer"),
        "outputType": output_type,
        "resultKind": parsed.frontmatter.get("resultKind"),
    }


def _personalize_sample_skill_text(skill_text: str, payload: SkillDraftFromSampleRequest) -> str:
    text = str(skill_text or "").strip()
    if not text.startswith("---"):
        return text
    data_type = payload.dataTypeName.strip() or ("样例数据" if payload.kind == "extraction" else "样例处理")
    suffix = uuid4().hex[:8]
    prefix = "extract" if payload.kind == "extraction" else "process"
    skill_id = f"{prefix}_sample_{suffix}".lower()
    display_name = data_type if data_type.endswith(("提取", "处理", "分析", "核对")) else (
        f"{data_type}提取" if payload.kind == "extraction" else f"{data_type}处理"
    )
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    frontmatter = parts[1]
    body = parts[2]
    if re.search(r"(?m)^id\s*:", frontmatter):
        frontmatter = re.sub(r"(?m)^id\s*:.*$", f"id: {skill_id}", frontmatter, count=1)
    else:
        frontmatter = f"\nid: {skill_id}{frontmatter}"
    if re.search(r"(?m)^name\s*:", frontmatter):
        frontmatter = re.sub(r"(?m)^name\s*:.*$", f"name: {display_name}", frontmatter, count=1)
    else:
        frontmatter = f"{frontmatter.rstrip()}\nname: {display_name}\n"
    return f"---{frontmatter}---{body}".strip()


def _force_operation_result_kind(skill_text: str, result_kind: str) -> str:
    if result_kind not in {"decision", "object", "table", "text"}:
        return skill_text
    text = str(skill_text or "").strip()
    parts = text.split("---", 2)
    if len(parts) < 3:
        return skill_text
    frontmatter = parts[1]
    body = parts[2]
    if re.search(r"(?m)^resultKind\s*:", frontmatter):
        frontmatter = re.sub(r"(?m)^resultKind\s*:.*$", f"resultKind: {result_kind}", frontmatter, count=1)
    else:
        frontmatter = f"{frontmatter.rstrip()}\nresultKind: {result_kind}\n"
    return f"---{frontmatter}---{body}".strip()


def _compact_sample_value(value: Any, *, limit: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)
    return _sample_excerpt(text, limit=limit)


def _resolve_skill_detail(
    *,
    kind: str,
    skill_id: str,
    scope: str,
    customer_id: Optional[str],
    include_text: bool = True,
    include_inactive: bool = False,
    business_registry: BusinessSkillRegistry,
    extraction_registry: ExtractionSkillRegistry,
) -> dict[str, Any]:
    resolved_customer_id = customer_id if scope == "customer" else None
    if kind == "operation":
        return business_registry.get_detail(
            skill_id=skill_id,
            scope=scope,
            customer_id=resolved_customer_id,
            include_text=include_text,
            include_inactive=include_inactive,
        ).model_dump()
    elif kind == "extraction":
        return extraction_registry.get_detail(
            skill_id=skill_id,
            scope=scope,
            customer_id=resolved_customer_id,
            include_text=include_text,
            include_inactive=include_inactive,
        ).model_dump()
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kind 只支持 extraction 或 operation。")


def _rewrite_skill_identity_for_copy(skill_text: str, *, source_id: str) -> str:
    parsed = parse_skill_markdown(skill_text)
    source_name = str(parsed.frontmatter.get("name") or source_id).strip()
    copy_id = _unique_copy_id(source_id)
    replacements = {
        "id": copy_id,
        "name": f"{source_name} 副本",
    }
    output = parsed.text
    for key, value in replacements.items():
        pattern = re.compile(rf"(^|\n)({re.escape(key)}:\s*)([^\n]*)")
        if pattern.search(output):
            output = pattern.sub(lambda match, key=key, value=value: f"{match.group(1)}{match.group(2)}{value}", output, count=1)
        else:
            output = output.replace("---\n", f"---\n{key}: {value}\n", 1)
    return output


def _unique_copy_id(source_id: str) -> str:
    suffix = uuid4().hex[:6]
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", source_id.strip()) or "skill"
    return f"{clean}_copy_{suffix}"


def _build_oss_storage() -> OssStorageService:
    try:
        return build_oss_storage_service(get_settings())
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"对象存储不可用，无法保存 Skill 资产：{error}",
        ) from error


def _skill_sample_response(
    record: SkillSampleRecord,
    *,
    include_content: bool = False,
    content: Optional[str] = None,
) -> SkillSampleResponse:
    body = content
    if include_content and body is None:
        try:
            body = _build_oss_storage().read_text_object(objectKey=record.objectKey)
        except Exception:
            body = None
    return SkillSampleResponse(
        id=record.id,
        kind=record.kind,  # type: ignore[arg-type]
        skillId=record.skillId,
        version=record.version,
        customerId=record.customerId,
        instruction=record.instruction,
        objectKey=record.objectKey,
        contentType=record.contentType,
        fileName=record.fileName,
        sizeBytes=record.sizeBytes,
        preview=record.preview,
        content=body,
        createdAt=record.createdAt,
        updatedAt=record.updatedAt,
    )


def _skill_test_run_response(record: SkillTestRunRecord, *, include_payload: bool = False) -> SkillTestRunSummary:
    result_payload = record.result
    facts_payload = record.facts
    if record.resultObjectKey and include_payload:
        result_payload = _read_json_asset(record.resultObjectKey, label="Skill 测试输出")
    elif not include_payload:
        result_payload = record.summary or record.result
    if record.factsObjectKey and include_payload:
        facts_payload = _read_json_asset(record.factsObjectKey, label="Skill 测试输入事实")
    elif not include_payload:
        facts_payload = None
    return SkillTestRunSummary(
        id=record.id,
        kind=record.kind,  # type: ignore[arg-type]
        skillId=record.skillId,
        version=record.version,
        customerId=record.customerId,
        status=record.status,
        valid=record.valid,
        errors=list(record.errors or []),
        summary=record.summary,
        inputObjectKey=record.inputObjectKey,
        resultObjectKey=record.resultObjectKey,
        factsObjectKey=record.factsObjectKey,
        llmObjectKey=record.llmObjectKey,
        result=result_payload,
        facts=facts_payload,
        sampleId=record.sampleId,
        provider=record.provider,
        model=record.model,
        durationMs=record.durationMs,
        inputChars=record.inputChars,
        outputChars=record.outputChars,
        createdAt=record.createdAt,
        updatedAt=record.updatedAt,
    )


def _persist_skill_test_run_if_requested(
    payload: SkillTestRunRequest,
    response: SkillTestRunResponse,
    repository: WorkbenchRepository,
) -> None:
    if not payload.persist:
        return
    try:
        parsed = parse_skill_markdown(payload.skillText)
    except ValueError:
        return
    skill_id = str(parsed.frontmatter.get("id") or "").strip()
    version = str(parsed.frontmatter.get("version") or "1.0.0").strip()
    if not skill_id:
        return
    run_id = f"skill-run-{uuid4().hex[:12]}"
    result_payload: Optional[dict[str, Any]] = None
    if response.extractionResult is not None:
        result_payload = response.extractionResult.model_dump()
    elif isinstance(response.rawOutput, dict):
        result_payload = response.rawOutput
    input_payload = {
        "skillText": payload.skillText,
        "sampleText": payload.sampleText,
        "config": payload.config,
        "customerId": payload.customerId,
        "sampleId": payload.sampleId,
    }
    input_object_key = _write_skill_test_asset(
        kind=payload.kind,
        customer_id=payload.customerId,
        skill_id=skill_id,
        version=version or "1.0.0",
        run_id=run_id,
        name="input",
        payload=input_payload,
    )
    result_object_key = _write_skill_test_asset(
        kind=payload.kind,
        customer_id=payload.customerId,
        skill_id=skill_id,
        version=version or "1.0.0",
        run_id=run_id,
        name="result",
        payload=result_payload or {},
    )
    facts_object_key = _write_skill_test_asset(
        kind=payload.kind,
        customer_id=payload.customerId,
        skill_id=skill_id,
        version=version or "1.0.0",
        run_id=run_id,
        name="facts",
        payload=response.facts or {},
    )
    summary = _summarize_skill_test_run_result(response=response, result_payload=result_payload)
    now = datetime.now(timezone.utc).isoformat()
    repository.save_skill_test_run(
        SkillTestRunRecord(
            id=run_id,
            kind=payload.kind,
            skillId=skill_id,
            version=version or "1.0.0",
            customerId=payload.customerId,
            status="completed" if response.valid else "failed",
            valid=response.valid,
            errors=list(response.errors or []),
            summary=summary,
            inputObjectKey=input_object_key,
            resultObjectKey=result_object_key,
            factsObjectKey=facts_object_key,
            result=None,
            facts=None,
            sampleId=payload.sampleId,
            provider=response.provider,
            model=response.model,
            durationMs=response.durationMs,
            inputChars=response.inputChars,
            outputChars=response.outputChars,
            createdAt=now,
            updatedAt=now,
        )
    )


def _write_skill_test_asset(
    *,
    kind: str,
    customer_id: Optional[str],
    skill_id: str,
    version: str,
    run_id: str,
    name: str,
    payload: dict[str, Any],
) -> str:
    object_key = "/".join(
        [
            "poc",
            _safe_object_segment(customer_id or "platform"),
            "skills",
            _safe_object_segment(kind),
            _safe_object_segment(skill_id),
            _safe_object_segment(version),
            "test-runs",
            _safe_object_segment(run_id),
            f"{_safe_object_segment(name)}.json",
        ]
    )
    _build_oss_storage().write_text_object(
        objectKey=object_key,
        content=json.dumps(payload or {}, ensure_ascii=False, indent=2),
        contentType="application/json; charset=utf-8",
    )
    return object_key


def _safe_object_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "-", str(value or "").strip()).strip("-") or "asset"


def _read_json_asset(object_key: str, *, label: str) -> dict[str, Any]:
    try:
        text = _build_oss_storage().read_text_object(objectKey=object_key, maxBytes=20_000_000)
        parsed = json.loads(text or "{}")
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{label} 无法从对象存储读取：{object_key}",
        ) from error
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{label} OSS 内容不是 JSON 对象：{object_key}",
        )
    return parsed


def _summarize_skill_test_run_result(
    *,
    response: SkillTestRunResponse,
    result_payload: Optional[dict[str, Any]],
) -> dict[str, Any]:
    result = result_payload or {}
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    validation_errors = result.get("validationErrors") if isinstance(result.get("validationErrors"), list) else []
    return {
        "valid": response.valid,
        "status": "completed" if response.valid else "failed",
        "errorCount": len(response.errors or []),
        "errorsPreview": [str(item) for item in (response.errors or [])[:5]],
        "outputCount": len(outputs),
        "validationErrorCount": len(validation_errors),
        "resultKeys": list(result.keys())[:30],
        "preview": _sample_excerpt(json.dumps(result, ensure_ascii=False), limit=1000),
    }


def _default_customer_id(current_user: SessionUser) -> str:
    if current_user.customerIds:
        return current_user.customerIds[0]
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 customerId。")


def _visible_customer_ids(*, current_user: SessionUser, repository: WorkbenchRepository) -> list[str]:
    if current_user.role == "admin":
        return [customer.id for customer in repository.list_customers()]
    return list(current_user.customerIds)


def _ensure_controlled_python_admin(executor: str, current_user: SessionUser) -> None:
    if executor == "controlled_python" and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="controlled_python 仅管理员可发布。")


def _skill_assist_model() -> str:
    return os.getenv("DASHSCOPE_SKILL_ASSIST_MODEL", "qwen3.7-max")


def _call_skill_assistant(payload: SkillAssistRequest) -> tuple[str, str, int]:
    settings = get_settings()
    if not settings.dashscope_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DASHSCOPE_API_KEY 未配置。请配置 BYO OpenAI-compatible 模型后再发起真实 AI 操作。",
        )
    system_prompt = _build_skill_assist_system_prompt(payload.kind)
    sample_text = payload.sampleText.strip()
    if len(sample_text) > 12000:
        sample_text = sample_text[:12000] + "\n...（样本已截断）"
    requirements = [
        "最终答案第一行必须是 ---。",
        "返回完整 SKILL.md，不要只返回片段。",
        "不要只输出 JSON、JSON Schema 或提取结果。",
        "不要使用 Markdown 代码围栏包裹最终 SKILL.md。",
        "frontmatter 必须是合法 YAML。",
        "frontmatter 只放短的机器字段，不要把用户原始要求、样本、JSON 字典、制表符或多行文本放进 frontmatter。",
        "复杂规则、映射字典、输出示例必须写在 Markdown 正文里。",
        "正文面向实施人员维护，写清目标、规则、输出格式和示例。",
    ]
    if payload.kind == "operation":
        requirements.extend(
            [
                "业务处理 Skill 的 resultKind 只能是 decision、object、table、text。",
                "record_collection 只能出现在 targetTypes 中表示可处理的输入对象类型，绝不能作为 resultKind。",
                "如果业务处理要输出 records/记录集合，必须使用 resultKind: object，并把记录数组放入 output_payload.records。",
                "业务处理输出示例必须使用 {\"summary\":\"...\",\"result_kind\":\"object\",\"output_payload\":{\"records\":[...]}} 这种平台协议。",
            ]
        )
    else:
        requirements.extend(
            [
                "如果是结构化解析且 output.type 为 record_collection，输出示例必须使用 {\"records\":[...]}，不要使用裸 JSON 数组。",
                "record_collection 的 output.required 表示 records 中每条记录的必填字段。",
            ]
        )
    user_payload = {
        "kind": payload.kind,
        "instruction": payload.instruction.strip(),
        "currentSkillText": payload.skillText.strip(),
        "realSample": sample_text,
        "requirements": requirements,
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    request_payload = {
        "model": _skill_assist_model(),
        "messages": messages,
        "stream": True,
        "top_p": 0.8,
        "temperature": 0.7,
        "result_format": "message",
        "enable_thinking": True,
        "thinking_budget": 4000,
    }
    req = request.Request(
        url=f"{settings.dashscope_base_url}/chat/completions",
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []
    try:
        with request.urlopen(req, timeout=180, context=_build_ssl_context()) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_text = line.removeprefix("data:").strip()
                if data_text == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content")
                content = delta.get("content")
                if reasoning is not None:
                    reasoning_parts.append(str(reasoning))
                if content:
                    answer_parts.append(str(content))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"DashScope Skill 辅助请求失败: {exc.code} {detail}",
        ) from exc
    except error.URLError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"DashScope Skill 辅助网络调用失败: {exc.reason}",
        ) from exc
    answer = "".join(answer_parts).strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="DashScope Skill 辅助未返回内容。")
    return answer, "".join(reasoning_parts).strip(), len(system_prompt) + len(json.dumps(user_payload, ensure_ascii=False))


def _build_skill_assist_system_prompt(kind: str) -> str:
    common = (
        "你是旗讯OCR智能文档处理平台的 SKILL.md 编写助手。"
        "你的任务是根据用户要求生成或改写可发布的 SKILL.md。"
        "最终答案第一行必须是 ---，必须返回完整 SKILL.md 文本，不要输出解释，不要用代码围栏包裹。"
        "禁止只返回 JSON、JSON Schema、提取结果或空模板。"
        "如果用户给了现有 SKILL.md，除非用户明确要求，否则保留原 id、kind 和主要输出类型。"
        "frontmatter 只允许放 id、version、name、kind、category、enabled、sourceTypes、targetTypes、executor、input、renderer、output、resultKind、configSchema、outputSchema、defaults 等短字段。"
        "不要把用户原始要求、样本、JSON 映射、制表符或多行长文本放入 frontmatter；这些内容必须写入正文。"
    )
    if kind == "operation":
        return (
            common +
            "业务处理 Skill 的 kind 必须是 operation。"
            "executor 只能从 llm_structured、local_transform、quality_check、export_data、http_connector、controlled_python、external_connector 中选择。"
            "如果不是明确的本地映射、检查、导出或接口调用，默认使用 llm_structured。"
            "必须声明 targetTypes、resultKind、renderer、outputSchema。"
            "resultKind 只允许 decision、object、table、text，绝不能使用 record_collection。"
            "record_collection 只能作为 targetTypes 中的输入目标类型，表示这个 Skill 可以处理记录集合。"
            "如果用户要输出 records 或记录集合，必须使用 resultKind: object，outputSchema.type: object，"
            "并在正文输出示例中使用 {\"summary\":\"...\",\"result_kind\":\"object\",\"output_payload\":{\"records\":[...]}}。"
            "业务处理执行结果最终必须返回 summary、result_kind、output_payload 三个字段。"
        )
    return (
        common +
        "结构化解析 Skill 的 kind 必须是 extraction，executor 必须是 llm_structured。"
        "必须声明 sourceTypes、input.builder、renderer、output。"
        "如果目标是多条记录集合，优先使用 renderer: nested_records 和 output.type: record_collection。"
        "record_collection 的平台协议固定为 JSON 对象 {\"records\":[...]}，不要在输出格式中写裸 JSON 数组。"
        "如果用户说“输出 JSON 数组”，也必须在 SKILL.md 中表达为 {\"records\":[...]}。"
        "record_collection 的 output.required 表示 records 中每条记录的必填字段，不是 JSON 顶层字段。"
        "如果目标是报告对象且同时包含 KV 和 list，可以使用 output.type: custom，正文必须写清哪些字段是 KV、哪些字段是 list。"
        "输出格式中的空字符串只是结构占位，执行时必须从识别事实中填入真实值，不能返回空模板。"
        "规则必须强调只基于识别结果、保留所有行、不要编造。"
    )


def _extract_skill_markdown(answer: str) -> str:
    text = answer.strip()
    fence_match = re.match(
        r"^\s*```(?:md|markdown|skill\.md)?\s*\n([\s\S]*?)\n```\s*$",
        text,
        flags=re.IGNORECASE,
    )
    if fence_match:
        text = fence_match.group(1).strip()
    start_match = re.search(r"(?m)^---\s*$", text)
    start = start_match.start() if start_match else -1
    if start > 0:
        text = text[start:].strip()
    return text


def _synthesize_skill_markdown_from_assistant_answer(payload: SkillAssistRequest, answer: str) -> str:
    instruction = payload.instruction.strip() or ("结构化解析" if payload.kind == "extraction" else "业务处理")
    output_example = _normalize_output_example(answer)
    if payload.kind == "operation":
        output_example = _coerce_operation_output_example(output_example)
        return f"""---
id: custom_operation_sample
version: 1.0.0
name: 样本反推业务处理
kind: operation
category: business_operation
targetTypes: [field, table, structured_object, record_collection, record, output]
executor: llm_structured
resultKind: object
renderer: auto
outputSchema:
  type: object
---

# 目标

{instruction}

# 规则

- 只处理用户选中的提取结果。
- 按本次处理要求输出结构化结果。
- 不要编造输入中不存在的数据。
- result_kind 只允许 decision、object、table、text。
- 如果输出 records/记录集合，使用 result_kind=object，并将记录数组放入 output_payload.records。

# 输出格式

模型执行时必须返回完整业务处理协议：

```json
{output_example}
```
"""
    output_type, renderer = _infer_extraction_output_shape(output_example)
    output_example = _coerce_output_example_for_output_type(output_example, output_type)
    required_fields = _infer_required_fields_from_output_example(output_example)
    required_line = f"\n  required: {json.dumps(required_fields, ensure_ascii=False)}" if output_type == "record_collection" and required_fields else ""
    return f"""---
id: custom_extraction_from_sample
version: 1.0.0
name: 样本反推结构化解析
kind: extraction
category: extraction
enabled: true
sourceTypes: [text, html_table]
executor: llm_structured
input:
  builder: page_compact
renderer: {renderer}
output:
  type: {output_type}{required_line}
---

# 目标

{instruction}

# 规则

- 只基于当前页识别结果。
- 输出格式里的空值只是结构占位，执行时必须填入样本中可见的真实值。
- 如果某一项在样本中可见，不允许返回空字符串。
- list 字段必须保留所有有效行，不要只返回第一行。
- 如果 output.type 是 record_collection，最终执行结果必须返回 JSON 对象 {{"records":[...]}}, 不要返回裸数组或单条对象。
- record_collection 的 output.required 表示 records 中每条记录的必填字段。
- 不要去重，不要汇总，不要编造。

# 输出格式

```json
{output_example}
```
"""


def _normalize_assisted_skill_contract(payload: SkillAssistRequest, skill_text: str) -> str:
    try:
        parsed = parse_skill_markdown(skill_text)
    except ValueError:
        return skill_text
    if payload.kind == "operation":
        return _normalize_operation_skill_contract(parsed.body, parsed.frontmatter, skill_text)
    if payload.kind != "extraction":
        return skill_text
    output = parsed.frontmatter.get("output")
    if not isinstance(output, dict) or output.get("type") != "record_collection":
        return skill_text

    frontmatter = skill_text.split("---", 2)[1].strip()
    required_fields = _resolve_record_collection_required_fields(
        output=output,
        body=parsed.body,
        instruction=payload.instruction,
    )
    body = _normalize_record_collection_body(parsed.body, required_fields=required_fields)
    if required_fields:
        frontmatter = _ensure_record_collection_required(frontmatter, required_fields)
    return f"---\n{frontmatter}\n---\n\n{body}".strip()


def _normalize_operation_skill_contract(body: str, payload: dict[str, Any], skill_text: str) -> str:
    if str(payload.get("kind") or "").strip() != "operation":
        return skill_text
    frontmatter = skill_text.split("---", 2)[1].strip()
    result_kind = str(payload.get("resultKind") or "").strip()
    if result_kind not in {"decision", "object", "table", "text"}:
        frontmatter = _ensure_frontmatter_scalar(frontmatter, "resultKind", "object", after_key="executor")
        result_kind = "object"
    normalized_body = _normalize_operation_body(body, result_kind=result_kind)
    return f"---\n{frontmatter}\n---\n\n{normalized_body}".strip()


def _ensure_frontmatter_scalar(frontmatter: str, key: str, value: str, *, after_key: str) -> str:
    pattern = rf"(?m)^{re.escape(key)}\s*:\s*.*$"
    replacement = f"{key}: {value}"
    if re.search(pattern, frontmatter):
        return re.sub(pattern, replacement, frontmatter, count=1)
    lines = frontmatter.splitlines()
    result: list[str] = []
    inserted = False
    for line in lines:
        result.append(line)
        if not inserted and re.match(rf"^{re.escape(after_key)}\s*:", line):
            result.append(replacement)
            inserted = True
    if not inserted:
        result.append(replacement)
    return "\n".join(result)


def _normalize_operation_body(body: str, *, result_kind: str) -> str:
    normalized = _remove_markdown_section(body, "平台输出协议")
    output_format_section = _build_operation_output_format_section(result_kind)
    if re.search(r"(?m)^#\s+输出格式\s*$", normalized):
        normalized = _replace_markdown_section(normalized, "输出格式", output_format_section)
    else:
        normalized = f"{normalized.rstrip()}\n\n{output_format_section}".strip()
    return normalized


def _normalize_record_collection_body(body: str, *, required_fields: list[str]) -> str:
    normalized = _wrap_record_collection_json_examples(body)
    normalized = _remove_markdown_section(normalized, "平台输出协议")
    output_format_section = _build_record_collection_output_format_section(required_fields)
    if re.search(r"(?m)^#\s+输出格式\s*$", normalized):
        normalized = _replace_markdown_section(normalized, "输出格式", output_format_section)
    else:
        normalized = f"{normalized.rstrip()}\n\n{output_format_section}".strip()
    return normalized


def _wrap_record_collection_json_examples(body: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return match.group(0)
        if not isinstance(parsed, list):
            return match.group(0)
        wrapped = json.dumps({"records": parsed}, ensure_ascii=False, indent=2)
        return f"```json\n{wrapped}\n```"

    return re.sub(r"```json\s*\n([\s\S]*?)\n```", replace, body, flags=re.IGNORECASE)


def _resolve_record_collection_required_fields(
    *,
    output: dict[str, Any],
    body: str,
    instruction: str,
) -> list[str]:
    required_fields = [
        str(item).strip()
        for item in (output.get("required") or [])
        if str(item).strip()
    ] if isinstance(output.get("required"), list) else []
    if required_fields:
        return required_fields
    required_fields = _infer_required_fields_from_output_example(_extract_first_json_example(body))
    if required_fields:
        return required_fields
    if instruction:
        return _infer_required_fields_from_instruction(instruction)
    return []


def _build_record_collection_output_format_section(required_fields: list[str]) -> str:
    example_fields = required_fields or ["字段1", "字段2"]
    example_record = {field: "" for field in example_fields}
    example_json = json.dumps({"records": [example_record]}, ensure_ascii=False, indent=2)
    required_display = "、".join(f"`{field}`" for field in example_fields)
    return (
        "# 输出格式\n\n"
        "必须返回 JSON 对象，顶层结构严格为：\n\n"
        f"```json\n{example_json}\n```\n\n"
        "要求：\n"
        "- 只能返回 JSON 对象，不返回解释文本、Markdown 包裹或裸数组。\n"
        "- 顶层必须包含 `records`，且 `records` 必须是数组。\n"
        "- 不要只返回第一条记录，也不要返回单条对象。\n"
        f"- `records` 中每条记录都必须包含这些字段：{required_display}。\n"
        "- 字段缺失时返回空字符串 `\"\"`。\n"
    ).strip()


def _build_operation_output_format_section(result_kind: str) -> str:
    example_payload: dict[str, Any] | str
    output_rules = [
        "- 必须返回 JSON 对象，且必须包含 `summary`、`result_kind`、`output_payload` 三个字段。",
        f"- `result_kind` 必须固定为 `{result_kind}`。",
    ]
    if result_kind == "table":
        example_payload = {
            "headers": ["字段1", "字段2"],
            "rows": [
                {"字段1": "", "字段2": ""},
            ],
        }
        output_rules.extend(
            [
                "- `output_payload.headers` 必须是字符串数组。",
                "- `output_payload.rows` 必须是对象数组，数组中每一项代表一行数据。",
            ]
        )
    elif result_kind == "text":
        example_payload = "处理后的文本结果"
        output_rules.extend(
            [
                "- `output_payload` 必须是字符串，不要返回对象或数组。",
            ]
        )
    elif result_kind == "decision":
        example_payload = {
            "decision": "pass",
            "reason": "",
            "confidence": "",
        }
        output_rules.extend(
            [
                "- `output_payload` 必须是对象，至少包含决策结论和原因。",
                "- 不要把 decision 结果写成裸字符串或裸布尔值。",
            ]
        )
    else:
        example_payload = {
            "records": [
                {
                    "字段1": "",
                    "字段2": "",
                }
            ]
        }
        output_rules.extend(
            [
                "- `output_payload` 必须是对象。",
                "- 如果要输出记录集合，请放在 `output_payload.records` 中，不要返回裸数组。",
            ]
        )

    example_json = json.dumps(
        {
            "summary": "已完成业务处理。",
            "result_kind": result_kind,
            "output_payload": example_payload,
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        "# 输出格式\n\n"
        "必须返回以下业务处理协议：\n\n"
        f"```json\n{example_json}\n```\n\n"
        "要求：\n"
        + "\n".join(output_rules)
    ).strip()


def _replace_markdown_section(body: str, heading: str, new_section: str) -> str:
    pattern = rf"(?ms)^#\s+{re.escape(heading)}\s*$.*?(?=^#\s+\S|\Z)"
    replacement = f"{new_section}\n\n"
    if re.search(pattern, body):
        return re.sub(pattern, replacement, body, count=1)
    return f"{body.rstrip()}\n\n{new_section}".strip()


def _remove_markdown_section(body: str, heading: str) -> str:
    pattern = rf"(?ms)^#\s+{re.escape(heading)}\s*$.*?(?=^#\s+\S|\Z)"
    if not re.search(pattern, body):
        return body
    return re.sub(pattern, "", body, count=1).strip()


def _ensure_record_collection_required(frontmatter: str, required_fields: list[str]) -> str:
    required_json = json.dumps(required_fields, ensure_ascii=False)
    replaced = _replace_required_frontmatter_block(frontmatter, required_json)
    if replaced != frontmatter:
        return replaced
    lines = frontmatter.splitlines()
    result: list[str] = []
    inserted = False
    for line in lines:
        result.append(line)
        if not inserted and re.match(r"^\s+type\s*:\s*record_collection\s*$", line):
            indent = re.match(r"^(\s*)", line).group(1)  # type: ignore[union-attr]
            result.append(f"{indent}required: {required_json}")
            inserted = True
    return "\n".join(result)


def _replace_required_frontmatter_block(frontmatter: str, required_json: str) -> str:
    lines = frontmatter.splitlines()
    result: list[str] = []
    skip_child_indent: int | None = None
    replaced = False
    for line in lines:
        if skip_child_indent is not None:
            stripped = line.strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent > skip_child_indent:
                continue
            skip_child_indent = None

        match = re.match(r"^(\s*)required\s*:.*$", line)
        if match and not replaced:
            indent = match.group(1)
            result.append(f"{indent}required: {required_json}")
            skip_child_indent = len(indent)
            replaced = True
            continue
        result.append(line)
    return "\n".join(result) if replaced else frontmatter


def _normalize_output_example(answer: str) -> str:
    text = answer.strip()
    text = re.sub(r"^json\s*", "", text, flags=re.IGNORECASE).strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return json.dumps({"result": text}, ensure_ascii=False, indent=2)


def _coerce_operation_output_example(output_example: str) -> str:
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        parsed = {"result": output_example}

    if isinstance(parsed, dict) and (
        "result_kind" in parsed
        or "resultKind" in parsed
        or "output_payload" in parsed
        or "outputPayload" in parsed
    ):
        raw_result_kind = str(parsed.get("result_kind") or parsed.get("resultKind") or "object").strip().lower()
        result_kind = raw_result_kind if raw_result_kind in {"decision", "object", "table", "text"} else "object"
        output_payload = parsed.get("output_payload") if "output_payload" in parsed else parsed.get("outputPayload")
        if output_payload is None:
            output_payload = {
                key: value
                for key, value in parsed.items()
                if key not in {"summary", "result_kind", "resultKind", "output_payload", "outputPayload"}
            }
        return json.dumps(
            {
                "summary": str(parsed.get("summary") or "已完成业务处理。"),
                "result_kind": result_kind,
                "output_payload": output_payload if output_payload is not None else {},
            },
            ensure_ascii=False,
            indent=2,
        )

    if isinstance(parsed, list):
        output_payload: Any = {"records": parsed}
    elif isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
        output_payload = {"records": parsed["records"]}
    elif isinstance(parsed, dict):
        output_payload = parsed
    else:
        output_payload = {"value": parsed}
    return json.dumps(
        {
            "summary": "已完成业务处理。",
            "result_kind": "object",
            "output_payload": output_payload,
        },
        ensure_ascii=False,
        indent=2,
    )


def _infer_extraction_output_shape(output_example: str) -> tuple[str, str]:
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        return "custom", "json_view"
    if isinstance(parsed, dict):
        if isinstance(parsed.get("headers"), list) and isinstance(parsed.get("rows"), list):
            return "data_table", "data_table"
        if isinstance(parsed.get("records"), list):
            return "record_collection", "nested_records"
        if isinstance(parsed.get("kv"), dict) and isinstance(parsed.get("table"), list):
            return "kv_record_table", "nested_records"
    if isinstance(parsed, list):
        return "record_collection", "nested_records"
    return "custom", "json_view"


def _coerce_output_example_for_output_type(output_example: str, output_type: str) -> str:
    if output_type != "record_collection":
        return output_example
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        return output_example
    if isinstance(parsed, list):
        return json.dumps({"records": parsed}, ensure_ascii=False, indent=2)
    return output_example


def _extract_first_json_example(body: str) -> str:
    match = re.search(r"```json\s*\n([\s\S]*?)\n```", body, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _infer_required_fields_from_output_example(output_example: str) -> list[str]:
    if not output_example.strip():
        return []
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        return []
    records = parsed.get("records") if isinstance(parsed, dict) else parsed
    if not isinstance(records, list):
        return []
    for record in records:
        if isinstance(record, dict):
            return [str(key).strip() for key in record.keys() if str(key).strip()]
    return []


def _infer_required_fields_from_instruction(instruction: str) -> list[str]:
    match = re.search(r"(?:输出格式|输出字段|字段)\s*[：:]\s*([^\n。；;]+)", instruction)
    if not match:
        return []
    source = match.group(1)
    source = re.sub(r"[，,、/|]+", " ", source)
    fields = [item.strip() for item in source.split() if item.strip()]
    return [item for item in fields if len(item) <= 32][:20]


def _safe_build_test_facts(sample_text: str) -> dict[str, Any]:
    try:
        return _build_test_facts(sample_text)
    except Exception:
        return {}


def _build_test_facts(sample_text: str) -> dict[str, Any]:
    text = sample_text.strip()
    if not text:
        raise ValueError("样本内容不能为空。")
    if text.startswith("{") or text.startswith("["):
        parsed = json.loads(text)
        facts = _facts_from_json_payload(parsed)
        if facts:
            return facts
    table_matches = re.findall(r"<table[\s\S]*?</table>", text, flags=re.IGNORECASE)
    if table_matches:
        return {
            "pages": [
                {
                    "pageNo": 1,
                    "title": "上传样本",
                    "blocks": [
                        {
                            "type": "table",
                            "title": f"样本表格 {index}",
                            "tableGrid": _table_grid_from_html(html, title=f"样本表格 {index}"),
                        }
                        for index, html in enumerate(table_matches, start=1)
                    ],
                }
            ]
        }
    return {
        "pages": [
            {
                "pageNo": 1,
                "title": "上传样本",
                "blocks": [{"type": "text", "title": "", "text": text}],
            }
        ]
    }


def _facts_from_json_payload(payload: Any) -> Optional[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("pages"), list):
        pages = []
        for page in payload.get("pages") or []:
            if not isinstance(page, dict):
                continue
            blocks = page.get("blocks")
            if isinstance(blocks, list):
                compact_blocks = []
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if isinstance(block.get("tableGrid"), dict):
                        compact_blocks.append(
                            {
                                "type": "table",
                                "title": str(block.get("title") or ""),
                                "tableGrid": block.get("tableGrid"),
                            }
                        )
                    elif str(block.get("type") or "").lower() == "table" and "<table" in str(block.get("content") or "").lower():
                        compact_blocks.append(
                            {
                                "type": "table",
                                "title": str(block.get("title") or ""),
                                "tableGrid": _table_grid_from_html(
                                    str(block.get("content") or ""),
                                    title=str(block.get("title") or ""),
                                ),
                            }
                        )
                    elif str(block.get("content") or block.get("text") or "").strip():
                        compact_blocks.append(
                            {
                                "type": str(block.get("type") or "text"),
                                "title": str(block.get("title") or ""),
                                "text": str(block.get("text") or block.get("content") or "").strip(),
                            }
                        )
                pages.append({"pageNo": int(page.get("pageNo") or len(pages) + 1), "title": str(page.get("title") or ""), "blocks": compact_blocks})
        if pages:
            return {"pages": pages}
    if isinstance(payload, dict) and isinstance(payload.get("markdownSegments"), list):
        return _facts_from_markdown_segments(payload.get("markdownSegments"))
    if isinstance(payload, dict):
        for key in ("task", "page", "payload", "data"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                facts = _facts_from_json_payload(nested)
                if facts:
                    return facts
    return None


def _facts_from_markdown_segments(segments: Any) -> Optional[dict[str, Any]]:
    if not isinstance(segments, list):
        return None
    blocks = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        html = str(segment.get("html") or "")
        if "<table" in html.lower():
            blocks.append(
                {
                    "type": "table",
                    "title": str(segment.get("title") or f"样本表格 {index}"),
                    "tableGrid": _table_grid_from_html(html, title=str(segment.get("title") or f"样本表格 {index}")),
                }
            )
    return {"pages": [{"pageNo": 1, "title": "上传样本", "blocks": blocks}]} if blocks else None


def _table_grid_from_html(html: str, *, title: str) -> dict[str, Any]:
    parsed = parse_table_html(html, title=title)
    logical_grid = parsed.get("logicalGrid") if isinstance(parsed.get("logicalGrid"), list) else []
    rows = [
        [str(cell) for cell in row]
        for row in logical_grid
        if isinstance(row, list) and any(str(cell).strip() for cell in row)
    ]
    return {
        "title": title,
        "rowCount": len(rows),
        "columnCount": max((len(row) for row in rows), default=0),
        "rows": rows,
    }
