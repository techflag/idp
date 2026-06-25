# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""DashScope-compatible LLM helpers for page-group and summary execution."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import json
import logging
import re
import ssl
import time
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Callable, Protocol
from urllib import error, request

from app.core.config import AppSettings
from app.services.extraction_result import (
    extract_field_items_from_custom_result,
    is_field_only_custom_result,
    merge_field_items,
    normalize_custom_result_value,
    normalize_field_items,
)
from app.services.table_parser import parse_table_html

logger = logging.getLogger("uvicorn.error")

BUSINESS_ISSUE_DETAIL_MAX_LENGTH = 24
BUSINESS_ISSUE_SUGGESTION_MAX_LENGTH = 12
PENDING_ISSUE_DETAIL = "需人工核对。"
PASS_ISSUE_DETAIL = "符合当前页证据。"
TABLE_ROW_CHUNK_SIZE = 3
TABLE_TARGET_MATCH_MIN_SCORE = 2
DEFAULT_TABLE_TASK_MODE = "semantic_extract"
TABLE_TASK_MODES = {"parse_json", "semantic_extract", "semantic_enrich"}
DEFAULT_TEXT_EXTRACTION_PROMPT = (
    "提取当前页文本中所有明确的键值字段。"
    "字段名使用原文冒号、空格或标签前的名称；字段值使用当前页直接可见内容。"
    "只返回有明确值的字段，不要编造，不要返回说明性段落。"
)


@dataclass
class PromptRunOutput:
    title: str
    excerpt: str
    detail: str
    structuredExtractionResult: dict[str, Any] | None = None
    structuredProcessResult: dict[str, Any] | None = None
    structuredBusinessResult: dict[str, Any] | None = None
    evidenceBlockIds: list[str] = field(default_factory=list)
    evidenceExcerpts: list[str] = field(default_factory=list)
    rawContent: str = ""
    provider: str = ""
    model: str = ""
    schemaOutput: dict[str, Any] | None = None
    validationErrors: list[str] | None = None
    llmLogs: dict[str, Any] | None = None


class PromptLlmService(Protocol):
    def run_page_group(
        self,
        *,
        taskId: str,
        pageRange: str,
        promptName: str,
        promptText: str,
        pagePayload: dict[str, Any],
        progress_callback: Callable[[PromptRunOutput], None] | None = None,
    ) -> PromptRunOutput: ...

    def run_summary(
        self,
        *,
        taskId: str,
        promptName: str,
        promptText: str,
        pageResults: list[dict[str, Any]],
    ) -> PromptRunOutput: ...

    def run_schema_template(
        self,
        *,
        taskId: str,
        pageRange: str,
        templateId: str,
        templateName: str,
        templateVersion: str | None,
        schemaDefinition: dict[str, Any],
        instructions: str,
        factsPayload: dict[str, Any],
    ) -> PromptRunOutput: ...

    def run_post_process(
        self,
        *,
        taskId: str,
        pageRange: str,
        instruction: str,
        responseMode: str,
        factsPayload: dict[str, Any],
    ) -> PromptRunOutput: ...

    def run_object_operation(
        self,
        *,
        taskId: str,
        pageNo: int,
        operationType: str,
        instruction: str,
        resultMode: str,
        target: dict[str, Any],
        relatedTargets: list[dict[str, Any]],
        factsPayload: dict[str, Any],
    ) -> PromptRunOutput: ...

    def run_extraction_skill(
        self,
        *,
        taskId: str,
        pageRange: str,
        skill: dict[str, Any],
        config: dict[str, Any],
        factsPayload: dict[str, Any],
        applicationScope: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        enable_thinking: bool | None = None,
    ) -> PromptRunOutput: ...

    def review_extraction_skill_output(
        self,
        *,
        taskId: str,
        pageRange: str,
        skill: dict[str, Any],
        config: dict[str, Any],
        factsPayload: dict[str, Any],
        applicationScope: dict[str, Any],
        runtimeContract: dict[str, Any],
        rawExtractionResult: dict[str, Any],
        normalizedExtractionResult: dict[str, Any],
    ) -> PromptRunOutput: ...


class DashScopePromptLlmService:
    """Call DashScope OpenAI-compatible chat completions endpoint."""

    def __init__(self, settings: AppSettings) -> None:
        self._base_url = settings.dashscope_base_url
        self._api_key = settings.dashscope_api_key
        self._model = settings.dashscope_model

    def run_page_group(
        self,
        *,
        taskId: str,
        pageRange: str,
        promptName: str,
        promptText: str,
        pagePayload: dict[str, Any],
        progress_callback: Callable[[PromptRunOutput], None] | None = None,
    ) -> PromptRunOutput:
        pages = pagePayload.get("pages") or []
        logger.info(
            "[LLM] start page_group taskId=%s pageRange=%s promptName=%s pages=%s",
            taskId,
            pageRange,
            promptName,
            len(pages),
        )
        compact_payload = _build_page_prompt_payload(pagePayload)
        effective_prompt_text = _apply_default_prompt_text(promptText, page_payload=compact_payload)
        structured_extraction = None

        enabled_modes = _get_enabled_request_modes(prompt_text=effective_prompt_text, page_payload=compact_payload)
        table_task_mode = _get_table_task_mode(compact_payload)
        business_contents: dict[str, str] = {}
        llm_logs: dict[str, Any] = {
            "mode": "page_group",
            "provider": "dashscope",
            "model": self._model,
            "requests": [],
        }
        extraction_payloads: list[tuple[str, dict[str, Any]]] = []
        extraction_parsed_results: list[dict[str, Any]] = []
        for mode in enabled_modes:
            mode_page_payload = _filter_page_payload_for_mode(compact_payload, mode)
            if mode == "table" and table_task_mode == "parse_json":
                parser_results = _build_table_parser_only_results(
                    page_range=pageRange,
                    mode_prompt="",
                    page_payload=mode_page_payload,
                    table_task_mode=table_task_mode,
                )
                extraction_parsed_results.extend(parser_results)
                for index, parsed_result in enumerate(parser_results, start=1):
                    merge_meta = _get_payload_merge_meta(parsed_result)
                    llm_logs["requests"].append(
                        {
                            "payloadKey": f"parse-table-{index}",
                            "requestKind": "parser",
                            "sourceMode": "table",
                            "chunkIndex": merge_meta.get("chunkIndex"),
                            "chunkCount": merge_meta.get("chunkCount"),
                            "parsed": parsed_result,
                        }
                    )
                continue
            mode_extraction_payloads = _build_extraction_user_payloads(
                page_range=pageRange,
                prompt_text=effective_prompt_text,
                page_payload=mode_page_payload,
                source_mode=mode,
            )
            extraction_payloads.extend(
                (f"extract-{mode}-{index + 1}", payload)
                for index, payload in enumerate(mode_extraction_payloads)
            )

        if extraction_payloads:
            logger.info(
                "[LLM] dispatch extraction taskId=%s pageRange=%s chunks=%s payloadKeys=%s",
                taskId,
                pageRange,
                len(extraction_payloads),
                [payload_key for payload_key, _ in extraction_payloads],
            )
            with ThreadPoolExecutor(max_workers=len(extraction_payloads) or 1) as executor:
                future_map = {
                    executor.submit(
                        self._chat,
                        system_prompt=_build_extraction_system_prompt(
                            source_mode=str(payload.get("sourceMode") or ""),
                            mode_prompt=str(payload.get("modePrompt") or ""),
                        ),
                        user_payload=_build_llm_user_payload(payload),
                    ): (payload_key, payload)
                    for payload_key, payload in extraction_payloads
                }
                for future in as_completed(future_map):
                    payload_key, request_user_payload = future_map[future]
                    chat_result = future.result()
                    content = str(chat_result.get("content") or "")
                    source_mode = str(request_user_payload.get("sourceMode") or "")
                    chunk_index = request_user_payload.get("chunkIndex")
                    chunk_count = request_user_payload.get("chunkCount")
                    parsed_result = _parse_required_json_payload(content, context="结构化抽取")
                    _validate_parse_prompt_payload(parsed_result)
                    parsed_result["_solo_meta"] = {
                        "sourceMode": source_mode,
                        "chunkIndex": chunk_index,
                        "chunkCount": chunk_count,
                        "modePrompt": request_user_payload.get("modePrompt"),
                        "chunkStrategy": request_user_payload.get("chunkStrategy"),
                        "sourceBlockId": request_user_payload.get("sourceBlockId"),
                        "sourceBlockTitle": request_user_payload.get("sourceBlockTitle"),
                        "rowAnchors": list(request_user_payload.get("rowAnchors") or []),
                        "headerRows": list(request_user_payload.get("headerRows") or []),
                        "headerCells": list(request_user_payload.get("headerCells") or []),
                        "headerMode": request_user_payload.get("headerMode"),
                        "columnSemanticAnchor": request_user_payload.get("columnSemanticAnchor"),
                        "expectedFields": list(request_user_payload.get("expectedFields") or []),
                        "expectedFieldSource": request_user_payload.get("expectedFieldSource"),
                        "inputRows": list(request_user_payload.get("inputRows") or []),
                        "parserResult": request_user_payload.get("parserResult"),
                        "relevantBlocks": list(request_user_payload.get("relevantBlocks") or []),
                        "tableTaskMode": request_user_payload.get("tableTaskMode"),
                    }
                    extraction_parsed_results.append(parsed_result)
                    if parsed_result.get("structured_business_result") is not None:
                        business_contents[payload_key] = content
                    llm_logs["requests"].append(
                        {
                            "payloadKey": payload_key,
                            "requestKind": "extraction",
                            "sourceMode": source_mode,
                            "chunkIndex": chunk_index,
                            "chunkCount": chunk_count,
                            "request": chat_result.get("request"),
                            "response": chat_result.get("response"),
                            "trace": _build_chat_trace_meta(chat_result),
                            "parsed": parsed_result,
                        }
                    )
                    response_usage = chat_result.get("response", {}).get("usage") or {}
                    logger.info(
                        "[LLM] done extraction taskId=%s pageRange=%s payloadKey=%s promptTokens=%s completionTokens=%s totalTokens=%s",
                        taskId,
                        pageRange,
                        payload_key,
                        response_usage.get("prompt_tokens"),
                        response_usage.get("completion_tokens"),
                        response_usage.get("total_tokens"),
                    )
                    structured_extraction = _merge_structured_extraction_results(
                        payloads=extraction_parsed_results,
                    )
                    if progress_callback:
                        partial_output = _build_page_group_output(
                            page_range=pageRange,
                            prompt_name=promptName,
                            prompt_text=effective_prompt_text,
                            structured_extraction=structured_extraction,
                            business_parsed_results=extraction_parsed_results,
                            business_contents={},
                            llm_logs=llm_logs,
                            model=self._model,
                        )
                        progress_callback(partial_output)

        if extraction_parsed_results:
            structured_extraction = _merge_structured_extraction_results(
                payloads=extraction_parsed_results,
            )

        return _build_page_group_output(
            page_range=pageRange,
            prompt_name=promptName,
            prompt_text=effective_prompt_text,
            structured_extraction=structured_extraction,
            business_parsed_results=extraction_parsed_results,
            business_contents=business_contents,
            llm_logs=llm_logs,
            model=self._model,
        )

    def run_summary(
        self,
        *,
        taskId: str,
        promptName: str,
        promptText: str,
        pageResults: list[dict[str, Any]],
    ) -> PromptRunOutput:
        chat_result = self._chat(
            system_prompt=_build_summary_system_prompt(),
            user_payload={
                "taskId": taskId,
                "promptName": promptName,
                "promptText": promptText,
                "pageResults": pageResults,
            },
        )
        content = str(chat_result.get("content") or "")
        parsed = _parse_json_payload(content)
        return PromptRunOutput(
            title=str(parsed.get("title") or promptName),
            excerpt=str(parsed.get("excerpt") or "")[:200],
            detail=str(parsed.get("detail") or content),
            structuredExtractionResult=_normalize_structured_extraction_result(
                parsed.get("structured_extraction_result"),
            ),
            structuredProcessResult=_normalize_structured_process_result(
                parsed.get("structured_process_result"),
            ),
            structuredBusinessResult=_normalize_structured_business_result(
                parsed.get("structured_business_result"),
            ),
            evidenceBlockIds=[],
            evidenceExcerpts=[],
            rawContent=content,
            provider="dashscope",
            model=self._model,
            llmLogs={
                "mode": "summary",
                "provider": "dashscope",
                "model": self._model,
                "request": chat_result.get("request"),
                "response": chat_result.get("response"),
                "trace": _build_chat_trace_meta(chat_result),
                "parsed": parsed,
            },
        )

    def run_schema_template(
        self,
        *,
        taskId: str,
        pageRange: str,
        templateId: str,
        templateName: str,
        templateVersion: str | None,
        schemaDefinition: dict[str, Any],
        instructions: str,
        factsPayload: dict[str, Any],
    ) -> PromptRunOutput:
        chat_result = self._chat(
            system_prompt=_build_schema_system_prompt(),
            user_payload=_build_schema_user_payload(
                task_id=taskId,
                page_range=pageRange,
                template_id=templateId,
                template_name=templateName,
                template_version=templateVersion,
                schema_definition=schemaDefinition,
                instructions=instructions,
                facts_payload=factsPayload,
            ),
        )
        content = str(chat_result.get("content") or "")
        parsed = _parse_json_payload(content)
        schema_payload = _normalize_schema_run_payload(
            parsed,
            schema_definition=schemaDefinition,
        )
        schema_output = schema_payload.get("schemaOutput") or {}
        summary = str(schema_payload.get("summary") or templateName).strip()
        evidence_refs = schema_payload.get("evidenceRefs") or []
        validation_errors = [
            str(item).strip()
            for item in (schema_payload.get("validationErrors") or [])
            if str(item).strip()
        ]
        output_text = json.dumps(schema_output, ensure_ascii=False, indent=2) if schema_output else None
        return PromptRunOutput(
            title=f"{pageRange} {templateName}",
            excerpt=summary[:200],
            detail=output_text or summary,
            structuredExtractionResult=None,
            structuredProcessResult={
                "resultType": "transform",
                "summary": summary or "已生成模板处理结果。",
                "outputText": output_text,
                "bullets": [],
                "source": "runtime",
            },
            structuredBusinessResult=None,
            schemaOutput=schema_output,
            validationErrors=validation_errors,
            evidenceBlockIds=[
                str(item.get("blockId") or "").strip()
                for item in evidence_refs
                if str(item.get("blockId") or "").strip()
            ],
            evidenceExcerpts=[
                str(item.get("excerpt") or "").strip()
                for item in evidence_refs
                if str(item.get("excerpt") or "").strip()
            ],
            rawContent=content,
            provider="dashscope",
            model=self._model,
            llmLogs={
                "mode": "schema_template",
                "provider": "dashscope",
                "model": self._model,
                "request": chat_result.get("request"),
                "response": chat_result.get("response"),
                "trace": _build_chat_trace_meta(chat_result),
                "parsed": parsed,
                "normalized": schema_payload,
            },
        )

    def run_post_process(
        self,
        *,
        taskId: str,
        pageRange: str,
        instruction: str,
        responseMode: str,
        factsPayload: dict[str, Any],
    ) -> PromptRunOutput:
        chat_result = self._chat(
            system_prompt=_build_post_process_system_prompt(),
            user_payload=_build_post_process_user_payload(
                task_id=taskId,
                page_range=pageRange,
                instruction=instruction,
                response_mode=responseMode,
                facts_payload=factsPayload,
            ),
        )
        content = str(chat_result.get("content") or "")
        parsed = _parse_json_payload(content)
        process_payload = _normalize_post_process_payload(parsed, response_mode=responseMode)
        result_kind = str(process_payload.get("resultKind"))
        output_payload = process_payload.get("outputPayload")
        summary = str(process_payload.get("summary")).strip()
        evidence_refs = process_payload.get("evidenceRefs") or []
        validation_errors = [
            str(item).strip()
            for item in (process_payload.get("validationErrors") or [])
            if str(item).strip()
        ]
        detail_text = _stringify_post_process_output(
            result_kind=result_kind,
            output_payload=output_payload,
            fallback_summary=summary,
        )
        return PromptRunOutput(
            title=f"{pageRange} 二次处理",
            excerpt=summary[:200],
            detail=detail_text,
            structuredExtractionResult=None,
            structuredProcessResult={
                "summary": summary,
                "resultKind": result_kind,
                "outputPayload": output_payload,
                "validationErrors": validation_errors,
                "evidenceRefs": evidence_refs,
                "source": "runtime",
            },
            structuredBusinessResult=None,
            evidenceBlockIds=[
                str(item.get("blockId") or "").strip()
                for item in evidence_refs
                if str(item.get("blockId") or "").strip()
            ],
            evidenceExcerpts=[
                str(item.get("excerpt") or "").strip()
                for item in evidence_refs
                if str(item.get("excerpt") or "").strip()
            ],
            rawContent=content,
            provider="dashscope",
            model=self._model,
            llmLogs={
                "mode": "post_process",
                "provider": "dashscope",
                "model": self._model,
                "request": chat_result.get("request"),
                "response": chat_result.get("response"),
                "trace": _build_chat_trace_meta(chat_result),
                "parsed": parsed,
                "normalized": process_payload,
            },
        )

    def run_object_operation(
        self,
        *,
        taskId: str,
        pageNo: int,
        operationType: str,
        instruction: str,
        resultMode: str,
        target: dict[str, Any],
        relatedTargets: list[dict[str, Any]],
        factsPayload: dict[str, Any],
    ) -> PromptRunOutput:
        chat_result = self._chat(
            system_prompt=_build_object_operation_system_prompt(),
            user_payload=_build_object_operation_user_payload(
                task_id=taskId,
                page_no=pageNo,
                operation_type=operationType,
                instruction=instruction,
                result_mode=resultMode,
                target=target,
                related_targets=relatedTargets,
                facts_payload=factsPayload,
            ),
        )
        content = str(chat_result.get("content") or "")
        parsed = _parse_required_json_payload(content, context="对象处理")
        operation_payload = _normalize_object_operation_payload(
            parsed,
            operation_type=operationType,
            result_mode=resultMode,
            target_id=str(target.get("id") or ""),
            related_target_ids=[
                str(item.get("id") or "").strip()
                for item in relatedTargets
                if str(item.get("id") or "").strip()
            ],
        )
        result_kind = str(operation_payload.get("resultKind"))
        output_payload = operation_payload.get("outputPayload")
        summary = str(operation_payload.get("summary")).strip()
        evidence_refs = operation_payload.get("evidenceRefs") or []
        validation_errors = [
            str(item).strip()
            for item in (operation_payload.get("validationErrors") or [])
            if str(item).strip()
        ]
        detail_text = _stringify_post_process_output(
            result_kind=result_kind,
            output_payload=output_payload,
        )
        return PromptRunOutput(
            title=f"第 {pageNo} 页对象处理",
            excerpt=summary[:200],
            detail=detail_text,
            structuredExtractionResult=None,
            structuredProcessResult={
                "summary": summary,
                "operationType": operationType,
                "targetId": str(target.get("id") or ""),
                "relatedTargetIds": [
                    str(item.get("id") or "").strip()
                    for item in relatedTargets
                    if str(item.get("id") or "").strip()
                ],
                "resultKind": result_kind,
                "outputPayload": output_payload,
                "validationErrors": validation_errors,
                "evidenceRefs": evidence_refs,
                "source": "runtime",
            },
            structuredBusinessResult=None,
            evidenceBlockIds=[
                str(item.get("blockId") or "").strip()
                for item in evidence_refs
                if str(item.get("blockId") or "").strip()
            ],
            evidenceExcerpts=[
                str(item.get("excerpt") or "").strip()
                for item in evidence_refs
                if str(item.get("excerpt") or "").strip()
            ],
            rawContent=content,
            provider="dashscope",
            model=self._model,
            llmLogs={
                "mode": "object_operation",
                "provider": "dashscope",
                "model": self._model,
                "request": chat_result.get("request"),
                "response": chat_result.get("response"),
                "trace": _build_chat_trace_meta(chat_result),
                "parsed": parsed,
                "normalized": operation_payload,
            },
        )

    def run_extraction_skill(
        self,
        *,
        taskId: str,
        pageRange: str,
        skill: dict[str, Any],
        config: dict[str, Any],
        factsPayload: dict[str, Any],
        applicationScope: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        enable_thinking: bool | None = None,
    ) -> PromptRunOutput:
        user_payload = {
            "taskId": taskId,
            "pageRange": pageRange,
            "skill": skill,
            "config": config,
            "facts": factsPayload,
        }
        if applicationScope:
            user_payload["applicationScope"] = applicationScope
            runtime_contract = applicationScope.get("runtimeContract") if isinstance(applicationScope, dict) else None
            if isinstance(runtime_contract, dict) and runtime_contract:
                user_payload["runtimeContract"] = runtime_contract
        chat_result = self._chat(
            system_prompt=_build_extraction_skill_system_prompt(skill),
            user_payload=user_payload,
            model=model,
            temperature=temperature,
            enable_thinking=enable_thinking,
        )
        effective_model = str(chat_result.get("requestModel") or model or self._model)
        content = str(chat_result.get("content") or "")
        parsed = _parse_required_extraction_skill_payload(content, skill=skill)
        return PromptRunOutput(
            title=str(skill.get("name") or "结构化解析"),
            excerpt="",
            detail=json.dumps(parsed, ensure_ascii=False),
            structuredExtractionResult=parsed,
            structuredProcessResult=None,
            structuredBusinessResult=None,
            evidenceBlockIds=[],
            evidenceExcerpts=[],
            rawContent=content,
            provider="dashscope",
            model=effective_model,
            llmLogs={
                "mode": "extraction_skill",
                "provider": "dashscope",
                "model": effective_model,
                "request": chat_result.get("request"),
                "response": chat_result.get("response"),
                "trace": _build_chat_trace_meta(chat_result),
                "parsed": parsed,
            },
        )

    def review_extraction_skill_output(
        self,
        *,
        taskId: str,
        pageRange: str,
        skill: dict[str, Any],
        config: dict[str, Any],
        factsPayload: dict[str, Any],
        applicationScope: dict[str, Any],
        runtimeContract: dict[str, Any],
        rawExtractionResult: dict[str, Any],
        normalizedExtractionResult: dict[str, Any],
    ) -> PromptRunOutput:
        user_payload = {
            "taskId": taskId,
            "pageRange": pageRange,
            "skill": skill,
            "config": config,
            "facts": factsPayload,
            "applicationScope": applicationScope,
            "runtimeContract": runtimeContract,
            "rawExtractionResult": rawExtractionResult,
            "normalizedExtractionResult": normalizedExtractionResult,
        }
        chat_result = self._chat(
            system_prompt=_build_extraction_skill_review_system_prompt(skill),
            user_payload=user_payload,
            model=None,
            temperature=0.1,
            enable_thinking=False,
        )
        effective_model = str(chat_result.get("requestModel") or self._model)
        content = str(chat_result.get("content") or "")
        parsed = _parse_required_extraction_skill_payload(content, skill=skill)
        return PromptRunOutput(
            title=str(skill.get("name") or "结构化解析复核"),
            excerpt="",
            detail=json.dumps(parsed, ensure_ascii=False),
            structuredExtractionResult=parsed,
            structuredProcessResult=None,
            structuredBusinessResult=None,
            evidenceBlockIds=[],
            evidenceExcerpts=[],
            rawContent=content,
            provider="dashscope",
            model=effective_model,
            llmLogs={
                "mode": "extraction_skill_review",
                "provider": "dashscope",
                "model": effective_model,
                "request": chat_result.get("request"),
                "response": chat_result.get("response"),
                "trace": _build_chat_trace_meta(chat_result),
                "parsed": parsed,
            },
        )

    def _chat(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        model: str | None = None,
        temperature: float | None = None,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("DashScope API Key 未配置")

        request_model = str(model or self._model).strip() or self._model
        request_temperature = temperature if temperature is not None else 0.2
        request_enable_thinking = enable_thinking if enable_thinking is not None else False
        payload = {
            "model": request_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            # DashScope 兼容接口默认关闭 thinking，A/B replay 可按实验参数单次覆盖。
            "enable_thinking": request_enable_thinking,
            "temperature": request_temperature,
        }
        req = request.Request(
            url=f"{self._base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with request.urlopen(req, timeout=180, context=_build_ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DashScope 请求失败: {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"DashScope 网络调用失败: {exc.reason}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("DashScope 未返回 choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        duration_ms = int((time.perf_counter() - started) * 1000)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        trace_meta = {
            "durationMs": duration_ms,
            "inputChars": len(json.dumps(payload, ensure_ascii=False)),
            "promptTokens": usage.get("prompt_tokens"),
            "completionTokens": usage.get("completion_tokens"),
            "totalTokens": usage.get("total_tokens"),
        }
        if isinstance(content, str):
            return {
                "content": content,
                "request": payload,
                "response": data,
                "requestModel": request_model,
                **trace_meta,
                "outputChars": len(content),
            }
        if isinstance(content, list):
            text_parts = [str(item.get("text") or "") for item in content if isinstance(item, dict)]
            joined_content = "\n".join(part for part in text_parts if part)
            return {
                "content": joined_content,
                "request": payload,
                "response": data,
                "requestModel": request_model,
                **trace_meta,
                "outputChars": len(joined_content),
            }
        raise RuntimeError("DashScope 返回内容格式不受支持")


def _build_chat_trace_meta(chat_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "durationMs": chat_result.get("durationMs"),
        "inputChars": chat_result.get("inputChars"),
        "outputChars": chat_result.get("outputChars"),
        "promptTokens": chat_result.get("promptTokens"),
        "completionTokens": chat_result.get("completionTokens"),
        "totalTokens": chat_result.get("totalTokens"),
    }


def _parse_json_payload(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()

    candidate = _extract_first_json_object(stripped)
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            detail_value = parsed.get("detail")
            if isinstance(detail_value, str):
                nested = detail_value.strip()
                if nested.startswith("{") and nested.endswith("}"):
                    try:
                        nested_parsed = json.loads(nested)
                        if isinstance(nested_parsed, dict) and (
                            "structured_business_result" in nested_parsed
                            or "structured_process_result" in nested_parsed
                            or "structured_extraction_result" in nested_parsed
                            or "title" in nested_parsed
                        ):
                            return nested_parsed
                    except json.JSONDecodeError:
                        pass
            return parsed
        if isinstance(parsed, str):
            nested = parsed.strip()
            if nested.startswith("{") and nested.endswith("}"):
                try:
                    nested_parsed = json.loads(nested)
                    if isinstance(nested_parsed, dict):
                        return nested_parsed
                except json.JSONDecodeError:
                    pass
            return {"detail": parsed}
        return {"detail": content}
    except json.JSONDecodeError:
        return {"detail": content}


def _parse_required_json_payload(content: str, *, context: str) -> dict[str, Any]:
    parsed = _parse_json_payload(content)
    if not isinstance(parsed, dict) or set(parsed.keys()) == {"detail"}:
        raise RuntimeError(f"{context}失败：模型未返回合法 JSON 对象。")
    return parsed


def _parse_required_extraction_skill_payload(content: str, *, skill: dict[str, Any]) -> dict[str, Any]:
    output_schema = skill.get("outputSchema") if isinstance(skill.get("outputSchema"), dict) else {}
    output_type = str(output_schema.get("type") or "").strip()
    if output_type == "record_collection":
        parsed = _parse_json_payload_value(content)
        if isinstance(parsed, list):
            return {"records": parsed}
        if isinstance(parsed, dict) and set(parsed.keys()) != {"detail"}:
            return parsed
        raise RuntimeError("Extraction Skill失败：模型未返回合法 record_collection JSON。")
    return _parse_required_json_payload(content, context="Extraction Skill")


def _parse_json_payload_value(content: str) -> Any:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()

    candidate = _extract_first_json_value(stripped)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {"detail": content}
    if isinstance(parsed, str):
        nested = parsed.strip()
        if nested.startswith(("{", "[")):
            try:
                return json.loads(nested)
            except json.JSONDecodeError:
                pass
        return {"detail": parsed}
    return parsed


def _validate_parse_prompt_payload(payload: dict[str, Any]) -> None:
    if "structured_extraction_result" not in payload:
        raise RuntimeError("结构化抽取失败：模型输出缺少 structured_extraction_result。")
    extraction = payload.get("structured_extraction_result")
    if not isinstance(extraction, dict):
        raise RuntimeError("结构化抽取失败：structured_extraction_result 必须是 JSON 对象。")
    missing = [
        field_name
        for field_name in ("summary", "basicInfo")
        if field_name not in extraction
    ]
    if missing:
        raise RuntimeError(f"结构化抽取失败：structured_extraction_result 缺少字段 {', '.join(missing)}。")
    if not isinstance(extraction.get("summary"), str):
        raise RuntimeError("结构化抽取失败：summary 必须是字符串。")
    if not isinstance(extraction.get("basicInfo"), list):
        raise RuntimeError("结构化抽取失败：basicInfo 必须是数组。")


def _build_schema_system_prompt() -> str:
    return (
        "你是文档二级结构化处理助手。"
        "你会收到 OCR/页面事实层、模板说明和输出 schema。"
        "你的任务是只基于给定事实填充 schema_output，不要重复 OCR，不要臆造证据。"
        "必须返回 JSON 对象，结构固定为："
        '{"summary":"",'
        '"schema_output":{},'
        '"validation_errors":[],'
        '"evidence_refs":[{"pageNo":1,"blockId":"","blockPosition":"","excerpt":""}]}.'
        "当字段无法从事实中确认时，不要编造值，把原因写入 validation_errors。"
    )


def _build_post_process_system_prompt() -> str:
    return (
        "你是文档二次处理助手。"
        "你会收到当前页的 OCR/解析事实层和用户的处理要求。"
        "你不能重复 OCR，也不能编造不存在的字段或证据。"
        "请只基于输入 facts 做二次处理。"
        "必须返回 JSON 对象，结构固定为："
        '{"summary":"",'
        '"result_kind":"object|table|issues|text",'
        '"output_payload":{},'
        '"validation_errors":[],'
        '"evidence_refs":[{"pageNo":1,"blockId":"","blockPosition":"","excerpt":""}]}.'
        "其中 result_kind 只允许 object、table、issues、text。"
        "如果用户要求整理成 JSON/结构化结果，优先返回 object；"
        "如果用户要求适合导出/表格结构，优先返回 table；"
        "如果用户要求核对/检查/列问题，优先返回 issues；"
        "如果用户要求改写说明或总结，优先返回 text。"
    )


def _build_extraction_skill_system_prompt(skill: dict[str, Any]) -> str:
    rules = skill.get("rules") if isinstance(skill.get("rules"), list) else []
    examples = skill.get("examples") if isinstance(skill.get("examples"), list) else []
    output_schema = skill.get("outputSchema") if isinstance(skill.get("outputSchema"), dict) else {}
    output_type = str(output_schema.get("type") or "").strip()
    prompt_template = str(skill.get("promptTemplate") or "").strip()
    shape_instruction = _build_extraction_skill_shape_instruction(output_schema)
    full_record_instruction = (
        "如果输入中有多个表格或多行明细，必须逐表逐行完整输出，禁止只输出第一条。"
        if output_type in {"record_collection", "data_table", "kv_record_table"}
        else ""
    )
    return (
        "你是 Extraction Skill 执行器，只能基于用户消息里的当前页识别事实输出业务 JSON。"
        "compact facts 中 tableGrid.rows 是 HTML table 的无损行列展开，不代表业务语义判断。"
        "如果 facts.evidenceSelection.mode 为 field_list_selected_evidence，"
        "tableGrid.rows、dedupedRows、rowTexts 是本次有边界的候选证据窗口，"
        "originalRowCount、rowSelection 和 truncated 表示它并非整张表；"
        "只能从当前 facts 可见内容抽取，候选窗口外的信息不要猜测。"
        "用户消息不会提供 bbox、blockId 或 source id；不要输出证据定位字段。"
        "用户消息里的 config.userInstruction、config.testInstruction 或 config.runtimeEvidenceInstruction "
        "是本次运行的提取诉求，必须优先遵循。"
        "用户消息里的 applicationScope 是文档应用制作时确认的运行契约；"
        "若 applicationScope.targetMapping.generatedTargets 提供 field 标签，field_list 输出必须覆盖这些字段，"
        "该字段清单优先于 Skill 正文中过时或更窄的字段列表；facts 中不可见的字段才返回空字符串。"
        "字段标签和 facts 中的标题、表头、键名不要求字面完全一致；"
        "必须根据语义、上下文、版式区域和定位模块内容判断对应关系并抽取可见值。"
        "若定位模块是文档树模块，必须优先阅读该模块内的文本节点和表格单元格，"
        "不要因为信息在表格、旋转文本、合并单元格或键值串中就忽略。"
        "每个非空字段值都必须能从当前 facts 或 selected Evidence 中找到可追溯证据；"
        "若只能凭 Skill 术语说明或常识推断而无法在证据中确认，必须返回空值或保留复核问题。"
        "如果该诉求和 Skill 规则冲突，以更具体的本次诉求为准，但仍不得编造输入中不存在的数据。"
        "Skill 正文里的输出格式是结构模板，不是最终答案；执行时必须从 facts 中填入真实可见值。"
        "如果字段在 facts 中有明确值，禁止返回空字符串占位；只有 facts 中确实不可见时才可为空。"
        "如果某个字段要求是 list，必须保留所有有效数据行，不要只返回一行模板。"
        f"{full_record_instruction}"
        "必须输出裸 JSON，不要 Markdown，不要代码块，不要解释。"
        "必须严格满足当前 skill 的 outputSchema；不要增加无关顶层字段。"
        f"{shape_instruction}"
        f"\n\nSkill 名称：{skill.get('name') or ''}"
        f"\n输出 schema：{json.dumps(output_schema, ensure_ascii=False)}"
        f"\n规则：{json.dumps(rules, ensure_ascii=False)}"
        f"\n示例：{json.dumps(examples, ensure_ascii=False)}"
        f"\n补充提示：{prompt_template}"
        "\n\n最终运行契约：如果用户消息提供 runtimeContract 或 applicationScope.runtimeContract，"
        "它是本次运行的最高优先级契约。必须优先覆盖 runtimeContract.fieldLabels，"
        "不要被 Skill 正文里的旧字段列表限制；只有 facts 中确实不可见的字段才输出空字符串。"
    )


def _build_extraction_skill_review_system_prompt(skill: dict[str, Any]) -> str:
    output_schema = skill.get("outputSchema") if isinstance(skill.get("outputSchema"), dict) else {}
    shape_instruction = _build_extraction_skill_shape_instruction(output_schema)
    return (
        "你是 Extraction Skill 输出复核器。"
        "你会收到 facts、runtimeContract、原始模型输出和规范化输出。"
        "你的任务是修正漏字段、漏值或输出协议偏差，返回同一个 skill outputSchema 的裸 JSON。"
        "runtimeContract 是最高优先级：field_list 必须覆盖 runtimeContract.fieldLabels。"
        "只能从 facts 中提取值；如果 facts 中不可确认，保留字段并将 value 设为空字符串。"
        "不要编造，不要新增 runtimeContract 以外的无关业务字段。"
        "字段标签与 facts 中标题、表头、键名不要求字面相同，必须按语义、上下文和版式判断。"
        "修正非空值前必须确认值可追溯到当前 facts 或 selected Evidence；"
        "如果只能凭 Skill 术语说明或常识推断，必须保持空值或保留复核问题。"
        "如果 facts.evidenceSelection.mode 为 field_list_selected_evidence，"
        "当前 facts 是已扩展的复核证据包，tableGrid.rows、dedupedRows、rowTexts 仍可能不是整表；"
        "必须使用 rowSelection、originalRowCount 和 truncated 判断证据边界。"
        "必须重点阅读 tableGrid.rows、tableGrid.dedupedRows 和 tableGrid.rowTexts。"
        "如果字段在表格、合并单元格、旋转文本或键值串中可见，不得返回空字符串。"
        "必须输出裸 JSON，不要 Markdown，不要代码块，不要解释。"
        f"{shape_instruction}"
        f"\n输出 schema：{json.dumps(output_schema, ensure_ascii=False)}"
    )


def _build_extraction_skill_shape_instruction(output_schema: dict[str, Any]) -> str:
    output_type = str(output_schema.get("type") or "").strip()
    if output_type == "record_collection":
        return (
            "当前 output.type 是 record_collection，最终 JSON 顶层必须是对象，格式严格为 "
            '{"records":[{...},{...}]}。'
            "records 必须是数组；如果 Skill 正文或本次诉求要求输出 JSON 数组，必须把这个数组作为 records 的值。"
            "禁止返回裸数组，禁止只返回单个记录对象，禁止只返回第一条记录。"
            "records 数组里必须保留输入中所有可见的有效记录。"
            "如果 outputSchema.required 配置了字段名，它表示 records 数组中每条记录都必须包含这些字段，"
            "不要把这些字段放到 JSON 顶层。"
        )
    if output_type == "data_table":
        return (
            "当前 output.type 是 data_table，最终 JSON 顶层必须是对象，格式严格为 "
            '{"headers":[],"rows":[]}。'
            "rows 必须包含所有有效数据行。"
        )
    if output_type == "field_list":
        return '当前 output.type 是 field_list，最终 JSON 顶层必须是对象，格式严格为 {"fields":[{"label":"","value":""}]}。'
    if output_type == "kv_table":
        return '当前 output.type 是 kv_table，最终 JSON 顶层必须是对象，格式严格为 {"kv":{}}。'
    if output_type == "kv_record_table":
        return '当前 output.type 是 kv_record_table，最终 JSON 顶层必须是对象，格式严格为 {"kv":{},"table":[{}]}。'
    return "最终 JSON 顶层必须是对象。"


def _build_object_operation_system_prompt() -> str:
    return (
        "你是文档对象级后处理助手。"
        "你会收到当前页中的一个主对象、可选的关联对象、最小必要事实层和用户操作要求。"
        "你的任务不是总结整页，而是只围绕主对象完成指定操作。"
        "如果主对象类型是 table，它代表整张逻辑表，默认按整表批处理，不要把结果降级成逐行分别回答，除非用户明确要求逐行。"
        "对于 table 类型对象，target.parsedTable 包含解析后的结构化表头与数据行（headers 和 rows 数组），处理时应将 parsedTable 作为主数据源，excerpt 仅作原始参考。"
        "如果主对象类型是 field，则只围绕该字段或字段组完成处理。"
        "当 result_kind=table 时，output_payload 必须是对象，格式为 {\"headers\":[],\"rows\":[]}；"
        "headers 必须放字段名，rows 优先使用对象数组（每行 {字段名: 值}），不要返回只有值、没有字段名的二维数组。"
        "当用户要求提取多个字段时，必须保留每个字段名；多字段属于同一条记录时合并为同一个对象。"
        "必须返回 JSON 对象，结构固定为："
        '{"summary":"",'
        '"result_kind":"decision|object|table|text",'
        '"output_payload":{},'
        '"validation_errors":[],'
        '"evidence_refs":[{"pageNo":1,"blockId":"","blockPosition":"","excerpt":""}]}.'
        "当证据不足时，不要臆造，把原因写入 validation_errors。"
    )


def _build_schema_user_payload(
    *,
    task_id: str,
    page_range: str,
    template_id: str,
    template_name: str,
    template_version: str | None,
    schema_definition: dict[str, Any],
    instructions: str,
    facts_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "taskId": task_id,
        "pageRange": page_range,
        "templateId": template_id,
        "templateName": template_name,
        "templateVersion": template_version or "",
        "instructions": instructions,
        "schemaDefinition": schema_definition,
        "facts": facts_payload,
    }


def _build_post_process_user_payload(
    *,
    task_id: str,
    page_range: str,
    instruction: str,
    response_mode: str,
    facts_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "taskId": task_id,
        "pageRange": page_range,
        "instruction": instruction,
        "responseMode": response_mode,
        "facts": facts_payload,
    }


def _build_object_operation_user_payload(
    *,
    task_id: str,
    page_no: int,
    operation_type: str,
    instruction: str,
    result_mode: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "taskId": task_id,
        "pageNo": page_no,
        "operationType": operation_type,
        "instruction": instruction,
        "resultMode": result_mode,
        "target": target,
        "relatedTargets": related_targets,
        "facts": facts_payload,
    }


def _normalize_schema_run_payload(
    payload: Any,
    *,
    schema_definition: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "summary": "模型未返回有效的模板结果。",
            "schemaOutput": {},
            "validationErrors": ["模型未返回合法 JSON 对象。"],
            "evidenceRefs": [],
        }

    summary = str(payload.get("summary") or "").strip()
    raw_output = payload.get("schema_output")
    schema_output = raw_output if isinstance(raw_output, dict) else {}
    validation_errors = [
        str(item).strip()
        for item in (payload.get("validation_errors") or [])
        if str(item).strip()
    ]
    validation_errors.extend(_validate_schema_output(schema_definition, schema_output))
    evidence_refs = _normalize_evidence_refs(payload.get("evidence_refs"))
    return {
        "summary": summary or "已生成模板处理结果。",
        "schemaOutput": schema_output,
        "validationErrors": validation_errors[:20],
        "evidenceRefs": evidence_refs[:20],
    }


def _normalize_post_process_payload(payload: Any, *, response_mode: str) -> dict[str, Any]:
    _ = response_mode
    if not isinstance(payload, dict):
        raise RuntimeError("二次处理失败：模型输出必须是 JSON 对象。")

    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise RuntimeError("二次处理失败：模型输出缺少 summary。")
    result_kind = str(payload.get("result_kind", payload.get("resultKind")) or "").strip().lower()
    if result_kind not in {"object", "table", "issues", "text"}:
        raise RuntimeError("二次处理失败：result_kind 必须是 object、table、issues 或 text。")
    if "output_payload" in payload:
        output_payload = payload.get("output_payload")
    elif "outputPayload" in payload:
        output_payload = payload.get("outputPayload")
    else:
        raise RuntimeError("二次处理失败：模型输出缺少 output_payload。")
    _validate_post_process_output_payload(result_kind=result_kind, payload=output_payload)
    validation_errors = [
        str(item).strip()
        for item in (payload.get("validation_errors", payload.get("validationErrors")) or [])
        if str(item).strip()
    ]
    evidence_refs = _normalize_evidence_refs(payload.get("evidence_refs", payload.get("evidenceRefs")))
    return {
        "summary": summary,
        "resultKind": result_kind,
        "outputPayload": output_payload,
        "validationErrors": validation_errors[:20],
        "evidenceRefs": evidence_refs[:20],
    }


def _validate_post_process_output_payload(*, result_kind: str, payload: Any) -> None:
    if result_kind == "text" and not isinstance(payload, str):
        raise RuntimeError("二次处理失败：result_kind=text 时 output_payload 必须是字符串。")
    if result_kind == "object" and not isinstance(payload, dict):
        raise RuntimeError("二次处理失败：result_kind=object 时 output_payload 必须是对象。")
    if result_kind == "issues" and not isinstance(payload, list):
        raise RuntimeError("二次处理失败：result_kind=issues 时 output_payload 必须是数组。")
    if result_kind == "table":
        if not isinstance(payload, dict):
            raise RuntimeError("二次处理失败：result_kind=table 时 output_payload 必须是包含 headers 和 rows 的对象。")
        if not isinstance(payload.get("headers"), list) or not isinstance(payload.get("rows"), list):
            raise RuntimeError("二次处理失败：result_kind=table 时 output_payload.headers 和 rows 必须是数组。")


def _normalize_object_operation_payload(
    payload: Any,
    *,
    operation_type: str,
    result_mode: str,
    target_id: str,
    related_target_ids: list[str],
) -> dict[str, Any]:
    _ = operation_type, result_mode
    if not isinstance(payload, dict):
        raise RuntimeError("对象处理失败：模型输出必须是 JSON 对象。")

    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise RuntimeError("对象处理失败：模型输出缺少 summary。")

    raw_result_kind = payload.get("result_kind", payload.get("resultKind"))
    result_kind = str(raw_result_kind or "").strip().lower()
    if result_kind not in {"decision", "object", "table", "text"}:
        raise RuntimeError("对象处理失败：result_kind 必须是 decision、object、table 或 text。")

    if "output_payload" in payload:
        raw_output_payload = payload.get("output_payload")
    elif "outputPayload" in payload:
        raw_output_payload = payload.get("outputPayload")
    else:
        raise RuntimeError("对象处理失败：模型输出缺少 output_payload。")

    _validate_object_operation_output_payload(result_kind=result_kind, payload=raw_output_payload)
    output_payload = raw_output_payload
    validation_errors = [
        str(item).strip()
        for item in (payload.get("validation_errors", payload.get("validationErrors")) or [])
        if str(item).strip()
    ]
    evidence_refs = _normalize_evidence_refs(payload.get("evidence_refs", payload.get("evidenceRefs")))
    return {
        "summary": summary,
        "resultKind": result_kind,
        "outputPayload": output_payload,
        "validationErrors": validation_errors[:20],
        "evidenceRefs": evidence_refs[:20],
        "targetId": target_id,
        "relatedTargetIds": related_target_ids,
    }


def _validate_object_operation_output_payload(*, result_kind: str, payload: Any) -> None:
    if result_kind == "text":
        if not isinstance(payload, str):
            raise RuntimeError("对象处理失败：result_kind=text 时 output_payload 必须是字符串。")
        return

    if result_kind == "decision":
        if not isinstance(payload, dict):
            raise RuntimeError("对象处理失败：result_kind=decision 时 output_payload 必须是对象。")
        return

    if result_kind == "object":
        if not isinstance(payload, dict):
            raise RuntimeError("对象处理失败：result_kind=object 时 output_payload 必须是对象。")
        return

    if result_kind == "table":
        if not isinstance(payload, dict):
            raise RuntimeError("对象处理失败：result_kind=table 时 output_payload 必须是包含 headers 和 rows 的对象。")
        headers = payload.get("headers")
        rows = payload.get("rows")
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise RuntimeError("对象处理失败：result_kind=table 时 output_payload.headers 和 rows 必须是数组。")
        if not all(isinstance(header, str) and header.strip() for header in headers):
            raise RuntimeError("对象处理失败：result_kind=table 时 headers 必须是非空字符串数组。")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("对象处理失败：result_kind=table 时 rows 必须使用对象数组，不能只返回二维值数组。")
        return


def _stringify_post_process_output(
    *,
    result_kind: str,
    output_payload: Any,
    fallback_summary: str = "",
) -> str:
    if result_kind == "text":
        text = str(output_payload or "").strip()
        return text
    if output_payload is None:
        return ""
    if isinstance(output_payload, str):
        return output_payload.strip()
    try:
        return json.dumps(output_payload, ensure_ascii=False, indent=2)
    except TypeError:
        return fallback_summary


def _normalize_evidence_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "pageNo": int(item.get("pageNo") or 0),
                "blockId": str(item.get("blockId") or "").strip(),
                "blockPosition": str(item.get("blockPosition") or "").strip(),
                "excerpt": str(item.get("excerpt") or "").strip(),
            }
        )
    return refs


def _validate_schema_output(schema_definition: dict[str, Any], schema_output: dict[str, Any]) -> list[str]:
    if not isinstance(schema_definition, dict):
        return []
    fields = schema_definition.get("fields")
    if not isinstance(fields, list):
        return []

    errors: list[str] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_key = str(field.get("fieldKey") or "").strip()
        if not field_key:
            continue
        label = str(field.get("label") or field_key)
        required = bool(field.get("required"))
        field_type = str(field.get("type") or "string").strip().lower()
        if field_key not in schema_output:
            if required:
                errors.append(f"{label} 缺失。")
            continue
        value = schema_output.get(field_key)
        if value is None:
            if required:
                errors.append(f"{label} 为空。")
            continue
        if field_type == "string" and not isinstance(value, str):
            errors.append(f"{label} 应为字符串。")
        elif field_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"{label} 应为数字。")
        elif field_type == "boolean" and not isinstance(value, bool):
            errors.append(f"{label} 应为布尔值。")
        elif field_type == "array" and not isinstance(value, list):
            errors.append(f"{label} 应为数组。")
        elif field_type == "object" and not isinstance(value, dict):
            errors.append(f"{label} 应为对象。")
        elif field_type == "enum":
            allowed = [str(item) for item in field.get("enumValues") or []]
            if allowed and str(value) not in allowed:
                errors.append(f"{label} 不在允许枚举值中。")
    return errors


@lru_cache(maxsize=1)
def _build_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _build_extraction_protocol_prompt() -> str:
    return (
        "你是 IDP 结构化抽取助手。"
        "仅基于 sourceMode、modePrompt 和当前 chunk 提供的证据处理结果。"
        "sourceMode=text 只看文本 relevantBlocks；sourceMode=table 只看当前表格 chunk 的证据。"
        "仅输出裸 JSON；顶层只允许 structured_extraction_result、structured_process_result 和 structured_business_result；不要输出 Markdown code fence、代码块、说明、分析过程。"
        "structured_extraction_result 必须包含 summary、basicInfo，可选 customResult。"
        "structured_process_result 可为 null；若返回，结构必须为 {resultType,summary,outputText,bullets}。"
        "resultType 只允许 transform、analysis、mixed。"
        "basicInfo 元素为 {label,value}。"
        "modePrompt 决定本次任务目标。"
        "如果 modePrompt 要求提取字段或键值对，字段结果统一放在 structured_extraction_result.basicInfo，label 使用字段原文。"
        "customResult 只用于 canonicalTable、rowDecisions、markdown_table 等无法表达为字段列表的复杂结构；不要把普通字段放入 customResult。"
        "若 modePrompt 明确列出字段，basicInfo 只返回这些字段，不要返回未要求字段。"
        "若 modePrompt 主要是在做改写、替换、映射、格式化、计算或通用后处理，优先返回 structured_process_result。"
        "无额外业务判断时 structured_business_result 返回 null。"
        "不要复述规则，不要粘贴长证据，不要输出步骤说明、分析过程，不要编造不存在的字段、值、表格行或结论。"
    )


def _mode_prompt_requests_markdown_table(mode_prompt: str) -> bool:
    normalized = mode_prompt.strip().lower()
    if not normalized:
        return False
    return "markdown" in normalized


def _build_table_extraction_prompt(*, mode_prompt: str) -> str:
    markdown_instruction = (
        "若 modePrompt 明确要求 markdown 表格，最终结果会由服务端基于 canonicalTable 派生 markdown_table；当前 chunk 仍不要输出 markdown_table。"
        if _mode_prompt_requests_markdown_table(mode_prompt)
        else "不要输出 markdown_table；最终结果仅保留结构化 JSON，由前端基于返回 JSON 展示。"
    )
    return (
        "若请求提供 expectedFields，则 customResult.rowDecisions[*].resultRow.values 必须严格按 expectedFields 的顺序和数量返回；resultRow.label 直接使用第一列值；不得混入未要求列。"
        "若单行证据天然包含一个或多个键值对，可在 resultRow 中额外返回 rowType=kv_row|hybrid_row 以及 pairs=[{key,value}]；label 与 values 仍保留用于兼容。"
        "每个目标字段应优先映射到原表中最匹配的单列值；除非原单元格本身就是组合文本，否则不要把相邻列、多列或上下文说明拼接成一个字段值。"
        "例如不要把“规格一”和“规格二”拼接成同一个字段值。"
        "当多个源列名称相近时，应选择与目标字段语义最匹配的一列，不要把相邻列、多列或额外上下文混入该字段。"
        "sourceMode=table 且 chunkStrategy=batch_windows 时，表格证据只来自 globalContext 与 batchWindows；relevantBlocks 仅用于标识来源块，不要依赖其内容做额外补充。"
        "若 batchWindows 使用 prevRefs/currentRef/nextRefs 而不是 prevRows/currentRow/nextRows，需先根据 rowPool 中的 id 找到对应 rowHtml，再按完全相同的逐行上下文语义处理。"
        "若请求提供 columnSemanticAnchor，需优先按其中 sourceHeaders 与 targetFieldToSourceColumn 理解原表列义。"
        "若 headerMode=inherited，表示当前 chunk 是续页且当前块未重复打印表头，仍应沿用继承到的列定义，不要把业务数据行误当成表头。"
        "若 chunkStrategy=batch_windows，customResult 必须返回与 batchWindows 一一对应的 rowDecisions。"
        "rowDecisions 元素结构：{anchor,rowIndex,decision,reason,resultRow}；decision 只允许 keep|skip|merge_prev。"
        "有效业务行用 keep；跨列表头说明、重复表头、空行等无关行用 skip；上一业务行的续行用 merge_prev。"
        "reason 保持极短：keep 用“数据行”，merge_prev 用“续行”，skip 仅用“表头”“标题”“头部”“空行”等短词。"
        "sourceMode=table 时，structured_extraction_result.summary 固定返回空字符串，不要解释字段映射、抽取过程或列来源。"
        "不要输出 tables 或 previewRows；表格结构统一放入 customResult。"
        "table 展示由服务端基于最终 canonicalTable/displayTable 派生；不要在当前 chunk 输出 previewRows、markdown_table 或整段表格抄写。"
        + markdown_instruction +
        "当 sourceMode=table 时，customResult 必须覆盖当前 chunk 的完整表格结果，不要跨 chunk 合并，不要只返回部分行。"
    )


def _build_business_extraction_prompt() -> str:
    return (
        "如果 modePrompt 额外要求核对、审查、判断、范围检查或一致性结论，可返回 structured_business_result。"
        "若 modePrompt 明确要求核对、审查或结论，可返回 structured_business_result；证据不足时返回 null，不要编造。"
        "structured_business_result 若返回，结构必须为 {summary,riskLevel,issueCount,issues}；issues 元素为 {level,title,detail,suggestion?}；level 只允许 通过、待确认、关注、风险。"
        "通过场景 detail 固定写“符合当前页证据。”；待确认场景固定写“需人工核对。”。"
        "detail 保持 1 句短句，控制在 24 个中文字符内；suggestion 必须输出时控制在 12 个中文字符内。"
    )


def _mode_prompt_requests_business_result(mode_prompt: str) -> bool:
    normalized = mode_prompt.strip()
    if not normalized:
        return False
    transform_keywords = ("改为", "替换", "映射", "改写", "统一格式", "归一化", "格式化")
    if any(keyword in normalized for keyword in transform_keywords):
        if not any(keyword in normalized for keyword in ("核对", "审查", "合规", "风险", "一致性", "是否通过", "是否缺失")):
            return False

    keywords = ("核对", "审查", "合规", "一致性", "风险", "待确认", "是否通过", "是否合格", "是否缺失")
    return any(keyword in normalized for keyword in keywords)


def _mode_prompt_requests_process_result(mode_prompt: str) -> bool:
    normalized = mode_prompt.strip()
    if not normalized:
        return False
    keywords = (
        "改为",
        "替换",
        "映射",
        "改写",
        "统一格式",
        "归一化",
        "格式化",
        "计算",
        "派生",
        "处理要求",
        "执行以下处理要求",
        "核对",
        "审查",
        "合规",
        "一致性",
        "风险",
        "是否缺失",
    )
    return any(keyword in normalized for keyword in keywords)


def _build_extraction_system_prompt(*, source_mode: str, mode_prompt: str) -> str:
    prompt_parts = [_build_extraction_protocol_prompt()]
    if source_mode == "table":
        prompt_parts.append(_build_table_extraction_prompt(mode_prompt=mode_prompt))
    if _mode_prompt_requests_process_result(mode_prompt):
        prompt_parts.append(
            "若当前任务属于后处理，请优先返回 structured_process_result。"
            "改写/替换/映射/格式化/计算场景使用 resultType=transform；"
            "判断/审查/合规场景使用 resultType=analysis；"
            "同时包含改写输出和判断结论时使用 resultType=mixed。"
            "transform 或 mixed 场景应尽量在 outputText 中给出处理后的可读结果；"
            "analysis 或 mixed 场景可在 bullets 中给出问题项或判断要点。"
        )
    if _mode_prompt_requests_business_result(mode_prompt):
        prompt_parts.append(_build_business_extraction_prompt())
    return "".join(prompt_parts)


def _build_llm_user_payload(user_payload: dict[str, Any]) -> dict[str, Any]:
    request_payload = dict(user_payload)
    request_payload.pop("parserResult", None)
    if (
        str(request_payload.get("sourceMode") or "") == "table"
        and str(request_payload.get("chunkStrategy") or "") == "parser_enrichment"
    ):
        request_payload.pop("inputRows", None)
    if (
        str(request_payload.get("sourceMode") or "") == "table"
        and str(request_payload.get("chunkStrategy") or "") == "batch_windows"
    ):
        request_payload.pop("inputRows", None)
        relevant_blocks = []
        for block in request_payload.get("relevantBlocks") or []:
            sanitized_block = dict(block)
            sanitized_block.pop("content", None)
            relevant_blocks.append(sanitized_block)
        if relevant_blocks:
            request_payload["relevantBlocks"] = relevant_blocks
        batch_windows = list(request_payload.get("batchWindows") or [])
        if len(batch_windows) >= 3:
            row_html_to_id: dict[str, str] = {}
            row_pool: list[dict[str, str]] = []
            for window in batch_windows:
                window_rows = [
                    *[str(row) for row in window.get("prevRows") or [] if str(row).strip()],
                    str(window.get("currentRow") or "").strip(),
                    *[str(row) for row in window.get("nextRows") or [] if str(row).strip()],
                ]
                for row_html in window_rows:
                    if not row_html or row_html in row_html_to_id:
                        continue
                    row_id = f"r{len(row_html_to_id) + 1}"
                    row_html_to_id[row_html] = row_id
                    row_pool.append({"id": row_id, "rowHtml": row_html})

            transformed_windows = []
            for window in batch_windows:
                current_row = str(window.get("currentRow") or "").strip()
                transformed_windows.append(
                    {
                        "anchor": window.get("anchor"),
                        "rowIndex": window.get("rowIndex"),
                        "prevRefs": [
                            row_html_to_id[str(row)]
                            for row in window.get("prevRows") or []
                            if str(row).strip() and str(row) in row_html_to_id
                        ],
                        "currentRef": row_html_to_id.get(current_row),
                        "nextRefs": [
                            row_html_to_id[str(row)]
                            for row in window.get("nextRows") or []
                            if str(row).strip() and str(row) in row_html_to_id
                        ],
                    }
                )
            request_payload["rowPool"] = row_pool
            request_payload["batchWindows"] = transformed_windows
    return request_payload


def _build_summary_system_prompt() -> str:
    return (
        "你是 IDP 文档汇总助手。"
        "请基于已完成的分页结果汇总文档级结论。"
        "只能返回一个 JSON 对象，不要返回 markdown 或额外解释。"
        "JSON 顶层字段必须包含：title, excerpt, detail, structured_extraction_result, "
        "structured_business_result。"
        "若没有结构化抽取或业务结果，可返回 null。"
    )


def _build_merged_result_view(
    *,
    page_range: str,
    prompt_name: str,
    process_result: dict[str, Any] | None,
    business_result: dict[str, Any] | None,
) -> dict[str, str]:
    title = f"{page_range} {prompt_name}"
    if process_result:
        process_excerpt = str(process_result.get("summary") or "").strip()
        process_detail = _build_process_detail_from_result(process_result)
        return {
            "title": title,
            "excerpt": process_excerpt[:200],
            "detail": process_detail,
        }
    if not business_result:
        return {
            "title": title,
            "excerpt": "",
            "detail": "",
        }
    return {
        "title": title,
        "excerpt": str(business_result.get("summary") or "").strip(),
        "detail": _build_business_detail_from_result(business_result),
    }


def _build_page_group_output(
    *,
    page_range: str,
    prompt_name: str,
    prompt_text: str,
    structured_extraction: dict[str, Any] | None,
    business_parsed_results: list[dict[str, Any]],
    business_contents: dict[str, str],
    llm_logs: dict[str, Any],
    model: str,
) -> PromptRunOutput:
    structured_business = _merge_business_results(
        payloads=business_parsed_results,
    )
    structured_process = _merge_structured_process_results(
        payloads=business_parsed_results,
    )
    detail_source = _build_merged_result_view(
        page_range=page_range,
        prompt_name=prompt_name,
        process_result=structured_process,
        business_result=structured_business,
    )
    detail = str(detail_source.get("detail") or "").strip() or _build_model_detail(
        prompt_text=prompt_text,
        extraction_result=structured_extraction,
        process_result=structured_process,
        business_result=structured_business,
    )
    return PromptRunOutput(
        title=str(detail_source.get("title") or f"{page_range} {prompt_name}"),
        excerpt=str(detail_source.get("excerpt") or "")[:200],
        detail=detail,
        structuredExtractionResult=structured_extraction,
        structuredProcessResult=structured_process,
        structuredBusinessResult=structured_business,
        evidenceBlockIds=[],
        evidenceExcerpts=[],
        rawContent=json.dumps(
            {
                "extraction": structured_extraction,
                "business": business_contents,
            },
            ensure_ascii=False,
            indent=2,
        ),
        provider="dashscope",
        model=model,
        llmLogs={
            **llm_logs,
            "requests": list(llm_logs.get("requests") or []),
        },
    )


def _build_extraction_user_payloads(
    *,
    page_range: str,
    prompt_text: str,
    page_payload: dict[str, Any],
    source_mode: str,
) -> list[dict[str, Any]]:
    prompt_text = _apply_default_prompt_text(prompt_text, page_payload=page_payload)
    text_prompt, table_prompt = _split_modal_prompts(prompt_text)
    mode_prompt = text_prompt if source_mode == "text" else table_prompt
    if not mode_prompt:
        return []

    relevant_blocks = _build_relevant_blocks_payload(page_payload)
    payloads: list[dict[str, Any]] = []

    if source_mode == "table":
        payloads = _build_table_extraction_user_payloads(
            page_range=page_range,
            mode_prompt=mode_prompt,
            relevant_blocks=relevant_blocks,
            table_task_mode=_get_table_task_mode(page_payload),
        )
    else:
        block_chunks = _chunk_relevant_blocks(relevant_blocks, source_mode)
        for index, block_chunk in enumerate(block_chunks, start=1):
            payloads.append(
                {
                    "pageRange": page_range,
                    "sourceMode": source_mode,
                    "chunkIndex": index,
                    "chunkCount": 0,
                    "modePrompt": mode_prompt,
                    "relevantBlocks": [
                        {
                            "pageNo": block.get("pageNo"),
                            "type": block.get("type"),
                            "title": block.get("title"),
                            "content": block.get("content"),
                        }
                        for block in block_chunk
                    ],
                }
            )

    effective_chunk_count = len(payloads)
    for index, payload in enumerate(payloads, start=1):
        payload["chunkIndex"] = index
        payload["chunkCount"] = effective_chunk_count

    return payloads


def _split_modal_prompts(prompt_text: str) -> tuple[str, str]:
    trimmed = prompt_text.strip()
    if not trimmed:
        return "", ""

    text_match = re.search(r"文本提示词：([\s\S]*?)(?:\n\s*\n\S+提示词：|$)", trimmed)
    table_match = re.search(r"表格提示词：([\s\S]*?)(?:\n\s*\n\S+提示词：|$)", trimmed)

    return (
        _normalize_prompt_section(text_match.group(1) if text_match else ""),
        _normalize_prompt_section(table_match.group(1) if table_match else ""),
    )


def _normalize_prompt_section(value: str) -> str:
    normalized = value.strip()
    if normalized == "未填写":
        return ""
    return normalized


def _apply_default_prompt_text(prompt_text: str, *, page_payload: dict[str, Any]) -> str:
    text_prompt, table_prompt = _split_modal_prompts(prompt_text)
    if text_prompt or table_prompt or not _page_payload_has_text_blocks(page_payload):
        return prompt_text
    return f"文本提示词：{DEFAULT_TEXT_EXTRACTION_PROMPT}\n\n表格提示词：未填写"


def _page_payload_has_text_blocks(page_payload: dict[str, Any]) -> bool:
    text_types = {"text", "title", "paragraph", "list", "header"}
    for page in page_payload.get("pages") or []:
        for block in page.get("blocks") or []:
            if str(block.get("type") or "").lower() in text_types and str(block.get("content") or "").strip():
                return True
    return False


def _merge_structured_extraction_results(
    *,
    payloads: list[dict[str, Any]],
    fallback: Any = None,
) -> dict[str, Any] | None:
    _ = fallback
    basic_info: list[dict[str, Any]] = []
    seen_basic_info: set[tuple[str, str]] = set()
    seen_basic_info_labels: set[str] = set()
    summary_parts: list[str] = []
    custom_result_values: list[Any] = []
    standalone_custom_result_values: list[Any] = []
    standalone_requested_fields: list[str] = []
    merged_custom_result_groups: dict[str, list[dict[str, Any]]] = {}
    merged_custom_result_order: list[str] = []
    merged_table_input_groups: dict[str, list[dict[str, Any]]] = {}
    merged_table_input_order: list[str] = []
    text_blocks_by_prompt: dict[str, list[Any]] = {}

    def append_basic_info(label: Any, value: Any) -> None:
        normalized_label = str(label or "").strip()
        normalized_value = str(value or "").strip()
        key = (normalized_label, normalized_value)
        label_key = _normalize_field_alias(normalized_label)
        if (
            not normalized_label
            or not normalized_value
            or key in seen_basic_info
            or (label_key and label_key in seen_basic_info_labels)
        ):
            return
        seen_basic_info.add(key)
        if label_key:
            seen_basic_info_labels.add(label_key)
        basic_info.append({"label": normalized_label, "value": normalized_value})

    for payload in payloads:
        merge_meta = _get_payload_merge_meta(payload)
        if str(merge_meta.get("sourceMode") or "").strip() != "text":
            continue
        mode_prompt = str(merge_meta.get("modePrompt") or "").strip()
        if not mode_prompt:
            continue
        text_blocks_by_prompt.setdefault(mode_prompt, []).extend(list(merge_meta.get("relevantBlocks") or []))
    text_requested_fields_by_prompt = {
        mode_prompt: _extract_requested_text_field_names(
            mode_prompt=mode_prompt,
            blocks=blocks,
        )
        for mode_prompt, blocks in text_blocks_by_prompt.items()
    }

    for payload in payloads:
        normalized = _normalize_structured_extraction_result(
            payload.get("structured_extraction_result"),
        )
        if not normalized:
            continue
        merge_meta = _get_payload_merge_meta(payload)
        table_row_chunk_group_key = _get_table_row_chunk_group_key(merge_meta)
        source_mode = str(merge_meta.get("sourceMode") or "").strip()
        mode_prompt = str(merge_meta.get("modePrompt") or "").strip()
        relevant_blocks = list(merge_meta.get("relevantBlocks") or [])
        requested_fields = text_requested_fields_by_prompt.get(mode_prompt, []) if source_mode == "text" else []
        if requested_fields:
            standalone_requested_fields = _merge_requested_field_names(
                standalone_requested_fields,
                requested_fields,
            )
        if requested_fields:
            derived_text_fields = _extract_requested_text_fields_from_blocks(
                blocks=relevant_blocks,
                requested_fields=requested_fields,
            )
            for label, value in derived_text_fields.items():
                append_basic_info(label, value)

        summary = str(normalized.get("summary") or "").strip()
        if summary and summary not in summary_parts:
            summary_parts.append(summary)

        if "customResult" in normalized:
            custom_result = normalized.get("customResult")
            if custom_result is not None:
                if table_row_chunk_group_key:
                    if table_row_chunk_group_key not in merged_custom_result_groups:
                        merged_custom_result_groups[table_row_chunk_group_key] = []
                        merged_custom_result_order.append(table_row_chunk_group_key)
                    merged_custom_result_groups[table_row_chunk_group_key].append(
                        {
                            "chunkIndex": int(merge_meta.get("chunkIndex") or 0),
                            "customResult": custom_result,
                            "_solo_meta": merge_meta,
                        }
                    )
                else:
                    standalone_custom_result_values.append(custom_result)

        if table_row_chunk_group_key:
            if table_row_chunk_group_key not in merged_table_input_groups:
                merged_table_input_groups[table_row_chunk_group_key] = []
                merged_table_input_order.append(table_row_chunk_group_key)
            merged_table_input_groups[table_row_chunk_group_key].append(
                {
                    "chunkIndex": int(merge_meta.get("chunkIndex") or 0),
                    "modePrompt": str(merge_meta.get("modePrompt") or ""),
                    "sourceBlockId": str(merge_meta.get("sourceBlockId") or ""),
                    "sourceBlockTitle": str(merge_meta.get("sourceBlockTitle") or ""),
                    "headerRows": list(merge_meta.get("headerRows") or []),
                    "headerCells": list(merge_meta.get("headerCells") or []),
                    "headerMode": str(merge_meta.get("headerMode") or ""),
                    "chunkStrategy": str(merge_meta.get("chunkStrategy") or ""),
                    "columnSemanticAnchor": (
                        dict(merge_meta.get("columnSemanticAnchor") or {})
                        if isinstance(merge_meta.get("columnSemanticAnchor"), dict)
                        else None
                    ),
                    "expectedFields": list(merge_meta.get("expectedFields") or []),
                    "expectedFieldSource": str(merge_meta.get("expectedFieldSource") or ""),
                    "parserResult": (
                        dict(merge_meta.get("parserResult") or {})
                        if isinstance(merge_meta.get("parserResult"), dict)
                        else None
                    ),
                    "tableTaskMode": str(merge_meta.get("tableTaskMode") or ""),
                    "rowAnchors": list(merge_meta.get("rowAnchors") or []),
                    "inputRows": list(merge_meta.get("inputRows") or []),
                    "customResult": normalized.get("customResult"),
                }
            )

        for item in normalized.get("basicInfo") or []:
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            if requested_fields and not _label_matches_requested_field(label, requested_fields):
                continue
            append_basic_info(label, value)

    merged_table_inputs_by_group: dict[str, dict[str, Any]] = {}
    validation_table_inputs: list[dict[str, Any]] = []
    for group_key in merged_table_input_order:
        merged_table_input = _merge_table_chunk_input_meta(merged_table_input_groups.get(group_key) or [])
        if merged_table_input:
            merged_table_inputs_by_group[group_key] = merged_table_input
            validation_table_inputs.append(merged_table_input)

    merged_custom_results_by_group: dict[str, Any] = {}
    for group_key in merged_custom_result_order:
        merged_custom_result = _merge_table_chunk_custom_results(
            merged_custom_result_groups.get(group_key) or [],
        )
        if merged_custom_result is not None:
            normalized_custom_result = _normalize_table_custom_result(
                custom_result=merged_custom_result,
                table_input=merged_table_inputs_by_group.get(group_key),
            )
            merged_custom_results_by_group[group_key] = normalized_custom_result
            custom_result_values.append(normalized_custom_result)
            merged_table_input = merged_table_inputs_by_group.get(group_key)
            if isinstance(merged_table_input, dict) and isinstance(normalized_custom_result, dict):
                normalized_row_decisions = normalized_custom_result.get("rowDecisions")
                if isinstance(normalized_row_decisions, list):
                    merged_table_input["rowDecisions"] = normalized_row_decisions

    for group_key in merged_table_input_order:
        if group_key in merged_custom_results_by_group:
            continue
        merged_table_input = merged_table_inputs_by_group.get(group_key)
        if not isinstance(merged_table_input, dict):
            continue
        parser_result = merged_table_input.get("parserResult")
        if not isinstance(parser_result, dict):
            continue
        normalized_custom_result = _normalize_table_custom_result(
            custom_result=parser_result,
            table_input=merged_table_input,
        )
        if normalized_custom_result is not None:
            merged_custom_results_by_group[group_key] = normalized_custom_result
            custom_result_values.append(normalized_custom_result)

    merged_standalone_custom_result = _merge_standalone_custom_results(
        standalone_custom_result_values,
        requested_fields=standalone_requested_fields,
    )
    if merged_standalone_custom_result is not None:
        custom_result_values.append(merged_standalone_custom_result)

    if not summary_parts and not basic_info and not custom_result_values:
        return None

    merged_summary = "；".join(summary_parts[:2])
    if not merged_summary and custom_result_values:
        merged_summary = "已抽取表格结果。" if (merged_table_input_order or merged_custom_result_order) else "已完成自定义抽取。"

    merged_payload = {
        "summary": merged_summary,
        "basicInfo": basic_info,
        "customResult": custom_result_values[0] if len(custom_result_values) == 1 else custom_result_values if custom_result_values else None,
        "validationMeta": {"tableInputs": validation_table_inputs} if validation_table_inputs else None,
    }
    return _normalize_structured_extraction_result(merged_payload)


def _build_page_prompt_payload(page_payload: dict[str, Any]) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []

    for page in page_payload.get("pages") or []:
        compact_blocks = []
        for block in page.get("blocks") or []:
            content = str(block.get("content") or "").strip()
            compact_blocks.append(
                {
                    "id": block.get("id"),
                    "type": block.get("type"),
                    "title": block.get("title"),
                    "content": content,
                    "tableHeaderContext": block.get("tableHeaderContext"),
                }
            )

        compact_markdown_segments = []
        for segment in page.get("markdownSegments") or []:
            html = str(segment.get("html") or "").strip()
            if not html:
                continue
            compact_markdown_segments.append(
                {
                    "id": segment.get("id"),
                    "blockId": segment.get("blockId"),
                    "blockPosition": segment.get("blockPosition"),
                    "type": segment.get("type"),
                    "html": html,
                }
            )

        pages.append(
            {
                "pageNo": page.get("pageNo"),
                "title": page.get("title"),
                "summary": page.get("summary"),
                "markdownSegments": compact_markdown_segments,
                "blocks": compact_blocks,
            }
        )

    return {
        "taskId": page_payload.get("taskId"),
        "documentId": page_payload.get("documentId"),
        "pageRange": page_payload.get("pageRange"),
        "tableTaskMode": _get_table_task_mode(page_payload),
        "pages": pages,
    }


def _build_structured_extraction_result(
    *,
    page_range: str,
    text_blocks: list[dict[str, Any]],
    table_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """为旧测试桩保留一个最小抽取结果构造器，避免测试依赖真实 LLM 返回。"""
    basic_info: list[dict[str, str]] = []
    for block in text_blocks[:6]:
        title = str(block.get("title") or "").strip()
        content = str(block.get("content") or "").strip()
        if title and content:
            basic_info.append({"label": title[:32], "value": content[:200]})

    table_results: list[dict[str, Any]] = []
    for block in table_blocks[:6]:
        table_content = str(block.get("content") or "").strip()
        if table_content:
            table_results.append(parse_table_html(table_content, title=str(block.get("title") or "")))

    summary_parts: list[str] = []
    if basic_info:
        summary_parts.append(f"{page_range} 提取到 {len(basic_info)} 个文本字段")
    if table_results:
        row_count = 0
        for table_result in table_results:
            canonical_table = table_result.get("canonicalTable") if isinstance(table_result, dict) else None
            if isinstance(canonical_table, dict):
                row_count += len(canonical_table.get("rows") or [])
        summary_parts.append(f"{page_range} 提取到 {row_count} 行表格数据")

    return {
        "summary": "；".join(summary_parts) or f"{page_range} 已完成基础抽取。",
        "basicInfo": basic_info,
        "customResult": table_results[0] if len(table_results) == 1 else table_results if table_results else None,
    }


def _get_table_task_mode(page_payload: dict[str, Any]) -> str:
    raw_mode = str(page_payload.get("tableTaskMode") or DEFAULT_TABLE_TASK_MODE).strip()
    return raw_mode if raw_mode in TABLE_TASK_MODES else DEFAULT_TABLE_TASK_MODE


def _get_enabled_request_modes(*, prompt_text: str, page_payload: dict[str, Any]) -> list[str]:
    """只按显式模态提示词和当前页块类型决定是否启用 text/table 链路。"""

    prompt_text = _apply_default_prompt_text(prompt_text, page_payload=page_payload)
    text_prompt, table_prompt = _split_modal_prompts(prompt_text)
    table_task_mode = _get_table_task_mode(page_payload)
    block_types = {
        str(block.get("type") or "").lower()
        for page in page_payload.get("pages") or []
        for block in page.get("blocks") or []
    }
    block_types.update(
        str(segment.get("type") or "").lower()
        for page in page_payload.get("pages") or []
        for segment in page.get("markdownSegments") or []
    )
    modes: list[str] = []
    if text_prompt and any(block_type in {"text", "title", "paragraph", "list", "header"} for block_type in block_types):
        modes.append("text")
    table_prompt_enabled = bool(table_prompt) or table_task_mode == "parse_json"
    if table_prompt_enabled and any(block_type in {"table", "table_body"} for block_type in block_types):
        modes.append("table")
    return modes


def _filter_page_payload_for_mode(page_payload: dict[str, Any], mode: str) -> dict[str, Any]:
    allowed_types = {"table", "table_body"} if mode == "table" else {"text", "title", "paragraph", "list", "header"}
    pages = []
    for page in page_payload.get("pages") or []:
        blocks = [
            block
            for block in page.get("blocks") or []
            if str(block.get("type") or "").lower() in allowed_types
        ]
        if not blocks:
            continue
        pages.append(
            {
                "pageNo": page.get("pageNo"),
                "title": page.get("title"),
                "summary": page.get("summary"),
                "blocks": blocks,
            }
        )
    return {
        "taskId": page_payload.get("taskId"),
        "documentId": page_payload.get("documentId"),
        "pageRange": page_payload.get("pageRange"),
        "tableTaskMode": _get_table_task_mode(page_payload),
        "pages": pages,
    }


def _build_relevant_blocks_payload(page_payload: dict[str, Any]) -> list[dict[str, Any]]:
    relevant_blocks: list[dict[str, Any]] = []
    for page in page_payload.get("pages") or []:
        markdown_segments = page.get("markdownSegments") or []
        if markdown_segments:
            for segment in markdown_segments:
                normalized_segment = _normalize_markdown_segment_for_prompt(
                    page_no=page.get("pageNo"),
                    segment=segment,
                )
                if normalized_segment:
                    relevant_blocks.append(normalized_segment)
            continue
        for block in page.get("blocks") or []:
            content = str(block.get("content") or "").strip()
            if not content:
                continue
            relevant_blocks.append(
                {
                    "id": str(block.get("id") or "").strip(),
                    "pageNo": page.get("pageNo"),
                    "type": block.get("type"),
                    "title": block.get("title"),
                    "content": content,
                    "tableHeaderContext": block.get("tableHeaderContext"),
                }
            )
    return relevant_blocks


def _normalize_markdown_segment_for_prompt(
    *,
    page_no: Any,
    segment: dict[str, Any],
) -> dict[str, Any] | None:
    html = str(segment.get("html") or "").strip()
    if not html:
        return None

    segment_type = str(segment.get("type") or "").strip() or "text"
    normalized_type = segment_type.lower()
    content = html if "table" in normalized_type else _strip_html_tags(html)
    if not content:
        return None

    plain_text = _strip_html_tags(html)
    title = plain_text[:80] if plain_text else str(segment.get("blockId") or segment.get("id") or "").strip()

    return {
        "id": str(segment.get("blockId") or segment.get("id") or "").strip(),
        "pageNo": segment.get("pageNo") or page_no,
        "type": segment_type,
        "title": title,
        "content": content,
        "tableHeaderContext": None,
    }


def _chunk_relevant_blocks(relevant_blocks: list[dict[str, Any]], source_mode: str) -> list[list[dict[str, Any]]]:
    if not relevant_blocks:
        return [[]]
    if source_mode == "text":
        return [relevant_blocks]
    return [[block] for block in relevant_blocks]


def _build_table_extraction_user_payloads(
    *,
    page_range: str,
    mode_prompt: str,
    relevant_blocks: list[dict[str, Any]],
    table_task_mode: str = DEFAULT_TABLE_TASK_MODE,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    target_blocks = _filter_target_table_blocks_for_prompt(
        mode_prompt=mode_prompt,
        relevant_blocks=relevant_blocks,
    )
    for block in target_blocks:
        if str(block.get("type") or "").lower() not in {"table", "table_body"}:
            continue
        if table_task_mode == "semantic_enrich":
            payloads.extend(
                _build_table_parser_enrichment_payloads(
                    page_range=page_range,
                    mode_prompt=mode_prompt,
                    block=block,
                    table_task_mode=table_task_mode,
                )
            )
        else:
            payloads.extend(
                _build_table_block_chunk_payloads(
                    page_range=page_range,
                    mode_prompt=mode_prompt,
                    block=block,
                )
            )
    return payloads


def _build_table_parser_enrichment_payloads(
    *,
    page_range: str,
    mode_prompt: str,
    block: dict[str, Any],
    table_task_mode: str,
) -> list[dict[str, Any]]:
    table_content = str(block.get("content") or "").strip()
    if not table_content:
        return []
    rows = re.findall(r"<tr\b[^>]*>[\s\S]*?</tr>", table_content, flags=re.IGNORECASE)
    if not rows:
        return []
    block_id = str(block.get("id") or "")
    parser_result = parse_table_html(table_content, title=str(block.get("title") or ""))
    parser_context = _build_compact_parser_context(parser_result)
    input_rows = _build_table_input_rows(
        chunk_rows=rows,
        row_offset=0,
        block_id=block_id,
    )
    return [
        {
            "pageRange": page_range,
            "sourceMode": "table",
            "chunkIndex": 0,
            "chunkCount": 0,
            "modePrompt": mode_prompt,
            "chunkStrategy": "parser_enrichment",
            "tableTaskMode": table_task_mode,
            "sourceBlockId": block_id,
            "sourceBlockTitle": str(block.get("title") or ""),
            "parserContext": parser_context,
            "relevantBlocks": [
                {
                    "pageNo": block.get("pageNo"),
                    "type": block.get("type"),
                    "title": block.get("title"),
                    "parserContext": parser_context,
                }
            ],
            "rowAnchors": [str(row.get("anchor") or "") for row in input_rows],
            "inputRows": input_rows,
            "parserResult": parser_result,
        }
    ]


def _build_compact_parser_context(parser_result: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in ("title", "tableRole", "canonicalTable", "displayTable", "kvPairs", "segments", "parseWarnings"):
        value = parser_result.get(key)
        if value not in (None, "", [], {}):
            context[key] = value
    return context


def _build_table_parser_only_results(
    *,
    page_range: str,
    mode_prompt: str,
    page_payload: dict[str, Any],
    table_task_mode: str,
) -> list[dict[str, Any]]:
    relevant_blocks = _build_relevant_blocks_payload(page_payload)
    results: list[dict[str, Any]] = []
    table_blocks = [
        block
        for block in relevant_blocks
        if str(block.get("type") or "").lower() in {"table", "table_body"}
    ]
    for block_index, block in enumerate(table_blocks, start=1):
        table_content = str(block.get("content") or "").strip()
        if not table_content:
            continue
        rows = re.findall(r"<tr\b[^>]*>[\s\S]*?</tr>", table_content, flags=re.IGNORECASE)
        if not rows:
            continue
        block_id = str(block.get("id") or "").strip()
        parser_result = parse_table_html(table_content, title=str(block.get("title") or ""))
        input_rows = _build_table_input_rows(
            chunk_rows=rows,
            row_offset=0,
            block_id=block_id,
        )
        results.append(
            {
                "structured_extraction_result": {
                    "summary": "已抽取表格 JSON。",
                    "basicInfo": [],
                    "customResult": parser_result,
                },
                "structured_process_result": None,
                "structured_business_result": None,
                "_solo_meta": {
                    "sourceMode": "table",
                    "chunkIndex": block_index,
                    "chunkCount": 0,
                    "modePrompt": mode_prompt,
                    "chunkStrategy": "parser_only",
                    "sourceBlockId": block_id,
                    "sourceBlockTitle": str(block.get("title") or ""),
                    "rowAnchors": [str(row.get("anchor") or "") for row in input_rows],
                    "inputRows": input_rows,
                    "parserResult": parser_result,
                    "relevantBlocks": [
                        {
                            "pageNo": block.get("pageNo"),
                            "type": block.get("type"),
                            "title": block.get("title"),
                            "content": table_content,
                        }
                    ],
                    "tableTaskMode": table_task_mode,
                },
            }
        )
    chunk_count = len(results)
    for result in results:
        meta = result.get("_solo_meta")
        if isinstance(meta, dict):
            meta["chunkCount"] = chunk_count
    return results


def _build_table_block_chunk_payloads(
    *,
    page_range: str,
    mode_prompt: str,
    block: dict[str, Any],
) -> list[dict[str, Any]]:
    table_content = str(block.get("content") or "").strip()
    if not table_content:
        return []
    
    rows = re.findall(r"<tr\b[^>]*>[\s\S]*?</tr>", table_content, flags=re.IGNORECASE)
    if not rows:
        return []
    parser_result = parse_table_html(table_content, title=str(block.get("title") or ""))
    header_rows, _ = _split_html_table_rows(table_content)
    raw_header_cells: list[str] = []
    for row_html in header_rows:
        raw_header_cells.extend(_extract_html_row_cells(row_html))
    table_header_context = block.get("tableHeaderContext")
    semantic_context = _resolve_table_semantic_context(
        mode_prompt=mode_prompt,
        parser_result=parser_result,
        raw_header_cells=raw_header_cells,
        table_header_context=table_header_context,
    )
    expected_fields = semantic_context["expectedFields"]
    semantic_header_cells = semantic_context["sourceHeaders"]
    header_mode = semantic_context["headerMode"]
    expected_field_source = semantic_context["expectedFieldSource"]
    column_semantic_anchor = _build_column_semantic_anchor(
        mode_prompt=mode_prompt,
        expected_fields=expected_fields,
        source_headers=semantic_header_cells,
        source_column_count=len(semantic_header_cells),
    )

    global_context_rows = rows[:3]

    payloads: list[dict[str, Any]] = []
    for row_offset in range(0, len(rows), TABLE_ROW_CHUNK_SIZE):
        chunk_rows = rows[row_offset : row_offset + TABLE_ROW_CHUNK_SIZE]
        chunk_table_content = "<table>" + "".join([*global_context_rows, *chunk_rows]) + "</table>"
        
        batch_windows = []
        input_rows = []
        for index, row_html in enumerate(chunk_rows):
            global_index = row_offset + index
            anchor = _extract_row_anchor_from_html_row(
                row_html,
                fallback_index=global_index + 1,
                block_id=str(block.get("id") or ""),
            )
            prev_rows = rows[max(0, global_index - 1) : global_index]
            next_rows = rows[global_index + 1 : global_index + 2]
            
            batch_windows.append(
                {
                    "anchor": anchor,
                    "rowIndex": global_index + 1,
                    "prevRows": prev_rows,
                    "currentRow": row_html,
                    "nextRows": next_rows,
                }
            )
            input_rows.append(
                {
                    "anchor": anchor,
                    "rowIndex": global_index + 1,
                    "rowHtml": row_html,
                    "cells": _extract_html_row_cells(row_html),
                }
            )
            
        payloads.append(
            {
                "pageRange": page_range,
                "sourceMode": "table",
                "chunkIndex": 0,
                "chunkCount": 0,
                "modePrompt": mode_prompt,
                "chunkStrategy": "batch_windows",
                "tableTaskMode": "semantic_extract",
                "sourceBlockId": str(block.get("id") or ""),
                "sourceBlockTitle": str(block.get("title") or ""),
                "headerRows": header_rows,
                "headerCells": semantic_header_cells,
                "headerMode": header_mode,
                "columnSemanticAnchor": column_semantic_anchor,
                "expectedFields": expected_fields,
                "expectedFieldSource": expected_field_source,
                "globalContext": global_context_rows,
                "batchWindows": batch_windows,
                "relevantBlocks": [
                    {
                        "pageNo": block.get("pageNo"),
                        "type": block.get("type"),
                        "title": block.get("title"),
                        "content": chunk_table_content,
                    }
                ],
                "rowAnchors": [item["anchor"] for item in batch_windows],
                "inputRows": input_rows,
                "parserResult": parser_result,
            }
        )
    return payloads


def _filter_target_table_blocks_for_prompt(
    *,
    mode_prompt: str,
    relevant_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    table_blocks = [
        block
        for block in relevant_blocks
        if str(block.get("type") or "").lower() in {"table", "table_body"}
    ]
    if len(table_blocks) <= 1:
        return table_blocks

    expected_field_groups = _extract_prompt_field_keyword_groups(mode_prompt)
    if not expected_field_groups:
        scored_blocks = [
            (
                _score_table_block_against_prompt_headers(
                    block=block,
                    mode_prompt=mode_prompt,
                ),
                block,
            )
            for block in table_blocks
        ]
        max_score = max((score for score, _ in scored_blocks), default=0)
        if max_score <= 0:
            return table_blocks
        return [block for score, block in scored_blocks if score == max_score]

    scored_blocks = [
        (
            _score_table_block_against_prompt_fields(
                block=block,
                expected_field_groups=expected_field_groups,
            ),
            block,
        )
        for block in table_blocks
    ]
    max_score = max((score for score, _ in scored_blocks), default=0)
    if max_score < TABLE_TARGET_MATCH_MIN_SCORE:
        return []

    return [
        block
        for score, block in scored_blocks
        if score == max_score and score >= TABLE_TARGET_MATCH_MIN_SCORE
    ]


def _score_table_block_against_prompt_headers(*, block: dict[str, Any], mode_prompt: str) -> int:
    table_content = str(block.get("content") or "").strip()
    if not table_content:
        return 0
    parser_result = parse_table_html(table_content, title=str(block.get("title") or ""))
    header_rows, _ = _split_html_table_rows(table_content)
    raw_header_cells: list[str] = []
    for row_html in header_rows:
        raw_header_cells.extend(_extract_html_row_cells(row_html))
    header_candidates = _collect_table_header_candidates(
        parser_result=parser_result,
        context_headers=[],
        raw_header_cells=raw_header_cells,
    )
    inferred_fields, _ = _infer_table_fields_from_prompt(
        mode_prompt=mode_prompt,
        header_candidates=header_candidates,
    )
    return len(inferred_fields)


def _extract_prompt_field_keyword_groups(mode_prompt: str) -> list[set[str]]:
    match = re.search(r"字段：([\s\S]*?)(?:\n\s*\n|校验要求[:：]|$)", mode_prompt, flags=re.IGNORECASE)
    if not match:
        return []

    raw_section = match.group(1).strip()
    if not raw_section:
        return []

    raw_fields = [
        field.strip()
        for field in re.split(r"[|\n]+", raw_section)
        if field.strip()
    ]
    keyword_groups: list[set[str]] = []
    for raw_field in raw_fields:
        normalized_field = raw_field.strip()
        aliases = {
            normalized_field,
            *[
                part.strip()
                for part in re.split(r"[/、,，\s]+", normalized_field)
                if len(part.strip()) >= 2
            ],
        }
        aliases = {alias for alias in aliases if alias}
        if aliases:
            keyword_groups.append(aliases)
    return keyword_groups


def _build_field_keyword_groups_from_fields(fields: list[str]) -> list[set[str]]:
    groups: list[set[str]] = []
    for field in fields:
        aliases = {
            alias
            for alias in _iter_field_aliases(field)
            if _normalize_field_alias(alias)
        }
        if aliases:
            groups.append(aliases)
    return groups


def _extract_prompt_field_names(mode_prompt: str) -> list[str]:
    match = re.search(r"字段：([\s\S]*?)(?:\n\s*\n|校验要求[:：]|$)", mode_prompt, flags=re.IGNORECASE)
    if not match:
        return []

    raw_section = match.group(1).strip()
    if not raw_section:
        return []

    return [
        field.strip()
        for field in re.split(r"[|\n]+", raw_section)
        if field.strip()
    ]


def _resolve_table_semantic_context(
    *,
    mode_prompt: str,
    parser_result: dict[str, Any],
    raw_header_cells: list[str],
    table_header_context: Any,
) -> dict[str, Any]:
    explicit_fields = _extract_prompt_field_names(mode_prompt)
    explicit_groups = _extract_prompt_field_keyword_groups(mode_prompt)
    context_headers: list[str] = []
    context_mode = "explicit" if raw_header_cells else "none"
    if isinstance(table_header_context, dict):
        context_headers = [
            str(cell).strip()
            for cell in table_header_context.get("sourceHeaders") or []
            if str(cell).strip()
        ]
        context_mode = str(table_header_context.get("headerMode") or context_mode).strip() or context_mode

    header_candidates = _collect_table_header_candidates(
        parser_result=parser_result,
        context_headers=context_headers,
        raw_header_cells=raw_header_cells,
    )

    if explicit_fields:
        source_headers = _select_best_table_header_candidate(
            header_candidates=header_candidates,
            expected_field_groups=explicit_groups or _build_field_keyword_groups_from_fields(explicit_fields),
        )
        return {
            "expectedFields": explicit_fields,
            "expectedFieldSource": "explicit",
            "sourceHeaders": source_headers or context_headers or raw_header_cells,
            "headerMode": context_mode if source_headers in (context_headers, raw_header_cells) else "parser_segment",
        }

    inferred_fields, inferred_headers = _infer_table_fields_from_prompt(
        mode_prompt=mode_prompt,
        header_candidates=header_candidates,
    )
    if inferred_fields:
        return {
            "expectedFields": inferred_fields,
            "expectedFieldSource": "inferred_header",
            "sourceHeaders": inferred_headers,
            "headerMode": "inferred_header",
        }

    return {
        "expectedFields": [],
        "expectedFieldSource": "",
        "sourceHeaders": context_headers or raw_header_cells,
        "headerMode": context_mode,
    }


def _collect_table_header_candidates(
    *,
    parser_result: dict[str, Any],
    context_headers: list[str],
    raw_header_cells: list[str],
) -> list[list[str]]:
    candidates: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def append(headers: Any) -> None:
        if not isinstance(headers, list):
            return
        normalized = [str(item).strip() for item in headers if str(item).strip()]
        if len(normalized) < 2 or _headers_are_placeholder_columns(normalized):
            return
        signature = tuple(_normalize_field_alias(item) for item in normalized)
        if not any(signature) or signature in seen:
            return
        seen.add(signature)
        candidates.append(normalized)

    append(context_headers)
    for segment in parser_result.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("kind") or segment.get("segmentType") or "").strip() != "records":
            continue
        append(segment.get("headers"))
    for table_key in ("canonicalTable", "displayTable"):
        table_payload = parser_result.get(table_key)
        if isinstance(table_payload, dict):
            append(table_payload.get("headers"))
    append(raw_header_cells)
    return candidates


def _headers_are_placeholder_columns(headers: list[str]) -> bool:
    normalized = [str(header).strip() for header in headers if str(header).strip()]
    return bool(normalized) and all(re.fullmatch(r"列\d+", header) for header in normalized)


def _select_best_table_header_candidate(
    *,
    header_candidates: list[list[str]],
    expected_field_groups: list[set[str]],
) -> list[str]:
    if not header_candidates or not expected_field_groups:
        return []

    best_headers: list[str] = []
    best_score = 0
    for headers in header_candidates:
        field_indexes = _resolve_prompt_field_header_indexes(
            header_cells=headers,
            expected_field_groups=expected_field_groups,
        )
        matched_count = sum(1 for index in field_indexes if index is not None)
        if matched_count <= 0:
            continue
        score = matched_count * 100 - len(headers)
        if score > best_score:
            best_score = score
            best_headers = headers
    return best_headers


def _infer_table_fields_from_prompt(
    *,
    mode_prompt: str,
    header_candidates: list[list[str]],
) -> tuple[list[str], list[str]]:
    normalized_prompt = re.sub(r"\s+", " ", str(mode_prompt or "").strip())
    if not normalized_prompt or not header_candidates:
        return ([], [])

    best_fields: list[str] = []
    best_headers: list[str] = []
    best_score = 0
    for headers in header_candidates:
        matched_fields: list[str] = []
        for header in headers:
            if _table_header_appears_in_prompt(header, normalized_prompt):
                matched_fields.append(header)
        if not matched_fields:
            continue
        score = len(matched_fields) * 100 - len(headers)
        if score > best_score:
            best_score = score
            best_fields = matched_fields
            best_headers = headers
    return (best_fields, best_headers)


def _table_header_appears_in_prompt(header: str, normalized_prompt: str) -> bool:
    for alias in _iter_field_aliases(header):
        if _field_name_appears_in_prompt(alias, normalized_prompt):
            return True
    return False


def _iter_field_aliases(field: str) -> list[str]:
    text = str(field or "").strip().strip(":：")
    if not text:
        return []

    aliases: list[str] = []

    def append(value: str) -> None:
        normalized = str(value or "").strip().strip(":：")
        if not normalized:
            return
        alias_key = _normalize_field_alias(normalized)
        if not alias_key:
            return
        if any(_normalize_field_alias(item) == alias_key for item in aliases):
            return
        aliases.append(normalized)

    append(text)
    for part in re.split(r"[/、,，|;；()（）\[\]【】]+", text):
        append(part)
    for chinese_part in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        append(chinese_part)
    for english_part in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*)*", text):
        if len(_normalize_field_alias(english_part)) >= 3:
            append(english_part)
    return aliases



def _score_table_block_against_prompt_fields(
    *,
    block: dict[str, Any],
    expected_field_groups: list[set[str]],
) -> int:
    table_content = str(block.get("content") or "").strip()
    if not table_content:
        return 0

    header_rows, data_rows = _split_html_table_rows(table_content)
    candidate_rows = [*header_rows, *(data_rows[:4] if data_rows else [])]
    header_cells: list[str] = []
    for row_html in candidate_rows:
        header_cells.extend(_extract_html_row_cells(row_html))
    normalized_headers = [cell.strip() for cell in header_cells if cell.strip()]
    if not normalized_headers:
        return 0

    score = 0
    for aliases in expected_field_groups:
        if any(alias in header for alias in aliases for header in normalized_headers):
            score += 1
    return score


def _score_row_cells_against_prompt_fields(
    row_cells: list[str],
    expected_field_groups: list[set[str]],
) -> int:
    normalized_cells = [cell.strip() for cell in row_cells if cell.strip()]
    if not normalized_cells:
        return 0
    score = 0
    for aliases in expected_field_groups:
        if any(alias in cell for aliases_item in [aliases] for alias in aliases_item for cell in normalized_cells):
            score += 1
    return score


def _resolve_prompt_field_header_indexes(
    *,
    header_cells: list[str],
    expected_field_groups: list[set[str]],
) -> list[int | None]:
    normalized_headers = [cell.strip() for cell in header_cells]
    used_indexes: set[int] = set()
    resolved_indexes: list[int | None] = []

    for aliases in expected_field_groups:
        best_index: int | None = None
        best_score = -1
        for index, header in enumerate(normalized_headers):
            if index in used_indexes or not header:
                continue
            score = 0
            for alias in aliases:
                normalized_alias = alias.strip()
                if not normalized_alias:
                    continue
                if header == normalized_alias:
                    score = max(score, 1000 + len(normalized_alias))
                elif normalized_alias in header or header in normalized_alias:
                    score = max(score, 100 + len(normalized_alias))
            if score > best_score:
                best_score = score
                best_index = index
        if best_score <= 0:
            resolved_indexes.append(None)
            continue
        resolved_indexes.append(best_index)
        if best_index is not None:
            used_indexes.add(best_index)
    return resolved_indexes


def _derive_header_cells_from_input_rows(
    *,
    input_rows: list[dict[str, Any]],
    expected_field_groups: list[set[str]],
) -> list[str]:
    best_cells: list[str] = []
    best_score = 0

    for row in input_rows:
        if not isinstance(row, dict):
            continue
        cells = [str(cell).strip() for cell in row.get("cells") or [] if str(cell).strip()]
        if not cells:
            continue
        score = _score_row_cells_against_prompt_fields(
            row_cells=cells,
            expected_field_groups=expected_field_groups,
        )
        if score > best_score:
            best_score = score
            best_cells = cells

    return best_cells if best_score > 0 else []


def _dedupe_table_input_rows(input_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int]] = set()
    for row in sorted(input_rows, key=lambda item: int(item.get("rowIndex") or 0) if isinstance(item, dict) else 0):
        if not isinstance(row, dict):
            continue
        anchor = str(row.get("anchor") or "").strip()
        row_index = int(row.get("rowIndex") or 0)
        dedupe_key = (anchor, row_index)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped_rows.append(row)
    return deduped_rows


def _dedupe_row_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped_decisions: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int]] = set()
    # 保持 rowIndex 升序，且后出现的覆盖先出现的（或者简单去重）
    for decision in sorted(decisions, key=lambda item: int(item.get("rowIndex") or 0) if isinstance(item, dict) else 0):
        if not isinstance(decision, dict):
            continue
        anchor = str(decision.get("anchor") or "").strip()
        row_index = int(decision.get("rowIndex") or 0)
        dedupe_key = (anchor, row_index)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped_decisions.append(decision)
    return deduped_decisions


def _derive_canonical_table_headers(
    *,
    input_rows: list[dict[str, Any]],
    header_cells: list[str],
    expected_field_groups: list[set[str]],
    row_decisions: list[dict[str, Any]] | None = None,
) -> list[str]:
    derived_headers = _derive_header_cells_from_input_rows(
        input_rows=input_rows,
        expected_field_groups=expected_field_groups,
    )
    if len(derived_headers) >= 2:
        return derived_headers

    first_kept_row_index = min(
        (
            int(decision.get("rowIndex") or 0)
            for decision in row_decisions or []
            if isinstance(decision, dict) and str(decision.get("decision") or "").strip() != "skip"
        ),
        default=0,
    )

    best_candidate: list[str] = []
    best_score = -1
    for row in input_rows:
        if not isinstance(row, dict):
            continue
        row_index = int(row.get("rowIndex") or 0)
        if first_kept_row_index and row_index >= first_kept_row_index:
            continue
        cells = [str(cell).strip() for cell in row.get("cells") or [] if str(cell).strip()]
        if len(cells) < 2:
            continue
        score = len(cells)
        if not _row_looks_like_business_data(cells):
            score += 100
        score += _score_row_cells_against_prompt_fields(
            row_cells=cells,
            expected_field_groups=expected_field_groups,
        ) * 50
        if score > best_score:
            best_score = score
            best_candidate = cells

    if len(best_candidate) >= 2:
        return best_candidate

    return [str(cell).strip() for cell in header_cells if str(cell).strip()]


def _derive_full_canonical_rows_from_input_rows(
    *,
    row_decisions: list[dict[str, Any]],
    input_rows: list[dict[str, Any]],
) -> list[list[str]]:
    input_row_by_anchor: dict[str, dict[str, Any]] = {}
    input_row_by_index: dict[int, dict[str, Any]] = {}
    for row in input_rows:
        if not isinstance(row, dict):
            continue
        anchor = str(row.get("anchor") or "").strip()
        row_index = int(row.get("rowIndex") or 0)
        if anchor:
            input_row_by_anchor[anchor] = row
        if row_index:
            input_row_by_index[row_index] = row

    canonical_rows: list[list[str]] = []
    for decision in sorted(row_decisions, key=lambda item: int(item.get("rowIndex") or 0) if isinstance(item, dict) else 0):
        if not isinstance(decision, dict):
            continue
        decision_type = str(decision.get("decision") or "").strip()
        if decision_type == "skip":
            continue

        anchor = str(decision.get("anchor") or "").strip()
        row_index = int(decision.get("rowIndex") or 0)
        input_row = input_row_by_anchor.get(anchor) or input_row_by_index.get(row_index)
        if not isinstance(input_row, dict):
            continue

        row_cells = [str(cell).strip() for cell in input_row.get("cells") or []]
        if not any(row_cells):
            continue

        if decision_type == "merge_prev" and canonical_rows:
            previous = canonical_rows[-1]
            if len(previous) < len(row_cells):
                previous.extend([""] * (len(row_cells) - len(previous)))
            for index, value in enumerate(row_cells):
                if not value:
                    continue
                previous_value = previous[index]
                if not previous_value:
                    previous[index] = value
                elif value not in previous_value.split("\n"):
                    previous[index] = f"{previous_value}\n{value}"
            continue

        canonical_rows.append(row_cells)

    deduped_rows: list[list[str]] = []
    seen_rows: set[tuple[str, ...]] = set()
    for row in canonical_rows:
        dedupe_key = tuple(row)
        if dedupe_key in seen_rows:
            continue
        seen_rows.add(dedupe_key)
        deduped_rows.append(row)
    return deduped_rows


def _project_expected_field_table_from_input_rows(
    *,
    row_decisions: list[dict[str, Any]],
    input_rows: list[dict[str, Any]],
    expected_fields: list[str],
    column_semantic_anchor: dict[str, Any] | None,
    header_cells: list[str],
    mode_prompt: str,
) -> dict[str, Any] | None:
    normalized_fields = [str(field).strip() for field in expected_fields if str(field).strip()]
    if not normalized_fields:
        return None

    field_indexes = _resolve_expected_field_source_indexes(
        expected_fields=normalized_fields,
        column_semantic_anchor=column_semantic_anchor,
        header_cells=header_cells,
        mode_prompt=mode_prompt,
    )
    if not any(index is not None for index in field_indexes):
        return None

    input_row_by_anchor: dict[str, dict[str, Any]] = {}
    input_row_by_index: dict[int, dict[str, Any]] = {}
    for row in input_rows:
        if not isinstance(row, dict):
            continue
        anchor = str(row.get("anchor") or "").strip()
        row_index = int(row.get("rowIndex") or 0)
        if anchor:
            input_row_by_anchor[anchor] = row
        if row_index:
            input_row_by_index[row_index] = row

    projected_rows: list[list[str]] = []
    normalized_decisions: list[dict[str, Any]] = []
    for decision in sorted(row_decisions, key=lambda item: int(item.get("rowIndex") or 0) if isinstance(item, dict) else 0):
        if not isinstance(decision, dict):
            continue
        normalized_decision = dict(decision)
        decision_type = str(decision.get("decision") or "").strip()
        if decision_type == "skip":
            normalized_decision["resultRow"] = None
            normalized_decisions.append(normalized_decision)
            continue

        anchor = str(decision.get("anchor") or "").strip()
        row_index = int(decision.get("rowIndex") or 0)
        input_row = input_row_by_anchor.get(anchor) or input_row_by_index.get(row_index)
        row_cells = [str(cell).strip() for cell in (input_row.get("cells") or [])] if isinstance(input_row, dict) else []
        extracted_cells = [
            row_cells[index] if index is not None and index < len(row_cells) else ""
            for index in field_indexes
        ]
        if not any(extracted_cells):
            result_row = decision.get("resultRow")
            result_values = result_row.get("values") if isinstance(result_row, dict) else None
            if isinstance(result_values, list) and len(result_values) == len(normalized_fields):
                extracted_cells = [str(value).strip() for value in result_values]
        if not any(extracted_cells):
            normalized_decisions.append(normalized_decision)
            continue

        label = extracted_cells[0] or str((decision.get("resultRow") or {}).get("label") if isinstance(decision.get("resultRow"), dict) else "").strip()
        if not label:
            label = f"Row_{row_index or len(normalized_decisions) + 1}"
        normalized_decision["resultRow"] = {"label": label, "values": extracted_cells}
        normalized_decisions.append(normalized_decision)

        if decision_type == "merge_prev" and projected_rows:
            previous = projected_rows[-1]
            for index, value in enumerate(extracted_cells):
                if not value:
                    continue
                previous_value = previous[index]
                if not previous_value:
                    previous[index] = value
                elif value not in previous_value.split("\n"):
                    previous[index] = f"{previous_value}\n{value}"
            continue
        projected_rows.append(extracted_cells)

    if not projected_rows:
        return None
    return {
        "headers": normalized_fields,
        "rows": projected_rows,
        "rowDecisions": normalized_decisions,
    }


def _project_expected_field_table_from_parser_result(
    *,
    parser_result: Any,
    expected_fields: list[str],
    mode_prompt: str,
) -> dict[str, Any] | None:
    normalized_fields = [str(field).strip() for field in expected_fields if str(field).strip()]
    if not isinstance(parser_result, dict) or not normalized_fields:
        return None

    field_groups = _extract_prompt_field_keyword_groups(mode_prompt)
    if not field_groups:
        field_groups = _build_field_keyword_groups_from_fields(normalized_fields)
    if not field_groups:
        return None

    best_segments: list[tuple[list[int | None], list[list[str]]]] = []
    best_score = 0
    required_matches = min(len(normalized_fields), 2)
    for segment in parser_result.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("kind") or segment.get("segmentType") or "").strip() != "records":
            continue
        headers = [str(item).strip() for item in segment.get("headers") or [] if str(item).strip()]
        rows = [
            [str(cell).strip() for cell in row]
            for row in segment.get("rows") or []
            if isinstance(row, list) and any(str(cell).strip() for cell in row)
        ]
        if not headers or not rows:
            continue
        field_indexes = _resolve_prompt_field_header_indexes(
            header_cells=headers,
            expected_field_groups=field_groups,
        )
        matched_count = sum(1 for index in field_indexes if index is not None)
        if matched_count < required_matches:
            continue
        score = matched_count * 100 - len(headers)
        if score > best_score:
            best_score = score
            best_segments = [(field_indexes, rows)]
        elif score == best_score:
            best_segments.append((field_indexes, rows))

    if not best_segments:
        return None

    projected_rows: list[list[str]] = []
    for field_indexes, rows in best_segments:
        for row in rows:
            projected = [
                row[index] if index is not None and index < len(row) else ""
                for index in field_indexes
            ]
            if any(projected):
                projected_rows.append(projected)

    if not projected_rows:
        return None
    return {"headers": normalized_fields, "rows": projected_rows}


def _resolve_expected_field_source_indexes(
    *,
    expected_fields: list[str],
    column_semantic_anchor: dict[str, Any] | None,
    header_cells: list[str],
    mode_prompt: str,
) -> list[int | None]:
    indexes: list[int | None] = []
    source_headers = list(header_cells)
    if isinstance(column_semantic_anchor, dict):
        anchor_headers = [
            str(item).strip()
            for item in column_semantic_anchor.get("sourceHeaders") or []
            if str(item).strip()
        ]
        if anchor_headers:
            source_headers = anchor_headers
        mapping = column_semantic_anchor.get("targetFieldToSourceColumn")
        if isinstance(mapping, dict):
            for field in expected_fields:
                raw_index = mapping.get(field)
                try:
                    parsed_index = int(raw_index)
                except (TypeError, ValueError):
                    indexes.append(None)
                    continue
                indexes.append(parsed_index - 1 if parsed_index > 0 else None)
            if any(index is not None for index in indexes):
                return indexes

    field_groups = _extract_prompt_field_keyword_groups(mode_prompt)
    if not field_groups:
        field_groups = _build_field_keyword_groups_from_fields(expected_fields)
    if source_headers and field_groups:
        return _resolve_prompt_field_header_indexes(
            header_cells=source_headers,
            expected_field_groups=field_groups,
        )
    return [None for _ in expected_fields]


def _should_prefer_semantic_result_rows(
    *,
    expected_fields: list[str],
    result_rows: list[Any],
    input_rows: list[dict[str, Any]],
    parser_result: Any,
) -> bool:
    normalized_result_rows = [row for row in result_rows if isinstance(row, dict) and isinstance(row.get("values"), list)]
    if not normalized_result_rows:
        return False
    if expected_fields:
        return False
    if not input_rows:
        return not isinstance(parser_result, dict)

    result_widths = [
        len([value for value in row.get("values") or [] if str(value).strip()])
        for row in normalized_result_rows
    ]
    input_widths = [
        len([cell for cell in row.get("cells") or [] if str(cell).strip()])
        for row in input_rows
        if isinstance(row, dict)
    ]
    max_result_width = max(result_widths, default=0)
    max_input_width = max(input_widths, default=0)
    return max_result_width > 0 and max_input_width > max_result_width


def _derive_semantic_result_headers(
    *,
    result_rows: list[Any],
    expected_fields: list[str],
) -> list[str]:
    if expected_fields:
        return expected_fields
    max_width = max(
        (
            len(row.get("values") or [])
            for row in result_rows
            if isinstance(row, dict) and isinstance(row.get("values"), list)
        ),
        default=0,
    )
    if max_width <= 1:
        return ["提取结果"]
    return [f"值{index}" for index in range(1, max_width + 1)]


def _derive_header_cells_from_header_rows(
    *,
    header_rows: list[str],
    expected_field_groups: list[set[str]],
) -> list[str]:
    best_cells: list[str] = []
    best_score = 0

    for row_html in header_rows:
        cells = [str(cell).strip() for cell in _extract_html_row_cells(row_html) if str(cell).strip()]
        if not cells or _row_looks_like_business_data(cells):
            continue
        score = _score_row_cells_against_prompt_fields(
            row_cells=cells,
            expected_field_groups=expected_field_groups,
        )
        if score > best_score:
            best_score = score
            best_cells = cells

    return best_cells if best_score > 0 else []


def _row_looks_like_business_data(cells: list[str]) -> bool:
    if not cells:
        return False
    first_cell = str(cells[0]).strip()
    if re.fullmatch(r"\d+", first_cell):
        return True

    numeric_like_count = sum(1 for cell in cells if re.search(r"\d", str(cell)))
    return numeric_like_count >= max(2, len(cells) // 2)





def _split_html_table_rows(table_html: str) -> tuple[list[str], list[str]]:
    rows = re.findall(r"<tr\b[^>]*>[\s\S]*?</tr>", table_html, flags=re.IGNORECASE)
    if not rows:
        return ([], [])
    header_rows: list[str] = []
    data_rows: list[str] = []
    seen_data_row = False
    for row_html in rows:
        if re.search(r"<th\b", row_html, flags=re.IGNORECASE) and not seen_data_row:
            header_rows.append(row_html)
            continue
        if re.search(r"<td\b", row_html, flags=re.IGNORECASE):
            cells = [str(cell).strip() for cell in _extract_html_row_cells(row_html) if str(cell).strip()]
            if not seen_data_row and cells and not _row_looks_like_business_data(cells):
                header_rows.append(row_html)
                continue
            seen_data_row = True
            data_rows.append(row_html)
            continue
        if not seen_data_row:
            header_rows.append(row_html)
    return (header_rows, data_rows)


def _rebuild_html_table(*, original_html: str, header_rows: list[str], data_rows: list[str]) -> str:
    table_open_match = re.search(r"<table\b[^>]*>", original_html, flags=re.IGNORECASE)
    table_open = table_open_match.group(0) if table_open_match else "<table>"
    body = "\n".join([*header_rows, *data_rows]).strip()
    return f"{table_open}\n{body}\n</table>"


def _extract_row_anchor_from_html_row(row_html: str, *, fallback_index: int, block_id: str) -> str:
    _ = row_html
    prefix = block_id or "table"
    return f"{prefix}:_row_{fallback_index}"


def _extract_html_row_cells(row_html: str) -> list[str]:
    cells = re.findall(r"<t[dh]\b[^>]*>([\s\S]*?)</t[dh]>", row_html, flags=re.IGNORECASE)
    return [_strip_html_tags(unescape(cell)).strip() for cell in cells]


def _build_table_input_rows(
    *,
    chunk_rows: list[str],
    row_offset: int,
    block_id: str,
) -> list[dict[str, Any]]:
    input_rows: list[dict[str, Any]] = []
    for index, row_html in enumerate(chunk_rows):
        anchor = _extract_row_anchor_from_html_row(
            row_html,
            fallback_index=row_offset + index + 1,
            block_id=block_id,
        )
        input_rows.append(
            {
                "anchor": anchor,
                "rowIndex": row_offset + index + 1,
                "rowHtml": row_html,
                "cells": _extract_html_row_cells(row_html),
            }
        )
    return input_rows


def _get_payload_merge_meta(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("_solo_meta")
    return meta if isinstance(meta, dict) else {}


def _get_table_row_chunk_group_key(meta: dict[str, Any]) -> str:
    if meta.get("sourceMode") != "table" or meta.get("chunkStrategy") not in {
        "table_rows",
        "batch_windows",
        "parser_only",
        "parser_enrichment",
    }:
        return ""
    return str(meta.get("sourceBlockId") or meta.get("sourceBlockTitle") or "")


def _extract_custom_result_scalar_fields(parsed_result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in parsed_result.items()
        if key
        not in {
            "rowDecisions",
            "rows",
            "canonicalTable",
            "kvPairs",
            "total_rows",
            "totalRows",
            "markdown_table",
            "markdownTable",
            "markdown",
            "table_markdown",
            "tableMarkdown",
            "table_data",
            "tableData",
            "parserVersion",
            "tableRole",
            "logicalGrid",
            "cellGrid",
            "cells",
            "segments",
            "displayTable",
            "parseWarnings",
        }
    }


def _dedupe_kv_pair_payloads(pairs: list[Any]) -> list[dict[str, Any]]:
    normalized_pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int]] = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        key = str(pair.get("key") or "").strip().strip(":：")
        value = str(pair.get("value") or "").strip()
        if not key or not value:
            continue
        source_anchor = str(pair.get("sourceAnchor") or "").strip()
        try:
            row_index = int(pair.get("rowIndex") or 0)
        except (TypeError, ValueError):
            row_index = 0
        dedupe_key = (key, value, source_anchor, row_index)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_pair: dict[str, Any] = {"key": key, "value": value}
        if source_anchor:
            normalized_pair["sourceAnchor"] = source_anchor
        if row_index:
            normalized_pair["rowIndex"] = row_index
        normalized_pairs.append(normalized_pair)
    return normalized_pairs


def _merge_parser_result_into_custom_result(
    custom_result: dict[str, Any],
    parser_result: Any,
    *,
    prefer_parser_table: bool = True,
) -> dict[str, Any]:
    if not isinstance(parser_result, dict):
        return custom_result

    merged = dict(custom_result)
    for key in (
        "parserVersion",
        "title",
        "tableRole",
        "logicalGrid",
        "cellGrid",
        "cells",
        "segments",
        "parseWarnings",
    ):
        if key in parser_result:
            merged[key] = parser_result.get(key)

    parser_table = parser_result.get("displayTable") or parser_result.get("canonicalTable")
    if isinstance(parser_table, dict):
        has_result_table = isinstance(merged.get("canonicalTable"), dict) or isinstance(merged.get("displayTable"), dict)
        if prefer_parser_table or not has_result_table:
            merged["displayTable"] = parser_table
            merged["canonicalTable"] = parser_table
            rows = parser_table.get("rows")
            if isinstance(rows, list):
                merged["total_rows"] = len(rows)
        else:
            merged["sourceTable"] = parser_table

    parser_pairs = parser_result.get("kvPairs")
    if isinstance(parser_pairs, list) and parser_pairs:
        existing_pairs = merged.get("kvPairs") if isinstance(merged.get("kvPairs"), list) else []
        merged["kvPairs"] = _dedupe_kv_pair_payloads([*parser_pairs, *existing_pairs])

    return merged


def _merge_custom_result_scalars(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key, value in source.items():
        if key not in target:
            target[key] = value
            continue
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged_dict = dict(current)
            for nested_key, nested_value in value.items():
                if nested_key not in merged_dict or merged_dict[nested_key] in (None, "", [], {}):
                    merged_dict[nested_key] = nested_value
            target[key] = merged_dict
            continue
        if current in (None, "", [], {}) and value not in (None, "", [], {}):
            target[key] = value
    return target


def _merge_standalone_custom_results(
    values: list[Any],
    *,
    requested_fields: list[str],
) -> Any:
    merged: dict[str, Any] = {}
    passthrough_values: list[Any] = []

    for value in values:
        normalized_value = _normalize_custom_result_for_requested_fields(
            value,
            requested_fields=requested_fields,
        )
        if isinstance(normalized_value, dict):
            merged = _merge_custom_result_scalars(merged, normalized_value)
        elif normalized_value is not None:
            passthrough_values.append(normalized_value)

    if requested_fields and merged:
        for field in requested_fields:
            merged.setdefault(field, None)
        ordered = {field: merged.get(field) for field in requested_fields}
        for key, value in merged.items():
            if key not in ordered:
                ordered[key] = value
        merged = ordered

    if merged and passthrough_values:
        return [merged, *passthrough_values]
    if merged:
        return merged
    if len(passthrough_values) == 1:
        return passthrough_values[0]
    return passthrough_values or None


def _normalize_custom_result_for_requested_fields(value: Any, *, requested_fields: list[str]) -> Any:
    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item_value in value.items():
        normalized_key = str(key or "").strip()
        if requested_fields:
            matched_field = _match_requested_field_alias(normalized_key, requested_fields)
            if not matched_field:
                continue
            normalized_key = matched_field
        if not normalized_key:
            continue
        normalized[normalized_key] = item_value
    return normalized


def _extract_requested_text_field_names(
    *,
    mode_prompt: str,
    blocks: list[Any],
) -> list[str]:
    explicit_fields = _extract_prompt_field_names(mode_prompt)
    if explicit_fields:
        return explicit_fields

    normalized_prompt = re.sub(r"\s+", " ", str(mode_prompt or "").strip())
    if not normalized_prompt:
        return []

    requested_fields: list[str] = []
    for label in _extract_kv_labels_from_blocks(blocks):
        if _field_name_appears_in_prompt(label, normalized_prompt):
            requested_fields.append(label)
    return requested_fields


def _merge_requested_field_names(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    seen = {_normalize_field_alias(field) for field in merged}
    for field in incoming:
        normalized = _normalize_field_alias(field)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(field)
    return merged


def _extract_kv_labels_from_blocks(blocks: list[Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for text in (str(block.get("title") or ""), str(block.get("content") or "")):
            for line in re.split(r"[\n\r]+", text):
                match = re.match(r"^\s*([^:：]{1,32})[:：]\s*(.+?)\s*$", line)
                if not match:
                    continue
                label = match.group(1).strip()
                normalized = _normalize_field_alias(label)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                labels.append(label)
    return labels


def _field_name_appears_in_prompt(field: str, normalized_prompt: str) -> bool:
    normalized_field = _normalize_field_alias(field)
    if not normalized_field:
        return False
    prompt_tokens = {
        _normalize_field_alias(token)
        for token in re.split(r"[、,，/|;；:：\s]+", normalized_prompt)
        if _normalize_field_alias(token)
    }
    if normalized_field in prompt_tokens:
        return True
    compact_prompt = _normalize_field_alias(normalized_prompt)
    return normalized_field in compact_prompt


def _extract_requested_text_fields_from_blocks(
    *,
    blocks: list[Any],
    requested_fields: list[str],
) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        texts = [
            str(block.get("title") or ""),
            str(block.get("content") or ""),
        ]
        for text in texts:
            for line in re.split(r"[\n\r]+", text):
                match = re.match(r"^\s*([^:：]{1,32})[:：]\s*(.+?)\s*$", line)
                if not match:
                    continue
                raw_key = match.group(1).strip()
                value = match.group(2).strip()
                field = _match_requested_field_alias(raw_key, requested_fields)
                if not field or not value:
                    continue
                if extracted.get(field) in (None, "", [], {}):
                    extracted[field] = value
    return extracted


def _label_matches_requested_field(label: str, requested_fields: list[str]) -> bool:
    return bool(_match_requested_field_alias(label, requested_fields))


def _match_requested_field_alias(value: str, requested_fields: list[str]) -> str:
    normalized_value = _normalize_field_alias(value)
    if not normalized_value:
        return ""

    for field in requested_fields:
        normalized_field = _normalize_field_alias(field)
        if normalized_value == normalized_field:
            return field
    return ""


def _normalize_field_alias(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").strip().strip(":：").lower())


def _looks_like_kv_key(value: str) -> bool:
    normalized = str(value or "").strip().strip(":：")
    if not normalized:
        return False
    if len(normalized) > 32:
        return False
    if re.fullmatch(r"[\d.\-/%]+", normalized):
        return False

    digit_count = sum(1 for char in normalized if char.isdigit())
    if digit_count >= max(3, len(normalized) // 2):
        return False
    return True


def _normalize_kv_pairs(pairs: Any, *, source_anchor: str = "", row_index: int = 0) -> list[dict[str, Any]]:
    normalized_pairs: list[dict[str, Any]] = []
    if not isinstance(pairs, list):
        return normalized_pairs

    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        key = str(pair.get("key") or "").strip().strip(":：")
        value = str(pair.get("value") or "").strip()
        if not key or not value:
            continue
        normalized_pair = {"key": key, "value": value}
        pair_anchor = str(pair.get("sourceAnchor") or source_anchor).strip()
        if pair_anchor:
            normalized_pair["sourceAnchor"] = pair_anchor
        pair_row_index = int(pair.get("rowIndex") or row_index or 0)
        if pair_row_index:
            normalized_pair["rowIndex"] = pair_row_index
        normalized_pairs.append(normalized_pair)
    return normalized_pairs


def _derive_kv_pairs_from_row_decisions(
    decisions: list[dict[str, Any]],
    *,
    input_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    input_row_by_anchor: dict[str, dict[str, Any]] = {}
    input_row_by_index: dict[int, dict[str, Any]] = {}
    for row in input_rows or []:
        if not isinstance(row, dict):
            continue
        anchor = str(row.get("anchor") or "").strip()
        row_index = int(row.get("rowIndex") or 0)
        if anchor:
            input_row_by_anchor[anchor] = row
        if row_index:
            input_row_by_index[row_index] = row

    derived_pairs: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        if str(decision.get("decision") or "").strip() == "skip":
            continue
        anchor = str(decision.get("anchor") or "").strip()
        row_index = int(decision.get("rowIndex") or 0)
        result_row = decision.get("resultRow")
        if not isinstance(result_row, dict):
            continue

        normalized_pairs = _normalize_kv_pairs(
            result_row.get("pairs"),
            source_anchor=anchor,
            row_index=row_index,
        )
        if not normalized_pairs:
            input_row = input_row_by_anchor.get(anchor) or input_row_by_index.get(row_index)
            row_cells = [
                str(cell).strip()
                for cell in (input_row.get("cells") or [] if isinstance(input_row, dict) else [])
                if str(cell).strip()
            ]
            if len(row_cells) >= 2 and len(row_cells) % 2 == 0:
                candidate_pairs: list[dict[str, Any]] = []
                for index in range(0, len(row_cells), 2):
                    key = row_cells[index].strip().strip(":：")
                    value = row_cells[index + 1].strip()
                    if not _looks_like_kv_key(key) or not value:
                        candidate_pairs = []
                        break
                    candidate_pairs.append(
                        {
                            "key": key,
                            "value": value,
                            "sourceAnchor": anchor,
                            "rowIndex": row_index,
                        }
                    )
                normalized_pairs = candidate_pairs

        if not normalized_pairs:
            label = str(result_row.get("label") or "").strip().strip(":：")
            values = [str(value).strip() for value in result_row.get("values") or [] if str(value).strip()]
            if _looks_like_kv_key(label) and len(values) == 1:
                if _normalize_field_alias(label) == _normalize_field_alias(values[0]):
                    continue
                normalized_pairs = [
                    {
                        "key": label,
                        "value": values[0],
                        "sourceAnchor": anchor,
                        "rowIndex": row_index,
                    }
                ]

        for pair in normalized_pairs:
            key = str(pair.get("key") or "").strip()
            value = str(pair.get("value") or "").strip()
            pair_anchor = str(pair.get("sourceAnchor") or anchor).strip()
            if not key or not value:
                continue
            dedupe_key = (key, value, pair_anchor)
            if dedupe_key in seen_pairs:
                continue
            seen_pairs.add(dedupe_key)
            derived_pairs.append(pair)

    return derived_pairs


def _merge_table_chunk_custom_results(payloads: list[dict[str, Any]]) -> dict[str, Any] | str | None:
    if not payloads:
        return None
        
    ordered_payloads = sorted(payloads, key=lambda item: int(item.get("chunkIndex") or 0))
    first_payload = ordered_payloads[0]
    meta = _get_payload_merge_meta(first_payload)
    parser_result = meta.get("parserResult") if isinstance(meta.get("parserResult"), dict) else None

    column_semantic_anchor = meta.get("columnSemanticAnchor")
    fallback_headers = [str(item).strip() for item in meta.get("headerCells") or [] if str(item).strip()]
    if not fallback_headers:
        if isinstance(column_semantic_anchor, dict):
            fallback_headers = [
                str(item).strip()
                for item in column_semantic_anchor.get("sourceHeaders") or []
                if str(item).strip()
            ]
    
    if meta.get("chunkStrategy") == "batch_windows":
        all_decisions = []
        merged_scalars: dict[str, Any] = {}
        fallback_rows: list[Any] = []
        fallback_canonical_headers: list[str] = []
        fallback_canonical_rows: list[list[Any]] = []
        expected_fields = [str(item).strip() for item in meta.get("expectedFields") or [] if str(item).strip()]
        input_rows: list[dict[str, Any]] = []
        for payload in ordered_payloads:
            payload_meta = _get_payload_merge_meta(payload)
            for row in payload_meta.get("inputRows") or []:
                if isinstance(row, dict):
                    input_rows.append(row)
        input_rows = _dedupe_table_input_rows(input_rows)
        expected_field_groups = _extract_prompt_field_keyword_groups(str(meta.get("modePrompt") or ""))
        for payload in ordered_payloads:
            parsed_result = _normalize_custom_result_payload(payload.get("customResult"))
            if isinstance(parsed_result, dict):
                merged_scalars = _merge_custom_result_scalars(
                    merged_scalars,
                    _extract_custom_result_scalar_fields(parsed_result),
                )
                canonical_table = parsed_result.get("canonicalTable")
                if isinstance(canonical_table, dict):
                    headers = canonical_table.get("headers")
                    rows = canonical_table.get("rows")
                    if not fallback_canonical_headers and isinstance(headers, list):
                        fallback_canonical_headers = [str(item).strip() for item in headers]
                    if isinstance(rows, list):
                        fallback_canonical_rows.extend(row for row in rows if isinstance(row, list))
                row_decisions = parsed_result.get("rowDecisions")
                if isinstance(row_decisions, list) and row_decisions:
                    all_decisions.extend(row_decisions)
                elif isinstance(parsed_result.get("rows"), list):
                    fallback_rows.extend(parsed_result.get("rows") or [])
        
        if all_decisions:
            all_decisions = _dedupe_row_decisions(all_decisions)
            projected_table = _project_expected_field_table_from_parser_result(
                parser_result=parser_result,
                expected_fields=expected_fields,
                mode_prompt=str(meta.get("modePrompt") or ""),
            )
            if projected_table:
                merged_result = dict(merged_scalars)
                merged_result["rowDecisions"] = all_decisions
                merged_result["canonicalTable"] = {
                    "headers": projected_table["headers"],
                    "rows": projected_table["rows"],
                }
                merged_result["total_rows"] = len(projected_table["rows"])
                return _merge_parser_result_into_custom_result(
                    merged_result,
                    parser_result,
                    prefer_parser_table=False,
                )

            projected_table = _project_expected_field_table_from_input_rows(
                row_decisions=all_decisions,
                input_rows=input_rows,
                expected_fields=expected_fields,
                column_semantic_anchor=column_semantic_anchor if isinstance(column_semantic_anchor, dict) else None,
                header_cells=fallback_headers,
                mode_prompt=str(meta.get("modePrompt") or ""),
            )
            if projected_table:
                merged_result = dict(merged_scalars)
                merged_result["rowDecisions"] = projected_table["rowDecisions"]
                merged_result["canonicalTable"] = {
                    "headers": projected_table["headers"],
                    "rows": projected_table["rows"],
                }
                merged_result["total_rows"] = len(projected_table["rows"])
                return _merge_parser_result_into_custom_result(
                    merged_result,
                    parser_result,
                    prefer_parser_table=False,
                )

            merged_rows = []
            for decision in all_decisions:
                dec_type = decision.get("decision")
                if dec_type == "skip":
                    continue
                elif dec_type == "keep":
                    result_row = decision.get("resultRow")
                    if isinstance(result_row, dict):
                        # 避免原地修改导致侧效应，创建 resultRow 的浅拷贝，并对 values 进行拷贝
                        new_row = dict(result_row)
                        if "values" in new_row:
                            new_row["values"] = list(new_row["values"])
                        merged_rows.append(new_row)
                elif dec_type == "merge_prev":
                    if not merged_rows:
                        decision["decision"] = "skip"
                        decision["_warning"] = "orphan_merge_prev_forced_skip"
                    else:
                        result_row = decision.get("resultRow")
                        if isinstance(result_row, dict):
                            last_row = merged_rows[-1]
                            last_values = last_row.get("values", [])
                            new_values = result_row.get("values", [])

                            if isinstance(last_values, list) and isinstance(new_values, list):
                                for i in range(min(len(last_values), len(new_values))):
                                    if new_values[i]:
                                        last_values[i] = str(last_values[i]) + "\n" + str(new_values[i])
                                for i in range(len(last_values), len(new_values)):
                                    last_values.append(new_values[i])
            merged_result = dict(merged_scalars)
            merged_result["rowDecisions"] = all_decisions
            kv_pairs = _derive_kv_pairs_from_row_decisions(all_decisions, input_rows=input_rows)
            if kv_pairs:
                merged_result["kvPairs"] = kv_pairs
            prefer_result_rows = _should_prefer_semantic_result_rows(
                expected_fields=expected_fields,
                result_rows=merged_rows,
                input_rows=input_rows,
                parser_result=parser_result,
            )
            if prefer_result_rows:
                canonical_rows = _derive_canonical_rows_from_result_rows(merged_rows)
                canonical_headers = _derive_semantic_result_headers(
                    result_rows=merged_rows,
                    expected_fields=expected_fields,
                )
            else:
                canonical_headers = _derive_canonical_table_headers(
                    input_rows=input_rows,
                    header_cells=fallback_headers,
                    expected_field_groups=expected_field_groups,
                    row_decisions=all_decisions,
                )
                canonical_rows = _derive_full_canonical_rows_from_input_rows(
                    row_decisions=all_decisions,
                    input_rows=input_rows,
                )
                if not canonical_rows:
                    canonical_rows = _derive_canonical_rows_from_result_rows(merged_rows)
            if canonical_rows:
                merged_result["canonicalTable"] = {
                    "headers": canonical_headers or fallback_canonical_headers or expected_fields or fallback_headers,
                    "rows": canonical_rows,
                }
                merged_result["total_rows"] = len(canonical_rows)
            elif merged_rows:
                merged_result["rows"] = merged_rows
                merged_result["total_rows"] = len(merged_rows)
            return _merge_parser_result_into_custom_result(
                merged_result,
                parser_result,
                prefer_parser_table=not prefer_result_rows,
            )

        total_rows = len(fallback_canonical_rows) if fallback_canonical_rows else len(fallback_rows)
        if fallback_canonical_rows or fallback_rows:
            merged_result = dict(merged_scalars)
            if fallback_canonical_rows:
                merged_result["canonicalTable"] = {
                    "headers": fallback_canonical_headers or fallback_headers,
                    "rows": fallback_canonical_rows,
                }
            if total_rows:
                merged_result["total_rows"] = total_rows
            return _merge_parser_result_into_custom_result(merged_result, parser_result)
        if parser_result:
            return _merge_parser_result_into_custom_result(dict(merged_scalars), parser_result)
        return None

    merged_rows: list[Any] = []
    merged_scalars: dict[str, Any] = {}
    merged_canonical_headers: list[str] = []
    merged_canonical_rows: list[list[Any]] = []

    for payload in ordered_payloads:
        parsed_result = _normalize_custom_result_payload(payload.get("customResult"))
        if isinstance(parsed_result, dict):
            merged_scalars = _merge_custom_result_scalars(
                merged_scalars,
                _extract_custom_result_scalar_fields(parsed_result),
            )
            canonical_table = parsed_result.get("canonicalTable")
            if isinstance(canonical_table, dict):
                headers = canonical_table.get("headers")
                rows = canonical_table.get("rows")
                if not merged_canonical_headers and isinstance(headers, list):
                    merged_canonical_headers = [str(item).strip() for item in headers]
                if isinstance(rows, list):
                    merged_canonical_rows.extend(row for row in rows if isinstance(row, list))
            rows = parsed_result.get("rows")
            if isinstance(rows, list):
                merged_rows.extend(rows)
            continue

    total_rows = len(merged_canonical_rows) if merged_canonical_rows else len(merged_rows)
    if merged_rows or merged_scalars or merged_canonical_rows:
        merged_result = dict(merged_scalars)
        if merged_canonical_rows:
            merged_result["canonicalTable"] = {
                "headers": merged_canonical_headers or fallback_headers,
                "rows": merged_canonical_rows,
            }
        if total_rows:
            merged_result["total_rows"] = total_rows
        return _merge_parser_result_into_custom_result(merged_result, parser_result)
    if parser_result:
        return _merge_parser_result_into_custom_result(dict(merged_scalars), parser_result)
    return None


def _merge_table_chunk_input_meta(payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not payloads:
        return None
    ordered_payloads = sorted(payloads, key=lambda item: int(item.get("chunkIndex") or 0))
    mode_prompt = ""
    source_block_id = ""
    source_block_title = ""
    header_rows: list[str] = []
    header_cells: list[str] = []
    header_mode = ""
    chunk_strategy = ""
    column_semantic_anchor: dict[str, Any] | None = None
    parser_result: dict[str, Any] | None = None
    table_task_mode = ""
    expected_fields: list[str] = []
    expected_field_source = ""
    row_anchors: list[str] = []
    input_rows: list[dict[str, Any]] = []
    row_decisions: list[dict[str, Any]] = []
    
    for payload in ordered_payloads:
        if not mode_prompt:
            mode_prompt = str(payload.get("modePrompt") or "")
        if not source_block_id:
            source_block_id = str(payload.get("sourceBlockId") or "")
        if not source_block_title:
            source_block_title = str(payload.get("sourceBlockTitle") or "")
        if not header_rows:
            header_rows = [str(row) for row in payload.get("headerRows") or [] if str(row).strip()]
        if not header_cells:
            header_cells = [str(cell) for cell in payload.get("headerCells") or [] if str(cell).strip()]
        if not header_mode:
            header_mode = str(payload.get("headerMode") or "").strip()
        if not chunk_strategy:
            chunk_strategy = str(payload.get("chunkStrategy") or "").strip()
        if column_semantic_anchor is None and isinstance(payload.get("columnSemanticAnchor"), dict):
            column_semantic_anchor = dict(payload.get("columnSemanticAnchor") or {})
        if not expected_fields:
            expected_fields = [str(item).strip() for item in payload.get("expectedFields") or [] if str(item).strip()]
        if not expected_field_source:
            expected_field_source = str(payload.get("expectedFieldSource") or "").strip()
        if parser_result is None and isinstance(payload.get("parserResult"), dict):
            parser_result = dict(payload.get("parserResult") or {})
        if not table_task_mode:
            table_task_mode = str(payload.get("tableTaskMode") or "").strip()
        row_anchors.extend(str(anchor) for anchor in payload.get("rowAnchors") or [] if str(anchor).strip())
        for row in payload.get("inputRows") or []:
            if not isinstance(row, dict):
                continue
            input_rows.append(
                {
                    "anchor": str(row.get("anchor") or "").strip(),
                    "rowIndex": int(row.get("rowIndex") or 0),
                    "rowHtml": str(row.get("rowHtml") or ""),
                    "cells": [str(cell) for cell in row.get("cells") or []],
                }
            )
        
        parsed_result = _normalize_custom_result_payload(payload.get("customResult"))
        if isinstance(parsed_result, dict):
            decisions = parsed_result.get("rowDecisions")
            if isinstance(decisions, list):
                row_decisions.extend(decisions)

    if not source_block_id and not source_block_title and not input_rows:
        return None
        
    return {
        "modePrompt": mode_prompt,
        "sourceBlockId": source_block_id,
        "sourceBlockTitle": source_block_title,
        "headerRows": header_rows,
        "headerCells": header_cells,
        "headerMode": header_mode,
        "chunkStrategy": chunk_strategy,
        "columnSemanticAnchor": column_semantic_anchor,
        "expectedFields": expected_fields,
        "expectedFieldSource": expected_field_source,
        "parserResult": parser_result,
        "tableTaskMode": table_task_mode,
        "rowAnchors": row_anchors,
        "inputRows": input_rows,
        "expectedRowCount": len(input_rows),
        "rowDecisions": row_decisions,
    }


def _derive_table_display_from_custom_result(custom_result: Any) -> tuple[int | None, list[dict[str, Any]]]:
    normalized = _normalize_custom_result_payload(custom_result)
    if isinstance(normalized, dict):
        for table_key in ("displayTable", "canonicalTable"):
            table_payload = normalized.get(table_key)
            if isinstance(table_payload, dict):
                canonical_rows = table_payload.get("rows")
                if not isinstance(canonical_rows, list) or not canonical_rows:
                    continue
                preview_rows: list[dict[str, Any]] = []
                for row in canonical_rows[:8]:
                    if not isinstance(row, list):
                        continue
                    cells = [str(cell).strip() for cell in row]
                    if not cells:
                        continue
                    preview_rows.append(
                        {
                            "label": (cells[0] or f"Row {len(preview_rows) + 1}")[:32],
                            "values": cells[1:9],
                        }
                    )
                return (len(canonical_rows), preview_rows)
    if isinstance(normalized, dict):
        rows = normalized.get("rows")
        if isinstance(rows, list) and rows:
            preview_rows = []
            for index, row in enumerate(rows[:8], start=1):
                if not isinstance(row, dict):
                    continue
                if "label" in row and "values" in row and isinstance(row["values"], list):
                    preview_rows.append({
                        "label": str(row.get("label") or f"Row {index}")[:32],
                        "values": [str(v).strip() for v in row["values"]][:8],
                    })
                    continue
                if "label" in row and "values" in row and isinstance(row["values"], dict):
                    preview_rows.append({
                        "label": str(row.get("label") or f"Row {index}")[:32],
                        "values": [str(v).strip() for v in row["values"].values()][:8],
                    })
                    continue
                
                # 泛化兜底：当大模型返回的是平铺字典而非标准的 label/values 结构时
                # 不再通过硬编码字段名猜测行号，统一使用序号作为 label，并将所有非空值作为 values 预览
                label = f"Row {index}"
                values = [str(value).strip() for value in row.values() if str(value).strip()]
                preview_rows.append({"label": label[:32], "values": values[:8]})
            total_rows = _extract_total_rows_from_custom_result(normalized)
            return (total_rows if total_rows is not None else len(rows), preview_rows)

    return (None, [])


def _extract_total_rows_from_custom_result(custom_result: Any) -> int | None:
    if isinstance(custom_result, dict):
        for key in ("total_rows", "totalRows"):
            total_rows = custom_result.get(key)
            if isinstance(total_rows, int):
                return total_rows
    return None


def _normalize_custom_result_payload(custom_result: Any) -> Any:
    if isinstance(custom_result, str):
        trimmed = custom_result.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                return json.loads(trimmed)
            except json.JSONDecodeError:
                return trimmed
        return trimmed
    return custom_result


def _build_markdown_table_from_rows(headers: list[str], rows: list[list[str]]) -> str:
    normalized_headers = [str(header).strip() for header in headers]
    normalized_rows = [[str(cell or "").strip() for cell in row] for row in rows]
    if not normalized_headers or not normalized_rows:
        return ""

    def to_line(cells: list[str]) -> str:
        escaped_cells = [cell.replace("|", "\\|") for cell in cells]
        return f"| {' | '.join(escaped_cells)} |"

    separator = f"| {' | '.join(['---'] * len(normalized_headers))} |"
    lines = [to_line(normalized_headers), separator]
    lines.extend(to_line(row[: len(normalized_headers)]) for row in normalized_rows)
    return "\n".join(lines)


def _normalize_table_custom_result(
    *,
    custom_result: Any,
    table_input: dict[str, Any] | None,
) -> Any:
    if not isinstance(custom_result, dict) or not isinstance(table_input, dict):
        return custom_result

    mode_prompt = str(table_input.get("modePrompt") or "")
    derived_fields = _derive_rule_based_fields(
        custom_result=custom_result,
        table_input=table_input,
    )
    field_names = _extract_prompt_field_names(mode_prompt)
    if not field_names:
        field_names = [str(item).strip() for item in table_input.get("expectedFields") or [] if str(item).strip()]
    field_groups = _extract_prompt_field_keyword_groups(mode_prompt)
    if not field_groups and field_names:
        field_groups = _build_field_keyword_groups_from_fields(field_names)
    existing_requested_table = _extract_existing_requested_canonical_table(
        custom_result=custom_result,
        field_names=field_names,
    )
    if existing_requested_table is not None:
        normalized_result = dict(custom_result)
        if derived_fields:
            existing_derived_fields = normalized_result.get("derivedFields")
            if isinstance(existing_derived_fields, dict):
                normalized_result["derivedFields"] = {**existing_derived_fields, **derived_fields}
            else:
                normalized_result["derivedFields"] = derived_fields
        normalized_result.setdefault("total_rows", len(existing_requested_table["rows"]))
        if _mode_prompt_requests_markdown_table(mode_prompt) and not normalized_result.get("markdown_table"):
            normalized_markdown_table = _build_markdown_table_from_rows(
                existing_requested_table["headers"],
                existing_requested_table["rows"],
            )
            if normalized_markdown_table:
                normalized_result["markdown_table"] = normalized_markdown_table
        return normalized_result
    input_rows = _dedupe_table_input_rows(list(table_input.get("inputRows") or []))
    row_decisions = custom_result.get("rowDecisions")
    if not field_names or not field_groups or not isinstance(input_rows, list) or not isinstance(row_decisions, list):
        if derived_fields:
            normalized_result = dict(custom_result)
            existing_derived_fields = normalized_result.get("derivedFields")
            if isinstance(existing_derived_fields, dict):
                normalized_result["derivedFields"] = {**existing_derived_fields, **derived_fields}
            else:
                normalized_result["derivedFields"] = derived_fields
            return normalized_result
        return custom_result

    header_cells = [str(cell).strip() for cell in table_input.get("headerCells") or [] if str(cell).strip()]
    if not header_cells:
        header_rows = [str(row).strip() for row in table_input.get("headerRows") or [] if str(row).strip()]
        header_cells = _derive_header_cells_from_header_rows(
            header_rows=header_rows,
            expected_field_groups=field_groups,
        )
    if not header_cells:
        column_semantic_anchor = table_input.get("columnSemanticAnchor")
        if isinstance(column_semantic_anchor, dict):
            header_cells = [
                str(cell).strip()
                for cell in column_semantic_anchor.get("sourceHeaders") or []
                if str(cell).strip()
            ]
    if not header_cells:
        header_cells = _derive_header_cells_from_input_rows(
            input_rows=input_rows,
            expected_field_groups=field_groups,
        )
    if not header_cells:
        return custom_result

    field_indexes = _resolve_prompt_field_header_indexes(
        header_cells=header_cells,
        expected_field_groups=field_groups,
    )
    matched_fields = sum(1 for index in field_indexes if index is not None)
    if matched_fields < min(len(field_names), 2):
        return custom_result

    input_row_by_anchor: dict[str, dict[str, Any]] = {}
    input_row_by_index: dict[int, dict[str, Any]] = {}
    for row in input_rows:
        if not isinstance(row, dict):
            continue
        anchor = str(row.get("anchor") or "").strip()
        row_index = int(row.get("rowIndex") or 0)
        if anchor:
            input_row_by_anchor[anchor] = row
        if row_index:
            input_row_by_index[row_index] = row

    canonical_rows: list[list[str]] = []
    normalized_row_decisions: list[dict[str, Any]] = []
    for decision in sorted(row_decisions, key=lambda item: int(item.get("rowIndex") or 0) if isinstance(item, dict) else 0):
        if not isinstance(decision, dict):
            continue
        normalized_decision = dict(decision)
        decision_type = str(decision.get("decision") or "").strip()
        if decision_type == "skip":
            normalized_decision["resultRow"] = None
            normalized_row_decisions.append(normalized_decision)
            continue

        anchor = str(decision.get("anchor") or "").strip()
        row_index = int(decision.get("rowIndex") or 0)
        input_row = input_row_by_anchor.get(anchor) or input_row_by_index.get(row_index)
        if not isinstance(input_row, dict):
            continue

        row_cells = [str(cell).strip() for cell in input_row.get("cells") or []]
        extracted_cells = [
            row_cells[index] if index is not None and index < len(row_cells) else ""
            for index in field_indexes
        ]
        result_row = decision.get("resultRow")
        if isinstance(result_row, dict) and not extracted_cells[0]:
            extracted_cells[0] = str(result_row.get("label") or "").strip()
        if not any(extracted_cells):
            continue

        normalized_result_row = {
            "label": extracted_cells[0] if extracted_cells[0] else f"Row_{row_index or len(normalized_row_decisions) + 1}",
            "values": extracted_cells,
        }
        normalized_decision["resultRow"] = normalized_result_row
        normalized_row_decisions.append(normalized_decision)

        if decision_type == "merge_prev" and canonical_rows:
            previous = canonical_rows[-1]
            for index, value in enumerate(extracted_cells):
                if not value:
                    continue
                previous_value = previous[index]
                if not previous_value:
                    previous[index] = value
                elif value not in previous_value.split("\n"):
                    previous[index] = f"{previous_value}\n{value}"
            continue

        canonical_rows.append(extracted_cells)

    full_canonical_headers = _derive_canonical_table_headers(
        input_rows=input_rows,
        header_cells=header_cells,
        expected_field_groups=field_groups,
        row_decisions=normalized_row_decisions,
    )
    full_canonical_rows = _derive_full_canonical_rows_from_input_rows(
        row_decisions=normalized_row_decisions,
        input_rows=input_rows,
    )

    if not canonical_rows and not full_canonical_rows:
        return custom_result
    if field_names and not canonical_rows:
        return custom_result

    normalized_result = dict(custom_result)
    normalized_result.pop("rows", None)
    normalized_result.pop("markdown_table", None)
    if field_names:
        canonical_table_rows = canonical_rows
        canonical_table_headers = field_names
    else:
        canonical_table_rows = full_canonical_rows or canonical_rows
        canonical_table_headers = full_canonical_headers or field_names
    normalized_result["total_rows"] = len(canonical_table_rows)
    normalized_result["rowDecisions"] = normalized_row_decisions
    if derived_fields:
        existing_derived_fields = normalized_result.get("derivedFields")
        if isinstance(existing_derived_fields, dict):
            normalized_result["derivedFields"] = {**existing_derived_fields, **derived_fields}
        else:
            normalized_result["derivedFields"] = derived_fields
    if _mode_prompt_requests_markdown_table(mode_prompt):
        normalized_markdown_table = _build_markdown_table_from_rows(
            canonical_table_headers,
            canonical_table_rows,
        )
        if normalized_markdown_table:
            normalized_result["markdown_table"] = normalized_markdown_table
    normalized_result["canonicalTable"] = {
        "headers": canonical_table_headers,
        "rows": canonical_table_rows,
    }
    return normalized_result


def _extract_existing_requested_canonical_table(
    *,
    custom_result: dict[str, Any],
    field_names: list[str],
) -> dict[str, list[list[str]] | list[str]] | None:
    if not field_names:
        return None
    canonical_table = custom_result.get("canonicalTable")
    if not isinstance(canonical_table, dict):
        return None
    headers = [str(item).strip() for item in canonical_table.get("headers") or []]
    if [_normalize_field_alias(item) for item in headers] != [_normalize_field_alias(item) for item in field_names]:
        return None
    rows = [
        [str(cell).strip() for cell in row]
        for row in canonical_table.get("rows") or []
        if isinstance(row, list)
    ]
    if not rows:
        return None
    return {"headers": headers, "rows": rows}


def _build_column_semantic_anchor(
    *,
    mode_prompt: str,
    expected_fields: list[str],
    source_headers: list[str],
    source_column_count: int,
) -> dict[str, Any] | None:
    normalized_headers = [str(item).strip() for item in source_headers if str(item).strip()]
    if not normalized_headers:
        return None

    field_groups = _extract_prompt_field_keyword_groups(mode_prompt)
    if not field_groups and expected_fields:
        field_groups = _build_field_keyword_groups_from_fields(expected_fields)
    field_indexes = _resolve_prompt_field_header_indexes(
        header_cells=normalized_headers,
        expected_field_groups=field_groups,
    )
    target_field_to_source_column = {
        field: (field_indexes[index] + 1 if index < len(field_indexes) and field_indexes[index] is not None else None)
        for index, field in enumerate(expected_fields)
    }
    return {
        "sourceColumnCount": max(int(source_column_count or 0), len(normalized_headers)),
        "sourceHeaders": normalized_headers,
        "targetFieldToSourceColumn": target_field_to_source_column,
    }


def _derive_canonical_rows_from_result_rows(result_rows: list[Any]) -> list[list[str]]:
    canonical_rows: list[list[str]] = []
    for row in result_rows:
        if not isinstance(row, dict):
            continue
        values = row.get("values")
        if not isinstance(values, list):
            continue
        canonical_rows.append([str(value).strip() for value in values])
    return canonical_rows


def _extract_kv_pair_value_map(kv_pairs: Any) -> dict[str, list[str]]:
    value_map: dict[str, list[str]] = {}
    if not isinstance(kv_pairs, list):
        return value_map

    for pair in kv_pairs:
        if not isinstance(pair, dict):
            continue
        key = str(pair.get("key") or "").strip().strip(":：")
        value = str(pair.get("value") or "").strip()
        if not key or not value:
            continue
        bucket = value_map.setdefault(key, [])
        if value not in bucket:
            bucket.append(value)
    return value_map


def _pick_first_kv_value(value_map: dict[str, list[str]], *candidate_keys: str) -> str:
    for candidate in candidate_keys:
        normalized_candidate = candidate.strip().strip(":：")
        if not normalized_candidate:
            continue
        for key, values in value_map.items():
            if key == normalized_candidate or normalized_candidate in key or key in normalized_candidate:
                if values:
                    return values[0]
    return ""


def _extract_decimal_from_text(value: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except Exception:
        return None


def _extract_date_string(value: str) -> str:
    match = re.search(r"\b(\d{4})[./-](\d{2})[./-](\d{2})\b", str(value or ""))
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}.{month}.{day}"


def _normalize_signature_date_value(value: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return ""
    date_value = _extract_date_string(normalized)
    if not date_value:
        return normalized
    signature = normalized.replace(date_value, "").strip()
    return f"{signature} {date_value}".strip()


def _derive_rule_based_fields(
    *,
    custom_result: dict[str, Any],
    table_input: dict[str, Any],
) -> dict[str, Any]:
    mode_prompt = str(table_input.get("modePrompt") or "")
    kv_value_map = _extract_kv_pair_value_map(custom_result.get("kvPairs"))
    row_decisions = custom_result.get("rowDecisions") if isinstance(custom_result.get("rowDecisions"), list) else []

    derived_fields: dict[str, Any] = {}
    batch_number = _pick_first_kv_value(kv_value_map, "产品批号", "批号")
    if batch_number:
        derived_fields["batchNumber"] = batch_number

    production_date = _pick_first_kv_value(kv_value_map, "生产日期")
    normalized_production_date = _extract_date_string(production_date)
    if normalized_production_date:
        derived_fields["productionDate"] = normalized_production_date

    actual_yield_text = _pick_first_kv_value(kv_value_map, "实际产量")
    actual_yield_number = _extract_decimal_from_text(actual_yield_text)
    if actual_yield_number is not None:
        try:
            derived_fields["actualYieldValue"] = int(actual_yield_number)
        except Exception:
            pass

    ratio_match = re.search(r"实际产量\s*/\s*(\d+(?:\.\d+)?)", mode_prompt)
    if actual_yield_number is not None and ratio_match:
        try:
            denominator = Decimal(ratio_match.group(1))
            if denominator > 0:
                percent_value = (actual_yield_number / denominator * Decimal("100")).quantize(
                    Decimal("0.1"),
                    rounding=ROUND_HALF_UP,
                )
                derived_fields["yieldRatioPercent"] = f"{percent_value}%"
        except Exception:
            pass

    record_retention_date = _pick_first_kv_value(kv_value_map, "记录保存至")
    normalized_retention_date = _extract_date_string(record_retention_date)
    if normalized_retention_date:
        derived_fields["recordRetentionDate"] = normalized_retention_date

    for decision in row_decisions:
        if not isinstance(decision, dict):
            continue
        result_row = decision.get("resultRow")
        if not isinstance(result_row, dict):
            continue
        label = str(result_row.get("label") or "").strip().strip(":：")
        if not label:
            continue

        normalized_value = ""
        pair_value_map = _extract_kv_pair_value_map(result_row.get("pairs"))
        if pair_value_map:
            signature = _pick_first_kv_value(pair_value_map, "签名")
            date_value = _extract_date_string(_pick_first_kv_value(pair_value_map, "日期"))
            if signature:
                normalized_value = " ".join([part for part in [signature, date_value] if part]).strip()
        if not normalized_value:
            values = [str(item).strip() for item in result_row.get("values") or [] if str(item).strip()]
            normalized_value = _normalize_signature_date_value(" ".join(values))

        if not normalized_value:
            continue
        if label == "车间审核/日期":
            derived_fields["workshopSignatureDate"] = normalized_value
        elif label == "QA审核/日期":
            derived_fields["qaSignatureDate"] = normalized_value

    return derived_fields


def _merge_business_results(
    *,
    payloads: list[dict[str, Any]],
    fallback: Any = None,
) -> dict[str, Any] | None:
    _ = fallback
    if not payloads:
        return None

    normalized_results = [
        _normalize_structured_business_result(payload.get("structured_business_result"))
        for payload in payloads
    ]
    normalized_results = [result for result in normalized_results if result]
    if not normalized_results:
        return None

    issue_groups: dict[str, list[dict[str, Any]]] = {}
    issue_order: list[str] = []

    for result in normalized_results:
        if not result:
            continue
        for index, issue in enumerate(result.get("issues") or []):
            title = str(issue.get("title") or "").strip()
            detail = str(issue.get("detail") or "").strip()
            normalized_title = _normalize_issue_merge_title(title)
            key = normalized_title or title or detail or f"业务审查项 {index + 1}"
            if key not in issue_groups:
                issue_groups[key] = []
                issue_order.append(key)
            issue_groups[key].append(issue)

    if not issue_groups:
        return normalized_results[0]

    merged_issues = [
        _pick_preferred_issue(issue_groups[key], key)
        for key in issue_order
        if issue_groups.get(key)
    ]

    summary = _build_merged_business_summary(merged_issues)
    return {
        "summary": summary or "",
        "riskLevel": _infer_business_risk_level(merged_issues),
        "issueCount": len(merged_issues),
        "issues": merged_issues,
    }


def _pick_preferred_issue(issue_candidates: list[dict[str, Any]], fallback_title: str) -> dict[str, Any]:
    level_rank = {"风险": 4, "关注": 3, "通过": 2, "待确认": 1}

    def sort_key(issue: dict[str, Any]) -> tuple[int, int, int]:
        level = _normalize_issue_level(str(issue.get("level") or "待确认"))
        detail = str(issue.get("detail") or "").strip()
        specificity = _issue_specificity_score(issue, fallback_title)
        return (specificity, level_rank.get(level, 0), len(detail))

    best = max(issue_candidates, key=sort_key)
    detail = _normalize_issue_brief_text(
        best.get("detail"),
        max_length=BUSINESS_ISSUE_DETAIL_MAX_LENGTH,
    )
    suggestion = _normalize_issue_brief_text(
        best.get("suggestion"),
        max_length=BUSINESS_ISSUE_SUGGESTION_MAX_LENGTH,
    ) or None
    return {
        "level": _normalize_issue_level(str(best.get("level") or "待确认")),
        "title": str(best.get("title") or fallback_title).strip()[:80],
        "detail": detail,
        "suggestion": suggestion,
    }


def _normalize_issue_merge_title(title: str) -> str:
    normalized = re.sub(r"\s+", "", str(title or "").strip())
    if not normalized:
        return ""
    normalized = re.sub(r"[：:()（）\[\]【】\-_/|]+", "", normalized)
    normalized = re.sub(r"(范围)?(检查|核查|校验|核验|验证|判定|判断)$", "", normalized)
    return normalized


def _infer_business_risk_level(issues: list[dict[str, Any]]) -> str:
    levels = {_normalize_issue_level(str(issue.get("level") or "")) for issue in issues}
    if "风险" in levels:
        return "风险"
    if "关注" in levels:
        return "关注"
    if "待确认" in levels:
        return "待确认"
    return "通过"


def _build_merged_business_summary(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return ""
    counts = {"通过": 0, "关注": 0, "风险": 0, "待确认": 0}
    for issue in issues:
        counts[_normalize_issue_level(str(issue.get("level") or "待确认"))] += 1
    parts = [f"{counts[level]}条{level}" for level in ["通过", "关注", "风险", "待确认"] if counts[level] > 0]
    return "，".join(parts)


def _issue_specificity_score(issue: dict[str, Any], fallback_title: str) -> int:
    title = str(issue.get("title") or "").strip()
    detail = str(issue.get("detail") or "").strip()
    suggestion = str(issue.get("suggestion") or "").strip()
    score = 0

    if title and not re.fullmatch(r"规则\s*\d+", title):
        score += 2
    if fallback_title and fallback_title not in title:
        score += 1
    if detail and len(detail) >= 12:
        score += 1
    if _contains_concrete_evidence(detail):
        score += 3
    if detail == PASS_ISSUE_DETAIL:
        score += 2
    if detail == PENDING_ISSUE_DETAIL:
        score -= 3
    if "结合当前页抽取字段和证据块逐条核对" in suggestion:
        score -= 3
    if detail == fallback_title or detail == title:
        score -= 2
    return score


def _build_business_detail_from_result(business_result: dict[str, Any] | None) -> str:
    if not business_result:
        return ""
    lines = [str(business_result.get("summary") or "").strip()]
    for issue in (business_result.get("issues") or [])[:4]:
        level = str(issue.get("level") or "").strip()
        title = str(issue.get("title") or "").strip()
        detail = str(issue.get("detail") or "").strip()
        if title and detail:
            lines.append(f"{level} {title}：{detail}")
    return "\n".join(line for line in lines if line)


def _contains_concrete_evidence(detail: str) -> bool:
    if not detail:
        return False
    patterns = [
        r"\d{4}[./-]\d{1,2}[./-]\d{1,2}",
        r"\d+(?:\.\d+)?%",
        r"\d+(?:\.\d+)?(?:万片|片|年|月|日)?",
        r"[A-Za-z]{1,6}-[A-Za-z0-9.-]{2,}",
        r"“[^”]{2,20}”",
    ]
    return any(re.search(pattern, detail) for pattern in patterns) or any(
        token in detail for token in ["依据字段", "判定结论", "需人工核对", "符合要求", "计算", "格式"]
    )


def _is_pending_issue_text(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "需人工核对",
            "需人工复核",
            "证据不足",
            "待确认",
            "待核对",
            "无法核对",
            "未提取到",
            "未提供",
            "未发现",
            "缺失",
        ]
    )


def _is_pass_issue_text(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    return any(token in normalized for token in ["符合", "通过", "无异常", "已完成核对"])


def _normalize_issue_brief_text(value: Any, *, max_length: int) -> str:
    """
    在业务结果边界把 issue 文本收口为短句，避免模型把长解释塞进 detail/suggestion。

    优先保留首个完整短句；如果首句仍然过长，再退化为首个短分句；最后才做硬截断。
    这样可以尽量保留结论语义，同时把展示层长文案职责留在后端合并视图里。
    """

    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if len(text) <= max_length:
        return text

    sentence_candidates = [
        candidate.strip("，,、；;:： ")
        for candidate in re.split(r"[。！？!?；;\n]+", text)
        if candidate.strip("，,、；;:： ")
    ]
    for candidate in sentence_candidates:
        if len(candidate) <= max_length:
            return candidate

    clause_candidates = [
        candidate.strip("，,、；;:： ")
        for candidate in re.split(r"[，,、]+", text)
        if candidate.strip("，,、；;:： ")
    ]
    for candidate in clause_candidates:
        if len(candidate) <= max_length:
            return candidate

    return text[: max_length - 1].rstrip("，,、；;:： ") + "…"


def _normalize_issue_level_from_detail(raw_level: Any, detail: str) -> str:
    level = _normalize_issue_level(str(raw_level or "").strip() or "待确认")
    if level in {"风险", "关注"}:
        return level
    if _is_pass_issue_text(detail):
        return "通过"
    if _is_pending_issue_text(detail):
        return "待确认"
    return level


def _normalize_issue_detail(level: str, detail: Any) -> str:
    brief = _normalize_issue_brief_text(detail, max_length=BUSINESS_ISSUE_DETAIL_MAX_LENGTH)
    if not brief:
        return ""
    if _is_pending_issue_text(brief):
        return PENDING_ISSUE_DETAIL
    if level == "通过" or _is_pass_issue_text(brief):
        return PASS_ISSUE_DETAIL
    return brief


def _normalize_issue_suggestion(level: str, suggestion: Any) -> str | None:
    if level in {"通过", "待确认"}:
        return None
    brief = _normalize_issue_brief_text(suggestion, max_length=BUSINESS_ISSUE_SUGGESTION_MAX_LENGTH)
    if not brief:
        return None
    if brief in {"无需处理", "无需处理。"}:
        return None
    return brief


def _normalize_structured_extraction_result(
    payload: Any,
    fallback: Any = None,
) -> dict[str, Any] | None:
    _ = fallback
    if not isinstance(payload, dict):
        return None

    custom_result = normalize_custom_result_value(payload.get("customResult"))
    basic_info = merge_field_items(
        normalize_field_items(payload.get("basicInfo") or []),
        extract_field_items_from_custom_result(custom_result),
    )
    if is_field_only_custom_result(custom_result):
        custom_result = None

    validation_meta = payload.get("validationMeta")
    if not isinstance(validation_meta, dict):
        validation_meta = None

    summary = str(payload.get("summary") or "").strip()
    if not summary and not basic_info and custom_result is None and validation_meta is None:
        return None

    return {
        "summary": summary,
        "basicInfo": basic_info,
        "customResult": custom_result,
        "validationMeta": validation_meta,
    }


def _normalize_structured_business_result(
    payload: Any,
    fallback: Any = None,
) -> dict[str, Any] | None:
    _ = fallback
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None

    issues = []
    for issue in payload.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        raw_detail = str(issue.get("detail") or "").strip()
        level = _normalize_issue_level_from_detail(issue.get("level"), raw_detail)
        title = str(issue.get("title") or "").strip() or "业务审查项"
        detail = _normalize_issue_detail(level, raw_detail)
        suggestion = _normalize_issue_suggestion(level, issue.get("suggestion"))
        if detail:
            issues.append(
                {
                    "level": level[:16],
                    "title": title[:80],
                    "detail": detail,
                    "suggestion": suggestion,
                }
            )

    summary = str(payload.get("summary") or "").strip()
    risk_level = str(payload.get("riskLevel") or "").strip()
    if not summary and not issues:
        return None

    return {
        "summary": summary,
        "riskLevel": risk_level[:16],
        "issueCount": len(issues),
        "issues": issues[:12],
    }


def _normalize_structured_process_result(
    payload: Any,
    fallback: Any = None,
) -> dict[str, Any] | None:
    _ = fallback
    if payload is None or not isinstance(payload, dict):
        return None

    result_type = str(payload.get("resultType") or "").strip().lower()
    if result_type not in {"transform", "analysis", "mixed"}:
        if payload.get("outputText"):
            result_type = "transform"
        elif payload.get("bullets"):
            result_type = "analysis"
        else:
            return None

    summary = str(payload.get("summary") or "").strip()
    output_text = str(payload.get("outputText") or "").strip() or None
    bullets = [
        str(item).strip()[:200]
        for item in (payload.get("bullets") or [])
        if str(item).strip()
    ]
    if not summary and not output_text and not bullets:
        return None

    if result_type == "transform" and not output_text and bullets:
        result_type = "mixed"
    if result_type == "analysis" and output_text:
        result_type = "mixed"

    return {
        "resultType": result_type,
        "summary": summary or ("已生成处理结果。" if output_text else "已生成处理结论。"),
        "outputText": output_text,
        "bullets": bullets[:12],
        "source": "runtime",
    }


def _build_model_detail(
    *,
    prompt_text: str,
    extraction_result: dict[str, Any] | None,
    process_result: dict[str, Any] | None = None,
    business_result: dict[str, Any] | None = None,
) -> str:
    text_prompt, table_prompt = _split_modal_prompts(prompt_text)
    sections = [
        f"文本提示词：{text_prompt or '未填写'}",
        f"表格提示词：{table_prompt or '未填写'}",
    ]

    if extraction_result:
        basic_info = extraction_result.get("basicInfo") or []
        custom_result_lines = _format_custom_result_for_detail(extraction_result.get("customResult"))
        sections.append(
            "基础抽取：\n"
            + (extraction_result.get("summary") or "已完成基础抽取。")
            + (
                "\n"
                + "\n".join(f"{item.get('label', '字段')}：{item.get('value', '')}" for item in basic_info[:6])
                if basic_info
                else ""
            )
        )
        if custom_result_lines:
            sections.append("自定义抽取：\n" + "\n".join(custom_result_lines[:12]))

    if process_result:
        process_output = str(process_result.get("outputText") or "").strip()
        bullets = [str(item).strip() for item in (process_result.get("bullets") or []) if str(item).strip()]
        sections.append("处理结果：\n" + (process_result.get("summary") or "已生成处理结果。"))
        if process_output:
            sections.append("处理输出：\n" + process_output)
        if bullets:
            sections.append("处理要点：\n" + "\n".join(bullets[:8]))

    if business_result:
        issue_lines = [
            f"{issue.get('level', '一般')}：{issue.get('title', '')}"
            for issue in (business_result.get("issues") or [])[:8]
        ]
        sections.append(
            "业务处理：\n"
            + (business_result.get("summary") or "已生成业务处理结果。")
            + ("\n" + "\n".join(issue_lines) if issue_lines else "")
        )

    return "\n\n".join(sections)


def _merge_structured_process_results(payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_results = [
        normalized
        for payload in payloads
        if isinstance(payload, dict)
        for normalized in [_normalize_structured_process_result(payload.get("structured_process_result"))]
        if normalized
    ]
    if not normalized_results:
        return None

    output_texts = []
    bullets: list[str] = []
    summaries: list[str] = []
    has_transform = False
    has_analysis = False
    for item in normalized_results:
        result_type = str(item.get("resultType") or "")
        if result_type in {"transform", "mixed"} and item.get("outputText"):
            has_transform = True
            output_value = str(item.get("outputText") or "").strip()
            if output_value and output_value not in output_texts:
                output_texts.append(output_value)
        if result_type in {"analysis", "mixed"}:
            has_analysis = True
        for bullet in item.get("bullets") or []:
            normalized_bullet = str(bullet).strip()
            if normalized_bullet and normalized_bullet not in bullets:
                bullets.append(normalized_bullet)
        summary = str(item.get("summary") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)

    result_type = "mixed" if has_transform and has_analysis else "transform" if has_transform else "analysis"
    return {
        "resultType": result_type,
        "summary": summaries[0] if summaries else ("已生成处理结果。" if has_transform else "已生成处理结论。"),
        "outputText": "\n\n".join(output_texts) if output_texts else None,
        "bullets": bullets[:12],
        "source": "runtime",
    }


def _build_process_detail_from_result(process_result: dict[str, Any] | None) -> str:
    if not process_result:
        return ""
    sections = [str(process_result.get("summary") or "").strip()]
    output_text = str(process_result.get("outputText") or "").strip()
    if output_text:
        sections.append(output_text)
    bullets = [str(item).strip() for item in (process_result.get("bullets") or []) if str(item).strip()]
    if bullets:
        sections.append("\n".join(bullets[:12]))
    return "\n\n".join(section for section in sections if section)


def _format_custom_result_for_detail(custom_result: Any) -> list[str]:
    lines: list[str] = []

    def append_scalar(key: str, value: Any) -> None:
        if value in (None, "", [], {}):
            return
        label = str(key or "字段").strip() or "字段"
        if isinstance(value, (dict, list)):
            value_text = json.dumps(value, ensure_ascii=False)
        else:
            value_text = str(value).strip()
        if value_text:
            lines.append(f"{label}：{value_text}")

    if isinstance(custom_result, dict):
        for key, value in custom_result.items():
            append_scalar(str(key), value)
    elif isinstance(custom_result, list):
        seen: set[tuple[str, str]] = set()
        for item in custom_result:
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                before_count = len(lines)
                append_scalar(str(key), value)
                if len(lines) == before_count:
                    continue
                dedupe_key = tuple(lines[-1].split("：", 1)) if "：" in lines[-1] else ("", lines[-1])
                if dedupe_key in seen:
                    lines.pop()
                    continue
                seen.add(dedupe_key)
    return lines


def _extract_first_json_object(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return "{}"
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    if start < 0:
        return stripped

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]

    return stripped


def _extract_first_json_value(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return "{}"
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        return stripped

    object_start = stripped.find("{")
    array_start = stripped.find("[")
    starts = [index for index in (object_start, array_start) if index >= 0]
    if not starts:
        return stripped
    start = min(starts)
    opening = stripped[start]
    closing = "}" if opening == "{" else "]"

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == opening:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]

    return stripped[start:]


def _normalize_issue_level(level: str) -> str:
    if level in {"通过", "关注", "风险", "待确认"}:
        return level
    if any(keyword in level for keyword in ["通过", "正常", "符合"]):
        return "通过"
    if any(keyword in level for keyword in ["风险", "重大", "高", "异常"]):
        return "风险"
    if any(keyword in level for keyword in ["关注", "一般", "建议", "提示"]):
        return "关注"
    return "待确认"


def _extract_inline_pairs(content: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    compact = content.replace("\n", " ")

    for part in re.split(r"[；;]\s*", compact):
        if "：" not in part and ":" not in part:
            continue

        key, value = re.split(r"[:：]\s*", part, maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        if len(key) > 24:
            continue
        pairs.append((key[:24], value[:80]))

    return pairs


def _normalize_block_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _strip_html_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(text).split()).strip()
