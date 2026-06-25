# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Reusable SKILL.md assist helpers for routes and prototype workflows."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.schemas.workbench import SkillAssistRequest, SkillAssistResponse
from app.services.skill_loader import parse_skill_markdown


_ALLOWED_EXTRACTION_INPUT_BUILDERS = {"page_compact", "table_grid_only", "text_only"}
_EXTRACTION_INPUT_BUILDER_ALIASES = {
    "document": "page_compact",
    "document_text": "page_compact",
    "document_compact": "page_compact",
    "full_document": "page_compact",
    "full_document_text": "page_compact",
    "full_text": "page_compact",
    "page_text": "text_only",
    "ocr_text": "text_only",
    "table_only": "table_grid_only",
    "table_grid": "table_grid_only",
}


def run_skill_assist(payload: SkillAssistRequest) -> SkillAssistResponse:
    started = time.perf_counter()
    answer, reasoning, input_chars = call_skill_assistant(payload)
    skill_text = extract_skill_markdown(answer)
    skill_text = repair_missing_frontmatter_closer(skill_text)
    if not skill_text.lstrip().startswith("---"):
        skill_text = synthesize_skill_markdown_from_assistant_answer(payload, skill_text)
    skill_text = normalize_assisted_skill_contract(payload, skill_text)
    errors = validate_assisted_skill_text(payload, skill_text)
    return SkillAssistResponse(
        valid=not errors,
        errors=errors,
        skillText=skill_text,
        reasoning=reasoning,
        answer=answer,
        model=skill_assist_model(),
        durationMs=int((time.perf_counter() - started) * 1000),
        inputChars=input_chars,
        outputChars=len(answer),
    )


def run_sample_extraction_assist(
    *,
    instruction: str,
    expected_output: str,
    sample_text: str,
    data_type_name: str = "",
    source_scope: str = "",
    source_label: str = "",
    customer_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    answer, reasoning, input_chars, usage, trace = call_sample_extraction_assistant(
        instruction=instruction,
        expected_output=expected_output,
        sample_text=sample_text,
        data_type_name=data_type_name,
        source_scope=source_scope,
        source_label=source_label,
        customer_id=customer_id,
    )
    raw_payload = extract_json_payload(answer)
    return {
        "rawPayload": raw_payload,
        "answer": answer,
        "reasoning": reasoning,
        "provider": "dashscope",
        "model": sample_extraction_model(),
        "durationMs": int((time.perf_counter() - started) * 1000),
        "inputChars": input_chars,
        "outputChars": len(answer),
        "promptTokens": usage.get("prompt_tokens"),
        "completionTokens": usage.get("completion_tokens"),
        "totalTokens": usage.get("total_tokens"),
        "trace": trace,
    }


def run_sample_process_assist(
    *,
    instruction: str,
    expected_output: str,
    sample_text: str,
    data_type_name: str = "",
    source_scope: str = "",
    source_label: str = "",
    customer_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    answer, reasoning, input_chars, usage = call_sample_process_assistant(
        instruction=instruction,
        expected_output=expected_output,
        sample_text=sample_text,
        data_type_name=data_type_name,
        source_scope=source_scope,
        source_label=source_label,
        customer_id=customer_id,
    )
    raw_payload = extract_json_payload(answer, label="样例试处理")
    return {
        "rawPayload": raw_payload,
        "answer": answer,
        "reasoning": reasoning,
        "provider": "dashscope",
        "model": sample_process_model(),
        "durationMs": int((time.perf_counter() - started) * 1000),
        "inputChars": input_chars,
        "outputChars": len(answer),
        "promptTokens": usage.get("prompt_tokens"),
        "completionTokens": usage.get("completion_tokens"),
        "totalTokens": usage.get("total_tokens"),
    }


def validate_assisted_skill_text(payload: SkillAssistRequest, skill_text: str) -> list[str]:
    try:
        parsed = parse_skill_markdown(skill_text)
    except ValueError as exc:
        return [str(exc)]
    errors: list[str] = []
    kind = str(parsed.frontmatter.get("kind") or "").strip()
    executor = str(parsed.frontmatter.get("executor") or "").strip()
    if kind != payload.kind:
        errors.append(f"kind 应为 {payload.kind}。")
    if payload.kind == "extraction" and executor != "llm_structured":
        errors.append("extraction skill executor 应为 llm_structured。")
    return errors


def repair_missing_frontmatter_closer(skill_text: str) -> str:
    text = str(skill_text or "").strip()
    if not text.startswith("---"):
        return text
    if len(text.split("---", 2)) >= 3:
        return text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        if re.match(r"^#{1,6}\s+", line):
            frontmatter = "\n".join(lines[:index]).rstrip()
            body = "\n".join(lines[index:]).lstrip()
            return f"{frontmatter}\n---\n\n{body}".strip()
    return text


def skill_assist_model() -> str:
    return os.getenv("DASHSCOPE_SKILL_ASSIST_MODEL", "qwen3.7-max")


def sample_extraction_model() -> str:
    return os.getenv("DASHSCOPE_SAMPLE_EXTRACT_MODEL", skill_assist_model())


def sample_extraction_text_limit() -> int:
    try:
        return max(12000, int(os.getenv("DASHSCOPE_SAMPLE_EXTRACT_TEXT_LIMIT", "30000")))
    except ValueError:
        return 30000


def sample_process_model() -> str:
    return os.getenv("DASHSCOPE_SAMPLE_PROCESS_MODEL", skill_assist_model())


def _raise_missing_llm_configuration() -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="DASHSCOPE_API_KEY 未配置。请配置 BYO OpenAI-compatible 模型后再发起真实 AI 操作。",
    )


def call_sample_extraction_assistant(
    *,
    instruction: str,
    expected_output: str,
    sample_text: str,
    data_type_name: str = "",
    source_scope: str = "",
    source_label: str = "",
    customer_id: str | None = None,
) -> tuple[str, str, int, dict[str, int], dict[str, Any]]:
    settings = get_settings()
    if not settings.dashscope_api_key:
        _raise_missing_llm_configuration()
    compact_sample_text = sample_text.strip()
    sample_limit = sample_extraction_text_limit()
    if len(compact_sample_text) > sample_limit:
        compact_sample_text = compact_sample_text[:sample_limit] + "\n...（样本已截断）"
    system_prompt = (
        "你是旗讯OCR智能文档处理平台的样例数据抽取助手。"
        "你的任务是只基于用户给出的 OCR 样例内容，直接抽取结构化 JSON。"
        "不要生成、解释或返回 SKILL.md，不要返回 Markdown 代码围栏。"
        "禁止编造样例中不存在的数据。"
        "默认只保留 source_page/page 等轻量来源字段；除非用户明确要求，不要输出 original_text 或原文片段。"
        "最终答案必须是一个 JSON 对象。"
    )
    output_protocol = {
        "summary": "一句话说明抽取到的结果数量。",
        "outputs": [
            {
                "id": "sample-output-1",
                "title": data_type_name or "样例抽取结果",
                "type": "field_list | data_table | record_collection | custom",
                "renderer": "field_list | data_table | nested_records | auto",
                "data": "按 type 选择一种直接结构：field_list 使用 {fields:[...]}；data_table 使用 {headers:[...], rows:[...]}；record_collection 使用 {records:[...]}。",
                "schema": {},
                "sourceRefs": [],
            }
        ],
        "errors": [],
    }
    requirements = [
        "只抽取样例 OCR 中真实存在的数据。",
        "如果目标是表格，使用 type=data_table，data.headers/data.rows 必须完整保留行列关系；可在 data.mergeNotes 说明跨行跨列或结构含义。",
        "如果目标是字段，使用 type=field_list，data.fields 为字段数组。",
        "如果目标是多条同构记录，使用 type=record_collection，data.records 为记录数组。",
        "data 内不要再嵌套 field_list、data_table 或 record_collection 包装键。",
        "来源字段默认只写 source_page 或 page；不要默认输出 original_text。",
        "不要把空模板当作结果；确实缺失的数据才保留为空字符串。",
    ]
    user_payload = {
        "kind": "extraction",
        "customerId": customer_id,
        "dataTypeName": data_type_name,
        "sourceScope": source_scope,
        "sourceLabel": source_label,
        "instruction": instruction.strip(),
        "expectedOutput": expected_output.strip(),
        "sampleText": compact_sample_text,
        "requirements": requirements,
        "outputProtocol": output_protocol,
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    request_payload = {
        "model": sample_extraction_model(),
        "messages": messages,
        "stream": False,
        "top_p": 0.2,
        "temperature": 0.1,
        "result_format": "message",
        "enable_thinking": False,
    }
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request_url = f"{settings.dashscope_base_url}/chat/completions"
    trace: dict[str, Any] = {
        "requestUrl": request_url,
        "requestPayload": request_payload,
        "attempts": [],
    }
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []
    usage: dict[str, int] = {}
    max_attempts = 3
    for attempt in range(max_attempts):
        reasoning_parts = []
        answer_parts = []
        usage = {}
        attempt_trace: dict[str, Any] = {"attempt": attempt + 1}
        try:
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), trust_env=False) as client:
                response = client.post(request_url, headers=headers, content=request_body)
            attempt_trace["statusCode"] = response.status_code
            attempt_trace["responseChars"] = len(response.text or "")
            if response.status_code >= 400:
                attempt_trace["error"] = response.text
                trace["attempts"].append(attempt_trace)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"DashScope 样例试抽取请求失败: {response.status_code} {response.text}",
                )
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="DashScope 样例试抽取返回了非 JSON 内容。",
                ) from exc
            trace["responsePayload"] = data
            choices = data.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                reasoning = message.get("reasoning_content")
                content = message.get("content")
                if reasoning is not None:
                    reasoning_parts.append(str(reasoning))
                if content:
                    answer_parts.append(str(content))
            raw_usage = data.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    key: int(value)
                    for key, value in raw_usage.items()
                    if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(value, int)
                }
            attempt_trace["usage"] = usage
            trace["attempts"].append(attempt_trace)
            break
        except httpx.TransportError as exc:
            attempt_trace["transportError"] = str(exc)
            trace["attempts"].append(attempt_trace)
            if attempt < max_attempts - 1 and _is_retryable_skill_assist_transport_error(exc):
                time.sleep(0.8 * (attempt + 1))
                continue
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"DashScope 样例试抽取网络调用失败: {exc}",
            ) from exc
    answer = "".join(answer_parts).strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="DashScope 样例试抽取未返回内容。")
    return answer, "".join(reasoning_parts).strip(), len(system_prompt) + len(json.dumps(user_payload, ensure_ascii=False)), usage, trace


def call_sample_process_assistant(
    *,
    instruction: str,
    expected_output: str,
    sample_text: str,
    data_type_name: str = "",
    source_scope: str = "",
    source_label: str = "",
    customer_id: str | None = None,
) -> tuple[str, str, int, dict[str, int]]:
    settings = get_settings()
    if not settings.dashscope_api_key:
        _raise_missing_llm_configuration()
    compact_sample_text = sample_text.strip()
    if len(compact_sample_text) > 12000:
        compact_sample_text = compact_sample_text[:12000] + "\n...（样本已截断）"
    system_prompt = (
        "你是旗讯OCR智能文档处理平台的样例业务处理助手。"
        "你的任务是只基于用户选中的结构化提取结果，直接执行一次业务处理并返回 JSON。"
        "不要生成、解释或返回 SKILL.md，不要返回 Markdown 代码围栏。"
        "禁止编造输入中不存在的数据。"
        "最终答案必须是一个 JSON 对象。"
    )
    output_protocol = {
        "summary": "一句话说明处理结果。",
        "result_kind": "decision | object | table | text",
        "output_payload": "按 result_kind 返回业务处理后的轻量结果；object 可包含 records/items/fields/issues 等结构。",
        "validationErrors": [],
    }
    requirements = [
        "只处理样例输入中真实存在的结构化对象，不要额外查找或补造数据。",
        "如果处理结果是判断/通过/不通过，使用 result_kind=decision，output_payload 包含 decision、reason、evidence。",
        "如果处理结果是字段映射、校验结果、归一化对象或记录集合，使用 result_kind=object。",
        "如果处理结果需要二维表展示，使用 result_kind=table，output_payload 包含 headers 和 rows。",
        "如果处理结果只是说明文本，使用 result_kind=text，output_payload 包含 text。",
        "validationErrors 只放样例处理中的格式或数据问题；没有则返回空数组。",
        "不要默认输出 original_text 或长原文片段；如需证据只保留 source_page、字段名或短依据。",
    ]
    user_payload = {
        "kind": "operation",
        "customerId": customer_id,
        "dataTypeName": data_type_name,
        "sourceScope": source_scope,
        "sourceLabel": source_label,
        "instruction": instruction.strip(),
        "expectedOutput": expected_output.strip(),
        "selectedOperationTargets": compact_sample_text,
        "requirements": requirements,
        "outputProtocol": output_protocol,
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    request_payload = {
        "model": sample_process_model(),
        "messages": messages,
        "stream": False,
        "top_p": 0.2,
        "temperature": 0.1,
        "result_format": "message",
        "enable_thinking": False,
    }
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request_url = f"{settings.dashscope_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []
    usage: dict[str, int] = {}
    max_attempts = 3
    for attempt in range(max_attempts):
        reasoning_parts = []
        answer_parts = []
        usage = {}
        try:
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), trust_env=False) as client:
                response = client.post(request_url, headers=headers, content=request_body)
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"DashScope 样例试处理请求失败: {response.status_code} {response.text}",
                )
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="DashScope 样例试处理返回了非 JSON 内容。",
                ) from exc
            choices = data.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                reasoning = message.get("reasoning_content")
                content = message.get("content")
                if reasoning is not None:
                    reasoning_parts.append(str(reasoning))
                if content:
                    answer_parts.append(str(content))
            raw_usage = data.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    key: int(value)
                    for key, value in raw_usage.items()
                    if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(value, int)
                }
            break
        except httpx.TransportError as exc:
            if attempt < max_attempts - 1 and _is_retryable_skill_assist_transport_error(exc):
                time.sleep(0.8 * (attempt + 1))
                continue
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"DashScope 样例试处理网络调用失败: {exc}",
            ) from exc
    answer = "".join(answer_parts).strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="DashScope 样例试处理未返回内容。")
    return answer, "".join(reasoning_parts).strip(), len(system_prompt) + len(json.dumps(user_payload, ensure_ascii=False)), usage


def extract_json_payload(answer: str, *, label: str = "样例试抽取") -> dict[str, Any]:
    text = str(answer or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    snippet = _find_first_json_object(text)
    if snippet:
        try:
            payload = json.loads(snippet)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"DashScope {label}未返回有效 JSON 对象。")


def _find_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def call_skill_assistant(payload: SkillAssistRequest) -> tuple[str, str, int]:
    settings = get_settings()
    if not settings.dashscope_api_key:
        _raise_missing_llm_configuration()
    system_prompt = build_skill_assist_system_prompt(payload.kind)
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
        "正文面向实施人员维护，但必须简洁：结构化解析 Skill 至少写目标、适用条件、领域语义、证据规则、冲突与缺失、输出格式；业务处理 Skill 保持目标、规则和输出协议清晰。",
        "不要重复输出格式，不要同时写两套 JSON 协议，不要照搬其他文档类型的字段示例。",
        "输出示例必须是短结构模板，只展示 1 行占位，不要把样本数据整段抄入 SKILL.md。",
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
                "如果用户的处理目标或输出要求包含“表格、表头、行数据、行列关系、合并单元格”，必须使用 renderer: data_table 和 output.type: data_table。",
                "表格提取的输出示例必须使用 {\"headers\":[...],\"rows\":[...],\"mergeNotes\":[...],\"evidence\":[...]}，不要使用 field_name/field_value 逐字段记录。",
                "表格提取正文不要超过 1200 个中文字符；不要同时保留“输出示例”和“输出格式”两段。",
                "如果是结构化解析且 output.type 为 record_collection，输出示例必须使用 {\"records\":[...]}，不要使用裸 JSON 数组。",
                "record_collection 的 output.required 表示 records 中每条记录的必填字段。",
                "业务语义只能写在正文的领域语义和证据规则中，不要写成 frontmatter JSON 字典或固定别名表。",
                "必须说明：字段、列名或角色称谓不完全一致时，由模型结合 Evidence 的上下文、动作关系、所属模块和版式位置判断；证据不足时返回空值或进入复核。",
                "必须说明：runtimeContract 是最终运行契约，优先于正文中过时或更窄的字段列表。",
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
        "model": skill_assist_model(),
        "messages": messages,
        "stream": False,
        "top_p": 0.8,
        "temperature": 0.7,
        "result_format": "message",
        "enable_thinking": True,
        "thinking_budget": 4000,
    }
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request_url = f"{settings.dashscope_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []
    max_attempts = 3
    for attempt in range(max_attempts):
        reasoning_parts = []
        answer_parts = []
        try:
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), trust_env=False) as client:
                response = client.post(request_url, headers=headers, content=request_body)
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"DashScope Skill 辅助请求失败: {response.status_code} {response.text}",
                )
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="DashScope Skill 辅助返回了非 JSON 内容。",
                ) from exc
            choices = data.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                reasoning = message.get("reasoning_content")
                content = message.get("content")
                if reasoning is not None:
                    reasoning_parts.append(str(reasoning))
                if content:
                    answer_parts.append(str(content))
            break
        except httpx.TransportError as exc:
            if attempt < max_attempts - 1 and _is_retryable_skill_assist_transport_error(exc):
                time.sleep(0.8 * (attempt + 1))
                continue
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"DashScope Skill 辅助网络调用失败: {exc}",
            ) from exc
    answer = "".join(answer_parts).strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="DashScope Skill 辅助未返回内容。")
    return answer, "".join(reasoning_parts).strip(), len(system_prompt) + len(json.dumps(user_payload, ensure_ascii=False))


def _is_retryable_skill_assist_transport_error(exc: httpx.TransportError) -> bool:
    reason = str(exc).lower()
    retryable_markers = (
        "unexpected_eof",
        "eof occurred",
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
    )
    return any(marker in reason for marker in retryable_markers)


def build_skill_assist_system_prompt(kind: str) -> str:
    common = (
        "你是旗讯OCR智能文档处理平台的 SKILL.md 编写助手。"
        "你的任务是根据用户要求生成或改写可发布的 SKILL.md。"
        "最终答案第一行必须是 ---，必须返回完整 SKILL.md 文本，不要输出解释，不要用代码围栏包裹。"
        "禁止只返回 JSON、JSON Schema、提取结果或空模板。"
        "如果用户给了现有 SKILL.md，除非用户明确要求，否则保留原 id、kind 和主要输出类型。"
        "frontmatter 只允许放 id、version、name、kind、category、enabled、sourceTypes、targetTypes、executor、input、renderer、output、resultKind、configSchema、outputSchema、defaults 等短字段。"
        "不要把用户原始要求、样本、JSON 映射、制表符或多行长文本放入 frontmatter；这些内容必须写入正文。"
        "正文必须短：结构化解析 Skill 至少包含目标、适用条件、领域语义、证据规则、冲突与缺失、输出格式；业务处理 Skill 保持目标、规则和输出协议清晰；输出格式只能出现一次。"
        "输出示例只写通用结构模板，不要照搬其他业务字段或长样本。"
    )
    if kind == "operation":
        return (
            common
            + "业务处理 Skill 的 kind 必须是 operation。"
            + "executor 只能从 llm_structured、local_transform、quality_check、export_data、http_connector、controlled_python、external_connector 中选择。"
            + "如果不是明确的本地映射、检查、导出或接口调用，默认使用 llm_structured。"
            + "必须声明 targetTypes、resultKind、renderer、outputSchema。"
            + "resultKind 只允许 decision、object、table、text，绝不能使用 record_collection。"
            + "record_collection 只能作为 targetTypes 中的输入目标类型，表示这个 Skill 可以处理记录集合。"
            + "如果用户要输出 records 或记录集合，必须使用 resultKind: object，outputSchema.type: object，"
            + "并在正文输出示例中使用 {\"summary\":\"...\",\"result_kind\":\"object\",\"output_payload\":{\"records\":[...]}}。"
            + "业务处理执行结果最终必须返回 summary、result_kind、output_payload 三个字段。"
        )
    return (
        common
        + "结构化解析 Skill 的 kind 必须是 extraction，executor 必须是 llm_structured。"
        + "必须声明 sourceTypes、input.builder、renderer、output。"
        + "input.builder 只能使用 page_compact、text_only、table_grid_only；默认使用 page_compact。"
        + "禁止使用 document_text、document、full_text、page_text 等平台不支持的 builder。"
        + "如果用户目标是提取表格、表头、行数据、行列关系或合并单元格，必须使用 renderer: data_table 和 output.type: data_table，"
        + "正文输出示例使用 {\"headers\":[...],\"rows\":[...],\"mergeNotes\":[...],\"evidence\":[...]}。"
        + "表格提取不要退化为 field_name/field_value 记录集合。"
        + "表格提取正文保持简洁，不要保留两套输出格式或长篇样例。"
        + "如果目标是多条记录集合，优先使用 renderer: nested_records 和 output.type: record_collection。"
        + "record_collection 的平台协议固定为 JSON 对象 {\"records\":[...]}，不要在输出格式中写裸 JSON 数组。"
        + "如果用户说“输出 JSON 数组”，也必须在 SKILL.md 中表达为 {\"records\":[...]}。"
        + "record_collection 的 output.required 表示 records 中每条记录的必填字段，不是 JSON 顶层字段。"
        + "如果目标是报告对象且同时包含 KV 和 list，可以使用 output.type: custom，正文必须写清哪些字段是 KV、哪些字段是 list。"
        + "输出格式中的空字符串只是结构占位，执行时必须从识别事实中填入真实值，不能返回空模板。"
        + "业务语义必须写在正文中，不能写成 frontmatter JSON 映射或固定别名表。"
        + "必须说明 runtimeContract 是本次运行最高优先级契约；字段名、表头或角色称谓不完全一致时，"
        + "由模型结合 Evidence 的上下文、动作关系、所属模块和版式位置判断，证据不足时返回空值或进入复核。"
        + "规则必须强调只基于识别结果、保留所有行、不要编造。"
    )


def extract_skill_markdown(answer: str) -> str:
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


def synthesize_skill_markdown_from_assistant_answer(payload: SkillAssistRequest, answer: str) -> str:
    instruction = payload.instruction.strip() or ("结构化解析" if payload.kind == "extraction" else "业务处理")
    output_example = _normalize_output_example(answer)
    if payload.kind == "operation":
        return _synthesize_operation_skill(instruction, output_example)
    output_type, renderer = _infer_extraction_output_shape(output_example, instruction=instruction)
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

{_build_runtime_contract_priority_section(output_kind=output_type)}

# 领域语义

- 字段、列或记录含义以 runtimeContract、字段要求和本 Skill 目标共同确定。
- 名称、表头或角色称谓不完全一致时，结合上下文、动作关系、所属模块和版式位置判断。
- 本节是语义判断方法，不是固定别名表；证据不足时不得强行映射。

# 证据规则

- 优先使用文档树命中范围、相邻标题、表格字段区、文本块和 OCR 行。
- 非空值必须能在当前 Evidence 中追溯到对应页面或短证据。
- 长表只使用与目标输出相关的证据窗口，不能把窗口外内容当作已知事实。

# 冲突与缺失

- 多个候选冲突时，选择与 runtimeContract、定位模块和邻近证据最一致的值。
- 仍无法确认时返回空字符串或记录复核问题，不编造、不删除目标字段。

# 输出格式

```json
{output_example}
```
"""


def normalize_assisted_skill_contract(payload: SkillAssistRequest, skill_text: str) -> str:
    try:
        parsed = parse_skill_markdown(skill_text)
    except ValueError:
        return skill_text
    if payload.kind == "operation":
        return _normalize_operation_skill_contract(parsed.body, parsed.frontmatter, skill_text)
    if payload.kind != "extraction":
        return skill_text
    frontmatter = skill_text.split("---", 2)[1].strip()
    frontmatter = _normalize_extraction_frontmatter_input_builder(frontmatter, parsed.frontmatter)
    forced_output_type, forced_renderer = _forced_extraction_output_shape(payload.instruction)
    if forced_output_type == "field_list":
        frontmatter = _ensure_extraction_output_frontmatter(frontmatter, renderer=forced_renderer, output_type="field_list")
        body = _normalize_field_list_body(parsed.body, instruction=payload.instruction)
        return f"---\n{frontmatter}\n---\n\n{body}".strip()
    if forced_output_type == "data_table" or _is_table_extraction_intent(payload.instruction):
        frontmatter = _ensure_extraction_output_frontmatter(frontmatter, renderer="data_table", output_type="data_table")
        body = _normalize_data_table_body(parsed.body, instruction=payload.instruction)
        return f"---\n{frontmatter}\n---\n\n{body}".strip()
    if forced_output_type == "record_collection":
        frontmatter = _ensure_extraction_output_frontmatter(frontmatter, renderer=forced_renderer, output_type="record_collection")
        output = {"type": "record_collection", "required": _extract_confirmed_record_fields_from_instruction(payload.instruction)}
        required_fields = _resolve_record_collection_required_fields(
            output=output,
            body=parsed.body,
            instruction=payload.instruction,
        )
        body = _normalize_record_collection_body(parsed.body, required_fields=required_fields)
        if required_fields:
            frontmatter = _ensure_record_collection_required(frontmatter, required_fields)
        return f"---\n{frontmatter}\n---\n\n{body}".strip()
    output = parsed.frontmatter.get("output")
    if not isinstance(output, dict) or output.get("type") != "record_collection":
        return f"---\n{frontmatter}\n---\n\n{parsed.body}".strip()

    required_fields = _resolve_record_collection_required_fields(
        output=output,
        body=parsed.body,
        instruction=payload.instruction,
    )
    body = _normalize_record_collection_body(parsed.body, required_fields=required_fields)
    if required_fields:
        frontmatter = _ensure_record_collection_required(frontmatter, required_fields)
    return f"---\n{frontmatter}\n---\n\n{body}".strip()


def ensure_extraction_skill_semantic_governance(skill_text: str) -> str:
    try:
        parsed = parse_skill_markdown(skill_text)
    except ValueError:
        return skill_text
    if str(parsed.frontmatter.get("kind") or "").strip() != "extraction":
        return skill_text
    output_payload = parsed.frontmatter.get("output")
    output = output_payload if isinstance(output_payload, dict) else {}
    output_type = str(output.get("type") or "").strip()
    output_kind = output_type if output_type in {"field_list", "data_table", "record_collection"} else "field_list"
    required_fields = [str(item).strip() for item in output.get("required", []) if str(item).strip()] if isinstance(output.get("required"), list) else []
    body = parsed.body.strip()
    if output_kind == "field_list":
        body = _soften_field_list_fixed_field_language(body)
    body = _ensure_runtime_contract_priority_section(body, output_kind=output_kind)
    sections: list[str] = []
    if "领域语义" not in body:
        sections.append(_build_domain_semantics_section(required_fields, output_kind=output_kind))
    if "证据规则" not in body:
        sections.append(_build_evidence_rules_section(output_kind=output_kind))
    if "冲突与缺失" not in body:
        sections.append(_build_conflict_and_missing_section(output_kind=output_kind))
    frontmatter = skill_text.split("---", 2)[1].strip()
    if not sections:
        return f"---\n{frontmatter}\n---\n\n{body}".strip()
    return f"---\n{frontmatter}\n---\n\n{body}\n\n" + "\n\n".join(sections)


def _normalize_extraction_frontmatter_input_builder(frontmatter: str, payload: dict[str, Any]) -> str:
    raw_input = payload.get("input")
    input_payload = raw_input if isinstance(raw_input, dict) else {}
    raw_builder = str(payload.get("inputBuilder") or input_payload.get("builder") or "page_compact").strip()
    builder = _EXTRACTION_INPUT_BUILDER_ALIASES.get(raw_builder, raw_builder)
    if builder not in _ALLOWED_EXTRACTION_INPUT_BUILDERS:
        builder = "page_compact"
    if re.search(r"(?m)^inputBuilder\s*:", frontmatter):
        return re.sub(r"(?m)^inputBuilder\s*:.*$", f"inputBuilder: {builder}", frontmatter, count=1)
    if re.search(r"(?m)^(\s*)builder\s*:", frontmatter):
        return re.sub(r"(?m)^(\s*)builder\s*:.*$", rf"\1builder: {builder}", frontmatter, count=1)
    if re.search(r"(?m)^input\s*:\s*$", frontmatter):
        return re.sub(r"(?m)^input\s*:\s*$", f"input:\n  builder: {builder}", frontmatter, count=1)
    lines = frontmatter.splitlines()
    result: list[str] = []
    inserted = False
    for line in lines:
        result.append(line)
        if not inserted and re.match(r"^executor\s*:", line):
            result.extend(["input:", f"  builder: {builder}"])
            inserted = True
    if not inserted:
        result.extend(["input:", f"  builder: {builder}"])
    return "\n".join(result)


def build_local_extraction_skill(
    *,
    prototype_id: str,
    name: str,
    extraction_goal: str,
    field_requirements: str,
    output_example: str,
) -> str:
    required_fields = _extract_required_field_names(field_requirements or output_example)
    required_line = f"\n  required: {json.dumps(required_fields, ensure_ascii=False)}" if required_fields else ""
    example = _normalize_output_example(output_example or "{}")
    return f"""---
id: {prototype_id}_baseline
version: 0.1.0
name: {name}
kind: extraction
category: extraction
enabled: true
sourceTypes: [text, html_table, json]
executor: llm_structured
input:
  builder: page_compact
renderer: nested_records
output:
  type: record_collection{required_line}
---

# 目标

{extraction_goal}

# 字段要求

{field_requirements or "- 按输出示例抽取所有可见字段。"}

# 规则

- 只基于用户提供的 OCR 文本、HTML 片段或结构化 OCR JSON。
- 保留所有可见记录，不要只返回第一条。
- 缺失字段返回空字符串，不要编造。
- 输出必须是 JSON 对象，格式为 {{"records":[...]}}。
- 每条记录字段名应与字段要求或输出示例保持一致。

# 领域语义

- 字段、列或记录含义以 runtimeContract、字段要求和本 Skill 目标共同确定。
- 名称、表头或角色称谓不完全一致时，结合上下文、动作关系、所属模块和版式位置判断。
- 本节是语义判断方法，不是固定别名表；证据不足时不得强行映射。

# 证据规则

- 优先使用文档树命中范围、相邻标题、表格字段区、文本块和 OCR 行。
- 非空值必须能在当前 Evidence 中追溯到对应页面或短证据。
- 长表只使用与目标输出相关的证据窗口，不能把窗口外内容当作已知事实。

# 冲突与缺失

- 多个候选冲突时，选择与 runtimeContract、定位模块和邻近证据最一致的值。
- 仍无法确认时返回空字符串或记录复核问题，不编造、不删除目标字段。

# 输出格式

```json
{example}
```
"""


def _synthesize_operation_skill(instruction: str, output_example: str) -> str:
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


def _normalize_output_example(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return "{}"
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start_candidates = [pos for pos in (text.find("{"), text.find("[")) if pos >= 0]
    if start_candidates:
        text = text[min(start_candidates) :].strip()
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return json.dumps({"records": []}, ensure_ascii=False, indent=2)


def _infer_extraction_output_shape(output_example: str, *, instruction: str = "") -> tuple[str, str]:
    if _is_table_extraction_intent(instruction):
        return "data_table", "data_table"
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        return "custom", "json_view"
    if isinstance(parsed, list):
        return "record_collection", "nested_records"
    if isinstance(parsed, dict):
        if isinstance(parsed.get("headers"), list) and isinstance(parsed.get("rows"), list):
            return "data_table", "data_table"
        if isinstance(parsed.get("records"), list):
            return "record_collection", "nested_records"
        if any(isinstance(value, list) for value in parsed.values()):
            return "custom", "json_view"
        return "custom", "field_grid"
    return "custom", "json_view"


def _forced_extraction_output_shape(instruction: str) -> tuple[str, str]:
    text = str(instruction or "")
    match = re.search(r"确认输出协议\s*[:：]\s*([a-z_]+)", text, flags=re.IGNORECASE)
    output_type = match.group(1).strip().lower() if match else ""
    if not output_type:
        match = re.search(r"output\.type\s*必须是\s*`?([a-z_]+)`?", text, flags=re.IGNORECASE)
        output_type = match.group(1).strip().lower() if match else ""
    mapping = {
        "field_list": ("field_list", "field_list"),
        "data_table": ("data_table", "data_table"),
        "record_collection": ("record_collection", "nested_records"),
        "custom": ("custom", "auto"),
    }
    return mapping.get(output_type, ("", ""))


def _coerce_output_example_for_output_type(output_example: str, output_type: str) -> str:
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        return output_example
    if output_type == "data_table":
        return _coerce_data_table_output_example(parsed)
    if output_type == "record_collection" and isinstance(parsed, list):
        return json.dumps({"records": parsed}, ensure_ascii=False, indent=2)
    if output_type == "record_collection" and isinstance(parsed, dict) and "records" not in parsed:
        return json.dumps({"records": [parsed]}, ensure_ascii=False, indent=2)
    return output_example


def _is_table_extraction_intent(instruction: str) -> bool:
    forced_output_type, _ = _forced_extraction_output_shape(instruction)
    if forced_output_type and forced_output_type != "data_table":
        return False
    text = str(instruction or "")
    table_keywords = ("表格", "表头", "行数据", "行列", "单元格", "合并单元格", "headers", "rows")
    return any(keyword in text for keyword in table_keywords)


def _coerce_data_table_output_example(parsed: Any) -> str:
    if isinstance(parsed, dict):
        headers = parsed.get("headers") if isinstance(parsed.get("headers"), list) else []
        rows = parsed.get("rows") if isinstance(parsed.get("rows"), list) else []
        merge_notes = parsed.get("mergeNotes") or parsed.get("merge_notes") or parsed.get("merges") or []
        evidence = parsed.get("evidence") or parsed.get("evidenceRefs") or parsed.get("sourceEvidence") or []
        if not headers and rows and isinstance(rows[0], dict):
            headers = [str(key) for key in rows[0].keys()]
        payload = {
            "headers": headers or ["表头1", "表头2"],
            "rows": rows or [],
            "mergeNotes": merge_notes if isinstance(merge_notes, list) else [],
            "evidence": evidence if isinstance(evidence, list) else [],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return json.dumps(
        {
            "headers": ["表头1", "表头2"],
            "rows": [],
            "mergeNotes": [],
            "evidence": [],
        },
        ensure_ascii=False,
        indent=2,
    )


def _coerce_operation_output_example(output_example: str) -> str:
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict) or "summary" not in parsed or "output_payload" not in parsed:
        parsed = {
            "summary": "处理完成",
            "result_kind": "object",
            "output_payload": parsed if isinstance(parsed, dict) else {"records": parsed},
        }
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _infer_required_fields_from_output_example(output_example: str) -> list[str]:
    try:
        parsed = json.loads(output_example)
    except json.JSONDecodeError:
        return []
    record: dict[str, Any] | None = None
    if isinstance(parsed, dict) and isinstance(parsed.get("records"), list) and parsed["records"]:
        first = parsed["records"][0]
        if isinstance(first, dict):
            record = first
    elif isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        record = parsed[0]
    elif isinstance(parsed, dict):
        record = parsed
    if not record:
        return []
    return [str(key) for key in record.keys() if str(key).strip()][:20]


def _extract_required_field_names(text: str) -> list[str]:
    fields: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip().strip("-*0123456789.、 ")
        if not stripped:
            continue
        key = re.split(r"[:：,，\s]", stripped, maxsplit=1)[0].strip()
        if 1 <= len(key) <= 32 and key not in fields:
            fields.append(key)
    return fields[:20]


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
    output_format = _build_operation_output_format_section(result_kind)
    if re.search(r"(?m)^#\s+输出格式\s*$", body):
        return _replace_markdown_section(body, "输出格式", output_format)
    return f"{body.rstrip()}\n\n{output_format}".strip()


def _build_operation_output_format_section(result_kind: str) -> str:
    return f"""# 输出格式

模型执行时必须返回完整业务处理协议：

```json
{{
  "summary": "处理结论摘要",
  "result_kind": "{result_kind}",
  "output_payload": {{}}
}}
```"""


def _replace_markdown_section(body: str, title: str, replacement: str) -> str:
    pattern = rf"(?ms)^#{{1,6}}\s+{re.escape(title)}\s*$.*?(?=^#{{1,6}}\s+|\Z)"
    return re.sub(pattern, replacement.strip(), body).strip()


def _insert_markdown_section_before(body: str, title: str, section: str) -> str:
    pattern = rf"(?m)^#{{1,6}}\s+{re.escape(title)}\s*$"
    match = re.search(pattern, body)
    if not match:
        return f"{body.rstrip()}\n\n{section.strip()}".strip()
    return f"{body[:match.start()].rstrip()}\n\n{section.strip()}\n\n{body[match.start():].lstrip()}".strip()


def _remove_markdown_section(body: str, title: str) -> str:
    pattern = rf"(?ms)^#{{1,6}}\s+{re.escape(title)}\s*$.*?(?=^#{{1,6}}\s+|\Z)"
    return re.sub(pattern, "", body).strip()


def _ensure_data_table_frontmatter(frontmatter: str) -> str:
    return _ensure_extraction_output_frontmatter(frontmatter, renderer="data_table", output_type="data_table")


def _ensure_extraction_output_frontmatter(frontmatter: str, *, renderer: str, output_type: str) -> str:
    if re.search(r"(?m)^renderer\s*:", frontmatter):
        frontmatter = re.sub(r"(?m)^renderer\s*:.*$", f"renderer: {renderer}", frontmatter, count=1)
    else:
        frontmatter = f"{frontmatter.rstrip()}\nrenderer: {renderer}"
    return _replace_output_frontmatter_block(frontmatter, output_type)


def _replace_output_frontmatter_block(frontmatter: str, output_type: str) -> str:
    lines = frontmatter.splitlines()
    result: list[str] = []
    in_output = False
    replaced = False
    for line in lines:
        if re.match(r"^output\s*:", line):
            result.extend(["output:", f"  type: {output_type}"])
            in_output = True
            replaced = True
            continue
        if in_output:
            if line.startswith(" ") or not line.strip():
                continue
            in_output = False
        result.append(line)
    if not replaced:
        result.extend(["output:", f"  type: {output_type}"])
    return "\n".join(result)


def _normalize_field_list_body(body: str, *, instruction: str) -> str:
    title = _extract_markdown_title(body) or _infer_field_list_title(instruction)
    goal = _extract_section_plain_text(body, ("目标", "处理目标", "目标与适用条件")) or _infer_field_list_goal(instruction)
    conditions = _extract_section_bullets(body, ("适用条件", "目标与适用条件")) or _infer_field_list_conditions(instruction)
    field_labels = _extract_confirmed_field_labels_from_instruction(instruction)
    rules = [
        "字段全集以 runtimeContract.fieldLabels 和用户确认样例为准；本 Skill 正文中的字段名或示例字段不得缩小最终输出字段集合。",
        "按确认样例的字段列表抽取字段名、字段值和来源页码；字段命名保持稳定。",
        "即使字段来自表格或版式化区域，也输出为字段列表，不要改成 data_table。",
        "字段在当前样例中缺失时 value 保持为空字符串，不要编造。",
        "source_page 必须从识别结果动态获取；不要写死页码触发条件。",
        "默认不要输出 original_text 或长原文片段。",
    ]
    if field_labels:
        rules.insert(2, "当前样例确认字段包括：" + "、".join(field_labels[:16]) + "；这些字段用于校验样例，不代表新文档运行时的固定字段全集。")
    output_format = _build_field_list_output_format_section(field_labels)
    return "\n\n".join(
        [
            f"# {title}",
            "## 目标\n" + _truncate_text(goal, 180),
            "## 适用条件\n" + "\n".join(f"- {_truncate_text(item, 90)}" for item in conditions[:3]),
            _build_runtime_contract_priority_section(output_kind="field_list"),
            _build_domain_semantics_section(field_labels, output_kind="field_list"),
            _build_evidence_rules_section(output_kind="field_list"),
            _build_conflict_and_missing_section(output_kind="field_list"),
            "## 提取规则\n" + "\n".join(f"- {item}" for item in rules),
            output_format,
        ]
    ).strip()


def _build_domain_semantics_section(field_labels: list[str], *, output_kind: str) -> str:
    if output_kind == "record_collection":
        target = "每条记录的字段"
    elif output_kind == "data_table":
        target = "表头、列、行和表格区域"
    else:
        target = "字段"
    sample_line = f"\n- 当前样例涉及的字段或列示例：{'、'.join(field_labels[:12])}；这些名称用于说明语义判断，不是固定别名表或字段全集。" if field_labels else ""
    return (
        "## 领域语义\n"
        f"- {target}含义以 runtimeContract、确认样例和本 Skill 目标共同确定。{sample_line}\n"
        "- 名称、表头或角色称谓不完全一致时，结合上下文、动作关系、所属模块和版式位置判断。\n"
        "- 本节是语义判断方法，不是固定别名表；证据不足时不得强行映射。"
    )


def _build_runtime_contract_priority_section(*, output_kind: str) -> str:
    if output_kind == "field_list":
        contract_rule = "字段全集、字段顺序、缺失字段保留规则以 runtimeContract.fieldLabels 和用户确认样例为准。"
        coverage_rule = "输出必须覆盖 runtimeContract 要求的全部字段；字段缺失时保留该字段并将 value 置为空字符串。"
    elif output_kind == "record_collection":
        contract_rule = "记录结构、必填列和记录完整性以 runtimeContract 和 output.required 为准。"
        coverage_rule = "不得因为 Skill 示例只展示部分列或部分行而丢弃运行契约要求的记录字段。"
    elif output_kind == "data_table":
        contract_rule = "表格结构、行列关系和结构保真要求以 runtimeContract 和当前 Evidence 为准。"
        coverage_rule = "不得因为 Skill 示例是简单二维表而静默扁平化复杂表头、合并单元格或矩阵结构。"
    else:
        contract_rule = "输出结构以 runtimeContract 为准。"
        coverage_rule = "不得用 Skill 正文中的历史示例覆盖本次运行契约。"
    return (
        "## 运行契约优先级\n"
        f"- runtimeContract 是本次运行的最高优先级输出契约；{contract_rule}\n"
        "- Skill.md 正文负责领域理解、证据判断和缺失处理；正文中出现的字段名、示例字段或历史样例不得缩小 runtimeContract 的要求。\n"
        f"- {coverage_rule}"
    )


def _ensure_runtime_contract_priority_section(body: str, *, output_kind: str) -> str:
    if re.search(r"(?m)^##\s+运行契约优先级\s*$", body):
        return body
    insert_section = _build_runtime_contract_priority_section(output_kind=output_kind)
    if re.search(r"(?m)^##\s+领域语义\s*$", body):
        return _insert_markdown_section_before(body, "领域语义", insert_section)
    if re.search(r"(?m)^##\s+提取规则\s*$", body):
        return _insert_markdown_section_before(body, "提取规则", insert_section)
    if re.search(r"(?m)^##\s+输出格式\s*$", body):
        return _insert_markdown_section_before(body, "输出格式", insert_section)
    return f"{body}\n\n{insert_section}".strip()


def _soften_field_list_fixed_field_language(body: str) -> str:
    body = re.sub(
        r"(?m)^-\s*优先覆盖确认样例中的字段[:：]\s*([^。\n]+)。?\s*$",
        r"- 当前样例确认字段包括：\1；这些字段用于校验样例，不代表新文档运行时的固定字段全集。",
        body,
    )
    body = re.sub(
        r"(?m)^-\s*字段（([^）]+)）含义以\s*runtimeContract、确认样例和本 Skill 目标共同确定。",
        r"- 字段含义以 runtimeContract、确认样例和本 Skill 目标共同确定。\n- 当前样例涉及的字段示例：\1；这些名称用于说明语义判断，不是固定别名表或字段全集。",
        body,
    )
    if "上方 JSON 只是单项结构示例" not in body and re.search(r"(?m)^##\s+输出格式\s*$", body):
        body = re.sub(
            r"(?m)^-\s*`fields`\s+为字段数组",
            "- 上方 JSON 只是单项结构示例，不代表字段全集；实际字段集合必须以 runtimeContract.fieldLabels 和用户确认样例为准。\n- `fields` 为字段数组",
            body,
            count=1,
        )
    return body


def _build_evidence_rules_section(*, output_kind: str) -> str:
    if output_kind == "data_table":
        scope_rule = "保留表格结构、表头层级、行列关系、合并单元格和来源页码。"
    elif output_kind == "record_collection":
        scope_rule = "优先使用候选记录表、表头、续表关系和行完整性证据。"
    else:
        scope_rule = "优先使用文档树命中范围、相邻标题、表格字段区、文本块和 OCR 行。"
    return (
        "## 证据规则\n"
        f"- {scope_rule}\n"
        "- 非空值必须能在当前 Evidence 中追溯到对应页面或短证据。\n"
        "- 长表只使用与目标输出相关的证据窗口，不能把窗口外内容当作已知事实。"
    )


def _build_conflict_and_missing_section(*, output_kind: str) -> str:
    missing_rule = (
        "结构不确定时保留原始证据并记录复核问题，不静默扁平化。"
        if output_kind == "data_table"
        else "仍无法确认时返回空字符串或记录复核问题，不编造、不删除目标字段。"
    )
    return (
        "## 冲突与缺失\n"
        "- 多个候选冲突时，选择与 runtimeContract、定位模块和邻近证据最一致的值。\n"
        f"- {missing_rule}"
    )


def _infer_field_list_title(instruction: str) -> str:
    match = re.search(r"数据类型\s*[:：]\s*([^\n。；;]+)", instruction)
    value = match.group(1).strip() if match else "字段信息"
    return value if value.endswith("提取") else f"{value}提取"


def _infer_field_list_goal(instruction: str) -> str:
    match = re.search(r"处理目标\s*[:：]\s*([^\n]+)", instruction)
    if match:
        return match.group(1).strip()
    return "提取文档中可识别的关键字段和值，整理为可复核的字段列表。"


def _infer_field_list_conditions(instruction: str) -> list[str]:
    data_type_match = re.search(r"数据类型\s*[:：]\s*([^\n。；;]+)", instruction)
    data_type = data_type_match.group(1).strip() if data_type_match else "目标信息"
    labels = _extract_confirmed_field_labels_from_instruction(instruction)
    conditions = [f"页面或内容块包含与“{data_type}”相关的字段信息。"]
    if labels:
        conditions.append("可识别到这些字段中的一个或多个：" + "、".join(labels[:10]) + "。")
    conditions.append("字段可以来自表格、键值对或版式化文本，但输出仍保持字段列表协议。")
    return conditions


def _build_field_list_output_format_section(field_labels: list[str]) -> str:
    first_label = field_labels[0] if field_labels else "字段名"
    example = {
        "fields": [
            {
                "label": first_label,
                "value": "从识别结果填入",
                "source_page": "第 X 页",
            }
        ]
    }
    return (
        "## 输出格式\n\n"
        f"```json\n{json.dumps(example, ensure_ascii=False, indent=2)}\n```\n\n"
        "- 上方 JSON 只是单项结构示例，不代表字段全集；实际字段集合必须以 runtimeContract.fieldLabels 和用户确认样例为准。\n"
        "- `fields` 为字段数组，每项包含 `label`、`value`、`source_page`。\n"
        "- 字段缺失时 `value` 返回空字符串；不要删除确认样例中应覆盖的字段。\n"
        "- 不要返回 `headers`、`rows`、`mergeNotes` 等表格协议字段。"
    )


def _extract_confirmed_field_labels_from_instruction(instruction: str) -> list[str]:
    placeholder_labels = {
        "字段名",
        "字段",
        "field",
        "field_name",
        "label",
        "name",
        "从识别结果填入",
        "字段值",
    }
    labels: list[str] = []
    for pattern in (r'"label"\s*:\s*"([^"]+)"', r'"field_name"\s*:\s*"([^"]+)"', r'"name"\s*:\s*"([^"]+)"'):
        for match in re.finditer(pattern, instruction):
            value = match.group(1).strip()
            if value and value not in placeholder_labels and value not in labels:
                labels.append(value)
    return labels


def _extract_confirmed_record_fields_from_instruction(instruction: str) -> list[str]:
    match = re.search(r'"records"\s*:\s*\[\s*\{([\s\S]*?)\}', instruction)
    if not match:
        return []
    fields: list[str] = []
    for key in re.findall(r'"([^"]+)"\s*:', match.group(1)):
        if key not in {"source_page", "page"} and key not in fields:
            fields.append(key)
    return fields


def _normalize_data_table_body(body: str, *, instruction: str) -> str:
    title = _extract_markdown_title(body) or _infer_data_table_title(instruction)
    goal = _extract_section_plain_text(body, ("目标", "处理目标", "目标与适用条件")) or _infer_data_table_goal(instruction)
    conditions = _extract_section_bullets(body, ("适用条件", "目标与适用条件")) or _infer_data_table_conditions(instruction)
    rules = _infer_data_table_rules(instruction)
    output_format = _build_data_table_output_format_section()
    return "\n\n".join(
        [
            f"# {title}",
            "## 目标\n" + _truncate_text(goal, 180),
            "## 适用条件\n" + "\n".join(f"- {_truncate_text(item, 90)}" for item in conditions[:3]),
            _build_domain_semantics_section([], output_kind="data_table"),
            _build_evidence_rules_section(output_kind="data_table"),
            _build_conflict_and_missing_section(output_kind="data_table"),
            "## 提取规则\n" + "\n".join(f"- {item}" for item in rules),
            output_format,
        ]
    ).strip()


def _build_data_table_output_format_section() -> str:
    example = {
        "headers": ["列1", "列2"],
        "rows": [
            {
                "列1": "从识别结果填入",
                "列2": "从识别结果填入",
                "source_page": "第 X 页",
            }
        ],
        "mergeNotes": [
            {
                "text": "合并单元格、跨列表头或内部结构说明；没有则返回空数组",
                "source_page": "第 X 页",
            }
        ],
        "evidence": [
            {
                "source_page": "第 X 页",
                "text": "短证据或表格片段；不需要逐行重复原文",
            }
        ],
    }
    return (
        "## 输出格式\n\n"
        f"```json\n{json.dumps(example, ensure_ascii=False, indent=2)}\n```\n\n"
        "- `headers` 保留表头层级和列顺序，多级表头可用 `/` 连接。\n"
        "- `rows` 每项代表原表一行；只保留必要字段和 `source_page`，不要逐行重复长原文。\n"
        "- `mergeNotes` 只记录合并单元格、跨列表头或内部结构说明；没有则返回空数组。\n"
        "- `evidence` 只放表格整体或关键行的短证据，避免重复长原文；只能基于识别结果填值。"
    )


def _extract_markdown_title(body: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return match.group(1).strip() if match else ""


def _extract_section_plain_text(body: str, titles: tuple[str, ...]) -> str:
    for title in titles:
        section = _extract_markdown_section(body, title)
        if not section:
            continue
        cleaned = re.sub(r"(?m)^\s*[-*]\s*", "", section)
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            return cleaned
    return ""


def _extract_section_bullets(body: str, titles: tuple[str, ...]) -> list[str]:
    for title in titles:
        section = _extract_markdown_section(body, title)
        if not section:
            continue
        bullets = [
            re.sub(r"\*\*(.+?)\*\*", r"\1", match.group(1)).strip(" ：:")
            for match in re.finditer(r"(?m)^\s*[-*]\s+(.+?)\s*$", section)
        ]
        bullets = [item for item in bullets if item]
        if bullets:
            return bullets
    return []


def _extract_markdown_section(body: str, title: str) -> str:
    pattern = rf"(?ms)^#{{1,6}}\s+{re.escape(title)}\s*$\n?(.*?)(?=^#{{1,6}}\s+|\Z)"
    match = re.search(pattern, body)
    return match.group(1).strip() if match else ""


def _infer_data_table_title(instruction: str) -> str:
    match = re.search(r"数据类型[：:]\s*([^\n]+)", instruction)
    name = match.group(1).strip() if match else "表格数据"
    return f"{name}提取"


def _infer_data_table_goal(instruction: str) -> str:
    match = re.search(r"处理目标[：:]\s*([^\n]+)", instruction)
    if match:
        return match.group(1).strip()
    return "从文档中提取符合条件的表格，整理为可复核的结构化表格。"


def _infer_data_table_conditions(instruction: str) -> list[str]:
    source = ""
    source_match = re.search(r"样例来源[：:]\s*([^\n]+)", instruction)
    if source_match:
        source = source_match.group(1).strip()
    if source:
        return [f"内容形态与“{source}”相似，包含可识别的表头、行列关系或表格结构。"]
    return ["页面中存在需要保留表头、行列关系或合并单元格含义的表格。"]


def _infer_data_table_rules(instruction: str) -> list[str]:
    rules = [
        "识别所有符合适用条件的表格；多个表格分别输出，不合并无关表格。",
        "保留表头层级、列顺序、行顺序、空单元格和原始语义。",
        "合并单元格、跨列表头、分组表头或上下结构关系写入 `mergeNotes`。",
        "每行和整体证据默认保留来源页码等轻量来源字段。",
    ]
    if "不要写死页码" in instruction:
        rules[3] = "页码只作为证据动态取值；每行和整体证据默认保留来源页码，不要编造。"
    return rules


def _truncate_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _resolve_record_collection_required_fields(*, output: dict[str, Any], body: str, instruction: str) -> list[str]:
    required = output.get("required")
    if isinstance(required, list):
        fields = [str(item).strip() for item in required if str(item).strip()]
        if fields:
            return fields[:20]
    return _extract_required_field_names(instruction) or _infer_required_fields_from_output_example(_normalize_output_example(body))


def _normalize_record_collection_body(body: str, *, required_fields: list[str]) -> str:
    normalized = body.strip()
    required_text = "、".join(required_fields) if required_fields else "输出示例中的字段"
    sections: list[str] = []
    if "领域语义" not in normalized:
        sections.append(_build_domain_semantics_section(required_fields, output_kind="record_collection"))
    if "证据规则" not in normalized:
        sections.append(_build_evidence_rules_section(output_kind="record_collection"))
    if "冲突与缺失" not in normalized:
        sections.append(_build_conflict_and_missing_section(output_kind="record_collection"))
    if "# 协议约束" not in normalized:
        sections.append(
            f"# 协议约束\n\n"
            f"- 最终输出必须是 JSON 对象，顶层只放 records、summary、validationErrors 等平台允许字段。\n"
            f"- records 中每条记录至少应包含：{required_text}。\n"
            f"- 不要返回裸数组。"
        )
    if not sections:
        return normalized
    return f"{normalized}\n\n" + "\n\n".join(sections)


def _ensure_record_collection_required(frontmatter: str, required_fields: list[str]) -> str:
    required_json = json.dumps(required_fields, ensure_ascii=False)
    replaced = _replace_required_frontmatter_block(frontmatter, required_json)
    if replaced != frontmatter:
        return replaced
    return re.sub(r"(?m)^(\s*)type\s*:\s*record_collection\s*$", rf"\1type: record_collection\n\1required: {required_json}", frontmatter, count=1)


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
