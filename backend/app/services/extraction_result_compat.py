# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Compatibility helpers for normalized extraction results."""

from __future__ import annotations

import json
from typing import Any


def legacy_table_from_data_table(data: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """Build the legacy table view without dropping object-shaped table rows."""
    raw_headers = data.get("headers") or []
    headers = [str(item) for item in raw_headers] if isinstance(raw_headers, list) else []
    raw_rows = data.get("rows") or []
    rows_input = raw_rows if isinstance(raw_rows, list) else []

    if not headers:
        seen: list[str] = []
        for row in rows_input:
            if isinstance(row, dict):
                for key in row:
                    text = str(key)
                    if text not in seen:
                        seen.append(text)
            elif isinstance(row, list):
                for index in range(len(row)):
                    text = f"列{index + 1}"
                    if text not in seen:
                        seen.append(text)
        headers = seen

    has_source_page = any(
        isinstance(row, dict) and ("source_page" in row or "sourcePage" in row)
        for row in rows_input
    )
    if has_source_page and "source_page" not in headers and "sourcePage" not in headers:
        headers = [*headers, "source_page"]

    rows: list[list[str]] = []
    for row in rows_input:
        if isinstance(row, list):
            rows.append([
                _legacy_cell_to_text(row[index]) if index < len(row) else ""
                for index, _header in enumerate(headers)
            ])
            continue
        if isinstance(row, dict):
            cells: list[str] = []
            for header in headers:
                if header == "source_page" and "source_page" not in row and "sourcePage" in row:
                    cells.append(_legacy_cell_to_text(row.get("sourcePage")))
                else:
                    cells.append(_legacy_cell_to_text(row.get(header)))
            rows.append(cells)
    return headers, rows


def repair_legacy_extraction_result_tables(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill legacy `tables` from canonical `outputs` when stored rows are missing."""
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        return payload

    tables: list[dict[str, Any]] = []
    changed = False
    for index, output in enumerate(outputs):
        if not isinstance(output, dict) or output.get("type") != "data_table":
            continue
        data = output.get("data")
        if not isinstance(data, dict):
            continue
        headers, rows = legacy_table_from_data_table(data)
        if not headers and not rows:
            continue
        tables.append(
            {
                "title": str(output.get("title") or f"表格 {index + 1}"),
                "headers": headers,
                "rows": rows,
                "source": "llm",
                "evidenceRefs": [],
                "parserMeta": {},
            }
        )
        if rows:
            changed = True

    existing_tables = payload.get("tables")
    existing_has_rows = (
        isinstance(existing_tables, list)
        and any(isinstance(table, dict) and table.get("rows") for table in existing_tables)
    )
    if not changed or existing_has_rows:
        return payload

    next_payload = dict(payload)
    next_payload["tables"] = tables
    return next_payload


def _legacy_cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)
