"""Evidence selection and Evidence V2 integration for extraction runtime."""

from __future__ import annotations

import time
from typing import Any

from app.services.runtime_evidence import FIELD_LIST_INITIAL_MAX_TOTAL_TABLE_ROWS, FIELD_LIST_REVIEW_MAX_TOTAL_TABLE_ROWS
from app.services.extraction_runtime.models import ExtractionRuntimePorts, ExtractionRuntimeRequest


def select_runtime_evidence(
    *,
    request: ExtractionRuntimeRequest,
    ports: ExtractionRuntimePorts,
    facts_payload: dict[str, Any],
    evidence_index: dict[str, Any],
    runtime_contract: dict[str, Any],
    skill_meta: dict[str, Any],
    application_scope: dict[str, Any],
    output_type: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    model_facts_payload, evidence_selection = ports.build_runtime_evidence_package(
        facts_payload=facts_payload,
        evidence_index=evidence_index,
        runtime_contract=runtime_contract,
        skill_meta=skill_meta,
        expansion_level="initial",
    )
    model_facts_payload, evidence_selection = ports.apply_field_list_row_budget(
        facts_payload=model_facts_payload,
        evidence_selection=evidence_selection,
        max_total_rows=FIELD_LIST_INITIAL_MAX_TOTAL_TABLE_ROWS,
    )
    review_facts_payload, review_evidence_selection = ports.build_field_list_evidence_package(
        facts_payload=facts_payload,
        evidence_index=evidence_index,
        runtime_contract=runtime_contract,
        skill_meta=skill_meta,
        expansion_level="review",
    )
    review_facts_payload, review_evidence_selection = ports.apply_field_list_row_budget(
        facts_payload=review_facts_payload,
        evidence_selection=review_evidence_selection,
        max_total_rows=FIELD_LIST_REVIEW_MAX_TOTAL_TABLE_ROWS,
    )
    fallback_review_facts_payload = review_facts_payload
    fallback_review_evidence_selection = review_evidence_selection

    model_facts_source = "runtime_evidence_v1"
    evidence_v2_ms = 0
    evidence_v2_package: dict[str, Any] = {
        "version": "evidence_v2_disabled",
        "mode": "disabled",
        "status": "disabled",
        "canUseForModel": False,
        "metrics": {},
    }
    evidence_v2_model_input_enabled = bool(
        ports.settings.evidence_v2_model_input_enabled
        and runtime_contract
    )
    evidence_v2_enabled = bool(
        ports.settings.evidence_v2_shadow_enabled
        or evidence_v2_model_input_enabled
    )
    if evidence_v2_enabled:
        evidence_v2_started = time.perf_counter()
        try:
            if evidence_v2_model_input_enabled:
                evidence_v2_package = ports.build_evidence_v2_model_package(
                    facts_payload=facts_payload,
                    evidence_index=evidence_index,
                    runtime_contract=runtime_contract,
                    skill_meta=skill_meta,
                    application_scope=application_scope,
                )
            else:
                evidence_v2_package = ports.build_evidence_v2_shadow_package(
                    facts_payload=facts_payload,
                    evidence_index=evidence_index,
                    runtime_contract=runtime_contract,
                    skill_meta=skill_meta,
                    application_scope=application_scope,
                )
        except Exception as exc:
            ports.logger.warning(
                "[ExtractionRuntime] Evidence V2 package failed runId=%s taskId=%s: %s",
                request.run.id,
                request.run.taskId,
                exc,
            )
            evidence_v2_package = ports.build_evidence_v2_failure_package(exc)
        evidence_v2_ms = int((time.perf_counter() - evidence_v2_started) * 1000)
        evidence_v2_package["durationMs"] = evidence_v2_ms
        evidence_v2_facts = evidence_v2_package.get("factsPayload")
        if (
            evidence_v2_model_input_enabled
            and evidence_v2_package.get("canUseForModel")
            and isinstance(evidence_v2_facts, dict)
            and isinstance(evidence_v2_facts.get("pages"), list)
        ):
            model_facts_payload = evidence_v2_facts
            evidence_selection = ports.evidence_v2_runtime_selection(evidence_v2_package)
            model_facts_source = "evidence_v2_model_input"
            if output_type == "field_list":
                review_facts_payload = model_facts_payload
                review_evidence_selection = {
                    **evidence_selection,
                    "mode": "field_list_evidence_v2_review_reuse",
                    "expansionLevel": "review_reuse_initial",
                    "selectionReasons": [
                        *(
                            evidence_selection.get("selectionReasons")
                            if isinstance(evidence_selection.get("selectionReasons"), list)
                            else []
                        ),
                        "review_reuses_evidence_v2_model_input",
                    ],
                }

    table_review_risk = ports.assess_table_review_risk(
        facts_payload=model_facts_payload,
        evidence_index=evidence_index,
        skill_meta=skill_meta,
    )

    candidate_select_ms = int((time.perf_counter() - started) * 1000)
    evidence_v2_summary = {
        "enabled": evidence_v2_enabled,
        "modelInputEnabled": evidence_v2_model_input_enabled,
        "usedForModel": model_facts_source == "evidence_v2_model_input",
        "status": evidence_v2_package.get("status"),
        "mode": evidence_v2_package.get("mode"),
        "canUseForModel": bool(evidence_v2_package.get("canUseForModel")),
        "artifactPath": None,
        "durationMs": evidence_v2_ms,
        "metrics": evidence_v2_package.get("metrics") if isinstance(evidence_v2_package.get("metrics"), dict) else {},
    }
    return {
        "modelFactsPayload": model_facts_payload,
        "evidenceSelection": evidence_selection,
        "reviewFactsPayload": review_facts_payload,
        "reviewEvidenceSelection": review_evidence_selection,
        "fallbackReviewFactsPayload": fallback_review_facts_payload,
        "fallbackReviewEvidenceSelection": fallback_review_evidence_selection,
        "tableReviewRisk": table_review_risk,
        "modelFactsSource": model_facts_source,
        "evidenceV2Package": evidence_v2_package,
        "evidenceV2Summary": evidence_v2_summary,
        "evidenceV2Enabled": evidence_v2_enabled,
        "candidateSelectMs": candidate_select_ms,
    }
