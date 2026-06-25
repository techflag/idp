# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Sample-preview request adapter for application workshop extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from uuid import uuid4

from app.domain.models import PromptRunRecord
from app.services.extraction_runtime.adapters import build_prompt_run_runtime_request
from app.services.extraction_runtime.models import ExtractionRuntimeRequest


@dataclass
class SamplePreviewRuntimeBuild:
    """Runtime request plus workshop-facing metadata."""

    request: ExtractionRuntimeRequest
    runtime_pages: list[Any]
    selected_content: list[dict[str, Any]]
    runtime_contract: dict[str, Any]
    skill_meta: dict[str, Any]


def build_sample_preview_runtime_request(
    *,
    pages: list[Any],
    selected_page_numbers: list[int],
    sample_id: str,
    context_id: str,
    instruction: str,
    expected_output: str,
    data_type_name: str,
    source_label: str,
    source_text: str,
    tree_node_id: str | None,
    content_refs: list[dict[str, Any]],
    output_type: str,
    renderer: str,
) -> SamplePreviewRuntimeBuild:
    runtime_pages = [
        page
        for page in pages
        if _page_no(page) in set(selected_page_numbers)
    ] or pages
    if not runtime_pages:
        raise ValueError("sample preview requires at least one page")

    selected_content = _selected_content(
        content_refs=content_refs,
        selected_page_numbers=selected_page_numbers,
        source_label=source_label,
        data_type_name=data_type_name,
        source_text=source_text,
        tree_node_id=tree_node_id,
    )
    prompt_template = _sample_preview_prompt_template(
        instruction=instruction,
        expected_output=expected_output,
        data_type_name=data_type_name,
    )
    skill_meta = {
        "id": f"sample_preview_{uuid4().hex[:8]}",
        "version": "sample-preview",
        "name": data_type_name or "样例抽取",
        "category": "extraction",
        "sourceTypes": ["text", "html_table"],
        "executor": "llm_structured",
        "inputBuilder": "page_compact",
        "renderer": renderer,
        "outputSchema": {"type": output_type},
        "promptTemplate": prompt_template,
    }
    runtime_contract = {
        "contractVersion": "sample_preview_runtime_contract_v1",
        "outputType": output_type,
        "selectedContent": selected_content,
        "selectedSourceText": _sample_source_text(source_text, limit=20000),
        "matchedPageNos": selected_page_numbers,
        "outputProtocol": sample_preview_output_protocol(output_type=output_type),
        "rules": [
            "样例抽取必须遵守 runtimeContract.outputProtocol。",
            "字段、表头、记录和值只能来自 selectedContent 对应证据。",
            "如果证据不足，不要编造。",
        ],
    }
    start_page_no = min((_page_no(page) for page in runtime_pages), default=1) or 1
    end_page_no = max((_page_no(page) for page in runtime_pages), default=start_page_no) or start_page_no
    schema_definition = {
        "protocol": "sample_preview_extraction_v1",
        "sourceMode": "sample_preview",
        "skill": skill_meta,
        "config": {
            "runtimeContract": runtime_contract,
            "applicationScope": {
                "inputMapping": {
                    "matchedPageNos": selected_page_numbers,
                    "contentRefs": selected_content,
                },
                "targetMapping": {"outputType": output_type},
            },
        },
    }
    run = PromptRunRecord(
        id=f"sample-preview-{uuid4().hex[:12]}",
        taskId=sample_id,
        documentId=context_id or sample_id,
        runType="page_group" if start_page_no != end_page_no else "page",
        runName=data_type_name or "样例抽取",
        promptName=data_type_name or "样例抽取",
        promptText=prompt_template,
        startPageNo=start_page_no,
        endPageNo=end_page_no,
        status="running",
        runPurpose="parse_prompt",
        schemaDefinition=schema_definition,
    )
    return SamplePreviewRuntimeBuild(
        request=build_prompt_run_runtime_request(run=run, pages=runtime_pages),
        runtime_pages=runtime_pages,
        selected_content=selected_content,
        runtime_contract=runtime_contract,
        skill_meta=skill_meta,
    )


def sample_preview_output_protocol(*, output_type: str) -> dict[str, Any]:
    if output_type == "field_list":
        return {
            "jsonShape": {"fields": [{"label": "字段名", "value": "从 Evidence 填入", "source_page": "第 X 页或空字符串"}]},
            "missingValue": "",
            "forbiddenTopLevelKeys": ["headers", "rows", "mergeNotes"],
        }
    if output_type == "record_collection":
        return {
            "jsonShape": {"records": [{"字段名": "从 Evidence 填入"}]},
            "missingValue": "",
            "preserveTextRecordCompleteness": True,
            "description": "当记录来自章节、列表或段落时，记录字段必须覆盖该记录标题下的连续文本，不得只保留摘要。",
        }
    if output_type == "data_table":
        return {
            "jsonShape": {"headers": ["表头"], "rows": [["单元格值"]]},
            "preserveTableStructure": True,
        }
    return {"jsonShape": {"outputs": []}}


def _selected_content(
    *,
    content_refs: list[dict[str, Any]],
    selected_page_numbers: list[int],
    source_label: str,
    data_type_name: str,
    source_text: str,
    tree_node_id: str | None,
) -> list[dict[str, Any]]:
    selected = [_strip_visual_geometry(item) for item in content_refs if isinstance(item, dict)]
    if selected:
        return selected
    return [
        {
            "source": "sample_preview",
            "title": source_label or data_type_name or "样例内容",
            "pages": selected_page_numbers,
            "treeNodeId": tree_node_id or "",
            "excerpt": _sample_excerpt(source_text, limit=500),
        }
    ]


def _strip_visual_geometry(value: Any) -> Any:
    geometry_keys = {
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
    if isinstance(value, dict):
        return {
            str(key): _strip_visual_geometry(item)
            for key, item in value.items()
            if str(key).replace("_", "").lower() not in geometry_keys
        }
    if isinstance(value, list):
        return [_strip_visual_geometry(item) for item in value]
    return value


def _sample_preview_prompt_template(
    *,
    instruction: str,
    expected_output: str,
    data_type_name: str,
) -> str:
    prompt_parts = [
        f"# {data_type_name or '样例抽取'}",
        instruction.strip(),
    ]
    if expected_output.strip():
        prompt_parts.append("## 输出要求\n" + expected_output.strip())
    prompt_parts.extend(
        [
            "## 运行规则",
            "- runtimeContract 是本次样例抽取的最终输出契约。",
            "- 只基于 Evidence 中可追溯的文本、表格、列表或文档树模块抽取。",
            "- 缺失信息保持空字符串或进入复核，不编造。",
        ]
    )
    return "\n\n".join(part for part in prompt_parts if part.strip())


def _sample_excerpt(value: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _sample_source_text(value: str, limit: int = 20000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...（样例来源已截断）"


def _page_no(page: Any) -> int:
    try:
        return int(getattr(page, "pageNo", 0) or 0)
    except (TypeError, ValueError):
        return 0
