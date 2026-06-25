# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Text normalization helpers for business-facing extraction evaluation."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_eval_text(value: Any) -> str:
    """Normalize harmless OCR/LLM formatting differences before comparison."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"\s+", "", text)
    text = _collapse_duplicate_separators(text)
    text = _normalize_separators(text)
    return text


def _collapse_duplicate_separators(text: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = re.sub(r"([,，、;；:/\\|])\1+", r"\1", current)
        current = re.sub(r"([,，、;；])([,，、;；])+", r"\1", current)
    return current


def _normalize_separators(text: str) -> str:
    replacements = {
        "，": ",",
        "、": ",",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "＜": "<",
        "＞": ">",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text
