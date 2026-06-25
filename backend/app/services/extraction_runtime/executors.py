# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Executors for local structured paths, LLM calls, and review passes."""

from __future__ import annotations

from dataclasses import replace
import time
from typing import Any

from app.services.extraction_runtime.models import (
    ExtractionRuntimePorts,
    ExtractionRuntimePrepared,
    ExtractionRuntimeRequest,
    page_range_label,
)


def execute_model_or_local_path(
    *,
    request: ExtractionRuntimeRequest,
    prepared: ExtractionRuntimePrepared,
    ports: ExtractionRuntimePorts,
) -> dict[str, Any]:
    model_call_started = time.perf_counter()
    fast_path_output = ports.try_table_fast_path(request, prepared)
    used_table_fast_path = fast_path_output is not None
    fast_path_metrics = (
        fast_path_output.llmLogs.get("metrics")
        if fast_path_output is not None and isinstance(fast_path_output.llmLogs, dict)
        else {}
    )
    if fast_path_output is not None:
        output = fast_path_output
        model_call_ms = int(fast_path_metrics.get("fastPathPreviewMs") or 0)
        local_structured_build_ms = int(fast_path_metrics.get("localStructuredBuildMs") or 0)
    else:
        output = ports.run_llm_extraction(
            taskId=request.run.taskId,
            pageRange=page_range_label(request, ports),
            skill=ports.skill_payload_for_llm(prepared.skill_meta),
            config=prepared.config,
            factsPayload=prepared.model_facts_payload,
            applicationScope=prepared.application_scope,
        )
        model_call_ms = int((time.perf_counter() - model_call_started) * 1000)
        local_structured_build_ms = 0

    raw_payload = output.structuredExtractionResult
    if not isinstance(raw_payload, dict):
        raise RuntimeError("解析 skill 未返回 JSON 对象。")

    review_call_ms = 0
    review_started = time.perf_counter()
    review_output = ports.review_field_list(request, prepared, raw_payload, output)
    review_call_ms = int((time.perf_counter() - review_started) * 1000) if review_output is not None else 0
    repaired_model_payload: dict[str, Any] | None = None
    review_count = 0
    review_facts_payload = prepared.review_facts_payload
    review_evidence_selection = prepared.review_evidence_selection
    if review_output is not None:
        review_output, review_facts_payload, review_evidence_selection = review_output
        review_count = 1
        previous_model_payload = raw_payload
        repaired_model_payload = previous_model_payload
        output = review_output
        raw_payload = output.structuredExtractionResult
        if not isinstance(raw_payload, dict):
            raise RuntimeError("解析 skill 复核未返回 JSON 对象。")
        raw_payload = ports.preserve_review_source_pages(
            raw_payload=raw_payload,
            previous_payload=previous_model_payload,
        )
        output = replace(output, structuredExtractionResult=raw_payload)

    return {
        "output": output,
        "rawPayload": raw_payload,
        "reviewFactsPayload": review_facts_payload,
        "reviewEvidenceSelection": review_evidence_selection,
        "reviewCount": review_count,
        "reviewCallMs": review_call_ms,
        "repairedModelPayload": repaired_model_payload,
        "usedTableFastPath": used_table_fast_path,
        "fastPathMetrics": fast_path_metrics,
        "modelCallMs": model_call_ms,
        "localStructuredBuildMs": local_structured_build_ms,
    }
