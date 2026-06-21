"""Normalize extraction output and decide completion status."""

from __future__ import annotations

from typing import Any

from app.services.extraction_runtime.models import (
    ExtractionRuntimePorts,
    ExtractionRuntimePrepared,
    ExtractionRuntimeRequest,
)


def normalize_and_validate_output(
    *,
    request: ExtractionRuntimeRequest,
    prepared: ExtractionRuntimePrepared,
    ports: ExtractionRuntimePorts,
    output: Any,
    raw_payload: dict[str, Any],
    duration_ms: int,
    execution_metrics: dict[str, Any],
) -> dict[str, Any]:
    metrics = {
        **prepared.metrics,
        "reviewCount": int(execution_metrics.get("reviewCount") or 0),
        "tableFastPath": bool(execution_metrics.get("usedTableFastPath")),
        "reviewFactsBytes": ports.estimate_json_payload_bytes(execution_metrics.get("reviewFactsPayload"))
        if int(execution_metrics.get("reviewCount") or 0)
        else 0,
        "modelCallMs": int(execution_metrics.get("modelCallMs") or 0),
        "reviewCallMs": int(execution_metrics.get("reviewCallMs") or 0),
        "localStructuredBuildMs": int(execution_metrics.get("localStructuredBuildMs") or 0),
        "fastPathPreviewMs": int((execution_metrics.get("fastPathMetrics") or {}).get("fastPathPreviewMs") or 0),
        "evidenceSelection": prepared.evidence_selection,
        "reviewEvidenceSelection": execution_metrics.get("reviewEvidenceSelection")
        if int(execution_metrics.get("reviewCount") or 0)
        else {},
        "tableReviewRisk": prepared.table_review_risk,
        "sourceMode": request.source_mode,
        "kernelVersion": "extraction_runtime_kernel_v1",
    }
    run_meta = ports.build_run_meta(
        skill_meta=prepared.skill_meta,
        config=prepared.config,
        output=output,
        duration_ms=duration_ms,
        input_payload={
            "skill": ports.skill_payload_for_llm(prepared.skill_meta),
            "config": prepared.config,
            "applicationScope": prepared.application_scope,
            "runtimeContract": prepared.runtime_contract,
            "facts": prepared.model_facts_payload,
            "evidenceSelection": prepared.evidence_selection,
            "sourceMode": request.source_mode,
        },
        raw_payload=raw_payload,
        metrics=metrics,
    )
    extraction_result = ports.normalize_output(
        raw_payload=raw_payload,
        skill_meta=prepared.skill_meta,
        run_meta=run_meta,
    )
    extraction_result = ports.enrich_result_from_application_scope(
        extraction_result,
        schema_definition=request.schema_definition,
    )
    errors = [
        str(item).strip()
        for item in extraction_result.get("errors", [])
        if str(item).strip()
    ]
    warnings = [
        str(item).strip()
        for item in extraction_result.get("validationWarnings", [])
        if str(item).strip()
    ]
    output_schema = prepared.skill_meta.get("outputSchema") if isinstance(prepared.skill_meta.get("outputSchema"), dict) else {}
    output_type = str(output_schema.get("type") or "").strip()
    for error in prepared.evidence_selection.get("validationErrors") or []:
        text = str(error or "").strip()
        if text and text not in errors:
            errors.append(text)
    if (
        output_type == "record_collection"
        and not bool(execution_metrics.get("usedTableFastPath"))
        and prepared.evidence_selection.get("mode") in {"record_collection_selected_evidence", "evidence_v2_model_input"}
        and int(prepared.evidence_selection.get("selectedTableRowCount") or 0) > 0
        and int(prepared.evidence_selection.get("selectedTableRowCount") or 0)
        < int(prepared.evidence_selection.get("totalTableRowCount") or 0)
    ):
        errors.append(
            "记录集合只选中了目标表格的部分行窗口，未生成全量记录。请复核："
            "1. 当前选中的表格是否就是本次定位目标；"
            "2. 表头/列含义是否正确；"
            "3. 若确认无误，请基于该列映射重新生成完整记录。"
        )
    for error in prepared.table_review_risk.get("validationErrors") or []:
        text = str(error or "").strip()
        if text and text not in errors:
            errors.append(text)
    for warning in prepared.table_review_risk.get("warnings") or []:
        text = str(warning or "").strip()
        if text and text not in warnings:
            warnings.append(text)
    if errors:
        extraction_result["errors"] = errors
        extraction_result["validationErrors"] = errors
    if warnings:
        extraction_result["validationWarnings"] = warnings
    return {
        "metrics": metrics,
        "runMeta": run_meta,
        "extractionResult": extraction_result,
        "errors": errors,
        "completionStatus": ports.completion_status_from_errors(errors),
    }
