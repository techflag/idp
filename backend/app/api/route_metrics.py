"""Small route-level metrics helpers for payload-heavy IDP endpoints."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("app.api.metrics")


def metric_start() -> float:
    return time.perf_counter()


def estimate_payload_bytes(payload: Any) -> int:
    try:
        if hasattr(payload, "model_dump_json"):
            return len(payload.model_dump_json().encode("utf-8"))
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return -1


def log_response_metric(kind: str, *, started_at: float, payload: Any, **fields: Any) -> None:
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    field_text = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info(
        "[ApiMetric] kind=%s durationMs=%s payloadBytes=%s %s",
        kind,
        duration_ms,
        estimate_payload_bytes(payload),
        field_text,
    )
