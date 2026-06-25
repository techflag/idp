# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Adapters for application extraction-step runtime requests.

This module keeps application orchestration from knowing the prompt-run schema
details used by the extraction runtime kernel.  It is intentionally generic:
application code supplies step snapshots and mappings; the runtime package owns
the wire shape that adapters later turn into an ``ExtractionRuntimeRequest``.
"""

from __future__ import annotations

from typing import Any


def build_application_extraction_schema_definition(
    *,
    skill_snapshot: dict[str, Any],
    config_snapshot: dict[str, Any] | None = None,
    input_mapping: dict[str, Any] | None = None,
    target_mapping: dict[str, Any] | None = None,
    orchestration_context: dict[str, Any] | None = None,
    persist_operation_targets: bool = True,
    persist_run_artifact: bool = False,
) -> dict[str, Any]:
    """Build the schema definition for one application extraction step."""

    return {
        "protocol": "application_extraction_step_v1",
        "skill": dict(skill_snapshot or {}),
        "config": dict(config_snapshot or {}),
        "inputMapping": dict(input_mapping or {}),
        "targetMapping": dict(target_mapping or {}),
        "orchestration": dict(orchestration_context or {}),
        "persistOperationTargets": bool(persist_operation_targets),
        "persistRunArtifact": bool(persist_run_artifact),
    }
