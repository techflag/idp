"""HTML table structure parser used before LLM semantic enrichment.

The parser is intentionally structural: it expands rowspan/colspan and derives
stable table views without relying on document-specific field keywords.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from typing import Any


TABLE_PARSER_VERSION = "html-table-parser-v1"
COMPLEX_TABLE_TODO_WARNING = "todo_complex_table_structure_review_required"


@dataclass
class _RawCell:
    text: str
    rowspan: int
    colspan: int
    tag: str
    source_row: int
    source_col: int


@dataclass
class _PlacedCell:
    cell_id: str
    text: str
    row: int
    col: int
    rowspan: int
    colspan: int
    tag: str
    source_row: int
    source_col: int


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.rows: list[list[_RawCell]] = []
        self._table_depth = 0
        self._current_row: list[_RawCell] | None = None
        self._current_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "table":
            self._table_depth += 1
            return
        if self._table_depth <= 0:
            return
        if normalized_tag == "tr":
            self._current_row = []
            return
        if normalized_tag in {"td", "th"} and self._current_row is not None:
            attrs_dict = {key.lower(): value for key, value in attrs}
            self._current_cell = {
                "tag": normalized_tag,
                "rowspan": _parse_span(attrs_dict.get("rowspan")),
                "colspan": _parse_span(attrs_dict.get("colspan")),
                "parts": [],
            }
            return
        if normalized_tag == "br" and self._current_cell is not None:
            self._current_cell["parts"].append("\n")
            return
        if normalized_tag == "img" and self._current_cell is not None:
            attrs_dict = {key.lower(): value for key, value in attrs}
            alt_text = str(attrs_dict.get("alt") or "").strip()
            if alt_text:
                self._current_cell["parts"].append(alt_text)

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell["parts"].append(data)

    def handle_entityref(self, name: str) -> None:
        if self._current_cell is not None:
            self._current_cell["parts"].append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._current_cell is not None:
            self._current_cell["parts"].append(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(
                _RawCell(
                    text=_normalize_cell_text("".join(self._current_cell["parts"])),
                    rowspan=int(self._current_cell["rowspan"]),
                    colspan=int(self._current_cell["colspan"]),
                    tag=str(self._current_cell["tag"]),
                    source_row=len(self.rows) + 1,
                    source_col=len(self._current_row) + 1,
                )
            )
            self._current_cell = None
            return
        if normalized_tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
            return
        if normalized_tag == "table" and self._table_depth > 0:
            self._table_depth -= 1


def parse_table_html(html: str, title: str = "") -> dict[str, Any]:
    """Parse a MinerU HTML table into structural JSON."""

    parser = _TableHTMLParser()
    parser.feed(str(html or ""))
    raw_rows = parser.rows
    logical_grid, placed_cells, cell_grid = _expand_spans(raw_rows)
    logical_grid = _normalize_grid_width(logical_grid)
    cell_grid = _normalize_grid_width(cell_grid)

    parse_warnings: list[str] = []
    if not raw_rows:
        parse_warnings.append("no_table_rows")
    complex_table_todo = _complex_table_todo(placed_cells)
    if complex_table_todo["required"]:
        parse_warnings.append(COMPLEX_TABLE_TODO_WARNING)

    record_view = _derive_record_table(logical_grid)
    full_grid_table = _derive_grid_display_table(logical_grid, cell_grid)
    kv_pairs = _derive_kv_pairs(logical_grid)
    structured_objects = _derive_structured_objects(logical_grid, title=title)
    display_table = (
        full_grid_table
        if structured_objects
        else _select_display_table(
            logical_grid=logical_grid,
            record_view=record_view,
            full_grid_table=full_grid_table,
            placed_cells=placed_cells,
            kv_pairs=kv_pairs,
        )
    )
    segments = _derive_segments(logical_grid)
    segments = _ensure_primary_record_segment(segments, rows=logical_grid, record_view=record_view)
    table_role = _infer_table_role(
        logical_grid=logical_grid,
        display_table=display_table,
        kv_pairs=kv_pairs,
        segments=segments,
        placed_cells=placed_cells,
    )

    return {
        "parserVersion": TABLE_PARSER_VERSION,
        "title": str(title or "").strip(),
        "tableRole": table_role,
        "logicalGrid": logical_grid,
        "cellGrid": cell_grid,
        "cells": [_placed_cell_to_dict(cell) for cell in placed_cells],
        "segments": segments,
        "canonicalTable": display_table,
        "displayTable": display_table,
        "kvPairs": kv_pairs,
        "structuredObjects": structured_objects,
        "parseWarnings": parse_warnings,
        "complexTableTodo": complex_table_todo,
    }


def _parse_span(value: str | None) -> int:
    try:
        parsed = int(str(value or "1").strip())
    except ValueError:
        return 1
    return max(parsed, 1)


def _normalize_cell_text(value: str) -> str:
    text = unescape(value or "").replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def _expand_spans(raw_rows: list[list[_RawCell]]) -> tuple[list[list[str]], list[_PlacedCell], list[list[str]]]:
    active: dict[int, tuple[_PlacedCell, int]] = {}
    logical_grid: list[list[str]] = []
    cell_grid: list[list[str]] = []
    placed_cells: list[_PlacedCell] = []

    for row_index, raw_row in enumerate(raw_rows, start=1):
        row_values: list[str] = []
        row_cell_ids: list[str] = []
        next_active: dict[int, tuple[_PlacedCell, int]] = {}
        raw_index = 0
        col_index = 0

        def has_active_at_or_after(col: int) -> bool:
            return any(active_col >= col for active_col in active)

        while raw_index < len(raw_row) or has_active_at_or_after(col_index):
            if col_index in active:
                placed_cell, remaining_rows = active[col_index]
                row_values.append(placed_cell.text)
                row_cell_ids.append(placed_cell.cell_id)
                if remaining_rows > 1:
                    next_active[col_index] = (placed_cell, remaining_rows - 1)
                col_index += 1
                continue

            if raw_index >= len(raw_row):
                row_values.append("")
                row_cell_ids.append("")
                col_index += 1
                continue

            raw_cell = raw_row[raw_index]
            raw_index += 1
            cell_id = f"r{raw_cell.source_row}c{raw_cell.source_col}"
            placed_cell = _PlacedCell(
                cell_id=cell_id,
                text=raw_cell.text,
                row=row_index,
                col=col_index + 1,
                rowspan=raw_cell.rowspan,
                colspan=raw_cell.colspan,
                tag=raw_cell.tag,
                source_row=raw_cell.source_row,
                source_col=raw_cell.source_col,
            )
            placed_cells.append(placed_cell)

            for offset in range(raw_cell.colspan):
                row_values.append(raw_cell.text)
                row_cell_ids.append(cell_id)
                if raw_cell.rowspan > 1:
                    next_active[col_index + offset] = (placed_cell, raw_cell.rowspan - 1)
            col_index += raw_cell.colspan

        logical_grid.append(_trim_trailing_empty(row_values))
        cell_grid.append(row_cell_ids[: len(logical_grid[-1])])
        active = next_active

    return logical_grid, placed_cells, cell_grid


def _normalize_grid_width(grid: list[list[str]]) -> list[list[str]]:
    if not grid:
        return []
    max_width = max((len(row) for row in grid), default=0)
    return [row + [""] * (max_width - len(row)) for row in grid]


def _trim_trailing_empty(row: list[str]) -> list[str]:
    trimmed = list(row)
    while trimmed and not str(trimmed[-1]).strip():
        trimmed.pop()
    return trimmed


def _placed_cell_to_dict(cell: _PlacedCell) -> dict[str, Any]:
    return {
        "id": cell.cell_id,
        "text": cell.text,
        "row": cell.row,
        "col": cell.col,
        "rowspan": cell.rowspan,
        "colspan": cell.colspan,
        "tag": cell.tag,
        "sourceRowIndex": cell.source_row,
        "sourceColIndex": cell.source_col,
    }


def _complex_table_todo(cells: list[_PlacedCell]) -> dict[str, Any]:
    complex_cells = [cell for cell in cells if cell.rowspan > 1 or cell.colspan > 1]
    return {
        "required": bool(complex_cells),
        "status": "todo" if complex_cells else "not_required",
        "reason": (
            "检测到合并单元格。当前版本会保留展开后的结构和来源信息，但复杂表格语义归属、"
            "多级表头含义和分组关系仍需后续专项处理。"
            if complex_cells
            else ""
        ),
        "cellCount": len(complex_cells),
        "hasRowspan": any(cell.rowspan > 1 for cell in complex_cells),
        "hasColspan": any(cell.colspan > 1 for cell in complex_cells),
        "sampleCells": [
            {
                "text": cell.text,
                "row": cell.row,
                "col": cell.col,
                "rowspan": cell.rowspan,
                "colspan": cell.colspan,
            }
            for cell in complex_cells[:8]
        ],
    }


def _derive_record_table(grid: list[list[str]]) -> dict[str, Any] | None:
    rows = [_trim_trailing_empty([str(cell).strip() for cell in row]) for row in grid]
    header_start = _find_header_start(rows)
    if header_start is None:
        return None

    header_end = _find_header_end(rows, header_start)

    data_end = _find_record_data_end(rows, header_start=header_start, header_end=header_end)
    data_rows = [_trim_trailing_empty(row) for row in rows[header_end:data_end] if _row_has_content(row)]
    if not data_rows:
        return None

    max_width = max(len(row) for row in [*rows[header_start:header_end], *data_rows])
    headers = _flatten_header_rows(rows[header_start:header_end], max_width)
    normalized_rows = [_pad_row(row, max_width) for row in data_rows]

    return {
        "headers": headers,
        "rows": normalized_rows,
        "_rowStart": header_start + 1,
        "_rowEnd": data_end,
    }


def _find_header_start(rows: list[list[str]]) -> int | None:
    best_index: int | None = None
    best_score = -1

    for index in range(len(rows)):
        row = rows[index]
        if not _row_looks_like_header(row):
            continue
        if _row_is_single_spanned_value(row):
            continue
        header_end = _find_header_end(rows, index)
        header_width = max((len(item) for item in rows[index:header_end]), default=0)
        if header_end >= len(rows) or not _row_can_be_record_data(rows[header_end], header_width=header_width):
            continue
        data_end = _find_record_data_end(rows, header_start=index, header_end=header_end)
        data_rows = [
            candidate
            for candidate in rows[header_end:data_end]
            if _row_can_be_record_data(candidate, header_width=header_width)
        ]
        if not data_rows:
            continue
        score = _score_header_candidate(rows, header_start=index, header_end=header_end, data_rows=data_rows)
        if score > best_score:
            best_score = score
            best_index = index

    return best_index


def _find_header_end(rows: list[list[str]], header_start: int) -> int:
    header_end = header_start + 1
    while header_end < len(rows) and header_end < header_start + 4:
        header_width = max((len(item) for item in rows[header_start:header_end]), default=0)
        if _row_can_be_record_data(rows[header_end], header_width=header_width):
            break
        if not _row_looks_like_header(rows[header_end]) and not _row_looks_like_header_continuation(rows[header_end]):
            break
        header_end += 1
    return header_end


def _score_header_candidate(
    rows: list[list[str]],
    *,
    header_start: int,
    header_end: int,
    data_rows: list[list[str]],
) -> int:
    width = max((len(row) for row in [*rows[header_start:header_end], *data_rows]), default=0)
    score = width + len(data_rows) * 4
    if header_start > 0 and _row_is_single_spanned_value(rows[header_start - 1]):
        score += 3
    if any(_row_has_large_repeated_span(row) for row in rows[header_start:header_end]):
        score -= 8
    return score


def _find_record_data_end(rows: list[list[str]], *, header_start: int, header_end: int) -> int:
    header_width = max((len(row) for row in rows[header_start:header_end]), default=0)
    index = header_end
    data_seen = False

    while index < len(rows):
        row = rows[index]
        if not _row_has_content(row):
            if data_seen:
                break
            index += 1
            continue

        if not _row_can_be_record_data(row, header_width=header_width):
            if data_seen:
                break
            return header_end

        if data_seen and _row_is_record_boundary(row, header_width=header_width):
            break

        if (
            data_seen
            and not _row_first_cell_starts_data(row)
            and _row_looks_like_header(row)
            and any(
                _row_starts_data_region(candidate)
                for candidate in rows[index + 1 : index + 4]
            )
        ):
            break

        data_seen = True
        index += 1

    return index


def _row_is_record_boundary(row: list[str], *, header_width: int) -> bool:
    if not _row_has_content(row):
        return True
    if _row_is_single_spanned_value(row):
        return True
    if _row_has_large_repeated_span(row):
        return True
    trimmed = _trim_trailing_empty(row)
    if header_width >= 4 and len(trimmed) <= max(1, header_width // 3):
        return True
    return False


def _row_can_be_record_data(row: list[str], *, header_width: int) -> bool:
    if not _row_has_content(row):
        return False
    if _row_is_single_spanned_value(row) or _row_has_large_repeated_span(row):
        return False
    unique_values = _unique_nonempty_values(row)
    if len(unique_values) < 2:
        return False
    if header_width >= 4 and len(unique_values) <= max(2, header_width // 3):
        return _row_is_sparse_placeholder_record(row, header_width=header_width)
    return True


def _row_is_sparse_placeholder_record(row: list[str], *, header_width: int) -> bool:
    trimmed = _trim_trailing_empty(row)
    if len(trimmed) < max(2, header_width // 2):
        return False
    substantive_values = [
        str(cell).strip()
        for cell in trimmed
        if str(cell).strip() and not _is_placeholder_value(str(cell).strip())
    ]
    if len(substantive_values) < 2:
        return False
    return _row_first_cell_starts_data(trimmed)


def _row_is_single_spanned_value(row: list[str]) -> bool:
    values = [str(cell).strip() for cell in row if str(cell).strip()]
    if len(values) < 3:
        return False
    unique_values = set(values)
    return len(unique_values) == 1


def _row_looks_like_header(row: list[str]) -> bool:
    cells = [cell for cell in row if str(cell).strip()]
    if len(cells) < 2:
        return False
    numeric_like = sum(1 for cell in cells if _looks_numeric_or_code(cell))
    long_cells = sum(1 for cell in cells if len(cell) > 80)
    return numeric_like <= max(1, len(cells) // 2) and long_cells == 0


def _row_has_large_repeated_span(row: list[str]) -> bool:
    values = [str(cell).strip() for cell in row]
    width = len(values)
    if width < 4:
        return False
    threshold = max(3, width // 2)
    current_value = ""
    current_count = 0
    for value in values:
        if _is_placeholder_value(value):
            current_value = ""
            current_count = 0
            continue
        if value and value == current_value:
            current_count += 1
        else:
            current_value = value
            current_count = 1 if value else 0
        if value and current_count >= threshold:
            return True
    return False


def _is_placeholder_value(value: str) -> bool:
    return str(value or "").strip() in {"-", "—", "–", "－"}


def _row_looks_like_header_continuation(row: list[str]) -> bool:
    cells = [cell for cell in row if str(cell).strip()]
    if not cells:
        return False
    first_cell = str(row[0]).strip() if row else ""
    if first_cell and _looks_numeric_or_code(first_cell):
        return False
    long_cells = sum(1 for cell in cells if len(cell) > 80)
    return long_cells == 0


def _row_first_cell_starts_data(row: list[str]) -> bool:
    first_cell = str(row[0]).strip() if row else ""
    return bool(first_cell and _looks_numeric_or_code(first_cell))


def _row_starts_data_region(row: list[str]) -> bool:
    cells = [cell for cell in row if str(cell).strip()]
    if len(cells) < 2:
        return False
    first = cells[0]
    numeric_like = sum(1 for cell in cells if _looks_numeric_or_code(cell))
    return _looks_numeric_or_code(first) or numeric_like >= max(2, len(cells) // 2)


def _looks_numeric_or_code(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[-+~]?\d+(?:[.,:：/~\-]\d+)*(?:%|[A-Za-z]+)?", text):
        return True
    if re.fullmatch(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", text):
        return True
    if re.search(r"\d", text) and re.search(r"[A-Za-z]", text) and not re.search(r"[\u4e00-\u9fff]", text) and len(text) <= 32:
        return True
    return False


def _flatten_header_rows(header_rows: list[list[str]], width: int) -> list[str]:
    headers: list[str] = []
    for col in range(width):
        parts: list[str] = []
        for row in header_rows:
            value = str(row[col] if col < len(row) else "").strip()
            if not value or value in parts:
                continue
            parts.append(value)
        headers.append(" / ".join(parts) if parts else f"列{col + 1}")
    return headers


def _pad_row(row: list[str], width: int) -> list[str]:
    return [str(cell).strip() for cell in row[:width]] + [""] * max(0, width - len(row))


def _select_display_table(
    *,
    logical_grid: list[list[str]],
    record_view: dict[str, Any] | None,
    full_grid_table: dict[str, Any],
    placed_cells: list[_PlacedCell],
    kv_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    if record_view is None:
        return full_grid_table

    content_row_count = len([row for row in logical_grid if _row_has_content(row)])
    max_width = max((len(row) for row in logical_grid), default=0)
    if kv_pairs and len(kv_pairs) >= max(1, content_row_count // 2) and max_width <= 8:
        return full_grid_table

    row_start = int(record_view.get("_rowStart") or 1)
    row_end = int(record_view.get("_rowEnd") or content_row_count)
    has_merged_cells = any(cell.rowspan > 1 or cell.colspan > 1 for cell in placed_cells)
    record_covers_whole_table = row_start <= 1 and row_end >= content_row_count
    if has_merged_cells and not record_covers_whole_table:
        return full_grid_table
    return _public_table(record_view)


def _public_table(table: dict[str, Any]) -> dict[str, Any]:
    result = {
        "headers": table.get("headers") if isinstance(table.get("headers"), list) else [],
        "rows": table.get("rows") if isinstance(table.get("rows"), list) else [],
    }
    title = str(table.get("title") or "").strip()
    if title:
        result["title"] = title
    return result


def _derive_grid_display_table(grid: list[list[str]], cell_grid: list[list[str]] | None = None) -> dict[str, Any]:
    rows = _collapse_grid_for_display(grid, cell_grid=cell_grid)
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return {"headers": [], "rows": []}
    return {
        "headers": [f"列{index + 1}" for index in range(width)],
        "rows": [_pad_row(row, width) for row in rows],
    }


def _collapse_grid_for_display(grid: list[list[str]], *, cell_grid: list[list[str]] | None) -> list[list[str]]:
    if cell_grid is None:
        return [_trim_trailing_empty([str(cell).strip() for cell in row]) for row in grid if _row_has_content(row)]

    rows: list[list[str]] = []
    consumed_cell_ids: set[str] = set()
    for row_index, row in enumerate(grid):
        if not _row_has_content(row):
            continue
        display_row: list[str] = []
        row_cell_ids = cell_grid[row_index] if row_index < len(cell_grid) else []
        for col_index, cell in enumerate(row):
            value = str(cell).strip()
            cell_id = str(row_cell_ids[col_index]).strip() if col_index < len(row_cell_ids) else ""
            if not value:
                display_row.append("")
                continue
            if cell_id and cell_id in consumed_cell_ids:
                display_row.append("")
                continue
            display_row.append(value)
            if cell_id:
                consumed_cell_ids.add(cell_id)
        rows.append(_trim_trailing_empty(display_row))
    return rows


def _derive_kv_pairs(grid: list[list[str]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for row_index, row in enumerate(grid, start=1):
        cells = [str(cell).strip() for cell in row if str(cell).strip()]
        if len(cells) < 2 or len(cells) % 2 != 0 or len(cells) > 8:
            continue
        candidate_pairs: list[tuple[str, str]] = []
        for index in range(0, len(cells), 2):
            key = cells[index].strip().strip(":：")
            value = cells[index + 1].strip()
            if not _looks_like_key(key) or not value:
                candidate_pairs = []
                break
            candidate_pairs.append((key, value))
        for key, value in candidate_pairs:
            dedupe_key = (key, value, row_index)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            pairs.append({"key": key, "value": value, "rowIndex": row_index})
    return pairs


def _derive_structured_objects(grid: list[list[str]], *, title: str = "") -> list[dict[str, Any]]:
    rows = [
        (row_index, _trim_trailing_empty([str(cell).strip() for cell in row]))
        for row_index, row in enumerate(grid, start=1)
        if _row_has_content(row)
    ]
    objects: list[dict[str, Any]] = []
    cursor = 0

    while cursor < len(rows):
        detected = _detect_kv_record_table(rows, cursor)
        if detected is None:
            cursor += 1
            continue

        structured_object, next_cursor = detected
        structured_object["id"] = f"structured-object-{len(objects) + 1}"
        if title and not structured_object.get("title"):
            structured_object["title"] = str(title).strip()
        objects.append(structured_object)
        cursor = max(next_cursor, cursor + 1)

    return objects


def _detect_kv_record_table(
    rows: list[tuple[int, list[str]]],
    start: int,
) -> tuple[dict[str, Any], int] | None:
    kv_rows: list[tuple[int, str, str]] = []
    index = start

    while index < len(rows):
        row_index, row = rows[index]
        if _row_is_two_column_header(row) and _has_two_column_detail_run(rows, index + 1):
            break
        if not _row_is_two_column_kv_prefix(row):
            break
        key = str(row[0]).strip().strip(":：")
        value = str(row[1]).strip()
        kv_rows.append((row_index, key, value))
        index += 1

    if not kv_rows or index >= len(rows):
        return None

    header_row_index, header_row = rows[index]
    if not _row_is_two_column_header(header_row):
        return None
    headers = [str(header_row[0]).strip(), str(header_row[1]).strip()]

    data_rows: list[tuple[int, list[str]]] = []
    previous_row_index = header_row_index
    index += 1

    while index < len(rows):
        row_index, row = rows[index]
        if data_rows and row_index > previous_row_index + 1:
            break
        if not _row_is_two_column_detail_data(row):
            break
        data_rows.append((row_index, [str(row[0]).strip(), str(row[1]).strip()]))
        previous_row_index = row_index
        index += 1

    if len(data_rows) < 2:
        return None

    kv = {key: value for _, key, value in kv_rows if key and value}
    if not kv:
        return None

    return (
        {
            "title": "",
            "type": "kv_record_table",
            "kv": kv,
            "table": [
                {headers[0]: row[0], headers[1]: row[1]}
                for _, row in data_rows
            ],
            "source": "parser",
            "evidenceRefs": [],
            "parserMeta": {
                "parserVersion": TABLE_PARSER_VERSION,
                "rowStart": kv_rows[0][0],
                "rowEnd": data_rows[-1][0],
                "headerRowIndex": header_row_index,
                "kvCount": len(kv),
                "rowCount": len(data_rows),
                "columnCount": len(headers),
                "headers": headers,
            },
        },
        index,
    )


def _row_is_two_column_kv_prefix(row: list[str]) -> bool:
    cells = _trim_trailing_empty([str(cell).strip() for cell in row])
    if len(cells) != 2:
        return False
    key, value = cells
    if not key or not value:
        return False
    return _looks_like_key(key)


def _row_is_two_column_header(row: list[str]) -> bool:
    cells = _trim_trailing_empty([str(cell).strip() for cell in row])
    if len(cells) != 2:
        return False
    left, right = cells
    if not left or not right or left == right:
        return False
    return _looks_like_key(left) and _looks_like_key(right)


def _row_is_two_column_detail_data(row: list[str]) -> bool:
    cells = _trim_trailing_empty([str(cell).strip() for cell in row])
    if len(cells) != 2:
        return False
    left, right = cells
    if not left or not right:
        return False
    if _row_is_two_column_header(cells):
        return False
    return _looks_numeric_or_code(left) or _looks_numeric_or_code(right) or not _looks_like_key(left)


def _has_two_column_detail_run(rows: list[tuple[int, list[str]]], start: int) -> bool:
    matched = 0
    previous_row_index: int | None = None
    index = start

    while index < len(rows):
        row_index, row = rows[index]
        if previous_row_index is not None and matched > 0 and row_index > previous_row_index + 1:
            break
        if not _row_is_two_column_detail_data(row):
            break
        matched += 1
        previous_row_index = row_index
        if matched >= 2:
            return True
        index += 1

    return False


def _looks_like_key(value: str) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 40:
        return False
    if _looks_numeric_or_code(text):
        return False
    digit_count = sum(1 for char in text if char.isdigit())
    return digit_count < max(3, len(text) // 2)


def _derive_segments(grid: list[list[str]]) -> list[dict[str, Any]]:
    rows = [_trim_trailing_empty([str(cell).strip() for cell in row]) for row in grid]
    segments: list[dict[str, Any]] = []
    current_title = ""
    index = 0

    while index < len(rows):
        row = rows[index]
        if not _row_has_content(row):
            index += 1
            continue

        unique_values = _unique_nonempty_values(row)
        if len(unique_values) == 1 and len(unique_values[0]) <= 80:
            current_title = unique_values[0]
            segments.append({"kind": "section", "title": current_title, "rowIndex": index + 1})
            index += 1
            continue

        if _row_looks_like_header(row):
            header_start = index
            header_end = _find_header_end(rows, header_start)
            header_width = max((len(item) for item in rows[header_start:header_end]), default=0)
            if header_end >= len(rows) or not _row_can_be_record_data(rows[header_end], header_width=header_width):
                index += 1
                continue

            data_end = header_end
            while data_end < len(rows):
                candidate = rows[data_end]
                if not _row_has_content(candidate):
                    data_end += 1
                    continue
                if data_end > header_end and _row_is_record_boundary(candidate, header_width=header_width):
                    break
                if (
                    data_end > header_end
                    and not _row_first_cell_starts_data(candidate)
                    and _row_looks_like_header(candidate)
                    and any(
                        _row_starts_data_region(next_row)
                        for next_row in rows[data_end + 1 : data_end + 4]
                    )
                ):
                    break
                data_end += 1

            data_rows = [row for row in rows[header_end:data_end] if _row_has_content(row)]
            if data_rows:
                width = max(len(item) for item in [*rows[header_start:header_end], *data_rows])
                segments.append(
                    {
                        "kind": "records",
                        "title": current_title,
                        "rowStart": header_start + 1,
                        "rowEnd": data_end,
                        "headers": _flatten_header_rows(rows[header_start:header_end], width),
                        "rows": [_pad_row(item, width) for item in data_rows],
                    }
                )
                index = data_end
                continue

        index += 1

    if not segments and any(_row_has_content(row) for row in rows):
        display_table = _derive_grid_display_table(rows)
        segments.append(
            {
                "kind": "grid",
                "title": "",
                "headers": display_table["headers"],
                "rows": display_table["rows"],
            }
        )
    return segments


def _ensure_primary_record_segment(
    segments: list[dict[str, Any]],
    *,
    rows: list[list[str]],
    record_view: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if record_view is None or not record_view.get("rows"):
        return segments

    public_record = _public_table(record_view)
    signature = json_like_signature(public_record.get("headers"), public_record.get("rows"))
    primary_start = int(record_view.get("_rowStart") or 1)
    primary_end = int(record_view.get("_rowEnd") or primary_start)

    filtered_segments: list[dict[str, Any]] = []
    has_primary = False
    for segment in segments:
        if segment.get("kind") != "records":
            filtered_segments.append(segment)
            continue
        if json_like_signature(segment.get("headers"), segment.get("rows")) == signature:
            has_primary = True
            filtered_segments.append(segment)
            continue
        segment_start = _coerce_positive_int(segment.get("rowStart"))
        segment_end = _coerce_positive_int(segment.get("rowEnd"))
        if segment_start and segment_end and segment_start < primary_start and segment_end >= primary_end:
            continue
        filtered_segments.append(segment)

    if has_primary:
        return filtered_segments

    table_rows = [_trim_trailing_empty([str(cell).strip() for cell in row]) for row in rows]
    title = _find_section_title_before(table_rows, row_start=primary_start)
    return [
        *filtered_segments,
        {
            "kind": "records",
            "title": title,
            "rowStart": primary_start,
            "rowEnd": primary_end,
            "headers": public_record["headers"],
            "rows": public_record["rows"],
        },
    ]


def _coerce_positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _find_section_title_before(rows: list[list[str]], *, row_start: int) -> str:
    start_index = max(0, row_start - 2)
    stop_index = max(-1, start_index - 4)
    for index in range(start_index, stop_index, -1):
        unique_values = _unique_nonempty_values(rows[index])
        if len(unique_values) == 1 and len(unique_values[0]) <= 120:
            return unique_values[0]
    return ""


def json_like_signature(headers: object, rows: object) -> str:
    return repr((headers, rows))


def _row_has_content(row: list[str]) -> bool:
    return any(str(cell).strip() for cell in row)


def _unique_nonempty_values(row: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for cell in row:
        value = str(cell).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _infer_table_role(
    *,
    logical_grid: list[list[str]],
    display_table: dict[str, Any],
    kv_pairs: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    placed_cells: list[_PlacedCell],
) -> str:
    row_count = len([row for row in logical_grid if _row_has_content(row)])
    col_count = max((len(row) for row in logical_grid), default=0)
    if row_count == 0 or col_count == 0:
        return "layout_table"
    if kv_pairs and len(kv_pairs) >= max(1, row_count // 2) and col_count <= 4:
        return "kv_table"
    if any(cell.rowspan > 1 or cell.colspan > 1 for cell in placed_cells) and len(segments) > 1:
        return "sectioned_table"
    header_count = len(display_table.get("headers") or [])
    if header_count >= 4 and row_count >= 3:
        if any(" / " in str(header) for header in display_table.get("headers") or []):
            return "matrix_table"
        return "record_table"
    if len(segments) > 1:
        return "sectioned_table"
    return "mixed_table"
