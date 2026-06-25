# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Extraction runtime orchestration kernel."""

from __future__ import annotations

import time

from app.services.extraction_runtime.context import build_runtime_context
from app.services.extraction_runtime.evidence import select_runtime_evidence
from app.services.extraction_runtime.executors import execute_model_or_local_path
from app.services.extraction_runtime.models import (
    ExtractionRuntimePorts,
    ExtractionRuntimePrepared,
    ExtractionRuntimeRequest,
    ExtractionRuntimeResult,
)
from app.services.extraction_runtime.renderers import build_input_payload, build_output_artifact_payload
from app.services.extraction_runtime.validators import normalize_and_validate_output


class ExtractionRuntimeKernel:
    """Shared runtime for all extraction entrypoints."""

    def prepare(
        self,
        request: ExtractionRuntimeRequest,
        *,
        ports: ExtractionRuntimePorts,
    ) -> ExtractionRuntimePrepared:
        context = build_runtime_context(request=request, ports=ports)
        evidence = select_runtime_evidence(
            request=request,
            ports=ports,
            facts_payload=context["factsPayload"],
            evidence_index=context["evidenceIndex"],
            runtime_contract=context["runtimeContract"],
            skill_meta=request.skill_meta,
            application_scope=context["applicationScope"],
            output_type=context["outputType"],
        )
        input_payload = build_input_payload(
            request=request,
            ports=ports,
            config=context["config"],
            application_scope=context["applicationScope"],
            runtime_contract=context["runtimeContract"],
            model_facts_payload=evidence["modelFactsPayload"],
            evidence_selection=evidence["evidenceSelection"],
            evidence_v2_summary=evidence["evidenceV2Summary"],
        )
        metrics = ports.build_payload_metrics(
            facts_payload=evidence["modelFactsPayload"],
            evidence_index=context["evidenceIndex"],
            input_payload=input_payload,
            full_facts_payload=context["factsPayload"],
        )
        metrics.update(
            ports.evidence_selection_metric_summary(
                evidence_selection=evidence["evidenceSelection"],
                evidence_build_ms=context["evidenceBuildMs"],
                candidate_select_ms=evidence["candidateSelectMs"],
            )
        )
        metrics["modelFactsSource"] = evidence["modelFactsSource"]
        metrics["evidenceV2"] = evidence["evidenceV2Summary"]
        metrics["evidenceV2Shadow"] = evidence["evidenceV2Summary"]
        metrics["sourceMode"] = request.source_mode
        metrics["kernelVersion"] = "extraction_runtime_kernel_v1"
        return ExtractionRuntimePrepared(
            skill_meta=request.skill_meta,
            config=context["config"],
            facts_payload=context["factsPayload"],
            evidence_index=context["evidenceIndex"],
            application_scope=context["applicationScope"],
            runtime_contract=context["runtimeContract"],
            output_type=context["outputType"],
            model_facts_payload=evidence["modelFactsPayload"],
            evidence_selection=evidence["evidenceSelection"],
            review_facts_payload=evidence["reviewFactsPayload"],
            review_evidence_selection=evidence["reviewEvidenceSelection"],
            fallback_review_facts_payload=evidence["fallbackReviewFactsPayload"],
            fallback_review_evidence_selection=evidence["fallbackReviewEvidenceSelection"],
            table_review_risk=evidence["tableReviewRisk"],
            model_facts_source=evidence["modelFactsSource"],
            evidence_v2_package=evidence["evidenceV2Package"],
            evidence_v2_summary=evidence["evidenceV2Summary"],
            evidence_v2_enabled=bool(evidence["evidenceV2Enabled"]),
            evidence_build_ms=context["evidenceBuildMs"],
            candidate_select_ms=evidence["candidateSelectMs"],
            input_payload=input_payload,
            metrics=metrics,
        )

    def execute(
        self,
        request: ExtractionRuntimeRequest,
        prepared: ExtractionRuntimePrepared,
        *,
        ports: ExtractionRuntimePorts,
        started_at: float | None = None,
    ) -> ExtractionRuntimeResult:
        started = started_at if started_at is not None else time.perf_counter()
        execution = execute_model_or_local_path(
            request=request,
            prepared=prepared,
            ports=ports,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        validation = normalize_and_validate_output(
            request=request,
            prepared=prepared,
            ports=ports,
            output=execution["output"],
            raw_payload=execution["rawPayload"],
            duration_ms=duration_ms,
            execution_metrics=execution,
        )
        output_artifact_payload = build_output_artifact_payload(
            skill_meta=prepared.skill_meta,
            config=prepared.config,
            application_scope=prepared.application_scope,
            runtime_contract=prepared.runtime_contract,
            model_facts_payload=prepared.model_facts_payload,
            review_facts_payload=execution["reviewFactsPayload"] if execution["reviewCount"] else None,
            evidence_selection=prepared.evidence_selection,
            evidence_v2_summary=prepared.evidence_v2_summary,
            review_evidence_selection=execution["reviewEvidenceSelection"] if execution["reviewCount"] else {},
            repaired_model_payload=execution["repairedModelPayload"],
            raw_payload=execution["rawPayload"],
            extraction_result=validation["extractionResult"],
        )
        return ExtractionRuntimeResult(
            output=execution["output"],
            raw_payload=execution["rawPayload"],
            extraction_result=validation["extractionResult"],
            errors=validation["errors"],
            completion_status=validation["completionStatus"],
            metrics=validation["metrics"],
            run_meta=validation["runMeta"],
            output_artifact_payload=output_artifact_payload,
            review_facts_payload=execution["reviewFactsPayload"],
            review_evidence_selection=execution["reviewEvidenceSelection"],
            review_count=int(execution["reviewCount"]),
            repaired_model_payload=execution["repairedModelPayload"],
            duration_ms=duration_ms,
            used_table_fast_path=bool(execution["usedTableFastPath"]),
        )
