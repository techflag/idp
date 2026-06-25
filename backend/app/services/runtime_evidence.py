# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Runtime evidence helpers for application extraction runs.

This module is intentionally isolated from repositories, task models and LLM
clients.  It operates on plain dict payloads so the application runtime can swap
or remove this evidence layer without dragging business code with it.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FIELD_LIST_INITIAL_MAX_TOTAL_TABLE_ROWS = 32
FIELD_LIST_REVIEW_MAX_TOTAL_TABLE_ROWS = 96

_MAX_COMPACT_CONTENT_REFS = 24
_MAX_COMPACT_GENERATED_TARGETS = 64
_MAX_COMPACT_TEXT_CHARS = 420
_MAX_TABLE_BLOCK_TEXT_CHARS = 6000


VALUE_PRESERVATION_INSTRUCTION = (
    "字段抽取时必须保留证据中的完整可见值，不要截断、改写、归一化或只取日期/编号片段；"
    "字段标签与证据标题、表头、键名可以按语义对应；"
    "值只能来自 facts 中可见的文本、表格单元格或行文本，无法确认时才返回空字符串。"
)


def enrich_field_list_extraction_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Attach generic field-list extraction guidance without business keywords."""

    next_config = dict(config or {})
    existing_instruction = str(next_config.get("runtimeEvidenceInstruction") or "").strip()
    if VALUE_PRESERVATION_INSTRUCTION in existing_instruction:
        return next_config
    if existing_instruction:
        next_config["runtimeEvidenceInstruction"] = f"{existing_instruction}\n{VALUE_PRESERVATION_INSTRUCTION}"
    else:
        next_config["runtimeEvidenceInstruction"] = VALUE_PRESERVATION_INSTRUCTION
    return next_config


def compact_application_scope_for_runtime(
    application_scope: dict[str, Any] | None,
    runtime_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep the application contract visible while dropping bulky UI-only data."""

    if not isinstance(application_scope, dict):
        return {}
    contract = runtime_contract if isinstance(runtime_contract, dict) else application_scope.get("runtimeContract")
    if not isinstance(contract, dict) or not contract:
        return dict(application_scope)

    input_mapping = application_scope.get("inputMapping") if isinstance(application_scope.get("inputMapping"), dict) else {}
    target_mapping = application_scope.get("targetMapping") if isinstance(application_scope.get("targetMapping"), dict) else {}
    content_refs = application_scope.get("contentRefs") if isinstance(application_scope.get("contentRefs"), list) else []
    generated_targets = (
        target_mapping.get("generatedTargets") if isinstance(target_mapping.get("generatedTargets"), list) else []
    )

    compact_target_mapping: dict[str, Any] = {}
    if generated_targets:
        compact_target_mapping["generatedTargets"] = [
            _compact_generated_target(item) for item in generated_targets[:_MAX_COMPACT_GENERATED_TARGETS]
        ]
    if target_mapping.get("outputType"):
        compact_target_mapping["outputType"] = target_mapping.get("outputType")

    return {
        "matchedPageNos": _compact_int_list(application_scope.get("matchedPageNos") or input_mapping.get("matchedPageNos")),
        "contentRefs": [_compact_content_ref(item) for item in content_refs[:_MAX_COMPACT_CONTENT_REFS] if isinstance(item, dict)],
        "targetMapping": compact_target_mapping,
        "runtimeContract": contract,
    }


def apply_field_list_global_row_budget(
    *,
    facts_payload: dict[str, Any],
    evidence_selection: dict[str, Any],
    max_total_rows: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a global table-row budget to a field_list evidence package.

    Existing selection already chooses relevant row windows per table.  This
    second pass enforces a run-level budget and rebuilds table block text so LLM
    input cannot accidentally include an entire long table through block.text.
    Full facts remain available in ``inputFactsSnapshot`` and artifacts.
    """

    if not isinstance(facts_payload, dict) or not isinstance(evidence_selection, dict):
        return facts_payload, evidence_selection
    if evidence_selection.get("mode") != "field_list_selected_evidence":
        return facts_payload, evidence_selection
    if max_total_rows <= 0:
        return facts_payload, evidence_selection

    payload = deepcopy(facts_payload)
    selection = deepcopy(evidence_selection)
    selected_before = _count_selected_table_rows(payload)
    total_table_rows = int(selection.get("totalTableRowCount") or 0) or _count_original_table_rows(payload)
    selection["maxTotalTableRows"] = max_total_rows
    selection["budgetApplied"] = True
    if selected_before <= max_total_rows:
        _rebuild_all_table_text(payload)
        selection["selectedTableRowCount"] = selected_before
        selection["totalTableRowCount"] = total_table_rows
        selection["budgetTruncated"] = False
        _refresh_selected_evidence(selection, payload)
        payload["evidenceSelection"] = selection
        return payload, selection

    remaining = max_total_rows
    selected_after = 0
    skipped_blocks = int(selection.get("skippedBlockCount") or 0)
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        next_blocks: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else None
            if table_grid is None:
                next_blocks.append(block)
                continue

            current_count = _grid_selected_row_count(table_grid)
            keep_count = min(current_count, max(remaining, 0))
            if keep_count <= 0:
                skipped_blocks += 1
                continue
            _slice_table_grid_to_count(table_grid, keep_count=keep_count, max_total_rows=max_total_rows)
            _rebuild_table_block_text(block)
            selected_after += keep_count
            remaining -= keep_count
            next_blocks.append(block)
        page["blocks"] = next_blocks

    selection["selectedTableRowCount"] = selected_after
    selection["totalTableRowCount"] = total_table_rows
    selection["skippedBlockCount"] = skipped_blocks
    selection["budgetTruncated"] = True
    reasons = selection.get("selectionReasons") if isinstance(selection.get("selectionReasons"), list) else []
    if "global_table_row_budget" not in reasons:
        selection["selectionReasons"] = [*reasons, "global_table_row_budget"]
    warnings = selection.get("warnings") if isinstance(selection.get("warnings"), list) else []
    budget_warning = (
        f"字段类证据已按全局预算限制为 {selected_after}/{selected_before} 行窗口，完整 facts 已保留。"
    )
    if budget_warning not in warnings:
        selection["warnings"] = [*warnings, budget_warning]
    _refresh_selected_evidence(selection, payload)
    payload["evidenceSelection"] = selection
    return payload, selection


def _compact_generated_target(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("type", "label", "fieldKey", "name", "outputType"):
        value = item.get(key)
        if value not in (None, "", [], {}):
            compact[key] = _truncate_text(value)
    return compact


def _compact_content_ref(item: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "source",
        "type",
        "title",
        "targetId",
        "blockId",
        "nodeId",
        "treeNodeId",
        "blockPosition",
        "excerpt",
    ):
        value = item.get(key)
        if value not in (None, "", [], {}):
            compact[key] = _truncate_text(value)
    for key in ("pages", "evidencePages", "blockIds", "blockIdsExact"):
        value = item.get(key)
        if isinstance(value, list) and value:
            compact[key] = [_truncate_text(part) for part in value[:16]]
    return compact


def _truncate_text(value: Any, limit: int = _MAX_COMPACT_TEXT_CHARS) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _compact_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    pages: list[int] = []
    for value in values:
        try:
            page_no = int(value)
        except (TypeError, ValueError):
            continue
        if page_no > 0 and page_no not in pages:
            pages.append(page_no)
    return pages


def _count_selected_table_rows(payload: dict[str, Any]) -> int:
    return sum(_grid_selected_row_count(grid) for grid in _iter_table_grids(payload))


def _count_original_table_rows(payload: dict[str, Any]) -> int:
    total = 0
    for grid in _iter_table_grids(payload):
        total += _grid_original_row_count(grid)
    return total


def _iter_table_grids(payload: dict[str, Any]):
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else None
            if table_grid is not None:
                yield table_grid


def _grid_selected_row_count(table_grid: dict[str, Any]) -> int:
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    selected_rows = [row for row in rows if isinstance(row, list)]
    if selected_rows:
        return len(selected_rows)
    try:
        return int(table_grid.get("rowCount") or 0)
    except (TypeError, ValueError):
        return 0


def _grid_original_row_count(table_grid: dict[str, Any]) -> int:
    for key in ("originalRowCount", "sourceRowCount", "fullRowCount", "rowCount"):
        try:
            count = int(table_grid.get(key) or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            return count
    return _grid_selected_row_count(table_grid)


def _slice_table_grid_to_count(
    table_grid: dict[str, Any],
    *,
    keep_count: int,
    max_total_rows: int,
) -> None:
    selected_before = _grid_selected_row_count(table_grid)
    for key in ("rows", "dedupedRows", "rowTexts", "rowSelection"):
        value = table_grid.get(key)
        if isinstance(value, list):
            table_grid[key] = value[:keep_count]
    table_grid["rowCount"] = keep_count
    table_grid["selectedRowCount"] = keep_count
    table_grid["maxTotalTableRows"] = max_total_rows
    table_grid["budgetTruncated"] = keep_count < selected_before
    table_grid["truncated"] = bool(table_grid.get("truncated") or keep_count < _grid_original_row_count(table_grid))


def _rebuild_all_table_text(payload: dict[str, Any]) -> None:
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("tableGrid"), dict):
                _rebuild_table_block_text(block)


def _rebuild_table_block_text(block: dict[str, Any]) -> None:
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    title = str(table_grid.get("title") or block.get("title") or "").strip()
    row_texts = [str(item or "").strip() for item in table_grid.get("rowTexts") or [] if str(item or "").strip()]
    if not row_texts:
        rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
        for row in rows:
            if isinstance(row, list):
                joined = " ".join(str(cell or "").strip() for cell in row if str(cell or "").strip())
                if joined:
                    row_texts.append(joined)
    lines = [line for line in [title, *row_texts] if line]
    rebuilt = "\n".join(lines)
    if len(rebuilt) > _MAX_TABLE_BLOCK_TEXT_CHARS:
        block["text"] = rebuilt[:_MAX_TABLE_BLOCK_TEXT_CHARS]
        block["textTruncated"] = True
        block["originalTextCharCount"] = len(rebuilt)
    else:
        block["text"] = rebuilt
    if table_grid.get("truncated") or table_grid.get("budgetTruncated"):
        block["textTruncated"] = True


def _refresh_selected_evidence(selection: dict[str, Any], payload: dict[str, Any]) -> None:
    table_infos = _collect_table_infos(payload)
    table_cursor = 0
    refreshed: list[dict[str, Any]] = []
    selected_evidence = selection.get("selectedEvidence") if isinstance(selection.get("selectedEvidence"), list) else []
    for item in selected_evidence:
        if not isinstance(item, dict):
            continue
        if item.get("sourceType") == "table" or "selectedRowCount" in item:
            if table_cursor >= len(table_infos):
                continue
            info = table_infos[table_cursor]
            table_cursor += 1
            if info["selectedRowCount"] <= 0:
                continue
            next_item = dict(item)
            next_item["selectedRowCount"] = info["selectedRowCount"]
            next_item["totalRowCount"] = info["totalRowCount"]
            next_item["rowWindow"] = info["rowWindow"]
            next_item["excerpt"] = info["excerpt"]
            if info["budgetTruncated"]:
                next_item["budgetTruncated"] = True
            refreshed.append(next_item)
            continue
        refreshed.append(dict(item))
    selection["selectedEvidence"] = refreshed[:24]
    selection["selectedBlockCount"] = len(refreshed)


def _collect_table_infos(payload: dict[str, Any]) -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else None
            if table_grid is None:
                continue
            row_texts = [str(item or "").strip() for item in table_grid.get("rowTexts") or [] if str(item or "").strip()]
            excerpt = " | ".join(row_texts[:3])[:320]
            infos.append(
                {
                    "selectedRowCount": _grid_selected_row_count(table_grid),
                    "totalRowCount": _grid_original_row_count(table_grid),
                    "rowWindow": (table_grid.get("rowSelection") or [])[:16]
                    if isinstance(table_grid.get("rowSelection"), list)
                    else [],
                    "excerpt": excerpt,
                    "budgetTruncated": bool(table_grid.get("budgetTruncated")),
                }
            )
    return infos
