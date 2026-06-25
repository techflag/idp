# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Authentication primitives and signed cookie session helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.core.config import AppSettings


@dataclass
class AuthUser:
    id: str
    username: str
    passwordHash: str
    role: str
    displayName: str
    customerIds: list[str]
    enabled: bool = True


@dataclass
class SessionUser:
    id: str
    username: str
    role: str
    displayName: str
    customerIds: list[str]


def hash_password(password: str, *, salt: str | None = None, iterations: int = 600_000) -> str:
    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${actual_salt}${base64.urlsafe_b64encode(digest).decode('ascii')}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt, _expected = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt=salt, iterations=int(raw_iterations))
    return hmac.compare_digest(candidate, encoded)


def build_session_token(user: SessionUser, settings: AppSettings) -> str:
    payload = {
        "username": user.username,
        "exp": int(time.time()) + settings.auth_session_ttl_seconds,
    }
    raw_payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw_payload).decode("ascii")
    signature = hmac.new(
        settings.auth_secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def read_session_token(
    token: str | None,
    settings: AppSettings,
    user_loader,
) -> SessionUser | None:
    if not token:
        return None
    try:
        payload_b64, signature = token.rsplit(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(
        settings.auth_secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None

    if int(payload.get("exp") or 0) <= int(time.time()):
        return None

    username = payload.get("username")
    if not isinstance(username, str) or not username:
        return None
    return user_loader(username)

