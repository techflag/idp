# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Typed request/result models for the extraction runtime kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from app.domain.models import PromptRunRecord
from app.services.llm import PromptRunOutput

ExtractionSourceMode = Literal[
    "manual_task_run",
    "application_run",
    "workshop_trial",
    "sample_preview",
    "skill_test",
]


@dataclass
class ExtractionRuntimeRequest:
    """Input contract for one extraction runtime execution.

    Entrypoints should adapt their own state into this request, then stop doing
    evidence/render/model work themselves.
    """

    run: PromptRunRecord
    pages: list[Any]
    source_mode: ExtractionSourceMode = "manual_task_run"
    schema_definition: dict[str, Any] = field(default_factory=dict)
    skill_meta: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    facts_payload: dict[str, Any] | None = None
    evidence_index: dict[str, Any] | None = None
    page_range_label: str | None = None


def page_range_label(request: ExtractionRuntimeRequest, ports: Any) -> str:
    label = str(request.page_range_label or "").strip()
    if label:
        return label
    return ports.format_page_range(request.run.startPageNo, request.run.endPageNo)


@dataclass
class ExtractionRuntimePrepared:
    """Prepared context before the model/local executor runs."""

    skill_meta: dict[str, Any]
    config: dict[str, Any]
    facts_payload: dict[str, Any]
    evidence_index: dict[str, Any]
    application_scope: dict[str, Any]
    runtime_contract: dict[str, Any]
    output_type: str
    model_facts_payload: dict[str, Any]
    evidence_selection: dict[str, Any]
    review_facts_payload: dict[str, Any]
    review_evidence_selection: dict[str, Any]
    fallback_review_facts_payload: dict[str, Any]
    fallback_review_evidence_selection: dict[str, Any]
    table_review_risk: dict[str, Any]
    model_facts_source: str
    evidence_v2_package: dict[str, Any]
    evidence_v2_summary: dict[str, Any]
    evidence_v2_enabled: bool
    evidence_build_ms: int
    candidate_select_ms: int
    input_payload: dict[str, Any]
    metrics: dict[str, Any]

    def set_evidence_v2_artifact_path(self, artifact_path: str | None) -> None:
        if not artifact_path:
            return
        self.evidence_v2_summary["artifactPath"] = artifact_path
        self.input_payload["evidenceV2"] = self.evidence_v2_summary
        self.metrics["evidenceV2"] = self.evidence_v2_summary
        self.metrics["evidenceV2Shadow"] = self.evidence_v2_summary


@dataclass
class ExtractionRuntimeResult:
    """Execution result returned by the runtime kernel."""

    output: PromptRunOutput
    raw_payload: dict[str, Any]
    extraction_result: dict[str, Any]
    errors: list[str]
    completion_status: str
    metrics: dict[str, Any]
    run_meta: dict[str, Any]
    output_artifact_payload: dict[str, Any]
    review_facts_payload: dict[str, Any]
    review_evidence_selection: dict[str, Any]
    review_count: int
    repaired_model_payload: dict[str, Any] | None
    duration_ms: int
    used_table_fast_path: bool


@dataclass
class ExtractionRuntimePorts:
    """Ports that keep the kernel independent from repositories and routes.

    The first migration keeps some mature algorithms in their original module
    and exposes them here as callbacks.  Later passes can move those callbacks
    into the package module by module.
    """

    build_compact_extraction_facts: Callable[..., tuple[dict[str, Any], dict[str, Any]]]
    build_application_scope: Callable[[dict[str, Any] | None], dict[str, Any]]
    build_runtime_contract: Callable[..., dict[str, Any]]
    enrich_field_list_config: Callable[[dict[str, Any]], dict[str, Any]]
    compact_application_scope: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    augment_evidence_index: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    build_runtime_evidence_package: Callable[..., tuple[dict[str, Any], dict[str, Any]]]
    build_field_list_evidence_package: Callable[..., tuple[dict[str, Any], dict[str, Any]]]
    apply_field_list_row_budget: Callable[..., tuple[dict[str, Any], dict[str, Any]]]
    assess_table_review_risk: Callable[..., dict[str, Any]]
    build_evidence_v2_model_package: Callable[..., dict[str, Any]]
    build_evidence_v2_shadow_package: Callable[..., dict[str, Any]]
    build_evidence_v2_failure_package: Callable[[Exception], dict[str, Any]]
    evidence_v2_runtime_selection: Callable[[dict[str, Any]], dict[str, Any]]
    build_payload_metrics: Callable[..., dict[str, Any]]
    evidence_selection_metric_summary: Callable[..., dict[str, Any]]
    skill_payload_for_llm: Callable[[dict[str, Any]], dict[str, Any]]
    format_page_range: Callable[[int, int], str]
    run_llm_extraction: Callable[..., PromptRunOutput]
    try_table_fast_path: Callable[[ExtractionRuntimeRequest, ExtractionRuntimePrepared], PromptRunOutput | None]
    review_field_list: Callable[
        [ExtractionRuntimeRequest, ExtractionRuntimePrepared, dict[str, Any], PromptRunOutput],
        tuple[PromptRunOutput, dict[str, Any], dict[str, Any]] | None,
    ]
    preserve_review_source_pages: Callable[..., dict[str, Any]]
    estimate_json_payload_bytes: Callable[[Any], int]
    build_run_meta: Callable[..., dict[str, Any]]
    normalize_output: Callable[..., dict[str, Any]]
    enrich_result_from_application_scope: Callable[..., dict[str, Any]]
    completion_status_from_errors: Callable[[Any], str]
    settings: Any
    logger: Any
