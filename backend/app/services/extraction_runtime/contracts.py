# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Runtime contract helpers.

This module is intentionally generic.  It merges the application/workshop
contract with the Skill output schema without adding industry-specific field
aliases or document-type branches.
"""

from __future__ import annotations

from typing import Any

from app.services.extraction_runtime.models import ExtractionRuntimePorts, ExtractionRuntimeRequest


def resolve_runtime_contract(
    *,
    request: ExtractionRuntimeRequest,
    ports: ExtractionRuntimePorts,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    application_scope = ports.build_application_scope(request.schema_definition)
    runtime_contract = ports.build_runtime_contract(
        schema_definition=request.schema_definition,
        skill_meta=request.skill_meta,
    )
    output_schema = request.skill_meta.get("outputSchema") if isinstance(request.skill_meta.get("outputSchema"), dict) else {}
    output_type = str(runtime_contract.get("outputType") or output_schema.get("type") or "").strip()
    config = dict(request.config or {})
    if output_type == "field_list":
        config = ports.enrich_field_list_config(config)
    if runtime_contract:
        application_scope = {
            **application_scope,
            "runtimeContract": runtime_contract,
        }
    application_scope = ports.compact_application_scope(application_scope, runtime_contract)
    return config, application_scope, runtime_contract, output_type
