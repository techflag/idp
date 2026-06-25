# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Logical scope expansion for document-tree modules.

The persisted document tree is kept as the parser produced it.  This module
builds a runtime overlay for "node with children" scopes when parser levels are
flat but document-order headings still expose a recoverable hierarchy.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


_NUMERIC_PREFIX_RE = re.compile(r"^\s*(\d+(?:\s*[.]\s*\d+)+|\d+)(?=\s|[^\d]|$)")
_BRACKETED_MARKER_RE = re.compile(r"^\s*[\(\（\[\【]\s*([^\)\）\]\】]{1,12})\s*[\)\）\]\】]")


@dataclass(frozen=True)
class DocumentTreeScopeItem:
    module: dict[str, Any]
    selected_id: str
    reason: str
    reason_label: str

    @property
    def module_id(self) -> str:
        return str(self.module.get("id") or "")


@dataclass(frozen=True)
class DocumentTreeScopeBoundary:
    module: dict[str, Any]
    reason: str
    reason_label: str

    @property
    def module_id(self) -> str:
        return str(self.module.get("id") or "")


@dataclass(frozen=True)
class DocumentTreeScopeResolution:
    items: list[DocumentTreeScopeItem]
    boundaries: list[DocumentTreeScopeBoundary]
    warnings: list[str]

    @property
    def module_ids(self) -> list[str]:
        return [item.module_id for item in self.items if item.module_id]

    @property
    def pages(self) -> list[int]:
        values: set[int] = set()
        for item in self.items:
            for page in item.module.get("pages") or []:
                coerced = _coerce_positive_int(page)
                if coerced is not None:
                    values.add(coerced)
        return sorted(values)

    @property
    def block_ids(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for item in self.items:
            for block_id in _module_block_ids(item.module):
                if block_id in seen:
                    continue
                seen.add(block_id)
                values.append(block_id)
        return values

    def role_for(self, module_id: str) -> DocumentTreeScopeItem | None:
        for item in self.items:
            if item.module_id == module_id:
                return item
        return None

    def trace_payload(self) -> dict[str, Any]:
        return {
            "mode": "document_tree_logical_scope",
            "moduleIds": self.module_ids,
            "pages": self.pages,
            "blockIds": self.block_ids,
            "items": [
                {
                    "moduleId": item.module_id,
                    "title": str(item.module.get("title") or ""),
                    "selectedId": item.selected_id,
                    "reason": item.reason,
                    "reasonLabel": item.reason_label,
                }
                for item in self.items
            ],
            "boundaries": [
                {
                    "moduleId": boundary.module_id,
                    "title": str(boundary.module.get("title") or ""),
                    "reason": boundary.reason,
                    "reasonLabel": boundary.reason_label,
                }
                for boundary in self.boundaries
            ],
            "warnings": list(self.warnings),
        }


def expand_document_tree_modules(
    modules: list[dict[str, Any]] | Any,
    selected_ids: list[str],
) -> DocumentTreeScopeResolution:
    normalized_modules = [module for module in modules or [] if isinstance(module, dict)]
    if not normalized_modules or not selected_ids:
        return DocumentTreeScopeResolution(items=[], boundaries=[], warnings=[])

    by_id = {str(module.get("id") or ""): module for module in normalized_modules}
    collected: list[DocumentTreeScopeItem] = []
    boundaries: list[DocumentTreeScopeBoundary] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for selected_id in selected_ids:
        if selected_id not in by_id:
            warnings.append(f"selected_module_not_found:{selected_id}")
            continue
        expansion = expand_document_tree_module(normalized_modules, selected_id)
        boundaries.extend(expansion.boundaries)
        warnings.extend(expansion.warnings)
        for item in expansion.items:
            if item.module_id in seen:
                continue
            seen.add(item.module_id)
            collected.append(item)

    order = {str(module.get("id") or ""): index for index, module in enumerate(normalized_modules)}
    collected.sort(key=lambda item: order.get(item.module_id, 10**9))
    return DocumentTreeScopeResolution(items=collected, boundaries=boundaries, warnings=warnings)


def expand_document_tree_module(
    modules: list[dict[str, Any]],
    selected_id: str,
) -> DocumentTreeScopeResolution:
    selected_index = next(
        (index for index, module in enumerate(modules) if str(module.get("id") or "") == selected_id),
        None,
    )
    if selected_index is None:
        return DocumentTreeScopeResolution(
            items=[],
            boundaries=[],
            warnings=[f"selected_module_not_found:{selected_id}"],
        )

    selected = modules[selected_index]
    selected_vector = heading_number_vector(selected.get("title"))
    selected_path = _module_path(selected)
    selected_parent_path = selected_path[:-1]
    items = [
        DocumentTreeScopeItem(
            module=selected,
            selected_id=selected_id,
            reason="selected_node",
            reason_label="选中节点",
        )
    ]
    boundaries: list[DocumentTreeScopeBoundary] = []
    active_numeric_parent = selected_vector

    for module in modules[selected_index + 1 :]:
        title = module.get("title")
        vector = heading_number_vector(title)
        path = _module_path(module)
        same_parent_path = path[:-1] == selected_parent_path
        is_path_descendant = bool(selected_path and path[: len(selected_path)] == selected_path and len(path) > len(selected_path))
        is_numeric_descendant = bool(
            selected_vector
            and vector
            and len(vector) > len(selected_vector)
            and vector[: len(selected_vector)] == selected_vector
        )
        is_local_marker = has_local_heading_marker(title)

        if is_path_descendant:
            reason = "tree_path_descendant"
            reason_label = "原始文档树路径下级"
            if vector:
                active_numeric_parent = vector
        elif is_numeric_descendant:
            reason = "heading_number_descendant"
            reason_label = "编号层级属于选中节点下级"
            active_numeric_parent = vector
        elif selected_vector and is_local_marker and same_parent_path and active_numeric_parent:
            reason = "local_subheading_under_current_section"
            reason_label = "当前章节内的局部子标题"
        else:
            if selected_vector and vector:
                boundaries.append(
                    DocumentTreeScopeBoundary(
                        module=module,
                        reason="same_or_higher_heading_boundary",
                        reason_label="遇到同级或上级编号边界，停止扩展",
                    )
                )
                break
            if selected_path and path and not same_parent_path and not is_path_descendant:
                boundaries.append(
                    DocumentTreeScopeBoundary(
                        module=module,
                        reason="tree_path_boundary",
                        reason_label="遇到不同文档树路径边界，停止扩展",
                    )
                )
                break
            continue

        items.append(
            DocumentTreeScopeItem(
                module=module,
                selected_id=selected_id,
                reason=reason,
                reason_label=reason_label,
            )
        )

    return DocumentTreeScopeResolution(items=items, boundaries=boundaries, warnings=[])


def heading_number_vector(title: Any) -> tuple[int, ...] | None:
    match = _NUMERIC_PREFIX_RE.match(_normalize(title))
    if not match:
        return None
    raw = re.sub(r"\s+", "", match.group(1))
    try:
        return tuple(int(part) for part in raw.split("."))
    except ValueError:
        return None


def has_local_heading_marker(title: Any) -> bool:
    match = _BRACKETED_MARKER_RE.match(_normalize(title))
    if not match:
        return False
    marker = match.group(1).strip()
    return bool(marker) and len(marker) <= 12


def _module_path(module: dict[str, Any]) -> tuple[str, ...]:
    return tuple(_normalize(item) for item in (module.get("path") or []) if _normalize(item))


def _module_block_ids(module: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(str(item) for item in (module.get("blockIds") or []) if str(item).strip())
    content = module.get("content") if isinstance(module.get("content"), dict) else {}
    for key in ("texts", "tables"):
        for item in content.get(key) or []:
            if not isinstance(item, dict):
                continue
            values.extend(str(block_id) for block_id in (item.get("blockIds") or []) if str(block_id).strip())
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
