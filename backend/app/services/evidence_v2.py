"""Evidence V2 kernel for application extraction runs.

This module is deliberately pure: it works with plain dictionaries and does not
depend on repositories, FastAPI routes, runtime stores, or LLM clients.
"""

from __future__ import annotations

import json
import re
from typing import Any


DEFAULT_MAX_SELECTED_EVIDENCE = 32
DEFAULT_MAX_RENDER_CHARS = 16000
FIELD_LIST_CONTEXT_WINDOW = 12
FIELD_LIST_MAX_CONTEXT_ITEMS = 12


def build_evidence_v2_shadow_package(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    application_scope: dict[str, Any] | None = None,
    max_selected_evidence: int = DEFAULT_MAX_SELECTED_EVIDENCE,
    max_render_chars: int = DEFAULT_MAX_RENDER_CHARS,
) -> dict[str, Any]:
    """Build a shadow Evidence V2 package.

    The package is suitable for diagnostics and regression comparison.  It is
    not used as the official model input until a later feature-flagged phase.
    """

    return _build_evidence_v2_package(
        facts_payload=facts_payload,
        evidence_index=evidence_index,
        runtime_contract=runtime_contract,
        skill_meta=skill_meta,
        application_scope=application_scope,
        max_selected_evidence=max_selected_evidence,
        max_render_chars=max_render_chars,
        mode="shadow",
        include_model_facts=False,
    )


def build_evidence_v2_model_package(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    application_scope: dict[str, Any] | None = None,
    max_selected_evidence: int = DEFAULT_MAX_SELECTED_EVIDENCE,
    max_render_chars: int = DEFAULT_MAX_RENDER_CHARS,
) -> dict[str, Any]:
    """Build an Evidence V2 package that can be used as the model facts input."""

    return _build_evidence_v2_package(
        facts_payload=facts_payload,
        evidence_index=evidence_index,
        runtime_contract=runtime_contract,
        skill_meta=skill_meta,
        application_scope=application_scope,
        max_selected_evidence=max_selected_evidence,
        max_render_chars=max_render_chars,
        mode="model_input",
        include_model_facts=True,
    )


def _build_evidence_v2_package(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    application_scope: dict[str, Any] | None,
    max_selected_evidence: int,
    max_render_chars: int,
    mode: str,
    include_model_facts: bool,
) -> dict[str, Any]:
    index_items = _build_evidence_index_items(
        facts_payload=facts_payload,
        evidence_index=evidence_index,
    )
    selected = _select_evidence(
        items=index_items,
        runtime_contract=runtime_contract,
        skill_meta=skill_meta,
        application_scope=application_scope or {},
        max_selected_evidence=max_selected_evidence,
    )
    rendered = _render_evidence(
        selected_evidence=selected["selectedEvidence"],
        runtime_contract=runtime_contract,
        skill_meta=skill_meta,
        max_render_chars=max_render_chars,
    )
    metrics = _build_metrics(
        index_items=index_items,
        selected_evidence=selected["selectedEvidence"],
        rendered_evidence=rendered,
        selected=selected,
        mode=mode,
    )
    selected_evidence = selected["selectedEvidence"]
    can_use_for_model = include_model_facts and bool(selected_evidence)
    package = {
        "version": "evidence_v2_model_v1" if include_model_facts else "evidence_v2_shadow_v1",
        "mode": mode,
        "status": "ready" if selected_evidence else "empty",
        "canUseForModel": can_use_for_model,
        "runtimeContract": _compact_runtime_contract(runtime_contract),
        "evidenceIndex": {
            "itemCount": len(index_items),
            "items": [_strip_private_keys(item) for item in index_items[:128]],
            "truncated": len(index_items) > 128,
        },
        "selectedEvidence": selected["selectedEvidence"],
        "renderedEvidence": rendered,
        "expansionTrace": selected["expansionTrace"],
        "uncertainties": selected["uncertainties"],
        "warnings": selected["warnings"],
        "metrics": metrics,
    }
    if include_model_facts:
        facts = _build_model_facts_payload(
            facts_payload=facts_payload,
            selected_evidence=selected_evidence,
            rendered_evidence=rendered,
            runtime_contract=runtime_contract,
            skill_meta=skill_meta,
        )
        package["factsPayload"] = facts
        package["metrics"] = {
            **metrics,
            "factsBytes": _estimate_json_payload_bytes(facts),
            "canUseForModel": can_use_for_model,
        }
    return package


def build_evidence_v2_failure_package(error: Exception | str) -> dict[str, Any]:
    """Return a serializable shadow failure without affecting the main run."""

    return {
        "version": "evidence_v2_shadow_v1",
        "mode": "shadow",
        "status": "failed",
        "canUseForModel": False,
        "error": str(error),
        "metrics": {},
    }


def _build_evidence_index_items(
    *,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_by_page_and_fact = _evidence_by_page_and_fact_index(evidence_index)
    items: list[dict[str, Any]] = []
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = _coerce_int(page.get("pageNo"), 0)
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            evidence = evidence_by_page_and_fact.get((page_no, block_index), {})
            table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else None
            source_type = "table" if table_grid is not None else str(block.get("type") or "text").strip() or "text"
            item = {
                "id": _evidence_item_id(page_no=page_no, block_index=block_index, evidence=evidence),
                "sourceType": source_type,
                "pageNo": page_no,
                "blockRef": {
                    "factBlockIndex": block_index,
                    "blockId": str(evidence.get("blockId") or block.get("blockId") or "").strip(),
                    "sourceOrdinal": str(evidence.get("sourceOrdinal") or evidence.get("id") or "").strip(),
                    "blockPosition": str(evidence.get("blockPosition") or "").strip(),
                },
                "title": _compact_text(block.get("title") or evidence.get("title") or ""),
                "nearbyTitle": _compact_text(evidence.get("nearbyTitle") or ""),
                "excerpt": _evidence_excerpt(block=block, evidence=evidence, limit=640),
                "score": 0,
                "scoreReasons": [],
                "uncertainties": _collect_uncertainties(block=block, evidence=evidence),
                "originalRefs": {
                    "pageNo": page_no,
                    "factBlockIndex": block_index,
                    "blockId": str(evidence.get("blockId") or block.get("blockId") or "").strip(),
                    "sourceOrdinal": str(evidence.get("sourceOrdinal") or evidence.get("id") or "").strip(),
                    "hasTableGrid": table_grid is not None,
                },
            }
            if table_grid is not None:
                item["tableShape"] = _table_shape(table_grid)
                table_row_texts = _table_row_texts(table_grid)
                item["rowTextSummary"] = table_row_texts[:8]
                item["_rowTextSearch"] = table_row_texts
            items.append(item)
    return items


def _select_evidence(
    *,
    items: list[dict[str, Any]],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    application_scope: dict[str, Any],
    max_selected_evidence: int,
) -> dict[str, Any]:
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(runtime_contract.get("outputType") or output_schema.get("type") or "").strip()
    matched_pages = _runtime_contract_page_numbers(runtime_contract)
    selected_block_ids = _runtime_contract_block_ids(runtime_contract)
    field_labels = [str(item or "").strip() for item in runtime_contract.get("fieldLabels") or [] if str(item or "").strip()]
    terms = _contract_terms(runtime_contract=runtime_contract, skill_meta=skill_meta)

    if output_type == "field_list":
        selected = _select_field_list_evidence(
            items=items,
            field_labels=field_labels,
            terms=terms,
            matched_pages=matched_pages,
            selected_block_ids=selected_block_ids,
            max_selected_evidence=max_selected_evidence,
        )
    elif output_type == "record_collection":
        selected = _select_record_collection_evidence(
            items=items,
            terms=terms,
            matched_pages=matched_pages,
            selected_block_ids=selected_block_ids,
            selected_source_text=_runtime_contract_selected_source_text(runtime_contract),
            max_selected_evidence=max_selected_evidence,
        )
    else:
        selected = _select_generic_evidence(
            items=items,
            terms=terms,
            matched_pages=matched_pages,
            selected_block_ids=selected_block_ids,
            max_selected_evidence=max_selected_evidence,
        )

    warnings = list(selected.get("warnings") or [])
    if application_scope and application_scope.get("runtimeContract") and not runtime_contract:
        warnings.append("application_scope_has_contract_but_runtime_contract_missing")
    return {
        "selectedEvidence": selected["selectedEvidence"],
        "expansionTrace": selected["expansionTrace"],
        "uncertainties": _unique_strings(
            uncertainty
            for item in selected["selectedEvidence"]
            for uncertainty in (item.get("uncertainties") if isinstance(item.get("uncertainties"), list) else [])
        )[:24],
        "warnings": warnings[:24],
    }


def _select_field_list_evidence(
    *,
    items: list[dict[str, Any]],
    field_labels: list[str],
    terms: list[str],
    matched_pages: set[int],
    selected_block_ids: set[str],
    max_selected_evidence: int,
) -> dict[str, Any]:
    selected_by_id: dict[str, dict[str, Any]] = {}
    trace: list[dict[str, Any]] = [
        {
            "step": "select_field_list_candidates",
            "fieldCount": len(field_labels),
            "strategy": "field_top_k_then_scope_fallback",
        }
    ]
    fields = field_labels or ["__generic_field_list__"]
    for field in fields:
        field_terms = _extract_terms(field) if field != "__generic_field_list__" else terms
        scored = [
            _score_item(
                item,
                terms=field_terms or terms,
                matched_pages=matched_pages,
                selected_block_ids=selected_block_ids,
                output_type="field_list",
            )
            for item in items
        ]
        candidates = [item for item in scored if item["score"] > 0]
        if field != "__generic_field_list__":
            candidates = [item for item in candidates if _is_field_list_strong_candidate(item)]
        candidates.sort(key=lambda item: (-int(item["score"]), item.get("pageNo") or 0, str(item.get("id") or "")))
        for candidate in candidates[:2]:
            target_fields = candidate.setdefault("targetFields", [])
            if field != "__generic_field_list__" and field not in target_fields:
                target_fields.append(field)
            selected_by_id[candidate["id"]] = _prepare_selected_item(candidate, terms=field_terms or terms)

    if not selected_by_id:
        fallback = [
            _score_item(
                item,
                terms=terms,
                matched_pages=matched_pages,
                selected_block_ids=selected_block_ids,
                output_type="field_list",
                allow_scope_fallback=True,
            )
            for item in items
        ]
        fallback = [item for item in fallback if item["score"] > 0]
        fallback.sort(key=lambda item: (-int(item["score"]), item.get("pageNo") or 0, str(item.get("id") or "")))
        for candidate in fallback[:max(3, min(8, max_selected_evidence))]:
            selected_by_id[candidate["id"]] = _prepare_selected_item(candidate, terms=terms)
        trace.append({"step": "scope_fallback", "selectedCount": len(selected_by_id)})

    if field_labels and selected_by_id:
        covered_field_count = _selected_target_field_count(selected_by_id.values())
        minimum_coverage = min(len(field_labels), max(2, (len(field_labels) + 1) // 2))
        if covered_field_count < minimum_coverage and len(selected_by_id) < max_selected_evidence:
            added = _expand_field_list_context(
                items=items,
                selected_by_id=selected_by_id,
                matched_pages=matched_pages,
                selected_block_ids=selected_block_ids,
                max_selected_evidence=max_selected_evidence,
            )
            trace.append(
                {
                    "step": "field_context_expansion",
                    "reason": "low_field_coverage",
                    "coveredFieldCount": covered_field_count,
                    "minimumCoverage": minimum_coverage,
                    "addedCount": added,
                    "selectedCount": len(selected_by_id),
                }
            )

    selected = sorted(
        selected_by_id.values(),
        key=lambda item: (-int(item.get("score") or 0), item.get("pageNo") or 0, str(item.get("id") or "")),
    )[:max_selected_evidence]
    trace.append({"step": "finalize_selection", "selectedCount": len(selected)})
    return {"selectedEvidence": selected, "expansionTrace": trace, "warnings": []}


def _is_field_list_strong_candidate(candidate: dict[str, Any]) -> bool:
    """Return whether a field_list candidate is related to field evidence.

    A selected page/module alone is too weak for field extraction because a
    document-tree module may include long continuation tables.  Keep candidates
    whose own text/rows match the contract terms or whose table shape looks like
    a field/KV container.  Scope-only fallback is still available if nothing
    stronger is found.
    """

    reasons = {str(reason or "") for reason in candidate.get("scoreReasons") or []}
    if "contract_or_skill_term_match" in reasons:
        return True
    if "field_like_table_shape" in reasons:
        return True
    return False


def _selected_target_field_count(items) -> int:
    fields: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        fields.update(str(field or "").strip() for field in item.get("targetFields") or [] if str(field or "").strip())
    return len(fields)


def _expand_field_list_context(
    *,
    items: list[dict[str, Any]],
    selected_by_id: dict[str, dict[str, Any]],
    matched_pages: set[int],
    selected_block_ids: set[str],
    max_selected_evidence: int,
) -> int:
    """Add nearby compact field context when exact field-term coverage is sparse.

    Field documents often split a logical header into short OCR paragraphs.  An
    exact term match may select only one field, while neighboring key/value
    snippets hold semantically related fields with different labels.  This
    expansion is intentionally structural: it follows page/module scope and
    nearby compact blocks, not business-specific aliases.
    """

    remaining = max_selected_evidence - len(selected_by_id)
    if remaining <= 0:
        return 0
    selected_items = list(selected_by_id.values())
    anchor_pages = {_coerce_int(item.get("pageNo"), 0) for item in selected_items}
    anchor_pages.discard(0)
    if not anchor_pages:
        anchor_pages = set(matched_pages)
    anchor_indexes_by_page: dict[int, list[int]] = {}
    for item in selected_items:
        page_no = _coerce_int(item.get("pageNo"), 0)
        block_ref = item.get("blockRef") if isinstance(item.get("blockRef"), dict) else {}
        fact_index = _coerce_int(block_ref.get("factBlockIndex"), -1)
        if page_no > 0 and fact_index >= 0:
            anchor_indexes_by_page.setdefault(page_no, []).append(fact_index)

    context_candidates: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id or item_id in selected_by_id:
            continue
        page_no = _coerce_int(item.get("pageNo"), 0)
        if anchor_pages and page_no not in anchor_pages:
            continue
        distance = _nearest_anchor_distance(item=item, anchor_indexes_by_page=anchor_indexes_by_page)
        if distance is not None and distance > FIELD_LIST_CONTEXT_WINDOW and not _is_selected_content_ref(item, selected_block_ids):
            continue
        if not _looks_like_field_context(item) and distance is None and not _is_selected_content_ref(item, selected_block_ids):
            continue
        candidate = dict(item)
        candidate["score"] = max(1, int(candidate.get("score") or 0)) + _field_context_score(item=item, distance=distance)
        reasons = list(candidate.get("scoreReasons") or [])
        reasons.append("field_context_expansion")
        if distance is not None:
            reasons.append("neighbor_context")
        if _looks_like_field_context(item):
            reasons.append("compact_field_context")
        candidate["scoreReasons"] = _unique_strings(reasons)
        candidate.setdefault("targetFields", []).append("__context__")
        context_candidates.append(candidate)

    context_candidates.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            item.get("pageNo") or 0,
            _coerce_int((item.get("blockRef") or {}).get("factBlockIndex") if isinstance(item.get("blockRef"), dict) else None, 999999),
            str(item.get("id") or ""),
        )
    )
    added = 0
    for candidate in context_candidates[: min(remaining, FIELD_LIST_MAX_CONTEXT_ITEMS)]:
        selected_by_id[str(candidate["id"])] = _prepare_selected_item(candidate, terms=[])
        added += 1
    return added


def _nearest_anchor_distance(*, item: dict[str, Any], anchor_indexes_by_page: dict[int, list[int]]) -> int | None:
    page_no = _coerce_int(item.get("pageNo"), 0)
    block_ref = item.get("blockRef") if isinstance(item.get("blockRef"), dict) else {}
    fact_index = _coerce_int(block_ref.get("factBlockIndex"), -1)
    anchors = anchor_indexes_by_page.get(page_no) or []
    if fact_index < 0 or not anchors:
        return None
    return min(abs(fact_index - anchor) for anchor in anchors)


def _is_selected_content_ref(item: dict[str, Any], selected_block_ids: set[str]) -> bool:
    if not selected_block_ids:
        return False
    block_ref = item.get("blockRef") if isinstance(item.get("blockRef"), dict) else {}
    source_ids = {
        str(block_ref.get("blockId") or "").strip(),
        str(block_ref.get("sourceOrdinal") or "").strip(),
        str(item.get("id") or "").strip(),
    }
    return _source_id_matches_selected(source_ids, selected_block_ids)


def _looks_like_field_context(item: dict[str, Any]) -> bool:
    if item.get("sourceType") == "table":
        shape = item.get("tableShape") if isinstance(item.get("tableShape"), dict) else {}
        return shape.get("shapeType") in {"kv_or_field_table", "mixed_table"}
    text = _compact_field_context_text(item)
    if not text:
        return False
    if len(text) > 520:
        return False
    if "：" in text or ":" in text:
        return True
    tokens = [token for token in re.split(r"\s+", text.strip()) if token]
    return 1 <= len(tokens) <= 12 and len(text) <= 180


def _field_context_score(*, item: dict[str, Any], distance: int | None) -> int:
    score = 18
    if _looks_like_field_context(item):
        score += 16
    if distance is not None:
        score += max(0, FIELD_LIST_CONTEXT_WINDOW - distance)
    if item.get("sourceType") == "table":
        shape = item.get("tableShape") if isinstance(item.get("tableShape"), dict) else {}
        if shape.get("shapeType") == "mixed_table":
            score -= 8
    return max(1, score)


def _compact_field_context_text(item: dict[str, Any]) -> str:
    return _compact_text(" ".join(str(item.get(key) or "") for key in ("title", "nearbyTitle", "excerpt")), limit=720)


def _select_record_collection_evidence(
    *,
    items: list[dict[str, Any]],
    terms: list[str],
    matched_pages: set[int],
    selected_block_ids: set[str],
    selected_source_text: str,
    max_selected_evidence: int,
) -> dict[str, Any]:
    if selected_source_text:
        selected = [
            _selected_source_text_evidence_item(
                selected_source_text=selected_source_text,
                matched_pages=matched_pages,
            )
        ]
        return {
            "selectedEvidence": selected,
            "expansionTrace": [
                {
                    "step": "select_record_collection_candidates",
                    "selectedCount": len(selected),
                    "strategy": "selected_source_text",
                }
            ],
            "warnings": [],
        }

    if selected_block_ids:
        scoped = [
            _score_item(
                item,
                terms=terms,
                matched_pages=matched_pages,
                selected_block_ids=selected_block_ids,
                output_type="record_collection",
            )
            for item in items
        ]
        scoped = [item for item in scoped if item["score"] > 0 and _is_record_collection_scoped_candidate(item)]
        scoped.sort(key=lambda item: (-int(item.get("score") or 0), item.get("pageNo") or 0, str(item.get("id") or "")))
        if scoped:
            selected = [_prepare_selected_item(item, terms=terms) for item in scoped[:max_selected_evidence]]
            return {
                "selectedEvidence": selected,
                "expansionTrace": [
                    {
                        "step": "select_record_collection_candidates",
                        "selectedCount": len(selected),
                        "strategy": "selected_content_scope",
                    }
                ],
                "warnings": [],
            }

    scored: list[dict[str, Any]] = []
    for item in items:
        if item.get("sourceType") != "table":
            continue
        candidate = _score_item(
            item,
            terms=terms,
            matched_pages=matched_pages,
            selected_block_ids=selected_block_ids,
            output_type="record_collection",
            allow_scope_fallback=True,
        )
        shape = candidate.get("tableShape") if isinstance(candidate.get("tableShape"), dict) else {}
        if shape.get("shapeType") == "record_table":
            candidate["score"] += 35
            candidate.setdefault("scoreReasons", []).append("record_table_shape")
        scored.append(candidate)
    scored = [item for item in scored if item["score"] > 0]
    scored.sort(key=lambda item: (-int(item.get("score") or 0), item.get("pageNo") or 0, str(item.get("id") or "")))
    selected = [_prepare_selected_item(item, terms=[]) for item in scored[:max_selected_evidence]]
    return {
        "selectedEvidence": selected,
        "expansionTrace": [
            {
                "step": "select_record_collection_candidates",
                "selectedCount": len(selected),
                "strategy": "table_preview_and_shape_signals",
            }
        ],
        "warnings": [],
    }


def _selected_source_text_evidence_item(*, selected_source_text: str, matched_pages: set[int]) -> dict[str, Any]:
    page_no = min(matched_pages) if matched_pages else 0
    return {
        "id": "runtime-contract-selected-source",
        "sourceType": "text",
        "pageNo": page_no,
        "blockRef": {
            "factBlockIndex": -1,
            "blockId": "runtime-contract-selected-source",
            "sourceOrdinal": "runtimeContract.selectedSourceText",
            "blockPosition": "",
        },
        "title": "选中文档树来源",
        "excerpt": _compact_text(selected_source_text, limit=640),
        "score": 100,
        "scoreReasons": ["runtime_contract_selected_source_text"],
        "uncertainties": [],
        "originalRefs": {
            "pageNo": page_no,
            "factBlockIndex": -1,
            "blockId": "runtime-contract-selected-source",
            "sourceOrdinal": "runtimeContract.selectedSourceText",
            "hasTableGrid": False,
        },
    }


def _is_record_collection_scoped_candidate(candidate: dict[str, Any]) -> bool:
    reasons = {str(reason or "") for reason in candidate.get("scoreReasons") or []}
    return bool(reasons & {"selected_content_ref", "contract_or_skill_term_match"})


def _select_generic_evidence(
    *,
    items: list[dict[str, Any]],
    terms: list[str],
    matched_pages: set[int],
    selected_block_ids: set[str],
    max_selected_evidence: int,
) -> dict[str, Any]:
    scored = [
        _score_item(
            item,
            terms=terms,
            matched_pages=matched_pages,
            selected_block_ids=selected_block_ids,
            output_type="generic",
            allow_scope_fallback=True,
        )
        for item in items
    ]
    scored = [item for item in scored if item["score"] > 0]
    scored.sort(key=lambda item: (-int(item.get("score") or 0), item.get("pageNo") or 0, str(item.get("id") or "")))
    selected = [_prepare_selected_item(item, terms=terms) for item in scored[:max_selected_evidence]]
    return {
        "selectedEvidence": selected,
        "expansionTrace": [{"step": "select_generic_candidates", "selectedCount": len(selected)}],
        "warnings": [],
    }


def _score_item(
    item: dict[str, Any],
    *,
    terms: list[str],
    matched_pages: set[int],
    selected_block_ids: set[str],
    output_type: str,
    allow_scope_fallback: bool = False,
) -> dict[str, Any]:
    candidate = dict(item)
    score = 0
    reasons: list[str] = []
    page_no = _coerce_int(item.get("pageNo"), 0)
    block_ref = item.get("blockRef") if isinstance(item.get("blockRef"), dict) else {}
    source_ids = {
        str(block_ref.get("blockId") or "").strip(),
        str(block_ref.get("sourceOrdinal") or "").strip(),
        str(item.get("id") or "").strip(),
    }
    selected_ref_matched = bool(selected_block_ids and _source_id_matches_selected(source_ids, selected_block_ids))
    if selected_block_ids and not selected_ref_matched:
        candidate["score"] = 0
        candidate["scoreReasons"] = ["outside_selected_content_refs"]
        return candidate

    if matched_pages and page_no in matched_pages:
        score += 15
        reasons.append("matched_page")

    if selected_ref_matched:
        score += 45
        reasons.append("selected_content_ref")

    search_text = _normalize(" ".join(str(item.get(key) or "") for key in ("title", "nearbyTitle", "excerpt")))
    row_summary = item.get("rowTextSummary") if isinstance(item.get("rowTextSummary"), list) else []
    if row_summary:
        search_text += _normalize(" ".join(str(row or "") for row in row_summary))
    matched_terms = [term for term in terms if term and term in search_text]
    if matched_terms:
        score += min(80, 24 + len(matched_terms[:8]) * 8)
        reasons.append("contract_or_skill_term_match")
        candidate["matchedTerms"] = matched_terms[:12]

    table_shape = item.get("tableShape") if isinstance(item.get("tableShape"), dict) else {}
    if output_type == "field_list" and table_shape.get("shapeType") in {"kv_or_field_table", "mixed_table"}:
        score += 22
        reasons.append("field_like_table_shape")
    if allow_scope_fallback and score == 0 and (not matched_pages or page_no in matched_pages):
        score += 8
        reasons.append("scope_fallback")

    if item.get("uncertainties"):
        score -= min(18, len(item.get("uncertainties") or []) * 3)
        reasons.append("uncertainty_penalty")

    candidate["score"] = max(0, score)
    candidate["scoreReasons"] = reasons
    return candidate


def _prepare_selected_item(item: dict[str, Any], *, terms: list[str]) -> dict[str, Any]:
    selected = dict(item)
    if selected.get("sourceType") == "table":
        row_window = _select_table_row_window(item=item, terms=terms)
        selected["rowWindow"] = row_window
        shape = selected.get("tableShape") if isinstance(selected.get("tableShape"), dict) else {}
        selected["selectedRowCount"] = len(row_window)
        selected["totalRowCount"] = _coerce_int(shape.get("rowCount"), 0)
    selected.pop("_rowTextSearch", None)
    return selected


def _select_table_row_window(*, item: dict[str, Any], terms: list[str]) -> list[dict[str, Any]]:
    row_texts = item.get("_rowTextSearch") if isinstance(item.get("_rowTextSearch"), list) else []
    if not row_texts:
        row_texts = item.get("rowTextSummary") if isinstance(item.get("rowTextSummary"), list) else []
    shape = item.get("tableShape") if isinstance(item.get("tableShape"), dict) else {}
    row_count = _coerce_int(shape.get("rowCount"), len(row_texts))
    selected: dict[int, str] = {}
    normalized_terms = [term for term in terms if term]
    for index, row_text in enumerate(row_texts):
        normalized = _normalize(str(row_text or ""))
        if not normalized:
            continue
        if any(term and term in normalized for term in normalized_terms):
            selected[index] = "semantic_term_match"
            if index > 0:
                selected.setdefault(index - 1, "neighbor_context")
            if index + 1 < row_count:
                selected.setdefault(index + 1, "neighbor_context")
    if not selected:
        preview_count = min(6, max(row_count, len(row_texts)))
        for index in range(preview_count):
            selected[index] = "bounded_preview"
        if row_count > preview_count:
            selected[row_count - 1] = "tail_context"
    return [{"rowIndex": index, "reason": reason} for index, reason in sorted(selected.items())]


def _render_evidence(
    *,
    selected_evidence: list[dict[str, Any]],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    max_render_chars: int,
) -> str:
    output_schema = skill_meta.get("outputSchema") if isinstance(skill_meta.get("outputSchema"), dict) else {}
    output_type = str(runtime_contract.get("outputType") or output_schema.get("type") or "custom").strip() or "custom"
    lines = [
        "# Evidence V2 Shadow Render",
        f"outputType: {output_type}",
    ]
    fields = [str(item or "").strip() for item in runtime_contract.get("fieldLabels") or [] if str(item or "").strip()]
    if fields:
        lines.append("fields: " + ", ".join(fields[:40]))
    lines.append("")
    for item in selected_evidence:
        lines.append(f"## {item.get('id')} page={item.get('pageNo')} source={item.get('sourceType')}")
        target_fields = item.get("targetFields") if isinstance(item.get("targetFields"), list) else []
        if target_fields:
            lines.append("targetFields: " + ", ".join(str(field) for field in target_fields[:12]))
        reasons = item.get("scoreReasons") if isinstance(item.get("scoreReasons"), list) else []
        if reasons:
            lines.append("reasons: " + ", ".join(str(reason) for reason in reasons[:8]))
        title = str(item.get("title") or item.get("nearbyTitle") or "").strip()
        if title:
            lines.append("title: " + title[:240])
        if item.get("sourceType") == "table":
            shape = item.get("tableShape") if isinstance(item.get("tableShape"), dict) else {}
            lines.append(
                "table: "
                + f"shape={shape.get('shapeType') or 'table'} "
                + f"rows={shape.get('rowCount') or 0} cols={shape.get('columnCount') or 0}"
            )
            row_window = item.get("rowWindow") if isinstance(item.get("rowWindow"), list) else []
            if row_window:
                lines.append("rowWindow: " + ", ".join(str(row.get("rowIndex")) for row in row_window[:16] if isinstance(row, dict)))
        excerpt = str(item.get("excerpt") or "").strip()
        if excerpt:
            lines.append("excerpt: " + excerpt[:720])
        uncertainties = item.get("uncertainties") if isinstance(item.get("uncertainties"), list) else []
        if uncertainties:
            lines.append("uncertainties: " + ", ".join(str(flag) for flag in uncertainties[:8]))
        lines.append("")
    rendered = "\n".join(lines).strip()
    if len(rendered) > max_render_chars:
        return rendered[:max_render_chars] + "\n[truncated]"
    return rendered


def _build_metrics(
    *,
    index_items: list[dict[str, Any]],
    selected_evidence: list[dict[str, Any]],
    rendered_evidence: str,
    selected: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    selected_rows = 0
    full_rows = 0
    for item in selected_evidence:
        if item.get("sourceType") != "table":
            continue
        selected_rows += int(item.get("selectedRowCount") or 0)
        full_rows += int(item.get("totalRowCount") or 0)
    return {
        "evidenceV2Enabled": True,
        "evidenceV2Mode": mode,
        "evidenceItemCount": len(index_items),
        "selectedEvidenceCount": len(selected_evidence),
        "selectedTableRowCount": selected_rows,
        "fullTableRowCount": full_rows,
        "renderedEvidenceChars": len(rendered_evidence),
        "evidenceExpansionLevel": "shadow_initial",
        "uncertaintyFlags": selected.get("uncertainties") or [],
        "warningCount": len(selected.get("warnings") or []),
    }


def _build_model_facts_payload(
    *,
    facts_payload: dict[str, Any],
    selected_evidence: list[dict[str, Any]],
    rendered_evidence: str,
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
) -> dict[str, Any]:
    fact_lookup = _fact_blocks_by_page_and_index(facts_payload)
    pages_by_no: dict[int, list[dict[str, Any]]] = {}
    for item in selected_evidence:
        page_no = _coerce_int(item.get("pageNo"), 0)
        if page_no <= 0:
            continue
        block_ref = item.get("blockRef") if isinstance(item.get("blockRef"), dict) else {}
        fact_index = _coerce_int(block_ref.get("factBlockIndex"), -1)
        original_block = fact_lookup.get((page_no, fact_index))
        if isinstance(original_block, dict):
            block = _model_block_from_original(original_block=original_block, evidence_item=item)
        else:
            block = _synthetic_model_block(evidence_item=item)
        pages_by_no.setdefault(page_no, []).append(block)

    pages = [
        {"pageNo": page_no, "blocks": blocks}
        for page_no, blocks in sorted(pages_by_no.items(), key=lambda pair: pair[0])
        if blocks
    ]
    selected_table_rows = sum(
        _coerce_int(item.get("selectedRowCount"), 0)
        for item in selected_evidence
        if item.get("sourceType") == "table"
    )
    full_table_rows = sum(
        _coerce_int(item.get("totalRowCount"), 0)
        for item in selected_evidence
        if item.get("sourceType") == "table"
    )
    evidence_selection = {
        "mode": "evidence_v2_model_input",
        "expansionLevel": "initial",
        "selectedBlockCount": len(selected_evidence),
        "selectedTableRowCount": selected_table_rows,
        "totalTableRowCount": full_table_rows,
        "selectionReasons": ["runtime_contract", "evidence_v2_candidate_selection", "bounded_evidence_render"],
        "uncertainties": _unique_strings(
            uncertainty
            for item in selected_evidence
            for uncertainty in (item.get("uncertainties") if isinstance(item.get("uncertainties"), list) else [])
        ),
        "selectedEvidence": [_selected_evidence_summary(item) for item in selected_evidence[:32]],
        "fullFactsPreserved": True,
        "source": "evidence_v2",
    }
    return {
        "pages": pages,
        "evidenceSelection": evidence_selection,
        "evidenceV2": {
            "version": "evidence_v2_model_facts_v1",
            "mode": "model_input",
            "outputType": str(runtime_contract.get("outputType") or (skill_meta.get("outputSchema") or {}).get("type") or ""),
            "fieldLabels": list(runtime_contract.get("fieldLabels") or [])[:80],
            "tableHeaders": list(runtime_contract.get("tableHeaders") or [])[:80],
            "recordFields": list(runtime_contract.get("recordFields") or [])[:80],
            "expectedCounts": runtime_contract.get("expectedCounts") if isinstance(runtime_contract.get("expectedCounts"), dict) else {},
            "selectedEvidenceCount": len(selected_evidence),
            "selectedEvidence": [_selected_evidence_summary(item) for item in selected_evidence[:32]],
            "fullFactsPreserved": True,
        },
    }


def _model_block_from_original(*, original_block: dict[str, Any], evidence_item: dict[str, Any]) -> dict[str, Any]:
    source_type = str(evidence_item.get("sourceType") or original_block.get("type") or "text").strip() or "text"
    source_ref = {
        "evidenceV2Id": evidence_item.get("id"),
        "pageNo": evidence_item.get("pageNo"),
        **(evidence_item.get("originalRefs") if isinstance(evidence_item.get("originalRefs"), dict) else {}),
    }
    block = {
        key: value
        for key, value in original_block.items()
        if key not in {"tableGrid", "text", "htmlContent"}
    }
    block["type"] = source_type
    block["title"] = str(evidence_item.get("title") or original_block.get("title") or "").strip()
    block["sourceRef"] = source_ref
    block["evidenceV2"] = _selected_evidence_summary(evidence_item)
    if source_type == "table" and isinstance(original_block.get("tableGrid"), dict):
        table_grid = _model_table_grid(
            table_grid=original_block["tableGrid"],
            evidence_item=evidence_item,
        )
        block["tableGrid"] = table_grid
        row_texts = table_grid.get("rowTexts") if isinstance(table_grid.get("rowTexts"), list) else []
        block["text"] = "\n".join(str(item or "") for item in row_texts if str(item or "").strip())[:2400]
    else:
        text = str(original_block.get("text") or evidence_item.get("excerpt") or "").strip()
        block["text"] = text[:2400]
        if len(text) > 2400:
            block["textTruncated"] = True
            block["originalTextCharCount"] = len(text)
    return block


def _model_table_grid(*, table_grid: dict[str, Any], evidence_item: dict[str, Any]) -> dict[str, Any]:
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    deduped_rows = table_grid.get("dedupedRows") if isinstance(table_grid.get("dedupedRows"), list) else []
    row_texts = table_grid.get("rowTexts") if isinstance(table_grid.get("rowTexts"), list) else []
    row_window = evidence_item.get("rowWindow") if isinstance(evidence_item.get("rowWindow"), list) else []
    selected_indexes = [
        _coerce_int(item.get("rowIndex"), -1)
        for item in row_window
        if isinstance(item, dict)
    ]
    selected_indexes = sorted({index for index in selected_indexes if index >= 0})
    if not selected_indexes:
        selected_indexes = list(range(min(6, len(rows))))
        if len(rows) > len(selected_indexes):
            selected_indexes.append(len(rows) - 1)
    selected_rows = [
        [str(cell or "") for cell in rows[index]]
        for index in selected_indexes
        if 0 <= index < len(rows) and isinstance(rows[index], list)
    ]
    selected_row_texts = [
        str(row_texts[index] or "")
        for index in selected_indexes
        if 0 <= index < len(row_texts)
    ]
    original_row_count = len([row for row in rows if isinstance(row, list)])
    return {
        **{
            key: value
            for key, value in table_grid.items()
            if key not in {"rows", "dedupedRows", "rowTexts", "rowSelection"}
        },
        "rows": selected_rows,
        "rowTexts": selected_row_texts,
        "rowSelection": [
            {
                "rowIndex": _coerce_int(item.get("rowIndex"), -1),
                "reason": str(item.get("reason") or "evidence_v2_window"),
            }
            for item in row_window
            if isinstance(item, dict) and _coerce_int(item.get("rowIndex"), -1) >= 0
        ],
        "rowCount": len(selected_rows),
        "originalRowCount": table_grid.get("rowCount") or original_row_count,
        "columnCount": table_grid.get("columnCount") or max((len(row) for row in selected_rows), default=0),
        "truncated": original_row_count > len(selected_rows),
        "evidencePackage": True,
        "evidencePackageVersion": "evidence_v2_model_facts_v1",
    }


def _synthetic_model_block(*, evidence_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(evidence_item.get("sourceType") or "text"),
        "title": str(evidence_item.get("title") or evidence_item.get("nearbyTitle") or "").strip(),
        "text": str(evidence_item.get("excerpt") or "").strip()[:2400],
        "sourceRef": {
            "evidenceV2Id": evidence_item.get("id"),
            "pageNo": evidence_item.get("pageNo"),
            **(evidence_item.get("originalRefs") if isinstance(evidence_item.get("originalRefs"), dict) else {}),
        },
        "evidenceV2": _selected_evidence_summary(evidence_item),
    }


def _selected_evidence_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "id": item.get("id"),
        "sourceType": item.get("sourceType"),
        "pageNo": item.get("pageNo"),
        "title": item.get("title") or item.get("nearbyTitle"),
        "score": item.get("score"),
        "scoreReasons": list(item.get("scoreReasons") or [])[:8],
        "targetFields": list(item.get("targetFields") or [])[:16],
        "uncertainties": list(item.get("uncertainties") or [])[:8],
        "rowWindow": list(item.get("rowWindow") or [])[:16],
        "selectedRowCount": item.get("selectedRowCount"),
        "totalRowCount": item.get("totalRowCount"),
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _fact_blocks_by_page_and_index(facts_payload: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    result: dict[tuple[int, int], dict[str, Any]] = {}
    pages = facts_payload.get("pages") if isinstance(facts_payload.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = _coerce_int(page.get("pageNo"), 0)
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for index, block in enumerate(blocks):
            if isinstance(block, dict):
                result[(page_no, index)] = block
    return result


def _evidence_by_page_and_fact_index(evidence_index: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    indexed: dict[tuple[int, int], dict[str, Any]] = {}
    pages = evidence_index.get("pages") if isinstance(evidence_index.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = _coerce_int(page.get("pageNo"), 0)
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            refs = block.get("originalRefs") if isinstance(block.get("originalRefs"), dict) else {}
            fact_index = _coerce_int(refs.get("factBlockIndex"), -1)
            if fact_index >= 0:
                indexed[(page_no, fact_index)] = block
    return indexed


def _evidence_item_id(*, page_no: int, block_index: int, evidence: dict[str, Any]) -> str:
    raw = str(evidence.get("id") or evidence.get("sourceOrdinal") or "").strip()
    if raw:
        return raw
    return f"ev2:p{page_no}:b{block_index}"


def _table_shape(table_grid: dict[str, Any]) -> dict[str, Any]:
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    normalized_rows = [row for row in rows if isinstance(row, list)]
    row_count = len(normalized_rows) or _coerce_int(table_grid.get("rowCount"), 0)
    column_count = _coerce_int(table_grid.get("columnCount"), 0) or max((len(row) for row in normalized_rows), default=0)
    nonempty = 0
    total_cells = 0
    repeated_rows = 0
    field_like_rows = 0
    for row in normalized_rows:
        cells = [str(cell or "").strip() for cell in row]
        filled = [cell for cell in cells if cell]
        total_cells += len(cells)
        nonempty += len(filled)
        if len(set(filled)) <= 2 and len(filled) >= 4:
            repeated_rows += 1
        joined = " ".join(filled)
        if ":" in joined or "：" in joined or (1 <= len(filled) <= 4 and any(len(cell) <= 12 for cell in filled)):
            if ":" in joined or "：" in joined or row_count <= 24:
                field_like_rows += 1
    empty_ratio = 1.0
    if total_cells > 0:
        empty_ratio = 1 - (nonempty / total_cells)
    shape_type = "table"
    if _table_has_complex_signal(table_grid):
        shape_type = "complex_table"
    elif row_count >= 8 and column_count >= 3 and repeated_rows < max(3, row_count // 2):
        shape_type = "record_table"
    elif field_like_rows >= max(1, min(3, row_count or 1)):
        shape_type = "kv_or_field_table"
    if row_count >= 8 and column_count >= 3 and field_like_rows > 0:
        shape_type = "mixed_table" if shape_type != "complex_table" else shape_type
    return {
        "shapeType": shape_type,
        "rowCount": row_count,
        "columnCount": column_count,
        "emptyRatio": round(empty_ratio, 4),
        "fieldLikeRowCount": field_like_rows,
        "repeatedRowCount": repeated_rows,
        "hasComplexSignals": _table_has_complex_signal(table_grid),
        "headerCandidates": _header_candidates(normalized_rows),
    }


def _table_has_complex_signal(table_grid: dict[str, Any]) -> bool:
    warnings = table_grid.get("parseWarnings") if isinstance(table_grid.get("parseWarnings"), list) else []
    if warnings:
        return True
    complex_table = table_grid.get("complexTableTodo")
    if isinstance(complex_table, dict) and complex_table.get("required"):
        return True
    table_role = str(table_grid.get("tableRole") or "").strip()
    return table_role in {"matrix_table", "pivot_table", "crosstab_table"}


def _header_candidates(rows: list[list[Any]]) -> list[str]:
    candidates: list[str] = []
    for row in rows[:3]:
        text = " ".join(str(cell or "").strip() for cell in row if str(cell or "").strip())
        if text:
            candidates.append(text[:240])
    return candidates


def _table_row_texts(table_grid: dict[str, Any]) -> list[str]:
    row_texts = [str(item or "").strip() for item in table_grid.get("rowTexts") or [] if str(item or "").strip()]
    if row_texts:
        return row_texts
    rows = table_grid.get("rows") if isinstance(table_grid.get("rows"), list) else []
    generated: list[str] = []
    for row in rows:
        if isinstance(row, list):
            text = " ".join(str(cell or "").strip() for cell in row if str(cell or "").strip())
            if text:
                generated.append(text)
    return generated


def _evidence_excerpt(*, block: dict[str, Any], evidence: dict[str, Any], limit: int) -> str:
    parts: list[str] = []
    for value in (block.get("text"), evidence.get("excerpt")):
        text = str(value or "").strip()
        if text:
            parts.append(text)
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    parts.extend(_table_row_texts(table_grid)[:4])
    return _compact_text(" ".join(parts), limit=limit)


def _collect_uncertainties(*, block: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (evidence.get("uncertainties"),):
        if isinstance(source, list):
            values.extend(str(item or "").strip() for item in source)
    table_grid = block.get("tableGrid") if isinstance(block.get("tableGrid"), dict) else {}
    parse_warnings = table_grid.get("parseWarnings") if isinstance(table_grid.get("parseWarnings"), list) else []
    values.extend(str(item or "").strip() for item in parse_warnings)
    if _table_has_complex_signal(table_grid):
        values.append("table_shape_uncertain")
    return _unique_strings(values)


def _runtime_contract_page_numbers(runtime_contract: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    for key in ("matchedPageNos", "pageNos"):
        values = runtime_contract.get(key)
        if isinstance(values, list):
            pages.update(_coerce_int(value, 0) for value in values)
    selected_content = runtime_contract.get("selectedContent") if isinstance(runtime_contract.get("selectedContent"), list) else []
    for item in selected_content:
        if not isinstance(item, dict):
            continue
        for key in ("pages", "evidencePages"):
            values = item.get(key)
            if isinstance(values, list):
                pages.update(_coerce_int(value, 0) for value in values)
    pages.discard(0)
    return pages


def _runtime_contract_block_ids(runtime_contract: dict[str, Any]) -> set[str]:
    selected: set[str] = set()
    selected_content = runtime_contract.get("selectedContent") if isinstance(runtime_contract.get("selectedContent"), list) else []
    for item in selected_content:
        if not isinstance(item, dict):
            continue
        for key in ("blockId", "targetId"):
            value = str(item.get(key) or "").strip()
            if value:
                selected.add(value)
        for key in ("blockIds", "blockIdsExact"):
            values = item.get(key)
            if isinstance(values, list):
                selected.update(str(value or "").strip() for value in values if str(value or "").strip())
    return selected


def _runtime_contract_selected_source_text(runtime_contract: dict[str, Any]) -> str:
    text = str(runtime_contract.get("selectedSourceText") or "").strip()
    if not text:
        return ""
    max_chars = 20000
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...（选中来源已截断，完整 facts 已保留）"


def _source_id_matches_selected(source_ids: set[str], selected_block_ids: set[str]) -> bool:
    normalized_selected = {
        str(value or "").strip()
        for value in selected_block_ids
        if str(value or "").strip()
    }
    if not normalized_selected:
        return False
    for raw_source_id in source_ids:
        source_id = str(raw_source_id or "").strip()
        if not source_id:
            continue
        if source_id in normalized_selected:
            return True
        for selected_id in normalized_selected:
            if _source_id_has_selected_suffix(source_id=source_id, selected_id=selected_id):
                return True
    return False


def _source_id_has_selected_suffix(*, source_id: str, selected_id: str) -> bool:
    if not source_id or not selected_id or source_id == selected_id:
        return bool(source_id and selected_id and source_id == selected_id)
    if len(selected_id) > len(source_id) or not source_id.endswith(selected_id):
        return False
    prefix = source_id[: -len(selected_id)]
    return bool(prefix) and prefix[-1] in {"-", "_", ":", "/", "#"}


def _contract_terms(*, runtime_contract: dict[str, Any], skill_meta: dict[str, Any]) -> list[str]:
    raw_terms: list[str] = []
    for key in ("fieldLabels", "tableHeaders", "recordFields"):
        values = runtime_contract.get(key)
        if isinstance(values, list):
            raw_terms.extend(str(item or "") for item in values)
    selected_content = runtime_contract.get("selectedContent") if isinstance(runtime_contract.get("selectedContent"), list) else []
    for item in selected_content:
        if not isinstance(item, dict):
            continue
        raw_terms.append(str(item.get("title") or ""))
        raw_terms.append(str(item.get("excerpt") or ""))
    raw_terms.append(str(runtime_contract.get("selectedSourceText") or ""))
    raw_terms.append(str(skill_meta.get("name") or ""))
    raw_terms.append(str(skill_meta.get("promptTemplate") or ""))
    for rule in skill_meta.get("rules") or []:
        raw_terms.append(str(rule or ""))

    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        for term in _extract_terms(raw):
            if term not in seen:
                seen.add(term)
                terms.append(term)
            if len(terms) >= 160:
                return terms
    return terms


def _extract_terms(text: str) -> list[str]:
    terms: list[str] = []
    whole = _normalize(text)
    if len(whole) >= 2:
        terms.append(whole)
    for token in re.findall(r"[A-Za-z0-9_\-.]{2,}|[\u4e00-\u9fff]{2,}", text or ""):
        normalized = _normalize(token)
        if len(normalized) >= 2:
            terms.append(normalized)
    return terms


def _compact_runtime_contract(runtime_contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "contractVersion": runtime_contract.get("contractVersion"),
        "outputType": runtime_contract.get("outputType"),
        "fieldLabels": list(runtime_contract.get("fieldLabels") or [])[:80],
        "tableHeaders": list(runtime_contract.get("tableHeaders") or [])[:80],
        "recordFields": list(runtime_contract.get("recordFields") or [])[:80],
        "expectedCounts": runtime_contract.get("expectedCounts") if isinstance(runtime_contract.get("expectedCounts"), dict) else {},
        "matchedPageNos": list(runtime_contract.get("matchedPageNos") or [])[:80],
        "selectedContentCount": len(runtime_contract.get("selectedContent") or []),
    }


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text or "").lower())


def _compact_text(value: Any, limit: int = 420) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _estimate_json_payload_bytes(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return -1


def _unique_strings(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _strip_private_keys(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not str(key).startswith("_")}
