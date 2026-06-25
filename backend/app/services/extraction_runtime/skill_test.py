# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Adapters for extraction Skill test and evaluation runs."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.domain.models import PromptRunRecord
from app.services.extraction_runtime.adapters import build_prompt_run_runtime_request
from app.services.extraction_runtime.models import ExtractionRuntimeRequest


def build_skill_test_runtime_request(
    *,
    skill_meta: dict[str, Any],
    config: dict[str, Any] | None,
    facts_payload: dict[str, Any],
    run_id: str | None = None,
    task_id: str = "skill-test-run",
    document_id: str = "skill-test-sample",
    sample_label: str = "样本内容",
    source_mode: str = "skill_test",
) -> ExtractionRuntimeRequest:
    """Build a kernel request from a sample facts payload.

    Skill testing and candidate evaluation already receive compact facts rather
    than persisted workbench pages.  The facts still go through the shared
    evidence selection, render, model, and validation chain.
    """

    schema_definition = {
        "protocol": "skill_test_extraction_v1",
        "sourceMode": source_mode,
        "skill": dict(skill_meta or {}),
        "config": dict(config or {}),
    }
    run = PromptRunRecord(
        id=run_id or f"skill-test-{uuid4().hex[:12]}",
        taskId=task_id,
        documentId=document_id,
        runType="sample",
        runName=str(skill_meta.get("name") or "Skill 测试"),
        promptName=str(skill_meta.get("name") or "Skill 测试"),
        promptText=str(skill_meta.get("promptTemplate") or ""),
        startPageNo=1,
        endPageNo=1,
        status="running",
        runPurpose="skill_test",
        schemaDefinition=schema_definition,
    )
    return build_prompt_run_runtime_request(
        run=run,
        pages=[],
        facts_payload=facts_payload,
        page_range_label=sample_label,
    )
