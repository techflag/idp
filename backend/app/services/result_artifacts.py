"""Helpers for storing large task result payloads outside primary rows."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.oss import OssStorageService, UploadedObject


@dataclass(frozen=True)
class StoredJsonArtifact:
    objectKey: str
    contentHash: str
    sizeBytes: int
    contentType: str
    uploaded: UploadedObject


JSON_CONTENT_TYPE = "application/json; charset=utf-8"


def dumps_json_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def load_json_payload(text: str) -> Any:
    return json.loads(text)


def write_json_artifact(
    *,
    oss_service: OssStorageService,
    object_key: str,
    payload: Any,
    content_type: str = JSON_CONTENT_TYPE,
) -> StoredJsonArtifact:
    content = dumps_json_payload(payload)
    encoded = content.encode("utf-8")
    uploaded = oss_service.write_text_object(
        objectKey=object_key,
        content=content,
        contentType=content_type,
    )
    return StoredJsonArtifact(
        objectKey=uploaded.objectKey,
        contentHash=hashlib.sha256(encoded).hexdigest(),
        sizeBytes=len(encoded),
        contentType=content_type,
        uploaded=uploaded,
    )


def build_task_object_key(task_id: str, *parts: str) -> str:
    safe_parts = [_safe_object_key_part(part) for part in parts if str(part or "").strip()]
    return "/".join(["tasks", _safe_object_key_part(task_id), *safe_parts])


def safe_target_file_name(target_id: str) -> str:
    return f"{_safe_object_key_part(target_id)}.json"


def _safe_object_key_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._=-]+", "-", str(value).strip())
    return safe.strip("-") or "object"


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
