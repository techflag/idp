"""Extraction skill registry and compact MinerU facts helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.config import AppSettings
from app.domain.models import BusinessSkillRecord
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import BusinessSkillConfigField, ExtractionSkillDetail
from app.services.skill_loader import (
    as_string_list,
    extract_markdown_rules,
    parse_skill_markdown,
)
from app.services.oss import OssStorageService
from app.services.skill_text_store import (
    build_skill_text_asset,
    read_skill_text_asset,
    strip_stored_skill_text,
    upload_skill_text_asset,
)
from app.services.table_parser import parse_table_html


ALLOWED_EXTRACTION_EXECUTORS = {"llm_structured"}
ALLOWED_INPUT_BUILDERS = {"page_compact", "table_grid_only", "text_only"}
INPUT_BUILDER_ALIASES = {
    "document": "page_compact",
    "document_text": "page_compact",
    "document_compact": "page_compact",
    "full_document": "page_compact",
    "full_document_text": "page_compact",
    "full_text": "page_compact",
    "page_text": "text_only",
    "ocr_text": "text_only",
    "table_only": "table_grid_only",
    "table_grid": "table_grid_only",
}
ALLOWED_OUTPUT_TYPES = {
    "field_list",
    "data_table",
    "kv_table",
    "kv_record_table",
    "record_collection",
    "custom",
}
ALLOWED_SKILL_STATUSES = {"draft", "active", "disabled", "deprecated"}


@dataclass
class ExtractionSkillRecord:
    id: str
    version: str
    name: str
    category: str = "extraction"
    status: str = "active"
    sourceTypes: list[str] = field(default_factory=list)
    executor: str = "llm_structured"
    inputBuilder: str = "page_compact"
    renderer: str = "auto"
    configSchema: dict[str, Any] = field(default_factory=dict)
    outputSchema: dict[str, Any] = field(default_factory=dict)
    summaryTemplate: str = ""
    promptTemplate: str = ""
    rules: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    skillTextObjectKey: str = ""
    skillTextHash: str = ""
    skillTextSizeBytes: int = 0
    skillTextPreview: str = ""
    skillText: str = ""
    enabled: bool = True
    customerId: str | None = None
    tags: list[str] = field(default_factory=list)
    latestTestStatus: str | None = None
    sampleCount: int = 0
    testRunCount: int = 0
    lastTestedAt: str | None = None
    createdBy: str | None = None
    updatedBy: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class ExtractionSkillRegistry:
    def __init__(
        self,
        *,
        repository: WorkbenchRepository,
        settings: AppSettings,
        oss_service: OssStorageService | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._oss_service = oss_service

    def list_skills(self, *, customer_id: str | None = None, include_inactive: bool = False) -> list[ExtractionSkillDetail]:
        records_by_id: dict[str, ExtractionSkillRecord] = {}
        for record in self._load_platform_skills():
            if include_inactive or _is_active_skill(record):
                records_by_id.setdefault(record.id, record)
        if customer_id:
            customer_seen: set[str] = set()
            for record in self._list_customer_skills_safely(customer_id):
                if record.executor not in ALLOWED_EXTRACTION_EXECUTORS:
                    continue
                if (include_inactive or _is_active_skill(record)) and record.id not in customer_seen:
                    records_by_id[record.id] = record
                    customer_seen.add(record.id)
        return [
            self._to_detail(record, include_text=False)
            for record in sorted(records_by_id.values(), key=lambda item: item.name)
            if include_inactive or _is_active_skill(record)
        ]

    def list_skills_for_customers(self, *, customer_ids: list[str], include_inactive: bool = False) -> list[ExtractionSkillDetail]:
        scoped_records = [
            _from_business_skill_record(record)
            for record in self._list_business_skills_for_customers_safely(customer_ids)
            if record.category == "extraction"
        ]
        platform_records = [
            record
            for record in scoped_records
            if record.customerId is None and record.executor in ALLOWED_EXTRACTION_EXECUTORS
        ]

        records_by_key: dict[str, ExtractionSkillRecord] = {}
        for record in platform_records:
            if include_inactive or _is_active_skill(record):
                records_by_key.setdefault(f"platform:{record.id}", record)
        for record in scoped_records:
            if record.customerId and (include_inactive or _is_active_skill(record)) and record.executor in ALLOWED_EXTRACTION_EXECUTORS:
                records_by_key.setdefault(f"{record.customerId}:{record.id}", record)

        return [
            self._to_detail(record, include_text=False)
            for record in sorted(records_by_key.values(), key=lambda item: (item.customerId or "", item.name))
        ]

    def resolve_skill(
        self,
        *,
        skill_id: str,
        customer_id: str | None = None,
        version: str | None = None,
    ) -> ExtractionSkillRecord:
        candidates: list[ExtractionSkillRecord] = []
        if customer_id:
            candidates.extend(
                item
                for item in self._list_customer_skills_safely(customer_id)
                if item.id == skill_id and _is_active_skill(item) and item.executor in ALLOWED_EXTRACTION_EXECUTORS
            )
        candidates.extend(item for item in self._load_platform_skills() if item.id == skill_id and _is_active_skill(item))
        if version:
            candidates = [item for item in candidates if item.version == version]
        if not candidates:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction skill not found")
        return self._with_loaded_skill_text(candidates[0])

    def get_detail(
        self,
        *,
        skill_id: str,
        scope: str,
        customer_id: str | None = None,
        include_text: bool = True,
        include_inactive: bool = False,
    ) -> ExtractionSkillDetail:
        return self._to_detail(
            self._get_exact_skill(
                skill_id=skill_id,
                scope=scope,
                customer_id=customer_id,
                include_inactive=include_inactive,
            ),
            include_text=include_text,
        )

    def parse_markdown(self, skill_text: str, *, customer_id: str | None = None) -> ExtractionSkillRecord:
        return parse_extraction_skill_markdown(skill_text, customer_id=customer_id)

    def save_customer_skill(self, skill_text: str, *, customer_id: str, updated_by: Optional[str] = None) -> ExtractionSkillDetail:
        record = self.parse_markdown(skill_text, customer_id=customer_id)
        if updated_by:
            record = replace(record, createdBy=updated_by, updatedBy=updated_by)
        record = self._with_uploaded_skill_text(record)
        saved = self._repository.save_business_skill(_to_business_skill_record(record))
        return self._to_detail(self._with_loaded_skill_text(_from_business_skill_record(saved)), include_text=True)

    def _load_platform_skills(self) -> list[ExtractionSkillRecord]:
        return [
            _from_business_skill_record(record)
            for record in self._list_platform_skills_safely()
            if record.category == "extraction"
        ]

    def _get_exact_skill(
        self,
        *,
        skill_id: str,
        scope: str,
        customer_id: str | None,
        include_inactive: bool = False,
    ) -> ExtractionSkillRecord:
        if scope == "customer":
            if not customer_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="读取客户 Skill 必须提供 customerId。")
            candidates = [
                item
                for item in self._list_customer_skills_safely(customer_id)
                if item.id == skill_id and (include_inactive or _is_active_skill(item)) and item.executor in ALLOWED_EXTRACTION_EXECUTORS
            ]
        elif scope == "platform":
            candidates = [
                item
                for item in self._load_platform_skills()
                if item.id == skill_id and (include_inactive or _is_active_skill(item))
            ]
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope 只支持 platform 或 customer。")
        if not candidates:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction skill not found")
        return self._with_loaded_skill_text(candidates[0])

    def _list_customer_skills_safely(self, customer_id: str) -> list[ExtractionSkillRecord]:
        try:
            return [
                _from_business_skill_record(record)
                for record in self._repository.list_business_skills(customer_id)
                if record.category == "extraction"
            ]
        except (ProgrammingError, OperationalError) as exc:
            if "business_skills" in str(exc):
                return []
            raise

    def _list_business_skills_for_customers_safely(self, customer_ids: list[str]) -> list[BusinessSkillRecord]:
        try:
            list_for_customers = getattr(self._repository, "list_business_skills_for_customers", None)
            if callable(list_for_customers):
                return list_for_customers(customer_ids)
            records = list(self._repository.list_business_skills(None))
            for customer_id in customer_ids:
                records.extend(self._repository.list_business_skills(customer_id))
            return records
        except (ProgrammingError, OperationalError) as exc:
            if "business_skills" in str(exc):
                return []
            raise

    def _list_platform_skills_safely(self) -> list[BusinessSkillRecord]:
        try:
            return self._repository.list_business_skills(None)
        except (ProgrammingError, OperationalError) as exc:
            if "business_skills" in str(exc):
                return []
            raise

    def _with_uploaded_skill_text(self, record: ExtractionSkillRecord) -> ExtractionSkillRecord:
        skill_text = record.skillText
        if not skill_text.strip():
            return record
        try:
            asset = upload_skill_text_asset(
                storage=self._oss_service,
                customer_id=record.customerId,
                kind="extraction",
                skill_id=record.id,
                version=record.version,
                skill_text=skill_text,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"OSS 未配置，无法保存 SKILL.md：{exc}",
            ) from exc
        return replace(
            record,
            defaults=strip_stored_skill_text(record.defaults),
            skillTextObjectKey=asset.objectKey,
            skillTextHash=asset.sha256,
            skillTextSizeBytes=asset.sizeBytes,
            skillTextPreview=asset.preview,
            skillText=skill_text,
        )

    def _with_loaded_skill_text(self, record: ExtractionSkillRecord) -> ExtractionSkillRecord:
        if record.skillText:
            return record
        if record.skillTextObjectKey:
            try:
                return replace(record, skillText=read_skill_text_asset(storage=self._oss_service, object_key=record.skillTextObjectKey))
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"OSS 未配置，无法读取 SKILL.md：{exc}",
                ) from exc
        return record

    def _to_detail(self, record: ExtractionSkillRecord, *, include_text: bool = True) -> ExtractionSkillDetail:
        config_schema = {
            key: BusinessSkillConfigField.model_validate(value)
            for key, value in (record.configSchema or {}).items()
            if isinstance(value, dict)
        }
        return ExtractionSkillDetail(
            id=record.id,
            version=record.version,
            name=record.name,
            category=record.category,
            sourceTypes=record.sourceTypes,
            customerScope="customer" if record.customerId else "platform",
            scope="customer" if record.customerId else "platform",
            customerId=record.customerId,
            enabled=record.enabled,
            status=_normalize_record_status(record),
            tags=list(record.tags or []),
            executor=record.executor,
            inputBuilder=record.inputBuilder,
            renderer=record.renderer,
            configSchema=config_schema,
            outputSchema=record.outputSchema,
            summaryTemplate=record.summaryTemplate,
            promptTemplate=record.promptTemplate,
            rules=record.rules,
            examples=record.examples,
            defaults=strip_stored_skill_text(record.defaults),
            latestTestStatus=record.latestTestStatus,
            sampleCount=record.sampleCount,
            testRunCount=record.testRunCount,
            lastTestedAt=record.lastTestedAt,
            createdBy=record.createdBy,
            updatedBy=record.updatedBy,
            createdAt=record.createdAt,
            skillText=record.skillText if include_text else "",
            skillTextObjectKey=record.skillTextObjectKey,
            skillTextHash=record.skillTextHash,
            skillTextSizeBytes=record.skillTextSizeBytes,
            skillTextPreview=record.skillTextPreview,
            updatedAt=record.updatedAt,
        )


def parse_extraction_skill_markdown(skill_text: str, *, customer_id: str | None = None) -> ExtractionSkillRecord:
    parsed = parse_skill_markdown(skill_text)
    payload = parsed.frontmatter

    required_fields = ["id", "version", "name", "kind", "executor", "output"]
    missing = [field for field in required_fields if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError(f"缺少必填字段：{', '.join(missing)}。")
    if str(payload.get("kind") or "").strip() != "extraction":
        raise ValueError("结构化解析 Skill 的 kind 必须是 extraction。")

    executor = str(payload.get("executor") or "").strip()
    skill_status = _status_from_payload(payload)
    raw_input = payload.get("input")
    input_payload = raw_input if isinstance(raw_input, dict) else {}
    input_builder = _normalize_input_builder(
        str(payload.get("inputBuilder") or input_payload.get("builder") or "page_compact")
    )
    if executor not in ALLOWED_EXTRACTION_EXECUTORS:
        raise ValueError(f"executor 不支持：{executor}。")
    if input_builder not in ALLOWED_INPUT_BUILDERS:
        raise ValueError(f"inputBuilder 不支持：{input_builder}。")

    config_schema = payload.get("configSchema") or {}
    if not isinstance(config_schema, dict):
        raise ValueError("configSchema 必须是对象。")
    for key, value in config_schema.items():
        if not isinstance(value, dict):
            raise ValueError(f"configSchema.{key} 必须是对象。")
        BusinessSkillConfigField.model_validate(value)

    output_schema = payload.get("outputSchema") or payload.get("output") or {}
    if not isinstance(output_schema, dict):
        raise ValueError("output 必须是对象。")
    output_type = str(output_schema.get("type") or "").strip()
    if output_type and output_type not in ALLOWED_OUTPUT_TYPES:
        raise ValueError(f"outputSchema.type 不支持：{output_type}。")

    asset = build_skill_text_asset(skill_text=parsed.text)

    return ExtractionSkillRecord(
        id=str(payload["id"]).strip(),
        version=str(payload["version"]).strip(),
        name=str(payload["name"]).strip(),
        category=str(payload.get("category") or "extraction").strip(),
        status=skill_status,
        sourceTypes=as_string_list(payload.get("sourceTypes") or input_payload.get("include")),
        executor=executor,
        inputBuilder=input_builder,
        renderer=str(payload.get("renderer") or "auto").strip(),
        configSchema=config_schema,
        outputSchema=output_schema,
        summaryTemplate=str(payload.get("summaryTemplate") or "").strip(),
        promptTemplate=parsed.body or str(payload.get("promptTemplate") or "").strip(),
        rules=as_string_list(payload.get("rules")) or extract_markdown_rules(parsed.body),
        examples=[item for item in (payload.get("examples") or []) if isinstance(item, dict)]
        if isinstance(payload.get("examples") or [], list)
        else [],
        defaults=strip_stored_skill_text(payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}),
        skillTextHash=asset.sha256,
        skillTextSizeBytes=asset.sizeBytes,
        skillTextPreview=asset.preview,
        skillText=parsed.text,
        enabled=skill_status == "active",
        customerId=customer_id,
        tags=as_string_list(payload.get("tags")),
    )


def _normalize_input_builder(value: str) -> str:
    input_builder = str(value or "page_compact").strip()
    return INPUT_BUILDER_ALIASES.get(input_builder, input_builder)


def merge_extraction_skill_config(skill: ExtractionSkillRecord, config: dict[str, Any] | None) -> dict[str, Any]:
    merged = {
        key: value
        for key, value in (skill.defaults or {}).items()
        if not str(key).startswith("_")
    }
    if isinstance(config, dict):
        merged.update(config)
    for key, field in (skill.configSchema or {}).items():
        if key not in merged and isinstance(field, dict) and "default" in field:
            merged[key] = field.get("default")
    return merged


def build_compact_extraction_facts(
    *,
    pages: list[Any],
    input_builder: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence_index: dict[str, Any] = {"pages": []}
    fact_pages: list[dict[str, Any]] = []
    include_text = input_builder in {"page_compact", "text_only"}
    include_tables = input_builder in {"page_compact", "table_grid_only"}

    for page in pages:
        fact_blocks: list[dict[str, Any]] = []
        evidence_blocks: list[dict[str, Any]] = []
        for ordinal, block in enumerate(getattr(page, "blocks", []) or []):
            source_ordinal = f"p{page.pageNo}-b{ordinal}"
            block_type = str(getattr(block, "type", "") or "").lower()
            content = str(getattr(block, "content", "") or "")
            html_content = str(getattr(block, "htmlContent", "") or "")
            title = str(getattr(block, "title", "") or "")
            fact: dict[str, Any] | None = None
            table_html = content if "<table" in content.lower() else html_content
            table_grid = (
                _build_table_grid(table_html, title=title)
                if block_type == "table" and "<table" in table_html.lower()
                else None
            )
            if include_tables and table_grid is not None:
                fact = {
                    "type": "table",
                    "title": title,
                    "tableGrid": table_grid,
                }
            elif include_text and content.strip() and block_type != "table":
                fact = {
                    "type": block_type or "text",
                    "title": title,
                    "text": content.strip(),
                }
            fact_index: int | None = None
            if fact is not None:
                fact_index = len(fact_blocks)
                fact_blocks.append(fact)
            evidence_blocks.append(
                _build_evidence_index_block(
                    source_ordinal=source_ordinal,
                    block=block,
                    page_no=page.pageNo,
                    block_type=block_type,
                    title=title,
                    content=content,
                    html_content=html_content,
                    table_grid=table_grid,
                    fact_index=fact_index,
                )
            )
        fact_pages.append({"pageNo": page.pageNo, "title": getattr(page, "title", ""), "blocks": fact_blocks})
        evidence_index["pages"].append({"pageNo": page.pageNo, "blocks": evidence_blocks})

    return {"pages": fact_pages}, evidence_index


def _build_evidence_index_block(
    *,
    source_ordinal: str,
    block: Any,
    page_no: int,
    block_type: str,
    title: str,
    content: str,
    html_content: str,
    table_grid: dict[str, Any] | None,
    fact_index: int | None,
) -> dict[str, Any]:
    ignored_by_default, ignore_reason = _default_evidence_ignore_reason(block_type=block_type, title=title)
    evidence: dict[str, Any] = {
        "id": source_ordinal,
        "sourceOrdinal": source_ordinal,
        "sourceType": _normalize_evidence_source_type(block_type),
        "blockId": getattr(block, "id", ""),
        "blockPosition": getattr(block, "blockPosition", ""),
        "pageNo": getattr(block, "pageNo", page_no),
        "bbox": list(getattr(block, "bbox", ()) or ()),
        "title": title.strip(),
        "nearbyTitle": title.strip(),
        "excerpt": (title or content or html_content).strip()[:200],
        "shapeSignals": _table_shape_signals(table_grid) if table_grid is not None else _text_shape_signals(content),
        "originalRefs": {
            "pageNo": getattr(block, "pageNo", page_no),
            "blockId": getattr(block, "id", ""),
            "blockPosition": getattr(block, "blockPosition", ""),
            "factBlockIndex": fact_index,
        },
        "includedInFacts": fact_index is not None,
        "ignoredByDefault": ignored_by_default,
        "uncertainties": _table_uncertainties(table_grid) if table_grid is not None else [],
    }
    if ignore_reason:
        evidence["ignoreReason"] = ignore_reason
    if table_grid is not None:
        evidence["headerCandidates"] = _table_header_candidates(table_grid)
        evidence["rowTextSummary"] = _table_row_text_summary(table_grid)
    return evidence


def _normalize_evidence_source_type(block_type: str) -> str:
    normalized = str(block_type or "").strip().lower()
    if normalized == "table":
        return "table"
    if normalized in {"list", "ordered_list", "unordered_list"}:
        return "list"
    if normalized:
        return normalized
    return "text"


def _default_evidence_ignore_reason(*, block_type: str, title: str) -> tuple[bool, str]:
    normalized = f"{block_type} {title}".strip().lower()
    layout_markers = (
        "header",
        "footer",
        "watermark",
        "page_number",
        "page-number",
        "page number",
        "页眉",
        "页脚",
        "页码",
        "水印",
    )
    for marker in layout_markers:
        if marker in normalized:
            return True, "layout_artifact"
    return False, ""


def _text_shape_signals(content: str) -> dict[str, Any]:
    text = str(content or "")
    lines = [line for line in text.splitlines() if line.strip()]
    return {
        "charCount": len(text),
        "lineCount": len(lines),
        "hasText": bool(text.strip()),
    }


def _table_shape_signals(table_grid: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(table_grid, dict):
        return {}
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    normalized_rows = [
        [str(cell or "") for cell in row]
        for row in rows
        if isinstance(row, list)
    ]
    row_widths = [len(row) for row in normalized_rows if row]
    total_cells = sum(len(row) for row in normalized_rows)
    empty_cells = sum(1 for row in normalized_rows for cell in row if not str(cell).strip())
    deduped_rows = table_grid.get("dedupedRows") if isinstance(table_grid.get("dedupedRows"), list) else []
    repeated_cell_rows = 0
    for row, deduped in zip(normalized_rows, deduped_rows):
        if isinstance(deduped, list) and len(deduped) < len(row):
            repeated_cell_rows += 1
    return {
        "rowCount": int(table_grid.get("rowCount") or len(normalized_rows)),
        "columnCount": int(table_grid.get("columnCount") or max(row_widths or [0])),
        "minColumnCount": min(row_widths or [0]),
        "maxColumnCount": max(row_widths or [0]),
        "emptyCellRatio": round(empty_cells / total_cells, 4) if total_cells else 0,
        "repeatedCellRowCount": repeated_cell_rows,
        "largeTable": len(normalized_rows) >= 24,
    }


def _table_header_candidates(table_grid: dict[str, Any] | None) -> list[list[str]]:
    if not isinstance(table_grid, dict):
        return []
    rows = table_grid.get("dedupedRows") if isinstance(table_grid.get("dedupedRows"), list) else []
    candidates: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        normalized = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
        if normalized:
            candidates.append(normalized[:12])
        if len(candidates) >= 2:
            break
    return candidates


def _table_row_text_summary(table_grid: dict[str, Any] | None) -> list[str]:
    if not isinstance(table_grid, dict):
        return []
    row_texts = [
        str(item or "").strip()
        for item in (table_grid.get("rowTexts") or [])
        if str(item or "").strip()
    ]
    if len(row_texts) <= 10:
        return [text[:240] for text in row_texts]
    return [text[:240] for text in row_texts[:8]] + [text[:240] for text in row_texts[-2:]]


def _table_uncertainties(table_grid: dict[str, Any] | None) -> list[str]:
    if not isinstance(table_grid, dict):
        return []
    signals = _table_shape_signals(table_grid)
    uncertainties: list[str] = []
    if not _table_header_candidates(table_grid):
        uncertainties.append("missing_header_candidate")
    if signals.get("largeTable"):
        uncertainties.append("large_table")
    if int(signals.get("minColumnCount") or 0) != int(signals.get("maxColumnCount") or 0):
        uncertainties.append("ragged_rows")
    if float(signals.get("emptyCellRatio") or 0) >= 0.4:
        uncertainties.append("many_empty_cells")
    if int(signals.get("repeatedCellRowCount") or 0) > 0:
        uncertainties.append("repeated_cells")
    for warning in table_grid.get("parseWarnings") or []:
        text = str(warning or "").strip()
        if text and text not in uncertainties:
            uncertainties.append(text)
    complex_table = table_grid.get("complexTableTodo")
    if isinstance(complex_table, dict) and complex_table.get("required"):
        if "complex_table_structure_review_required" not in uncertainties:
            uncertainties.append("complex_table_structure_review_required")
    return uncertainties


def _build_table_grid(html: str, *, title: str = "") -> dict[str, Any]:
    parsed = parse_table_html(html, title=title)
    logical_grid = parsed.get("logicalGrid") if isinstance(parsed.get("logicalGrid"), list) else []
    rows = [
        [str(cell) for cell in row]
        for row in logical_grid
        if isinstance(row, list) and any(str(cell).strip() for cell in row)
    ]
    deduped_rows = [_dedupe_repeated_row_cells(row) for row in rows]
    row_texts = [
        " ".join(cell for cell in row if cell.strip()).strip()
        for row in deduped_rows
        if any(cell.strip() for cell in row)
    ]
    return {
        "title": title.strip(),
        "tableRole": parsed.get("tableRole"),
        "parseWarnings": parsed.get("parseWarnings") if isinstance(parsed.get("parseWarnings"), list) else [],
        "complexTableTodo": parsed.get("complexTableTodo") if isinstance(parsed.get("complexTableTodo"), dict) else {},
        "rowCount": len(rows),
        "columnCount": max((len(row) for row in rows), default=0),
        "rows": rows,
        "dedupedRows": deduped_rows,
        "rowTexts": row_texts,
    }


def _dedupe_repeated_row_cells(row: list[str]) -> list[str]:
    deduped: list[str] = []
    previous = object()
    for cell in row:
        text = str(cell)
        comparable = text.strip()
        if comparable and comparable == previous:
            continue
        deduped.append(text)
        previous = comparable
    return deduped


def _to_business_skill_record(record: ExtractionSkillRecord) -> BusinessSkillRecord:
    defaults = strip_stored_skill_text(record.defaults)
    defaults["sourceTypes"] = list(record.sourceTypes)
    defaults["inputBuilder"] = record.inputBuilder
    defaults["summaryTemplate"] = record.summaryTemplate
    defaults["rules"] = list(record.rules)
    return BusinessSkillRecord(
        id=record.id,
        version=record.version,
        name=record.name,
        category="extraction",
        status=record.status,
        sourceTypes=list(record.sourceTypes),
        targetTypes=[],
        executor=record.executor,
        resultKind="object",
        renderer=record.renderer,
        configSchema=record.configSchema,
        outputSchema=record.outputSchema,
        promptTemplate=record.promptTemplate,
        examples=record.examples,
        defaults=defaults,
        skillTextObjectKey=record.skillTextObjectKey,
        skillTextHash=record.skillTextHash,
        skillTextSizeBytes=record.skillTextSizeBytes,
        skillTextPreview=record.skillTextPreview,
        skillText=record.skillText,
        enabled=record.enabled,
        customerId=record.customerId,
        tags=list(record.tags),
        latestTestStatus=record.latestTestStatus,
        sampleCount=record.sampleCount,
        testRunCount=record.testRunCount,
        lastTestedAt=record.lastTestedAt,
        createdBy=record.createdBy,
        updatedBy=record.updatedBy,
        createdAt=record.createdAt or "",
        updatedAt=record.updatedAt or "",
    )


def _from_business_skill_record(record: BusinessSkillRecord) -> ExtractionSkillRecord:
    defaults = strip_stored_skill_text(record.defaults)
    return ExtractionSkillRecord(
        id=record.id,
        version=record.version,
        name=record.name,
        category="extraction",
        status=record.status,
        sourceTypes=record.sourceTypes or _as_string_list(defaults.get("sourceTypes")),
        executor=record.executor,
        inputBuilder=str(defaults.get("inputBuilder") or "page_compact"),
        renderer=record.renderer,
        configSchema=record.configSchema,
        outputSchema=record.outputSchema,
        summaryTemplate=str(defaults.get("summaryTemplate") or ""),
        promptTemplate=record.promptTemplate,
        rules=_as_string_list(defaults.get("rules")),
        examples=record.examples,
        defaults={key: value for key, value in defaults.items() if key not in {"sourceTypes", "inputBuilder", "summaryTemplate", "rules"}},
        skillTextObjectKey=record.skillTextObjectKey,
        skillTextHash=record.skillTextHash,
        skillTextSizeBytes=record.skillTextSizeBytes,
        skillTextPreview=record.skillTextPreview,
        skillText=record.skillText,
        enabled=record.enabled,
        customerId=record.customerId,
        tags=list(record.tags),
        latestTestStatus=record.latestTestStatus,
        sampleCount=record.sampleCount,
        testRunCount=record.testRunCount,
        lastTestedAt=record.lastTestedAt,
        createdBy=record.createdBy,
        updatedBy=record.updatedBy,
        createdAt=record.createdAt,
        updatedAt=record.updatedAt,
    )


def _as_string_list(value: Any) -> list[str]:
    return as_string_list(value)


def _normalize_record_status(record: ExtractionSkillRecord) -> str:
    status = str(record.status or "").strip()
    if status in ALLOWED_SKILL_STATUSES:
        return status
    return "active" if record.enabled else "disabled"


def _is_active_skill(record: ExtractionSkillRecord) -> bool:
    return bool(record.enabled) and _normalize_record_status(record) == "active"


def _status_from_payload(payload: dict[str, Any]) -> str:
    raw_status = str(payload.get("status") or "").strip()
    if raw_status:
        if raw_status not in ALLOWED_SKILL_STATUSES:
            raise ValueError(f"status 不支持：{raw_status}。")
        return raw_status
    return "active" if bool(payload.get("enabled", True)) else "disabled"
