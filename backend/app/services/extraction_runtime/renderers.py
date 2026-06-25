# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Render selected evidence into model and artifact payloads."""

from __future__ import annotations

from typing import Any

from app.services.extraction_runtime.models import ExtractionRuntimePorts, ExtractionRuntimeRequest, page_range_label


def build_input_payload(
    *,
    request: ExtractionRuntimeRequest,
    ports: ExtractionRuntimePorts,
    config: dict[str, Any],
    application_scope: dict[str, Any],
    runtime_contract: dict[str, Any],
    model_facts_payload: dict[str, Any],
    evidence_selection: dict[str, Any],
    evidence_v2_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "taskId": request.run.taskId,
        "documentId": request.run.documentId,
        "pageRange": page_range_label(request, ports),
        "skill": ports.skill_payload_for_llm(request.skill_meta),
        "config": config,
        "applicationScope": application_scope,
        "runtimeContract": runtime_contract,
        "facts": model_facts_payload,
        "evidenceSelection": evidence_selection,
        "evidenceV2": evidence_v2_summary,
        "sourceMode": request.source_mode,
        "fullFactsPreserved": True,
    }


def build_output_artifact_payload(
    *,
    skill_meta: dict[str, Any],
    config: dict[str, Any],
    application_scope: dict[str, Any],
    runtime_contract: dict[str, Any],
    model_facts_payload: dict[str, Any],
    review_facts_payload: dict[str, Any] | None,
    evidence_selection: dict[str, Any],
    evidence_v2_summary: dict[str, Any],
    review_evidence_selection: dict[str, Any],
    repaired_model_payload: dict[str, Any] | None,
    raw_payload: dict[str, Any],
    extraction_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "skill": skill_meta,
        "config": config,
        "applicationScope": application_scope,
        "runtimeContract": runtime_contract,
        "facts": model_facts_payload,
        "reviewFacts": review_facts_payload,
        "fullFactsPreserved": True,
        "evidenceSelection": evidence_selection,
        "evidenceV2": evidence_v2_summary,
        "evidenceV2Shadow": evidence_v2_summary,
        "reviewEvidenceSelection": review_evidence_selection,
        "repairedFromRawModelPayload": repaired_model_payload,
        "rawModelPayload": raw_payload,
        "extractionResult": extraction_result,
    }
