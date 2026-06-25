# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Semantic locator helpers for reusable extraction application steps.

The service intentionally keeps LLM-generated profiles and local candidate
recall separate: local scoring only narrows the search space, while the
execution gate decides whether the result is safe enough to run automatically.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.schemas.workbench import ApplicationPlanTarget, WorkbenchDocumentTree, WorkbenchPageDetail
from app.services.document_tree_builder import parse_table_details


DEFAULT_AUTO_EXECUTE_CONFIDENCE = 0.70
DEFAULT_MIN_CANDIDATE_GAP = 0.05
BLOCKING_WARNING_TERMS = ("空表格", "无明细", "仅包含头部", "缺少具体", "结构不完整")
GENERIC_LOCATOR_TERMS = {
    "信息",
    "数据",
    "内容",
    "文档",
    "字段",
    "记录",
    "记录集合",
    "提取",
    "解析",
    "结果",
}
FIELD_ABBREVIATION_ALIASES = {
    "id": ["identifier"],
    "no": ["number", "num"],
    "num": ["number", "no"],
    "qty": ["quantity"],
    "amt": ["amount"],
    "desc": ["description"],
    "uom": ["unit of measure", "unit"],
}
MAX_MATCH_TERMS = 48
MAX_MATCH_WINDOWS = 4


@dataclass
class LocatorCandidate:
    node_id: str
    page_no: int
    type: str
    title: str
    excerpt: str
    score: float
    row_count: int = 0
    column_count: int = 0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocatorRunResult:
    selected: bool
    confidence: float
    reason: str
    candidate_gap: float
    candidates: list[LocatorCandidate]
    selected_candidates: list[LocatorCandidate]
    execution_gate: dict[str, Any]
    warnings: list[str]


class SemanticLocatorReranker(Protocol):
    """Optional LLM reranker used after local recall narrows candidates."""

    def rerank(
        self,
        *,
        locator_profile: dict[str, Any],
        candidates: list[LocatorCandidate],
        document_tree: WorkbenchDocumentTree | None = None,
    ) -> dict[str, Any]: ...


class SemanticLocatorService:
    """Build locator profiles and run document-tree-like candidate matching."""

    def __init__(
        self,
        *,
        reranker: SemanticLocatorReranker | None = None,
        rerank_top_k: int = 6,
        rerank_gap_threshold: float = 0.18,
        skip_rerank_min_confidence: float = 0.86,
    ) -> None:
        self._reranker = reranker
        self._rerank_top_k = max(1, min(rerank_top_k, 12))
        self._rerank_gap_threshold = max(0.0, min(rerank_gap_threshold, 1.0))
        self._skip_rerank_min_confidence = max(0.0, min(skip_rerank_min_confidence, 1.0))

    def build_locator_profile_from_step(
        self,
        *,
        skill_snapshot: dict[str, Any],
        target_mapping: dict[str, Any],
        output_summary: dict[str, Any],
        prompt_text: str,
        source_page_no: int | None,
    ) -> dict[str, Any]:
        generated_targets = [
            item
            for item in (target_mapping.get("generatedTargets") or [])
            if isinstance(item, dict)
        ]
        confirmed_shape = self._confirmed_output_shape(output_summary, generated_targets)
        output_schema = skill_snapshot.get("outputSchema") if isinstance(skill_snapshot.get("outputSchema"), dict) else {}
        output_fields = [
            str(item)
            for item in (output_schema.get("required") or output_schema.get("fields") or [])
            if str(item).strip()
        ]
        positive_terms = self._unique(
            [
                str(skill_snapshot.get("name") or ""),
                str(skill_snapshot.get("id") or ""),
                str(skill_snapshot.get("category") or ""),
                *output_fields,
                *[
                    part
                    for field in output_fields
                    for part in re.split(r"[-_/\\]+", field)
                    if 2 <= len(part) <= 24
                ],
                *self._terms_from_text(prompt_text),
                *[
                    str(value)
                    for item in generated_targets
                    for value in [item.get("label"), item.get("fieldKey"), item.get("groupLabel")]
                ],
                *[
                    str(header)
                    for item in generated_targets
                    for header in (item.get("headers") or [])
                ],
                *[
                    str(header)
                    for shape in confirmed_shape
                    for header in (shape.get("headers") or [])
                ],
                *[
                    str(label)
                    for shape in confirmed_shape
                    for label in (shape.get("fieldLabels") or [])
                ],
            ]
        )
        if not positive_terms:
            positive_terms = ["表格", "字段", "记录", "明细"]
        derived_terms = self._derive_locator_terms(
            {
                "semanticSlot": str(skill_snapshot.get("name") or skill_snapshot.get("id") or "数据提取"),
                "positiveTerms": positive_terms,
                "confirmedOutputShape": confirmed_shape,
            }
        )
        expected_types: list[str] = []
        if int(output_summary.get("tableCount") or 0) > 0:
            expected_types.append("table")
        if int(output_summary.get("fieldCount") or 0) > 0:
            expected_types.append("text")
        if not expected_types:
            expected_types = ["table", "text"]
        field_count = int(output_summary.get("fieldCount") or 0)
        table_count = int(output_summary.get("tableCount") or 0)
        auto_confidence = 0.45 if field_count > 0 and table_count == 0 else DEFAULT_AUTO_EXECUTE_CONFIDENCE
        min_gap = 0.0 if field_count > 0 and table_count == 0 else DEFAULT_MIN_CANDIDATE_GAP
        return {
            "semanticSlot": str(skill_snapshot.get("name") or skill_snapshot.get("id") or "数据提取"),
            "description": "由用户确认样例输出生成的运行时定位画像。",
            "positiveTerms": positive_terms[:32],
            "derivedTerms": derived_terms[:MAX_MATCH_TERMS],
            "negativeTerms": [],
            "expectedObjectTypes": expected_types,
            "contentContracts": self._content_contracts(output_summary),
            "confirmedOutputShape": confirmed_shape,
            "sourcePageNo": source_page_no,
            "reviewStatus": "verified",
            "gate": {
                "autoExecuteMinConfidence": auto_confidence,
                "minCandidateGap": min_gap,
            },
        }

    def locate(
        self,
        *,
        pages: list[WorkbenchPageDetail],
        locator_profile: dict[str, Any],
        document_tree: WorkbenchDocumentTree | None = None,
    ) -> LocatorRunResult:
        candidates = self._merge_candidates(
            [
                *self._recall_tree_candidates(document_tree, locator_profile),
                *self._recall_block_candidates(pages, locator_profile),
            ]
        )
        selected_candidates = [item for item in candidates if item.score >= self._auto_confidence(locator_profile)]
        if not selected_candidates and candidates:
            selected_candidates = [candidates[0]]
        gap = self._candidate_gap(candidates)
        confidence = selected_candidates[0].score if selected_candidates else 0.0
        warnings: list[str] = []
        if not candidates:
            warnings.append("未召回可定位候选。")
        if not selected_candidates:
            warnings.append("未找到可执行目标节点。")
        if confidence < self._auto_confidence(locator_profile):
            warnings.append(f"定位置信度低于自动执行阈值 {self._auto_confidence(locator_profile):.2f}。")
        if gap < self._min_gap(locator_profile) and len(candidates) > 1:
            warnings.append(f"候选差距 {gap:.2f} 低于自动执行阈值 {self._min_gap(locator_profile):.2f}。")
        if selected_candidates and self._has_blocking_warning(selected_candidates[0]):
            warnings.append("最高候选包含阻断风险，需要人工复核。")
        rerank_payload = self._try_rerank(
            locator_profile=locator_profile,
            candidates=candidates,
            selected_candidates=selected_candidates,
            warnings=warnings,
            document_tree=document_tree,
        )
        if rerank_payload is not None:
            return self._apply_rerank_payload(
                locator_profile=locator_profile,
                candidates=candidates,
                local_selected_candidates=selected_candidates,
                local_warnings=warnings,
                rerank_payload=rerank_payload,
            )
        selected_candidates = self._expand_selected_candidates(selected_candidates, candidates)
        auto_execute = bool(selected_candidates) and not warnings
        reason = self._reason(selected_candidates, candidates, locator_profile, warnings)
        gate = {
            "autoExecute": auto_execute,
            "needsReview": not auto_execute,
            "confidence": round(confidence, 3),
            "candidateGap": gap,
            "warnings": warnings,
        }
        return LocatorRunResult(
            selected=auto_execute,
            confidence=round(confidence, 3),
            reason=reason,
            candidate_gap=gap,
            candidates=candidates[:12],
            selected_candidates=selected_candidates[:12] if auto_execute else [],
            execution_gate=gate,
            warnings=warnings,
        )

    def _try_rerank(
        self,
        *,
        locator_profile: dict[str, Any],
        candidates: list[LocatorCandidate],
        selected_candidates: list[LocatorCandidate],
        warnings: list[str],
        document_tree: WorkbenchDocumentTree | None,
    ) -> dict[str, Any] | None:
        if not self._reranker or not candidates:
            return None
        gap = self._candidate_gap(candidates)
        blocking = bool(selected_candidates and self._has_blocking_warning(selected_candidates[0]))
        force_rerank = bool(locator_profile.get("forceRerank"))
        close_candidate_gap = len(candidates) > 1 and gap <= self._rerank_gap_threshold
        uncertain = force_rerank or bool(warnings) or close_candidate_gap
        if (
            selected_candidates
            and not warnings
            and not blocking
            and not force_rerank
            and self._has_strong_title_path_match(selected_candidates[0])
        ):
            return None
        if (
            selected_candidates
            and not warnings
            and not blocking
            and not force_rerank
            and not close_candidate_gap
            and self._has_strong_local_selection(selected_candidates[0], locator_profile)
        ):
            return None
        if not uncertain and not blocking:
            return None
        try:
            payload = self._reranker.rerank(
                locator_profile=locator_profile,
                candidates=candidates[: self._rerank_top_k],
                document_tree=document_tree,
            )
        except Exception as error:  # noqa: BLE001 - rerank must never break local fallback
            return {
                "_rerank_failed": True,
                "error": str(error),
            }
        return payload if isinstance(payload, dict) else {"_rerank_failed": True, "error": "复判器未返回 JSON 对象"}

    def _apply_rerank_payload(
        self,
        *,
        locator_profile: dict[str, Any],
        candidates: list[LocatorCandidate],
        local_selected_candidates: list[LocatorCandidate],
        local_warnings: list[str],
        rerank_payload: dict[str, Any],
    ) -> LocatorRunResult:
        if rerank_payload.get("_rerank_failed"):
            confidence = local_selected_candidates[0].score if local_selected_candidates else 0.0
            warnings = list(local_warnings)
            warnings.append("LLM 复判失败，需要人工复核。")
            gate = {
                "autoExecute": False,
                "needsReview": True,
                "confidence": round(confidence, 3),
                "candidateGap": self._candidate_gap(candidates),
                "warnings": warnings,
                "rerank": {
                    "attempted": True,
                    "applied": False,
                    "fallback": "needs_review",
                    "error": str(rerank_payload.get("error") or "LLM 复判失败"),
                },
            }
            return LocatorRunResult(
                selected=False,
                confidence=round(confidence, 3),
                reason=self._reason(local_selected_candidates, candidates, locator_profile, warnings),
                candidate_gap=self._candidate_gap(candidates),
                candidates=candidates[:12],
                selected_candidates=[],
                execution_gate=gate,
                warnings=warnings,
            )

        winner_ids = self._winner_node_ids(rerank_payload)
        candidate_map = {item.node_id: item for item in candidates}
        winner_candidates = [candidate_map[node_id] for node_id in winner_ids if node_id in candidate_map]
        rerank_confidence = self._coerce_score(rerank_payload.get("confidence"))
        needs_review = bool(rerank_payload.get("needsReview") or rerank_payload.get("needs_review"))
        rerank_warnings = [str(item) for item in (rerank_payload.get("warnings") or []) if str(item).strip()]
        warnings: list[str] = []
        if needs_review:
            warnings.extend(rerank_warnings)
            warnings.append("LLM 复判要求人工复核。")
        if not winner_candidates:
            warnings.append("LLM 复判未返回可用候选节点。")
        if winner_candidates and any(self._has_blocking_warning(item) for item in winner_candidates):
            warnings.append("LLM 复判候选包含阻断风险，需要人工复核。")
        if rerank_confidence < self._auto_confidence(locator_profile):
            warnings.append(f"LLM 复判置信度低于自动执行阈值 {self._auto_confidence(locator_profile):.2f}。")
        winner_candidates = self._expand_selected_candidates(winner_candidates, candidates)
        auto_execute = bool(winner_candidates) and not warnings
        confidence = rerank_confidence if winner_candidates else 0.0
        reason_text = str(rerank_payload.get("reason") or "").strip()
        reason = f"LLM 复判：{reason_text}" if reason_text else self._reason(winner_candidates, candidates, locator_profile, warnings)
        gate = {
            "autoExecute": auto_execute,
            "needsReview": not auto_execute,
            "confidence": round(confidence, 3),
            "candidateGap": self._candidate_gap(candidates),
            "warnings": warnings,
            "rerank": {
                "attempted": True,
                "applied": True,
                "winnerNodeIds": winner_ids,
                "confidence": round(rerank_confidence, 3),
                "needsReview": needs_review,
                "reason": reason_text,
                "warnings": rerank_warnings,
                "rejectedNodeIds": rerank_payload.get("rejectedNodeIds") or rerank_payload.get("rejected_node_ids") or [],
                "llmTrace": rerank_payload.get("_llmTrace") if isinstance(rerank_payload.get("_llmTrace"), dict) else None,
            },
        }
        return LocatorRunResult(
            selected=auto_execute,
            confidence=round(confidence, 3),
            reason=reason,
            candidate_gap=self._candidate_gap(candidates),
            candidates=candidates[:12],
            selected_candidates=winner_candidates[:12] if auto_execute else [],
            execution_gate=gate,
            warnings=warnings,
        )

    def to_plan_target(self, candidate: LocatorCandidate) -> ApplicationPlanTarget:
        return ApplicationPlanTarget(
            targetId=candidate.node_id,
            pageNo=candidate.page_no,
            type=candidate.type,
            label=candidate.title,
            excerpt=candidate.excerpt[:260],
            score=round(candidate.score, 3),
            reasons=candidate.reasons[:6],
            payload=candidate.payload,
        )

    def _recall_tree_candidates(
        self,
        document_tree: WorkbenchDocumentTree | None,
        locator_profile: dict[str, Any],
    ) -> list[LocatorCandidate]:
        if not document_tree or not document_tree.modules:
            return []
        positives = self._locator_match_terms(locator_profile)
        negatives = self._profile_terms(locator_profile, "negativeTerms")
        expected_types = self._expected_object_types(locator_profile)
        candidates: list[LocatorCandidate] = []
        for module in document_tree.modules:
            if not isinstance(module, dict):
                continue
            pages = [int(item) for item in (module.get("pages") or []) if self._coerce_positive_int(item)]
            path = [str(item) for item in (module.get("path") or []) if str(item).strip()]
            title_path_text = " ".join(
                [
                    str(module.get("title") or ""),
                    " ".join(str(item) for item in path),
                ]
            )
            title_path_normalized = self._normalize(title_path_text)
            query_normalized = self._normalize(locator_profile.get("semanticSlot") or "")
            title_query_hits = [
                term
                for term in positives
                if len(term) >= 2 and self._normalize(term) in title_path_normalized
            ]
            if (
                len(path) <= 1
                and len(pages) > 1
                and not (query_normalized and query_normalized in title_path_normalized)
                and len(title_query_hits) < 2
            ):
                continue
            content = module.get("content") if isinstance(module.get("content"), dict) else {}
            tables = [item for item in (content.get("tables") or []) if isinstance(item, dict)]
            texts = [item for item in (content.get("texts") or []) if isinstance(item, dict)]
            module_type = "table" if tables else "text"
            page_no = pages[0] if pages else 1
            row_count = sum(len(table.get("rows") or []) for table in tables)
            column_count = max((len(row) for table in tables for row in (table.get("rows") or [])), default=0)
            text = self._module_text(module, tables, texts)
            normalized = self._normalize(text)
            score = 0.0
            reasons: list[str] = ["文档树模块"]
            warnings: list[str] = []
            score += 0.30
            if module_type == "table":
                reasons.append("内容形态：表格")
                if row_count:
                    reasons.append(f"{row_count} 行")
                    score += 0.12
                else:
                    warnings.append("空表格")
                if column_count >= 3:
                    reasons.append(f"{column_count} 列")
                    score += 0.08
            else:
                reasons.append("内容形态：文本")
            if expected_types:
                if module_type in expected_types:
                    score += 0.06
                    reasons.append("内容形态符合输出类型")
                else:
                    score -= 0.06
            title_hits = title_query_hits
            if query_normalized and query_normalized in title_path_normalized:
                score += 0.56
                reasons.append("标题/路径直接匹配查询")
            elif title_hits:
                score += min(0.54, 0.16 * len(title_hits))
                reasons.append("标题/路径匹配：" + "、".join(title_hits[:6]))
            table_windows = self._table_windows(tables, positives)
            table_matched_terms = self._unique(
                [
                    str(term)
                    for window in table_windows
                    for term in (window.get("matchedTerms") or [])
                ]
            )
            hits = [term for term in positives if self._match_term_in_text(term, normalized)]
            if hits:
                score += min(0.42, 0.08 * len(hits))
                reasons.append("语义信号：" + "、".join(hits[:6]))
            if table_windows:
                score += min(0.34, 0.06 * len(table_matched_terms))
                if self._has_header_like_window(table_windows):
                    score += 0.08
                reasons.append("行窗口匹配：" + "、".join(table_matched_terms[:6]))
            matched_terms = self._unique([*title_hits, *hits, *table_matched_terms])
            neg_hits = [term for term in negatives if self._normalize(term) and self._normalize(term) in normalized]
            if neg_hits:
                score -= min(0.34, 0.09 * len(neg_hits))
                warnings.append("排除信号：" + "、".join(neg_hits[:5]))
            score = max(0.0, min(score, 0.98))
            if score <= 0:
                continue
            title = str(module.get("title") or module.get("path") or f"文档树模块 {module.get('id') or ''}").strip()
            candidates.append(
                LocatorCandidate(
                    node_id=str(module.get("id") or f"tree-module-{len(candidates) + 1}"),
                    page_no=page_no,
                    type=module_type,
                    title=title,
                    excerpt=str(module.get("summary") or module.get("directSummary") or "")[:320],
                    score=round(score, 4),
                    row_count=row_count,
                    column_count=column_count,
                    reasons=reasons,
                    warnings=warnings,
                    payload={
                        "id": str(module.get("id") or ""),
                        "treeNodeId": str(module.get("id") or ""),
                        "source": "document_tree_module",
                        "pageNo": page_no,
                        "pages": pages,
                        "type": module_type,
                        "title": title,
                        "path": path,
                        "excerpt": str(module.get("summary") or "")[:500],
                        "blockIds": [str(item) for item in (module.get("blockIds") or [])],
                        "rowCount": row_count,
                        "columnCount": column_count,
                        "matchedTerms": matched_terms[:MAX_MATCH_TERMS],
                        "matchedWindows": table_windows,
                        "rowWindow": table_windows[0] if table_windows else None,
                        "shapeSignals": self._table_shape_signals(
                            row_count=row_count,
                            column_count=column_count,
                            matched_windows=table_windows,
                        ),
                        "uncertainties": self._table_uncertainties(
                            row_count=row_count,
                            matched_windows=table_windows,
                        ),
                        "deterministicScore": round(score, 4),
                        "tablePreviews": self._table_previews(tables, table_windows=table_windows),
                        "textPreviews": self._text_previews(texts),
                    },
                )
            )
        candidates.sort(key=lambda item: (item.score, -item.page_no, item.node_id), reverse=True)
        return candidates

    def _recall_block_candidates(
        self,
        pages: list[WorkbenchPageDetail],
        locator_profile: dict[str, Any],
    ) -> list[LocatorCandidate]:
        positives = self._locator_match_terms(locator_profile)
        negatives = self._profile_terms(locator_profile, "negativeTerms")
        expected_types = self._expected_object_types(locator_profile)
        candidates: list[LocatorCandidate] = []
        for page in pages:
            page_no = self._coerce_int(getattr(page, "pageNo", 0), 0)
            blocks = getattr(page, "blocks", None) or []
            for block_index, block in enumerate(blocks):
                raw_type = str(getattr(block, "type", "") or "").strip().lower()
                block_type = "table" if raw_type == "table" else "text"
                block_id = str(getattr(block, "id", "") or f"page-{page_no}-block-{block_index}").strip()
                block_page_no = self._coerce_int(getattr(block, "pageNo", page_no), page_no)
                block_title = str(getattr(block, "title", "") or "")
                block_content = str(getattr(block, "content", "") or "")
                block_html = str(getattr(block, "htmlContent", "") or "")
                bbox = self._bbox_list(getattr(block, "bbox", None))
                text = " ".join([block_title, block_content, block_html])
                normalized = self._normalize(text)
                title_normalized = self._normalize(block_title)
                rows = parse_table_details(block_html or block_content).get("rows") if block_type == "table" else []
                row_count = len(rows or [])
                column_count = max((len(row) for row in rows or []), default=0)
                score = 0.0
                reasons: list[str] = []
                warnings: list[str] = []
                score += 0.24
                reasons.append(f"内容形态：{block_type}")
                if block_type == "table":
                    if row_count:
                        reasons.append(f"{row_count} 行")
                    else:
                        warnings.append("空表格")
                    if column_count >= 3:
                        reasons.append(f"{column_count} 列")
                if expected_types:
                    if block_type in expected_types:
                        score += 0.06
                        reasons.append("内容形态符合输出类型")
                    else:
                        score -= 0.06
                title_hits = [term for term in positives if len(term) >= 2 and self._normalize(term) in title_normalized]
                query_normalized = self._normalize(locator_profile.get("semanticSlot") or "")
                if query_normalized and query_normalized in title_normalized:
                    score += 0.50
                    reasons.append("标题直接匹配查询")
                elif title_hits:
                    score += min(0.46, 0.14 * len(title_hits))
                    reasons.append("标题匹配：" + "、".join(title_hits[:6]))
                table_windows = self._table_windows_from_rows(
                    rows or [],
                    positives,
                    table_title=block_title or f"第 {block_page_no} 页表格",
                    page_no=block_page_no,
                    block_ids=[block_id],
                ) if block_type == "table" else []
                table_matched_terms = self._unique(
                    [
                        str(term)
                        for window in table_windows
                        for term in (window.get("matchedTerms") or [])
                    ]
                )
                hits = [term for term in positives if self._match_term_in_text(term, normalized)]
                if hits:
                    score += min(0.40, 0.09 * len(hits))
                    reasons.append("语义信号：" + "、".join(hits[:6]))
                if table_windows:
                    score += min(0.34, 0.06 * len(table_matched_terms))
                    if self._has_header_like_window(table_windows):
                        score += 0.08
                    reasons.append("行窗口匹配：" + "、".join(table_matched_terms[:6]))
                matched_terms = self._unique([*title_hits, *hits, *table_matched_terms])
                neg_hits = [term for term in negatives if self._normalize(term) and self._normalize(term) in normalized]
                if neg_hits:
                    score -= min(0.30, 0.08 * len(neg_hits))
                    warnings.append("排除信号：" + "、".join(neg_hits[:5]))
                score = max(0.0, min(score, 0.98))
                if score <= 0:
                    continue
                candidates.append(
                    LocatorCandidate(
                        node_id=block_id,
                        page_no=block_page_no,
                        type=block_type,
                        title=block_title or f"第 {block_page_no} 页内容块",
                        excerpt=(block_content or block_title or "")[:320],
                        score=round(score, 4),
                        row_count=row_count,
                        column_count=column_count,
                        reasons=reasons,
                        warnings=warnings,
                        payload={
                            "id": block_id,
                            "pageNo": block_page_no,
                            "type": block_type,
                            "title": block_title,
                            "excerpt": block_content[:500],
                            "blockId": block_id,
                            "bbox": bbox,
                            "rowCount": row_count,
                            "columnCount": column_count,
                            "matchedTerms": matched_terms[:MAX_MATCH_TERMS],
                            "matchedWindows": table_windows,
                            "rowWindow": table_windows[0] if table_windows else None,
                            "shapeSignals": self._table_shape_signals(
                                row_count=row_count,
                                column_count=column_count,
                                matched_windows=table_windows,
                            ),
                            "uncertainties": self._table_uncertainties(
                                row_count=row_count,
                                matched_windows=table_windows,
                            ),
                            "deterministicScore": round(score, 4),
                            "rowPreview": table_windows[0].get("previewRows") if table_windows else self._row_preview(rows or []),
                        },
                    )
                )
        candidates.sort(key=lambda item: (item.score, item.row_count, item.column_count), reverse=True)
        return candidates

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bbox_list(value: Any) -> list[float]:
        if not isinstance(value, (list, tuple)):
            return []
        normalized: list[float] = []
        for item in list(value)[:4]:
            try:
                normalized.append(float(item))
            except (TypeError, ValueError):
                return []
        return normalized if len(normalized) == 4 else []

    @staticmethod
    def _merge_candidates(candidates: list[LocatorCandidate]) -> list[LocatorCandidate]:
        seen: set[str] = set()
        merged: list[LocatorCandidate] = []
        for candidate in sorted(candidates, key=lambda item: (item.score, -item.page_no, item.node_id), reverse=True):
            source = str(candidate.payload.get("source") or "page_block")
            key = f"{source}:{candidate.node_id}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
        return merged

    @staticmethod
    def _expand_selected_candidates(
        selected: list[LocatorCandidate],
        candidates: list[LocatorCandidate],
    ) -> list[LocatorCandidate]:
        """Expand a semantic table anchor to structurally continuous tables.

        The locator first chooses the semantic anchor. When that anchor is a
        table, later table candidates with the same physical column structure
        are treated as the same data range even if their local text score is
        low. This avoids the common failure mode where a reusable template only
        extracts the first page of a long table. The rule is structural, not
        business-keyword based.
        """

        if not selected:
            return []

        expanded: list[LocatorCandidate] = []
        seen: set[str] = set()
        for item in selected:
            if item.node_id in seen:
                continue
            expanded.append(item)
            seen.add(item.node_id)

        table_anchors = [
            item
            for item in selected
            if item.type == "table" and item.row_count > 0 and item.column_count >= 2
        ]
        if not table_anchors:
            return expanded

        min_anchor_page = min(item.page_no for item in table_anchors)
        compatible_columns = {item.column_count for item in table_anchors if item.column_count >= 2}
        for candidate in candidates:
            if candidate.node_id in seen:
                continue
            if candidate.type != "table" or candidate.row_count <= 0:
                continue
            if candidate.page_no < min_anchor_page:
                continue
            if compatible_columns and candidate.column_count not in compatible_columns:
                continue
            if any(term in " ".join(candidate.warnings) for term in BLOCKING_WARNING_TERMS):
                continue
            expanded.append(candidate)
            seen.add(candidate.node_id)

        expanded.sort(key=lambda item: (item.page_no, item.node_id))
        return expanded

    @staticmethod
    def _module_text(module: dict[str, Any], tables: list[dict[str, Any]], texts: list[dict[str, Any]]) -> str:
        parts: list[str] = [
            str(module.get("title") or ""),
            " ".join(str(item) for item in (module.get("path") or [])),
            str(module.get("summary") or ""),
            str(module.get("directSummary") or ""),
            str(module.get("skillInput") or ""),
        ]
        for text in texts[:8]:
            parts.extend([str(text.get("title") or ""), str(text.get("content") or "")])
        for table in tables[:4]:
            parts.append(str(table.get("title") or ""))
            rows = table.get("rows") or []
            for row in rows[:12]:
                parts.append(" ".join(str(cell) for cell in row[:12]))
        return " ".join(parts)

    @classmethod
    def _locator_match_terms(cls, profile: dict[str, Any]) -> list[str]:
        return cls._derive_locator_terms(profile)

    @classmethod
    def _derive_locator_terms(cls, profile: dict[str, Any]) -> list[str]:
        seed_values: list[str] = []
        for key in (
            "semanticSlot",
            "locatorInstruction",
            "positiveTerms",
            "queryTerms",
            "derivedTerms",
            "fieldLabels",
            "recordFields",
            "tableHeaders",
            "expectedOutput",
            "exampleOutput",
            "sampleOutput",
            "fieldSchema",
        ):
            seed_values.extend(cls._string_values(profile.get(key)))
        seed_values.extend(cls._shape_terms(profile.get("confirmedOutputShape")))
        seed_values.extend(cls._confirmed_hint_terms(profile.get("confirmedEvidenceHints")))
        variants: list[str] = []
        for value in seed_values:
            variants.extend(cls._mechanical_term_variants(value))
        return cls._unique([term for term in variants if cls._is_useful_match_term(term)])[:MAX_MATCH_TERMS]

    @classmethod
    def _string_values(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return cls._terms_from_text(value)
        if isinstance(value, list):
            values: list[str] = []
            for item in value[:80]:
                values.extend(cls._string_values(item))
            return values
        if isinstance(value, dict):
            values: list[str] = []
            for key in (
                "label",
                "title",
                "fieldKey",
                "name",
                "description",
                "query",
                "header",
                "value",
                "fields",
                "properties",
                "required",
                "items",
                "examples",
                "example",
                "sample",
                "synonyms",
                "aliases",
                "headers",
                "recordFields",
                "tableHeaders",
            ):
                if key in value:
                    values.extend(cls._string_values(value.get(key)))
            return values
        return cls._terms_from_text(str(value))

    @classmethod
    def _shape_terms(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        terms: list[str] = []
        for item in value[:24]:
            if not isinstance(item, dict):
                continue
            for key in ("title", "fieldKey", "query", "type"):
                terms.extend(cls._string_values(item.get(key)))
            for key in ("headers", "fieldLabels", "recordFields", "tableHeaders"):
                terms.extend(cls._string_values(item.get(key)))
        return terms

    @classmethod
    def _confirmed_hint_terms(cls, value: Any) -> list[str]:
        hints = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        terms: list[str] = []
        for hint in hints[:12]:
            if not isinstance(hint, dict):
                continue
            for key in ("matchedTerms", "selectedTerms", "headerTerms"):
                terms.extend(cls._string_values(hint.get(key)))
            window = hint.get("selectedWindow") if isinstance(hint.get("selectedWindow"), dict) else {}
            terms.extend(cls._string_values(window.get("matchedTerms")))
        return terms

    @classmethod
    def _mechanical_term_variants(cls, value: Any) -> list[str]:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        if not text or text in GENERIC_LOCATOR_TERMS:
            return []
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[\u200b\u200c\u200d\ufeff]+", "", text)
        camel_spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        separator_spaced = re.sub(r"[_\-./\\|]+", " ", camel_spaced)
        compact = re.sub(r"[\s_\-./\\|]+", "", camel_spaced)
        title_case = " ".join(part[:1].upper() + part[1:] for part in separator_spaced.split())
        variants = [text, camel_spaced, separator_spaced, compact, title_case]
        parts = [part for part in separator_spaced.split() if part]
        for index, part in enumerate(parts):
            aliases = FIELD_ABBREVIATION_ALIASES.get(part.lower()) or []
            for alias in aliases:
                next_parts = list(parts)
                next_parts[index] = alias
                alias_text = " ".join(next_parts)
                variants.extend([alias_text, re.sub(r"\s+", "", alias_text)])
        if text.isupper() or len(text) <= 5:
            variants.append(text.upper())
        return cls._unique([item for item in variants if item.strip()])

    @staticmethod
    def _is_useful_match_term(value: str) -> bool:
        text = str(value or "").strip()
        if not text or text in GENERIC_LOCATOR_TERMS:
            return False
        normalized = SemanticLocatorService._normalize(text)
        if not normalized or normalized in GENERIC_LOCATOR_TERMS:
            return False
        if re.fullmatch(r"[a-z0-9]+", normalized) and len(normalized) < 3:
            return False
        return len(normalized) >= 2

    @classmethod
    def _matched_terms(cls, terms: list[str], text: Any) -> list[str]:
        normalized = cls._normalize(text)
        return cls._unique([term for term in terms if cls._match_term_in_text(term, normalized)])[:MAX_MATCH_TERMS]

    @classmethod
    def _match_term_in_text(cls, term: Any, normalized_text: str) -> bool:
        normalized_term = cls._normalize(term)
        if not cls._is_useful_match_term(str(term)) or not normalized_text:
            return False
        return normalized_term in normalized_text

    @classmethod
    def _table_windows(cls, tables: list[dict[str, Any]], terms: list[str]) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []
        for table_index, table in enumerate(tables[:8]):
            rows = table.get("rows") or []
            if not isinstance(rows, list):
                continue
            page_no = None
            pages = table.get("pages") if isinstance(table.get("pages"), list) else []
            if pages:
                page_no = cls._coerce_positive_int(pages[0])
            windows.extend(
                cls._table_windows_from_rows(
                    rows,
                    terms,
                    table_title=str(table.get("title") or f"表格 {table_index + 1}"),
                    page_no=page_no,
                    block_ids=[str(item) for item in (table.get("blockIds") or []) if str(item).strip()],
                    table_index=table_index,
                )
            )
        windows.sort(key=lambda item: (-float(item.get("score") or 0), int(item.get("rowStart") or 0)))
        return windows[:MAX_MATCH_WINDOWS]

    @classmethod
    def _table_windows_from_rows(
        cls,
        rows: list[Any],
        terms: list[str],
        *,
        table_title: str,
        page_no: int | None,
        block_ids: list[str],
        table_index: int = 0,
    ) -> list[dict[str, Any]]:
        normalized_rows = [
            [str(cell or "") for cell in row] if isinstance(row, list) else [str(row or "")]
            for row in rows
        ]
        hit_rows: list[dict[str, Any]] = []
        for index, row in enumerate(normalized_rows):
            row_text = " ".join(row)
            matched_terms = cls._matched_terms(terms, row_text)
            if not matched_terms:
                continue
            hit_rows.append(
                {
                    "index": index,
                    "matchedTerms": matched_terms,
                    "headerLike": cls._looks_like_header_row(row, matched_terms),
                    "hasFollowingDataRows": cls._has_following_data_rows(normalized_rows, index),
                }
            )
        if not hit_rows:
            return []

        ranges: list[dict[str, Any]] = []
        for hit in hit_rows:
            start = max(0, int(hit["index"]) - 2)
            end = min(len(normalized_rows), int(hit["index"]) + 5)
            if ranges and start <= int(ranges[-1]["end"]):
                ranges[-1]["end"] = max(int(ranges[-1]["end"]), end)
                ranges[-1]["hits"].append(hit)
            else:
                ranges.append({"start": start, "end": end, "hits": [hit]})

        windows: list[dict[str, Any]] = []
        for range_index, item in enumerate(ranges[:MAX_MATCH_WINDOWS]):
            matched_terms = cls._unique(
                [
                    str(term)
                    for hit in item["hits"]
                    for term in (hit.get("matchedTerms") or [])
                ]
            )
            header_like = any(bool(hit.get("headerLike")) for hit in item["hits"])
            has_following = any(bool(hit.get("hasFollowingDataRows")) for hit in item["hits"])
            score = min(1.0, 0.16 * len(matched_terms) + (0.16 if header_like else 0) + (0.12 if has_following else 0))
            start = int(item["start"])
            end = int(item["end"])
            preview_rows = cls._row_preview(normalized_rows[start:end], max_rows=7)
            windows.append(
                {
                    "id": f"table-{table_index}-window-{range_index}",
                    "tableIndex": table_index,
                    "tableTitle": table_title[:120],
                    "pageNo": page_no,
                    "rowStart": start + 1,
                    "rowEnd": end,
                    "matchedRows": [int(hit["index"]) + 1 for hit in item["hits"]],
                    "matchedTerms": matched_terms[:MAX_MATCH_TERMS],
                    "previewRows": preview_rows,
                    "headerLike": header_like,
                    "hasFollowingDataRows": has_following,
                    "score": round(score, 4),
                    "sourceRefs": {
                        "blockIds": block_ids[:20],
                        "pageNo": page_no,
                    },
                }
            )
        return windows

    @staticmethod
    def _looks_like_header_row(row: list[str], matched_terms: list[str]) -> bool:
        non_empty = [cell for cell in row if str(cell or "").strip()]
        if len(matched_terms) >= 2 and len(non_empty) >= 2:
            return True
        return len(non_empty) >= 3 and len(matched_terms) >= 1

    @staticmethod
    def _has_following_data_rows(rows: list[list[str]], index: int) -> bool:
        for row in rows[index + 1:index + 4]:
            non_empty = [cell for cell in row if str(cell or "").strip()]
            numeric_or_token = [
                cell for cell in non_empty
                if re.search(r"\d", cell) or re.fullmatch(r"[A-Za-z0-9_\-./]+", cell.strip())
            ]
            if len(non_empty) >= 2 and (numeric_or_token or len(non_empty) >= 4):
                return True
        return False

    @staticmethod
    def _has_header_like_window(windows: list[dict[str, Any]]) -> bool:
        return any(bool(item.get("headerLike")) and bool(item.get("hasFollowingDataRows")) for item in windows)

    @staticmethod
    def _table_shape_signals(
        *,
        row_count: int,
        column_count: int,
        matched_windows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        matched_rows = {
            int(row)
            for window in matched_windows
            for row in (window.get("matchedRows") or [])
            if isinstance(row, int)
        }
        matched_terms = {
            str(term)
            for window in matched_windows
            for term in (window.get("matchedTerms") or [])
            if str(term).strip()
        }
        return {
            "rowCount": row_count,
            "columnCount": column_count,
            "matchedRowCount": len(matched_rows),
            "matchedTermCount": len(matched_terms),
            "hasHeaderLikeWindow": SemanticLocatorService._has_header_like_window(matched_windows),
            "hasMatchedWindow": bool(matched_windows),
        }

    @staticmethod
    def _table_uncertainties(*, row_count: int, matched_windows: list[dict[str, Any]]) -> list[str]:
        uncertainties: list[str] = []
        if row_count <= 0:
            uncertainties.append("empty_table")
        if row_count > 0 and not matched_windows:
            uncertainties.append("no_skill_signal_window")
        if matched_windows and not SemanticLocatorService._has_header_like_window(matched_windows):
            uncertainties.append("matched_window_without_following_data")
        return uncertainties

    @staticmethod
    def _content_contracts(output_summary: dict[str, Any]) -> list[str]:
        contracts: list[str] = []
        if int(output_summary.get("tableCount") or 0) > 0:
            contracts.append("目标内容通常是可结构化表格，需保留表头、行数据和来源。")
        if int(output_summary.get("fieldCount") or 0) > 0:
            contracts.append("目标内容包含字段名和值，需保留来源页码。")
        if int(output_summary.get("structuredObjectCount") or 0) > 0:
            contracts.append("目标内容包含结构化对象或记录集合。")
        return contracts or ["目标内容应与用户确认样例输出的数据形态一致。"]

    @staticmethod
    def _confirmed_output_shape(
        output_summary: dict[str, Any],
        generated_targets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        shapes = [item for item in (output_summary.get("outputShapes") or []) if isinstance(item, dict)]
        if shapes:
            return shapes[:16]
        fallback: list[dict[str, Any]] = []
        for target in generated_targets[:12]:
            headers = [str(item)[:80] for item in (target.get("headers") or [])[:30]]
            shape = {
                "type": str(target.get("type") or target.get("renderer") or ""),
                "title": str(target.get("label") or target.get("groupLabel") or "")[:120],
                "fieldKey": str(target.get("fieldKey") or "")[:120],
                "headers": headers,
            }
            fallback.append({key: value for key, value in shape.items() if value not in ("", [], None)})
        return fallback[:16]

    @staticmethod
    def _terms_from_text(value: str) -> list[str]:
        text = re.sub(r"[`*_#{}\\[\\]()>:：,，。；;]", " ", str(value or ""))
        return [item for item in re.split(r"\s+|/|\\|\|", text) if 2 <= len(item) <= 24][:24]

    @staticmethod
    def _profile_terms(profile: dict[str, Any], key: str) -> list[str]:
        values = profile.get(key) or []
        if isinstance(values, str):
            values = [values]
        terms: list[str] = []
        for item in values:
            text = str(item).strip()
            if not text:
                continue
            if key == "positiveTerms" and text in GENERIC_LOCATOR_TERMS:
                continue
            terms.append(text)
        return terms

    @staticmethod
    def _expected_object_types(profile: dict[str, Any]) -> set[str]:
        values = profile.get("expectedObjectTypes") or []
        if isinstance(values, str):
            values = [values]
        expected: set[str] = set()
        for item in values:
            text = str(item or "").strip().lower()
            if text in {"table", "data_table", "record_collection"}:
                expected.add("table")
            elif text in {"text", "field_list", "notes"}:
                expected.add("text")
        return expected

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen or text in GENERIC_LOCATOR_TERMS:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _normalize(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).lower()
        return re.sub(r"[\s_\-./\\|:：,，。;；()（）\[\]{}<>《》\"'`]+", "", text)

    @staticmethod
    def _coerce_positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _candidate_gap(candidates: list[LocatorCandidate]) -> float:
        if not candidates:
            return 0.0
        top = candidates[0].score
        second = candidates[1].score if len(candidates) > 1 else 0.0
        return round(max(0.0, top - second), 4)

    @staticmethod
    def _has_blocking_warning(candidate: LocatorCandidate) -> bool:
        text = " ".join(candidate.warnings)
        return any(term in text for term in BLOCKING_WARNING_TERMS)

    @staticmethod
    def _has_strong_title_path_match(candidate: LocatorCandidate) -> bool:
        """Protect explicit title/path matches from being overruled by rerank.

        The rule is intentionally business-agnostic. If the user's query already
        maps clearly to a document-tree title or path, the locator should respect
        that module instead of letting the reranker jump to referenced content.
        """

        for reason in candidate.reasons:
            if reason in {"标题/路径直接匹配查询", "标题直接匹配查询"}:
                return True
            if reason.startswith(("标题/路径匹配：", "标题匹配：")) and candidate.score >= 0.70:
                matched_terms = [
                    item.strip()
                    for item in reason.split("：", 1)[-1].replace("、", ",").split(",")
                    if item.strip()
                ]
                if len(matched_terms) >= 2:
                    return True
        return False

    def _has_strong_local_selection(
        self,
        candidate: LocatorCandidate,
        locator_profile: dict[str, Any],
    ) -> bool:
        """Skip LLM rerank when local recall already has a strong, typed hit.

        This is still generic: the signal comes from the current Skill/runtime
        contract and the document-tree candidate reasons, not from business
        aliases or sample values.
        """

        if candidate.score < self._skip_rerank_min_confidence:
            return False
        expected_types = {
            str(item or "").strip()
            for item in (locator_profile.get("expectedObjectTypes") or [])
            if str(item or "").strip()
        }
        if expected_types and candidate.type not in expected_types:
            return False
        reason_text = " ".join(str(reason or "") for reason in candidate.reasons)
        has_semantic_signal = "语义信号：" in reason_text
        has_title_signal = "标题/路径" in reason_text or "标题" in reason_text
        has_shape_signal = candidate.type == "table" and candidate.row_count > 0 and candidate.column_count > 0
        return has_semantic_signal and (has_title_signal or has_shape_signal)

    @staticmethod
    def _winner_node_ids(payload: dict[str, Any]) -> list[str]:
        value = payload.get("winnerNodeIds") or payload.get("winner_node_ids") or payload.get("selectedNodeIds") or []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _coerce_score(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(parsed, 1.0))

    @staticmethod
    def _row_preview(rows: list[list[Any]], *, max_rows: int = 8, max_columns: int = 10) -> list[list[str]]:
        preview: list[list[str]] = []
        for row in rows[:max_rows]:
            preview.append([str(cell)[:80] for cell in row[:max_columns]])
        return preview

    @classmethod
    def _table_previews(
        cls,
        tables: list[dict[str, Any]],
        *,
        table_windows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        previews: list[dict[str, Any]] = []
        windows_by_index: dict[int, list[dict[str, Any]]] = {}
        for window in table_windows or []:
            try:
                table_index = int(window.get("tableIndex") or 0)
            except (TypeError, ValueError):
                table_index = 0
            windows_by_index.setdefault(table_index, []).append(window)
        for table_index, table in enumerate(tables[:3]):
            rows = table.get("rows") or []
            windows = windows_by_index.get(table_index, [])
            previews.append(
                {
                    "title": str(table.get("title") or "")[:120],
                    "pages": list(table.get("pages") or [])[:6],
                    "rowCount": len(rows),
                    "columnCount": max((len(row) for row in rows), default=0),
                    "rows": windows[0].get("previewRows") if windows else cls._row_preview(rows),
                    "matchedWindows": windows[:3],
                }
            )
        return previews

    @staticmethod
    def _text_previews(texts: list[dict[str, Any]]) -> list[dict[str, str]]:
        previews: list[dict[str, str]] = []
        for text in texts[:5]:
            previews.append(
                {
                    "title": str(text.get("title") or "")[:120],
                    "content": str(text.get("content") or "")[:240],
                }
            )
        return previews

    @staticmethod
    def _auto_confidence(profile: dict[str, Any]) -> float:
        gate = profile.get("gate") if isinstance(profile.get("gate"), dict) else {}
        try:
            value = gate.get("autoExecuteMinConfidence")
            return float(DEFAULT_AUTO_EXECUTE_CONFIDENCE if value is None else value)
        except (TypeError, ValueError):
            return DEFAULT_AUTO_EXECUTE_CONFIDENCE

    @staticmethod
    def _min_gap(profile: dict[str, Any]) -> float:
        gate = profile.get("gate") if isinstance(profile.get("gate"), dict) else {}
        try:
            value = gate.get("minCandidateGap")
            return float(DEFAULT_MIN_CANDIDATE_GAP if value is None else value)
        except (TypeError, ValueError):
            return DEFAULT_MIN_CANDIDATE_GAP

    @staticmethod
    def _reason(
        selected: list[LocatorCandidate],
        candidates: list[LocatorCandidate],
        profile: dict[str, Any],
        warnings: list[str],
    ) -> str:
        slot = str(profile.get("semanticSlot") or "目标内容")
        if selected and not warnings:
            pages = sorted({item.page_no for item in selected})
            return f"定位到「{slot}」候选 {len(selected)} 个，分布在第 {'、'.join(map(str, pages))} 页。"
        if candidates:
            return f"「{slot}」最高候选仍需复核：{'；'.join(warnings) if warnings else '候选不稳定'}"
        return f"未找到「{slot}」的可靠候选。"
