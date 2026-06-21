"""Entrypoint adapters for the extraction runtime kernel."""

from __future__ import annotations

from typing import Any

from app.domain.models import PromptRunRecord
from app.services.extraction_runtime.models import ExtractionRuntimeRequest, ExtractionSourceMode


def source_mode_from_schema(schema_definition: dict[str, Any] | None) -> ExtractionSourceMode:
    if not isinstance(schema_definition, dict):
        return "manual_task_run"
    explicit = str(schema_definition.get("sourceMode") or "").strip()
    if explicit in {"manual_task_run", "application_run", "workshop_trial", "sample_preview", "skill_test"}:
        return explicit  # type: ignore[return-value]
    protocol = str(schema_definition.get("protocol") or "").strip()
    if protocol == "application_extraction_step_v1":
        return "application_run"
    if protocol == "sample_preview_extraction_v1":
        return "sample_preview"
    if protocol == "extraction_skill_v1":
        config = schema_definition.get("config") if isinstance(schema_definition.get("config"), dict) else {}
        if isinstance(config.get("runtimeContract"), dict):
            return "workshop_trial"
    return "manual_task_run"


def build_prompt_run_runtime_request(
    *,
    run: PromptRunRecord,
    pages: list[Any],
    source_mode: ExtractionSourceMode | None = None,
    facts_payload: dict[str, Any] | None = None,
    evidence_index: dict[str, Any] | None = None,
    page_range_label: str | None = None,
) -> ExtractionRuntimeRequest:
    schema_definition = run.schemaDefinition or {}
    skill_meta = schema_definition.get("skill") if isinstance(schema_definition.get("skill"), dict) else {}
    config = schema_definition.get("config") if isinstance(schema_definition.get("config"), dict) else {}
    if not isinstance(skill_meta, dict) or not skill_meta:
        raise RuntimeError("解析 skill 运行缺少 skill 快照。")
    if not isinstance(config, dict):
        config = {}
    return ExtractionRuntimeRequest(
        run=run,
        pages=pages,
        source_mode=source_mode or source_mode_from_schema(schema_definition),
        schema_definition=schema_definition,
        skill_meta=skill_meta,
        config=config,
        facts_payload=facts_payload,
        evidence_index=evidence_index,
        page_range_label=page_range_label,
    )
