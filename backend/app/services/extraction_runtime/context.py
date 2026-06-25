# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Build full extraction context from pages and Skill snapshots."""

from __future__ import annotations

import time
from typing import Any

from app.services.extraction_runtime.contracts import resolve_runtime_contract
from app.services.extraction_runtime.models import ExtractionRuntimePorts, ExtractionRuntimeRequest


def build_runtime_context(
    *,
    request: ExtractionRuntimeRequest,
    ports: ExtractionRuntimePorts,
) -> dict[str, Any]:
    started = time.perf_counter()
    if isinstance(request.facts_payload, dict):
        facts_payload = request.facts_payload
        evidence_index = request.evidence_index if isinstance(request.evidence_index, dict) else _evidence_index_from_facts(facts_payload)
    else:
        facts_payload, evidence_index = ports.build_compact_extraction_facts(
            pages=request.pages,
            input_builder=str(request.skill_meta.get("inputBuilder") or "page_compact"),
        )
    config, application_scope, runtime_contract, output_type = resolve_runtime_contract(
        request=request,
        ports=ports,
    )
    evidence_index = ports.augment_evidence_index(evidence_index, runtime_contract)
    return {
        "factsPayload": facts_payload,
        "evidenceIndex": evidence_index,
        "config": config,
        "applicationScope": application_scope,
        "runtimeContract": runtime_contract,
        "outputType": output_type,
        "evidenceBuildMs": int((time.perf_counter() - started) * 1000),
    }


def _evidence_index_from_facts(facts_payload: dict[str, Any]) -> dict[str, Any]:
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    index_pages: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            page_no = int(page.get("pageNo") or 0)
        except (TypeError, ValueError):
            page_no = 0
        index_blocks: list[dict[str, Any]] = []
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
            row_texts = table_grid.get("rowTexts") if isinstance(table_grid.get("rowTexts"), list) else []
            text = str(block.get("text") or "")
            excerpt = " | ".join(str(item or "").strip() for item in row_texts[:3] if str(item or "").strip())
            if not excerpt:
                excerpt = text.strip()
            source_type = "table" if table_grid else str(block.get("type") or "text")
            shape_signals: dict[str, Any] = {}
            if table_grid:
                rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
                shape_signals = {
                    "rowCount": table_grid.get("rowCount") or len(rows),
                    "columnCount": table_grid.get("columnCount") or max((len(row) for row in rows if isinstance(row, list)), default=0),
                    "hasDedupedRows": isinstance(table_grid.get("dedupedRows"), list),
                    "hasRowTexts": bool(row_texts),
                }
            index_blocks.append(
                {
                    "id": f"fact-{page_no}-{block_index}",
                    "sourceType": source_type,
                    "pageNo": page_no,
                    "blockId": str(block.get("id") or block.get("blockId") or f"fact-{page_no}-{block_index}"),
                    "sourceOrdinal": f"fact-{page_no}-{block_index}",
                    "title": str(block.get("title") or table_grid.get("title") or page.get("title") or "").strip()[:160],
                    "excerpt": excerpt[:320],
                    "rowTextSummary": [str(item or "") for item in row_texts[:8]],
                    "shapeSignals": shape_signals,
                    "originalRefs": {"pageNo": page_no, "factBlockIndex": block_index},
                }
            )
        index_pages.append({"pageNo": page_no, "title": page.get("title") or "", "blocks": index_blocks})
    return {
        "version": "facts_payload_evidence_index_v1",
        "source": "facts_payload_override",
        "pages": index_pages,
        "fullFactsPreserved": True,
    }
