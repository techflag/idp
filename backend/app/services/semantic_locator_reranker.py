# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""LLM reranker for semantic locator candidates.

The reranker is deliberately downstream of local recall. It receives a small
top-K candidate set with structural previews, then decides whether any candidate
is safe enough to execute automatically.
"""

from __future__ import annotations

from typing import Any

from app.core.config import AppSettings
from app.schemas.workbench import WorkbenchDocumentTree
from app.services.llm import DashScopePromptLlmService, _parse_required_json_payload
from app.services.semantic_locator import LocatorCandidate


LOCATOR_RERANK_PROMPT = """你是文档应用运行期的目标定位复判器。

请根据“模板定位画像”和“目标文档候选节点”判断哪些节点最可能承载本次 Skill 需要处理的业务内容。
你不是关键词匹配器：必须综合语义槽位、内容契约、结构形态、候选表格/文本预览、排除信号和用户已确认样例的数据形态。

只返回 JSON 对象，不要 Markdown。

输出结构：
{
  "winnerNodeIds": ["候选节点ID"],
  "confidence": 0.0,
  "needsReview": false,
  "reason": "选择或拒绝的简要理由",
  "warnings": [],
  "rejectedNodeIds": [
    {"nodeId": "候选节点ID", "reason": "排除原因"}
  ]
}

要求：
- 不要使用固定页码判断；页码只能作为候选证据。
- 优先选择与 semanticSlot、contentContracts 和 confirmedOutputShape 最一致的节点。
- 候选的表格/文本类型只是内容形态证据，不能作为定位优先级；用户查询指向章节文本时应选择文本章节，指向明细表时才选择表格或连续表格。
- 如果多个候选共同构成续表、连续章节或同一业务槽位，可返回多个 winnerNodeIds。
- 如果候选只是目录、页眉页脚、空表格、装饰性内容，或与业务槽位、内容契约、确认输出形态不一致，应排除。
- 如果候选差距小、结构证据不足、命中范围可能缺页或可能混入无关内容，needsReview=true。
- 只能在候选列表中选择节点，不要编造新的节点 ID。
"""


class DashScopeSemanticLocatorReranker:
    """DashScope-backed implementation of the optional locator reranker."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._llm = DashScopePromptLlmService(settings)
        self._model = settings.semantic_locator_llm_rerank_model or settings.dashscope_model

    def rerank(
        self,
        *,
        locator_profile: dict[str, Any],
        candidates: list[LocatorCandidate],
        document_tree: WorkbenchDocumentTree | None = None,
    ) -> dict[str, Any]:
        payload = {
            "locatorProfile": self._compact_locator_profile(locator_profile),
            "documentTreeSummary": self._document_tree_summary(document_tree),
            "candidates": [self._candidate_payload(item) for item in candidates],
        }
        chat_result = self._llm._chat(
            system_prompt=LOCATOR_RERANK_PROMPT,
            user_payload=payload,
            model=self._model,
            temperature=0.0,
            enable_thinking=False,
        )
        parsed = _parse_required_json_payload(str(chat_result.get("content") or ""), context="语义定位复判")
        parsed["_llmTrace"] = {
            "provider": "dashscope",
            "model": str(chat_result.get("requestModel") or self._model),
            "durationMs": chat_result.get("durationMs"),
            "inputChars": chat_result.get("inputChars"),
            "outputChars": chat_result.get("outputChars"),
            "promptTokens": chat_result.get("promptTokens"),
            "completionTokens": chat_result.get("completionTokens"),
            "totalTokens": chat_result.get("totalTokens"),
        }
        return parsed

    @staticmethod
    def _compact_locator_profile(profile: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "semanticSlot",
            "description",
            "locatorInstruction",
            "forceRerank",
            "positiveTerms",
            "derivedTerms",
            "negativeTerms",
            "expectedObjectTypes",
            "contentContracts",
            "confirmedOutputShape",
            "confirmedEvidenceHints",
            "selectedWindow",
            "reviewStatus",
            "gate",
        }
        compact = {key: value for key, value in profile.items() if key in allowed_keys}
        for key in ["positiveTerms", "derivedTerms", "negativeTerms", "contentContracts"]:
            value = compact.get(key)
            if isinstance(value, list):
                compact[key] = value[:30]
        hints = compact.get("confirmedEvidenceHints")
        if isinstance(hints, list):
            compact["confirmedEvidenceHints"] = hints[:5]
        return compact

    @staticmethod
    def _document_tree_summary(document_tree: WorkbenchDocumentTree | None) -> dict[str, Any]:
        if not document_tree:
            return {"available": False}
        modules = []
        for module in document_tree.modules[:80]:
            if not isinstance(module, dict):
                continue
            content = module.get("content") if isinstance(module.get("content"), dict) else {}
            tables = [item for item in (content.get("tables") or []) if isinstance(item, dict)]
            texts = [item for item in (content.get("texts") or []) if isinstance(item, dict)]
            row_count = sum(len(table.get("rows") or []) for table in tables)
            column_count = max((len(row) for table in tables for row in (table.get("rows") or [])), default=0)
            modules.append(
                {
                    "id": str(module.get("id") or ""),
                    "title": str(module.get("title") or "")[:120],
                    "path": [str(item)[:80] for item in (module.get("path") or [])[:6]],
                    "pages": list(module.get("pages") or [])[:8],
                    "type": str(module.get("type") or ""),
                    "rowCount": row_count,
                    "columnCount": column_count,
                    "summary": str(module.get("summary") or module.get("directSummary") or "")[:260],
                    "textCount": len(texts),
                    "tableCount": len(tables),
                }
            )
        return {
            "available": True,
            "docId": document_tree.docId,
            "moduleCount": len(document_tree.modules),
            "modules": modules,
        }

    @staticmethod
    def _candidate_payload(candidate: LocatorCandidate) -> dict[str, Any]:
        payload = candidate.payload or {}
        return {
            "nodeId": candidate.node_id,
            "pageNo": candidate.page_no,
            "type": candidate.type,
            "title": candidate.title[:160],
            "excerpt": candidate.excerpt[:420],
            "localScore": round(candidate.score, 3),
            "rowCount": candidate.row_count,
            "columnCount": candidate.column_count,
            "reasons": candidate.reasons[:8],
            "warnings": candidate.warnings[:8],
            "matchedTerms": list(payload.get("matchedTerms") or [])[:40],
            "matchedWindows": list(payload.get("matchedWindows") or [])[:4],
            "rowWindow": payload.get("rowWindow") if isinstance(payload.get("rowWindow"), dict) else None,
            "shapeSignals": payload.get("shapeSignals") if isinstance(payload.get("shapeSignals"), dict) else {},
            "uncertainties": list(payload.get("uncertainties") or [])[:8],
            "deterministicScore": payload.get("deterministicScore"),
            "rerankScore": payload.get("rerankScore"),
            "path": list(payload.get("path") or [])[:8],
            "pages": list(payload.get("pages") or [])[:8],
            "blockIds": list(payload.get("blockIds") or [])[:20],
            "rowPreview": payload.get("rowPreview") or [],
            "tablePreviews": payload.get("tablePreviews") or [],
            "textPreviews": payload.get("textPreviews") or [],
        }
