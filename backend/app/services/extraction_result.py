"""Shared normalization helpers for structured extraction results."""

from __future__ import annotations

import re
from typing import Any


STRUCTURAL_CUSTOM_RESULT_KEYS = {
    "canonicaltable",
    "displaytable",
    "logicalgrid",
    "cellgrid",
    "cells",
    "segments",
    "tablerole",
    "parserversion",
    "parsewarnings",
    "rowdecisions",
    "markdown_table",
    "markdowntable",
    "tablemarkdown",
    "tabledata",
    "table_data",
    "rows",
    "headers",
    "validationmeta",
    "metadata",
    "total_rows",
    "totalrows",
}


def normalize_field_key(value: str) -> str:
    return re.sub(r"[\s_\-:：]+", "", str(value or "").strip().lower())


def normalize_custom_result_value(value: Any) -> Any:
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return None


def normalize_field_items(items: Any) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    if not isinstance(items, list):
        return fields
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        value = stringify_scalar_value(item.get("value"))
        if label and value:
            fields.append({"label": label, "value": value})
    return fields


def merge_field_items(*groups: list[dict[str, Any]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for item in group:
            label = str(item.get("label") or "").strip()
            value = stringify_scalar_value(item.get("value"))
            if not label or not value:
                continue
            key = (normalize_field_key(label), value)
            if key in seen:
                continue
            seen.add(key)
            merged.append({"label": label, "value": value})
    return merged


def extract_field_items_from_custom_result(custom_result: Any) -> list[dict[str, str]]:
    custom_result = normalize_custom_result_value(custom_result)
    if custom_result_has_table_payload(custom_result):
        return []

    fields: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def append_field(label: Any, raw_value: Any) -> None:
        normalized_label = str(label or "").strip()
        value = stringify_scalar_value(raw_value)
        if not normalized_label or not value:
            return
        key = (normalize_field_key(normalized_label), value)
        if key in seen:
            return
        seen.add(key)
        fields.append({"label": normalized_label, "value": value})

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if not isinstance(value, dict):
            return

        kv_pairs = value.get("kvPairs")
        if isinstance(kv_pairs, list):
            for pair in kv_pairs:
                if isinstance(pair, dict):
                    append_field(pair.get("key"), pair.get("value"))

        if "key" in value and "value" in value:
            append_field(value.get("key"), value.get("value"))
        if "label" in value and "value" in value:
            append_field(value.get("label"), value.get("value"))

        for key, item_value in value.items():
            if key in {"kvPairs", "key", "label", "value"}:
                continue
            if is_structural_custom_result_key(key):
                continue
            scalar_value = stringify_scalar_value(item_value)
            if scalar_value:
                append_field(key, scalar_value)

    collect(custom_result)
    return fields


def is_field_only_custom_result(custom_result: Any) -> bool:
    custom_result = normalize_custom_result_value(custom_result)
    if custom_result is None or custom_result_has_table_payload(custom_result):
        return False
    if isinstance(custom_result, list):
        return all(is_field_only_custom_result(item) for item in custom_result)
    if not isinstance(custom_result, dict):
        return False
    if not custom_result:
        return False

    for key, value in custom_result.items():
        if is_structural_custom_result_key(key):
            return False
        if key == "kvPairs":
            if not isinstance(value, list):
                return False
            for pair in value:
                if not isinstance(pair, dict) or not str(pair.get("key") or "").strip():
                    return False
                if pair.get("value") is not None and not stringify_scalar_value(pair.get("value")):
                    return False
            continue
        if key in {"key", "label"}:
            if not isinstance(value, (str, int, float, bool)) or not str(value).strip():
                return False
            continue
        if key == "value":
            if value is not None and not stringify_scalar_value(value):
                return False
            continue
        if value is not None and not stringify_scalar_value(value):
            return False
    return True


def custom_result_has_table_payload(value: Any) -> bool:
    value = normalize_custom_result_value(value)
    if isinstance(value, list):
        return any(custom_result_has_table_payload(item) for item in value)
    if not isinstance(value, dict):
        return False
    for key in value:
        if is_structural_custom_result_key(key):
            return True
    return False


def is_structural_custom_result_key(key: Any) -> bool:
    return normalize_field_key(str(key or "")) in STRUCTURAL_CUSTOM_RESULT_KEYS


def stringify_scalar_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        scalar_values = []
        for item in value:
            if item is None:
                continue
            if not isinstance(item, (str, int, float, bool)):
                return ""
            item_value = str(item).strip()
            if item_value:
                scalar_values.append(item_value)
        return " | ".join(scalar_values)
    return ""
