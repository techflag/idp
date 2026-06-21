"""Helpers for building workbench DTOs from parsed artifacts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any, Optional

from app.domain.models import LlmCallTraceRecord, PromptConfigRecord, PromptRunRecord
from app.schemas.workbench import (
    ExtractionFieldItem,
    ExtractionResult,
    ExtractionStructuredObjectItem,
    ExtractionTableItem,
    LlmCallTraceSummary,
    ObjectOperationResult,
    OperationTargetRef,
    PageResultDetail,
    PageResultPromptTrace,
    PageResultSummary,
    PromptTraceItem,
    SchemaProcessResult,
    SummaryResultItem,
    TaskRuntimeInfo,
    TaskSummary,
    WorkbenchBlock,
    WorkbenchDocument,
    WorkbenchEvidenceRef,
    WorkbenchPageDetail,
    WorkbenchMarkdownSegment,
    WorkbenchTaskDetail,
)
from app.services.extraction_result import (
    custom_result_has_table_payload,
    extract_field_items_from_custom_result,
    is_field_only_custom_result,
    merge_field_items,
    normalize_custom_result_value,
    normalize_field_items,
)
from app.services.extraction_result_compat import repair_legacy_extraction_result_tables


@dataclass(frozen=True)
class _StructuredField:
    label: str
    value: str


@dataclass(frozen=True)
class _StructuredExtraction:
    summary: str
    fields: list[_StructuredField]
    tablePayload: Any | None


def build_task_detail(
    *,
    task: TaskSummary,
    document: WorkbenchDocument,
    parseStatus: str,
    pages: list[WorkbenchPageDetail],
    promptConfigs: list[PromptConfigRecord] | None = None,
    promptRuns: list[PromptRunRecord] | None = None,
) -> WorkbenchTaskDetail:
    prompt_configs = promptConfigs or []
    prompt_runs = promptRuns or []
    bound_pages = _apply_prompt_configs(pages, prompt_configs)
    page_results = _build_page_results(bound_pages, prompt_runs)
    object_operation_results = _build_latest_object_operation_results(prompt_runs)
    summary_results = _build_summary_results(prompt_runs)
    runtime = _build_runtime_info(parseStatus, prompt_runs)

    if not prompt_runs:
        latest_run_label = {
            "pending": "等待触发文档解析",
            "running": "文档解析中",
            "completed": "解析结果已保存",
            "failed": "文档解析失败",
        }.get(parseStatus, "识别状态未知")
        runtime.latestRunLabel = latest_run_label

    return WorkbenchTaskDetail(
        task=task,
        document=document,
        runtime=runtime,
        pages=bound_pages,
        pageResults=page_results,
        objectOperationResults=object_operation_results,
        summaryResults=summary_results,
    )


def _build_latest_object_operation_results(promptRuns: list[PromptRunRecord]) -> list[ObjectOperationResult]:
    results_by_scope: dict[tuple[int, str], ObjectOperationResult] = {}
    for run in sorted(promptRuns, key=lambda item: item.updatedAt, reverse=True):
        if run.runPurpose != "post_process" or run.status not in {"completed", "needs_review"}:
            continue
        result = build_object_operation_result(run)
        if result is None:
            continue
        scope_key = (result.pageNo, result.targetId)
        if scope_key in results_by_scope:
            continue
        results_by_scope[scope_key] = result
    return list(results_by_scope.values())


def _build_runtime_info(parseStatus: str, promptRuns: list[PromptRunRecord]) -> TaskRuntimeInfo:
    latest_run = max(promptRuns, key=lambda item: item.updatedAt, default=None)
    page_runs = _get_latest_effective_runs([item for item in promptRuns if item.runType != "summary"])
    summary_runs = _get_latest_effective_runs([item for item in promptRuns if item.runType == "summary"])

    latest_run_label = {
        "pending": "等待触发文档解析",
        "running": "文档解析中",
        "completed": "解析结果已保存",
        "failed": "文档解析失败",
    }.get(parseStatus, "识别状态未知")

    if latest_run:
        scope_label = _format_page_range(latest_run.startPageNo, latest_run.endPageNo)
        latest_run_label = f"{latest_run.promptName} {scope_label} { _format_runtime_status_label(latest_run.status) }"

    return TaskRuntimeInfo(
        parseStatus=_normalize_task_status(parseStatus),
        pagePromptStatus=_aggregate_run_status(page_runs),
        summaryStatus=_aggregate_run_status(summary_runs),
        latestRunLabel=latest_run_label,
        failedPageCount=sum(1 for item in page_runs if item.status == "failed"),
        completedPageCount=sum(1 for item in page_runs if item.status == "completed"),
        latestPromptRunAt=latest_run.updatedAt if latest_run else None,
    )


def _apply_prompt_configs(
    pages: list[WorkbenchPageDetail],
    promptConfigs: list[PromptConfigRecord],
) -> list[WorkbenchPageDetail]:
    if not promptConfigs:
        return pages

    sorted_configs = sorted(promptConfigs, key=lambda item: item.updatedAt)
    bound_pages: list[WorkbenchPageDetail] = []
    for page in pages:
        selected = None
        for config in sorted_configs:
            if config.startPageNo <= page.pageNo <= config.endPageNo:
                selected = config
        if not selected:
            bound_pages.append(page)
            continue

        bound_pages.append(
            page.model_copy(
                update={
                    "prompt": selected.promptText,
                    "promptStatus": "submitted",
                    "promptName": selected.promptName,
                    "promptStartPageNo": selected.startPageNo,
                    "promptEndPageNo": selected.endPageNo,
                    "promptTemplateId": selected.sourceTemplateId,
                }
            )
        )
    return bound_pages


def _build_page_results(pages: list[WorkbenchPageDetail], promptRuns: list[PromptRunRecord]) -> list[PageResultSummary]:
    page_lookup = {page.pageNo: page for page in pages}
    page_results: list[PageResultSummary] = []
    sorted_runs = sorted(
        [item for item in promptRuns if item.runType != "summary"],
        key=lambda item: item.updatedAt,
        reverse=True,
    )
    for run in sorted_runs:
        anchor_page = page_lookup.get(run.startPageNo)
        page_results.append(_build_page_result_summary(run, anchor_page))
    return page_results


def _build_summary_results(promptRuns: list[PromptRunRecord]) -> list[SummaryResultItem]:
    summary_runs = sorted(
        [item for item in promptRuns if item.runType == "summary"],
        key=lambda item: item.updatedAt,
        reverse=True,
    )
    return [
        SummaryResultItem(
            id=run.id,
            title=run.promptName,
            status=_normalize_result_status(run.status),
            runName=run.runName,
            detail=str(run.outputText or ""),
            pageRange=_format_page_range(run.startPageNo, run.endPageNo),
            errorMessage=run.errorMessage,
            updatedAt=run.updatedAt,
        )
        for run in summary_runs
    ]


def _build_page_result_summary(
    run: PromptRunRecord,
    anchor_page: WorkbenchPageDetail | None,
) -> PageResultSummary:
    prompt_trace = _build_prompt_trace(run.promptText) if run.runPurpose not in {"schema_process", "post_process"} else None
    return PageResultSummary(
        id=run.id,
        title=run.runName,
        pageNo=run.startPageNo,
        pageIndex=(anchor_page.pageIndex if anchor_page else max(run.startPageNo - 1, 0)),
        status=_normalize_result_status(run.status),
        runPhase=_normalize_run_phase(run),
        phaseStartedAt=run.phaseStartedAt,
        lastHeartbeatAt=run.lastHeartbeatAt,
        resultStage=_infer_result_stage(run),
        runPurpose=run.runPurpose,  # type: ignore[arg-type]
        promptName=run.promptName,
        runType=run.runType,
        startPageNo=run.startPageNo,
        endPageNo=run.endPageNo,
        pageRange=_format_page_range(run.startPageNo, run.endPageNo),
        errorMessage=run.errorMessage,
        schemaTemplateId=run.templateId,
        schemaTemplateName=run.schemaTemplateName,
        schemaTemplateVersion=run.schemaTemplateVersion,
        evidenceRefs=_build_evidence_refs(run),
        promptTrace=prompt_trace,
        sourceSections=_build_source_sections(prompt_trace),
    )


def build_page_result_detail(
    pages: list[WorkbenchPageDetail],
    run: PromptRunRecord,
) -> PageResultDetail:
    page_lookup = {page.pageNo: page for page in pages}
    anchor_page = page_lookup.get(run.startPageNo)
    run_pages = [
        page
        for page_no, page in page_lookup.items()
        if run.startPageNo <= page_no <= run.endPageNo
    ]
    structured_extraction = _build_structured_extraction_result(run)
    prompt_trace = _build_prompt_trace(run.promptText) if run.runPurpose not in {"schema_process", "post_process"} else None
    extraction_result = _build_extraction_result(structured_extraction, run_pages, run)
    schema_process_result = _build_schema_process_result(run)
    summary = _build_page_result_summary(run, anchor_page)
    return PageResultDetail(
        **summary.model_dump(exclude={"promptTrace", "evidenceRefs"}),
        promptTrace=prompt_trace,
        extractionResult=extraction_result,
        outputText=run.outputText,
        schemaProcessResult=schema_process_result,
        schemaOutput=run.schemaOutput,
        evidenceRefs=_build_evidence_refs(run),
        validationErrors=list(run.validationErrors or []),
    )


def build_page_operation_targets(
    *,
    page: WorkbenchPageDetail,
    parse_run: PromptRunRecord | None,
) -> list[OperationTargetRef]:
    extraction = _build_structured_extraction_result(parse_run) if parse_run else None
    extraction_result = _build_extraction_result(extraction, [page], parse_run) if parse_run else None
    if not extraction_result:
        return []

    if extraction_result.outputs:
        return _build_operation_targets_from_outputs(page=page, outputs=extraction_result.outputs)

    targets: list[OperationTargetRef] = []
    for index, field in enumerate(extraction_result.fields):
        block_ids = [ref.blockId for ref in field.evidenceRefs if ref.blockId]
        excerpt = _resolve_target_excerpt(page.blocks, block_ids, fallback=f"{field.label}: {field.value}")
        targets.append(
            OperationTargetRef(
                id=f"field:{page.pageNo}:{index}",
                pageNo=page.pageNo,
                type="field",
                label=field.label,
                valueText=field.value,
                excerpt=excerpt,
                blockIds=block_ids,
                blockPosition=_resolve_target_block_position(page.blocks, block_ids),
                fieldKey=_slugify_label(field.label),
                groupLabel="字段",
            )
        )

    for object_index, structured_object in enumerate(extraction_result.structuredObjects):
        detail_headers = _collect_structured_object_headers(structured_object.table)
        headers = _unique_strings([*structured_object.kv.keys(), *detail_headers])
        block_ids = [ref.blockId for ref in structured_object.evidenceRefs if ref.blockId]
        title = structured_object.title or f"复合表对象 {object_index + 1}"
        fallback_excerpt = " | ".join(headers[:8]) or title
        excerpt = _resolve_target_excerpt(page.blocks, block_ids, fallback=fallback_excerpt)
        summary_parts = [f"{len(structured_object.kv)} 项 KV", f"{len(structured_object.table)} 行明细"]
        if detail_headers:
            summary_parts.append(f"表头：{' | '.join(detail_headers[:4])}")
        targets.append(
            OperationTargetRef(
                id=f"structured-object:{page.pageNo}:{object_index}",
                pageNo=page.pageNo,
                type="structured_object",
                label=title,
                valueText="，".join(summary_parts),
                excerpt=excerpt,
                blockIds=block_ids,
                blockPosition=_resolve_target_block_position(page.blocks, block_ids),
                rowCount=len(structured_object.table),
                columnCount=len(headers) or None,
                headers=headers,
                groupLabel="复合表",
            )
        )

    # Parser keeps the raw 2D table for debugging; when every raw table has a richer composite view,
    # object-operation targets should expose only the composite objects.
    skip_structured_raw_tables = (
        bool(extraction_result.structuredObjects)
        and len(extraction_result.tables) == len(extraction_result.structuredObjects)
    )
    for table_index, table in enumerate(extraction_result.tables):
        if skip_structured_raw_tables:
            continue
        headers = list(table.headers)
        rows = list(table.rows)
        title = table.title or f"第 {table_index + 1} 张表"
        block_ids = [ref.blockId for ref in table.evidenceRefs if ref.blockId]
        fallback_excerpt = " | ".join(headers[:8]) if headers else title
        excerpt = _resolve_target_excerpt(page.blocks, block_ids, fallback=fallback_excerpt)
        column_count = max((len(row) for row in rows), default=0)
        if headers:
            column_count = max(column_count, len(headers))
        row_count = len(rows)
        summary_parts = [f"{row_count} 行"]
        if column_count:
            summary_parts.append(f"{column_count} 列")
        if headers:
            summary_parts.append(f"表头：{' | '.join(headers[:4])}")
        targets.append(
            OperationTargetRef(
                id=f"table:{page.pageNo}:{table_index}",
                pageNo=page.pageNo,
                type="table",
                label=title,
                valueText="，".join(summary_parts),
                excerpt=excerpt,
                blockIds=block_ids,
                blockPosition=_resolve_target_block_position(page.blocks, block_ids),
                rowCount=row_count,
                columnCount=column_count or None,
                headers=headers,
                groupLabel="表格",
            )
        )

    return targets


def _build_operation_targets_from_outputs(
    *,
    page: WorkbenchPageDetail,
    outputs: list[Any],
) -> list[OperationTargetRef]:
    targets: list[OperationTargetRef] = []
    for output_index, output in enumerate(outputs):
        output_id = str(getattr(output, "id", "") or f"output-{output_index + 1}")
        output_type = str(getattr(output, "type", "") or "custom")
        title = str(getattr(output, "title", "") or f"提取结果 {output_index + 1}")
        data = getattr(output, "data", None)
        if output_type == "field_list" and isinstance(data, dict):
            for field_index, item in enumerate(data.get("fields") or []):
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("key") or f"字段 {field_index + 1}").strip()
                value = str(item.get("value") or "")
                targets.append(
                    OperationTargetRef(
                        id=f"field:{page.pageNo}:{output_index}:{field_index}",
                        pageNo=page.pageNo,
                        type="field",
                        label=label,
                        valueText=value,
                        excerpt=f"{label}: {value}",
                        blockIds=[],
                        fieldKey=_slugify_label(label),
                        groupLabel=title,
                        data={"label": label, "value": value, "outputId": output_id},
                    )
                )
            continue
        if output_type == "kv_table" and isinstance(data, dict) and isinstance(data.get("kv"), dict):
            for field_index, (key, value) in enumerate(data["kv"].items()):
                label = str(key).strip()
                if not label:
                    continue
                value_text = str(value)
                targets.append(
                    OperationTargetRef(
                        id=f"field:{page.pageNo}:{output_index}:kv:{field_index}",
                        pageNo=page.pageNo,
                        type="field",
                        label=label,
                        valueText=value_text,
                        excerpt=f"{label}: {value_text}",
                        blockIds=[],
                        fieldKey=_slugify_label(label),
                        groupLabel=title,
                        data={"label": label, "value": value_text, "outputId": output_id},
                    )
                )
            continue
        if output_type == "data_table" and isinstance(data, dict):
            headers = [str(item) for item in (data.get("headers") or [])]
            rows = data.get("rows") if isinstance(data.get("rows"), list) else []
            targets.append(
                OperationTargetRef(
                    id=f"table:{page.pageNo}:{output_index}",
                    pageNo=page.pageNo,
                    type="table",
                    label=title,
                    valueText=f"{len(rows)} 行 · {len(headers)} 列",
                    excerpt=" | ".join(headers[:8]) or title,
                    blockIds=[],
                    rowCount=len(rows),
                    columnCount=len(headers) or None,
                    headers=headers,
                    groupLabel="表格",
                    data=data,
                )
            )
            continue
        if output_type == "kv_record_table" and isinstance(data, dict):
            kv = data.get("kv") if isinstance(data.get("kv"), dict) else {}
            table = data.get("table") if isinstance(data.get("table"), list) else []
            headers = _collect_structured_object_headers([row for row in table if isinstance(row, dict)])
            targets.append(
                OperationTargetRef(
                    id=f"structured-object:{page.pageNo}:{output_index}",
                    pageNo=page.pageNo,
                    type="structured_object",
                    label=title,
                    valueText=f"{len(kv)} 项 KV，{len(table)} 行明细",
                    excerpt=" | ".join([*kv.keys(), *headers][:8]) or title,
                    blockIds=[],
                    rowCount=len(table),
                    columnCount=len(headers) or None,
                    headers=[*kv.keys(), *headers],
                    groupLabel="复合表",
                    data=data,
                )
            )
            continue
        if output_type == "record_collection" and isinstance(data, dict):
            records = data.get("records") if isinstance(data.get("records"), list) else []
            targets.append(
                OperationTargetRef(
                    id=f"record-collection:{page.pageNo}:{output_index}",
                    pageNo=page.pageNo,
                    type="record_collection",
                    label=title,
                    valueText=f"{len(records)} 条记录",
                    excerpt=title,
                    blockIds=[],
                    rowCount=len(records),
                    groupLabel="记录集合",
                    data=data,
                )
            )
            for record_index, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                record_label = str(record.get("调色号") or record.get("name") or record.get("id") or f"记录 {record_index + 1}")
                targets.append(
                    OperationTargetRef(
                        id=f"record:{page.pageNo}:{output_index}:{record_index}",
                        pageNo=page.pageNo,
                        type="record",
                        label=record_label,
                        valueText=f"第 {record_index + 1} 条记录",
                        excerpt=record_label,
                        blockIds=[],
                        rowIndex=record_index,
                        groupLabel=title,
                        data=record,
                    )
                )
            continue
        targets.append(
            OperationTargetRef(
                id=f"output:{page.pageNo}:{output_index}",
                pageNo=page.pageNo,
                type="output",
                label=title,
                valueText=output_type,
                excerpt=title,
                blockIds=[],
                groupLabel="提取结果",
                data=data,
            )
        )
    return targets


def build_extraction_result_payload(
    *,
    pages: list[WorkbenchPageDetail],
    parse_run: PromptRunRecord | None,
) -> dict[str, Any] | None:
    extraction = _build_structured_extraction_result(parse_run) if parse_run else None
    extraction_result = _build_extraction_result(extraction, pages, parse_run) if parse_run else None
    return extraction_result.model_dump() if extraction_result else None


def build_object_operation_result(run: PromptRunRecord) -> ObjectOperationResult | None:
    if run.runPurpose != "post_process":
        return None
    payload = run.structuredProcessResult
    if not isinstance(payload, dict) or payload.get("operationType") is None:
        return None

    result_kind = str(payload.get("resultKind") or "").strip().lower()
    if result_kind not in {"decision", "object", "table", "text"}:
        return None

    target_id = str(payload.get("targetId") or "").strip()
    if not target_id:
        return None
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        return None
    output_payload = payload.get("outputPayload")
    if not _object_operation_payload_matches_result_kind(result_kind, output_payload):
        return None

    return ObjectOperationResult(
        id=run.id,
        targetId=target_id,
        pageNo=run.startPageNo,
        operationType=str(payload.get("operationType")),  # type: ignore[arg-type]
        executionSource=str(payload.get("executionSource") or "").strip() or None,
        skillId=str(payload.get("skillId") or "").strip() or None,
        skillVersion=str(payload.get("skillVersion") or "").strip() or None,
        sourceSkillId=str(payload.get("sourceSkillId") or "").strip() or None,
        sourceSkillVersion=str(payload.get("sourceSkillVersion") or "").strip() or None,
        sourceSkillName=str(payload.get("sourceSkillName") or "").strip() or None,
        sourceApplicationId=str(payload.get("sourceApplicationId") or "").strip() or None,
        sourceApplicationVersion=str(payload.get("sourceApplicationVersion") or "").strip() or None,
        sourceApplicationStepId=str(payload.get("sourceApplicationStepId") or "").strip() or None,
        executor=str(payload.get("executor") or "").strip() or None,  # type: ignore[arg-type]
        configSnapshot=payload.get("configSnapshot") if isinstance(payload.get("configSnapshot"), dict) else None,
        resultKind=result_kind,  # type: ignore[arg-type]
        summary=summary,
        outputPayload=output_payload,
        validationErrors=[
            str(item).strip()
            for item in (payload.get("validationErrors") or run.validationErrors or [])
            if str(item).strip()
        ],
        runPhase=_normalize_run_phase(run),
        phaseStartedAt=run.phaseStartedAt,
        lastHeartbeatAt=run.lastHeartbeatAt,
        evidenceRefs=_build_evidence_refs(run),
        relatedTargetIds=[
            str(item).strip()
            for item in (payload.get("relatedTargetIds") or [])
            if str(item).strip()
        ],
        createdAt=run.updatedAt,
        source="runtime",
    )


def build_llm_trace_summary(traces: list[LlmCallTraceRecord]) -> Optional[LlmCallTraceSummary]:
    if not traces:
        return None
    latest = max(traces, key=lambda item: item.updatedAt or item.createdAt)
    return LlmCallTraceSummary(
        callCount=len(traces),
        slowCallCount=sum(1 for item in traces if int(item.totalMs or item.httpMs or 0) >= 30_000),
        totalHttpMs=sum(int(item.httpMs or 0) for item in traces),
        totalMs=sum(int(item.totalMs or item.httpMs or 0) for item in traces),
        inputChars=sum(int(item.inputChars or 0) for item in traces),
        outputChars=sum(int(item.outputChars or 0) for item in traces),
        promptTokens=_sum_optional_trace_int(traces, "promptTokens"),
        completionTokens=_sum_optional_trace_int(traces, "completionTokens"),
        totalTokens=_sum_optional_trace_int(traces, "totalTokens"),
        model=latest.model,
        provider=latest.provider,
        latestStatus=latest.status,
        latestErrorType=latest.errorType,
    )


def _sum_optional_trace_int(traces: list[LlmCallTraceRecord], attr: str) -> Optional[int]:
    values = [getattr(item, attr) for item in traces if getattr(item, attr) is not None]
    if not values:
        return None
    return sum(int(value or 0) for value in values)


def _object_operation_payload_matches_result_kind(result_kind: str, payload: Any) -> bool:
    if result_kind == "text":
        return isinstance(payload, str)
    if result_kind in {"decision", "object"}:
        return isinstance(payload, dict)
    if result_kind == "table":
        if not isinstance(payload, dict):
            return False
        headers = payload.get("headers")
        rows = payload.get("rows")
        return (
            isinstance(headers, list)
            and isinstance(rows, list)
            and all(isinstance(header, str) and header.strip() for header in headers)
            and all(isinstance(row, dict) for row in rows)
        )
    return False


def _build_structured_extraction_result(run: PromptRunRecord) -> _StructuredExtraction | None:
    payload = run.structuredExtractionResult
    if not payload:
        return None
    if isinstance(payload.get("outputs"), list):
        return _StructuredExtraction(
            summary=str(payload.get("summary") or ""),
            fields=[],
            tablePayload={"__extractionResult": payload},
        )

    custom_result = normalize_custom_result_value(payload.get("customResult"))
    field_items = merge_field_items(
        normalize_field_items(payload.get("basicInfo") or []),
        extract_field_items_from_custom_result(custom_result),
    )
    if is_field_only_custom_result(custom_result):
        custom_result = None

    return _StructuredExtraction(
        summary=str(payload.get("summary") or ""),
        fields=[
            _StructuredField(
                label=str(item.get("label") or "字段"),
                value=str(item.get("value") or ""),
            )
            for item in field_items
        ],
        tablePayload=custom_result,
    )


def _build_extraction_result(
    extraction: _StructuredExtraction | None,
    pages: list[WorkbenchPageDetail],
    run: PromptRunRecord | None,
) -> ExtractionResult | None:
    if not extraction:
        return None
    if isinstance(extraction.tablePayload, dict) and isinstance(extraction.tablePayload.get("__extractionResult"), dict):
        payload = dict(extraction.tablePayload["__extractionResult"])
        payload.setdefault("summary", extraction.summary)
        payload.setdefault("outputs", [])
        payload.setdefault("errors", [])
        payload.setdefault("runMeta", {})
        payload.setdefault("fields", [])
        payload.setdefault("tables", [])
        payload.setdefault("structuredObjects", [])
        payload.setdefault("validationErrors", list(run.validationErrors or []) if run else [])
        payload = repair_legacy_extraction_result_tables(payload)
        return ExtractionResult.model_validate(payload)

    fields: list[ExtractionFieldItem] = []
    for field in extraction.fields:
        block_ids = _match_block_ids_across_pages(
            pages,
            text_candidates=[field.label, field.value, f"{field.label}{field.value}"],
            prefer_table=False,
        )
        fields.append(
            ExtractionFieldItem(
                label=field.label,
                value=field.value,
                source="text",
                evidenceRefs=_build_page_evidence_refs(pages, block_ids, fallback=f"{field.label}: {field.value}"),
            )
        )

    tables: list[ExtractionTableItem] = []
    for table_index, table in enumerate(_extract_table_payloads_from_custom_result(extraction.tablePayload)):
        headers = [str(item).strip() for item in table.get("headers") or [] if str(item).strip()]
        rows = [
            [str(cell).strip() for cell in row]
            for row in (table.get("rows") or [])
            if isinstance(row, list)
        ]
        if not headers and not rows:
            continue
        title = str(table.get("title") or f"表格区域 {table_index + 1}").strip()
        block_ids = _match_block_ids_across_pages(
            pages,
            text_candidates=[title, *headers],
            prefer_table=True,
        )
        parser_meta = {
            "rowCount": len(rows),
            "columnCount": max([len(headers), *(len(row) for row in rows)] or [0]),
        }
        if table.get("parserVersion"):
            parser_meta["parserVersion"] = table.get("parserVersion")
        if table.get("tableRole"):
            parser_meta["tableRole"] = table.get("tableRole")
        tables.append(
            ExtractionTableItem(
                title=title,
                headers=headers,
                rows=rows,
                source="parser",
                evidenceRefs=_build_page_evidence_refs(
                    pages,
                    block_ids,
                    fallback=" | ".join(headers[:8]) if headers else title,
                ),
                parserMeta=parser_meta,
            )
        )

    structured_objects: list[ExtractionStructuredObjectItem] = []
    for object_index, item in enumerate(_extract_structured_object_payloads_from_custom_result(extraction.tablePayload)):
        kv = {
            str(key).strip(): str(value).strip()
            for key, value in (item.get("kv") or {}).items()
            if str(key).strip()
        }
        table_rows = [
            {
                str(key).strip(): str(value).strip()
                for key, value in row.items()
                if str(key).strip()
            }
            for row in (item.get("table") or [])
            if isinstance(row, dict)
        ]
        if not kv and not table_rows:
            continue
        headers = _collect_structured_object_headers(table_rows)
        title = str(item.get("title") or f"复合表对象 {object_index + 1}").strip()
        block_ids = _match_block_ids_across_pages(
            pages,
            text_candidates=[title, *kv.keys(), *kv.values(), *headers],
            prefer_table=True,
        )
        parser_meta = dict(item.get("parserMeta") or {})
        parser_meta.update(
            {
                "kvCount": len(kv),
                "rowCount": len(table_rows),
                "columnCount": len(headers),
            }
        )
        structured_objects.append(
            ExtractionStructuredObjectItem(
                id=f"structured-object-{object_index + 1}",
                title=title,
                type="kv_record_table",
                kv=kv,
                table=table_rows,
                source="parser",
                evidenceRefs=_build_page_evidence_refs(
                    pages,
                    block_ids,
                    fallback=" | ".join([*kv.keys(), *headers][:8]) or title,
                ),
                parserMeta=parser_meta,
            )
        )

    validation_errors = [
        str(item).strip()
        for item in ((run.validationErrors if run else []) or [])
        if str(item).strip()
    ]
    summary = str(extraction.summary or "").strip()
    if not summary and not fields and not tables and not structured_objects and not validation_errors:
        return None
    return ExtractionResult(
        summary=summary,
        fields=fields,
        tables=tables,
        structuredObjects=structured_objects,
        validationErrors=validation_errors,
    )


def _infer_result_stage(run: PromptRunRecord) -> str:
    if run.runPurpose in {"schema_process", "post_process"}:
        return "process"
    return "process" if run.runPurpose == "summary" else "parse"


def _build_schema_process_result(run: PromptRunRecord) -> SchemaProcessResult | None:
    if run.runPurpose != "schema_process" or not run.templateId or not run.schemaOutput:
        return None
    return SchemaProcessResult(
        templateId=run.templateId,
        templateName=run.schemaTemplateName or run.promptName,
        templateVersion=run.schemaTemplateVersion,
        summary=run.outputText or "已生成模板处理结果。",
        schemaOutput=run.schemaOutput,
        validationErrors=list(run.validationErrors or []),
        evidenceRefs=_build_evidence_refs(run),
        source="runtime",
    )


def _build_evidence_refs(run: PromptRunRecord) -> list[WorkbenchEvidenceRef]:
    refs: list[WorkbenchEvidenceRef] = []
    excerpts = list(run.evidenceExcerpts or [])
    for index, block_id in enumerate(run.evidenceBlockIds or []):
        refs.append(
            WorkbenchEvidenceRef(
                pageNo=run.startPageNo,
                blockId=block_id,
                blockPosition="",
                excerpt=excerpts[index] if index < len(excerpts) else "",
            )
        )
    return refs


def _match_block_ids_across_pages(
    pages: list[WorkbenchPageDetail],
    *,
    text_candidates: list[str],
    prefer_table: bool,
) -> list[str]:
    matched: list[str] = []
    for page in pages:
        matched.extend(
            _match_block_ids(
                page.blocks,
                text_candidates=text_candidates,
                prefer_table=prefer_table,
            )
        )
        if matched:
            break
    return matched


def _build_page_evidence_refs(
    pages: list[WorkbenchPageDetail],
    block_ids: list[str],
    *,
    fallback: str,
) -> list[WorkbenchEvidenceRef]:
    block_lookup = {
        block.id: (page.pageNo, block)
        for page in pages
        for block in page.blocks
    }
    refs: list[WorkbenchEvidenceRef] = []
    for block_id in block_ids:
        matched = block_lookup.get(block_id)
        if not matched:
            continue
        page_no, block = matched
        refs.append(
            WorkbenchEvidenceRef(
                pageNo=page_no,
                blockId=block.id,
                blockPosition=block.blockPosition,
                excerpt=(block.content or block.title or fallback).strip()[:200],
            )
        )
    if refs:
        return refs
    page_no = pages[0].pageNo if pages else 1
    return [
        WorkbenchEvidenceRef(
            pageNo=page_no,
            blockId="",
            blockPosition="",
            excerpt=fallback.strip()[:200],
        )
    ]


def _match_block_ids(
    blocks: list[WorkbenchBlock],
    *,
    text_candidates: list[str],
    prefer_table: bool,
) -> list[str]:
    normalized_candidates = [_normalize_search_text(item) for item in text_candidates if _normalize_search_text(item)]
    if not normalized_candidates:
        return []

    scored: list[tuple[int, WorkbenchBlock]] = []
    for block in blocks:
        content = _normalize_search_text(" ".join(filter(None, [block.title, block.content])))
        score = 0
        if prefer_table:
            score += 2 if str(block.type or "").lower() in {"table", "table_body", "table_caption"} else 0
        for candidate in normalized_candidates:
            if candidate and candidate in content:
                score += max(1, min(len(candidate), 12))
        if score > 0:
            scored.append((score, block))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [block.id for _, block in scored[:2]]


def _resolve_target_excerpt(
    blocks: list[WorkbenchBlock],
    block_ids: list[str],
    *,
    fallback: str,
) -> str:
    block_lookup = {block.id: block for block in blocks}
    for block_id in block_ids:
        matched = block_lookup.get(block_id)
        if matched:
            return (matched.content or matched.title or fallback).strip()[:200]
    return fallback.strip()[:200]


def _resolve_target_block_position(blocks: list[WorkbenchBlock], block_ids: list[str]) -> str | None:
    block_lookup = {block.id: block for block in blocks}
    for block_id in block_ids:
        matched = block_lookup.get(block_id)
        if matched and matched.blockPosition:
            return matched.blockPosition
    return None


def _slugify_label(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", value.strip()).strip("_").lower()
    return normalized or "field"


def _normalize_search_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _extract_table_payloads_from_custom_result(custom_result: Any) -> list[dict[str, Any]]:
    normalized = normalize_custom_result_value(custom_result)
    if isinstance(normalized, list):
        table_payloads: list[dict[str, Any]] = []
        for item in normalized:
            table_payloads.extend(_extract_table_payloads_from_custom_result(item))
        return table_payloads
    if not isinstance(normalized, dict) or not custom_result_has_table_payload(normalized):
        return []

    table_payload = normalized.get("displayTable") or normalized.get("canonicalTable")
    if not isinstance(table_payload, dict):
        return []

    headers = [str(item).strip() for item in table_payload.get("headers") or []]
    rows = [
        [str(cell).strip() for cell in row]
        for row in table_payload.get("rows") or []
        if isinstance(row, list)
    ]
    if not headers and not rows:
        return []

    return [
        {
            "title": str(normalized.get("title") or "").strip() or "表格区域",
            "headers": headers,
            "rows": rows,
            "parserVersion": normalized.get("parserVersion"),
            "tableRole": normalized.get("tableRole"),
        }
    ]


def _extract_structured_object_payloads_from_custom_result(custom_result: Any) -> list[dict[str, Any]]:
    normalized = normalize_custom_result_value(custom_result)
    if isinstance(normalized, list):
        payloads: list[dict[str, Any]] = []
        for item in normalized:
            payloads.extend(_extract_structured_object_payloads_from_custom_result(item))
        return payloads
    if not isinstance(normalized, dict):
        return []

    candidates: list[Any] = []
    structured_objects = normalized.get("structuredObjects")
    if isinstance(structured_objects, list):
        candidates.extend(structured_objects)
    elif _looks_like_structured_object_payload(normalized):
        candidates.append(normalized)

    result: list[dict[str, Any]] = []
    for candidate in candidates:
        if not _looks_like_structured_object_payload(candidate):
            continue
        result.append(candidate)
    return result


def _looks_like_structured_object_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    object_type = str(value.get("type") or "kv_record_table").strip()
    kv = value.get("kv")
    table = value.get("table")
    return object_type == "kv_record_table" and isinstance(kv, dict) and isinstance(table, list)


def _collect_structured_object_headers(rows: list[dict[str, str]]) -> list[str]:
    headers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            normalized = str(key).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            headers.append(normalized)
    return headers


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _is_table_block(block_type: str) -> bool:
    return str(block_type).strip().lower() in {"table", "table_body", "table_caption"}


def _build_prompt_trace(prompt_text: str) -> PageResultPromptTrace:
    text_prompt, table_prompt = _split_modal_prompts(prompt_text)
    return PageResultPromptTrace(
        text=(
            PromptTraceItem(
                key="text",
                label="文本提示词",
                sourceMode="text",
                prompt=text_prompt,
                summary="文本链路仅消费文本块，结果来源固定回溯到当前文本提示词。",
            )
            if text_prompt
            else None
        ),
        table=(
            PromptTraceItem(
                key="table",
                label="表格提示词",
                sourceMode="table",
                prompt=table_prompt,
                summary="表格链路仅消费表格块，结果来源固定回溯到当前表格提示词。",
            )
            if table_prompt
            else None
        ),
    )


def _build_source_sections(prompt_trace: PageResultPromptTrace | None) -> dict[str, Any]:
    keys: list[str] = []
    modes: list[str] = []
    if prompt_trace and prompt_trace.text:
        keys.append("text")
        modes.append("text")
    if prompt_trace and prompt_trace.table:
        keys.append("table")
        modes.append("table")
    return {
        "text": {
            "sourceModes": ["text"] if "text" in modes else [],
            "promptTraceKeys": ["text"] if "text" in keys else [],
        },
        "table": {
            "sourceModes": ["table"] if "table" in modes else [],
            "promptTraceKeys": ["table"] if "table" in keys else [],
        },
        "business": {
            "sourceModes": modes,
            "promptTraceKeys": keys,
        },
    }


def _split_modal_prompts(prompt_text: str) -> tuple[str, str]:
    """
    从分页运行的组合提示词里拆出 text / table 两条显式链路输入。

    这里保持和 LLM service 一致的提示词片段格式，避免结果构建层再次去猜测
    某段内容属于哪条模态链路。
    """

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


def build_pages_from_artifacts(
    content_items: list[Any] | None,
    block_payload: dict[str, Any] | list[Any] | None,
) -> list[WorkbenchPageDetail]:
    if not content_items:
        return []

    content_by_page = (
        _group_content_list_v2_by_page(content_items)
        if _is_content_list_v2_payload(content_items)
        else _group_by_page([item for item in content_items if isinstance(item, dict)])
    )
    canonical_blocks_by_page = _build_canonical_blocks_by_page(block_payload)
    pages: list[WorkbenchPageDetail] = []

    for page_index in sorted(content_by_page.keys()):
        items = content_by_page[page_index]
        page_size = _resolve_page_size(block_payload, page_index)
        canonical_blocks = canonical_blocks_by_page.get(page_index) or []
        blocks = _build_page_blocks_from_content_items(
            page_index=page_index,
            items=items,
            canonical_blocks=canonical_blocks,
        )

        preview_text = " / ".join(
            block.content.replace("\n", " ").strip()
            for block in blocks[:2]
            if block.content.strip()
        )
        pages.append(
            WorkbenchPageDetail(
                pageIndex=page_index,
                pageNo=page_index + 1,
                prompt=_build_prompt(blocks),
                promptStatus="ready",
                markdownSegments=_build_markdown_segments(blocks),
                blocks=blocks,
                rawItems=items,
                pageSize=page_size,
            )
        )

    return pages


def _normalize_task_status(status: str) -> str:
    if status in {"pending", "running", "completed", "failed", "needs_review"}:
        return status
    return "pending"


def _normalize_result_status(status: str) -> str:
    if status == "running":
        return "processing"
    if status in {"completed", "failed", "needs_review"}:
        return status
    return "empty"


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


def _aggregate_run_status(runs: list[PromptRunRecord]) -> str:
    if not runs:
        return "pending"
    if any(item.status == "running" for item in runs):
        return "running"
    if any(item.status == "failed" for item in runs):
        return "failed"
    if any(item.status == "needs_review" for item in runs):
        return "needs_review"
    if all(item.status == "completed" for item in runs):
        return "completed"
    return "pending"


def _get_run_scope_key(run: PromptRunRecord) -> str:
    return f"{run.runType}:{run.startPageNo}:{run.endPageNo}:{run.promptName}"


def _get_latest_effective_runs(runs: list[PromptRunRecord]) -> list[PromptRunRecord]:
    sorted_runs = sorted(runs, key=lambda item: item.updatedAt, reverse=True)
    seen_keys: set[str] = set()
    effective_runs: list[PromptRunRecord] = []
    for run in sorted_runs:
      scope_key = _get_run_scope_key(run)
      if scope_key in seen_keys:
          continue
      seen_keys.add(scope_key)
      effective_runs.append(run)
    return effective_runs


def _format_page_range(startPageNo: int, endPageNo: int) -> str:
    if startPageNo == endPageNo:
        return f"第 {startPageNo} 页"
    return f"第 {startPageNo}-{endPageNo} 页"


def _format_runtime_status_label(status: str) -> str:
    return {
        "pending": "待执行",
        "running": "执行中",
        "completed": "已完成",
        "failed": "失败",
    }.get(status, "状态未知")


def _group_by_page(items: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[int(item.get("page_idx", 0))].append(item)
    return dict(grouped)


def _group_content_list_v2_by_page(content_items: list[Any]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for page_index, page_items in enumerate(content_items):
        if not isinstance(page_items, list):
            continue
        normalized_items: list[dict[str, Any]] = []
        for item in page_items:
            if not isinstance(item, dict):
                continue
            normalized_item = dict(item)
            normalized_item.setdefault("page_idx", page_index)
            normalized_items.append(normalized_item)
        grouped[page_index] = normalized_items
    return grouped


def _is_content_list_v2_payload(content_items: list[Any]) -> bool:
    return bool(content_items) and all(isinstance(page_items, list) for page_items in content_items)


def _resolve_page_size(
    block_payload: dict[str, Any] | list[Any] | None,
    page_index: int,
) -> tuple[float, float]:
    page_blocks = _get_layout_page(block_payload, page_index)
    if page_blocks:
        page_size = page_blocks.get("page_size")
        if isinstance(page_size, list) and len(page_size) == 2:
            return (float(page_size[0]), float(page_size[1]))
    return (595.0, 842.0)


def _resolve_bbox(item: dict[str, Any]) -> tuple[float, float, float, float]:
    raw_bbox = item.get("bbox") or [0, 0, 0, 0]
    normalized = list(raw_bbox)[:4]
    while len(normalized) < 4:
        normalized.append(0)
    return tuple(float(value) for value in normalized)


def _extract_block_content(item: dict[str, Any]) -> str:
    if item.get("type") == "table":
        content = item.get("content")
        if isinstance(content, dict):
            return str(content.get("html") or "")
        return item.get("table_body") or item.get("content") or ""
    if item.get("type") == "list":
        content = item.get("content")
        if isinstance(content, dict):
            return "\n".join(_extract_list_item_texts(content.get("list_items")))
        return "\n".join(_extract_list_item_texts(item.get("list_items")))
    content = item.get("content")
    if isinstance(content, dict):
        return _extract_text_from_content_payload(content)
    return item.get("text") or item.get("content") or ""


def _extract_block_title(item: dict[str, Any]) -> str:
    if item.get("type") == "table":
        content = item.get("content")
        captions = []
        if isinstance(content, dict):
            captions = [
                str(entry.get("content") or "").strip()
                for entry in content.get("table_caption") or []
                if isinstance(entry, dict) and str(entry.get("content") or "").strip()
            ]
        else:
            captions = item.get("table_caption") or []
        return " / ".join(captions) or "表格区域"
    if item.get("type") == "list":
        list_text = _extract_block_content(item).replace("\n", " ").strip()
        return (list_text[:18] if list_text else "列表片段")
    return (_extract_block_content(item) or "文本片段")[:18]


def _build_markdown_segments(blocks: list[WorkbenchBlock]) -> list[WorkbenchMarkdownSegment]:
    segments: list[WorkbenchMarkdownSegment] = []
    for index, block in enumerate(blocks):
        html = _build_block_segment_html(block)
        segments.append(
            WorkbenchMarkdownSegment(
                id=f"{block.id}-segment-{index}",
                pageIndex=block.pageIndex,
                pageNo=block.pageNo,
                blockId=block.id,
                blockPosition=block.blockPosition,
                type=block.type,
                html=html,
                bbox=block.bbox,
            )
        )
    return segments


def _build_block_segment_html(block: WorkbenchBlock) -> str:
    if block.type == "table":
        return str(block.htmlContent or block.content or "")
    if block.type == "list":
        return f"<pre>{block.content}</pre>"
    return f"<h3>{block.content}</h3>" if block.type == "title" else f"<p>{block.content}</p>"


def _get_layout_page(
    block_payload: dict[str, Any] | list[Any] | None,
    page_index: int,
) -> dict[str, Any] | None:
    if not isinstance(block_payload, dict):
        return None
    pdf_info = block_payload.get("pdf_info")
    if not isinstance(pdf_info, list):
        return None
    if 0 <= page_index < len(pdf_info) and isinstance(pdf_info[page_index], dict):
        return pdf_info[page_index]
    return None


def _build_canonical_blocks_by_page(
    block_payload: dict[str, Any] | list[Any] | None,
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    pdf_info = block_payload.get("pdf_info") if isinstance(block_payload, dict) else None
    if isinstance(pdf_info, list):
        for page in pdf_info:
            if not isinstance(page, dict):
                continue
            page_index = int(page.get("page_idx", len(grouped)))
            grouped[page_index] = _extract_para_blocks(page, page_index)

    model_payload = _get_model_payload(block_payload)
    if isinstance(model_payload, list):
        for page_index, page_blocks in enumerate(model_payload):
            model_blocks = _extract_model_page_blocks(page_blocks, page_index)
            if not model_blocks:
                continue
            if page_index in grouped:
                grouped[page_index] = _backfill_canonical_blocks_with_model(
                    layout_blocks=grouped[page_index],
                    model_blocks=model_blocks,
                )
            else:
                grouped[page_index] = model_blocks
    return grouped


def _extract_para_blocks(page: dict[str, Any], page_index: int) -> list[dict[str, Any]]:
    para_blocks = page.get("para_blocks")
    if not isinstance(para_blocks, list):
        return []
    blocks: list[dict[str, Any]] = []
    for offset, block in enumerate(para_blocks):
        if not isinstance(block, dict):
            continue
        blocks.append(
            {
                "id": f"page-{page_index}-para-{int(block.get('index', offset))}",
                "pageIndex": page_index,
                "blockPosition": f"para-{int(block.get('index', offset))}",
                "type": str(block.get("type") or "text"),
                "bbox": _normalize_bbox_values(block.get("bbox")),
                "content": _extract_layout_block_content(block),
                "title": _extract_layout_block_title(block),
                "htmlContent": _extract_layout_block_html(block),
                "signature": _normalize_matching_text(_extract_layout_block_signature_text(block)),
            }
        )
    return blocks


def _build_page_blocks_from_content_items(
    *,
    page_index: int,
    items: list[dict[str, Any]],
    canonical_blocks: list[dict[str, Any]],
) -> list[WorkbenchBlock]:
    matched_ids: set[str] = set()
    blocks: list[WorkbenchBlock] = []
    for index, item in enumerate(items):
        matched = _match_content_item_to_canonical_block(
            item=item,
            canonical_blocks=canonical_blocks,
            matched_ids=matched_ids,
        )
        content = _extract_block_content(item)
        item_type = str(item.get("type") or "text")
        html_content = _extract_item_html_content(item)
        title = _extract_block_title(item)
        if matched and _normalize_block_type(item_type) == "table":
            content = _choose_table_html(content, matched) or content
            html_content = _choose_table_html(html_content or "", matched) or html_content
            matched_title = str(matched.get("title") or "").strip()
            if title == "表格区域" and matched_title:
                title = matched_title
        block_id = str(matched.get("id") or f"page-{page_index}-block-{index}") if matched else f"page-{page_index}-block-{index}"
        block_position = str(matched.get("blockPosition") or f"{page_index}-{index}") if matched else f"{page_index}-{index}"
        bbox = tuple(matched.get("bbox") or _resolve_bbox(item)) if matched else _resolve_bbox(item)
        if matched:
            matched_ids.add(str(matched.get("id")))
        blocks.append(
            WorkbenchBlock(
                id=block_id,
                pageIndex=page_index,
                pageNo=page_index + 1,
                blockPosition=block_position,
                type=item_type,
                title=title,
                content=content,
                htmlContent=html_content,
                bbox=bbox,
            )
        )
    return blocks


def _get_model_payload(block_payload: dict[str, Any] | list[Any] | None) -> list[Any] | None:
    if isinstance(block_payload, list):
        return block_payload
    if isinstance(block_payload, dict):
        model_payload = block_payload.get("_model_payload")
        if isinstance(model_payload, list):
            return model_payload
        primary_payload = block_payload.get("_primary_payload")
        if isinstance(primary_payload, list):
            return primary_payload
    return None


def _extract_model_page_blocks(page_blocks: Any, page_index: int) -> list[dict[str, Any]]:
    if not isinstance(page_blocks, list):
        return []
    blocks: list[dict[str, Any]] = []
    for offset, block in enumerate(page_blocks):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "text")
        html = _extract_any_table_html(block) if _normalize_block_type(block_type) == "table" else ""
        content = html or _extract_layout_block_content(block)
        blocks.append(
            {
                "id": f"page-{page_index}-model-{offset}",
                "pageIndex": page_index,
                "blockPosition": f"model-{offset}",
                "type": block_type,
                "bbox": _normalize_bbox_values(block.get("bbox")),
                "content": content,
                "title": _extract_layout_block_title(block),
                "htmlContent": html,
                "signature": _normalize_matching_text(html or content),
            }
        )
    return blocks


def _backfill_canonical_blocks_with_model(
    *,
    layout_blocks: list[dict[str, Any]],
    model_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    used_model_indexes: set[int] = set()
    merged: list[dict[str, Any]] = []
    for layout_block in layout_blocks:
        block = dict(layout_block)
        if _normalize_block_type(str(block.get("type") or "")) == "table":
            for model_index, model_block in enumerate(model_blocks):
                if model_index in used_model_indexes:
                    continue
                if _normalize_block_type(str(model_block.get("type") or "")) != "table":
                    continue
                model_html = str(model_block.get("htmlContent") or model_block.get("content") or "")
                if not _has_table_html(model_html):
                    continue
                used_model_indexes.add(model_index)
                block["content"] = model_html
                block["htmlContent"] = model_html
                block["signature"] = _normalize_matching_text(model_html)
                if not str(block.get("title") or "").strip():
                    block["title"] = str(model_block.get("title") or "")
                break
        merged.append(block)
    return merged


def _choose_table_html(current_html: str, matched: dict[str, Any]) -> str:
    for key in ("htmlContent", "content"):
        candidate = str(matched.get(key) or "").strip()
        if _has_table_html(candidate):
            return candidate
    if _has_table_html(current_html):
        return current_html
    return ""


def _has_table_html(value: str) -> bool:
    return "<table" in str(value or "").lower()


def _match_content_item_to_canonical_block(
    *,
    item: dict[str, Any],
    canonical_blocks: list[dict[str, Any]],
    matched_ids: set[str],
) -> dict[str, Any] | None:
    item_type = str(item.get("type") or "text")
    item_bbox = _resolve_bbox(item)
    item_signature = _normalize_matching_text(_extract_item_signature_text(item))
    scored_candidates: list[tuple[int, dict[str, Any]]] = []
    for block in canonical_blocks:
        block_id = str(block.get("id") or "")
        if not block_id or block_id in matched_ids:
            continue
        score = _score_content_item_match(
            item_type=item_type,
            item_bbox=item_bbox,
            item_signature=item_signature,
            canonical_block=block,
        )
        if score <= 0:
            continue
        scored_candidates.append((score, block))
    if not scored_candidates:
        return None
    scored_candidates.sort(
        key=lambda entry: (
            entry[0],
            _bbox_iou(item_bbox, tuple(entry[1].get("bbox") or (0.0, 0.0, 0.0, 0.0))),
        ),
        reverse=True,
    )
    return scored_candidates[0][1]


def _score_content_item_match(
    *,
    item_type: str,
    item_bbox: tuple[float, float, float, float],
    item_signature: str,
    canonical_block: dict[str, Any],
) -> int:
    block_type = str(canonical_block.get("type") or "text")
    block_signature = str(canonical_block.get("signature") or "")
    score = 0
    if _normalize_block_type(item_type) == _normalize_block_type(block_type):
        score += 100
    if item_signature and block_signature:
        if item_signature == block_signature:
            score += 120
        elif item_signature in block_signature or block_signature in item_signature:
            score += 80
        else:
            overlap = _token_overlap_ratio(item_signature, block_signature)
            score += int(overlap * 60)
    iou = _bbox_iou(item_bbox, tuple(canonical_block.get("bbox") or (0.0, 0.0, 0.0, 0.0)))
    score += int(iou * 40)
    return score


def _normalize_block_type(value: str) -> str:
    if value in {"paragraph", "text"}:
        return "text"
    return value


def _extract_item_html_content(item: dict[str, Any]) -> str | None:
    if item.get("type") != "table":
        return None
    content = item.get("content")
    if isinstance(content, dict):
        html = str(content.get("html") or "").strip()
        return html or None
    html = str(item.get("table_body") or item.get("content") or "").strip()
    return html or None


def _extract_item_signature_text(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "text")
    if item_type == "table":
        return str(_extract_item_html_content(item) or "")
    if item_type == "list":
        content = item.get("content")
        if isinstance(content, dict):
            return "\n".join(_extract_list_item_texts(content.get("list_items")))
        return "\n".join(_extract_list_item_texts(item.get("list_items")))
    return str(_extract_block_content(item) or "")


def _extract_layout_block_content(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "text")
    if block_type == "table":
        return str(_extract_layout_block_html(block) or "")
    if block_type == "list":
        texts: list[str] = []
        for child in block.get("blocks") or []:
            child_text = _extract_layout_block_content(child)
            if child_text:
                texts.append(child_text)
        return "\n".join(texts)
    texts: list[str] = []
    for line in block.get("lines") or []:
        line_texts = [
            str(span.get("content") or "").strip()
            for span in line.get("spans") or []
            if isinstance(span, dict) and str(span.get("content") or "").strip()
        ]
        if line_texts:
            texts.append("".join(line_texts))
    return "\n".join(texts)


def _extract_layout_block_signature_text(block: dict[str, Any]) -> str:
    return _extract_layout_block_html(block) or _extract_layout_block_content(block)


def _extract_layout_block_title(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "text")
    if block_type == "table":
        captions = [
            _extract_layout_block_content(child)
            for child in block.get("blocks") or []
            if isinstance(child, dict) and str(child.get("type") or "") == "table_caption"
        ]
        return " / ".join(caption for caption in captions if caption) or "表格区域"
    if block_type == "list":
        return "列表片段"
    return (_extract_layout_block_content(block) or "文本片段")[:18]


def _extract_layout_block_html(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "text")
    if block_type == "table":
        direct_html = _extract_any_table_html(block)
        if direct_html:
            return direct_html
        for child in block.get("blocks") or []:
            if not isinstance(child, dict):
                continue
            for line in child.get("lines") or []:
                for span in line.get("spans") or []:
                    if isinstance(span, dict) and str(span.get("type") or "") == "table":
                        html = str(span.get("html") or "").strip()
                        if html:
                            return html
    return ""


def _extract_any_table_html(value: Any) -> str:
    if isinstance(value, str):
        return value.strip() if _has_table_html(value) else ""
    if isinstance(value, dict):
        for key in ("html", "table_body", "body", "content"):
            candidate = value.get(key)
            html = _extract_any_table_html(candidate)
            if html:
                return html
        for nested in value.values():
            html = _extract_any_table_html(nested)
            if html:
                return html
    if isinstance(value, list):
        for item in value:
            html = _extract_any_table_html(item)
            if html:
                return html
    return ""


def _extract_text_from_content_payload(content: dict[str, Any]) -> str:
    return "\n".join(_extract_content_texts(content))


def _extract_list_item_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value:
        parts = _extract_content_texts(item)
        text = "".join(parts).strip()
        if text:
            lines.append(text)
    return lines


def _extract_content_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            texts.extend(_extract_content_texts(item))
        return texts
    if isinstance(value, dict):
        texts: list[str] = []
        for key in (
            "content",
            "text",
            "item_content",
            "children",
            "title_content",
            "paragraph_content",
            "page_header_content",
            "page_footer_content",
            "page_number_content",
            "page_aside_text_content",
            "page_footnote_content",
            "image_caption",
            "image_footnote",
            "chart_caption",
            "chart_footnote",
            "table_caption",
            "table_footnote",
            "math_content",
            "code_caption",
            "code_content",
            "code_footnote",
            "algorithm_caption",
            "algorithm_content",
            "algorithm_footnote",
            "list_items",
        ):
            if key in value:
                texts.extend(_extract_content_texts(value.get(key)))
        return texts
    return []


def _normalize_bbox_values(raw_bbox: Any) -> tuple[float, float, float, float]:
    normalized = list(raw_bbox or [0, 0, 0, 0])[:4]
    while len(normalized) < 4:
        normalized.append(0)
    return tuple(float(value) for value in normalized)


def _normalize_matching_text(value: str) -> str:
    normalized = re.sub(r"\s+", "", value or "")
    return normalized.strip()


def _token_overlap_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_tokens = {token for token in re.split(r"[^\w\u4e00-\u9fff]+", left) if token}
    right_tokens = {token for token in re.split(r"[^\w\u4e00-\u9fff]+", right) if token}
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    baseline = max(len(left_tokens), len(right_tokens))
    return overlap / baseline if baseline else 0.0


def _bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    left_x1, left_y1, left_x2, left_y2 = left
    right_x1, right_y1, right_x2, right_y2 = right
    inter_x1 = max(left_x1, right_x1)
    inter_y1 = max(left_y1, right_y1)
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0
    left_area = max(0.0, left_x2 - left_x1) * max(0.0, left_y2 - left_y1)
    right_area = max(0.0, right_x2 - right_x1) * max(0.0, right_y2 - right_y1)
    union_area = left_area + right_area - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def _build_prompt(blocks: list[WorkbenchBlock]) -> str:
    has_text_blocks = any(not _is_table_block(block.type) for block in blocks)
    has_table_blocks = any(_is_table_block(block.type) for block in blocks)

    text_prompt = (
        "\n".join(
            [
                "1. 提取当前页文本中的关键字段，一行一条返回。",
                "2. 只基于当前页直接可见文本返回结果。",
                "3. 无相关字段时返回空结果，不要补推。",
            ]
        )
        if has_text_blocks
        else "未填写"
    )
    table_prompt = (
        "\n".join(
            [
                "1. 每行只写一条表格检查规则。",
                "2. 对每条规则分别返回结论；即使全部通过，也要逐条返回。",
                "3. 标题使用字段名，例如“湿度”“压差”“验证/校验有效期”。",
                "4. 只基于当前页表格直接可见证据判断。",
            ]
        )
        if has_table_blocks
        else "未填写"
    )

    return f"文本提示词：{text_prompt}\n\n表格提示词：{table_prompt}"
