#!/usr/bin/env python3
"""Diagnose DB-backed login state and optionally create the default admin.

Run from backend:
    python3 scripts/diagnose_auth.py
    python3 scripts/diagnose_auth.py --ensure-admin
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.models import CustomerModel, UserModel, utcnow
from app.db.session import get_engine, session_scope
from app.services.auth import hash_password, verify_password


DEFAULT_ADMIN_ID = "user-admin-001"
DEFAULT_ADMIN_USERNAME = "idp-admin"
DEFAULT_ADMIN_PASSWORD = "demo-pass"
DEFAULT_ADMIN_DISPLAY_NAME = "管理员"
DEFAULT_SCENE_WORKSPACE_ID = "community-scenario-app"
DEFAULT_SCENE_WORKSPACE_NAME = "场景应用"
DEFAULT_SCENE_WORKSPACE_CODE = "COMMUNITY-SCENE"
DEFAULT_SCENE_WORKSPACE_OWNER = "本地用户"
DEFAULT_SCENE_WORKSPACE_DESCRIPTION = "社区版本地默认场景应用空间。"


def _mask_database_url(value: str) -> str:
    if "://" not in value or "@" not in value:
        return value
    prefix, rest = value.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" not in credentials:
        return f"{prefix}://***@{host}"
    username, _password = credentials.split(":", 1)
    return f"{prefix}://{username}:***@{host}"


def _safe_count(table_name: str) -> int | None:
    try:
        with get_engine().connect() as connection:
            return int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)
    except SQLAlchemyError:
        return None


def _get_alembic_versions() -> list[str]:
    try:
        with get_engine().connect() as connection:
            rows = connection.execute(text("SELECT version_num FROM alembic_version")).all()
            return [str(row[0]) for row in rows]
    except SQLAlchemyError:
        return []


def _load_admin() -> UserModel | None:
    with session_scope() as session:
        return session.execute(
            select(UserModel).where(UserModel.username == DEFAULT_ADMIN_USERNAME)
        ).scalar_one_or_none()


def _load_default_workspace() -> CustomerModel | None:
    with session_scope() as session:
        return session.get(CustomerModel, DEFAULT_SCENE_WORKSPACE_ID)


def _ensure_admin(*, password: str) -> dict[str, Any]:
    now = utcnow()
    with session_scope() as session:
        model = session.execute(
            select(UserModel).where(UserModel.username == DEFAULT_ADMIN_USERNAME)
        ).scalar_one_or_none()
        if model is None:
            model = UserModel(
                id=DEFAULT_ADMIN_ID,
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(password),
                role="admin",
                display_name=DEFAULT_ADMIN_DISPLAY_NAME,
                customer_ids_json="[]",
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            return {"action": "created", "username": DEFAULT_ADMIN_USERNAME, "enabled": True}

        model.password_hash = hash_password(password)
        model.role = "admin"
        model.display_name = model.display_name or DEFAULT_ADMIN_DISPLAY_NAME
        model.customer_ids_json = model.customer_ids_json or "[]"
        model.enabled = True
        model.updated_at = now
        return {"action": "updated", "username": DEFAULT_ADMIN_USERNAME, "enabled": True}


def _ensure_default_workspace() -> dict[str, Any]:
    now = utcnow()
    with session_scope() as session:
        model = session.get(CustomerModel, DEFAULT_SCENE_WORKSPACE_ID)
        if model is None:
            model = CustomerModel(
                id=DEFAULT_SCENE_WORKSPACE_ID,
                name=DEFAULT_SCENE_WORKSPACE_NAME,
                project_code=DEFAULT_SCENE_WORKSPACE_CODE,
                owner=DEFAULT_SCENE_WORKSPACE_OWNER,
                description=DEFAULT_SCENE_WORKSPACE_DESCRIPTION,
                created_at=now,
            )
            session.add(model)
            return {
                "action": "created",
                "id": DEFAULT_SCENE_WORKSPACE_ID,
                "name": DEFAULT_SCENE_WORKSPACE_NAME,
            }

        model.name = DEFAULT_SCENE_WORKSPACE_NAME
        model.project_code = DEFAULT_SCENE_WORKSPACE_CODE
        model.owner = DEFAULT_SCENE_WORKSPACE_OWNER
        model.description = DEFAULT_SCENE_WORKSPACE_DESCRIPTION
        return {
            "action": "updated",
            "id": DEFAULT_SCENE_WORKSPACE_ID,
            "name": DEFAULT_SCENE_WORKSPACE_NAME,
        }


def diagnose() -> dict[str, Any]:
    settings = get_settings()
    engine = get_engine()
    result: dict[str, Any] = {
        "database_url": _mask_database_url(settings.database_url),
        "db_name": settings.db_name,
        "api_prefix": settings.api_prefix,
        "runtime_data_dir": str(settings.runtime_data_dir),
        "connection_ok": False,
        "alembic_versions": [],
        "tables": {},
        "admin": {"username": DEFAULT_ADMIN_USERNAME, "exists": False},
        "default_workspace": {
            "id": DEFAULT_SCENE_WORKSPACE_ID,
            "name": DEFAULT_SCENE_WORKSPACE_NAME,
            "exists": False,
        },
    }

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        result["connection_ok"] = True
    except SQLAlchemyError as error:
        result["connection_error"] = str(error)
        return result

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    for table_name in ("alembic_version", "users", "customers", "documents", "tasks"):
        result["tables"][table_name] = {
            "exists": table_name in table_names,
            "row_count": _safe_count(table_name) if table_name in table_names else None,
        }
    result["alembic_versions"] = _get_alembic_versions()

    if "users" not in table_names:
        result["admin"]["error"] = "users table is missing; run alembic upgrade head"
        return result

    try:
        admin = _load_admin()
    except SQLAlchemyError as error:
        result["admin"]["error"] = str(error)
        return result

    if admin is None:
        pass
    else:
        result["admin"] = {
            "username": admin.username,
            "exists": True,
            "enabled": bool(admin.enabled),
            "role": admin.role,
            "customer_ids_json_valid": _is_json_array(admin.customer_ids_json),
            "demo_pass_matches": verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash),
        }

    if "customers" in table_names:
        try:
            workspace = _load_default_workspace()
        except SQLAlchemyError as error:
            result["default_workspace"]["error"] = str(error)
        else:
            if workspace is not None:
                result["default_workspace"] = {
                    "id": workspace.id,
                    "name": workspace.name,
                    "exists": True,
                    "projectCode": workspace.project_code,
                }
    return result


def _is_json_array(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(parsed, list)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose auth DB state.")
    parser.add_argument("--ensure-admin", action="store_true", help="Create/update idp-admin with the provided password.")
    parser.add_argument("--password", default=DEFAULT_ADMIN_PASSWORD, help="Password used with --ensure-admin.")
    args = parser.parse_args()

    before = diagnose()
    print(json.dumps({"before": before}, ensure_ascii=False, indent=2))

    if args.ensure_admin:
        users_table = before.get("tables", {}).get("users", {})
        if not isinstance(users_table, dict) or not users_table.get("exists"):
            print(
                json.dumps(
                    {
                        "admin_seed": {
                            "error": "users table is missing; run: alembic -c alembic.ini upgrade head",
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(1)
        customers_table = before.get("tables", {}).get("customers", {})
        if not isinstance(customers_table, dict) or not customers_table.get("exists"):
            print(
                json.dumps(
                    {
                        "default_workspace_seed": {
                            "error": "customers table is missing; run: alembic -c alembic.ini upgrade head",
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(1)
        action = _ensure_admin(password=args.password)
        workspace_action = _ensure_default_workspace()
        after = diagnose()
        print(
            json.dumps(
                {"admin_seed": action, "default_workspace_seed": workspace_action, "after": after},
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
