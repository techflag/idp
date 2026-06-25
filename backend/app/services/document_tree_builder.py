# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Build neutral document-tree artifacts from parsed document content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from app.services.document_tree_scope import heading_number_vector, has_local_heading_marker


TEXT_SEPARATOR = "<|txt_split|>"
SPECIAL_TYPES = {"table", "chart", "image", "seal", "image_block"}
SUPPLEMENT_TYPES = {"page_title", "page_number", "page_footnote", "header", "aside_text", "footer"}
IGNORED_MODULE_TYPES = {"root", "header", "footer", "page_number", "page_footnote"}


@dataclass(frozen=True)
class DocumentTreeBuildResult:
    tree: dict[str, Any]
    treeText: str
    modules: list[dict[str, Any]]
    dispatchPlan: dict[str, Any]


class TableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.merge_descriptions: list[dict[str, Any]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._row_index = -1
        self._col_index = 0
        self._cell_start_col = 0
        self._cell_rowspan = 1
        self._cell_colspan = 1
        self._pending_rowspans: dict[tuple[int, int], str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
            self._row_index += 1
            self._col_index = 0
        elif tag in {"td", "th"}:
            self._advance_pending_rowspans()
            self._cell = []
            self._cell_start_col = self._col_index
            self._cell_rowspan = _span_attr(attrs, "rowspan")
            self._cell_colspan = _span_attr(attrs, "colspan")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            value = normalize_text("".join(self._cell))
            for offset in range(self._cell_colspan):
                self._row.append(value)
                if self._cell_rowspan > 1:
                    for row_offset in range(1, self._cell_rowspan):
                        self._pending_rowspans[(self._row_index + row_offset, self._cell_start_col + offset)] = value
            if self._cell_rowspan > 1 or self._cell_colspan > 1:
                self.merge_descriptions.append(
                    _merge_description(
                        row=self._row_index + 1,
                        column=self._cell_start_col + 1,
                        row_span=self._cell_rowspan,
                        col_span=self._cell_colspan,
                        text=value,
                    )
                )
            self._col_index += self._cell_colspan
            self._cell = None
            return
        if tag == "tr" and self._row is not None:
            self._advance_pending_rowspans()
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def _advance_pending_rowspans(self) -> None:
        if self._row is None:
            return
        while (self._row_index, self._col_index) in self._pending_rowspans:
            self._row.append(self._pending_rowspans.pop((self._row_index, self._col_index)))
            self._col_index += 1


class DocumentTreeBuilder:
    def build(self, *, task_id: str, content_payload: Any) -> DocumentTreeBuildResult:
        elements = _content_payload_to_elements(content_payload)
        tree = _build_tree(elements)
        table_lookup = _build_table_lookup(elements)
        modules = extract_modules(tree, table_lookup)
        dispatch_plan = build_dispatch_plan(modules)
        return DocumentTreeBuildResult(
            tree=tree,
            treeText=build_tree_text(tree),
            modules=modules,
            dispatchPlan={
                "taskId": task_id,
                **dispatch_plan,
            },
        )


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace(TEXT_SEPARATOR, "\n")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_table(html: str) -> list[list[str]]:
    return parse_table_details(html)["rows"]


def parse_table_details(html: str) -> dict[str, Any]:
    parser = TableTextParser()
    parser.feed(html or "")
    return {
        "rows": parser.rows,
        "mergeDescriptions": parser.merge_descriptions,
    }


def _span_attr(attrs: list[tuple[str, str | None]], name: str) -> int:
    for key, value in attrs:
        if key.lower() != name:
            continue
        try:
            parsed = int(value or "1")
        except ValueError:
            return 1
        return max(parsed, 1)
    return 1


def _merge_description(row: int, column: int, row_span: int, col_span: int, text: str) -> dict[str, Any]:
    parts: list[str] = []
    if row_span > 1:
        parts.append(f"纵向合并 {row_span} 行")
    if col_span > 1:
        parts.append(f"横向合并 {col_span} 列")
    value = text or "空白"
    return {
        "row": row,
        "column": column,
        "rowSpan": row_span,
        "colSpan": col_span,
        "text": text,
        "description": f"第 {row} 行第 {column} 列“{value}”" + (f"，{'，'.join(parts)}" if parts else ""),
    }


def _content_payload_to_elements(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []

    raw_items: list[tuple[dict[str, Any], int]] = []
    if all(isinstance(page, list) for page in payload):
        for page_index, page_items in enumerate(payload):
            if not isinstance(page_items, list):
                continue
            for raw in page_items:
                if isinstance(raw, dict):
                    raw_items.append((raw, page_index))
    else:
        for raw in payload:
            if isinstance(raw, dict):
                raw_items.append((raw, _page_index_from_item(raw)))

    elements: list[dict[str, Any]] = []
    for order, (raw, fallback_page_index) in enumerate(raw_items, start=1):
        element = _raw_item_to_element(raw, fallback_page_index=fallback_page_index, order=order)
        if element:
            elements.append(element)
    return elements


def _raw_item_to_element(raw: dict[str, Any], *, fallback_page_index: int, order: int) -> dict[str, Any] | None:
    raw_type = normalize_text(raw.get("type")).lower() or "paragraph"
    page_no = _page_no_from_item(raw, fallback_page_index)
    bbox = _bbox_from_item(raw)
    block_id = raw.get("id") or raw.get("block_id") or raw.get("blockId") or raw.get("block_position") or order
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    source_label = normalize_text(raw.get("source_label") or raw.get("sourceLabel")).lower()

    element_type = "text"
    text = ""
    level: int | None = None
    raw_html = ""
    title = ""

    if raw_type == "title":
        element_type = "title"
        text = _text_from_parts(content.get("title_content") if isinstance(content, dict) else None)
        text = text or _first_text(raw, "text", "title", "content")
        level = _coerce_int(content.get("level") if isinstance(content, dict) else None) or _coerce_int(raw.get("text_level")) or 1
    elif raw_type == "text":
        text = _first_text(raw, "text", "content", "title")
        level = _coerce_int(raw.get("text_level"))
        element_type = "title" if level and level > 0 else _source_label_to_type(source_label) or "text"
    elif raw_type == "paragraph":
        text = _text_from_parts(content.get("paragraph_content") if isinstance(content, dict) else None)
        text = text or _first_text(raw, "text", "content")
    elif raw_type == "list":
        element_type = "list"
        text = _list_text(content)
        text = text or _first_text(raw, "text", "content")
    elif raw_type == "table":
        element_type = "table"
        raw_html = _first_text(raw, "table_body", "html", "content_html")
        if isinstance(content, dict):
            raw_html = raw_html or normalize_text(content.get("html"))
            title = _text_from_parts(content.get("table_caption"))
        title = title or _text_from_parts(raw.get("table_caption")) or _first_text(raw, "text", "caption", "title")
        text = title or _table_fallback_title(raw_html)
    elif raw_type in {"page_header", "header"}:
        element_type = "header"
        text = _text_from_parts(content.get("page_header_content") if isinstance(content, dict) else None)
        text = text or _first_text(raw, "text", "content")
    elif raw_type in {"page_footer", "footer"}:
        element_type = "footer"
        text = _text_from_parts(content.get("page_footer_content") if isinstance(content, dict) else None)
        text = text or _first_text(raw, "text", "content")
    elif raw_type == "page_number":
        element_type = "page_number"
        text = _text_from_parts(content.get("page_number_content") if isinstance(content, dict) else None)
        text = text or _first_text(raw, "text", "content")
    elif raw_type in SPECIAL_TYPES:
        element_type = raw_type
        text = _first_text(raw, "text", "caption", "title", "content")
    else:
        text = _first_text(raw, "text", "content", "title")

    text = normalize_text(text)
    if not text and not raw_html:
        return None

    element: dict[str, Any] = {
        "id": block_id,
        "order": order,
        "type": element_type,
        "content": text,
        "title": title or text,
        "level": level or -1,
        "bbox": bbox,
        "page": page_no,
        "image": raw.get("image") if raw.get("image") is not None else -1,
        "contd": _coerce_int(raw.get("contd")) or -1,
        "source_label": source_label,
    }
    if raw_html:
        table_details = parse_table_details(raw_html)
        element["rawHtml"] = raw_html
        element["rows"] = table_details["rows"]
        element["mergeDescriptions"] = table_details["mergeDescriptions"]
    return element


def _source_label_to_type(source_label: str) -> str | None:
    return {
        "page_title": "page_title",
        "number": "page_number",
        "page_number": "page_number",
        "footnote": "page_footnote",
        "page_footnote": "page_footnote",
        "aside_text": "aside_text",
        "header": "header",
        "footer": "footer",
    }.get(source_label)


def _build_tree(elements: list[dict[str, Any]]) -> dict[str, Any]:
    text_components = _get_text_components(elements)
    infer_document_tree_heading_levels(text_components)
    root = _component("root", level=0)
    root["children"] = []
    stack: list[dict[str, Any]] = [{"node": root, "level": 0}]

    for component in text_components:
        component["children"] = []
        level = component["level"] if isinstance(component.get("level"), int) and component["level"] > 0 else 100
        while len(stack) > 1 and stack[-1]["level"] >= level:
            stack.pop()
        stack[-1]["node"]["children"].append(component)
        stack.append({"node": component, "level": level})

    _add_special_elements(root, elements)
    _add_supplement_nodes(root, elements)
    return root


def normalize_document_tree_hierarchy(tree: dict[str, Any]) -> dict[str, Any]:
    """Repair recoverable heading hierarchy in an existing document tree.

    Parser output can flatten numbered headings when the upstream OCR provider
    emits the same text level for every heading.  The repair is intentionally
    structural: it only reads heading markers and document order, then keeps the
    original nodes, content, block ids, bboxes, tables, and pages intact.
    """
    if not isinstance(tree, dict):
        return tree
    _repair_node_children_hierarchy(tree)
    return tree


def infer_document_tree_heading_levels(components: list[dict[str, Any]]) -> None:
    base = _numbered_heading_base(components)
    if base is None:
        infer_visual_heading_levels(components)
        return
    base_vector_len, base_level = base
    active_numeric_level: int | None = None

    for component in components:
        if not isinstance(component, dict):
            continue
        title = normalize_text(component.get("title"))
        vector = heading_number_vector(title)
        if vector:
            inferred_level = base_level + max(len(vector) - base_vector_len, 0)
            component["level"] = max(1, inferred_level)
            active_numeric_level = int(component["level"])
            continue
        if active_numeric_level is not None and has_local_heading_marker(title):
            component["level"] = active_numeric_level + 1


def infer_visual_heading_levels(components: list[dict[str, Any]]) -> None:
    """Infer hierarchy when OCR marks headings but emits flat levels.

    Some OCR providers correctly distinguish ``type=title`` but assign the same
    level to every title.  The tree builder keeps that upstream title signal and
    uses neutral layout cues to recover a usable hierarchy: centered headings are
    treated as section roots, left-aligned headings as children, and subtitle-like
    consecutive headings with no body under the first heading become one level
    deeper.  This is intentionally generic and does not read business words.
    """
    candidates = [
        component
        for component in components
        if isinstance(component, dict)
        and normalize_text(component.get("title"))
        and str(component.get("type") or "").lower() not in SUPPLEMENT_TYPES | IGNORED_MODULE_TYPES
    ]
    if len(candidates) < 3:
        return

    page_width = _estimate_page_width(components)
    if page_width <= 0:
        return

    positive_levels = [
        level
        for level in (_coerce_int(component.get("level")) for component in candidates)
        if level is not None and level > 0
    ]
    if len(set(positive_levels)) > 1:
        return

    base_level = min(positive_levels) if positive_levels else 1
    if not _has_mixed_heading_alignment(candidates, page_width):
        return

    previous_heading: dict[str, Any] | None = None
    for component in candidates:
        title_bbox = _first_location_bbox(component)
        if not title_bbox:
            continue
        if _is_centered_heading_bbox(title_bbox, page_width):
            component["level"] = base_level
        else:
            inferred_level = base_level + 1
            if previous_heading is not None and _looks_like_consecutive_subtitle(previous_heading, component):
                previous_level = _coerce_int(previous_heading.get("level")) or inferred_level
                inferred_level = previous_level + 1
            component["level"] = inferred_level
        previous_heading = component


def _estimate_page_width(components: list[dict[str, Any]]) -> float:
    max_x = 0.0
    for component in components:
        if not isinstance(component, dict):
            continue
        for location in component.get("location") or []:
            if not isinstance(location, dict):
                continue
            bbox = location.get("bbox")
            if isinstance(bbox, list) and len(bbox) >= 3:
                try:
                    max_x = max(max_x, float(bbox[2]))
                except (TypeError, ValueError):
                    continue
    return max_x


def _first_location_bbox(component: dict[str, Any]) -> list[float]:
    for location in component.get("location") or []:
        if not isinstance(location, dict):
            continue
        bbox = location.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        values: list[float] = []
        for item in bbox[:4]:
            try:
                values.append(float(item))
            except (TypeError, ValueError):
                values = []
                break
        if values:
            return values
    return []


def _is_centered_heading_bbox(bbox: list[float], page_width: float) -> bool:
    if page_width <= 0 or len(bbox) < 4:
        return False
    left, _top, right, _bottom = bbox[:4]
    width = max(right - left, 0)
    center = left + width / 2
    center_distance_ratio = abs(center - page_width / 2) / page_width
    left_ratio = left / page_width
    width_ratio = width / page_width
    return center_distance_ratio <= 0.16 and left_ratio >= 0.18 and width_ratio <= 0.72


def _has_mixed_heading_alignment(components: list[dict[str, Any]], page_width: float) -> bool:
    centered = 0
    non_centered = 0
    for component in components:
        bbox = _first_location_bbox(component)
        if not bbox:
            continue
        if _is_centered_heading_bbox(bbox, page_width):
            centered += 1
        else:
            non_centered += 1
    return centered > 0 and non_centered > 0


def _looks_like_consecutive_subtitle(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    previous_content = normalize_text(previous.get("content"))
    if previous_content:
        return False

    previous_locations = previous.get("location") if isinstance(previous.get("location"), list) else []
    current_locations = current.get("location") if isinstance(current.get("location"), list) else []
    previous_page = _first_location_page(previous_locations)
    current_page = _first_location_page(current_locations)
    if previous_page and current_page and previous_page != current_page:
        return False

    previous_bbox = _first_location_bbox(previous)
    current_bbox = _first_location_bbox(current)
    if not previous_bbox or not current_bbox:
        return False
    vertical_gap = current_bbox[1] - previous_bbox[3]
    if vertical_gap < -1 or vertical_gap > 32:
        return False

    previous_title = normalize_text(previous.get("title"))
    current_title = normalize_text(current.get("title"))
    if not previous_title or not current_title:
        return False
    if len(current_title) >= max(len(previous_title) + 6, len(previous_title) * 2):
        return True
    return current_title.endswith(("：", ":", "如下", "如下：", "如下:"))


def _first_location_page(locations: Any) -> int | None:
    if not isinstance(locations, list):
        return None
    for location in locations:
        if not isinstance(location, dict):
            continue
        page = location.get("page")
        if isinstance(page, int) and page > 0:
            return page
    return None


def _numbered_heading_base(components: list[dict[str, Any]]) -> tuple[int, int] | None:
    candidates: list[tuple[int, int]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        vector = heading_number_vector(component.get("title"))
        raw_level = _coerce_int(component.get("level"))
        if not vector or raw_level is None or raw_level <= 0:
            continue
        candidates.append((len(vector), raw_level))
    if not candidates:
        return None
    base_vector_len = min(vector_len for vector_len, _raw_level in candidates)
    base_level = min(raw_level for vector_len, raw_level in candidates if vector_len == base_vector_len)
    return base_vector_len, base_level


def _repair_node_children_hierarchy(node: dict[str, Any]) -> None:
    children = [child for child in (node.get("children") or []) if isinstance(child, dict)]
    if not children:
        return

    base = _numbered_heading_base(children)
    if base is not None:
        infer_document_tree_heading_levels(children)
        node["children"] = _nest_heading_children(children, _coerce_int(node.get("level")) or 0)
    else:
        before_levels = [_coerce_int(child.get("level")) for child in children]
        infer_visual_heading_levels(children)
        after_levels = [_coerce_int(child.get("level")) for child in children]
        if after_levels != before_levels:
            node["children"] = _nest_heading_children(children, _coerce_int(node.get("level")) or 0)

    for child in node.get("children") or []:
        if isinstance(child, dict):
            _repair_node_children_hierarchy(child)


def _nest_heading_children(children: list[dict[str, Any]], parent_level: int) -> list[dict[str, Any]]:
    nested: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = [{"node": {"children": nested}, "level": parent_level}]

    for child in children:
        child_type = str(child.get("type") or "").lower()
        if child_type in SUPPLEMENT_TYPES or child_type in IGNORED_MODULE_TYPES - {"root"}:
            nested.append(child)
            continue

        level = _coerce_int(child.get("level"))
        if level is None or level <= 0:
            stack[-1]["node"].setdefault("children", []).append(child)
            continue

        while len(stack) > 1 and stack[-1]["level"] >= level:
            stack.pop()
        stack[-1]["node"].setdefault("children", []).append(child)
        stack.append({"node": child, "level": level})

    return nested


def _get_text_components(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    current = _component("text", title="文档内容", level=1)

    for element in elements:
        element_type = element.get("type")
        if element_type == "title" and _coerce_int(element.get("level")) is not None and int(element["level"]) < 0:
            element_type = "text"

        if element_type == "title":
            if current["title"] != "文档内容" or current["content"]:
                components.append(current)
            current = _component(
                "text",
                title=element.get("content") or "未命名标题",
                level=_coerce_int(element.get("level")) or 1,
                location=[_location_for(element)],
                block_ids=[element.get("id")],
            )
            continue

        if element_type in SPECIAL_TYPES or element_type in SUPPLEMENT_TYPES:
            continue

        content = normalize_text(element.get("content"))
        if not content:
            continue
        separator = "\n" if not current["content"] else TEXT_SEPARATOR
        current["content"] = f"{current['content']}{separator}{content}" if current["content"] else content
        current["location"].append(_location_for(element))
        current["block_ids"].append(element.get("id"))

    if current["title"] != "文档内容" or current["content"]:
        components.append(current)
    return components


def _add_special_elements(root: dict[str, Any], elements: list[dict[str, Any]]) -> None:
    title_orders = [element["order"] for element in elements if element.get("type") == "title"]
    for element in elements:
        if element.get("type") not in SPECIAL_TYPES:
            continue
        visual_component = _component(
            str(element.get("type") or "table"),
            title=normalize_text(element.get("title")),
            content=normalize_text(element.get("content")),
            level=_coerce_int(element.get("image")) or -1,
            location=[_location_for(element)],
            block_ids=[element.get("id")],
        )
        if element.get("rawHtml"):
            visual_component["rawHtml"] = element["rawHtml"]
        if element.get("rows"):
            visual_component["rows"] = element["rows"]
        if element.get("mergeDescriptions"):
            visual_component["mergeDescriptions"] = element["mergeDescriptions"]
        visual_component["children"] = []

        parent = _find_node_by_block_id(root, element.get("image"))
        if parent is None:
            parent = _find_node_by_block_id(root, _nearest_previous_title_id(elements, element["order"], title_orders))
        if parent is None:
            parent = root
        parent.setdefault("children", []).append(visual_component)


def _add_supplement_nodes(root: dict[str, Any], elements: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for element in elements:
        if element.get("type") not in SUPPLEMENT_TYPES:
            continue
        node_type = str(element.get("type"))
        title = f"Page {element.get('page')} - {node_type}"
        counter = 0
        while title in seen:
            counter += 1
            title = f"Page {element.get('page')} - {node_type} - {counter}"
        seen.add(title)
        root.setdefault("children", []).append(
            _component(
                node_type,
                title=title,
                metadata=normalize_text(element.get("content")),
                content=normalize_text(element.get("content")),
                location=[_location_for(element)],
                block_ids=[element.get("id")],
            )
        )


def _component(
    component_type: str,
    *,
    title: str = "",
    metadata: str = "",
    content: str = "",
    level: int = -1,
    location: list[dict[str, Any]] | None = None,
    block_ids: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": component_type,
        "title": title,
        "metadata": metadata,
        "content": content,
        "level": level,
        "location": location or [],
        "block_ids": block_ids or [],
    }


def _location_for(element: dict[str, Any]) -> dict[str, Any]:
    return {"bbox": element.get("bbox") or [], "page": element.get("page")}


def _find_node_by_block_id(node: dict[str, Any], block_id: Any) -> dict[str, Any] | None:
    if block_id is None or block_id == -1:
        return None
    if block_id in (node.get("block_ids") or []):
        return node
    for child in node.get("children") or []:
        if isinstance(child, dict):
            found = _find_node_by_block_id(child, block_id)
            if found is not None:
                return found
    return None


def _nearest_previous_title_id(elements: list[dict[str, Any]], order: int, title_orders: list[int]) -> Any | None:
    previous_orders = [candidate for candidate in title_orders if candidate < order]
    if not previous_orders:
        return None
    previous_order = max(previous_orders)
    for element in elements:
        if element.get("order") == previous_order:
            return element.get("id")
    return None


def _build_table_lookup(elements: list[dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    tables: dict[tuple[int, str], dict[str, Any]] = {}
    for element in elements:
        if element.get("type") != "table":
            continue
        title = normalize_text(element.get("title") or element.get("content"))
        raw_html = str(element.get("rawHtml") or "")
        if not title or not raw_html:
            continue
        page_no = _coerce_int(element.get("page")) or 0
        tables[(page_no, title)] = {
            "title": title,
            "rawHtml": raw_html,
            "rows": element.get("rows") or parse_table(raw_html),
            "mergeDescriptions": element.get("mergeDescriptions") or [],
            "pages": [page_no] if page_no else [],
            "bbox": element.get("bbox"),
        }
    return tables


def collect_pages(node: dict[str, Any]) -> list[int]:
    pages: set[int] = set()

    def walk(current: dict[str, Any]) -> None:
        for location in current.get("location") or []:
            page = location.get("page") if isinstance(location, dict) else None
            if isinstance(page, int) and page > 0:
                pages.add(page)
        for child in current.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(node)
    return sorted(pages)


def collect_direct_pages(node: dict[str, Any]) -> list[int]:
    pages: set[int] = set()
    for location in node.get("location") or []:
        page = location.get("page") if isinstance(location, dict) else None
        if isinstance(page, int) and page > 0:
            pages.add(page)
    return sorted(pages)


def find_source_table(
    current: dict[str, Any],
    table_lookup: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, Any] | None:
    if not table_lookup:
        return None
    title = normalize_text(current.get("content") or current.get("title"))
    for page in collect_pages(current) or [0]:
        found = table_lookup.get((page, title))
        if found:
            return found
    return None


def collect_content(node: dict[str, Any], table_lookup: dict[tuple[int, str], dict[str, Any]]) -> dict[str, Any]:
    texts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    def walk(current: dict[str, Any]) -> None:
        node_type = current.get("type")
        title = normalize_text(current.get("title"))
        content = normalize_text(current.get("content"))

        if node_type == "table":
            source_table = find_source_table(current, table_lookup)
            raw_html = source_table["rawHtml"] if source_table else str(current.get("rawHtml") or "")
            rows = source_table["rows"] if source_table else (current.get("rows") or parse_table(raw_html))
            if rows:
                tables.append(
                    {
                        "title": source_table["title"] if source_table else content or title,
                        "rows": rows,
                        "mergeDescriptions": source_table.get("mergeDescriptions") if source_table else current.get("mergeDescriptions") or [],
                        "rawHtml": raw_html,
                        "pages": source_table["pages"] if source_table and source_table["pages"] else collect_pages(current),
                        "blockIds": current.get("block_ids") or [],
                        "bbox": source_table.get("bbox") if source_table else None,
                    }
                )
        elif title or content:
            texts.append(
                {
                    "title": title,
                    "content": content,
                    "type": node_type,
                    "level": current.get("level"),
                    "pages": collect_pages(current),
                    "blockIds": current.get("block_ids") or [],
                }
            )

        for child in current.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(node)
    return {"texts": texts, "tables": tables}


def collect_direct_content(node: dict[str, Any], table_lookup: dict[tuple[int, str], dict[str, Any]]) -> dict[str, Any]:
    node_type = node.get("type")
    title = normalize_text(node.get("title"))
    content = normalize_text(node.get("content"))
    texts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    if node_type == "table":
        source_table = find_source_table(node, table_lookup)
        raw_html = source_table["rawHtml"] if source_table else str(node.get("rawHtml") or "")
        rows = source_table["rows"] if source_table else (node.get("rows") or parse_table(raw_html))
        if rows:
            tables.append(
                {
                    "title": source_table["title"] if source_table else content or title,
                        "rows": rows,
                        "mergeDescriptions": source_table.get("mergeDescriptions") if source_table else node.get("mergeDescriptions") or [],
                        "rawHtml": raw_html,
                    "pages": source_table["pages"] if source_table and source_table["pages"] else collect_pages(node),
                    "blockIds": node.get("block_ids") or [],
                    "bbox": source_table.get("bbox") if source_table else None,
                }
            )
    elif title or content:
        texts.append(
            {
                "title": title,
                "content": content,
                "type": node_type,
                "level": node.get("level"),
                "pages": collect_direct_pages(node),
                "blockIds": node.get("block_ids") or [],
            }
        )
    return {"texts": texts, "tables": tables}


def extract_modules(tree: dict[str, Any], table_lookup: dict[tuple[int, str], dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    table_lookup = table_lookup or {}

    def walk(node: dict[str, Any], path: list[str]) -> None:
        title = normalize_text(node.get("title"))
        node_type = node.get("type")
        next_path = path + ([title] if title else [])

        if title and node_type not in IGNORED_MODULE_TYPES:
            content = collect_content(node, table_lookup)
            direct_content = collect_direct_content(node, table_lookup)
            if content["texts"] or content["tables"]:
                modules.append(
                    {
                        "id": f"module_{len(modules) + 1:03d}",
                        "title": title,
                        "path": next_path,
                        "type": node_type,
                        "level": node.get("level"),
                        "pages": collect_pages(node),
                        "blockIds": node.get("block_ids") or [],
                        "summary": build_summary(content),
                        "directSummary": build_summary(direct_content),
                        "directContent": direct_content,
                        "content": content,
                        "skillInput": build_skill_input(title, next_path, content),
                        "directSkillInput": build_skill_input(title, next_path, direct_content),
                    }
                )

        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, next_path)

    walk(tree, [])
    return modules


def build_dispatch_plan(modules: list[dict[str, Any]]) -> dict[str, Any]:
    data_blocks: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    for module in modules:
        is_whole_document = len(module["path"]) == 1 and len(module["pages"]) > 1
        if is_whole_document:
            continue

        data_block = {
            "dataBlockId": module["id"],
            "dataTypeName": module["title"],
            "source": {
                "kind": "document_tree_node",
                "path": module["path"],
                "pages": module["pages"],
                "blockIds": module["blockIds"],
            },
            "inputPreview": module["summary"],
            "skillInputFile": f"skill_inputs/{module['id']}_{safe_filename(module['title'])}.md",
        }
        data_blocks.append(data_block)
        steps.append(
            {
                "stepId": f"step_{len(steps) + 1:03d}",
                "name": f"{module['title']}提取",
                "kind": "extraction",
                "input": {
                    "fromDataBlock": module["id"],
                    "scope": "document_tree_node_with_children",
                },
                "output": {
                    "target": "extracted_result",
                    "dataTypeName": module["title"],
                    "format": "kv_or_table_or_record_list_with_evidence",
                },
                "dispatchReason": "该步骤由文档结构节点自动生成，运行时使用树节点和子内容作为输入，不按固定页码或关键词扫描全文。",
                "confidence": 0.9 if module["content"]["tables"] or module["content"]["texts"] else 0.6,
            }
        )

    return {
        "planType": "document_tree_driven_skill_dispatch",
        "principles": [
            "数据类型来自文档结构节点或用户命名，不写死在代码里。",
            "Skill 输入来自树节点及其子内容，不把整份长 PDF 塞给每个 Skill。",
            "页码只作为证据，不作为唯一匹配条件。",
        ],
        "dataBlocks": data_blocks,
        "steps": steps,
    }


def build_summary(content: dict[str, Any]) -> str:
    text_count = len(content["texts"])
    table_count = len(content["tables"])
    previews: list[str] = []
    for item in content["texts"][:3]:
        preview = item["content"] or item["title"]
        if preview:
            previews.append(preview[:80])
    for table in content["tables"][:2]:
        table_title = normalize_text(table.get("title")) or "表格"
        rows = table.get("rows") or []
        previews.append(f"{table_title}：{len(rows)} 行")
    return f"{text_count} 个文本节点，{table_count} 个表格。" + (" " + " / ".join(previews) if previews else "")


def table_to_markdown(rows: list[list[str]], max_rows: int = 12) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows[:max_rows]]
    header = normalized[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n... 省略 {len(rows) - max_rows} 行")
    return "\n".join(lines)


def build_skill_input(title: str, path: list[str], content: dict[str, Any]) -> str:
    lines = [
        f"模块：{title}",
        f"路径：{' / '.join(path)}",
        "",
        "## 文本",
    ]
    for item in content["texts"]:
        value = item["content"] or item["title"]
        if value:
            pages = ",".join(map(str, item["pages"])) or "-"
            lines.append(f"- 第 {pages} 页：{value}")

    if content["tables"]:
        lines.append("")
        lines.append("## 表格")
    for index, table in enumerate(content["tables"], start=1):
        pages = ",".join(map(str, table["pages"])) or "-"
        table_title = table.get("title") or f"表格 {index}"
        lines.append(f"\n### {table_title}（第 {pages} 页）")
        lines.append(table_to_markdown(table["rows"]))

    return "\n".join(lines).strip() + "\n"


def build_tree_text(tree: dict[str, Any]) -> str:
    lines: list[str] = []

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        title = normalize_text(node.get("title")) or "ROOT"
        content = normalize_text(node.get("content"))
        preview = content[:60] + ("..." if len(content) > 60 else "")
        lines.append(f"{' ' * (depth * 4)}{title}|{preview}")
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, depth + 1)

    walk(tree)
    return "\n".join(lines) + "\n"


def safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", value).strip("_") or "module"


def _page_index_from_item(raw: dict[str, Any]) -> int:
    page_idx = _coerce_int(raw.get("page_idx"))
    if page_idx is not None:
        return max(page_idx, 0)
    page_no = _coerce_int(raw.get("page_no") or raw.get("pageNo") or raw.get("page"))
    if page_no is not None and page_no > 0:
        return page_no - 1
    return 0


def _page_no_from_item(raw: dict[str, Any], fallback_page_index: int) -> int:
    page_idx = _coerce_int(raw.get("page_idx"))
    if page_idx is not None:
        return page_idx + 1
    page_no = _coerce_int(raw.get("page_no") or raw.get("pageNo") or raw.get("page"))
    if page_no is not None and page_no > 0:
        return page_no
    return fallback_page_index + 1


def _bbox_from_item(raw: dict[str, Any]) -> list[float]:
    bbox = raw.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return []
    values: list[float] = []
    for item in bbox[:4]:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            return []
    return values


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _first_text(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        text = _text_from_parts(value)
        if text:
            return text
    return ""


def _text_from_parts(parts: Any) -> str:
    if isinstance(parts, str):
        return normalize_text(parts)
    if isinstance(parts, list):
        values: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                values.append(_text_from_parts(part.get("content") or part.get("text") or part.get("item_content")))
            else:
                values.append(_text_from_parts(part))
        return normalize_text(" ".join(value for value in values if value))
    if isinstance(parts, dict):
        return _text_from_parts(parts.get("content") or parts.get("text") or parts.get("item_content"))
    return ""


def _list_text(content: Any) -> str:
    if not isinstance(content, dict):
        return ""
    lines: list[str] = []
    for index, list_item in enumerate(content.get("list_items") or [], start=1):
        if not isinstance(list_item, dict):
            continue
        value = _text_from_parts(list_item.get("item_content"))
        if value:
            lines.append(f"{index}. {value}")
    return "\n".join(lines)


def _table_fallback_title(raw_html: str) -> str:
    rows = parse_table(raw_html)
    if not rows:
        return "表格"
    first_row = " / ".join(cell for cell in rows[0] if cell)
    return first_row[:80] if first_row else "表格"
