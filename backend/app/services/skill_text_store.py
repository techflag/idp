# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Store SKILL.md text as an object asset and keep DB-friendly metadata."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from app.services.oss import OssStorageService


@dataclass(frozen=True)
class SkillTextAsset:
    objectKey: str
    sha256: str
    sizeBytes: int
    preview: str


def build_skill_text_asset(*, skill_text: str, object_key: str = "") -> SkillTextAsset:
    data = skill_text.encode("utf-8")
    return SkillTextAsset(
        objectKey=object_key,
        sha256=hashlib.sha256(data).hexdigest(),
        sizeBytes=len(data),
        preview=_preview_text(skill_text),
    )


def upload_skill_text_asset(
    *,
    storage: OssStorageService | None,
    customer_id: str | None,
    kind: str,
    skill_id: str,
    version: str,
    skill_text: str,
) -> SkillTextAsset:
    if storage is None:
        raise RuntimeError("OSS storage service is not configured")
    local_asset = build_skill_text_asset(skill_text=skill_text)
    uploaded = storage.upload_file(
        customerId=customer_id or "platform",
        fileName=f"{kind}-{skill_id}-{version}.SKILL.md",
        contentType="text/markdown; charset=utf-8",
        data=skill_text.encode("utf-8"),
    )
    return SkillTextAsset(
        objectKey=uploaded.objectKey,
        sha256=local_asset.sha256,
        sizeBytes=local_asset.sizeBytes,
        preview=local_asset.preview,
    )


def read_skill_text_asset(*, storage: OssStorageService | None, object_key: str) -> str:
    if storage is None:
        raise RuntimeError("OSS storage service is not configured")
    return storage.read_text_object(objectKey=object_key)


def strip_stored_skill_text(defaults: dict[str, object] | None) -> dict[str, object]:
    clean = dict(defaults or {})
    clean.pop("_skillText", None)
    return clean


def legacy_skill_text(defaults: dict[str, object] | None) -> str:
    value = (defaults or {}).get("_skillText")
    return str(value or "")


def _preview_text(text: str, limit: int = 2000) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized[:limit]
