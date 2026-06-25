# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""AgentScope-compatible orchestration state for application runs.

This module keeps the first implementation deliberately small: the business
runtime still executes the existing DocParser and Skill calls, while the run is
tracked with an AgentScope-compatible protocol that can later be replaced by a
full AgentScope agent/team service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

from app.domain.models import ApplicationStepRecord


def _resolve_agentscope_version() -> tuple[bool, str | None]:
    try:
        import agentscope  # type: ignore[import-not-found]  # noqa: F401
    except Exception:
        return False, None

    try:
        return True, metadata.version("agentscope")
    except Exception:
        return True, None


@dataclass
class AgentScopeApplicationState:
    """Lightweight state bridge between application steps and AgentScope."""

    application_id: str
    application_run_id: str
    version: str
    task_id: str
    protocol: str = "agentscope_application_orchestration_v1"
    engine: str = "agentscope"
    engine_available: bool = False
    engine_version: str | None = None
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        application_id: str,
        application_run_id: str,
        version: str,
        task_id: str,
    ) -> "AgentScopeApplicationState":
        available, version_text = _resolve_agentscope_version()
        return cls(
            application_id=application_id,
            application_run_id=application_run_id,
            version=version,
            task_id=task_id,
            engine_available=available,
            engine_version=version_text,
        )

    def begin_step(self, step: ApplicationStepRecord) -> dict[str, Any]:
        event = {
            "event": "step_started",
            "stepOrder": step.stepOrder,
            "kind": step.kind,
            "skillId": step.skillId,
            "skillVersion": step.skillVersion,
            "inputRefs": self._input_refs(step),
            "outputKey": self.output_key(step),
        }
        self.events.append(event)
        return event

    def finish_step(self, step: ApplicationStepRecord, *, prompt_run_id: str, status: str, output_summary: dict[str, Any]) -> dict[str, Any]:
        output_key = self.output_key(step)
        payload = {
            "outputKey": output_key,
            "stepOrder": step.stepOrder,
            "kind": step.kind,
            "skillId": step.skillId,
            "skillVersion": step.skillVersion,
            "skillName": step.skillName,
            "promptRunId": prompt_run_id,
            "status": status,
            "summary": output_summary,
        }
        self.outputs[output_key] = payload
        self.events.append(
            {
                "event": "step_finished",
                "stepOrder": step.stepOrder,
                "status": status,
                "promptRunId": prompt_run_id,
                "outputKey": output_key,
            }
        )
        return payload

    def fail_step(self, step: ApplicationStepRecord, *, error_message: str) -> None:
        self.events.append(
            {
                "event": "step_failed",
                "stepOrder": step.stepOrder,
                "kind": step.kind,
                "skillId": step.skillId,
                "error": error_message,
                "outputKey": self.output_key(step),
            }
        )

    def context_for_step(self, step: ApplicationStepRecord) -> dict[str, Any]:
        input_refs = self._input_refs(step)
        upstreams = [self.outputs[item] for item in input_refs if item in self.outputs]
        return {
            "protocol": self.protocol,
            "engine": self.engine,
            "engineAvailable": self.engine_available,
            "engineVersion": self.engine_version,
            "applicationId": self.application_id,
            "applicationRunId": self.application_run_id,
            "version": self.version,
            "taskId": self.task_id,
            "stepOrder": step.stepOrder,
            "inputRefs": input_refs,
            "outputKey": self.output_key(step),
            "upstreams": upstreams,
        }

    def runtime_meta(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "engine": self.engine,
            "engineAvailable": self.engine_available,
            "engineVersion": self.engine_version,
            "applicationRunId": self.application_run_id,
        }

    def output_key(self, step: ApplicationStepRecord) -> str:
        configured = str((step.dependencyRefs or {}).get("outputKey") or "").strip()
        if configured:
            return configured
        return f"step:{step.stepOrder}:{step.kind}:{step.skillId}:{step.skillVersion}"

    @staticmethod
    def _input_refs(step: ApplicationStepRecord) -> list[str]:
        refs = (step.dependencyRefs or {}).get("inputRefs")
        if not isinstance(refs, list):
            return []
        return [str(item).strip() for item in refs if str(item).strip()]
