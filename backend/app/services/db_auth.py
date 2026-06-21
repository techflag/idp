"""Database-backed authentication service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import UserModel, utcnow
from app.db.session import session_scope
from app.services.auth import AuthUser, SessionUser, build_session_token, hash_password, read_session_token, verify_password


@dataclass
class DbAuthService:
    def authenticate(self, username: str, password: str) -> SessionUser:
        user = self._find_user(username)
        if not user or not user.enabled or not verify_password(password, user.passwordHash):
            raise RuntimeError("账号或密码错误")
        return self._to_session_user(user)

    def get_user(self, username: str) -> SessionUser | None:
        user = self._find_user(username)
        if not user or not user.enabled:
            return None
        return self._to_session_user(user)

    def is_username_available(self, username: str) -> bool:
        return self._find_user(username) is None

    def create_customer_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        customer_ids: list[str],
    ) -> SessionUser:
        normalized_username = username.strip()
        normalized_display_name = display_name.strip()
        normalized_customer_ids = self._normalize_customer_ids(customer_ids)

        if len(normalized_username) < 3:
            raise RuntimeError("登录账号至少需要 3 个字符")
        if len(password) < 6:
            raise RuntimeError("初始密码至少需要 6 个字符")
        if not normalized_display_name:
            raise RuntimeError("客户显示名不能为空")
        if not normalized_customer_ids:
            raise RuntimeError("客户账号至少需要绑定 1 个客户空间")
        if not self.is_username_available(normalized_username):
            raise RuntimeError("登录账号已存在，请更换用户名")

        now = utcnow()
        user = UserModel(
            id=f"customer-user-{uuid4().hex[:8]}",
            username=normalized_username,
            password_hash=hash_password(password),
            role="customer",
            display_name=normalized_display_name,
            customer_ids_json=json.dumps(normalized_customer_ids, ensure_ascii=False),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        with session_scope() as session:
            session.add(user)
        return self._to_session_user(self._to_auth_user(user))

    def build_session_token(self, user: SessionUser) -> str:
        return build_session_token(user, get_settings())

    def read_session_token(self, token: str | None) -> SessionUser | None:
        return read_session_token(token, get_settings(), self.get_user)

    def _find_user(self, username: str) -> AuthUser | None:
        normalized = username.strip()
        if not normalized:
            return None

        with session_scope() as session:
            model = session.execute(
                select(UserModel).where(func.lower(UserModel.username) == normalized.lower())
            ).scalar_one_or_none()
            if not model:
                return None
            return self._to_auth_user(model)

    @staticmethod
    def _normalize_customer_ids(customer_ids: list[str]) -> list[str]:
        normalized_ids: list[str] = []
        seen_customer_ids: set[str] = set()
        for customer_id in customer_ids:
            normalized_id = str(customer_id).strip()
            if not normalized_id or normalized_id in seen_customer_ids:
                continue
            normalized_ids.append(normalized_id)
            seen_customer_ids.add(normalized_id)
        return normalized_ids

    @staticmethod
    def _to_auth_user(model: UserModel) -> AuthUser:
        return AuthUser(
            id=model.id,
            username=model.username,
            passwordHash=model.password_hash,
            role=model.role,
            displayName=model.display_name,
            customerIds=_loads_json_list(model.customer_ids_json),
            enabled=bool(model.enabled),
        )

    @staticmethod
    def _to_session_user(user: AuthUser) -> SessionUser:
        return SessionUser(
            id=user.id,
            username=user.username,
            role=user.role,
            displayName=user.displayName,
            customerIds=list(user.customerIds),
        )


def _loads_json_list(value: str | None) -> list[str]:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User customer_ids_json is null in database",
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User customer_ids_json is not valid JSON in database",
        ) from None
    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User customer_ids_json must be a JSON array in database",
        )
    return [str(item) for item in parsed if str(item).strip()]
