"""Task 6 prompt execution pipeline built on top of MinerU page artifacts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from html import unescape
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import tempfile
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

from app.core.config import AppSettings
from app.domain.models import LlmCallTraceRecord, PromptConfigRecord, PromptRunRecord, TaskResultArtifactRecord
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    FailedPromptRerunRequest,
    ExtractionSkillRunRequest,
    ObjectOperationExecutionResponse,
    ObjectOperationRunRequest,
    OperationTargetRef,
    PostProcessRunRequest,
    PromptExecutionRequest,
    PromptExecutionPageContext,
    PromptExecutionPageContextPage,
    PromptExecutionResponse,
    PromptRunRecordResponse,
    SchemaRunRequest,
    SkillRunRequest,
    SummaryExecutionRequest,
    WorkbenchPageDetail,
)
from app.services.business_skills import BusinessSkillRegistry, merge_skill_config
from app.services.extraction_skills import (
    ExtractionSkillRegistry,
    build_compact_extraction_facts,
    merge_extraction_skill_config,
)
from app.services.extraction_result_compat import legacy_table_from_data_table
from app.services.llm import (
    PromptRunOutput,
    PromptLlmService,
    _build_field_keyword_groups_from_fields,
    _collect_table_header_candidates,
    _extract_html_row_cells,
    _extract_prompt_field_keyword_groups,
    _filter_target_table_blocks_for_prompt,
    _infer_table_fields_from_prompt,
    _score_row_cells_against_prompt_fields,
    _split_html_table_rows,
    _split_modal_prompts,
)
from app.services.oss import OssStorageService
from app.services.result_artifacts import build_task_object_key, write_json_artifact
from app.services.runtime_evidence import (
    FIELD_LIST_INITIAL_MAX_TOTAL_TABLE_ROWS,
    FIELD_LIST_REVIEW_MAX_TOTAL_TABLE_ROWS,
    apply_field_list_global_row_budget,
    compact_application_scope_for_runtime,
    enrich_field_list_extraction_config,
)
from app.services.evidence_v2 import (
    build_evidence_v2_failure_package,
    build_evidence_v2_model_package,
    build_evidence_v2_shadow_package,
)
from app.services.extraction_runtime import (
    ExtractionRuntimeKernel,
    ExtractionRuntimePorts,
    ExtractionRuntimeRequest,
    ExtractionRuntimeResult,
)
from app.services.extraction_runtime.adapters import build_prompt_run_runtime_request
from app.services.runtime_store import JsonRuntimeStore
from app.services.table_parser import parse_table_html
from app.services.workbench_builder import (
    build_extraction_result_payload,
    build_object_operation_result,
    build_page_operation_targets,
)

logger = logging.getLogger("uvicorn.error")


def _application_extraction_scope(schema_definition: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema_definition, dict):
        return {}
    if schema_definition.get("protocol") == "application_extraction_step_v1":
        input_mapping = schema_definition.get("inputMapping") if isinstance(schema_definition.get("inputMapping"), dict) else {}
        target_mapping = schema_definition.get("targetMapping") if isinstance(schema_definition.get("targetMapping"), dict) else {}
    else:
        config = schema_definition.get("config") if isinstance(schema_definition.get("config"), dict) else {}
        scope = schema_definition.get("applicationScope")
        if not isinstance(scope, dict):
            scope = config.get("applicationScope")
        if not isinstance(scope, dict):
            return {}
        input_mapping = scope.get("inputMapping") if isinstance(scope.get("inputMapping"), dict) else {}
        target_mapping = scope.get("targetMapping") if isinstance(scope.get("targetMapping"), dict) else {}
        if not input_mapping and not target_mapping:
            return {}
    content_refs = input_mapping.get("contentRefs") if isinstance(input_mapping.get("contentRefs"), list) else []
    return {
        "inputMapping": input_mapping,
        "targetMapping": target_mapping,
        "contentRefs": content_refs,
        "matchedPageNos": input_mapping.get("matchedPageNos") if isinstance(input_mapping.get("matchedPageNos"), list) else [],
        "locatorResult": target_mapping.get("locatorResult") if isinstance(target_mapping.get("locatorResult"), dict) else {},
        "planTargets": target_mapping.get("planTargets") if isinstance(target_mapping.get("planTargets"), list) else [],
    }


def _explicit_runtime_contract(schema_definition: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema_definition, dict):
        return {}
    contract = schema_definition.get("runtimeContract")
    if isinstance(contract, dict):
        return contract
    config = schema_definition.get("config") if isinstance(schema_definition.get("config"), dict) else {}
    contract = config.get("runtimeContract")
    return contract if isinstance(contract, dict) else {}


def _application_runtime_contract(
    *,
    schema_definition: dict[str, Any] | None,
    skill_meta: dict[str, Any],
) -> dict[str, Any]:
    scope = _application_extraction_scope(schema_definition)
    explicit_contract = _explicit_runtime_contract(schema_definition)
    if not scope and not explicit_contract:
        return {}
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(explicit_contract.get("outputType") or output_schema.get("type") or "custom").strip() or "custom"
    explicit_labels = explicit_contract.get("fieldLabels") if isinstance(explicit_contract.get("fieldLabels"), list) else []
    field_labels = [
        str(item or "").strip()
        for item in explicit_labels
        if str(item or "").strip()
    ] or _application_target_field_labels(schema_definition)
    content_refs = scope.get("contentRefs") if isinstance(scope.get("contentRefs"), list) else []
    selected_content = explicit_contract.get("selectedContent") if isinstance(explicit_contract.get("selectedContent"), list) else []
    if not isinstance(selected_content, list):
        selected_content = []
    for ref in content_refs:
        if not isinstance(ref, dict):
            continue
        selected_content.append(
            {
                "source": str(ref.get("source") or ref.get("kind") or "").strip(),
                "targetId": str(ref.get("targetId") or "").strip(),
                "title": str(ref.get("title") or ref.get("label") or ref.get("name") or "").strip(),
                "treeNodeId": str(ref.get("treeNodeId") or ref.get("nodeId") or "").strip(),
                "nodeId": str(ref.get("nodeId") or ref.get("treeNodeId") or "").strip(),
                "blockIds": [
                    str(item or "").strip()
                    for item in (ref.get("blockIds") if isinstance(ref.get("blockIds"), list) else [])
                    if str(item or "").strip()
                ],
                "blockIdsExact": [
                    str(item or "").strip()
                    for item in (ref.get("blockIdsExact") if isinstance(ref.get("blockIdsExact"), list) else [])
                    if str(item or "").strip()
                ],
                "pages": ref.get("pages") if isinstance(ref.get("pages"), list) else [],
                "evidencePages": ref.get("evidencePages") if isinstance(ref.get("evidencePages"), list) else [],
                "excerpt": str(ref.get("excerpt") or ref.get("summary") or "").strip()[:500],
            }
        )
    table_headers = [
        str(item or "").strip()
        for item in (explicit_contract.get("tableHeaders") if isinstance(explicit_contract.get("tableHeaders"), list) else [])
        if str(item or "").strip()
    ]
    record_fields = [
        str(item or "").strip()
        for item in (explicit_contract.get("recordFields") if isinstance(explicit_contract.get("recordFields"), list) else [])
        if str(item or "").strip()
    ]
    expected_counts = explicit_contract.get("expectedCounts") if isinstance(explicit_contract.get("expectedCounts"), dict) else {}
    output_protocol = explicit_contract.get("outputProtocol") if isinstance(explicit_contract.get("outputProtocol"), dict) else {}
    contract: dict[str, Any] = {
        "contractVersion": str(explicit_contract.get("contractVersion") or "application_runtime_contract_v1"),
        "outputType": output_type,
        "fieldLabels": field_labels,
        "tableHeaders": table_headers,
        "recordFields": record_fields,
        "expectedCounts": expected_counts,
        "selectedContent": selected_content,
        "matchedPageNos": explicit_contract.get("matchedPageNos") if isinstance(explicit_contract.get("matchedPageNos"), list) else (scope.get("matchedPageNos") if isinstance(scope.get("matchedPageNos"), list) else []),
        "rules": [
            "runtimeContract 是本次应用运行的最终契约，优先于 Skill 正文中的旧字段清单。",
            "输出必须遵守 runtimeContract.outputProtocol；字段、表头、记录字段和值只能来自 facts 与 selectedContent 对应证据。",
            "字段或记录项缺失时按输出协议留空，不要编造；表格结构不确定时保留复核原因。",
            "字段名、表头和角色称谓与 facts 不要求字面一致，必须按 Skill 语义、上下文和证据位置判断。",
            "即使信息在表格、合并单元格、旋转文本、图文块或键值串中，也应作为可抽取 facts 读取。",
        ],
    }
    if output_protocol:
        contract["outputProtocol"] = output_protocol
    explicit_rules = explicit_contract.get("rules") if isinstance(explicit_contract.get("rules"), list) else []
    for rule in explicit_rules:
        text = str(rule or "").strip()
        if text and text not in contract["rules"]:
            contract["rules"].append(text)
    if output_type == "field_list" and "outputProtocol" not in contract:
        contract["outputProtocol"] = {
            "jsonShape": {"fields": [{"label": "字段名", "value": "从 facts 填入", "source_page": "第 X 页或空字符串"}]},
            "requiredFieldLabels": field_labels,
            "missingValue": "",
            "forbiddenTopLevelKeys": ["headers", "rows", "mergeNotes"],
        }
    return contract


def _application_target_field_labels(schema_definition: dict[str, Any] | None) -> list[str]:
    scope = _application_extraction_scope(schema_definition)
    target_mapping = scope.get("targetMapping") if isinstance(scope.get("targetMapping"), dict) else {}
    labels: list[str] = []
    for target in target_mapping.get("generatedTargets") or []:
        if not isinstance(target, dict) or target.get("type") != "field":
            continue
        label = str(target.get("label") or target.get("fieldKey") or "").strip()
        if label and label not in labels:
            labels.append(label)
    selector = target_mapping.get("targetSelector") if isinstance(target_mapping.get("targetSelector"), dict) else {}
    profile = selector.get("locatorProfile") if isinstance(selector.get("locatorProfile"), dict) else {}
    for shape in profile.get("confirmedOutputShape") or []:
        if not isinstance(shape, dict) or not isinstance(shape.get("fieldLabels"), list):
            continue
        for item in shape["fieldLabels"]:
            label = str(item or "").strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def _enrich_field_list_extraction_result_from_application_scope(
    extraction_result: dict[str, Any],
    *,
    schema_definition: dict[str, Any] | None,
) -> dict[str, Any]:
    expected_labels = _application_target_field_labels(schema_definition)
    if not expected_labels:
        return extraction_result
    outputs = extraction_result.get("outputs")
    if not isinstance(outputs, list):
        return extraction_result
    next_outputs: list[dict[str, Any]] = []
    changed = False
    for output in outputs:
        if not isinstance(output, dict) or output.get("type") != "field_list":
            next_outputs.append(output)
            continue
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        fields = [dict(item) for item in data.get("fields") or [] if isinstance(item, dict)]
        fields_by_label = {str(item.get("label") or "").strip(): item for item in fields}
        for label in expected_labels:
            field = fields_by_label.get(label)
            if field is None:
                field = {"label": label, "value": "", "source_page": ""}
                fields.append(field)
                fields_by_label[label] = field
                changed = True
        next_data = dict(data)
        next_data["fields"] = fields
        next_output = dict(output)
        next_output["data"] = next_data
        next_outputs.append(next_output)
    if not changed:
        return extraction_result
    enriched = dict(extraction_result)
    enriched["outputs"] = next_outputs
    legacy = _derive_legacy_extraction_fields(next_outputs)
    enriched["fields"] = legacy["fields"]
    enriched["tables"] = legacy["tables"]
    enriched["structuredObjects"] = legacy["structuredObjects"]
    summary = str(enriched.get("summary") or "")
    if summary:
        field_count = sum(
            len(output.get("data", {}).get("fields", []))
            for output in next_outputs
            if isinstance(output, dict) and isinstance(output.get("data"), dict)
        )
        enriched["summary"] = re.sub(r"已提取\s*\d+\s*个", f"已提取 {field_count} 个", summary)
    return enriched


def _field_list_extraction_needs_llm_review(
    extraction_result: dict[str, Any],
    *,
    schema_definition: dict[str, Any] | None,
) -> bool:
    expected_labels = _application_target_field_labels(schema_definition)
    if not expected_labels:
        return False
    outputs = extraction_result.get("outputs")
    if not isinstance(outputs, list):
        return False
    for output in outputs:
        if not isinstance(output, dict) or output.get("type") != "field_list":
            continue
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        fields = data.get("fields") if isinstance(data.get("fields"), list) else []
        fields_by_label = {
            str(item.get("label") or "").strip(): str(item.get("value") or "").strip()
            for item in fields
            if isinstance(item, dict)
        }
        missing_or_empty = [
            label
            for label in expected_labels
            if label not in fields_by_label or not fields_by_label[label]
        ]
        return bool(missing_or_empty)
    return False


def _field_list_extraction_has_any_target_value(
    extraction_result: dict[str, Any],
    *,
    schema_definition: dict[str, Any] | None,
) -> bool:
    expected_labels = set(_application_target_field_labels(schema_definition))
    if not expected_labels:
        return False
    outputs = extraction_result.get("outputs")
    if not isinstance(outputs, list):
        return False
    for output in outputs:
        if not isinstance(output, dict) or output.get("type") != "field_list":
            continue
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        fields = data.get("fields") if isinstance(data.get("fields"), list) else []
        for item in fields:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            if label in expected_labels and value:
                return True
    return False


def _preserve_review_field_source_pages(
    *,
    raw_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep source_page when the review model returns the same field value without it."""

    if not isinstance(previous_payload, dict):
        return raw_payload
    fields = raw_payload.get("fields")
    previous_fields = previous_payload.get("fields")
    if not isinstance(fields, list) or not isinstance(previous_fields, list):
        return raw_payload

    previous_by_label: dict[str, dict[str, Any]] = {}
    for item in previous_fields:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("key") or "").strip()
        if label and (item.get("source_page") or item.get("page")):
            previous_by_label[label] = item
    if not previous_by_label:
        return raw_payload

    changed = False
    next_fields: list[Any] = []
    for item in fields:
        if not isinstance(item, dict):
            next_fields.append(item)
            continue
        label = str(item.get("label") or item.get("key") or "").strip()
        previous = previous_by_label.get(label)
        if not previous or item.get("source_page") or item.get("page"):
            next_fields.append(item)
            continue
        if str(previous.get("value") or "") != str(item.get("value") or ""):
            next_fields.append(item)
            continue
        source_page = previous.get("source_page") or previous.get("page")
        if not source_page:
            next_fields.append(item)
            continue
        next_item = dict(item)
        next_item["source_page"] = source_page
        next_fields.append(next_item)
        changed = True

    if not changed:
        return raw_payload
    next_payload = dict(raw_payload)
    next_payload["fields"] = next_fields
    return next_payload


def _content_ref_pages(content_refs: list[dict[str, Any]]) -> set[int]:
    pages: set[int] = set()
    for ref in content_refs or []:
        if not isinstance(ref, dict):
            continue
        values: list[Any] = []
        values.extend(ref.get("pages") or [])
        values.extend(ref.get("evidencePages") or [])
        values.append(ref.get("pageNo"))
        for value in values:
            try:
                page_no = int(value)
            except (TypeError, ValueError):
                continue
            if page_no > 0:
                pages.add(page_no)
    return pages


def _content_ref_block_ids(content_refs: list[dict[str, Any]]) -> set[str]:
    block_ids: set[str] = set()
    for ref in content_refs or []:
        if not isinstance(ref, dict):
            continue
        for key in ("targetId", "blockId", "nodeId"):
            text = str(ref.get(key) or "").strip()
            if text:
                block_ids.add(text)
        for block_id in ref.get("blockIds") or []:
            text = str(block_id or "").strip()
            if text:
                block_ids.add(text)
        for block_id in ref.get("blockIdsExact") or []:
            text = str(block_id or "").strip()
            if text:
                block_ids.add(text)
    return block_ids


def _content_refs_include_document_tree_modules(content_refs: list[dict[str, Any]]) -> bool:
    for ref in content_refs or []:
        if not isinstance(ref, dict):
            continue
        source = str(ref.get("source") or ref.get("kind") or "").strip()
        if source == "document_tree_module":
            return True
        if str(ref.get("treeNodeId") or "").strip():
            return True
    return False


def _collect_fact_table_blocks(facts_payload: dict[str, Any]) -> list[dict[str, Any]]:
    table_blocks: list[dict[str, Any]] = []
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = page.get("pageNo")
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
            rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
            normalized_rows = [
                [str(cell or "").strip() for cell in row]
                for row in rows
                if isinstance(row, list) and any(str(cell or "").strip() for cell in row)
            ]
            if not normalized_rows:
                continue
            try:
                normalized_page_no = int(page_no)
            except (TypeError, ValueError):
                normalized_page_no = 0
            source_ref = block.get("sourceRef") if isinstance(block.get("sourceRef"), dict) else {}
            try:
                fact_block_index = int(source_ref.get("factBlockIndex"))
            except (TypeError, ValueError):
                fact_block_index = block_index
            table_blocks.append(
                {
                    "pageNo": normalized_page_no,
                    "blockIndex": block_index,
                    "factBlockIndex": fact_block_index,
                    "blockId": str(block.get("id") or source_ref.get("blockId") or "").strip(),
                    "blockPosition": str(block.get("blockPosition") or source_ref.get("blockPosition") or "").strip(),
                    "sourceOrdinal": str(source_ref.get("sourceOrdinal") or "").strip(),
                    "title": str(block.get("title") or table_grid.get("title") or "").strip(),
                    "rows": normalized_rows,
                    "columnCount": max((len(row) for row in normalized_rows), default=0),
                }
            )
    return table_blocks


def _filter_fact_table_blocks_by_preview(
    *,
    full_table_blocks: list[dict[str, Any]],
    preview_table_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not full_table_blocks or not preview_table_blocks:
        return full_table_blocks
    preview_block_keys = {
        (int(block.get("pageNo") or 0), int(block.get("factBlockIndex") or block.get("blockIndex") or 0))
        for block in preview_table_blocks
    }
    if preview_block_keys:
        selected = [
            block for block in full_table_blocks
            if (int(block.get("pageNo") or 0), int(block.get("factBlockIndex") or block.get("blockIndex") or 0))
            in preview_block_keys
        ]
        if selected:
            return selected

    preview_id_keys = {
        (int(block.get("pageNo") or 0), str(block.get(key) or "").strip())
        for block in preview_table_blocks
        for key in ("blockId", "blockPosition", "sourceOrdinal")
        if str(block.get(key) or "").strip()
    }
    if preview_id_keys:
        selected = [
            block for block in full_table_blocks
            if any(
                (int(block.get("pageNo") or 0), str(block.get(key) or "").strip()) in preview_id_keys
                for key in ("blockId", "blockPosition", "sourceOrdinal")
            )
        ]
        if selected:
            return selected
    return full_table_blocks


def _estimate_json_payload_bytes(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return -1


def _build_extraction_payload_metrics(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    input_payload: dict[str, Any],
    full_facts_payload: dict[str, Any] | None = None,
    review_count: int = 0,
    table_fast_path: bool = False,
) -> dict[str, Any]:
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    fact_block_count = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        fact_block_count += len(blocks)

    table_blocks = _collect_fact_table_blocks(facts_payload)
    table_row_count = sum(len(block.get("rows") or []) for block in table_blocks)
    max_table_rows = max((len(block.get("rows") or []) for block in table_blocks), default=0)
    full_table_blocks = _collect_fact_table_blocks(full_facts_payload or facts_payload)
    full_table_row_count = sum(len(block.get("rows") or []) for block in full_table_blocks)
    return {
        "factsBytes": _estimate_json_payload_bytes(facts_payload),
        "fullFactsBytes": _estimate_json_payload_bytes(full_facts_payload) if full_facts_payload is not None else _estimate_json_payload_bytes(facts_payload),
        "evidenceIndexBytes": _estimate_json_payload_bytes(evidence_index),
        "inputPayloadBytes": _estimate_json_payload_bytes(input_payload),
        "pageCount": len(pages),
        "factBlockCount": fact_block_count,
        "tableCount": len(table_blocks),
        "tableRowCount": table_row_count,
        "fullTableRowCount": full_table_row_count,
        "maxTableRows": max_table_rows,
        "reviewCount": int(review_count),
        "tableFastPath": bool(table_fast_path),
    }


def _evidence_selection_metric_summary(
    *,
    evidence_selection: dict[str, Any],
    evidence_build_ms: int,
    candidate_select_ms: int,
) -> dict[str, Any]:
    selected_evidence = evidence_selection.get("selectedEvidence") if isinstance(evidence_selection.get("selectedEvidence"), list) else []
    uncertainty_flags = [
        str(item).strip()
        for item in (evidence_selection.get("uncertainties") if isinstance(evidence_selection.get("uncertainties"), list) else [])
        if str(item).strip()
    ]
    return {
        "evidenceBuildMs": int(evidence_build_ms),
        "candidateSelectMs": int(candidate_select_ms),
        "selectedEvidenceCount": len(selected_evidence),
        "skippedEvidenceCount": int(evidence_selection.get("skippedBlockCount") or 0),
        "selectedTableRowCount": int(evidence_selection.get("selectedTableRowCount") or 0),
        "evidenceExpansionLevel": str(evidence_selection.get("expansionLevel") or ""),
        "uncertaintyFlags": uncertainty_flags[:12],
    }


def _evidence_v2_runtime_selection(package: dict[str, Any]) -> dict[str, Any]:
    metrics = package.get("metrics") if isinstance(package.get("metrics"), dict) else {}
    selected_evidence = package.get("selectedEvidence") if isinstance(package.get("selectedEvidence"), list) else []
    warnings = package.get("warnings") if isinstance(package.get("warnings"), list) else []
    uncertainties = package.get("uncertainties") if isinstance(package.get("uncertainties"), list) else []
    return {
        "mode": "evidence_v2_model_input",
        "expansionLevel": str(metrics.get("evidenceExpansionLevel") or "initial"),
        "selectedBlockCount": int(metrics.get("selectedEvidenceCount") or len(selected_evidence)),
        "skippedBlockCount": max(0, int(metrics.get("evidenceItemCount") or 0) - len(selected_evidence)),
        "selectedTableRowCount": int(metrics.get("selectedTableRowCount") or 0),
        "totalTableRowCount": int(metrics.get("fullTableRowCount") or 0),
        "selectionReasons": ["runtime_contract", "evidence_v2_candidate_selection", "bounded_evidence_render"],
        "warnings": [str(item) for item in warnings if str(item).strip()][:12],
        "uncertainties": [str(item) for item in uncertainties if str(item).strip()][:12],
        "selectedEvidence": [
            {
                "sourceType": item.get("sourceType"),
                "pageNo": item.get("pageNo"),
                "blockId": ((item.get("blockRef") if isinstance(item.get("blockRef"), dict) else {}) or {}).get("blockId"),
                "title": item.get("title") or item.get("nearbyTitle"),
                "excerpt": str(item.get("excerpt") or "")[:320],
                "reason": ", ".join(str(reason) for reason in (item.get("scoreReasons") or [])[:6]),
                "selectedRowCount": item.get("selectedRowCount"),
                "totalRowCount": item.get("totalRowCount"),
                "rowWindow": item.get("rowWindow") if isinstance(item.get("rowWindow"), list) else [],
                "uncertainties": item.get("uncertainties") if isinstance(item.get("uncertainties"), list) else [],
            }
            for item in selected_evidence[:24]
            if isinstance(item, dict)
        ],
        "fullFactsPreserved": True,
        "source": "evidence_v2",
    }


_TABLE_STRUCTURE_REVIEW_OUTPUT_TYPES = {"record_collection", "data_table", "kv_record_table"}
_CRITICAL_TABLE_UNCERTAINTIES = {
    "complex_table_structure_review_required",
    "todo_complex_table_structure_review_required",
    "matrix_table_shape",
    "matrix_table",
}
_RECORD_TABLE_REVIEW_UNCERTAINTIES = {
    "missing_header_candidate",
    "ragged_rows",
    "many_empty_cells",
    "possible_continuation_without_header",
}


def _assess_table_review_risk(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    skill_meta: dict[str, Any],
) -> dict[str, Any]:
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(output_schema.get("type") or "").strip()
    evidence_by_page_and_fact = _evidence_by_page_and_fact_index(evidence_index)
    table_risks: list[dict[str, Any]] = []
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    table_count = 0
    seen_table_widths: set[int] = set()
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            page_no = int(page.get("pageNo") or 0)
        except (TypeError, ValueError):
            page_no = 0
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else None
            if table_grid is None:
                continue
            table_count += 1
            evidence = evidence_by_page_and_fact.get((page_no, block_index), {})
            uncertainties = _table_review_uncertainties(table_grid=table_grid, evidence=evidence)
            rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
            width = int(table_grid.get("columnCount") or max((len(row) for row in rows if isinstance(row, list)), default=0))
            if (
                output_type == "record_collection"
                and width > 0
                and width in seen_table_widths
                and _table_first_row_looks_like_continuation_data(rows)
                and "possible_continuation_without_header" not in uncertainties
            ):
                uncertainties.append("possible_continuation_without_header")
            if width > 0:
                seen_table_widths.add(width)
            if not uncertainties:
                continue
            critical = _table_uncertainty_requires_review(uncertainties, output_type=output_type)
            table_risks.append(
                {
                    "pageNo": page_no,
                    "blockIndex": block_index,
                    "sourceOrdinal": evidence.get("sourceOrdinal") or evidence.get("id") or "",
                    "blockId": evidence.get("blockId") or "",
                    "title": str(block.get("title") or table_grid.get("title") or "").strip()[:160],
                    "rowCount": int(table_grid.get("rowCount") or len(rows) or 0),
                    "columnCount": int(table_grid.get("columnCount") or 0),
                    "uncertainties": uncertainties[:12],
                    "severity": "critical" if critical else "warning",
                    "reviewAction": _table_review_action_text(
                        output_type=output_type,
                        uncertainties=uncertainties,
                    ),
                }
            )

    validation_errors: list[str] = []
    if output_type in _TABLE_STRUCTURE_REVIEW_OUTPUT_TYPES:
        for risk in table_risks:
            if risk.get("severity") != "critical":
                continue
            location = f"第 {risk.get('pageNo') or '?'} 页"
            title = str(risk.get("title") or risk.get("blockId") or risk.get("sourceOrdinal") or "表格").strip()
            uncertainty_text = "、".join(_table_review_uncertainty_label(str(item)) for item in (risk.get("uncertainties") or [])[:4])
            size_text = f"{risk.get('rowCount') or 0} 行 x {risk.get('columnCount') or 0} 列"
            action_text = str(risk.get("reviewAction") or "").strip()
            validation_errors.append(
                f"表格结构需要复核：{location} {title}（{size_text}）。"
                f"原因：{uncertainty_text}。请复核：{action_text}".strip()
            )

    warnings = [
        _table_review_warning_text(risk=risk, output_type=output_type)
        for risk in table_risks[:12]
    ]
    return {
        "outputType": output_type,
        "tableCount": table_count,
        "riskTableCount": len(table_risks),
        "criticalTableCount": sum(1 for item in table_risks if item.get("severity") == "critical"),
        "warnings": warnings,
        "validationErrors": validation_errors[:12],
        "risks": table_risks[:20],
    }


def _table_review_uncertainties(*, table_grid: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    uncertainties: list[str] = []
    evidence_uncertainties = evidence.get("uncertainties") if isinstance(evidence.get("uncertainties"), list) else []
    for raw in evidence_uncertainties:
        text = str(raw or "").strip()
        if text and text not in uncertainties:
            uncertainties.append(text)
    parse_warnings = table_grid.get("parseWarnings") if isinstance(table_grid.get("parseWarnings"), list) else []
    for raw in parse_warnings:
        text = str(raw or "").strip()
        if text and text not in uncertainties:
            uncertainties.append(text)
    complex_table = table_grid.get("complexTableTodo")
    if isinstance(complex_table, dict) and complex_table.get("required"):
        for text in ("complex_table_structure_review_required", "todo_complex_table_structure_review_required"):
            if text not in uncertainties:
                uncertainties.append(text)
    table_role = str(table_grid.get("tableRole") or "").strip()
    if table_role in {"matrix_table", "pivot_table", "crosstab_table"}:
        if "matrix_table_shape" not in uncertainties:
            uncertainties.append("matrix_table_shape")
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    widths = [len(row) for row in rows if isinstance(row, list)]
    if widths and min(widths) != max(widths) and "ragged_rows" not in uncertainties:
        uncertainties.append("ragged_rows")
    return uncertainties


def _table_uncertainty_requires_review(uncertainties: list[str], *, output_type: str) -> bool:
    normalized = {str(item or "").strip() for item in uncertainties if str(item or "").strip()}
    if output_type == "record_collection" and normalized & _RECORD_TABLE_REVIEW_UNCERTAINTIES:
        return True
    if output_type in {"record_collection", "kv_record_table"} and normalized & _CRITICAL_TABLE_UNCERTAINTIES:
        return True
    return False


def _table_review_uncertainty_label(value: str) -> str:
    labels = {
        "complex_table_structure_review_required": "复杂表格结构未确认",
        "todo_complex_table_structure_review_required": "存在合并单元格/多级表头待确认",
        "matrix_table_shape": "疑似矩阵/交叉表",
        "matrix_table": "疑似矩阵表",
        "missing_header_candidate": "未找到稳定表头",
        "ragged_rows": "行列不齐",
        "many_empty_cells": "空单元格较多",
        "possible_continuation_without_header": "疑似续表但缺少表头",
        "repeated_cells": "重复单元格较多",
        "table_shape_uncertain": "表格形态不确定",
    }
    return labels.get(value, value)


def _table_review_action_text(*, output_type: str, uncertainties: list[str]) -> str:
    normalized = {str(item or "").strip() for item in uncertainties if str(item or "").strip()}
    actions = [
        "确认这张表是否属于本次定位命中的数据块",
        "核对表头、合并单元格和行列关系是否与原文一致",
    ]
    if output_type == "record_collection":
        actions.append("确认一行是否对应一条记录，续表/小计/分组行是否需要排除或补充上下文")
    elif output_type == "data_table":
        actions.append("确认是否需要保留多级表头、合并单元格或矩阵结构，而不是扁平化为普通二维表")
    elif output_type == "kv_record_table":
        actions.append("确认字段区、明细区、备注/合计区是否被正确分开")
    if "possible_continuation_without_header" in normalized:
        actions.append("确认上一页或上一张表是否是该表的表头来源")
    if "missing_header_candidate" in normalized:
        actions.append("补充或确认表头后再生成结构化结果")
    return "；".join(actions) + "。"


def _table_review_warning_text(*, risk: dict[str, Any], output_type: str) -> str:
    location = f"第 {risk.get('pageNo') or '?'} 页"
    title = str(risk.get("title") or risk.get("blockId") or risk.get("sourceOrdinal") or "表格").strip()
    uncertainty_text = "、".join(
        _table_review_uncertainty_label(str(item)) for item in (risk.get("uncertainties") or [])[:4]
    )
    if output_type == "data_table":
        return f"{location} {title} 表格存在{uncertainty_text}，已按当前结构输出，请注意核对。"
    return f"{location} {title} 表格存在不确定性：{uncertainty_text}。"


def _table_first_row_looks_like_continuation_data(rows: list[Any]) -> bool:
    if not rows or not isinstance(rows[0], list):
        return False
    first_row = [str(cell or "").strip() for cell in rows[0]]
    nonempty = [cell for cell in first_row if cell]
    if len(nonempty) < 2:
        return False
    numeric_like = sum(1 for cell in nonempty if _looks_numeric_like_table_value(cell))
    if numeric_like >= max(1, len(nonempty) // 2):
        return True
    return _looks_numeric_like_table_value(nonempty[0]) and numeric_like >= 1


def _looks_numeric_like_table_value(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(re.fullmatch(r"[-+]?\d+(?:[.,:/-]\d+)*(?:\.\d+)?%?", text))


def _augment_evidence_index_with_runtime_contract(
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
) -> dict[str, Any]:
    if not runtime_contract:
        return evidence_index
    selected_content = runtime_contract.get("selectedContent")
    if not isinstance(selected_content, list):
        selected_content = []
    contract_evidence: list[dict[str, Any]] = []
    for index, item in enumerate(selected_content):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        pages = item.get("pages") if isinstance(item.get("pages"), list) else []
        evidence_pages = item.get("evidencePages") if isinstance(item.get("evidencePages"), list) else []
        contract_evidence.append(
            {
                "id": f"contract-selected-content-{index + 1}",
                "sourceType": source or "selected_content",
                "title": str(item.get("title") or "").strip(),
                "pageNos": pages or evidence_pages,
                "excerpt": str(item.get("excerpt") or "").strip()[:300],
                "originalRefs": {
                    "treeNodeId": str(item.get("treeNodeId") or "").strip(),
                    "source": source,
                },
            }
        )
    next_index = dict(evidence_index)
    next_index["runtimeContract"] = {
        "contractVersion": runtime_contract.get("contractVersion"),
        "outputType": runtime_contract.get("outputType"),
        "fieldLabelCount": len(runtime_contract.get("fieldLabels") or []),
        "selectedContentCount": len(contract_evidence),
        "matchedPageNos": runtime_contract.get("matchedPageNos") if isinstance(runtime_contract.get("matchedPageNos"), list) else [],
    }
    next_index["contractEvidence"] = contract_evidence
    return next_index


def _build_field_list_evidence_package(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    expansion_level: str,
    allow_page_preview_fallback: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(runtime_contract.get("outputType") or output_schema.get("type") or "").strip()
    if output_type != "field_list" or not runtime_contract:
        return facts_payload, {
            "mode": "full_facts",
            "expansionLevel": "full",
            "reason": "non_application_field_list",
        }

    max_rows_per_table = 24 if expansion_level == "initial" else 96
    text_limit = 2400 if expansion_level == "initial" else 8000
    selected_page_nos = _runtime_contract_page_numbers(runtime_contract)
    selected_block_ids = _runtime_contract_block_ids(runtime_contract)
    has_document_tree_scope = _runtime_contract_has_document_tree_scope(runtime_contract)
    terms = _evidence_selection_terms(runtime_contract=runtime_contract, skill_meta=skill_meta)
    evidence_by_page_and_fact = _evidence_by_page_and_fact_index(evidence_index)

    selected_pages: list[dict[str, Any]] = []
    selected_block_count = 0
    skipped_block_count = 0
    selected_table_rows = 0
    total_table_rows = 0
    table_uncertainties: set[str] = set()
    selected_evidence_summary: list[dict[str, Any]] = []
    selection_validation_errors: list[str] = []
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            page_no = int(page.get("pageNo") or 0)
        except (TypeError, ValueError):
            page_no = 0
        if selected_page_nos and page_no not in selected_page_nos:
            continue
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        selected_blocks: list[dict[str, Any]] = []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            evidence = evidence_by_page_and_fact.get((page_no, block_index), {})
            source_ref = {
                "pageNo": page_no,
                "factBlockIndex": block_index,
                "sourceOrdinal": evidence.get("sourceOrdinal") or evidence.get("id") or "",
                "blockId": evidence.get("blockId") or "",
                "blockPosition": evidence.get("blockPosition") or "",
            }
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else None
            match = _field_list_block_match(
                block=block,
                evidence=evidence,
                source_ref=source_ref,
                selected_block_ids=selected_block_ids,
                selected_page_nos=selected_page_nos,
                terms=terms,
                expansion_level=expansion_level,
                allow_page_preview_fallback=allow_page_preview_fallback,
                has_document_tree_scope=has_document_tree_scope,
            )
            if not match.get("selected"):
                if table_grid is not None:
                    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
                    total_table_rows += len([row for row in rows if isinstance(row, list)])
                skipped_block_count += 1
                continue
            if table_grid is not None:
                uncertainties = [
                    str(item).strip()
                    for item in (evidence.get("uncertainties") if isinstance(evidence.get("uncertainties"), list) else [])
                    if str(item).strip()
                ]
                compact_block, table_meta = _compact_field_list_table_block(
                    block=block,
                    source_ref=source_ref,
                    terms=terms,
                    max_rows=max_rows_per_table,
                    expansion_level=expansion_level,
                    selection_reason=str(match.get("reason") or ""),
                    uncertainties=uncertainties,
                )
                selected_table_rows += int(table_meta.get("selectedRowCount") or 0)
                total_table_rows += int(table_meta.get("originalRowCount") or 0)
                if uncertainties:
                    table_uncertainties.update(uncertainties)
                selected_evidence_summary.append(
                    _field_list_evidence_summary_item(
                        block=compact_block,
                        source_ref=source_ref,
                        source_type="table",
                        table_meta=table_meta,
                        match_reason=str(match.get("reason") or ""),
                        uncertainties=uncertainties,
                    )
                )
                selected_blocks.append(compact_block)
                selected_block_count += 1
                continue
            compact_block = dict(block)
            text = str(compact_block.get("text") or "")
            if len(text) > text_limit:
                compact_block["text"] = text[:text_limit]
                compact_block["textTruncated"] = True
                compact_block["originalTextCharCount"] = len(text)
            compact_block["sourceRef"] = source_ref
            selected_evidence_summary.append(
                _field_list_evidence_summary_item(
                    block=compact_block,
                    source_ref=source_ref,
                    source_type=str(compact_block.get("type") or "text"),
                    match_reason=str(match.get("reason") or ""),
                )
            )
            selected_blocks.append(compact_block)
            selected_block_count += 1
        if selected_blocks:
            selected_pages.append({**page, "blocks": selected_blocks})

    if not selected_pages and selected_block_ids:
        selection_validation_errors.append(
            "定位命中的字段证据没有绑定到可抽取证据块：请复核定位结果是否选中了正确的文档树节点；"
            "如果页面预览可见目标字段，请重新确认样例或重新识别文档后再试跑。"
        )
    elif not selected_pages and selected_page_nos and not allow_page_preview_fallback:
        return _build_field_list_evidence_package(
            facts_payload=facts_payload,
            evidence_index=evidence_index,
            runtime_contract=runtime_contract,
            skill_meta=skill_meta,
            expansion_level=expansion_level,
            allow_page_preview_fallback=True,
        )

    package = {"pages": selected_pages}
    selection_warnings: list[str] = []
    if total_table_rows > selected_table_rows:
        selection_warnings.append(
            f"长表格证据已按字段契约限制为 {selected_table_rows}/{total_table_rows} 行窗口，完整 facts 已保留。"
        )
    if table_uncertainties:
        selection_warnings.append(
            "已选表格存在结构不确定性：" + "、".join(sorted(table_uncertainties)[:8])
        )

    selection_meta = {
        "mode": "field_list_selected_evidence",
        "expansionLevel": expansion_level,
        "selectedPageNos": sorted(selected_page_nos) if selected_page_nos else "all",
        "termCount": len(terms),
        "selectedBlockCount": selected_block_count,
        "skippedBlockCount": skipped_block_count,
        "selectedTableRowCount": selected_table_rows,
        "totalTableRowCount": total_table_rows,
        "rowLimitPerTable": max_rows_per_table,
        "selectionReasons": [
            "runtime_contract",
            "selected_content_pages",
            "field_label_and_skill_term_rows",
            "bounded_table_context",
        ],
        "warnings": selection_warnings,
        "validationErrors": selection_validation_errors,
        "uncertainties": sorted(table_uncertainties),
        "selectedEvidence": selected_evidence_summary[:24],
        "fullFactsPreserved": True,
    }
    package["evidenceSelection"] = selection_meta
    return package, selection_meta


def _build_record_collection_evidence_package(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(runtime_contract.get("outputType") or output_schema.get("type") or "").strip()
    if output_type != "record_collection":
        return facts_payload, {
            "mode": "full_facts",
            "expansionLevel": "full",
            "reason": "non_record_collection",
        }

    selected_page_nos = _runtime_contract_page_numbers(runtime_contract)
    selected_block_ids = _runtime_contract_block_ids(runtime_contract)
    selected_source_text = _runtime_contract_selected_source_text(runtime_contract)
    has_document_tree_scope = _runtime_contract_has_document_tree_scope(runtime_contract)
    terms = _evidence_selection_terms(runtime_contract=runtime_contract, skill_meta=skill_meta)
    strict_selected_content_refs = bool(selected_block_ids and has_document_tree_scope)
    evidence_by_page_and_fact = _evidence_by_page_and_fact_index(evidence_index)
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    selected_pages: list[dict[str, Any]] = []
    selected_evidence_summary: list[dict[str, Any]] = []
    selection_validation_errors: list[str] = []
    selected_block_count = 0
    skipped_block_count = 0
    selected_table_rows = 0
    selected_text_chars = 0
    total_table_rows = 0
    table_uncertainties: set[str] = set()
    table_seen = 0

    if selected_source_text:
        source_page_no = min(selected_page_nos) if selected_page_nos else 0
        source_ref = {
            "pageNo": source_page_no,
            "factBlockIndex": -1,
            "sourceOrdinal": "runtimeContract.selectedSourceText",
            "blockId": "runtime-contract-selected-source",
            "blockPosition": "",
        }
        compact_block = {
            "type": "text",
            "title": "选中文档树来源",
            "text": selected_source_text,
            "sourceRef": source_ref,
        }
        selected_pages.append({"pageNo": source_page_no or None, "blocks": [compact_block]})
        selected_block_count += 1
        selected_text_chars += len(selected_source_text)
        selected_evidence_summary.append(
            _field_list_evidence_summary_item(
                block=compact_block,
                source_ref=source_ref,
                source_type="text",
                match_reason="runtime_contract_selected_source_text",
            )
        )

    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            page_no = int(page.get("pageNo") or 0)
        except (TypeError, ValueError):
            page_no = 0
        if selected_page_nos and page_no not in selected_page_nos:
            continue
        selected_blocks: list[dict[str, Any]] = []
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else None
            if table_grid is None:
                source_ref = _fact_source_ref(
                    evidence=evidence_by_page_and_fact.get((page_no, block_index), {}),
                    page_no=page_no,
                    block_index=block_index,
                )
                if _record_collection_text_block_selected(
                    block=block,
                    selected_block_ids=selected_block_ids,
                    selected_page_nos=selected_page_nos,
                    source_ref=source_ref,
                    has_document_tree_scope=has_document_tree_scope,
                    selected_source_text_available=bool(selected_source_text),
                    terms=terms,
                ):
                    compact_block = _compact_record_collection_text_block(block=block, source_ref=source_ref)
                    selected_text_chars += len(str(compact_block.get("text") or ""))
                    selected_evidence_summary.append(
                        _field_list_evidence_summary_item(
                            block=compact_block,
                            source_ref=source_ref,
                            source_type=str(compact_block.get("type") or "text"),
                            match_reason="record_text_evidence",
                        )
                    )
                    selected_blocks.append(compact_block)
                    selected_block_count += 1
                else:
                    skipped_block_count += 1
                continue
            evidence = evidence_by_page_and_fact.get((page_no, block_index), {})
            source_ref = {
                "pageNo": page_no,
                "factBlockIndex": block_index,
                "sourceOrdinal": evidence.get("sourceOrdinal") or evidence.get("id") or "",
                "blockId": evidence.get("blockId") or "",
                "blockPosition": evidence.get("blockPosition") or "",
            }
            source_ids = {
                str(source_ref.get("blockId") or "").strip(),
                str(source_ref.get("sourceOrdinal") or "").strip(),
                str(evidence.get("id") or "").strip(),
                str(evidence.get("blockId") or "").strip(),
            }
            content_ref_matched = _source_id_matches_selected(source_ids, selected_block_ids)
            if selected_source_text and has_document_tree_scope and not content_ref_matched:
                rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
                total_table_rows += len([row for row in rows if isinstance(row, list)])
                skipped_block_count += 1
                continue
            if selected_block_ids and not content_ref_matched:
                rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
                total_table_rows += len([row for row in rows if isinstance(row, list)])
                skipped_block_count += 1
                continue
            if strict_selected_content_refs and not content_ref_matched:
                rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
                total_table_rows += len([row for row in rows if isinstance(row, list)])
                skipped_block_count += 1
                continue

            keep_rows = 4 if table_seen == 0 else 2
            compact_block, table_meta = _compact_record_collection_table_block(
                block=block,
                source_ref=source_ref,
                keep_rows=keep_rows,
            )
            table_seen += 1
            selected_table_rows += int(table_meta.get("selectedRowCount") or 0)
            total_table_rows += int(table_meta.get("originalRowCount") or 0)
            uncertainties = [
                str(item).strip()
                for item in (evidence.get("uncertainties") if isinstance(evidence.get("uncertainties"), list) else [])
                if str(item).strip()
            ]
            if uncertainties:
                table_uncertainties.update(uncertainties)
            selected_evidence_summary.append(
                _field_list_evidence_summary_item(
                    block=compact_block,
                    source_ref=source_ref,
                    source_type="table",
                    table_meta=table_meta,
                    match_reason="record_table_preview",
                    uncertainties=uncertainties,
                )
            )
            selected_blocks.append(compact_block)
            selected_block_count += 1
        if selected_blocks:
            selected_pages.append({**page, "blocks": selected_blocks})

    if not selected_pages and selected_block_ids:
        selection_validation_errors.append(
            "定位命中的内容没有绑定到可抽取证据块：请复核定位结果是否选中了正确的文档树节点；"
            "如果页面预览可见目标内容，请重新确认样例或重新识别文档后再试跑。"
        )

    if not selected_pages and not selected_block_ids:
        selected_pages = _build_table_record_preview_facts(facts_payload).get("pages", [])
        selected_block_count = sum(len(page.get("blocks") or []) for page in selected_pages if isinstance(page, dict))
        selected_table_rows = sum(
            len(((block.get("tableGrid") if isinstance(block, dict) else {}) or {}).get("rows") or [])
            for page in selected_pages
            if isinstance(page, dict)
            for block in (page.get("blocks") or [])
        )
        full_table_blocks = _collect_fact_table_blocks(facts_payload)
        total_table_rows = sum(len(block.get("rows") or []) for block in full_table_blocks)

    selection_warnings: list[str] = []
    if total_table_rows > selected_table_rows:
        selection_warnings.append(
            f"记录表证据以结构化预览进入模型：{selected_table_rows}/{total_table_rows} 行，完整 facts 已保留用于本地生成。"
        )
    if selected_text_chars:
        selection_warnings.append(
            f"记录集合包含文本型证据：{selected_text_chars} 字，已按文档树/页范围进入模型。"
        )
    if table_uncertainties:
        selection_warnings.append(
            "候选记录表存在结构不确定性：" + "、".join(sorted(table_uncertainties)[:8])
        )

    selection_meta = {
        "mode": "record_collection_selected_evidence",
        "expansionLevel": "preview",
        "selectedPageNos": sorted(selected_page_nos) if selected_page_nos else "all",
        "selectedBlockCount": selected_block_count,
        "skippedBlockCount": skipped_block_count,
        "selectedTableRowCount": selected_table_rows,
        "totalTableRowCount": total_table_rows,
        "selectedTextCharCount": selected_text_chars,
        "selectionReasons": [
            "runtime_contract",
            "record_table_preview",
            "record_text_evidence",
            "structured_rows_preserved",
        ],
        "warnings": selection_warnings,
        "validationErrors": selection_validation_errors,
        "uncertainties": sorted(table_uncertainties),
        "selectedEvidence": selected_evidence_summary[:24],
        "fullFactsPreserved": True,
    }
    package = {"pages": selected_pages, "evidenceSelection": selection_meta}
    return package, selection_meta


def _build_runtime_evidence_package(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    expansion_level: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(runtime_contract.get("outputType") or output_schema.get("type") or "").strip()
    if output_type == "field_list":
        return _build_field_list_evidence_package(
            facts_payload=facts_payload,
            evidence_index=evidence_index,
            runtime_contract=runtime_contract,
            skill_meta=skill_meta,
            expansion_level=expansion_level,
        )
    if output_type == "record_collection":
        return _build_record_collection_evidence_package(
            facts_payload=facts_payload,
            evidence_index=evidence_index,
            runtime_contract=runtime_contract,
            skill_meta=skill_meta,
        )
    return facts_payload, {
        "mode": "full_facts",
        "expansionLevel": "full",
        "reason": "unsupported_output_type",
    }


def _field_list_evidence_summary_item(
    *,
    block: dict[str, Any],
    source_ref: dict[str, Any],
    source_type: str,
    table_meta: dict[str, Any] | None = None,
    match_reason: str = "",
    uncertainties: list[str] | None = None,
) -> dict[str, Any]:
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    row_selection = table_grid.get("rowSelection") if isinstance(table_grid.get("rowSelection"), list) else []
    row_texts = table_grid.get("rowTexts") if isinstance(table_grid.get("rowTexts"), list) else []
    text = str(block.get("text") or "")
    excerpt = " | ".join(str(item or "").strip() for item in row_texts[:3] if str(item or "").strip())
    if not excerpt:
        excerpt = text.strip()
    item = {
        "sourceType": str(source_type or "text"),
        "pageNo": source_ref.get("pageNo"),
        "sourceOrdinal": source_ref.get("sourceOrdinal") or "",
        "blockId": source_ref.get("blockId") or "",
        "title": str(block.get("title") or table_grid.get("title") or "").strip()[:160],
        "excerpt": excerpt[:320],
    }
    if match_reason:
        item["reason"] = match_reason
    if table_meta:
        item.update(
            {
                "selectedRowCount": int(table_meta.get("selectedRowCount") or 0),
                "totalRowCount": int(table_meta.get("originalRowCount") or 0),
                "rowWindow": row_selection[:16],
            }
        )
    normalized_uncertainties = [str(value).strip() for value in (uncertainties or []) if str(value).strip()]
    if normalized_uncertainties:
        item["uncertainties"] = normalized_uncertainties[:8]
    if block.get("textTruncated"):
        item["textTruncated"] = True
    return {key: value for key, value in item.items() if value not in ("", [], None)}


def _fact_source_ref(*, evidence: dict[str, Any], page_no: int, block_index: int) -> dict[str, Any]:
    return {
        "pageNo": page_no,
        "factBlockIndex": block_index,
        "sourceOrdinal": evidence.get("sourceOrdinal") or evidence.get("id") or "",
        "blockId": evidence.get("blockId") or "",
        "blockPosition": evidence.get("blockPosition") or "",
    }


def _runtime_contract_selected_source_text(runtime_contract: dict[str, Any]) -> str:
    text = str(runtime_contract.get("selectedSourceText") or "").strip()
    if not text:
        return ""
    max_chars = 20000
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...（选中来源已截断，完整 facts 已保留）"


def _runtime_contract_has_document_tree_scope(runtime_contract: dict[str, Any]) -> bool:
    selected_content = runtime_contract.get("selectedContent") if isinstance(runtime_contract.get("selectedContent"), list) else []
    for item in selected_content:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("kind") or "").strip()
        if source == "document_tree_module":
            return True
        if str(item.get("treeNodeId") or item.get("nodeId") or "").strip():
            return True
    return False


def _record_collection_text_block_selected(
    *,
    block: dict[str, Any],
    selected_block_ids: set[str],
    selected_page_nos: set[int],
    source_ref: dict[str, Any],
    has_document_tree_scope: bool,
    selected_source_text_available: bool,
    terms: list[str],
) -> bool:
    text = _record_collection_block_text(block)
    if not text:
        return False
    if selected_source_text_available:
        return False
    source_ids = {
        str(block.get("id") or "").strip(),
        str(source_ref.get("blockId") or "").strip(),
        str(source_ref.get("sourceOrdinal") or "").strip(),
    }
    if selected_block_ids and _source_id_matches_selected(source_ids, selected_block_ids):
        return True
    if selected_block_ids:
        return False
    if has_document_tree_scope and terms:
        normalized_text = _normalize_evidence_match_text(text)
        if any(term and term in normalized_text for term in terms):
            return True
        return False
    if selected_page_nos:
        return True
    return not selected_block_ids


def _compact_record_collection_text_block(
    *,
    block: dict[str, Any],
    source_ref: dict[str, Any],
    text_limit: int = 8000,
) -> dict[str, Any]:
    compact_block = dict(block)
    text = _record_collection_block_text(compact_block)
    if len(text) > text_limit:
        compact_block["text"] = text[:text_limit]
        compact_block["textTruncated"] = True
        compact_block["originalTextCharCount"] = len(text)
    else:
        compact_block["text"] = text
    compact_block["sourceRef"] = source_ref
    return compact_block


def _record_collection_block_text(block: dict[str, Any]) -> str:
    values = [
        str(block.get("title") or "").strip(),
        str(block.get("text") or block.get("content") or "").strip(),
    ]
    text = "\n".join(value for value in values if value)
    return text.strip()


def _runtime_contract_page_numbers(runtime_contract: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    values: list[Any] = []
    values.extend(runtime_contract.get("matchedPageNos") or [])
    selected_content = runtime_contract.get("selectedContent") if isinstance(runtime_contract.get("selectedContent"), list) else []
    for item in selected_content:
        if not isinstance(item, dict):
            continue
        values.extend(item.get("pages") or [])
        values.extend(item.get("evidencePages") or [])
    for value in values:
        try:
            page_no = int(value)
        except (TypeError, ValueError):
            continue
        if page_no > 0:
            pages.add(page_no)
    return pages


def _runtime_contract_block_ids(runtime_contract: dict[str, Any]) -> set[str]:
    block_ids: set[str] = set()
    selected_content = runtime_contract.get("selectedContent") if isinstance(runtime_contract.get("selectedContent"), list) else []
    for item in selected_content:
        if not isinstance(item, dict):
            continue
        for key in ("targetId", "blockId"):
            text = str(item.get(key) or "").strip()
            if text:
                block_ids.add(text)
        for key in ("blockIds", "blockIdsExact"):
            values = item.get(key) if isinstance(item.get(key), list) else []
            for value in values:
                text = str(value or "").strip()
                if text:
                    block_ids.add(text)
    return block_ids


def _evidence_by_page_and_fact_index(evidence_index: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    indexed: dict[tuple[int, int], dict[str, Any]] = {}
    pages = evidence_index.get("pages") if isinstance(evidence_index.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            page_no = int(page.get("pageNo") or 0)
        except (TypeError, ValueError):
            page_no = 0
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            refs = block.get("originalRefs") if isinstance(block.get("originalRefs"), dict) else {}
            try:
                fact_index = int(refs.get("factBlockIndex"))
            except (TypeError, ValueError):
                continue
            indexed[(page_no, fact_index)] = block
    return indexed


def _field_list_block_match(
    *,
    block: dict[str, Any],
    evidence: dict[str, Any],
    source_ref: dict[str, Any],
    selected_block_ids: set[str],
    selected_page_nos: set[int],
    terms: list[str],
    expansion_level: str,
    allow_page_preview_fallback: bool = False,
    has_document_tree_scope: bool = False,
) -> dict[str, Any]:
    source_ids = {
        str(source_ref.get("blockId") or "").strip(),
        str(source_ref.get("sourceOrdinal") or "").strip(),
        str(evidence.get("id") or "").strip(),
        str(evidence.get("blockId") or "").strip(),
    }
    content_ref_matched = selected_block_ids and _source_id_matches_selected(source_ids, selected_block_ids)

    if selected_block_ids and has_document_tree_scope:
        if not content_ref_matched:
            return {"selected": False, "reason": "outside_selected_content_refs"}

    normalized_text = _normalize_evidence_match_text(_field_list_block_search_text(block=block, evidence=evidence))
    matched_terms = [term for term in terms if term and term in normalized_text]
    if matched_terms:
        return {"selected": True, "reason": "semantic_term_match", "matchedTerms": matched_terms[:12]}

    if content_ref_matched:
        if _table_looks_record_like_for_field_list(block):
            return {"selected": True, "reason": "content_ref_record_table_preview"}
        return {"selected": True, "reason": "content_ref_block"}

    if selected_block_ids:
        return {"selected": False, "reason": "outside_selected_content_refs"}

    if _table_has_field_like_shape(block):
        return {"selected": True, "reason": "field_like_table_shape"}

    try:
        page_no = int(source_ref.get("pageNo") or 0)
    except (TypeError, ValueError):
        page_no = 0
    if expansion_level != "initial" and (not selected_page_nos or page_no in selected_page_nos):
        return {"selected": True, "reason": "review_page_expansion"}
    if allow_page_preview_fallback and (not selected_page_nos or page_no in selected_page_nos):
        return {"selected": True, "reason": "matched_page_preview"}
    return {"selected": False, "reason": "not_relevant_to_field_contract"}


def _field_list_block_search_text(*, block: dict[str, Any], evidence: dict[str, Any]) -> str:
    parts = [
        block.get("title"),
        block.get("text"),
        evidence.get("title"),
        evidence.get("nearbyTitle"),
        evidence.get("excerpt"),
    ]
    row_summary = evidence.get("rowTextSummary") if isinstance(evidence.get("rowTextSummary"), list) else []
    parts.extend(row_summary)
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    row_texts = table_grid.get("rowTexts") if isinstance(table_grid.get("rowTexts"), list) else []
    parts.extend(row_texts)
    return " ".join(str(item or "") for item in parts if str(item or "").strip())


def _source_id_matches_selected(source_ids: set[str], selected_block_ids: set[str]) -> bool:
    normalized_selected = {
        str(value or "").strip()
        for value in selected_block_ids
        if str(value or "").strip()
    }
    if not normalized_selected:
        return False
    for raw_source_id in source_ids:
        source_id = str(raw_source_id or "").strip()
        if not source_id:
            continue
        if source_id in normalized_selected:
            return True
        for selected_id in normalized_selected:
            if _source_id_has_selected_suffix(source_id=source_id, selected_id=selected_id):
                return True
    return False


def _source_id_has_selected_suffix(*, source_id: str, selected_id: str) -> bool:
    if not source_id or not selected_id or source_id == selected_id:
        return bool(source_id and selected_id and source_id == selected_id)
    if len(selected_id) > len(source_id):
        return False
    if not source_id.endswith(selected_id):
        return False
    prefix = source_id[: -len(selected_id)]
    return bool(prefix) and prefix[-1] in {"-", "_", ":", "/", "#"}


def _table_has_field_like_shape(block: dict[str, Any]) -> bool:
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    rows = table_grid.get("dedupedRows") if isinstance(table_grid.get("dedupedRows"), list) else []
    if not rows:
        return False
    row_count = len(rows)
    column_count = int(table_grid.get("columnCount") or 0)
    if row_count > 24 or column_count > 8:
        return False
    field_like_rows = 0
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
        if not cells:
            continue
        joined = " ".join(cells)
        if "：" in joined or ":" in joined:
            field_like_rows += 1
            continue
        if 1 <= len(cells) <= 4 and any(len(cell) <= 12 for cell in cells):
            field_like_rows += 1
    return field_like_rows >= max(1, min(3, row_count))


def _table_looks_record_like_for_field_list(block: dict[str, Any]) -> bool:
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    row_count = len([row for row in rows if isinstance(row, list)])
    column_count = int(table_grid.get("columnCount") or 0)
    if row_count < 8 or column_count < 4:
        return False
    stable_rows = 0
    content_rich_rows = 0
    repeated_rows = 0
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
        if not cells:
            continue
        if len(row) >= max(3, int(column_count * 0.7)):
            stable_rows += 1
        if len(cells) >= min(3, column_count):
            content_rich_rows += 1
        unique_cells = set(cells)
        if len(unique_cells) <= 2 and len(cells) >= 4:
            repeated_rows += 1
    return (
        stable_rows >= max(4, row_count // 2)
        and content_rich_rows >= max(3, row_count // 3)
        and repeated_rows < max(3, row_count // 2)
    )


def _evidence_selection_terms(*, runtime_contract: dict[str, Any], skill_meta: dict[str, Any]) -> list[str]:
    raw_terms: list[str] = []
    for key in ("fieldLabels", "tableHeaders", "recordFields"):
        values = runtime_contract.get(key)
        if isinstance(values, list):
            raw_terms.extend(str(item or "") for item in values)
    selected_content = runtime_contract.get("selectedContent") if isinstance(runtime_contract.get("selectedContent"), list) else []
    for item in selected_content:
        if not isinstance(item, dict):
            continue
        raw_terms.append(str(item.get("title") or ""))
        raw_terms.append(str(item.get("excerpt") or ""))
    raw_terms.append(str(skill_meta.get("name") or ""))
    raw_terms.append(str(skill_meta.get("promptTemplate") or ""))
    for rule in skill_meta.get("rules") or []:
        raw_terms.append(str(rule or ""))

    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        for token in _extract_evidence_terms(raw):
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
            if len(terms) >= 120:
                return terms
    return terms


def _extract_evidence_terms(text: str) -> list[str]:
    terms: list[str] = []
    normalized_whole = _normalize_evidence_match_text(text)
    if len(normalized_whole) >= 2:
        terms.append(normalized_whole)
    for token in re.findall(r"[A-Za-z0-9_\-.]{2,}|[\u4e00-\u9fff]{2,}", text or ""):
        normalized = _normalize_evidence_match_text(token)
        if len(normalized) >= 2:
            terms.append(normalized)
    return terms


def _normalize_evidence_match_text(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text or "").lower())


def _compact_field_list_table_block(
    *,
    block: dict[str, Any],
    source_ref: dict[str, Any],
    terms: list[str],
    max_rows: int,
    expansion_level: str,
    selection_reason: str = "",
    uncertainties: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    deduped_rows = table_grid.get("dedupedRows") if isinstance(table_grid.get("dedupedRows"), list) else []
    row_texts = table_grid.get("rowTexts") if isinstance(table_grid.get("rowTexts"), list) else []
    normalized_rows = [row for row in rows if isinstance(row, list)]
    original_row_count = len(normalized_rows)
    selected_indexes, row_reasons = _select_field_list_table_row_indexes(
        row_texts=row_texts,
        original_row_count=original_row_count,
        terms=terms,
        max_rows=max_rows,
        expansion_level=expansion_level,
        selection_reason=selection_reason,
    )
    selected_rows = [
        [str(cell or "") for cell in normalized_rows[index]]
        for index in selected_indexes
        if 0 <= index < len(normalized_rows)
    ]
    selected_deduped_rows = [
        [str(cell or "") for cell in deduped_rows[index]]
        for index in selected_indexes
        if 0 <= index < len(deduped_rows) and isinstance(deduped_rows[index], list)
    ]
    selected_row_texts = [
        str(row_texts[index] or "")
        for index in selected_indexes
        if 0 <= index < len(row_texts)
    ]
    compact_rows = selected_rows
    rows_compacted_from_deduped = False
    if selected_deduped_rows and len(selected_deduped_rows) == len(selected_rows):
        next_rows: list[list[str]] = []
        for row, deduped_row in zip(selected_rows, selected_deduped_rows):
            if deduped_row and len(deduped_row) < len(row):
                next_rows.append(deduped_row)
                rows_compacted_from_deduped = True
            else:
                next_rows.append(row)
        compact_rows = next_rows
    compact_grid = {
        "title": table_grid.get("title") or block.get("title") or "",
        "rowCount": len(compact_rows),
        "columnCount": max((len(row) for row in compact_rows), default=0) or table_grid.get("columnCount") or 0,
        "originalRowCount": table_grid.get("rowCount") or original_row_count,
        "rows": compact_rows,
        "dedupedRows": selected_deduped_rows,
        "rowTexts": selected_row_texts,
        "rowSelection": [
            {"rowIndex": index, "reason": row_reasons.get(index, "bounded_context")}
            for index in selected_indexes
        ],
        "truncated": original_row_count > len(selected_rows),
        "evidencePackage": True,
        "expansionLevel": expansion_level,
    }
    if rows_compacted_from_deduped:
        compact_grid["rowsCompactedFromDeduped"] = True
    normalized_uncertainties = [str(item).strip() for item in (uncertainties or []) if str(item).strip()]
    if normalized_uncertainties:
        compact_grid["uncertainties"] = normalized_uncertainties[:12]
    compact_block = {
        **block,
        "tableGrid": compact_grid,
        "sourceRef": source_ref,
    }
    return compact_block, {
        "selectedRowCount": len(selected_rows),
        "originalRowCount": original_row_count,
    }


def _compact_record_collection_table_block(
    *,
    block: dict[str, Any],
    source_ref: dict[str, Any],
    keep_rows: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    original_row_count = len([row for row in rows if isinstance(row, list)])
    selected_indexes = list(range(min(max(1, keep_rows), original_row_count)))
    if original_row_count > keep_rows and original_row_count - 1 not in selected_indexes:
        selected_indexes.append(original_row_count - 1)
    selected_indexes = sorted(set(index for index in selected_indexes if 0 <= index < original_row_count))
    compact_grid = _slice_table_grid_rows(
        table_grid=table_grid,
        selected_indexes=selected_indexes,
        row_reason="record_preview",
    )
    compact_grid["evidencePackage"] = True
    compact_grid["expansionLevel"] = "preview"
    compact_block = {
        **block,
        "tableGrid": compact_grid,
        "sourceRef": source_ref,
    }
    return compact_block, {
        "selectedRowCount": int(compact_grid.get("rowCount") or 0),
        "originalRowCount": original_row_count,
    }


def _slice_table_grid_rows(
    *,
    table_grid: dict[str, Any],
    selected_indexes: list[int],
    row_reason: str,
) -> dict[str, Any]:
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    deduped_rows = table_grid.get("dedupedRows") if isinstance(table_grid.get("dedupedRows"), list) else []
    row_texts = table_grid.get("rowTexts") if isinstance(table_grid.get("rowTexts"), list) else []
    selected_rows = [
        [str(cell or "") for cell in rows[index]]
        for index in selected_indexes
        if 0 <= index < len(rows) and isinstance(rows[index], list)
    ]
    selected_deduped_rows = [
        [str(cell or "") for cell in deduped_rows[index]]
        for index in selected_indexes
        if 0 <= index < len(deduped_rows) and isinstance(deduped_rows[index], list)
    ]
    selected_row_texts = [
        str(row_texts[index] or "")
        for index in selected_indexes
        if 0 <= index < len(row_texts)
    ]
    original_row_count = len([row for row in rows if isinstance(row, list)])
    return {
        **{
            key: value
            for key, value in table_grid.items()
            if key not in {"rows", "dedupedRows", "rowTexts", "rowSelection"}
        },
        "originalRowCount": table_grid.get("rowCount") or original_row_count,
        "rows": selected_rows,
        "dedupedRows": selected_deduped_rows,
        "rowTexts": selected_row_texts,
        "rowCount": len(selected_rows),
        "columnCount": table_grid.get("columnCount") or max((len(row) for row in selected_rows), default=0),
        "rowSelection": [{"rowIndex": index, "reason": row_reason} for index in selected_indexes],
        "truncated": original_row_count > len(selected_rows),
    }


def _select_field_list_table_row_indexes(
    *,
    row_texts: list[Any],
    original_row_count: int,
    terms: list[str],
    max_rows: int,
    expansion_level: str,
    selection_reason: str = "",
) -> tuple[list[int], dict[int, str]]:
    semantic_selected: dict[int, str] = {}
    window = 2 if expansion_level != "initial" else 1
    for index, text in enumerate(row_texts):
        if index >= original_row_count:
            break
        normalized_text = _normalize_evidence_match_text(str(text or ""))
        if not normalized_text:
            continue
        if not any(term and term in normalized_text for term in terms):
            continue
        for neighbor in range(max(0, index - window), min(original_row_count, index + window + 1)):
            semantic_selected.setdefault(neighbor, "semantic_window" if neighbor != index else "semantic_term_match")

    if semantic_selected and selection_reason == "semantic_term_match":
        ordered = sorted(semantic_selected)
        return ordered, semantic_selected

    if original_row_count <= max_rows:
        if selection_reason == "content_ref_record_table_preview":
            preview_count = 4 if expansion_level != "initial" else 2
            selected = {index: "record_table_preview" for index in range(min(preview_count, original_row_count))}
            if original_row_count > preview_count:
                selected[original_row_count - 1] = "tail_context"
            return sorted(selected), selected
        if semantic_selected and original_row_count > 8 and selection_reason != "content_ref_block":
            ordered = sorted(semantic_selected)
            return ordered, semantic_selected
        return list(range(original_row_count)), {index: "small_table" for index in range(original_row_count)}

    selected: dict[int, str] = {}
    head_count = min(8 if expansion_level != "initial" else 5, original_row_count)
    tail_count = min(4 if expansion_level != "initial" else 2, max(original_row_count - head_count, 0))
    for index in range(head_count):
        selected[index] = "head_context"
    for index in range(max(original_row_count - tail_count, head_count), original_row_count):
        selected[index] = "tail_context"

    selected.update(semantic_selected)

    ordered = sorted(selected)
    if len(ordered) > max_rows:
        priority = {"semantic_term_match": 0, "semantic_window": 1, "head_context": 2, "tail_context": 3}
        ordered = sorted(
            ordered,
            key=lambda item: (priority.get(selected[item], 9), item),
        )[:max_rows]
        ordered.sort()
    return ordered, selected


def _table_blocks_are_regular_record_like(table_blocks: list[dict[str, Any]]) -> bool:
    if not table_blocks:
        return False
    widths = [int(block.get("columnCount") or 0) for block in table_blocks]
    max_width = max(widths or [0])
    if max_width < 4:
        return False
    total_rows = sum(len(block.get("rows") or []) for block in table_blocks)
    if total_rows < 8:
        return False
    stable_rows = 0
    content_rich_rows = 0
    for block in table_blocks:
        for row in block.get("rows") or []:
            nonempty = [cell for cell in row if str(cell).strip()]
            if len(row) >= max(3, int(max_width * 0.7)):
                stable_rows += 1
            if len(nonempty) >= min(3, max_width):
                content_rich_rows += 1
    return stable_rows >= max(4, total_rows // 2) and content_rich_rows >= max(3, total_rows // 3)


def _build_table_record_preview_facts(facts_payload: dict[str, Any]) -> dict[str, Any]:
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    preview_pages: list[dict[str, Any]] = []
    table_seen = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        preview_blocks: list[dict[str, Any]] = []
        for block in page.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
            rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
            if not rows:
                continue
            keep_rows = 4 if table_seen == 0 else 2
            table_seen += 1
            selected_indexes = list(range(min(len(rows), keep_rows)))
            if len(rows) > keep_rows and len(rows) - 1 not in selected_indexes:
                selected_indexes.append(len(rows) - 1)
            preview_grid = _slice_table_grid_rows(
                table_grid=table_grid,
                selected_indexes=sorted(set(selected_indexes)),
                row_reason="record_preview",
            )
            preview_blocks.append({**block, "tableGrid": preview_grid})
        if preview_blocks:
            preview_pages.append({**page, "blocks": preview_blocks})
    return {"pages": preview_pages}


def _table_record_mapping_preview_skill(skill_meta: dict[str, Any], required_fields: list[str]) -> dict[str, Any]:
    fields_text = "、".join(required_fields) if required_fields else "从原 Skill 输出字段中判断"
    return {
        **_skill_payload_for_llm(skill_meta),
        "id": f"{skill_meta.get('id') or 'record_collection'}:column-mapping-preview",
        "name": f"{skill_meta.get('name') or '记录集合'}列语义确认",
        "outputSchema": {"type": "custom", "required": ["columnMapping"]},
        "promptTemplate": (
            "这是长表格快路径的列语义确认，不是最终抽取。"
            "只根据 facts 中可见的少量预览行判断记录字段和表格列的对应关系。"
            "不要输出完整 records，不要补全预览窗口外的行。"
            f"需要映射的目标字段：{fields_text}。"
            "返回裸 JSON 对象，格式为："
            '{"columnMapping":[{"field":"字段名","columnIndex":0,"header":"可见表头或列含义","confidence":0.0}],'
            '"notes":[]}'
            "columnIndex 必须是 tableGrid.rows 的 0 基列序号；无法确认的字段不要输出。"
        ),
        "rules": [
            "只做列语义确认，不做全量记录抽取。",
            "columnIndex 使用 0 基序号。",
            "不要输出 records；如需举例，最多放入 notes，不要生成记录数组。",
        ],
        "examples": [],
    }


def _table_record_mapping_cache_key(
    *,
    skill_meta: dict[str, Any],
    required_fields: list[str],
    table_blocks: list[dict[str, Any]],
) -> str:
    prompt_text = " ".join(
        str(skill_meta.get(key) or "")
        for key in ("id", "version", "name", "promptTemplate", "skillText")
    )
    table_signatures: list[dict[str, Any]] = []
    for block in table_blocks[:8]:
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        table_signatures.append(
            {
                "columnCount": int(block.get("columnCount") or 0),
                "rowCountBucket": min(500, max(0, len(rows))),
                "headRows": [
                    _row_signature([str(cell or "") for cell in row])
                    for row in rows[:4]
                    if isinstance(row, list)
                ],
            }
        )
    payload = {
        "schema": "table_record_mapping_cache_v1",
        "skillHash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16],
        "requiredFields": required_fields,
        "tables": table_signatures,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:32]


def _table_record_mapping_cache_payload(
    *,
    cache_key: str,
    mapping: dict[str, Any],
    required_fields: list[str],
    table_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": "table_record_mapping_cache_v1",
        "cacheKey": cache_key,
        "requiredFields": list(required_fields),
        "mapping": mapping,
        "tableCount": len(table_blocks),
        "columnCounts": [int(block.get("columnCount") or 0) for block in table_blocks[:16]],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def _validate_cached_table_record_mapping(
    *,
    cached_payload: dict[str, Any],
    required_fields: list[str],
    table_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    if cached_payload.get("version") != "table_record_mapping_cache_v1":
        return {}
    if list(cached_payload.get("requiredFields") or []) != list(required_fields):
        return {}
    if int(cached_payload.get("tableCount") or 0) != len(table_blocks):
        return {}
    expected_widths = [int(block.get("columnCount") or 0) for block in table_blocks[:16]]
    if list(cached_payload.get("columnCounts") or []) != expected_widths:
        return {}
    mapping = cached_payload.get("mapping") if isinstance(cached_payload.get("mapping"), dict) else {}
    columns = mapping.get("columns") if isinstance(mapping.get("columns"), dict) else {}
    if not columns:
        return {}
    return mapping


def _infer_table_record_column_mapping_from_llm_mapping(
    *,
    table_blocks: list[dict[str, Any]],
    mapping_payload: dict[str, Any],
    required_fields: list[str],
) -> dict[str, Any]:
    raw_mapping = mapping_payload.get("columnMapping")
    if raw_mapping is None:
        raw_mapping = mapping_payload.get("columns")

    mapping_items: list[dict[str, Any]] = []
    if isinstance(raw_mapping, dict):
        for field, value in raw_mapping.items():
            if isinstance(value, dict):
                mapping_items.append({"field": field, **value})
            else:
                mapping_items.append({"field": field, "columnIndex": value})
    elif isinstance(raw_mapping, list):
        mapping_items = [item for item in raw_mapping if isinstance(item, dict)]

    if not mapping_items:
        return {}

    expected_fields = set(required_fields)
    max_width = max((int(block.get("columnCount") or 0) for block in table_blocks), default=0)
    columns: dict[str, int] = {}
    header_by_field: dict[str, str] = {}
    for item in mapping_items:
        field = str(item.get("field") or item.get("name") or item.get("key") or "").strip()
        if not field or (expected_fields and field not in expected_fields):
            continue
        raw_index = item.get("columnIndex")
        if raw_index is None:
            raw_index = item.get("column_index")
        if raw_index is None:
            raw_index = item.get("index")
        try:
            column_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if column_index >= max_width and 0 <= column_index - 1 < max_width:
            column_index -= 1
        if column_index < 0 or column_index >= max_width:
            continue
        columns[field] = column_index
        header = str(item.get("header") or item.get("label") or item.get("columnName") or "").strip()
        if header:
            header_by_field[field] = header

    fields = required_fields or list(columns.keys())
    fields = [field for field in fields if field and field != "source_page"]
    minimum_mapped = min(len(fields), 3)
    if len(columns) < minimum_mapped:
        return {}

    first_data_row_by_table: dict[str, int] = {}
    header_rows: dict[str, list[str]] = {}
    for block_index, block in enumerate(table_blocks):
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        header_index = _find_table_record_header_row_index(
            rows=rows,
            columns=columns,
            header_by_field=header_by_field,
        )
        if header_index is not None and 0 <= header_index < len(rows):
            header_rows[str(block_index)] = rows[header_index]
            first_data_row_by_table[str(block_index)] = header_index + 1
        else:
            first_data_row_by_table[str(block_index)] = 0

    return {
        "columns": columns,
        "matchedPreviewRows": [],
        "firstDataRowByTable": first_data_row_by_table,
        "headerRows": header_rows,
        "mappedFieldCount": len(columns),
        "source": "llm_column_mapping",
    }


def _find_table_record_header_row_index(
    *,
    rows: list[Any],
    columns: dict[str, int],
    header_by_field: dict[str, str],
) -> int | None:
    if not header_by_field:
        return None
    best_index: int | None = None
    best_score = 0
    for row_index, row in enumerate(rows[:8]):
        if not isinstance(row, list):
            continue
        score = 0
        for field, column_index in columns.items():
            if column_index < 0 or column_index >= len(row):
                continue
            expected_header = header_by_field.get(field)
            if not expected_header:
                continue
            cell = str(row[column_index] or "").strip()
            if _compact_match_text(cell) == _compact_match_text(expected_header):
                score += 2
            elif _normalize_evidence_match_text(expected_header) in _normalize_evidence_match_text(cell):
                score += 1
        if score > best_score:
            best_index = row_index
            best_score = score
    threshold = max(2, min(4, len(header_by_field)))
    return best_index if best_score >= threshold else None


def _infer_table_record_column_mapping(
    *,
    table_blocks: list[dict[str, Any]],
    preview_records: list[dict[str, Any]],
    required_fields: list[str],
) -> dict[str, Any]:
    fields = required_fields or _fields_from_preview_records(preview_records)
    fields = [field for field in fields if field and field != "source_page"]
    if not fields:
        return {}

    matched_pairs: list[tuple[int, int, dict[str, Any], list[str]]] = []
    for record in preview_records:
        best: tuple[int, int, int, list[str]] | None = None
        for block_index, block in enumerate(table_blocks):
            for row_index, row in enumerate(block.get("rows") or []):
                score = _score_record_against_row(record, row, fields)
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, block_index, row_index, row)
        if best and best[0] >= 2:
            matched_pairs.append((best[1], best[2], record, best[3]))

    if not matched_pairs:
        return {}

    column_votes: dict[str, dict[int, int]] = {field: {} for field in fields}
    for _block_index, _row_index, record, row in matched_pairs:
        for field in fields:
            value = record.get(field)
            if value is None or str(value).strip() == "":
                continue
            column_index = _best_matching_column(str(value), row)
            if column_index is None:
                continue
            votes = column_votes.setdefault(field, {})
            votes[column_index] = votes.get(column_index, 0) + 1

    columns: dict[str, int] = {}
    for field, votes in column_votes.items():
        if not votes:
            continue
        columns[field] = sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0][0]

    minimum_mapped = min(len(fields), 3)
    if len(columns) < minimum_mapped:
        return {}

    first_data_row_by_table: dict[str, int] = {}
    header_rows: dict[str, list[str]] = {}
    for block_index, row_index, _record, _row in matched_pairs:
        key = str(block_index)
        previous = first_data_row_by_table.get(key)
        if previous is None or row_index < previous:
            first_data_row_by_table[key] = row_index
            if row_index > 0:
                header_rows[key] = table_blocks[block_index]["rows"][row_index - 1]

    return {
        "columns": columns,
        "matchedPreviewRows": [
            {"tableIndex": block_index, "rowIndex": row_index}
            for block_index, row_index, _record, _row in matched_pairs
        ],
        "firstDataRowByTable": first_data_row_by_table,
        "headerRows": header_rows,
        "mappedFieldCount": len(columns),
    }


def _fields_from_preview_records(records: list[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record.keys():
            text = str(key or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            fields.append(text)
    return fields


def _score_record_against_row(record: dict[str, Any], row: list[str], fields: list[str]) -> int:
    score = 0
    for field in fields:
        value = record.get(field)
        if value is None or str(value).strip() == "":
            continue
        if _best_matching_column(str(value), row) is not None:
            score += 1
    return score


def _best_matching_column(value: str, row: list[str]) -> int | None:
    normalized_value = _normalize_match_text(value)
    compact_value = _compact_match_text(value)
    if not normalized_value:
        return None
    best_index: int | None = None
    best_score = 0
    for index, cell in enumerate(row):
        normalized_cell = _normalize_match_text(cell)
        if not normalized_cell:
            continue
        compact_cell = _compact_match_text(cell)
        score = 0
        if normalized_cell == normalized_value:
            score = 4
        elif compact_cell and compact_cell == compact_value:
            score = 3
        elif len(normalized_value) >= 3 and normalized_value in normalized_cell:
            score = 2
        elif len(normalized_cell) >= 3 and normalized_cell in normalized_value:
            score = 1
        if score > best_score:
            best_index = index
            best_score = score
    return best_index


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _compact_match_text(value: Any) -> str:
    return re.sub(r"[\s,，。:：/\\\-年月日]+", "", str(value or "").strip()).lower()


def _build_records_from_table_mapping(
    *,
    table_blocks: list[dict[str, Any]],
    mapping: dict[str, Any],
    required_fields: list[str],
) -> list[dict[str, Any]]:
    columns = mapping.get("columns") if isinstance(mapping.get("columns"), dict) else {}
    if not columns:
        return []
    fields = required_fields or list(columns.keys())
    first_data_row_by_table = mapping.get("firstDataRowByTable") if isinstance(mapping.get("firstDataRowByTable"), dict) else {}
    header_rows = mapping.get("headerRows") if isinstance(mapping.get("headerRows"), dict) else {}
    records: list[dict[str, Any]] = []
    for block_index, block in enumerate(table_blocks):
        start_index = 0
        try:
            start_index = int(first_data_row_by_table.get(str(block_index), 0))
        except (TypeError, ValueError):
            start_index = 0
        header_row = header_rows.get(str(block_index))
        page_no = int(block.get("pageNo") or 0)
        for row_index, row in enumerate(block.get("rows") or []):
            if row_index < start_index:
                continue
            if _row_should_skip_for_table_record(row, header_row=header_row):
                continue
            record: dict[str, Any] = {}
            nonempty_mapped_values = 0
            for field in fields:
                column_index = columns.get(field)
                value = ""
                if isinstance(column_index, int) and 0 <= column_index < len(row):
                    value = str(row[column_index] or "").strip()
                if value:
                    nonempty_mapped_values += 1
                record[field] = value
            if nonempty_mapped_values < max(1, min(2, len(columns))):
                continue
            if page_no > 0:
                record["source_page"] = page_no
            records.append(record)
    return records


def _row_should_skip_for_table_record(row: list[str], *, header_row: list[str] | None) -> bool:
    values = [str(cell or "").strip() for cell in row]
    nonempty = [value for value in values if value]
    if not nonempty:
        return True
    if header_row is not None and _row_signature(values) == _row_signature(header_row):
        return True
    unique_values: dict[str, int] = {}
    for value in nonempty:
        unique_values[value] = unique_values.get(value, 0) + 1
    max_repeat = max(unique_values.values() or [0])
    if len(unique_values) <= 2 and max_repeat >= max(3, len(nonempty) // 2):
        return True
    return False


def _row_signature(row: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_match_text(cell) for cell in row)


class PromptPipelineService:
    """Create page or page-group runs, persist I/O, and rebuild workbench detail."""

    def __init__(
        self,
        *,
        repository: WorkbenchRepository,
        runtime_store: JsonRuntimeStore,
        llm_service: PromptLlmService,
        settings: AppSettings,
        oss_service: OssStorageService | None = None,
    ) -> None:
        self._repository = repository
        self._runtime_store = runtime_store
        self._oss_service = oss_service
        self._llm_service = llm_service
        self._settings = settings
        self._extraction_runtime_kernel = ExtractionRuntimeKernel()

    def _build_extraction_runtime_ports(self) -> ExtractionRuntimePorts:
        return ExtractionRuntimePorts(
            build_compact_extraction_facts=build_compact_extraction_facts,
            build_application_scope=_application_extraction_scope,
            build_runtime_contract=_application_runtime_contract,
            enrich_field_list_config=enrich_field_list_extraction_config,
            compact_application_scope=compact_application_scope_for_runtime,
            augment_evidence_index=_augment_evidence_index_with_runtime_contract,
            build_runtime_evidence_package=_build_runtime_evidence_package,
            build_field_list_evidence_package=_build_field_list_evidence_package,
            apply_field_list_row_budget=apply_field_list_global_row_budget,
            assess_table_review_risk=_assess_table_review_risk,
            build_evidence_v2_model_package=build_evidence_v2_model_package,
            build_evidence_v2_shadow_package=build_evidence_v2_shadow_package,
            build_evidence_v2_failure_package=build_evidence_v2_failure_package,
            evidence_v2_runtime_selection=_evidence_v2_runtime_selection,
            build_payload_metrics=_build_extraction_payload_metrics,
            evidence_selection_metric_summary=_evidence_selection_metric_summary,
            skill_payload_for_llm=_skill_payload_for_llm,
            format_page_range=_format_page_range,
            run_llm_extraction=self._llm_service.run_extraction_skill,
            try_table_fast_path=lambda request, prepared: self._try_execute_table_record_fast_path(
                run=request.run,
                skill_meta=prepared.skill_meta,
                config=prepared.config,
                facts_payload=prepared.facts_payload,
                model_facts_payload=prepared.model_facts_payload,
            ),
            review_field_list=lambda request, prepared, raw_payload, output: self._review_field_list_extraction_if_needed(
                run=request.run,
                skill_meta=prepared.skill_meta,
                config=prepared.config,
                facts_payload=prepared.review_facts_payload,
                evidence_selection=prepared.review_evidence_selection,
                application_scope=prepared.application_scope,
                runtime_contract=prepared.runtime_contract,
                raw_payload=raw_payload,
                output=output,
                fallback_facts_payload=prepared.fallback_review_facts_payload,
                fallback_evidence_selection=prepared.fallback_review_evidence_selection,
            ),
            preserve_review_source_pages=_preserve_review_field_source_pages,
            estimate_json_payload_bytes=_estimate_json_payload_bytes,
            build_run_meta=_build_extraction_run_meta,
            normalize_output=_normalize_extraction_skill_output,
            enrich_result_from_application_scope=_enrich_field_list_extraction_result_from_application_scope,
            completion_status_from_errors=_completion_status_from_validation_errors,
            settings=self._settings,
            logger=logger,
        )

    def execute_extraction_runtime_request(
        self,
        request: ExtractionRuntimeRequest,
        *,
        started_at: float | None = None,
    ) -> ExtractionRuntimeResult:
        ports = self._build_extraction_runtime_ports()
        prepared = self._extraction_runtime_kernel.prepare(request, ports=ports)
        return self._extraction_runtime_kernel.execute(
            request,
            prepared,
            ports=ports,
            started_at=started_at,
        )

    def execute_extraction_prompt_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> PromptRunRecord:
        """Execute an extraction prompt run through the runtime kernel."""

        return self._execute_single_extraction_skill_run(run, available_pages=available_pages)

    def _persist_run_artifact(
        self,
        *,
        run: PromptRunRecord,
        stage: str,
        artifact_kind: str,
        file_name: str,
        payload: Any,
        summary: dict[str, Any],
        page_no: int | None = None,
    ) -> None:
        if not self._oss_service:
            raise RuntimeError("OSS service is required to persist task result artifacts.")
        stored = write_json_artifact(
            oss_service=self._oss_service,
            object_key=build_task_object_key(run.taskId, "runs", run.id, file_name),
            payload=payload,
        )
        now = self._now_iso()
        self._repository.save_result_artifact(
            TaskResultArtifactRecord(
                id=f"artifact-{uuid4().hex[:12]}",
                taskId=run.taskId,
                documentId=run.documentId,
                pageNo=page_no,
                runId=run.id,
                stage=stage,
                artifactKind=artifact_kind,
                objectKey=stored.objectKey,
                contentHash=stored.contentHash,
                sizeBytes=stored.sizeBytes,
                contentType=stored.contentType,
                summary=summary,
                createdAt=now,
                updatedAt=now,
            )
        )

    def _run_with_phase(self, run: PromptRunRecord, phase: str) -> PromptRunRecord:
        now = self._now_iso()
        return replace(
            run,
            runPhase=phase,
            phaseStartedAt=now,
            lastHeartbeatAt=now,
            updatedAt=now,
        )

    def _persist_llm_logs(
        self,
        *,
        run: PromptRunRecord,
        output: PromptRunOutput,
        stage: str,
        skill_id: str | None = None,
    ) -> None:
        if not output.llmLogs:
            return
        self._runtime_store.write_json_log("llm", run.taskId, f"{run.id}.json", output.llmLogs)
        self._persist_llm_call_traces(
            run=run,
            logs=output.llmLogs,
            stage=stage,
            default_provider=output.provider,
            default_model=output.model,
            skill_id=skill_id,
        )

    def _persist_llm_call_traces(
        self,
        *,
        run: PromptRunRecord,
        logs: dict[str, Any],
        stage: str,
        default_provider: str,
        default_model: str,
        skill_id: str | None,
    ) -> None:
        entries = logs.get("requests") if isinstance(logs.get("requests"), list) else [logs]
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                continue
            request_payload = entry.get("request")
            response_payload = entry.get("response")
            if request_payload is None and response_payload is None:
                continue

            trace_id = f"llm-trace-{uuid4().hex[:12]}"
            request_object_key = None
            response_object_key = None
            if self._oss_service:
                if request_payload is not None:
                    request_object_key = self._write_trace_payload(
                        run=run,
                        trace_id=trace_id,
                        suffix="request",
                        payload=_redact_sensitive_payload(request_payload),
                    )
                if response_payload is not None:
                    response_object_key = self._write_trace_payload(
                        run=run,
                        trace_id=trace_id,
                        suffix="response",
                        payload=_redact_sensitive_payload(response_payload),
                    )

            trace_meta = entry.get("trace") if isinstance(entry.get("trace"), dict) else {}
            usage = response_payload.get("usage") if isinstance(response_payload, dict) and isinstance(response_payload.get("usage"), dict) else {}
            now = self._now_iso()
            trace = LlmCallTraceRecord(
                id=trace_id,
                taskId=run.taskId,
                documentId=run.documentId,
                runId=run.id,
                stage=stage,
                requestKind=str(entry.get("requestKind") or logs.get("mode") or f"request-{index}"),
                status="completed",
                runPhase=_normalize_run_phase(run),
                provider=str(logs.get("provider") or default_provider or "") or None,
                model=str(logs.get("model") or default_model or "") or None,
                skillId=skill_id,
                inputChars=_coerce_int(trace_meta.get("inputChars"), _json_char_length(request_payload)),
                outputChars=_coerce_int(trace_meta.get("outputChars"), _response_content_length(response_payload)),
                promptTokens=_coerce_optional_int(trace_meta.get("promptTokens") or usage.get("prompt_tokens")),
                completionTokens=_coerce_optional_int(trace_meta.get("completionTokens") or usage.get("completion_tokens")),
                totalTokens=_coerce_optional_int(trace_meta.get("totalTokens") or usage.get("total_tokens")),
                httpMs=_coerce_optional_int(trace_meta.get("durationMs")),
                totalMs=_coerce_optional_int(trace_meta.get("durationMs")),
                errorType=None,
                requestObjectKey=request_object_key,
                responseObjectKey=response_object_key,
                createdAt=now,
                updatedAt=now,
            )
            self._repository.save_llm_call_trace(trace)

    def _write_trace_payload(self, *, run: PromptRunRecord, trace_id: str, suffix: str, payload: Any) -> str:
        if not self._oss_service:
            raise RuntimeError("OSS service is required to persist LLM trace payloads.")
        stored = write_json_artifact(
            oss_service=self._oss_service,
            object_key=build_task_object_key(run.taskId, "llm-traces", run.id, f"{trace_id}-{suffix}.json"),
            payload=payload,
        )
        return stored.objectKey

    def _persist_parse_targets_for_run(
        self,
        *,
        run: PromptRunRecord,
        pages: list[WorkbenchPageDetail],
    ) -> None:
        if run.runPurpose != "parse_prompt" or run.status not in {"completed", "needs_review"}:
            return
        for page in pages:
            targets = build_page_operation_targets(page=page, parse_run=run)
            self._repository.replace_operation_targets(
                run.taskId,
                page.pageNo,
                run.id,
                targets,
            )

    def execute_prompt_runs(self, taskId: str, payload: PromptExecutionRequest) -> PromptExecutionResponse:
        execution_context = self._repository.get_task_execution_context(taskId)
        source_pages = self._merge_prompt_context_pages(
            base_pages=execution_context.pages,
            page_context=payload.pageContext,
        )
        self._ensure_task_ready(execution_context.parseStatus, source_pages)

        end_page_no = payload.endPageNo or payload.startPageNo
        scopes = self._build_scopes(
            start_page_no=payload.startPageNo,
            end_page_no=end_page_no,
            run_mode=payload.runMode,
            page_group_size=payload.pageGroupSize,
        )
        document_id = execution_context.documentId
        created_runs: list[PromptRunRecord] = []
        run_async = not payload.createSummary

        for start_page_no, end_page_no in scopes:
            config = PromptConfigRecord(
                id=f"prompt-config-{uuid4().hex[:10]}",
                taskId=taskId,
                promptName=payload.promptName,
                promptText=payload.promptText,
                startPageNo=start_page_no,
                endPageNo=end_page_no,
                runPurpose=payload.runPurpose,
                sourceTemplateId=payload.templateId,
                updatedAt=self._now_iso(),
            )
            self._repository.save_prompt_config(config)
            run = PromptRunRecord(
                id=f"prompt-run-{uuid4().hex[:12]}",
                taskId=taskId,
                documentId=document_id,
                runType="page" if start_page_no == end_page_no else "page_group",
                runName=payload.runName or f"{payload.promptName} {_format_page_range(start_page_no, end_page_no)}",
                promptName=payload.promptName,
                promptText=payload.promptText,
                startPageNo=start_page_no,
                endPageNo=end_page_no,
                status="running",
                runPurpose=payload.runPurpose,
                promptConfigId=config.id,
                templateId=payload.templateId,
                schemaDefinition={"tableTaskMode": payload.tableTaskMode},
                updatedAt=self._now_iso(),
            )
            if run_async:
                saved_run = self._repository.save_prompt_run(run, refresh_task=False)
                self._start_background_run(saved_run, available_pages=source_pages)
                created_runs.append(saved_run)
            else:
                created_runs.append(self._execute_single_run(run, available_pages=source_pages))

        summary_run = None
        if payload.createSummary:
            summary_run = self._create_summary_run(taskId)

        response_detail = None if run_async else self._repository.get_task_detail(taskId)
        return PromptExecutionResponse(
            taskDetail=response_detail,
            runs=[self._to_run_response(run) for run in created_runs],
            summaryRun=self._to_run_response(summary_run) if summary_run else None,
        )

    def execute_schema_runs(self, taskId: str, payload: SchemaRunRequest) -> PromptExecutionResponse:
        execution_context = self._repository.get_task_execution_context(taskId)
        self._ensure_task_ready(execution_context.parseStatus, execution_context.pages)
        template = self._repository.get_schema_template(payload.templateId)
        end_page_no = payload.endPageNo or payload.startPageNo
        scopes = self._build_scopes(
            start_page_no=payload.startPageNo,
            end_page_no=end_page_no,
            run_mode=payload.runMode,
            page_group_size=payload.pageGroupSize,
        )
        document_id = execution_context.documentId
        created_runs: list[PromptRunRecord] = []
        run_async = not payload.createSummary

        for start_page_no, end_page_no in scopes:
            config = PromptConfigRecord(
                id=f"prompt-config-{uuid4().hex[:10]}",
                taskId=taskId,
                promptName=template.name,
                promptText=template.instructions or template.name,
                startPageNo=start_page_no,
                endPageNo=end_page_no,
                runPurpose="schema_process",
                sourceTemplateId=template.id,
                updatedAt=self._now_iso(),
            )
            self._repository.save_prompt_config(config)
            run = PromptRunRecord(
                id=f"prompt-run-{uuid4().hex[:12]}",
                taskId=taskId,
                documentId=document_id,
                runType="page" if start_page_no == end_page_no else "page_group",
                runName=payload.runName or f"{template.name} {_format_page_range(start_page_no, end_page_no)}",
                promptName=template.name,
                promptText=template.instructions or template.name,
                startPageNo=start_page_no,
                endPageNo=end_page_no,
                status="running",
                runPurpose="schema_process",
                promptConfigId=config.id,
                templateId=template.id,
                schemaTemplateName=template.name,
                schemaTemplateVersion=template.updatedAt,
                schemaDefinition=self._build_runtime_schema_definition(template.schemaDefinition),
                updatedAt=self._now_iso(),
            )
            if run_async:
                saved_run = self._repository.save_prompt_run(run, refresh_task=False)
                self._start_background_schema_run(saved_run, available_pages=execution_context.pages)
                created_runs.append(saved_run)
            else:
                created_runs.append(self._execute_single_schema_run(run, available_pages=execution_context.pages))

        summary_run = None
        if payload.createSummary:
            summary_run = self._create_summary_run(taskId)

        response_detail = None if run_async else self._repository.get_task_detail(taskId)
        return PromptExecutionResponse(
            taskDetail=response_detail,
            runs=[self._to_run_response(run) for run in created_runs],
            summaryRun=self._to_run_response(summary_run) if summary_run else None,
        )

    def execute_post_process_runs(self, taskId: str, payload: PostProcessRunRequest) -> PromptExecutionResponse:
        execution_context = self._repository.get_task_execution_context(taskId)
        self._ensure_task_ready(execution_context.parseStatus, execution_context.pages)

        end_page_no = payload.endPageNo or payload.startPageNo
        scopes = self._build_scopes(
            start_page_no=payload.startPageNo,
            end_page_no=end_page_no,
            run_mode=payload.runMode,
            page_group_size=payload.pageGroupSize,
        )
        created_runs: list[PromptRunRecord] = []
        run_async = not payload.createSummary

        for start_page_no, end_page_no in scopes:
            config = PromptConfigRecord(
                id=f"prompt-config-{uuid4().hex[:10]}",
                taskId=taskId,
                promptName="二次处理",
                promptText=payload.instruction,
                startPageNo=start_page_no,
                endPageNo=end_page_no,
                runPurpose="post_process",
                updatedAt=self._now_iso(),
            )
            self._repository.save_prompt_config(config)
            run = PromptRunRecord(
                id=f"prompt-run-{uuid4().hex[:12]}",
                taskId=taskId,
                documentId=execution_context.documentId,
                runType="page" if start_page_no == end_page_no else "page_group",
                runName=payload.runName or f"二次处理 {_format_page_range(start_page_no, end_page_no)}",
                promptName="二次处理",
                promptText=payload.instruction,
                startPageNo=start_page_no,
                endPageNo=end_page_no,
                status="running",
                runPurpose="post_process",
                promptConfigId=config.id,
                schemaDefinition={"responseMode": payload.responseMode},
                updatedAt=self._now_iso(),
            )
            if run_async:
                saved_run = self._repository.save_prompt_run(run, refresh_task=False)
                self._start_background_post_process_run(saved_run, available_pages=execution_context.pages)
                created_runs.append(saved_run)
            else:
                created_runs.append(
                    self._execute_single_post_process_run(
                        run,
                        available_pages=execution_context.pages,
                    )
                )

        summary_run = None
        if payload.createSummary:
            summary_run = self._create_summary_run(taskId)

        response_detail = None if run_async else self._repository.get_task_detail(taskId)
        return PromptExecutionResponse(
            taskDetail=response_detail,
            runs=[self._to_run_response(run) for run in created_runs],
            summaryRun=self._to_run_response(summary_run) if summary_run else None,
        )

    def execute_extraction_skill_run(
        self,
        taskId: str,
        payload: ExtractionSkillRunRequest,
    ) -> PromptExecutionResponse:
        execution_context = self._repository.get_task_execution_context(taskId)
        self._ensure_task_ready(execution_context.parseStatus, execution_context.pages)
        page = next((item for item in execution_context.pages if item.pageNo == payload.pageNo), None)
        if not page:
            raise RuntimeError("当前页不存在，无法执行解析 skill。")

        task = self._repository.get_task_record(taskId)
        registry = ExtractionSkillRegistry(
            repository=self._repository,
            settings=self._settings,
            oss_service=self._oss_service,
        )
        skill = registry.resolve_skill(
            skill_id=payload.skillId,
            customer_id=task.customerId,
            version=payload.skillVersion,
        )
        config = merge_extraction_skill_config(skill, payload.config)
        skill_snapshot = {
            "id": skill.id,
            "version": skill.version,
            "name": skill.name,
            "category": skill.category,
            "sourceTypes": list(skill.sourceTypes),
            "executor": skill.executor,
            "inputBuilder": skill.inputBuilder,
            "renderer": skill.renderer,
            "configSchema": skill.configSchema,
            "outputSchema": skill.outputSchema,
            "summaryTemplate": skill.summaryTemplate,
            "promptTemplate": skill.promptTemplate,
            "skillText": skill.skillText,
            "rules": list(skill.rules),
            "examples": list(skill.examples),
            "defaults": dict(skill.defaults or {}),
        }
        config_record = PromptConfigRecord(
            id=f"prompt-config-{uuid4().hex[:10]}",
            taskId=taskId,
            promptName=skill.name,
            promptText=skill.promptTemplate or skill.name,
            startPageNo=payload.pageNo,
            endPageNo=payload.pageNo,
            runPurpose="parse_prompt",
            sourceTemplateId=skill.id,
            updatedAt=self._now_iso(),
        )
        self._repository.save_prompt_config(config_record)
        run = PromptRunRecord(
            id=f"prompt-run-{uuid4().hex[:12]}",
            taskId=taskId,
            documentId=execution_context.documentId,
            runType="page",
            runName=f"{skill.name} 结构化解析",
            promptName=skill.name,
            promptText=skill.promptTemplate or skill.name,
            startPageNo=payload.pageNo,
            endPageNo=payload.pageNo,
            status="running",
            runPurpose="parse_prompt",
            promptConfigId=config_record.id,
            templateId=skill.id,
            schemaTemplateName=skill.name,
            schemaTemplateVersion=skill.version,
            schemaDefinition={
                "protocol": "extraction_skill_v1",
                "skill": skill_snapshot,
                "config": config,
            },
            updatedAt=self._now_iso(),
        )
        saved_run = self._repository.save_prompt_run(run, refresh_task=False)
        self._start_background_extraction_skill_run(saved_run, available_pages=execution_context.pages)
        return PromptExecutionResponse(
            taskDetail=None,
            runs=[self._to_run_response(saved_run)],
            summaryRun=None,
        )

    def execute_object_operation_run(
        self,
        taskId: str,
        payload: ObjectOperationRunRequest,
    ) -> ObjectOperationExecutionResponse:
        execution_context = self._repository.get_task_execution_context(taskId)
        self._ensure_task_ready(execution_context.parseStatus, execution_context.pages)
        page = next((item for item in execution_context.pages if item.pageNo == payload.pageNo), None)
        if not page:
            raise RuntimeError("当前页不存在，无法执行对象处理。")

        run = PromptRunRecord(
            id=f"prompt-run-{uuid4().hex[:12]}",
            taskId=taskId,
            documentId=execution_context.documentId,
            runType="page",
            runName=f"{payload.target.label} 对象处理",
            promptName="对象处理",
            promptText=payload.instruction,
            startPageNo=payload.pageNo,
            endPageNo=payload.pageNo,
            status="running",
            runPurpose="post_process",
            schemaDefinition={
                "operationType": payload.operationType,
                "resultMode": payload.resultMode,
                "target": payload.target.model_dump(),
                "relatedTargets": [item.model_dump() for item in payload.relatedTargets],
                "responseMode": "auto",
            },
            updatedAt=self._now_iso(),
        )
        completed_run = self._execute_single_object_operation_run(
            run,
            target=payload.target,
            related_targets=payload.relatedTargets,
            available_pages=execution_context.pages,
        )
        return ObjectOperationExecutionResponse(
            run=self._to_run_response(completed_run),
            result=build_object_operation_result(completed_run),
        )

    def execute_skill_run(
        self,
        taskId: str,
        payload: SkillRunRequest,
    ) -> ObjectOperationExecutionResponse:
        execution_context = self._repository.get_task_execution_context(taskId)
        self._ensure_task_ready(execution_context.parseStatus, execution_context.pages)
        page = next((item for item in execution_context.pages if item.pageNo == payload.pageNo), None)
        if not page:
            raise RuntimeError("当前页不存在，无法执行业务 skill。")

        task = self._repository.get_task_record(taskId)
        registry = BusinessSkillRegistry(
            repository=self._repository,
            settings=self._settings,
            oss_service=self._oss_service,
        )
        skill = registry.resolve_skill(
            skill_id=payload.skillId,
            customer_id=task.customerId,
            version=payload.skillVersion,
        )
        config = merge_skill_config(skill, payload.config)

        target_response = self._repository.get_task_page_operation_targets(taskId, payload.pageNo)
        targets_by_id = {item.id: item for item in target_response.targets}
        if not payload.targetIds:
            raise RuntimeError("业务处理必须指定已保存的处理目标。")
        missing_target_ids = [target_id for target_id in payload.targetIds if target_id not in targets_by_id]
        if missing_target_ids:
            raise RuntimeError(f"处理目标不存在或尚未持久化：{', '.join(missing_target_ids)}")
        selected_targets = [targets_by_id[target_id] for target_id in payload.targetIds]
        if not selected_targets:
            raise RuntimeError("当前页没有可处理的提取目标。")

        target = selected_targets[0]
        related_targets = selected_targets[1:]
        operation_type = _operation_type_for_skill_executor(skill.executor)
        result_mode = skill.resultKind if skill.resultKind in {"decision", "object", "table", "text"} else "auto"
        upstream_context = self._build_skill_chain_context(taskId, payload.upstreamRunIds)
        instruction = _build_skill_instruction(
            skill_name=skill.name,
            prompt_template=skill.promptTemplate,
            config=config,
            selected_targets=selected_targets,
        )
        instruction = _append_skill_chain_context(instruction, upstream_context)
        skill_snapshot = {
            "id": skill.id,
            "version": skill.version,
            "name": skill.name,
            "executor": skill.executor,
            "targetTypes": list(skill.targetTypes),
            "resultKind": skill.resultKind,
            "renderer": skill.renderer,
            "config": config,
            "defaults": dict(skill.defaults or {}),
            "outputSchema": skill.outputSchema,
            "promptTemplate": skill.promptTemplate,
            "skillText": skill.skillText,
            "examples": skill.examples,
        }
        run = PromptRunRecord(
            id=f"prompt-run-{uuid4().hex[:12]}",
            taskId=taskId,
            documentId=execution_context.documentId,
            runType="page",
            runName=f"{skill.name} 业务处理",
            promptName=skill.name,
            promptText=instruction,
            startPageNo=payload.pageNo,
            endPageNo=payload.pageNo,
            status="running",
            runPurpose="post_process",
            schemaDefinition={
                "operationType": operation_type,
                "resultMode": result_mode,
                "target": target.model_dump(),
                "relatedTargets": [item.model_dump() for item in related_targets],
                "responseMode": "auto",
                "skill": skill_snapshot,
                "orchestration": {
                    "protocol": "skill_chain_v1",
                    "upstreamRunIds": payload.upstreamRunIds,
                    "upstreams": upstream_context,
                },
            },
            updatedAt=self._now_iso(),
        )
        completed_run = self._execute_single_object_operation_run(
            run,
            target=target,
            related_targets=related_targets,
            available_pages=execution_context.pages,
        )
        return ObjectOperationExecutionResponse(
            run=self._to_run_response(completed_run),
            result=build_object_operation_result(completed_run),
        )

    def _build_skill_chain_context(self, task_id: str, upstream_run_ids: list[str]) -> list[dict[str, Any]]:
        upstreams: list[dict[str, Any]] = []
        seen: set[str] = set()
        for run_id in upstream_run_ids:
            normalized_run_id = str(run_id or "").strip()
            if not normalized_run_id or normalized_run_id in seen:
                continue
            seen.add(normalized_run_id)
            run = self._repository.get_prompt_run(normalized_run_id)
            if run.taskId != task_id:
                raise RuntimeError(f"上游处理结果不属于当前任务：{normalized_run_id}")
            upstreams.append(_summarize_upstream_prompt_run(run))
        return upstreams

    def rerun_failed_pages(self, taskId: str, payload: FailedPromptRerunRequest) -> PromptExecutionResponse:
        execution_context = self._repository.get_task_execution_context(taskId)
        self._ensure_task_ready(execution_context.parseStatus, execution_context.pages)

        candidate_runs = [
            run
            for run in self._repository.list_prompt_runs(taskId)
            if run.runType != "summary" and run.status == "failed"
        ]
        if payload.runIds:
            allowed_run_ids = set(payload.runIds)
            candidate_runs = [run for run in candidate_runs if run.id in allowed_run_ids]
        if not candidate_runs:
            raise RuntimeError("当前任务没有可重跑的失败页或失败页组。")

        rerun_records: list[PromptRunRecord] = []
        run_async = not payload.createSummary
        for original_run in candidate_runs:
            rerun = PromptRunRecord(
                id=f"prompt-run-{uuid4().hex[:12]}",
                taskId=original_run.taskId,
                documentId=original_run.documentId,
                runType=original_run.runType,
                runName=f"{original_run.runName} 重跑",
                promptName=original_run.promptName,
                promptText=original_run.promptText,
                startPageNo=original_run.startPageNo,
                endPageNo=original_run.endPageNo,
                status="running",
                runPurpose=original_run.runPurpose,
                promptConfigId=original_run.promptConfigId,
                templateId=original_run.templateId,
                schemaTemplateName=original_run.schemaTemplateName,
                schemaTemplateVersion=original_run.schemaTemplateVersion,
                schemaDefinition=original_run.schemaDefinition,
                updatedAt=self._now_iso(),
            )
            if run_async:
                saved_run = self._repository.save_prompt_run(rerun, refresh_task=False)
                if original_run.runPurpose == "schema_process":
                    self._start_background_schema_run(saved_run, available_pages=execution_context.pages)
                elif original_run.runPurpose == "post_process":
                    self._start_background_post_process_run(saved_run, available_pages=execution_context.pages)
                else:
                    self._start_background_run(saved_run, available_pages=execution_context.pages)
                rerun_records.append(saved_run)
            else:
                if original_run.runPurpose == "schema_process":
                    rerun_records.append(self._execute_single_schema_run(rerun, available_pages=execution_context.pages))
                elif original_run.runPurpose == "post_process":
                    rerun_records.append(
                        self._execute_single_post_process_run(rerun, available_pages=execution_context.pages)
                    )
                else:
                    rerun_records.append(self._execute_single_run(rerun, available_pages=execution_context.pages))

        summary_run = None
        if payload.createSummary:
            summary_run = self._create_summary_run(taskId)

        response_detail = None if run_async else self._repository.get_task_detail(taskId)
        return PromptExecutionResponse(
            taskDetail=response_detail,
            runs=[self._to_run_response(run) for run in rerun_records],
            summaryRun=self._to_run_response(summary_run) if summary_run else None,
        )

    def run_summary(self, taskId: str, payload: SummaryExecutionRequest) -> PromptExecutionResponse:
        self._repository.get_task_detail(taskId)
        summary_run = self._create_summary_run(
            taskId,
            prompt_name=payload.promptName,
            prompt_text=payload.promptText,
            run_name=payload.runName,
        )
        return PromptExecutionResponse(
            taskDetail=self._repository.get_task_detail(taskId),
            runs=[],
            summaryRun=self._to_run_response(summary_run) if summary_run else None,
        )

    def _execute_single_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> PromptRunRecord:
        source_pages = (
            available_pages
            if available_pages is not None
            else self._repository.get_task_execution_context(run.taskId).pages
        )
        pages = self._select_run_pages(
            source_pages,
            run=run,
        )
        logger.info(
            "[PromptPipeline] start runId=%s taskId=%s pageRange=%s promptName=%s pageCount=%s",
            run.id,
            run.taskId,
            _format_page_range(run.startPageNo, run.endPageNo),
            run.promptName,
            len(pages),
        )
        page_payload = self._build_page_payload(run=run, pages=pages, source_pages=source_pages)
        input_path = self._runtime_store.write_json_artifact(
            run.taskId,
            "prompt-inputs",
            f"{run.id}.json",
            _build_prompt_input_artifact(page_payload),
        )
        running_run = self._run_with_phase(
            replace(run, inputPath=input_path),
            "model_processing",
        )
        self._repository.save_prompt_run(running_run, refresh_task=False)
        run_state = {"current_run": running_run}

        try:
            output = self._llm_service.run_page_group(
                taskId=run.taskId,
                pageRange=_format_page_range(run.startPageNo, run.endPageNo),
                promptName=run.promptName,
                promptText=run.promptText,
                pagePayload=page_payload,
                progress_callback=lambda partial_output: run_state.__setitem__(
                    "current_run",
                    self._save_partial_run_progress(run_state["current_run"], partial_output),
                ),
            )
            normalized_block_ids = list(output.evidenceBlockIds or [])
            normalized_excerpts = list(output.evidenceExcerpts or [])
            output_payload = {
                "title": output.title,
                "excerpt": output.excerpt,
                "detail": output.detail,
                "structuredExtractionResult": output.structuredExtractionResult,
                "structuredProcessResult": output.structuredProcessResult,
                "structuredBusinessResult": output.structuredBusinessResult,
                "evidenceBlockIds": normalized_block_ids,
                "evidenceExcerpts": normalized_excerpts,
                "provider": output.provider,
                "model": output.model,
            }
            output_path = self._runtime_store.write_json_artifact(
                run.taskId,
                "prompt-outputs",
                f"{run.id}.json",
                output_payload,
            )
            self._persist_llm_logs(run=running_run, output=output, stage="parse")
            _validate_table_extraction_consistency(
                page_payload=page_payload,
                structured_extraction=output.structuredExtractionResult,
            )
            completed_run = self._run_with_phase(
                replace(
                    run_state["current_run"],
                    status="completed",
                    llmProvider=output.provider,
                    llmModel=output.model,
                    outputText=output.detail.strip(),
                    structuredExtractionResult=output.structuredExtractionResult,
                    structuredProcessResult=output.structuredProcessResult,
                    structuredBusinessResult=output.structuredBusinessResult,
                    outputPath=output_path,
                    evidenceBlockIds=normalized_block_ids,
                    evidenceExcerpts=normalized_excerpts,
                    errorMessage=None,
                ),
                "completed",
            )
            logger.info(
                "[PromptPipeline] completed runId=%s taskId=%s pageRange=%s provider=%s model=%s",
                run.id,
                run.taskId,
                _format_page_range(run.startPageNo, run.endPageNo),
                output.provider,
                output.model,
            )
            self._persist_run_artifact(
                run=completed_run,
                stage="parse",
                artifact_kind="parse_result",
                file_name="parse-result.json",
                payload=output_payload,
                page_no=run.startPageNo if run.startPageNo == run.endPageNo else None,
                summary={
                    "status": "completed",
                    "summary": str((output.structuredExtractionResult or {}).get("summary") or output.excerpt or "")[:500]
                    if isinstance(output.structuredExtractionResult, dict)
                    else output.excerpt[:500],
                    "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
                    "version": "parse_result_v1",
                },
            )
            persist_operation_targets = bool((run.schemaDefinition or {}).get("persistOperationTargets", True))
            if persist_operation_targets:
                self._persist_parse_targets_for_run(run=completed_run, pages=pages)
            return self._repository.save_prompt_run(completed_run)
        except Exception as exc:
            error_text = str(exc)
            error_path = self._runtime_store.write_text_artifact(
                run.taskId,
                "prompt-outputs",
                f"{run.id}.error.txt",
                error_text,
            )
            failed_run = self._run_with_phase(
                replace(
                    run_state["current_run"],
                    status="failed",
                    errorMessage=error_text,
                    outputPath=error_path,
                    outputText=None,
                    structuredExtractionResult=None,
                    structuredProcessResult=None,
                    structuredBusinessResult=None,
                    evidenceBlockIds=[],
                    evidenceExcerpts=[],
                ),
                "failed",
            )
            logger.exception(
                "[PromptPipeline] failed runId=%s taskId=%s pageRange=%s error=%s",
                run.id,
                run.taskId,
                _format_page_range(run.startPageNo, run.endPageNo),
                error_text,
            )
            return self._repository.save_prompt_run(failed_run)

    def _execute_single_schema_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> PromptRunRecord:
        source_pages = (
            available_pages
            if available_pages is not None
            else self._repository.get_task_execution_context(run.taskId).pages
        )
        pages = self._select_extraction_scope_pages(source_pages, run=run)
        facts_payload = self._build_schema_facts_payload(pages=pages)
        input_artifact = {
            "taskId": run.taskId,
            "documentId": run.documentId,
            "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
            "templateId": run.templateId,
            "templateName": run.schemaTemplateName,
            "templateVersion": run.schemaTemplateVersion,
            "schemaDefinition": run.schemaDefinition,
            "facts": facts_payload,
        }
        input_path = self._runtime_store.write_json_artifact(
            run.taskId,
            "schema-inputs",
            f"{run.id}.json",
            input_artifact,
        )
        running_run = self._run_with_phase(
            replace(
                run,
                inputPath=input_path,
                inputFactsSnapshot=facts_payload,
            ),
            "model_processing",
        )
        self._repository.save_prompt_run(running_run, refresh_task=False)
        try:
            output = self._llm_service.run_schema_template(
                taskId=run.taskId,
                pageRange=_format_page_range(run.startPageNo, run.endPageNo),
                templateId=run.templateId or "",
                templateName=run.schemaTemplateName or run.promptName,
                templateVersion=run.schemaTemplateVersion,
                schemaDefinition=run.schemaDefinition or {"fields": []},
                instructions=run.promptText,
                factsPayload=facts_payload,
            )
            output_payload = {
                "title": output.title,
                "excerpt": output.excerpt,
                "detail": output.detail,
                "schemaOutput": output.schemaOutput,
                "validationErrors": list(output.validationErrors or []),
                "structuredProcessResult": output.structuredProcessResult,
                "evidenceBlockIds": list(output.evidenceBlockIds or []),
                "evidenceExcerpts": list(output.evidenceExcerpts or []),
                "provider": output.provider,
                "model": output.model,
            }
            output_path = self._runtime_store.write_json_artifact(
                run.taskId,
                "schema-outputs",
                f"{run.id}.json",
                output_payload,
            )
            self._persist_llm_logs(run=running_run, output=output, stage="schema_process")
            completion_status = _completion_status_from_validation_errors(output.validationErrors)
            completed_run = self._run_with_phase(
                replace(
                    running_run,
                    status=completion_status,
                    llmProvider=output.provider,
                    llmModel=output.model,
                    outputText=output.detail.strip(),
                    schemaOutput=output.schemaOutput,
                    validationErrors=list(output.validationErrors or []),
                    structuredProcessResult=output.structuredProcessResult,
                    outputPath=output_path,
                    evidenceBlockIds=list(output.evidenceBlockIds or []),
                    evidenceExcerpts=list(output.evidenceExcerpts or []),
                    errorMessage=None,
                ),
                completion_status,
            )
            self._persist_run_artifact(
                run=completed_run,
                stage="process",
                artifact_kind="process_result",
                file_name="process-result.json",
                payload=output_payload,
                page_no=run.startPageNo if run.startPageNo == run.endPageNo else None,
                summary={
                    "status": completion_status,
                    "summary": output.excerpt[:500] or output.detail[:500],
                    "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
                    "version": "process_result_v1",
                },
            )
            return self._repository.save_prompt_run(completed_run)
        except Exception as exc:
            error_text = str(exc)
            error_path = self._runtime_store.write_text_artifact(
                run.taskId,
                "schema-outputs",
                f"{run.id}.error.txt",
                error_text,
            )
            failed_run = self._run_with_phase(
                replace(
                    running_run,
                    status="failed",
                    errorMessage=error_text,
                    outputPath=error_path,
                    outputText=None,
                    schemaOutput=None,
                    validationErrors=[],
                    structuredProcessResult=None,
                    evidenceBlockIds=[],
                    evidenceExcerpts=[],
                ),
                "failed",
            )
            logger.exception(
                "[PromptPipeline] failed schema runId=%s taskId=%s pageRange=%s error=%s",
                run.id,
                run.taskId,
                _format_page_range(run.startPageNo, run.endPageNo),
                error_text,
            )
            return self._repository.save_prompt_run(failed_run)

    def _start_background_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> None:
        worker = threading.Thread(
            target=self._execute_single_run,
            args=(run,),
            kwargs={"available_pages": list(available_pages) if available_pages is not None else None},
            name=f"prompt-run-{run.id}",
            daemon=True,
        )
        worker.start()

    def _start_background_schema_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> None:
        worker = threading.Thread(
            target=self._execute_single_schema_run,
            args=(run,),
            kwargs={"available_pages": list(available_pages) if available_pages is not None else None},
            name=f"schema-run-{run.id}",
            daemon=True,
        )
        worker.start()

    def _start_background_post_process_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> None:
        worker = threading.Thread(
            target=self._execute_single_post_process_run,
            args=(run,),
            kwargs={"available_pages": list(available_pages) if available_pages is not None else None},
            name=f"post-process-run-{run.id}",
            daemon=True,
        )
        worker.start()

    def _start_background_extraction_skill_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> None:
        worker = threading.Thread(
            target=self.execute_extraction_prompt_run,
            args=(run,),
            kwargs={"available_pages": list(available_pages) if available_pages is not None else None},
            name=f"extraction-skill-run-{run.id}",
            daemon=True,
        )
        worker.start()

    @staticmethod
    def _merge_prompt_context_pages(
        *,
        base_pages: list[WorkbenchPageDetail],
        page_context: PromptExecutionPageContext | None,
    ) -> list[WorkbenchPageDetail]:
        if not page_context or not page_context.pages:
            return base_pages

        base_by_page_no = {page.pageNo: page for page in base_pages}
        override_by_page_no = {page.pageNo: page for page in page_context.pages}
        merged_pages: list[WorkbenchPageDetail] = []
        seen_page_nos: set[int] = set()

        for base_page in base_pages:
            override_page = override_by_page_no.get(base_page.pageNo)
            if not override_page:
                merged_pages.append(base_page)
                continue
            merged_pages.append(
                PromptPipelineService._build_page_detail_from_context(
                    page_context=override_page,
                    base_page=base_page,
                )
            )
            seen_page_nos.add(base_page.pageNo)

        for override_page in page_context.pages:
            if override_page.pageNo in seen_page_nos or override_page.pageNo in base_by_page_no:
                continue
            merged_pages.append(
                PromptPipelineService._build_page_detail_from_context(
                    page_context=override_page,
                    base_page=None,
                )
            )

        return sorted(merged_pages, key=lambda item: (item.pageNo, item.pageIndex))

    @staticmethod
    def _build_page_detail_from_context(
        *,
        page_context: PromptExecutionPageContextPage,
        base_page: WorkbenchPageDetail | None,
    ) -> WorkbenchPageDetail:
        page_size = tuple(page_context.pageSize) if page_context.pageSize else ((0.0, 0.0) if not base_page else base_page.pageSize)
        return WorkbenchPageDetail(
            pageIndex=page_context.pageIndex if page_context.pageIndex is not None else (base_page.pageIndex if base_page else max(page_context.pageNo - 1, 0)),
            pageNo=page_context.pageNo,
            prompt=base_page.prompt if base_page else "",
            promptStatus=base_page.promptStatus if base_page else "draft",
            promptName=base_page.promptName if base_page else None,
            promptStartPageNo=base_page.promptStartPageNo if base_page else None,
            promptEndPageNo=base_page.promptEndPageNo if base_page else None,
            promptTemplateId=base_page.promptTemplateId if base_page else None,
            markdownSegments=page_context.markdownSegments or (base_page.markdownSegments if base_page else []),
            blocks=page_context.blocks or (base_page.blocks if base_page else []),
            rawItems=page_context.rawItems or (base_page.rawItems if base_page else []),
            pageSize=page_size,
        )

    @staticmethod
    def _select_run_pages(
        available_pages: list[WorkbenchPageDetail],
        *,
        run: PromptRunRecord,
    ) -> list[WorkbenchPageDetail]:
        return [
            page
            for page in available_pages
            if run.startPageNo <= page.pageNo <= run.endPageNo
        ]

    @staticmethod
    def _select_extraction_scope_pages(
        available_pages: list[WorkbenchPageDetail],
        *,
        run: PromptRunRecord,
    ) -> list[WorkbenchPageDetail]:
        pages = PromptPipelineService._select_run_pages(available_pages, run=run)
        scope = _application_extraction_scope(run.schemaDefinition)
        content_refs = scope.get("contentRefs") if isinstance(scope.get("contentRefs"), list) else []
        if not content_refs:
            return pages

        ref_pages = _content_ref_pages(content_refs)
        if ref_pages:
            scoped_pages = [page for page in available_pages if page.pageNo in ref_pages]
            if scoped_pages:
                pages = scoped_pages

        block_ids = _content_ref_block_ids(content_refs)
        if not block_ids:
            return pages

        runtime_block_ids = {
            str(getattr(block, "id", "") or "")
            for page in pages
            for block in (getattr(page, "blocks", []) or [])
            if str(getattr(block, "id", "") or "").strip()
        }
        matched_block_ids = block_ids & runtime_block_ids
        if not matched_block_ids:
            # Document-tree module references often use parser-side ids that do
            # not equal runtime OCR block ids. In that case the locator already
            # supplied evidence pages, so the page scope is the executable scope.
            if _content_refs_include_document_tree_modules(content_refs):
                return pages
            return pages

        filtered_pages: list[WorkbenchPageDetail] = []
        for page in pages:
            blocks = [
                block
                for block in (getattr(page, "blocks", []) or [])
                if str(getattr(block, "id", "") or "") in matched_block_ids
            ]
            if not blocks:
                continue
            if hasattr(page, "model_copy"):
                filtered_pages.append(page.model_copy(update={"blocks": blocks}))
            else:
                filtered_pages.append(replace(page, blocks=blocks))
        return filtered_pages or pages

    @staticmethod
    def _build_page_payload(
        *,
        run: PromptRunRecord,
        pages: list[WorkbenchPageDetail],
        source_pages: list[WorkbenchPageDetail] | None = None,
    ) -> dict[str, Any]:
        table_header_contexts = _build_table_header_contexts(
            pages=source_pages or pages,
            prompt_text=run.promptText,
        )
        return {
            "taskId": run.taskId,
            "documentId": run.documentId,
            "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
            "promptName": run.promptName,
            "promptText": run.promptText,
            "tableTaskMode": str((run.schemaDefinition or {}).get("tableTaskMode") or "parse_json"),
            "pages": [
                {
                    "pageNo": page.pageNo,
                    "title": _derive_prompt_page_title(page),
                    "summary": _derive_prompt_page_summary(page),
                    "markdownSegments": [
                        segment.model_dump() if hasattr(segment, "model_dump") else segment
                        for segment in page.markdownSegments
                    ],
                    "blocks": [
                        {
                            "id": block.id,
                            "type": block.type,
                            "title": block.title,
                            "content": block.content,
                            "tableHeaderContext": table_header_contexts.get((page.pageNo, block.id)),
                        }
                        for block in page.blocks
                    ],
                }
                for page in pages
            ],
        }

    @staticmethod
    def _build_runtime_schema_definition(schema_definition: dict[str, Any] | None) -> dict[str, Any]:
        if not schema_definition:
            return {"fields": []}
        if isinstance(schema_definition, dict):
            if isinstance(schema_definition.get("fields"), list):
                return schema_definition
            return {"fields": list(schema_definition.get("children") or [])}
        return {"fields": []}

    @staticmethod
    def _build_schema_facts_payload(*, pages: list[WorkbenchPageDetail]) -> dict[str, Any]:
        return {
            "pages": [
                {
                    "pageNo": page.pageNo,
                    "pageIndex": page.pageIndex,
                    "pageSize": list(page.pageSize),
                    "blocks": [
                        {
                            "id": block.id,
                            "pageNo": block.pageNo,
                            "blockPosition": block.blockPosition,
                            "type": block.type,
                            "title": block.title,
                            "content": block.content,
                        }
                        for block in page.blocks
                    ],
                    "markdownSegments": [
                        segment.model_dump() if hasattr(segment, "model_dump") else segment
                        for segment in page.markdownSegments
                    ],
                    "rawItems": list(page.rawItems or []),
                }
                for page in pages
            ]
        }

    def _build_post_process_facts_payload(
        self,
        *,
        task_id: str,
        pages: list[WorkbenchPageDetail],
    ) -> dict[str, Any]:
        latest_extraction_runs: dict[int, PromptRunRecord] = {}
        candidate_runs = sorted(
            self._repository.list_prompt_runs(task_id),
            key=lambda item: item.updatedAt,
        )
        for candidate_run in candidate_runs:
            if candidate_run.runPurpose != "parse_prompt" or candidate_run.status not in {"completed", "needs_review"}:
                continue
            if not isinstance(candidate_run.structuredExtractionResult, dict):
                continue
            for page_no in range(candidate_run.startPageNo, candidate_run.endPageNo + 1):
                latest_extraction_runs[page_no] = candidate_run

        return {
            "pages": [
                {
                    "pageNo": page.pageNo,
                    "pageIndex": page.pageIndex,
                    "pageSize": list(page.pageSize),
                    "blocks": [
                        {
                            "id": block.id,
                            "pageNo": block.pageNo,
                            "blockPosition": block.blockPosition,
                            "type": block.type,
                            "title": block.title,
                            "content": block.content,
                        }
                        for block in page.blocks
                    ],
                    "markdownSegments": [
                        segment.model_dump() if hasattr(segment, "model_dump") else segment
                        for segment in page.markdownSegments
                    ],
                    "rawItems": list(page.rawItems or []),
                    "latestExtractionResult": build_extraction_result_payload(
                        pages=[page],
                        parse_run=latest_extraction_runs.get(page.pageNo),
                    ),
                }
                for page in pages
            ]
        }

    def _build_object_operation_facts_payload(
        self,
        *,
        task_id: str,
        page: WorkbenchPageDetail,
        target: OperationTargetRef,
        related_targets: list[OperationTargetRef],
    ) -> dict[str, Any]:
        page_facts = self._build_post_process_facts_payload(task_id=task_id, pages=[page]).get("pages") or []
        latest_extraction = page_facts[0].get("latestExtractionResult") if page_facts else None
        block_lookup = {block.id: block for block in page.blocks}

        def build_target_snapshot(item: OperationTargetRef) -> dict[str, Any]:
            matched_blocks = [] if item.data is not None else _build_compact_matched_blocks(
                item=item,
                block_lookup=block_lookup,
            )
            snapshot: dict[str, Any] = {
                **item.model_dump(),
                "matchedBlocks": matched_blocks,
            }
            if item.type == "table" and isinstance(latest_extraction, dict):
                tables = latest_extraction.get("tables")
                table_index = _extract_table_target_index(item.id)
                if isinstance(tables, list) and 0 <= table_index < len(tables):
                    table_payload = tables[table_index]
                    if isinstance(table_payload, dict):
                        snapshot["parsedTable"] = {
                            "headers": list(table_payload.get("headers") or []),
                            "rows": [list(row) for row in (table_payload.get("rows") or []) if isinstance(row, list)],
                        }
            if item.type == "structured_object" and isinstance(latest_extraction, dict):
                structured_objects = latest_extraction.get("structuredObjects")
                object_index = _extract_structured_object_target_index(item.id)
                if isinstance(structured_objects, list) and 0 <= object_index < len(structured_objects):
                    object_payload = structured_objects[object_index]
                    if isinstance(object_payload, dict):
                        snapshot["structuredObject"] = {
                            "id": object_payload.get("id"),
                            "title": object_payload.get("title"),
                            "type": object_payload.get("type"),
                            "kv": dict(object_payload.get("kv") or {}),
                            "table": [
                                dict(row)
                                for row in (object_payload.get("table") or [])
                                if isinstance(row, dict)
                            ],
                            "parserMeta": dict(object_payload.get("parserMeta") or {}),
                        }
            return snapshot

        return {
            "page": {
                "pageNo": page.pageNo,
                "pageIndex": page.pageIndex,
                "pageSize": list(page.pageSize),
            },
            "target": build_target_snapshot(target),
            "relatedTargets": [build_target_snapshot(item) for item in related_targets],
            "latestExtractionResult": _build_compact_extraction_overview(latest_extraction),
        }

    def _read_table_record_mapping_cache(
        self,
        *,
        task_id: str,
        cache_key: str,
        required_fields: list[str],
        table_blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            path = self._runtime_store.resolve_artifact_path(
                task_id,
                f"table-record-mapping-cache/{cache_key}.json",
            )
            if not path.exists():
                return {}
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {}
            return _validate_cached_table_record_mapping(
                cached_payload=payload,
                required_fields=required_fields,
                table_blocks=table_blocks,
            )
        except Exception as exc:
            logger.info(
                "[PromptPipeline] table mapping cache read skipped taskId=%s cacheKey=%s error=%s",
                task_id,
                cache_key,
                exc,
            )
            return {}

    def _write_table_record_mapping_cache(
        self,
        *,
        task_id: str,
        cache_key: str,
        mapping: dict[str, Any],
        required_fields: list[str],
        table_blocks: list[dict[str, Any]],
    ) -> None:
        try:
            self._runtime_store.write_json_artifact(
                task_id,
                "table-record-mapping-cache",
                f"{cache_key}.json",
                _table_record_mapping_cache_payload(
                    cache_key=cache_key,
                    mapping=mapping,
                    required_fields=required_fields,
                    table_blocks=table_blocks,
                ),
            )
        except Exception as exc:
            logger.info(
                "[PromptPipeline] table mapping cache write skipped taskId=%s cacheKey=%s error=%s",
                task_id,
                cache_key,
                exc,
            )

    def _try_execute_table_record_fast_path(
        self,
        *,
        run: PromptRunRecord,
        skill_meta: dict[str, Any],
        config: dict[str, Any],
        facts_payload: dict[str, Any],
        model_facts_payload: dict[str, Any] | None = None,
    ) -> PromptRunOutput | None:
        output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
        if str(output_schema.get("type") or "").strip() != "record_collection":
            return None
        scope = _application_extraction_scope(run.schemaDefinition)
        if not scope.get("contentRefs"):
            return None

        full_table_blocks = _collect_fact_table_blocks(facts_payload)
        preview_source_blocks = _collect_fact_table_blocks(model_facts_payload) if model_facts_payload else full_table_blocks
        table_blocks = _filter_fact_table_blocks_by_preview(
            full_table_blocks=full_table_blocks,
            preview_table_blocks=preview_source_blocks,
        )
        total_rows = sum(len(block["rows"]) for block in table_blocks)
        if not table_blocks or total_rows < 24:
            return None
        if not _table_blocks_are_regular_record_like(table_blocks):
            return None

        required_fields = [
            str(item).strip()
            for item in (output_schema.get("required") or [])
            if str(item).strip()
        ] if isinstance(output_schema.get("required"), list) else []
        cache_key = _table_record_mapping_cache_key(
            skill_meta=skill_meta,
            required_fields=required_fields,
            table_blocks=table_blocks,
        )
        cached_mapping = self._read_table_record_mapping_cache(
            task_id=run.taskId,
            cache_key=cache_key,
            required_fields=required_fields,
            table_blocks=table_blocks,
        )
        if cached_mapping:
            local_started = time.perf_counter()
            records = _build_records_from_table_mapping(
                table_blocks=table_blocks,
                mapping=cached_mapping,
                required_fields=required_fields,
            )
            local_ms = int((time.perf_counter() - local_started) * 1000)
            if records:
                raw_payload = {
                    "summary": f"已基于缓存列映射解析 {len(records)} 条记录。",
                    "records": records,
                    "validationErrors": [],
                }
                return PromptRunOutput(
                    title=str(skill_meta.get("name") or "结构化解析"),
                    excerpt="",
                    detail=json.dumps(raw_payload, ensure_ascii=False),
                    structuredExtractionResult=raw_payload,
                    structuredProcessResult=None,
                    structuredBusinessResult=None,
                    evidenceBlockIds=[],
                    evidenceExcerpts=[],
                    rawContent=json.dumps(raw_payload, ensure_ascii=False),
                    provider="local",
                    model="cached-table-record-fast-path",
                    llmLogs={
                        "mode": "table_record_fast_path",
                        "cache": {
                            "hit": True,
                            "cacheKey": cache_key,
                        },
                        "mapping": cached_mapping,
                        "tableCount": len(table_blocks),
                        "inputRowCount": total_rows,
                        "outputRecordCount": len(records),
                        "metrics": {
                            "fastPathPreviewMs": 0,
                            "localStructuredBuildMs": local_ms,
                            "previewFactsBytes": 0,
                            "previewOutputRecordCount": 0,
                            "mappingCacheHit": True,
                        },
                    },
                )
        preview_facts = _build_table_record_preview_facts(model_facts_payload or facts_payload)
        preview_skill = _table_record_mapping_preview_skill(skill_meta, required_fields)
        preview_started = time.perf_counter()
        try:
            preview_output = self._llm_service.run_extraction_skill(
                taskId=run.taskId,
                pageRange=_format_page_range(run.startPageNo, run.endPageNo),
                skill=preview_skill,
                config={
                    **config,
                    "runtimeHint": (
                        "长表格快路径预览阶段：只返回 columnMapping，不要返回 records，"
                        "不要补全未出现的全量行。"
                    ),
                },
                factsPayload=preview_facts,
            )
        except Exception as exc:
            logger.info(
                "[PromptPipeline] table fast path preview failed runId=%s taskId=%s error=%s",
                run.id,
                run.taskId,
                exc,
            )
            return None
        preview_ms = int((time.perf_counter() - preview_started) * 1000)

        preview_payload = preview_output.structuredExtractionResult
        if not isinstance(preview_payload, dict):
            return None
        local_started = time.perf_counter()
        mapping = _infer_table_record_column_mapping_from_llm_mapping(
            table_blocks=table_blocks,
            mapping_payload=preview_payload,
            required_fields=required_fields,
        )
        preview_records = [
            record
            for record in (preview_payload.get("records") if isinstance(preview_payload.get("records"), list) else [])
            if isinstance(record, dict)
        ]
        if not mapping and preview_records:
            mapping = _infer_table_record_column_mapping(
                table_blocks=table_blocks,
                preview_records=preview_records[:12],
                required_fields=required_fields,
            )
        if not mapping:
            return None

        self._write_table_record_mapping_cache(
            task_id=run.taskId,
            cache_key=cache_key,
            mapping=mapping,
            required_fields=required_fields,
            table_blocks=table_blocks,
        )
        records = _build_records_from_table_mapping(
            table_blocks=table_blocks,
            mapping=mapping,
            required_fields=required_fields,
        )
        if not records:
            return None
        local_ms = int((time.perf_counter() - local_started) * 1000)

        raw_payload = {
            "summary": f"已基于定位表格解析 {len(records)} 条记录。",
            "records": records,
            "validationErrors": [],
        }
        return PromptRunOutput(
            title=str(skill_meta.get("name") or "结构化解析"),
            excerpt="",
            detail=json.dumps(raw_payload, ensure_ascii=False),
            structuredExtractionResult=raw_payload,
            structuredProcessResult=None,
            structuredBusinessResult=None,
            evidenceBlockIds=[],
            evidenceExcerpts=[],
            rawContent=json.dumps(raw_payload, ensure_ascii=False),
            provider=preview_output.provider or "local",
            model=f"{preview_output.model or 'llm'}+table-record-fast-path",
            llmLogs={
                "mode": "table_record_fast_path",
                "provider": preview_output.provider,
                "model": preview_output.model,
                "preview": {
                    "rawPayload": preview_payload,
                    "logs": preview_output.llmLogs,
                },
                "mapping": mapping,
                "tableCount": len(table_blocks),
                "inputRowCount": total_rows,
                "outputRecordCount": len(records),
                "metrics": {
                    "fastPathPreviewMs": preview_ms,
                    "localStructuredBuildMs": local_ms,
                    "previewFactsBytes": _estimate_json_payload_bytes(preview_facts),
                    "previewOutputRecordCount": len(preview_records),
                },
            },
        )

    def _review_field_list_extraction_if_needed(
        self,
        *,
        run: PromptRunRecord,
        skill_meta: dict[str, Any],
        config: dict[str, Any],
        facts_payload: dict[str, Any],
        evidence_selection: dict[str, Any],
        application_scope: dict[str, Any],
        runtime_contract: dict[str, Any],
        raw_payload: dict[str, Any],
        output: PromptRunOutput,
        fallback_facts_payload: dict[str, Any] | None = None,
        fallback_evidence_selection: dict[str, Any] | None = None,
    ) -> tuple[PromptRunOutput, dict[str, Any], dict[str, Any]] | None:
        output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
        if str(output_schema.get("type") or "").strip() != "field_list":
            return None
        if not runtime_contract:
            return None
        tentative_meta = _build_extraction_run_meta(
            skill_meta=skill_meta,
            config=config,
            output=output,
            duration_ms=0,
            input_payload={
                "skill": _skill_payload_for_llm(skill_meta),
                "config": config,
                "applicationScope": application_scope,
                "runtimeContract": runtime_contract,
                "facts": facts_payload,
            },
            raw_payload=raw_payload,
        )
        try:
            extraction_result = _normalize_extraction_skill_output(
                raw_payload=raw_payload,
                skill_meta=skill_meta,
                run_meta=tentative_meta,
            )
            extraction_result = _enrich_field_list_extraction_result_from_application_scope(
                extraction_result,
                schema_definition=run.schemaDefinition,
            )
        except Exception as exc:
            logger.warning(
                "[PromptPipeline] skip extraction review after normalization error runId=%s: %s",
                run.id,
                exc,
            )
            return None
        if not _field_list_extraction_needs_llm_review(extraction_result, schema_definition=run.schemaDefinition):
            return None
        reviewer = getattr(self._llm_service, "review_extraction_skill_output", None)
        if not callable(reviewer):
            return None
        review_facts_payload = facts_payload
        review_evidence_selection = evidence_selection
        if (
            fallback_facts_payload is not None
            and not _field_list_extraction_has_any_target_value(
                extraction_result,
                schema_definition=run.schemaDefinition,
            )
        ):
            review_facts_payload = fallback_facts_payload
            review_evidence_selection = fallback_evidence_selection or {}
        try:
            review_output = reviewer(
                taskId=run.taskId,
                pageRange=_format_page_range(run.startPageNo, run.endPageNo),
                skill=_skill_payload_for_llm(skill_meta),
                config=config,
                factsPayload=review_facts_payload,
                applicationScope=application_scope,
                runtimeContract=runtime_contract,
                rawExtractionResult=raw_payload,
                normalizedExtractionResult=extraction_result,
            )
            return review_output, review_facts_payload, review_evidence_selection
        except Exception as exc:
            logger.warning(
                "[PromptPipeline] extraction review failed runId=%s taskId=%s: %s",
                run.id,
                run.taskId,
                exc,
            )
            return None

    def _execute_single_extraction_skill_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> PromptRunRecord:
        source_pages = (
            available_pages
            if available_pages is not None
            else self._repository.get_task_execution_context(run.taskId).pages
        )
        pages = self._select_extraction_scope_pages(source_pages, run=run)
        ports = self._build_extraction_runtime_ports()
        runtime_request = build_prompt_run_runtime_request(run=run, pages=pages)
        started = time.perf_counter()
        prepared = self._extraction_runtime_kernel.prepare(runtime_request, ports=ports)
        if prepared.evidence_v2_enabled:
            evidence_v2_artifact_path = self._runtime_store.write_json_artifact(
                run.taskId,
                "extraction-skill-evidence-v2",
                f"{run.id}.json",
                prepared.evidence_v2_package,
            )
            prepared.set_evidence_v2_artifact_path(evidence_v2_artifact_path)
        input_path = self._runtime_store.write_json_artifact(
            run.taskId,
            "extraction-skill-inputs",
            f"{run.id}.json",
            prepared.input_payload,
        )
        self._runtime_store.write_json_artifact(
            run.taskId,
            "extraction-skill-evidence",
            f"{run.id}.json",
            prepared.evidence_index,
        )
        running_run = self._run_with_phase(
            replace(
                run,
                inputPath=input_path,
                inputFactsSnapshot=prepared.facts_payload,
            ),
            "model_processing",
        )
        self._repository.save_prompt_run(running_run, refresh_task=False)

        try:
            runtime_result = self._extraction_runtime_kernel.execute(
                runtime_request,
                prepared,
                ports=ports,
                started_at=started,
            )
            output_path = self._runtime_store.write_json_artifact(
                run.taskId,
                "extraction-skill-outputs",
                f"{run.id}.json",
                runtime_result.output_artifact_payload,
            )
            self._persist_llm_logs(
                run=running_run,
                output=runtime_result.output,
                stage="parse",
                skill_id=str(prepared.skill_meta.get("id") or "") or None,
            )
            completion_status = runtime_result.completion_status
            completed_run = self._run_with_phase(
                replace(
                    running_run,
                    status=completion_status,
                    llmProvider=runtime_result.output.provider,
                    llmModel=runtime_result.output.model,
                    outputText=str(runtime_result.extraction_result.get("summary") or "").strip(),
                    structuredExtractionResult=runtime_result.extraction_result,
                    validationErrors=runtime_result.errors,
                    outputPath=output_path,
                    evidenceBlockIds=[],
                    evidenceExcerpts=[],
                    errorMessage=None,
                ),
                completion_status,
            )
            logger.info(
                (
                    "[PromptPipeline] completed extraction skill runId=%s taskId=%s skill=%s "
                    "durationMs=%s inputPayloadBytes=%s factsBytes=%s fullFactsBytes=%s evidenceIndexBytes=%s "
                    "tableCount=%s tableRowCount=%s fullTableRowCount=%s maxTableRows=%s "
                    "reviewCount=%s reviewFactsBytes=%s tableFastPath=%s"
                ),
                run.id,
                run.taskId,
                prepared.skill_meta.get("id"),
                runtime_result.duration_ms,
                runtime_result.metrics.get("inputPayloadBytes"),
                runtime_result.metrics.get("factsBytes"),
                runtime_result.metrics.get("fullFactsBytes"),
                runtime_result.metrics.get("evidenceIndexBytes"),
                runtime_result.metrics.get("tableCount"),
                runtime_result.metrics.get("tableRowCount"),
                runtime_result.metrics.get("fullTableRowCount"),
                runtime_result.metrics.get("maxTableRows"),
                runtime_result.metrics.get("reviewCount"),
                runtime_result.metrics.get("reviewFactsBytes"),
                runtime_result.metrics.get("tableFastPath"),
            )
            persist_run_artifact = bool((run.schemaDefinition or {}).get("persistRunArtifact", True))
            if persist_run_artifact:
                self._persist_run_artifact(
                    run=completed_run,
                    stage="parse",
                    artifact_kind="parse_result",
                    file_name="parse-result.json",
                    payload=runtime_result.output_artifact_payload,
                    page_no=run.startPageNo if run.startPageNo == run.endPageNo else None,
                    summary={
                        "status": completion_status,
                        "summary": str(runtime_result.extraction_result.get("summary") or "")[:500],
                        "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
                        "version": "parse_result_v1",
                    },
                )
            persist_operation_targets = bool((run.schemaDefinition or {}).get("persistOperationTargets", True))
            if persist_operation_targets:
                self._persist_parse_targets_for_run(run=completed_run, pages=pages)
            return self._repository.save_prompt_run(completed_run)
        except Exception as exc:
            error_text = str(exc)
            error_path = self._runtime_store.write_text_artifact(
                run.taskId,
                "extraction-skill-outputs",
                f"{run.id}.error.txt",
                error_text,
            )
            failed_run = self._run_with_phase(
                replace(
                    running_run,
                    status="failed",
                    errorMessage=error_text,
                    outputPath=error_path,
                    outputText=None,
                    structuredExtractionResult=None,
                    validationErrors=[error_text],
                    evidenceBlockIds=[],
                    evidenceExcerpts=[],
                ),
                "failed",
            )
            logger.exception(
                "[PromptPipeline] failed extraction skill runId=%s taskId=%s pageRange=%s error=%s",
                run.id,
                run.taskId,
                _format_page_range(run.startPageNo, run.endPageNo),
                error_text,
            )
            return self._repository.save_prompt_run(failed_run)

    def _execute_single_post_process_run(
        self,
        run: PromptRunRecord,
        *,
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> PromptRunRecord:
        source_pages = (
            available_pages
            if available_pages is not None
            else self._repository.get_task_execution_context(run.taskId).pages
        )
        pages = self._select_run_pages(source_pages, run=run)
        facts_payload = self._build_post_process_facts_payload(task_id=run.taskId, pages=pages)
        response_mode = str((run.schemaDefinition or {}).get("responseMode") or "auto")
        input_artifact = {
            "taskId": run.taskId,
            "documentId": run.documentId,
            "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
            "instruction": run.promptText,
            "responseMode": response_mode,
            "facts": facts_payload,
        }
        input_path = self._runtime_store.write_json_artifact(
            run.taskId,
            "post-process-inputs",
            f"{run.id}.json",
            input_artifact,
        )
        running_run = self._run_with_phase(
            replace(
                run,
                inputPath=input_path,
                inputFactsSnapshot=facts_payload,
            ),
            "model_processing",
        )
        self._repository.save_prompt_run(running_run, refresh_task=False)
        try:
            output = self._llm_service.run_post_process(
                taskId=run.taskId,
                pageRange=_format_page_range(run.startPageNo, run.endPageNo),
                instruction=run.promptText,
                responseMode=response_mode,
                factsPayload=facts_payload,
            )
            output_payload = {
                "title": output.title,
                "excerpt": output.excerpt,
                "detail": output.detail,
                "structuredProcessResult": output.structuredProcessResult,
                "validationErrors": list(output.validationErrors or []),
                "evidenceBlockIds": list(output.evidenceBlockIds or []),
                "evidenceExcerpts": list(output.evidenceExcerpts or []),
                "provider": output.provider,
                "model": output.model,
            }
            output_path = self._runtime_store.write_json_artifact(
                run.taskId,
                "post-process-outputs",
                f"{run.id}.json",
                output_payload,
            )
            self._persist_llm_logs(run=running_run, output=output, stage="process")
            completion_status = _completion_status_from_validation_errors(output.validationErrors)
            completed_run = self._run_with_phase(
                replace(
                    running_run,
                    status=completion_status,
                    llmProvider=output.provider,
                    llmModel=output.model,
                    outputText=output.detail.strip(),
                    structuredProcessResult=output.structuredProcessResult,
                    validationErrors=list(output.validationErrors or []),
                    outputPath=output_path,
                    evidenceBlockIds=list(output.evidenceBlockIds or []),
                    evidenceExcerpts=list(output.evidenceExcerpts or []),
                    errorMessage=None,
                ),
                completion_status,
            )
            self._persist_run_artifact(
                run=completed_run,
                stage="process",
                artifact_kind="process_result",
                file_name="process-result.json",
                payload=output_payload,
                page_no=run.startPageNo if run.startPageNo == run.endPageNo else None,
                summary={
                    "status": completion_status,
                    "summary": output.excerpt[:500] or output.detail[:500],
                    "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
                    "version": "process_result_v1",
                },
            )
            return self._repository.save_prompt_run(completed_run)
        except Exception as exc:
            error_text = str(exc)
            error_path = self._runtime_store.write_text_artifact(
                run.taskId,
                "post-process-outputs",
                f"{run.id}.error.txt",
                error_text,
            )
            failed_run = self._run_with_phase(
                replace(
                    running_run,
                    status="failed",
                    errorMessage=error_text,
                    outputPath=error_path,
                    outputText=None,
                    structuredProcessResult=None,
                    validationErrors=[],
                    evidenceBlockIds=[],
                    evidenceExcerpts=[],
                ),
                "failed",
            )
            logger.exception(
                "[PromptPipeline] failed post-process runId=%s taskId=%s pageRange=%s error=%s",
                run.id,
                run.taskId,
                _format_page_range(run.startPageNo, run.endPageNo),
                error_text,
            )
            return self._repository.save_prompt_run(failed_run)

    def _execute_single_object_operation_run(
        self,
        run: PromptRunRecord,
        *,
        target: OperationTargetRef,
        related_targets: list[OperationTargetRef],
        available_pages: list[WorkbenchPageDetail] | None = None,
    ) -> PromptRunRecord:
        source_pages = (
            available_pages
            if available_pages is not None
            else self._repository.get_task_execution_context(run.taskId).pages
        )
        page = next((item for item in source_pages if item.pageNo == run.startPageNo), None)
        if page is None:
            raise RuntimeError("对象所在页不存在。")

        operation_meta = run.schemaDefinition or {}
        operation_type = str(operation_meta.get("operationType") or "review")
        result_mode = str(operation_meta.get("resultMode") or "auto")
        skill_meta = operation_meta.get("skill") if isinstance(operation_meta.get("skill"), dict) else None
        application_meta = operation_meta.get("application") if isinstance(operation_meta.get("application"), dict) else None
        facts_payload = self._build_object_operation_facts_payload(
            task_id=run.taskId,
            page=page,
            target=target,
            related_targets=related_targets,
        )
        input_artifact = {
            "taskId": run.taskId,
            "documentId": run.documentId,
            "pageNo": run.startPageNo,
            "instruction": run.promptText,
            "operationType": operation_type,
            "resultMode": result_mode,
            "target": target.model_dump(),
            "relatedTargets": [item.model_dump() for item in related_targets],
            "skill": skill_meta,
            "facts": facts_payload,
        }
        input_path = self._runtime_store.write_json_artifact(
            run.taskId,
            "object-operation-inputs",
            f"{run.id}.json",
            input_artifact,
        )
        running_run = self._run_with_phase(
            replace(
                run,
                inputPath=input_path,
                inputFactsSnapshot=facts_payload,
            ),
            "model_processing",
        )
        self._repository.save_prompt_run(running_run, refresh_task=False)
        try:
            output = (
                _try_run_skill_object_operation(
                    page_no=run.startPageNo,
                    operation_type=operation_type,
                    result_mode=result_mode,
                    target=target.model_dump(),
                    related_targets=[item.model_dump() for item in related_targets],
                    facts_payload=facts_payload,
                    skill_meta=skill_meta,
                )
                if skill_meta
                else None
            )
            if output is None:
                output = _try_run_local_object_operation(
                    page_no=run.startPageNo,
                    operation_type=operation_type,
                    instruction=run.promptText,
                    result_mode=result_mode,
                    target=target.model_dump(),
                    related_targets=[item.model_dump() for item in related_targets],
                    facts_payload=facts_payload,
                )
            if output is None:
                output = self._llm_service.run_object_operation(
                    taskId=run.taskId,
                    pageNo=run.startPageNo,
                    operationType=operation_type,
                    instruction=run.promptText,
                    resultMode=result_mode,
                    target=target.model_dump(),
                    relatedTargets=[item.model_dump() for item in related_targets],
                    factsPayload=facts_payload,
                )
            if skill_meta:
                output = _attach_skill_metadata_to_output(
                    output,
                    skill_meta,
                    application_meta=application_meta,
                )
            output_payload = {
                "title": output.title,
                "excerpt": output.excerpt,
                "detail": output.detail,
                "structuredProcessResult": output.structuredProcessResult,
                "validationErrors": list(output.validationErrors or []),
                "evidenceBlockIds": list(output.evidenceBlockIds or []),
                "evidenceExcerpts": list(output.evidenceExcerpts or []),
                "provider": output.provider,
                "model": output.model,
            }
            output_path = self._runtime_store.write_json_artifact(
                run.taskId,
                "object-operation-outputs",
                f"{run.id}.json",
                output_payload,
            )
            self._persist_llm_logs(
                run=running_run,
                output=output,
                stage="process",
                skill_id=str(skill_meta.get("id") or "") if skill_meta else None,
            )
            completion_status = _completion_status_from_validation_errors(output.validationErrors)
            completed_run = self._run_with_phase(
                replace(
                    running_run,
                    status=completion_status,
                    llmProvider=output.provider,
                    llmModel=output.model,
                    outputText=output.detail.strip(),
                    structuredProcessResult=output.structuredProcessResult,
                    validationErrors=list(output.validationErrors or []),
                    outputPath=output_path,
                    evidenceBlockIds=list(output.evidenceBlockIds or []),
                    evidenceExcerpts=list(output.evidenceExcerpts or []),
                    errorMessage=None,
                ),
                completion_status,
            )
            self._persist_run_artifact(
                run=completed_run,
                stage="process",
                artifact_kind="process_result",
                file_name="process-result.json",
                payload=output_payload,
                page_no=run.startPageNo if run.startPageNo == run.endPageNo else None,
                summary={
                    "status": completion_status,
                    "summary": output.excerpt[:500] or output.detail[:500],
                    "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
                    "version": "process_result_v1",
                },
            )
            return self._repository.save_prompt_run(completed_run)
        except Exception as exc:
            error_text = str(exc)
            error_path = self._runtime_store.write_text_artifact(
                run.taskId,
                "object-operation-outputs",
                f"{run.id}.error.txt",
                error_text,
            )
            failed_run = self._run_with_phase(
                replace(
                    running_run,
                    status="failed",
                    errorMessage=error_text,
                    outputPath=error_path,
                    outputText=None,
                    structuredProcessResult=None,
                    validationErrors=[],
                    evidenceBlockIds=[],
                    evidenceExcerpts=[],
                ),
                "failed",
            )
            logger.exception(
                "[PromptPipeline] failed object operation runId=%s taskId=%s pageNo=%s error=%s",
                run.id,
                run.taskId,
                run.startPageNo,
                error_text,
            )
            return self._repository.save_prompt_run(failed_run)

    def _save_partial_run_progress(self, current_run: PromptRunRecord, output) -> PromptRunRecord:
        partial_run = replace(
            current_run,
            llmProvider=output.provider,
            llmModel=output.model,
            outputText=output.detail.strip(),
            structuredExtractionResult=output.structuredExtractionResult,
            schemaOutput=output.schemaOutput,
            validationErrors=list(output.validationErrors or []),
            structuredProcessResult=output.structuredProcessResult,
            structuredBusinessResult=output.structuredBusinessResult,
            updatedAt=self._now_iso(),
            lastHeartbeatAt=self._now_iso(),
            errorMessage=None,
        )
        self._repository.save_prompt_run(partial_run, refresh_task=False)
        return partial_run

    def _create_summary_run(
        self,
        taskId: str,
        *,
        prompt_name: str = "文档级汇总",
        prompt_text: str = "基于已完成的分页或页组结果，汇总整份文档的关键结论、风险与证据页范围。",
        run_name: str | None = None,
    ) -> PromptRunRecord | None:
        detail = self._repository.get_task_detail(taskId)
        completed_page_runs = [
            run
            for run in self._repository.list_prompt_runs(taskId)
            if run.runType != "summary" and run.status in {"completed", "needs_review"}
        ]
        if not completed_page_runs:
            return None

        summary_run = PromptRunRecord(
            id=f"prompt-run-{uuid4().hex[:12]}",
            taskId=taskId,
            documentId=detail.document.id,
            runType="summary",
            runName=run_name or f"{prompt_name} {_format_page_range(min(run.startPageNo for run in completed_page_runs), max(run.endPageNo for run in completed_page_runs))}",
            promptName=prompt_name,
            promptText=prompt_text,
            startPageNo=min(run.startPageNo for run in completed_page_runs),
            endPageNo=max(run.endPageNo for run in completed_page_runs),
            status="running",
            runPurpose="summary",
            updatedAt=self._now_iso(),
        )
        summary_input = [
            {
                "runId": run.id,
                "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
                "promptName": run.promptName,
                "detail": run.outputText,
            }
            for run in completed_page_runs
        ]
        input_path = self._runtime_store.write_json_artifact(
            taskId,
            "summary-inputs",
            f"{summary_run.id}.json",
            summary_input,
        )
        running_summary = self._run_with_phase(
            replace(summary_run, inputPath=input_path),
            "model_processing",
        )
        self._repository.save_prompt_run(running_summary)

        try:
            output = self._llm_service.run_summary(
                taskId=taskId,
                promptName=prompt_name,
                promptText=prompt_text,
                pageResults=summary_input,
            )
            output_payload = {
                "title": output.title,
                "excerpt": output.excerpt,
                "detail": output.detail,
                "structuredExtractionResult": output.structuredExtractionResult,
                "structuredProcessResult": output.structuredProcessResult,
                "structuredBusinessResult": output.structuredBusinessResult,
                "provider": output.provider,
                "model": output.model,
            }
            output_path = self._runtime_store.write_json_artifact(
                taskId,
                "summary-outputs",
                f"{summary_run.id}.json",
                output_payload,
            )
            self._persist_llm_logs(run=running_summary, output=output, stage="summary")
            completed_summary = self._run_with_phase(
                replace(
                    running_summary,
                    status="completed",
                    llmProvider=output.provider,
                    llmModel=output.model,
                    outputText=output.detail.strip(),
                    structuredExtractionResult=output.structuredExtractionResult,
                    structuredProcessResult=output.structuredProcessResult,
                    structuredBusinessResult=output.structuredBusinessResult,
                    outputPath=output_path,
                    errorMessage=None,
                ),
                "completed",
            )
            return self._repository.save_prompt_run(completed_summary)
        except Exception as exc:
            error_text = str(exc)
            error_path = self._runtime_store.write_text_artifact(
                taskId,
                "summary-outputs",
                f"{summary_run.id}.error.txt",
                error_text,
            )
            failed_summary = self._run_with_phase(
                replace(
                    running_summary,
                    status="failed",
                    errorMessage=error_text,
                    outputPath=error_path,
                ),
                "failed",
            )
            return self._repository.save_prompt_run(failed_summary)

    def _build_scopes(
        self,
        *,
        start_page_no: int,
        end_page_no: int,
        run_mode: str,
        page_group_size: int | None,
    ) -> list[tuple[int, int]]:
        if end_page_no < start_page_no:
            raise RuntimeError("页组结束页不能小于起始页。")
        if run_mode == "page":
            return [(page_no, page_no) for page_no in range(start_page_no, end_page_no + 1)]
        if run_mode == "page_group":
            return [(start_page_no, end_page_no)]
        group_size = page_group_size or self._settings.prompt_default_page_group_size
        scopes: list[tuple[int, int]] = []
        cursor = start_page_no
        while cursor <= end_page_no:
            scopes.append((cursor, min(end_page_no, cursor + group_size - 1)))
            cursor += group_size
        return scopes

    def _ensure_task_ready(self, parse_status: str, pages: list[object]) -> None:
        if parse_status != "completed":
            raise RuntimeError("当前任务尚未完成文档解析，无法执行分页提示词处理。")
        if not pages:
            raise RuntimeError("当前任务暂无可用分页结果，无法执行二次处理。")

    def _to_run_response(self, run: PromptRunRecord) -> PromptRunRecordResponse:
        return PromptRunRecordResponse(
            id=run.id,
            runType=run.runType,
            runPurpose=run.runPurpose,
            runName=run.runName,
            promptName=run.promptName,
            promptText=run.promptText,
            startPageNo=run.startPageNo,
            endPageNo=run.endPageNo,
            pageRange=_format_page_range(run.startPageNo, run.endPageNo),
            status=run.status,
            runPhase=_normalize_run_phase(run),
            phaseStartedAt=run.phaseStartedAt,
            lastHeartbeatAt=run.lastHeartbeatAt,
            errorMessage=run.errorMessage,
            outputText=run.outputText,
            inputPath=run.inputPath,
            outputPath=run.outputPath,
            updatedAt=run.updatedAt,
            schemaTemplateId=run.templateId,
            schemaTemplateName=run.schemaTemplateName,
            schemaTemplateVersion=run.schemaTemplateVersion,
        )

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


def _normalize_run_phase(run: PromptRunRecord) -> str:
    phase = str(run.runPhase or "").strip()
    if phase == "queued" and run.status in {"completed", "failed", "needs_review"}:
        return run.status
    if phase in {"queued", "preparing_input", "model_processing", "validating", "saving", "completed", "failed", "needs_review"}:
        return phase
    if run.status == "running":
        return "model_processing"
    if run.status in {"completed", "failed", "needs_review"}:
        return run.status
    return "queued"


def _completion_status_from_validation_errors(errors: Any) -> str:
    if not errors:
        return "completed"
    if isinstance(errors, list):
        return "needs_review" if any(str(item).strip() for item in errors) else "completed"
    return "needs_review" if str(errors).strip() else "completed"


def _summarize_upstream_prompt_run(run: PromptRunRecord) -> dict[str, Any]:
    schema_definition = run.schemaDefinition if isinstance(run.schemaDefinition, dict) else {}
    skill_meta = schema_definition.get("skill") if isinstance(schema_definition.get("skill"), dict) else {}
    structured_payload = (
        run.structuredProcessResult
        if isinstance(run.structuredProcessResult, dict)
        else run.structuredExtractionResult
        if isinstance(run.structuredExtractionResult, dict)
        else {}
    )
    summary = ""
    if isinstance(structured_payload, dict):
        summary = str(
            structured_payload.get("summary")
            or structured_payload.get("excerpt")
            or structured_payload.get("title")
            or ""
        ).strip()
    if not summary:
        summary = str(run.outputText or "").strip()[:500]
    return {
        "runId": run.id,
        "runPurpose": run.runPurpose,
        "pageRange": _format_page_range(run.startPageNo, run.endPageNo),
        "status": run.status,
        "skillId": str(skill_meta.get("id") or ""),
        "skillVersion": str(skill_meta.get("version") or ""),
        "skillName": str(skill_meta.get("name") or run.promptName),
        "summary": summary[:500],
        "output": _compact_json_payload(structured_payload, max_chars=4000),
    }


def _append_skill_chain_context(instruction: str, upstream_context: list[dict[str, Any]]) -> str:
    if not upstream_context:
        return instruction
    context_text = json.dumps(upstream_context[-5:], ensure_ascii=False, default=str)
    if len(context_text) > 6000:
        context_text = f"{context_text[:6000]}..."
    return (
        f"{instruction}\n\n"
        "前序处理结果如下，请作为本次处理的业务上下文；如果字段已在前序步骤确认，不要重复解释，只输出本步骤需要补充或判断的结果：\n"
        f"{context_text}"
    )


def _compact_json_payload(payload: Any, *, max_chars: int) -> Any:
    if payload is None:
        return None
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return payload
    return {"truncated": True, "preview": text[:max_chars]}


def _redact_sensitive_payload(payload: Any) -> Any:
    sensitive_keys = {
        "authorization",
        "cookie",
        "api_key",
        "apikey",
        "access_key",
        "access_key_id",
        "access_key_secret",
        "secret",
        "token",
        "password",
        "database_url",
    }
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in sensitive_keys or any(part in normalized_key for part in ("secret", "password", "token")):
                redacted[str(key)] = "***REDACTED***"
            else:
                redacted[str(key)] = _redact_sensitive_payload(value)
        return redacted
    if isinstance(payload, list):
        return [_redact_sensitive_payload(item) for item in payload]
    return payload


def _json_char_length(payload: Any) -> int:
    if payload is None:
        return 0
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str))
    except TypeError:
        return len(str(payload))


def _response_content_length(payload: Any) -> int:
    if not isinstance(payload, dict):
        return _json_char_length(payload)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return _json_char_length(payload)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(str(item.get("text") or "")) for item in content if isinstance(item, dict))
    return _json_char_length(payload)


def _coerce_int(value: Any, default: int = 0) -> int:
    coerced = _coerce_optional_int(value)
    return default if coerced is None else coerced


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_page_range(start_page_no: int, end_page_no: int) -> str:
    if start_page_no == end_page_no:
        return f"第 {start_page_no} 页"
    return f"第 {start_page_no}-{end_page_no} 页"


def _derive_prompt_page_title(page: object) -> str:
    page_no = getattr(page, "pageNo", None)
    if isinstance(page_no, int):
        return f"第 {page_no} 页"
    return "页面"


def _derive_prompt_page_summary(page: object) -> str:
    blocks = getattr(page, "blocks", None)
    if not isinstance(blocks, list):
        return ""

    summary_parts: list[str] = []
    for block in blocks:
        content = getattr(block, "content", "")
        if not isinstance(content, str):
            continue
        normalized = re.sub(r"\s+", " ", content).strip()
        if not normalized:
            continue
        summary_parts.append(normalized[:80])
        if len(summary_parts) >= 2:
            break
    return " / ".join(summary_parts)


def _validate_table_extraction_consistency(
    *,
    page_payload: dict[str, Any],
    structured_extraction: dict[str, Any] | None,
) -> None:
    if not structured_extraction or not isinstance(structured_extraction, dict):
        return
        
    validation_meta = structured_extraction.get("validationMeta")
    if not isinstance(validation_meta, dict):
        return
        
    table_inputs = validation_meta.get("tableInputs")
    if not isinstance(table_inputs, list):
        return
        
    for table_input in table_inputs:
        if not isinstance(table_input, dict):
            continue

        if _table_input_is_parser_only_result(table_input):
            continue
            
        input_rows = table_input.get("inputRows")
        if not isinstance(input_rows, list):
            continue
            
        row_decisions = table_input.get("rowDecisions")
        requires_row_decisions = _table_input_requires_row_decisions(table_input)
        if not requires_row_decisions:
            expected_row_count = len(input_rows)
            actual_row_count = _extract_actual_row_count_for_table_input(
                table_input,
                structured_extraction=structured_extraction,
            )
            if expected_row_count > 0 and actual_row_count != expected_row_count:
                raise RuntimeError(f"表格抽取行数不一致：预期 {expected_row_count} 行，实际 {actual_row_count} 行。")
            continue

        if not isinstance(row_decisions, list):
            if len(input_rows) > 0:
                expected_row_count = len(input_rows)
                actual_row_count = _extract_actual_row_count_for_table_input(
                    table_input,
                    structured_extraction=structured_extraction,
                )
                if actual_row_count != expected_row_count:
                    raise RuntimeError(f"表格抽取行数不一致：预期 {expected_row_count} 行，实际 {actual_row_count} 行。")
            continue
            
        input_anchors = {str(row.get("anchor")) for row in input_rows if isinstance(row, dict) and row.get("anchor")}
        decision_anchors = {str(dec.get("anchor")) for dec in row_decisions if isinstance(dec, dict) and dec.get("anchor")}
        
        missing_decisions = input_anchors - decision_anchors
        if missing_decisions:
            raise RuntimeError(f"表格抽取决策不完整：缺少对以下行的判断: {', '.join(missing_decisions)}。")


def _table_input_requires_row_decisions(table_input: dict[str, Any]) -> bool:
    table_task_mode = str(table_input.get("tableTaskMode") or "").strip()
    chunk_strategy = str(table_input.get("chunkStrategy") or "").strip()
    if table_task_mode in {"parse_json", "semantic_enrich"}:
        return False
    return chunk_strategy in {"batch_windows", "table_rows"}


def _table_input_is_parser_only_result(table_input: dict[str, Any]) -> bool:
    chunk_strategy = str(table_input.get("chunkStrategy") or "").strip()
    table_task_mode = str(table_input.get("tableTaskMode") or "").strip()
    parser_result = table_input.get("parserResult")
    return (
        chunk_strategy == "parser_only"
        or (table_task_mode == "parse_json" and isinstance(parser_result, dict))
    )


def _extract_actual_row_count_for_table_input(
    table_input: dict[str, Any],
    *,
    structured_extraction: dict[str, Any],
) -> int:
    parser_result = table_input.get("parserResult")
    if isinstance(parser_result, dict):
        for table_key in ("displayTable", "canonicalTable"):
            table_payload = parser_result.get(table_key)
            if not isinstance(table_payload, dict):
                continue
            rows = table_payload.get("rows")
            if isinstance(rows, list):
                return len(rows)

    actual_row_count, _ = _extract_actual_table_rows(structured_extraction)
    return actual_row_count


def _extract_expected_table_rows(
    page_payload: dict[str, Any],
    *,
    structured_extraction: dict[str, Any] | None = None,
) -> tuple[int, list[str]]:
    validation_meta = _extract_table_validation_meta(structured_extraction)
    if validation_meta is not None:
        return validation_meta

    row_count = 0
    labels: list[str] = []
    prompt_text = str(page_payload.get("promptText") or "")
    _, table_prompt = _split_modal_prompts(prompt_text)
    if not table_prompt:
        return (0, [])
    for page in page_payload.get("pages") or []:
        target_blocks = _filter_target_table_blocks_for_prompt(
            mode_prompt=table_prompt,
            relevant_blocks=list(page.get("blocks") or []),
        )
        for block in target_blocks:
            if str(block.get("type") or "").lower() != "table":
                continue
            _, data_rows = _split_html_table_rows(str(block.get("content") or ""))
            numeric_labels = _extract_numeric_row_labels_from_html_rows(data_rows)
            if numeric_labels:
                row_count += len(numeric_labels)
                labels.extend(numeric_labels)
                continue
            row_count += len(data_rows)
    return (row_count, labels)


def _extract_table_validation_meta(
    structured_extraction: dict[str, Any] | None,
) -> tuple[int, list[str]] | None:
    if not structured_extraction or not isinstance(structured_extraction, dict):
        return None
    validation_meta = structured_extraction.get("validationMeta")
    if not isinstance(validation_meta, dict):
        return None
    table_inputs = validation_meta.get("tableInputs")
    if not isinstance(table_inputs, list):
        return None

    row_count = 0
    row_labels: list[str] = []
    for table_input in table_inputs:
        if not isinstance(table_input, dict):
            continue
        input_rows = table_input.get("inputRows")
        if not isinstance(input_rows, list):
            continue
        for row in input_rows:
            if not isinstance(row, dict):
                continue
            row_count += 1
            cells = row.get("cells")
            if isinstance(cells, list) and cells:
                first_cell = str(cells[0]).strip()
                if first_cell:
                    row_labels.append(first_cell)
    if row_count <= 0:
        return None
    return (row_count, row_labels)


def _extract_numeric_row_labels_from_html_rows(rows: list[str]) -> list[str]:
    labels: list[str] = []
    for row_html in rows:
        cells = [
            _strip_html(cell)
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
        ]
        if not cells:
            continue
        first_cell = cells[0].strip()
        if re.fullmatch(r"\d+", first_cell):
            labels.append(first_cell)
    return labels


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return " ".join(unescape(text).split()).strip()


def _extract_actual_table_rows(structured_extraction: dict[str, Any] | None) -> tuple[int, list[str]]:
    if not structured_extraction:
        return (0, [])

    custom_result = structured_extraction.get("customResult")
    structured_table = _extract_structured_table(custom_result)
    if structured_table is not None:
        headers, rows = structured_table
        labels = [row[0] for row in rows if row and row[0]]
        total_rows = _extract_total_rows(custom_result)
        return (total_rows if total_rows is not None else len(rows), labels if headers else labels)

    markdown_table = _extract_markdown_table(custom_result)
    markdown_labels = _extract_row_labels_from_markdown_table(markdown_table) if markdown_table else []
    if markdown_labels:
        total_rows = _extract_total_rows(custom_result)
        return (total_rows if total_rows is not None else len(markdown_labels), markdown_labels)

    total_rows = _extract_total_rows(custom_result)
    if total_rows is not None:
        return (total_rows, [])

    return (0, [])


def _extract_markdown_table(custom_result: Any) -> str:
    if isinstance(custom_result, dict):
        candidate = custom_result.get("markdown_table")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        return ""

    if isinstance(custom_result, str):
        trimmed = custom_result.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError:
                return ""
            return _extract_markdown_table(parsed)
        return trimmed

    return ""


def _extract_structured_table(custom_result: Any) -> tuple[list[str], list[list[str]]] | None:
    if isinstance(custom_result, str):
        trimmed = custom_result.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError:
                return None
            return _extract_structured_table(parsed)
        return None

    if not isinstance(custom_result, dict):
        return None

    canonical_table = custom_result.get("canonicalTable")
    if isinstance(canonical_table, dict):
        headers = canonical_table.get("headers")
        rows = canonical_table.get("rows")
        if (
            isinstance(headers, list)
            and all(isinstance(header, str) for header in headers)
            and isinstance(rows, list)
            and all(isinstance(row, list) for row in rows)
        ):
            normalized_rows = [[str(cell or "").strip() for cell in row] for row in rows]
            return ([str(header).strip() for header in headers], normalized_rows)

    rows = custom_result.get("rows")
    if not isinstance(rows, list) or not rows:
        return None

    normalized_rows: list[list[str]] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        label = str(row.get("label") or "").strip()
        values = row.get("values")
        if not isinstance(values, list):
            return None
        normalized_rows.append([label, *[str(value or "").strip() for value in values]])
    if not normalized_rows:
        return None
    return ([], normalized_rows)


def _extract_total_rows(custom_result: Any) -> int | None:
    if isinstance(custom_result, dict):
        total_rows = custom_result.get("total_rows")
        if isinstance(total_rows, int):
            return total_rows
    if isinstance(custom_result, str):
        trimmed = custom_result.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError:
                return None
            return _extract_total_rows(parsed)
    return None


def _extract_row_labels_from_markdown_table(markdown_table: str) -> list[str]:
    lines = [line.strip() for line in markdown_table.splitlines() if line.strip()]
    if len(lines) < 3:
        return []

    labels: list[str] = []
    for line in lines[2:]:
        if not line.startswith("|"):
            continue
        if re.fullmatch(r"\|?[\s:|-]+\|?", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        first_cell = cells[0]
        if re.fullmatch(r"\d+", first_cell):
            labels.append(first_cell)
    return labels


def _build_prompt_input_artifact(page_payload: dict[str, object]) -> dict[str, object]:
    return {
        "taskId": page_payload.get("taskId"),
        "documentId": page_payload.get("documentId"),
        "pageRange": page_payload.get("pageRange"),
        "promptName": page_payload.get("promptName"),
        "promptText": page_payload.get("promptText"),
        "tableTaskMode": page_payload.get("tableTaskMode"),
        "pages": [
            {
                "pageNo": page.get("pageNo"),
                "title": page.get("title"),
                "summary": page.get("summary"),
                "markdownSegments": [
                    {
                        "id": segment.get("id"),
                        "blockId": segment.get("blockId"),
                        "type": segment.get("type"),
                        "html": segment.get("html"),
                    }
                    for segment in page.get("markdownSegments", [])
                ],
                "blocks": [
                    {
                        "id": block.get("id"),
                        "type": block.get("type"),
                        "title": block.get("title"),
                        "content": block.get("content"),
                        "tableHeaderContext": block.get("tableHeaderContext"),
                    }
                    for block in page.get("blocks", [])
                ],
            }
            for page in page_payload.get("pages", [])
        ],
    }


def _build_table_header_contexts(
    *,
    pages: list[WorkbenchPageDetail],
    prompt_text: str,
) -> dict[tuple[int, str], dict[str, Any]]:
    _, table_prompt = _split_modal_prompts(prompt_text)
    if not table_prompt:
        return {}

    explicit_field_groups = _extract_prompt_field_keyword_groups(table_prompt)

    contexts: dict[tuple[int, str], dict[str, Any]] = {}
    latest_explicit_by_column_count: dict[int, dict[str, Any]] = {}

    for page in sorted(pages, key=lambda item: item.pageNo):
        for block in page.blocks:
            block_id = str(block.id or "").strip()
            block_type = str(block.type or "").lower()
            block_content = str(block.content or "").strip()
            if not block_id or block_type not in {"table", "table_body"} or not block_content:
                continue

            if explicit_field_groups:
                explicit_context = _extract_explicit_table_header_context(
                    page_no=page.pageNo,
                    block_id=block_id,
                    table_html=block_content,
                    expected_field_groups=explicit_field_groups,
                )
            else:
                explicit_context = _extract_inferred_table_header_context(
                    page_no=page.pageNo,
                    block_id=block_id,
                    table_html=block_content,
                    table_prompt=table_prompt,
                )
            if explicit_context:
                contexts[(page.pageNo, block_id)] = explicit_context
                column_count = int(explicit_context.get("sourceColumnCount") or 0)
                if column_count > 0:
                    latest_explicit_by_column_count[column_count] = explicit_context
                continue

            column_count = _estimate_table_source_column_count(block_content)
            if column_count <= 0:
                continue
            inherited_context = latest_explicit_by_column_count.get(column_count)
            if not inherited_context:
                continue
            contexts[(page.pageNo, block_id)] = {
                "headerMode": "inherited",
                "sourcePageNo": inherited_context.get("sourcePageNo"),
                "sourceBlockId": inherited_context.get("sourceBlockId"),
                "sourceColumnCount": inherited_context.get("sourceColumnCount"),
                "sourceHeaders": list(inherited_context.get("sourceHeaders") or []),
            }

    return contexts


def _extract_inferred_table_header_context(
    *,
    page_no: int,
    block_id: str,
    table_html: str,
    table_prompt: str,
) -> dict[str, Any] | None:
    parser_result = parse_table_html(table_html, title="")
    header_rows, _ = _split_html_table_rows(table_html)
    raw_header_cells: list[str] = []
    for row_html in header_rows:
        raw_header_cells.extend(_extract_html_row_cells(row_html))
    header_candidates = _collect_table_header_candidates(
        parser_result=parser_result,
        context_headers=[],
        raw_header_cells=raw_header_cells,
    )
    inferred_fields, inferred_headers = _infer_table_fields_from_prompt(
        mode_prompt=table_prompt,
        header_candidates=header_candidates,
    )
    if not inferred_fields or not inferred_headers:
        return None
    expected_field_groups = _build_field_keyword_groups_from_fields(inferred_fields)
    if not expected_field_groups:
        return None
    return {
        "headerMode": "inferred_header",
        "sourcePageNo": page_no,
        "sourceBlockId": block_id,
        "sourceColumnCount": len(inferred_headers),
        "sourceHeaders": inferred_headers,
    }


def _extract_explicit_table_header_context(
    *,
    page_no: int,
    block_id: str,
    table_html: str,
    expected_field_groups: list[set[str]],
) -> dict[str, Any] | None:
    header_rows, data_rows = _split_html_table_rows(table_html)
    candidate_rows = [*header_rows, *(data_rows[:3] if data_rows else [])]
    if not candidate_rows:
        return None

    best_cells: list[str] = []
    best_score = 0
    required_score = max(2, min(len(expected_field_groups), 2))
    for row_html in candidate_rows:
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

    if best_score < required_score or not best_cells:
        return None

    return {
        "headerMode": "explicit",
        "sourcePageNo": page_no,
        "sourceBlockId": block_id,
        "sourceColumnCount": len(best_cells),
        "sourceHeaders": best_cells,
    }


def _estimate_table_source_column_count(table_html: str) -> int:
    header_rows, data_rows = _split_html_table_rows(table_html)
    candidate_rows = [*header_rows, *(data_rows[:3] if data_rows else [])]
    best_count = 0
    for row_html in candidate_rows:
        cells = [str(cell).strip() for cell in _extract_html_row_cells(row_html) if str(cell).strip()]
        best_count = max(best_count, len(cells))
    return best_count


def _try_run_local_object_operation(
    *,
    page_no: int,
    operation_type: str,
    instruction: str,
    result_mode: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
) -> PromptRunOutput | None:
    if operation_type != "transform" or result_mode not in {"auto", "object"}:
        return None
    rules = _extract_local_display_mapping_rules(instruction, facts_payload)
    if not rules:
        return None
    snapshots = _collect_structured_object_snapshots(facts_payload)
    if not snapshots:
        return None

    processed_objects: list[dict[str, Any]] = []
    changed_count = 0
    for snapshot in snapshots:
        structured_object = snapshot.get("structuredObject")
        if not isinstance(structured_object, dict):
            continue
        object_id = str(snapshot.get("id") or structured_object.get("id") or "").strip()
        label = str(snapshot.get("label") or structured_object.get("title") or object_id or "复合表对象").strip()
        kv_payload, kv_changes = _normalize_mapping_record(dict(structured_object.get("kv") or {}), rules)
        table_rows: list[dict[str, Any]] = []
        for row in structured_object.get("table") or []:
            if not isinstance(row, dict):
                continue
            normalized_row, row_changes = _normalize_mapping_record(row, rules)
            table_rows.append(normalized_row)
            changed_count += row_changes
        changed_count += kv_changes
        processed_objects.append(
            {
                "id": object_id,
                "label": label,
                "kv_data": kv_payload,
                "table_data": table_rows,
            }
        )

    if not processed_objects:
        return None

    evidence_refs = _collect_object_operation_evidence_refs([target, *related_targets], facts_payload)
    rule_text = "、".join(
        f"{rule['field']} {rule['rawValue']} -> {rule['displayValue']}"
        for rule in rules
    )
    summary = (
        f"已按本地映射规则处理 {len(processed_objects)} 个复合表对象，"
        f"命中 {changed_count} 个值。"
    )
    output_payload = {"processed_objects": processed_objects}
    structured_process_result = {
        "summary": summary,
        "operationType": operation_type,
        "targetId": str(target.get("id") or ""),
        "relatedTargetIds": [
            str(item.get("id") or "").strip()
            for item in related_targets
            if str(item.get("id") or "").strip()
        ],
        "resultKind": "object",
        "outputPayload": output_payload,
        "validationErrors": [],
        "evidenceRefs": evidence_refs,
        "source": "local_rules",
    }
    return PromptRunOutput(
        title=f"第 {page_no} 页对象处理",
        excerpt=summary,
        detail=json.dumps(output_payload, ensure_ascii=False),
        structuredExtractionResult=None,
        structuredProcessResult=structured_process_result,
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
        rawContent=json.dumps(structured_process_result, ensure_ascii=False),
        provider="local",
        model="object-operation-rules",
        validationErrors=[],
        llmLogs={
            "mode": "object_operation_local",
            "rules": rules,
            "ruleText": rule_text,
        },
    )


def _operation_type_for_skill_executor(executor: str) -> str:
    if executor == "quality_check":
        return "review"
    if executor in {"local_transform", "controlled_python"}:
        return "transform"
    return "map"


def _skill_payload_for_llm(skill_meta: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "id",
        "version",
        "name",
        "category",
        "sourceTypes",
        "executor",
        "inputBuilder",
        "renderer",
        "outputSchema",
        "promptTemplate",
        "rules",
        "examples",
    ]
    return {key: skill_meta.get(key) for key in allowed if key in skill_meta}


def _build_extraction_run_meta(
    *,
    skill_meta: dict[str, Any],
    config: dict[str, Any],
    output: PromptRunOutput,
    duration_ms: int,
    input_payload: dict[str, Any],
    raw_payload: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage = {}
    if isinstance(output.llmLogs, dict):
        response = output.llmLogs.get("response")
        if isinstance(response, dict) and isinstance(response.get("usage"), dict):
            usage = response["usage"]
    return {
        "skillId": str(skill_meta.get("id") or ""),
        "skillVersion": str(skill_meta.get("version") or ""),
        "executor": str(skill_meta.get("executor") or "llm_structured"),
        "inputBuilder": str(skill_meta.get("inputBuilder") or "page_compact"),
        "configSnapshot": config,
        "provider": output.provider,
        "model": output.model,
        "durationMs": duration_ms,
        "inputChars": len(json.dumps(input_payload, ensure_ascii=False)),
        "outputChars": len(json.dumps(raw_payload, ensure_ascii=False)),
        "promptTokens": usage.get("prompt_tokens"),
        "completionTokens": usage.get("completion_tokens"),
        "totalTokens": usage.get("total_tokens"),
        "metrics": metrics or {},
    }


def _normalize_extraction_skill_output(
    *,
    raw_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    run_meta: dict[str, Any],
) -> dict[str, Any]:
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(output_schema.get("type") or "custom").strip() or "custom"
    required_fields = [
        str(item).strip()
        for item in (output_schema.get("required") or [])
        if str(item).strip()
    ] if isinstance(output_schema.get("required"), list) else []

    if isinstance(raw_payload.get("outputs"), list):
        outputs = raw_payload["outputs"]
    else:
        data_payload = _extract_direct_extraction_output_data(
            raw_payload=raw_payload,
            output_type=output_type,
        )
        outputs = [
            {
                "id": "output-1",
                "title": str(skill_meta.get("name") or "提取结果"),
                "type": output_type if output_type in {
                    "field_list",
                    "data_table",
                    "kv_table",
                    "kv_record_table",
                    "record_collection",
                    "custom",
                } else "custom",
                "renderer": str(skill_meta.get("renderer") or "auto"),
                "data": data_payload,
                "schema": output_schema,
                "sourceRefs": [],
            }
        ]

    normalized_outputs = [
        _normalize_extraction_output_item(
            item,
            index,
            default_type=output_type,
            default_renderer=str(skill_meta.get("renderer") or "auto"),
            default_schema=output_schema,
        )
        for index, item in enumerate(outputs)
    ]
    _validate_extraction_required_fields(
        outputs=normalized_outputs,
        output_type=output_type,
        required_fields=required_fields,
    )
    summary = str(raw_payload.get("summary") or "").strip()
    if not summary:
        summary = _render_extraction_summary_template(
            template=str(skill_meta.get("summaryTemplate") or ""),
            skill_name=str(skill_meta.get("name") or "结构化解析"),
            outputs=normalized_outputs,
        )
    errors = [
        str(item).strip()
        for item in (raw_payload.get("errors") or raw_payload.get("validationErrors") or [])
        if str(item).strip()
    ]
    warnings = [
        str(item).strip()
        for item in (raw_payload.get("validationWarnings") or raw_payload.get("validation_warnings") or [])
        if str(item).strip()
    ]
    legacy = _derive_legacy_extraction_fields(normalized_outputs)
    return {
        "summary": summary,
        "outputs": normalized_outputs,
        "errors": errors,
        "runMeta": run_meta,
        "fields": legacy["fields"],
        "tables": legacy["tables"],
        "structuredObjects": legacy["structuredObjects"],
        "validationErrors": errors,
        "validationWarnings": warnings,
    }


def _validate_extraction_required_fields(
    *,
    outputs: list[dict[str, Any]],
    output_type: str,
    required_fields: list[str],
) -> None:
    if not required_fields:
        return
    if output_type == "record_collection":
        for output in outputs:
            if output.get("type") != "record_collection":
                continue
            data = output.get("data")
            records = data.get("records") if isinstance(data, dict) else None
            if not isinstance(records, list):
                raise RuntimeError("解析 skill 输出不符合 schema：record_collection 必须返回 records 数组。")
            for record_index, record in enumerate(records):
                if not isinstance(record, dict):
                    raise RuntimeError(f"解析 skill 输出不符合 schema：records 第 {record_index + 1} 条必须是对象。")
                missing = [field for field in required_fields if field not in record]
                if missing:
                    raise RuntimeError(
                        f"解析 skill 输出不符合 schema：records 第 {record_index + 1} 条缺少字段 {', '.join(missing)}。"
                    )
        return
    if isinstance(outputs, list) and len(outputs) == 1:
        output = outputs[0]
        data = output.get("data")
        if isinstance(data, dict):
            missing = [field for field in required_fields if field not in data]
            if missing:
                raise RuntimeError(f"解析 skill 输出不符合 schema：缺少字段 {', '.join(missing)}。")


def _extract_direct_extraction_output_data(
    *,
    raw_payload: dict[str, Any],
    output_type: str,
) -> Any:
    if output_type == "record_collection":
        if not isinstance(raw_payload.get("records"), list):
            raise RuntimeError("解析 skill 输出不符合 schema：record_collection 必须返回 records 数组，不能返回单条对象。")
        return {"records": raw_payload["records"]}
    if output_type == "data_table" and ("headers" in raw_payload or "rows" in raw_payload):
        data = {
            "headers": raw_payload.get("headers") if isinstance(raw_payload.get("headers"), list) else [],
            "rows": raw_payload.get("rows") if isinstance(raw_payload.get("rows"), list) else [],
        }
        for key in ("mergeNotes", "evidence"):
            if isinstance(raw_payload.get(key), list):
                data[key] = raw_payload[key]
        return data
    if output_type == "field_list" and isinstance(raw_payload.get("fields"), list):
        return {"fields": raw_payload["fields"]}
    if output_type == "kv_table" and isinstance(raw_payload.get("kv"), dict):
        return {"kv": raw_payload["kv"]}
    if output_type == "kv_record_table" and ("kv" in raw_payload or "table" in raw_payload):
        return {
            "kv": raw_payload.get("kv") if isinstance(raw_payload.get("kv"), dict) else {},
            "table": raw_payload.get("table") if isinstance(raw_payload.get("table"), list) else [],
        }
    return raw_payload


def _normalize_extraction_output_item(
    item: Any,
    index: int,
    *,
    default_type: str = "custom",
    default_renderer: str = "auto",
    default_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {"data": item}
    output_type = str(item.get("type") or default_type or "custom")
    if output_type not in {"field_list", "data_table", "kv_table", "kv_record_table", "record_collection", "custom"}:
        output_type = "custom"
    data = item.get("data") if "data" in item else {}
    data = _normalize_extraction_output_data(data=data, output_type=output_type)
    return {
        "id": str(item.get("id") or f"output-{index + 1}"),
        "title": str(item.get("title") or f"提取结果 {index + 1}"),
        "type": output_type,
        "renderer": str(item.get("renderer") or default_renderer or "auto"),
        "data": data,
        "schema": item.get("schema") if isinstance(item.get("schema"), dict) else (default_schema or {}),
        "sourceRefs": item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else [],
    }


def _normalize_extraction_output_data(*, data: Any, output_type: str) -> Any:
    if output_type == "record_collection":
        if isinstance(data, dict) and isinstance(data.get("record_collection"), dict):
            data = data["record_collection"]
        if isinstance(data, list):
            return {"records": data}
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            return {"records": data["records"]}
        raise RuntimeError("解析 skill 输出不符合 schema：record_collection 的 data 必须包含 records 数组。")
    if output_type == "data_table":
        if isinstance(data, dict) and isinstance(data.get("data_table"), dict):
            data = data["data_table"]
        if not isinstance(data, dict):
            raise RuntimeError("解析 skill 输出不符合 schema：data_table 的 data 必须是对象。")
        headers = data.get("headers")
        rows = data.get("rows")
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise RuntimeError("解析 skill 输出不符合 schema：data_table 必须包含 headers 和 rows 数组。")
        normalized = {"headers": headers, "rows": rows}
        for key in ("mergeNotes", "evidence"):
            if isinstance(data.get(key), list):
                normalized[key] = data[key]
        return normalized
    if output_type == "field_list":
        if isinstance(data, dict) and isinstance(data.get("field_list"), dict):
            data = data["field_list"]
        if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
            raise RuntimeError("解析 skill 输出不符合 schema：field_list 必须包含 fields 数组。")
        return {"fields": data["fields"]}
    if output_type == "kv_table":
        if not isinstance(data, dict) or not isinstance(data.get("kv"), dict):
            raise RuntimeError("解析 skill 输出不符合 schema：kv_table 必须包含 kv 对象。")
        return {"kv": data["kv"]}
    if output_type == "kv_record_table":
        if not isinstance(data, dict) or not isinstance(data.get("kv"), dict) or not isinstance(data.get("table"), list):
            raise RuntimeError("解析 skill 输出不符合 schema：kv_record_table 必须包含 kv 对象和 table 数组。")
        return {"kv": data["kv"], "table": data["table"]}
    return data


def _render_extraction_summary_template(
    *,
    template: str,
    skill_name: str,
    outputs: list[dict[str, Any]],
) -> str:
    counts = _count_extraction_outputs(outputs)
    if template:
        result = template
        for key, value in counts.items():
            result = result.replace("{" + key + "}", str(value))
        return result
    if counts.get("recordCount"):
        return f"已通过 {skill_name} 提取 {counts['recordCount']} 条记录。"
    if counts.get("rowCount"):
        return f"已通过 {skill_name} 提取 {counts['rowCount']} 行数据。"
    if counts.get("fieldCount"):
        return f"已通过 {skill_name} 提取 {counts['fieldCount']} 个字段。"
    return f"已通过 {skill_name} 生成结构化结果。"


def _count_extraction_outputs(outputs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"recordCount": 0, "rowCount": 0, "fieldCount": 0, "componentCount": 0}
    for output in outputs:
        data = output.get("data")
        output_type = output.get("type")
        if output_type == "record_collection" and isinstance(data, dict):
            records = data.get("records")
            if isinstance(records, list):
                counts["recordCount"] += len(records)
                for record in records:
                    if isinstance(record, dict) and isinstance(record.get("components"), list):
                        counts["componentCount"] += len(record["components"])
        elif output_type == "data_table" and isinstance(data, dict):
            rows = data.get("rows")
            if isinstance(rows, list):
                counts["rowCount"] += len(rows)
        elif output_type in {"field_list", "kv_table"} and isinstance(data, dict):
            fields = data.get("fields")
            kv = data.get("kv")
            if isinstance(fields, list):
                counts["fieldCount"] += len(fields)
            elif isinstance(kv, dict):
                counts["fieldCount"] += len(kv)
    return counts


def _derive_legacy_extraction_fields(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    structured_objects: list[dict[str, Any]] = []
    for output in outputs:
        data = output.get("data")
        output_type = output.get("type")
        title = str(output.get("title") or "")
        if output_type == "field_list" and isinstance(data, dict):
            for item in data.get("fields") or []:
                if isinstance(item, dict):
                    label = str(item.get("label") or item.get("key") or "").strip()
                    if label:
                        fields.append({"label": label, "value": str(item.get("value") or ""), "source": "llm", "evidenceRefs": []})
        elif output_type == "kv_table" and isinstance(data, dict):
            kv = data.get("kv")
            if isinstance(kv, dict):
                for key, value in kv.items():
                    if str(key).strip():
                        fields.append({"label": str(key), "value": str(value), "source": "llm", "evidenceRefs": []})
        elif output_type == "data_table" and isinstance(data, dict):
            headers, rows = legacy_table_from_data_table(data)
            tables.append(
                {
                    "title": title,
                    "headers": headers,
                    "rows": rows,
                    "source": "llm",
                    "evidenceRefs": [],
                    "parserMeta": {},
                }
            )
        elif output_type == "kv_record_table" and isinstance(data, dict):
            structured_objects.append(
                {
                    "id": str(output.get("id") or ""),
                    "title": title,
                    "type": "kv_record_table",
                    "kv": {str(k): str(v) for k, v in (data.get("kv") or {}).items()} if isinstance(data.get("kv"), dict) else {},
                    "table": [
                        {str(k): str(v) for k, v in row.items()}
                        for row in (data.get("table") or [])
                        if isinstance(row, dict)
                    ],
                    "source": "llm",
                    "evidenceRefs": [],
                    "parserMeta": {},
                }
            )
    return {"fields": fields, "tables": tables, "structuredObjects": structured_objects}


def _build_skill_instruction(
    *,
    skill_name: str,
    prompt_template: str,
    config: dict[str, Any],
    selected_targets: list[OperationTargetRef],
) -> str:
    lines = [
        f"Skill：{skill_name}",
        prompt_template.strip() or "按业务 skill 配置处理选定范围。",
        "处理目标：" + "、".join(f"「{item.label}」" for item in selected_targets[:20]),
        "配置：",
        json.dumps(config, ensure_ascii=False, indent=2),
    ]
    extra_instruction = str(config.get("extraInstruction") or config.get("customInstruction") or "").strip()
    if extra_instruction:
        lines.append("用户补充要求：")
        lines.append(extra_instruction)
    return "\n".join(line for line in lines if line)


def _try_run_skill_object_operation(
    *,
    page_no: int,
    operation_type: str,
    result_mode: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any] | None,
) -> PromptRunOutput | None:
    if not skill_meta:
        return None
    executor = str(skill_meta.get("executor") or "").strip()
    config = skill_meta.get("config") if isinstance(skill_meta.get("config"), dict) else {}
    if executor == "local_transform":
        action = str(config.get("action") or "mapping").strip()
        if action == "field_extract":
            return _run_local_field_extract_skill(
                page_no=page_no,
                operation_type=operation_type,
                target=target,
                related_targets=related_targets,
                facts_payload=facts_payload,
                skill_meta=skill_meta,
                config=config,
            )
        return _run_local_mapping_skill(
            page_no=page_no,
            operation_type=operation_type,
            target=target,
            related_targets=related_targets,
            facts_payload=facts_payload,
            skill_meta=skill_meta,
            config=config,
        )
    if executor == "export_data":
        return _run_local_export_table_skill(
            page_no=page_no,
            operation_type=operation_type,
            target=target,
            related_targets=related_targets,
            facts_payload=facts_payload,
            skill_meta=skill_meta,
            config=config,
        )
    if executor == "http_connector":
        return _run_http_connector_skill(
            page_no=page_no,
            operation_type=operation_type,
            target=target,
            related_targets=related_targets,
            facts_payload=facts_payload,
            skill_meta=skill_meta,
            config=config,
        )
    if executor == "controlled_python":
        return _run_controlled_python_skill(
            page_no=page_no,
            operation_type=operation_type,
            target=target,
            related_targets=related_targets,
            facts_payload=facts_payload,
            skill_meta=skill_meta,
            config=config,
        )
    if executor == "quality_check":
        checks = set(_as_config_string_list(config.get("checks")))
        if checks - {"empty", "duplicate"} or str(config.get("extraInstruction") or "").strip():
            return None
        return _run_local_quality_check_skill(
            page_no=page_no,
            operation_type=operation_type,
            target=target,
            related_targets=related_targets,
            facts_payload=facts_payload,
            skill_meta=skill_meta,
            config=config,
        )
    return None


def _run_http_connector_skill(
    *,
    page_no: int,
    operation_type: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    config: dict[str, Any],
) -> PromptRunOutput:
    defaults = skill_meta.get("defaults") if isinstance(skill_meta.get("defaults"), dict) else {}
    http_config = defaults.get("http") if isinstance(defaults.get("http"), dict) else {}
    method = str(http_config.get("method") or "POST").strip().upper()
    url = str(http_config.get("url") or "").strip()
    if method not in {"GET", "POST", "PUT", "PATCH"} or not url:
        raise RuntimeError("http_connector 配置不完整：需要 method 和 url。")

    timeout = max(1, min(int(http_config.get("timeoutMs") or 10000) // 1000, 60))
    retries = max(0, min(int(http_config.get("retry") or 0), 3))
    headers = {"Content-Type": "application/json"}
    headers.update(_resolve_http_connector_headers(str(http_config.get("credentialRef") or "")))
    request_payload = {
        "skillId": str(skill_meta.get("id") or ""),
        "skillVersion": str(skill_meta.get("version") or ""),
        "config": config,
        "input": {
            "pageNo": page_no,
            "target": target,
            "relatedTargets": related_targets,
            "facts": facts_payload,
        },
    }
    data = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    response_payload: Any = None
    last_error: Exception | None = None
    for _ in range(retries + 1):
        try:
            request = urlrequest.Request(url, data=data if method != "GET" else None, method=method, headers=headers)
            with urlrequest.urlopen(request, timeout=timeout) as response:
                status_code = int(getattr(response, "status", 0) or 0)
                raw_text = response.read().decode("utf-8")
            if status_code < 200 or status_code >= 300:
                raise RuntimeError(f"http_connector 返回非 2xx 状态：{status_code}。")
            response_payload = json.loads(raw_text) if raw_text.strip() else {}
            break
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
    if response_payload is None:
        raise RuntimeError(f"http_connector 调用失败：{last_error}")
    if not isinstance(response_payload, dict):
        raise RuntimeError("http_connector 响应必须是 JSON 对象。")

    result_kind = str(skill_meta.get("resultKind") or "object")
    summary = str(response_payload.get("summary") or f"{skill_meta.get('name') or 'HTTP Skill'} 调用完成。").strip()
    output_payload = response_payload.get("outputPayload") if "outputPayload" in response_payload else response_payload
    return _build_local_skill_output(
        page_no=page_no,
        operation_type=operation_type,
        result_kind=result_kind,
        summary=summary,
        output_payload=output_payload if isinstance(output_payload, dict) else {"value": output_payload},
        target=target,
        related_targets=related_targets,
        facts_payload=facts_payload,
        skill_meta=skill_meta,
        provider_model="business-skill-http-connector",
    )


def _run_controlled_python_skill(
    *,
    page_no: int,
    operation_type: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    config: dict[str, Any],
) -> PromptRunOutput:
    defaults = skill_meta.get("defaults") if isinstance(skill_meta.get("defaults"), dict) else {}
    code = str(defaults.get("pythonCode") or "").strip()
    if not code:
        raise RuntimeError("controlled_python Skill 缺少 pythonCode。")
    script_result = _execute_controlled_python_code(
        code=code,
        input_payload={
            "pageNo": page_no,
            "target": target,
            "relatedTargets": related_targets,
            "facts": facts_payload,
        },
        config=config,
        context={
            "skillId": str(skill_meta.get("id") or ""),
            "skillVersion": str(skill_meta.get("version") or ""),
        },
        timeout_seconds=max(1, min(int(config.get("timeoutSeconds") or 5), 30)),
    )
    result_kind = str(script_result.get("resultKind") or skill_meta.get("resultKind") or "object")
    summary = str(script_result.get("summary") or f"{skill_meta.get('name') or 'Python Skill'} 执行完成。").strip()
    output_payload = script_result.get("outputPayload") if "outputPayload" in script_result else script_result
    if result_kind == "text" and isinstance(output_payload, str):
        normalized_payload: Any = output_payload
    elif isinstance(output_payload, dict):
        normalized_payload = output_payload
    else:
        normalized_payload = {"value": output_payload}
    return _build_local_skill_output(
        page_no=page_no,
        operation_type=operation_type,
        result_kind=result_kind,
        summary=summary,
        output_payload=normalized_payload,
        target=target,
        related_targets=related_targets,
        facts_payload=facts_payload,
        skill_meta=skill_meta,
        provider_model="business-skill-controlled-python",
    )


def _resolve_http_connector_headers(credential_ref: str) -> dict[str, str]:
    ref = credential_ref.strip()
    if not ref:
        return {}
    env_name = "SKILL_CREDENTIAL_" + re.sub(r"[^A-Za-z0-9]+", "_", ref).strip("_").upper()
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {"Authorization": f"Bearer {raw_value}"}
    if isinstance(payload, dict):
        headers = payload.get("headers")
        if isinstance(headers, dict):
            return {str(key): str(value) for key, value in headers.items()}
        token = str(payload.get("token") or "").strip()
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


def _execute_controlled_python_code(
    *,
    code: str,
    input_payload: dict[str, Any],
    config: dict[str, Any],
    context: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    wrapper = {
        "code": code,
        "input": input_payload,
        "config": config,
        "context": context,
    }
    runner = """
import json
import sys

payload = json.loads(sys.stdin.read())
safe_builtins = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "Exception": Exception, "float": float, "int": int,
    "len": len, "list": list, "max": max, "min": min, "range": range,
    "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "TypeError": TypeError, "ValueError": ValueError,
}
namespace = {}
exec(compile(payload["code"], "<controlled_python_skill>", "exec"), {"__builtins__": safe_builtins}, namespace)
run = namespace.get("run")
if not callable(run):
    raise RuntimeError("controlled_python 缺少 run(input, config, context)。")
result = run(payload.get("input") or {}, payload.get("config") or {}, payload.get("context") or {})
if not isinstance(result, dict):
    raise RuntimeError("controlled_python run() 必须返回 JSON 对象。")
print(json.dumps(result, ensure_ascii=False))
"""
    with tempfile.TemporaryDirectory(prefix="skill-python-") as tmp_dir:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", runner],
            input=json.dumps(wrapper, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            cwd=tmp_dir,
            env={"PYTHONIOENCODING": "utf-8"},
            check=False,
        )
    if proc.returncode != 0:
        error_text = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"controlled_python 执行失败：{error_text[:500]}")
    try:
        result = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("controlled_python 输出不是合法 JSON。") from exc
    if not isinstance(result, dict):
        raise RuntimeError("controlled_python 输出必须是 JSON 对象。")
    return result


def _run_local_mapping_skill(
    *,
    page_no: int,
    operation_type: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    config: dict[str, Any],
) -> PromptRunOutput | None:
    rules = _build_local_transform_rules(config, facts_payload)
    transform_objects = _collect_local_transform_objects(facts_payload)
    if not transform_objects:
        return None

    processed_objects: list[dict[str, Any]] = []
    changed_count = 0
    selected_fields = set(_as_config_string_list(config.get("fields")))
    for item in transform_objects:
        object_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or object_id or "处理对象").strip()
        kv_payload, kv_changes = _normalize_mapping_record(
            dict(item.get("kv") or {}),
            rules,
            selected_fields,
        )
        table_rows: list[dict[str, Any]] = []
        for row in item.get("table") or []:
            if not isinstance(row, dict):
                continue
            normalized_row, row_changes = _normalize_mapping_record(row, rules, selected_fields)
            table_rows.append(normalized_row)
            changed_count += row_changes
        changed_count += kv_changes
        payload = {"id": object_id, "label": label, "kv_data": kv_payload, "table_data": table_rows}
        processed_objects.append(payload)

    if not processed_objects:
        return None

    summary = (
        f"已按 {str(skill_meta.get('name') or '规范显示')} 处理 {len(processed_objects)} 个对象，"
        f"命中 {changed_count} 个转换值。"
    )
    output_payload = {"processed_objects": processed_objects}
    return _build_local_skill_output(
        page_no=page_no,
        operation_type=operation_type,
        result_kind="object",
        summary=summary,
        output_payload=output_payload,
        target=target,
        related_targets=related_targets,
        facts_payload=facts_payload,
        skill_meta=skill_meta,
        provider_model="business-skill-local-mapping",
    )


def _run_local_field_extract_skill(
    *,
    page_no: int,
    operation_type: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    config: dict[str, Any],
) -> PromptRunOutput | None:
    rows = _collect_rows_for_skill_config(facts_payload, config)
    if not rows:
        return None
    headers = _build_headers_for_skill_rows(rows, _as_config_string_list(config.get("fields")))
    normalized_rows = [
        {header: str(row.get(header) or "") for header in headers}
        for row in rows
        if any(str(row.get(header) or "").strip() for header in headers)
    ]
    if not normalized_rows:
        return None
    output_payload = {"headers": headers, "rows": normalized_rows}
    summary = f"已提取 {len(normalized_rows)} 行、{len(headers)} 个字段。"
    return _build_local_skill_output(
        page_no=page_no,
        operation_type=operation_type,
        result_kind="table",
        summary=summary,
        output_payload=output_payload,
        target=target,
        related_targets=related_targets,
        facts_payload=facts_payload,
        skill_meta=skill_meta,
        provider_model="business-skill-field-extract",
    )


def _run_local_export_table_skill(
    *,
    page_no: int,
    operation_type: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    config: dict[str, Any],
) -> PromptRunOutput | None:
    rows = _collect_rows_for_skill_config(facts_payload, config)
    if not rows:
        return None
    headers = _build_headers_for_skill_rows(rows, _as_config_string_list(config.get("fields")))
    output_payload = {
        "headers": headers,
        "rows": [{header: str(row.get(header) or "") for header in headers} for row in rows],
    }
    summary = f"已整理 {len(rows)} 行数据用于导出。"
    return _build_local_skill_output(
        page_no=page_no,
        operation_type=operation_type,
        result_kind="table",
        summary=summary,
        output_payload=output_payload,
        target=target,
        related_targets=related_targets,
        facts_payload=facts_payload,
        skill_meta=skill_meta,
        provider_model="business-skill-export-table",
    )


def _run_local_quality_check_skill(
    *,
    page_no: int,
    operation_type: str,
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    config: dict[str, Any],
) -> PromptRunOutput | None:
    rows = _collect_rows_for_skill_config(facts_payload, config)
    checks = set(_as_config_string_list(config.get("checks")))
    issues: list[dict[str, Any]] = []
    if "empty" in checks:
        for row_index, row in enumerate(rows, start=1):
            for key, value in row.items():
                if not str(value or "").strip():
                    issues.append(
                        {
                            "level": "待确认",
                            "title": f"{key} 为空",
                            "detail": f"第 {row_index} 条记录的 {key} 没有值。",
                            "suggestion": "建议核对原始识别结果或补充字段值。",
                        }
                    )
    if "duplicate" in checks:
        seen_values: dict[tuple[str, str], int] = {}
        for row in rows:
            for key, value in row.items():
                normalized = str(value or "").strip()
                if not normalized:
                    continue
                seen_values[(key, normalized)] = seen_values.get((key, normalized), 0) + 1
        for (key, value), count in seen_values.items():
            if count > 1:
                issues.append(
                    {
                        "level": "关注",
                        "title": f"{key} 存在重复值",
                        "detail": f"值「{value}」出现 {count} 次。",
                        "suggestion": "如需唯一值，请确认是否为同一业务项重复出现。",
                    }
                )
    summary = "未发现问题。" if not issues else f"发现 {len(issues)} 个问题。"
    output_payload = {
        "conclusion": summary,
        "checkedCount": len(rows),
        "issues": issues,
    }
    return _build_local_skill_output(
        page_no=page_no,
        operation_type=operation_type,
        result_kind="decision",
        summary=summary,
        output_payload=output_payload,
        target=target,
        related_targets=related_targets,
        facts_payload=facts_payload,
        skill_meta=skill_meta,
        provider_model="business-skill-quality-check",
    )


def _build_local_skill_output(
    *,
    page_no: int,
    operation_type: str,
    result_kind: str,
    summary: str,
    output_payload: dict[str, Any],
    target: dict[str, Any],
    related_targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
    skill_meta: dict[str, Any],
    provider_model: str,
) -> PromptRunOutput:
    evidence_refs = _collect_object_operation_evidence_refs([target, *related_targets], facts_payload)
    structured_process_result = {
        "summary": summary,
        "operationType": operation_type,
        "targetId": str(target.get("id") or ""),
        "relatedTargetIds": [
            str(item.get("id") or "").strip()
            for item in related_targets
            if str(item.get("id") or "").strip()
        ],
        "skillId": str(skill_meta.get("id") or ""),
        "skillVersion": str(skill_meta.get("version") or ""),
        "executor": str(skill_meta.get("executor") or ""),
        "renderer": str(skill_meta.get("renderer") or ""),
        "configSnapshot": dict(skill_meta.get("config") or {}),
        "resultKind": result_kind,
        "outputPayload": output_payload,
        "validationErrors": [],
        "evidenceRefs": evidence_refs,
        "source": "business_skill",
    }
    return PromptRunOutput(
        title=f"第 {page_no} 页业务处理",
        excerpt=summary,
        detail=json.dumps(output_payload, ensure_ascii=False),
        structuredExtractionResult=None,
        structuredProcessResult=structured_process_result,
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
        rawContent=json.dumps(structured_process_result, ensure_ascii=False),
        provider="local",
        model=provider_model,
        validationErrors=[],
        llmLogs={
            "mode": "business_skill_local",
            "skill": {
                "id": str(skill_meta.get("id") or ""),
                "version": str(skill_meta.get("version") or ""),
                "executor": str(skill_meta.get("executor") or ""),
            },
        },
    )


def _attach_skill_metadata_to_output(
    output: PromptRunOutput,
    skill_meta: dict[str, Any],
    *,
    application_meta: dict[str, Any] | None = None,
) -> PromptRunOutput:
    payload = output.structuredProcessResult
    if not isinstance(payload, dict):
        raise RuntimeError("Skill 输出缺少 structuredProcessResult。")
    expected_kind = str(skill_meta.get("resultKind") or "").strip()
    actual_kind = str(payload.get("resultKind") or "").strip()
    if expected_kind and not actual_kind:
        raise RuntimeError("Skill 输出缺少 resultKind。")
    if expected_kind and actual_kind and expected_kind != actual_kind:
        raise RuntimeError(f"Skill 输出类型不一致：预期 {expected_kind}，实际 {actual_kind}。")
    if actual_kind and not _skill_output_payload_matches_result_kind(actual_kind, payload.get("outputPayload")):
        raise RuntimeError(f"Skill 输出 payload 与 {actual_kind} 不匹配。")
    payload = {
        **payload,
        "executor": str(skill_meta.get("executor") or ""),
        "renderer": str(skill_meta.get("renderer") or ""),
        "configSnapshot": dict(skill_meta.get("config") or {}),
    }
    if application_meta:
        payload.update({
            "executionSource": "application_step",
            "sourceSkillId": str(skill_meta.get("id") or ""),
            "sourceSkillVersion": str(skill_meta.get("version") or ""),
            "sourceSkillName": str(skill_meta.get("name") or ""),
            "sourceApplicationId": str(application_meta.get("applicationId") or ""),
            "sourceApplicationVersion": str(application_meta.get("version") or ""),
            "sourceApplicationStepId": str(application_meta.get("sourceApplicationStepId") or ""),
        })
        payload.pop("skillId", None)
        payload.pop("skillVersion", None)
    else:
        payload.update({
            "executionSource": "skill_run",
            "skillId": str(skill_meta.get("id") or ""),
            "skillVersion": str(skill_meta.get("version") or ""),
        })
    return replace(output, structuredProcessResult=payload)


def _skill_output_payload_matches_result_kind(result_kind: str, payload: Any) -> bool:
    if result_kind == "text":
        return isinstance(payload, str)
    if result_kind in {"decision", "object"}:
        return isinstance(payload, dict)
    if result_kind == "table":
        if not isinstance(payload, dict):
            return False
        return isinstance(payload.get("headers"), list) and isinstance(payload.get("rows"), list)
    return False


def _build_mapping_instruction_from_config(config: dict[str, Any]) -> str:
    fields = _as_config_string_list(config.get("fields"))
    mapping_text = str(config.get("mappingRules") or "").strip()
    lines: list[str] = []
    if fields:
        lines.append("重点字段为" + "、".join(f"「{field}」" for field in fields) + "。")
    if mapping_text:
        lines.append("映射规则：")
        lines.append(mapping_text)
    return "\n".join(lines)


def _build_local_transform_rules(
    config: dict[str, Any],
    facts_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for rule in _extract_local_display_mapping_rules(
        _build_mapping_instruction_from_config(config),
        facts_payload,
    ):
        rules.append(
            {
                "type": "exact_mapping",
                "fields": [rule["field"]],
                "rawValue": rule["rawValue"],
                "displayValue": rule["displayValue"],
                "outputMode": "display",
            }
        )

    configured = config.get("transforms")
    if isinstance(configured, list):
        for item in configured:
            if isinstance(item, dict):
                normalized = dict(item)
                normalized["type"] = str(normalized.get("type") or "exact_mapping").strip()
                normalized["outputMode"] = str(normalized.get("outputMode") or "display").strip()
                rules.append(normalized)
    return rules


def _collect_rows_for_skill_config(
    facts_payload: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, str]]:
    selected_fields = set(_as_config_string_list(config.get("fields")))
    skip_empty = bool(config.get("skipEmpty", True))
    rows: list[dict[str, str]] = []
    field_row: dict[str, str] = {}

    for snapshot in _collect_operation_snapshots(facts_payload):
        snapshot_type = str(snapshot.get("type") or "")
        if snapshot_type == "field":
            label = str(snapshot.get("label") or snapshot.get("fieldKey") or "").strip()
            if not label or (selected_fields and label not in selected_fields):
                continue
            value = str(snapshot.get("valueText") or "").strip()
            if value or not skip_empty:
                field_row[label] = value
            continue

        data_rows = _collect_rows_from_operation_data(snapshot.get("data"), selected_fields, skip_empty)
        if data_rows:
            rows.extend(data_rows)
            continue

        structured_object = snapshot.get("structuredObject")
        if isinstance(structured_object, dict):
            kv = {
                str(key).strip(): str(value or "").strip()
                for key, value in dict(structured_object.get("kv") or {}).items()
                if str(key).strip()
            }
            kv_row = _filter_skill_row(kv, selected_fields, skip_empty)
            if kv_row:
                rows.append(kv_row)
            for row in structured_object.get("table") or []:
                if isinstance(row, dict):
                    filtered = _filter_skill_row(
                        {
                            str(key).strip(): str(value or "").strip()
                            for key, value in row.items()
                            if str(key).strip()
                        },
                        selected_fields,
                        skip_empty,
                    )
                    if filtered:
                        rows.append(filtered)
            continue

        parsed_table = snapshot.get("parsedTable")
        if isinstance(parsed_table, dict):
            headers = [str(item).strip() for item in (parsed_table.get("headers") or []) if str(item).strip()]
            for row in parsed_table.get("rows") or []:
                if not isinstance(row, list):
                    continue
                row_payload = {
                    header: str(row[index] if index < len(row) else "").strip()
                    for index, header in enumerate(headers)
                }
                filtered = _filter_skill_row(row_payload, selected_fields, skip_empty)
                if filtered:
                    rows.append(filtered)

    if field_row:
        rows.insert(0, field_row)
    return rows


def _collect_local_transform_objects(facts_payload: dict[str, Any]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for snapshot in _collect_structured_object_snapshots(facts_payload):
        structured_object = snapshot.get("structuredObject")
        if not isinstance(structured_object, dict):
            continue
        object_id = str(snapshot.get("id") or structured_object.get("id") or "").strip()
        if object_id and object_id in seen_ids:
            continue
        if object_id:
            seen_ids.add(object_id)
        objects.append(
            {
                "id": object_id or f"object-{len(objects) + 1}",
                "label": str(
                    snapshot.get("label")
                    or structured_object.get("title")
                    or object_id
                    or f"处理对象 {len(objects) + 1}"
                ).strip(),
                "kv": dict(structured_object.get("kv") or {}),
                "table": [
                    dict(row)
                    for row in (structured_object.get("table") or [])
                    if isinstance(row, dict)
                ],
            }
        )

    structured_source_ids = {
        str(item.get("id") or "").split(":", 1)[0]
        for item in objects
        if str(item.get("id") or "").strip()
    }
    for snapshot in _collect_operation_snapshots(facts_payload):
        snapshot_id = str(snapshot.get("id") or "").strip()
        if snapshot_id in seen_ids or snapshot_id in structured_source_ids:
            continue
        if snapshot.get("type") in {"structured_object", "record", "record_collection"}:
            continue

        kv: dict[str, Any] = {}
        table: list[dict[str, Any]] = []
        if snapshot.get("type") == "field":
            label = str(snapshot.get("label") or snapshot.get("fieldKey") or "").strip()
            if label:
                kv[label] = snapshot.get("valueText") or ""
        elif isinstance(snapshot.get("parsedTable"), dict):
            parsed_table = snapshot.get("parsedTable") or {}
            headers = [str(item).strip() for item in (parsed_table.get("headers") or []) if str(item).strip()]
            for row in parsed_table.get("rows") or []:
                if not isinstance(row, list):
                    continue
                table.append(
                    {
                        header: str(row[index] if index < len(row) else "").strip()
                        for index, header in enumerate(headers)
                    }
                )
        else:
            table.extend(_collect_rows_from_operation_data(snapshot.get("data"), set(), False))

        if not kv and not table:
            continue
        if snapshot_id:
            seen_ids.add(snapshot_id)
        objects.append(
            {
                "id": snapshot_id or f"object-{len(objects) + 1}",
                "label": str(snapshot.get("label") or f"处理对象 {len(objects) + 1}").strip(),
                "kv": kv,
                "table": table,
            }
        )

    return objects


def _collect_rows_from_operation_data(
    data: Any,
    selected_fields: set[str],
    skip_empty: bool,
) -> list[dict[str, str]]:
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, str]] = []

    records = data.get("records")
    if isinstance(records, list):
        for record in records:
            rows.extend(_collect_rows_from_record_data(record, selected_fields, skip_empty))
        return rows

    rows.extend(_collect_rows_from_record_data(data, selected_fields, skip_empty))
    if rows:
        return rows

    kv = data.get("kv")
    if isinstance(kv, dict):
        filtered = _filter_skill_row(
            {str(key).strip(): str(value or "").strip() for key, value in kv.items() if str(key).strip()},
            selected_fields,
            skip_empty,
        )
        if filtered:
            rows.append(filtered)

    table_rows = data.get("table")
    if isinstance(table_rows, list):
        for row in table_rows:
            if isinstance(row, dict):
                filtered = _filter_skill_row(
                    {str(key).strip(): str(value or "").strip() for key, value in row.items() if str(key).strip()},
                    selected_fields,
                    skip_empty,
                )
                if filtered:
                    rows.append(filtered)

    headers = [str(item).strip() for item in (data.get("headers") or []) if str(item).strip()]
    raw_rows = data.get("rows")
    if headers and isinstance(raw_rows, list):
        for row in raw_rows:
            if isinstance(row, list):
                row_payload = {
                    header: str(row[index] if index < len(row) else "").strip()
                    for index, header in enumerate(headers)
                }
            elif isinstance(row, dict):
                row_payload = {
                    header: str(row.get(header) or "").strip()
                    for header in headers
                }
            else:
                continue
            filtered = _filter_skill_row(row_payload, selected_fields, skip_empty)
            if filtered:
                rows.append(filtered)

    return rows


def _collect_rows_from_record_data(
    record: Any,
    selected_fields: set[str],
    skip_empty: bool,
) -> list[dict[str, str]]:
    if not isinstance(record, dict):
        return []
    base = {
        str(key).strip(): str(value or "").strip()
        for key, value in record.items()
        if str(key).strip() and key != "components" and not isinstance(value, (list, dict))
    }
    components = record.get("components")
    rows: list[dict[str, str]] = []
    if isinstance(components, list) and components:
        for component in components:
            if not isinstance(component, dict):
                continue
            row_payload = dict(base)
            row_payload.update(
                {
                    str(key).strip(): str(value or "").strip()
                    for key, value in component.items()
                    if str(key).strip()
                }
            )
            filtered = _filter_skill_row(row_payload, selected_fields, skip_empty)
            if filtered:
                rows.append(filtered)
    else:
        filtered = _filter_skill_row(base, selected_fields, skip_empty)
        if filtered:
            rows.append(filtered)
    return rows


def _filter_skill_row(
    row: dict[str, str],
    selected_fields: set[str],
    skip_empty: bool,
) -> dict[str, str]:
    filtered = {
        key: value
        for key, value in row.items()
        if (not selected_fields or key in selected_fields) and (value or not skip_empty)
    }
    return filtered


def _build_headers_for_skill_rows(rows: list[dict[str, str]], selected_fields: list[str]) -> list[str]:
    if selected_fields:
        headers = [field for field in selected_fields if any(field in row for row in rows)]
        if headers:
            return headers
    values: list[str] = []
    for row in rows:
        values.extend(row.keys())
    return _unique_text_values(values)


def _as_config_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、\n]", value) if item.strip()]
    return []


def _extract_local_display_mapping_rules(
    instruction: str,
    facts_payload: dict[str, Any],
) -> list[dict[str, str]]:
    if "映射规则" not in instruction:
        return []
    field_names = _collect_operation_field_names(facts_payload)
    focus_fields = _extract_focus_field_names(instruction)
    lines = _extract_mapping_rule_lines(instruction)
    rules: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        left, right = _split_mapping_rule_line(line)
        if not left or not right:
            continue
        field_name, raw_value = _match_mapping_rule_left_side(left, field_names)
        if not field_name and len(focus_fields) == 1:
            field_name = focus_fields[0]
            raw_value = left
        if not field_name or not raw_value:
            continue
        key = (field_name, raw_value, right)
        if key in seen:
            continue
        seen.add(key)
        rules.append(
            {
                "field": field_name,
                "rawValue": raw_value,
                "displayValue": right,
            }
        )
    return rules


def _extract_mapping_rule_lines(instruction: str) -> list[str]:
    _, _, tail = instruction.partition("映射规则")
    tail = tail.lstrip("：:\n ")
    stop_markers = ["补充要求：", "补充要求:"]
    for marker in stop_markers:
        if marker in tail:
            tail = tail.split(marker, 1)[0]
    return [
        re.sub(r"^[\-*•\d.、\s]+", "", line).strip()
        for line in tail.splitlines()
        if line.strip()
    ]


def _split_mapping_rule_line(line: str) -> tuple[str, str]:
    for separator in ["改为", "=>", "->", "→"]:
        if separator in line:
            left, right = line.split(separator, 1)
            return _clean_mapping_token(left), _clean_mapping_token(right)
    return "", ""


def _clean_mapping_token(value: str) -> str:
    return str(value or "").strip().strip("：:，,。；;\"'“”‘’ ")


def _match_mapping_rule_left_side(
    left: str,
    field_names: list[str],
) -> tuple[str, str]:
    normalized_left = _clean_mapping_token(left)
    for field_name in sorted(field_names, key=len, reverse=True):
        if not normalized_left.startswith(field_name):
            continue
        raw_value = _clean_mapping_token(normalized_left[len(field_name):])
        raw_value = re.sub(r"^(如果)?是", "", raw_value).strip()
        raw_value = re.sub(r"就$", "", raw_value).strip()
        raw_value = re.sub(r"^[=：:\s]+", "", raw_value).strip()
        if raw_value:
            return field_name, raw_value
    return "", ""


def _extract_focus_field_names(instruction: str) -> list[str]:
    match = re.search(r"重点字段为([^。\n]+)", instruction)
    if not match:
        return []
    return [
        str(item).strip()
        for item in re.findall(r"「([^」]+)」", match.group(1))
        if str(item).strip()
    ]


def _collect_operation_field_names(facts_payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for snapshot in _collect_operation_snapshots(facts_payload):
        values.extend(str(item).strip() for item in (snapshot.get("headers") or []) if str(item).strip())
        for row in _collect_rows_from_operation_data(snapshot.get("data"), set(), False):
            values.extend(str(key).strip() for key in row.keys() if str(key).strip())
        structured_object = snapshot.get("structuredObject")
        if not isinstance(structured_object, dict):
            continue
        values.extend(str(key).strip() for key in (structured_object.get("kv") or {}).keys() if str(key).strip())
        for row in structured_object.get("table") or []:
            if isinstance(row, dict):
                values.extend(str(key).strip() for key in row.keys() if str(key).strip())
    return _unique_text_values(values)


def _collect_structured_object_snapshots(facts_payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for snapshot in _collect_operation_snapshots(facts_payload):
        if snapshot.get("type") == "structured_object" and isinstance(snapshot.get("structuredObject"), dict):
            snapshot_id = str(snapshot.get("id") or snapshot.get("structuredObject", {}).get("id") or "").strip()
            if snapshot_id and snapshot_id in seen_ids:
                continue
            if snapshot_id:
                seen_ids.add(snapshot_id)
            snapshots.append(snapshot)
            continue

        data = snapshot.get("data")
        if not isinstance(data, dict):
            continue
        records = data.get("records")
        if isinstance(records, list):
            for record_index, record in enumerate(records):
                converted = _record_data_to_structured_snapshot(snapshot, record, record_index)
                snapshot_id = str(converted.get("id") or "").strip()
                if snapshot_id and snapshot_id in seen_ids:
                    continue
                if snapshot_id:
                    seen_ids.add(snapshot_id)
                snapshots.append(converted)
            continue
        if snapshot.get("type") == "record":
            converted = _record_data_to_structured_snapshot(snapshot, data, 0)
            snapshot_id = str(converted.get("id") or "").strip()
            if snapshot_id and snapshot_id in seen_ids:
                continue
            if snapshot_id:
                seen_ids.add(snapshot_id)
            snapshots.append(converted)
    return snapshots


def _record_data_to_structured_snapshot(
    snapshot: dict[str, Any],
    record: Any,
    record_index: int,
) -> dict[str, Any]:
    record_payload = record if isinstance(record, dict) else {}
    kv = {
        str(key).strip(): value
        for key, value in record_payload.items()
        if str(key).strip() and key != "components" and not isinstance(value, (list, dict))
    }
    components = [
        dict(item)
        for item in (record_payload.get("components") or [])
        if isinstance(item, dict)
    ]
    label = str(
        record_payload.get("调色号")
        or record_payload.get("name")
        or record_payload.get("title")
        or snapshot.get("label")
        or f"记录 {record_index + 1}"
    ).strip()
    object_id = f"{snapshot.get('id') or 'record'}:{record_index}"
    return {
        **snapshot,
        "id": object_id,
        "label": label,
        "type": "structured_object",
        "structuredObject": {
            "id": object_id,
            "title": label,
            "type": "kv_record_table",
            "kv": kv,
            "table": components,
            "parserMeta": {},
        },
    }


def _collect_operation_snapshots(facts_payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    target = facts_payload.get("target")
    if isinstance(target, dict):
        snapshots.append(target)
    related_targets = facts_payload.get("relatedTargets")
    if isinstance(related_targets, list):
        snapshots.extend(item for item in related_targets if isinstance(item, dict))
    return snapshots


def _normalize_mapping_record(
    row: dict[str, Any],
    rules: list[dict[str, Any]],
    selected_fields: set[str] | None = None,
) -> tuple[dict[str, Any], int]:
    normalized: dict[str, Any] = {}
    changed_count = 0
    selected_fields = selected_fields or set()
    for key, value in row.items():
        field_name = str(key).strip()
        raw_value = str(value if value is not None else "").strip()
        display_value, extra_values = _apply_local_transform_rules(field_name, raw_value, rules, selected_fields)
        if display_value != raw_value:
            changed_count += 1
        normalized[field_name] = {
            "rawValue": raw_value,
            "displayValue": display_value,
            "normalizedValue": display_value,
        }
        for extra_field, extra_value in extra_values:
            if extra_field in normalized:
                continue
            normalized[extra_field] = {
                "rawValue": raw_value,
                "displayValue": extra_value,
                "normalizedValue": extra_value,
            }
            if extra_value != raw_value:
                changed_count += 1
    return normalized, changed_count


def _apply_local_transform_rules(
    field_name: str,
    raw_value: str,
    rules: list[dict[str, Any]],
    selected_fields: set[str],
) -> tuple[str, list[tuple[str, str]]]:
    display_value = raw_value
    extra_values: list[tuple[str, str]] = []
    for rule in rules:
        if not _local_transform_rule_matches_field(rule, field_name, selected_fields):
            continue
        next_value = _apply_single_local_transform(display_value, rule)
        output_mode = str(rule.get("outputMode") or "display").strip()
        target_field = str(rule.get("targetField") or rule.get("outputField") or "").strip()
        if output_mode == "new_field" and target_field:
            extra_values.append((target_field, next_value))
            continue
        display_value = next_value
    return display_value, extra_values


def _local_transform_rule_matches_field(
    rule: dict[str, Any],
    field_name: str,
    selected_fields: set[str],
) -> bool:
    fields = _as_config_string_list(rule.get("fields") or rule.get("field"))
    if selected_fields and field_name not in selected_fields:
        return False
    return not fields or field_name in fields


def _apply_single_local_transform(value: str, rule: dict[str, Any]) -> str:
    rule_type = str(rule.get("type") or "exact_mapping").strip()
    if rule_type in {"exact_mapping", "mapping"}:
        raw_value = str(rule.get("rawValue") or rule.get("from") or rule.get("fromValue") or "").strip()
        if raw_value and value == raw_value:
            return str(rule.get("displayValue") or rule.get("to") or rule.get("toValue") or "").strip()
        mappings = rule.get("mappings") or rule.get("map")
        if isinstance(mappings, dict) and value in mappings:
            return str(mappings[value]).strip()
        return value
    if rule_type in {"dictionary", "dict_mapping"}:
        mappings = rule.get("mappings") or rule.get("map") or rule.get("dictionary")
        if isinstance(mappings, dict) and value in mappings:
            return str(mappings[value]).strip()
        return value
    if rule_type == "regex_replace":
        pattern = str(rule.get("pattern") or "").strip()
        if not pattern:
            return value
        replacement = _normalize_regex_replacement(str(rule.get("replacement") or ""))
        try:
            return re.sub(pattern, replacement, value)
        except re.error as exc:
            raise RuntimeError(f"正则转换规则无效：{exc}") from exc
    if rule_type in {"trim", "strip"}:
        return value.strip()
    if rule_type == "upper":
        return value.upper()
    if rule_type == "lower":
        return value.lower()
    if rule_type == "remove_chars":
        chars = str(rule.get("chars") or "").strip()
        return value.translate({ord(char): None for char in chars}) if chars else value
    if rule_type == "replace":
        old = str(rule.get("old") or rule.get("from") or "")
        new = str(rule.get("new") or rule.get("to") or "")
        return value.replace(old, new) if old else value
    raise RuntimeError(f"local_transform 不支持的转换规则类型：{rule_type}。")


def _normalize_regex_replacement(value: str) -> str:
    return re.sub(r"\$(\d+)", r"\\\1", value)


def _collect_object_operation_evidence_refs(
    targets: list[dict[str, Any]],
    facts_payload: dict[str, Any],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for snapshot in _collect_operation_snapshots(facts_payload):
        for block in snapshot.get("matchedBlocks") or []:
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("id") or "").strip()
            if not block_id or block_id in seen:
                continue
            seen.add(block_id)
            refs.append(
                {
                    "pageNo": str(block.get("pageNo") or ""),
                    "blockId": block_id,
                    "excerpt": str(block.get("excerpt") or "").strip(),
                }
            )
    if refs:
        return refs
    for item in targets:
        for block_id in item.get("blockIds") or []:
            block_id_text = str(block_id or "").strip()
            if not block_id_text or block_id_text in seen:
                continue
            seen.add(block_id_text)
            refs.append(
                {
                    "pageNo": str(item.get("pageNo") or ""),
                    "blockId": block_id_text,
                    "excerpt": str(item.get("excerpt") or "").strip(),
                }
            )
    return refs


def _unique_text_values(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _extract_table_target_index(target_id: str) -> int:
    match = re.search(r"table:\d+:(\d+)$", str(target_id or "").strip())
    if not match:
        return -1
    try:
        return int(match.group(1))
    except ValueError:
        return -1


def _extract_structured_object_target_index(target_id: str) -> int:
    match = re.search(r"structured-object:\d+:(\d+)$", str(target_id or "").strip())
    if not match:
        return -1
    try:
        return int(match.group(1))
    except ValueError:
        return -1


def _build_compact_matched_blocks(
    *,
    item: OperationTargetRef,
    block_lookup: dict[str, WorkbenchBlock],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block_id in item.blockIds[:2]:
        block = block_lookup.get(block_id)
        if block is None:
            continue
        excerpt = str(item.excerpt or block.title or block.content or "").strip()
        blocks.append(
            {
                "id": block.id,
                "pageNo": block.pageNo,
                "blockPosition": block.blockPosition,
                "type": block.type,
                "title": block.title,
                "excerpt": excerpt[:200],
            }
        )
    return blocks


def _build_compact_extraction_overview(latest_extraction: Any) -> dict[str, Any] | None:
    if not isinstance(latest_extraction, dict):
        return None
    outputs = latest_extraction.get("outputs")
    if isinstance(outputs, list):
        return {
            "summary": str(latest_extraction.get("summary") or ""),
            "outputCount": len(outputs),
            "outputs": [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or ""),
                    "type": str(item.get("type") or ""),
                    "renderer": str(item.get("renderer") or ""),
                }
                for item in outputs
                if isinstance(item, dict)
            ],
            "errors": [
                str(item).strip()
                for item in (latest_extraction.get("errors") or [])
                if str(item).strip()
            ][:20],
        }
    fields = latest_extraction.get("fields")
    tables = latest_extraction.get("tables")
    structured_objects = latest_extraction.get("structuredObjects")
    validation_errors = latest_extraction.get("validationErrors")
    return {
        "summary": str(latest_extraction.get("summary") or ""),
        "fieldCount": len(fields) if isinstance(fields, list) else 0,
        "tableCount": len(tables) if isinstance(tables, list) else 0,
        "structuredObjectCount": len(structured_objects) if isinstance(structured_objects, list) else 0,
        "validationErrors": [
            str(item).strip()
            for item in (validation_errors or [])
            if str(item).strip()
        ][:20],
    }


def _row_looks_like_business_data(cells: list[str]) -> bool:
    if not cells:
        return False
    first_cell = str(cells[0]).strip()
    if re.fullmatch(r"\d+", first_cell):
        return True

    numeric_like_count = sum(1 for cell in cells if re.search(r"\d", str(cell)))
    return numeric_like_count >= max(2, len(cells) // 2)
