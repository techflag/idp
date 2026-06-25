from __future__ import annotations

import os
from pathlib import Path

from app.core.config import (
    get_settings,
    _build_database_url,
    _build_sqlite_database_url,
    _is_sqlite_database_url,
    _load_local_env_file,
    _normalize_idp_edition,
    _normalize_object_storage_provider,
    _read_secret_env,
    _strip_env_value,
)


def test_strip_env_value_supports_quoted_strings() -> None:
    assert _strip_env_value('"token-value"') == "token-value"
    assert _strip_env_value("'token-value'") == "token-value"
    assert _strip_env_value(" token-value ") == "token-value"


def test_load_local_env_file_sets_missing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "# local secrets",
                "MINERU_TOKEN='test-token'",
                'DASHSCOPE_API_KEY="dashscope-key"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    _load_local_env_file(env_file)

    assert os.environ["MINERU_TOKEN"] == "test-token"
    assert os.environ["DASHSCOPE_API_KEY"] == "dashscope-key"


def test_load_local_env_file_keeps_existing_environment(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("MINERU_TOKEN=file-token\n", encoding="utf-8")

    monkeypatch.setenv("MINERU_TOKEN", "env-token")

    _load_local_env_file(env_file)

    assert os.environ["MINERU_TOKEN"] == "env-token"


def test_build_database_url_uses_mysql_pymysql_format() -> None:
    url = _build_database_url(
        host="db.example",
        port=3306,
        name="idp",
        user="idp_user",
        password="secret",
    )

    assert url == "mysql+pymysql://idp_user:secret@db.example:3306/idp?charset=utf8mb4"


def test_is_sqlite_database_url_accepts_sqlite_urls() -> None:
    assert _is_sqlite_database_url("sqlite+pysqlite:///tmp/idp.db") is True
    assert _is_sqlite_database_url(" sqlite:///tmp/idp.db") is True
    assert _is_sqlite_database_url("mysql+pymysql://example") is False
    assert _is_sqlite_database_url("") is False


def test_community_edition_defaults_to_sqlite(monkeypatch, tmp_path: Path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))

    try:
        settings = get_settings()
        assert settings.idp_edition == "community"
        assert settings.database_url == _build_sqlite_database_url(tmp_path / "runtime")
    finally:
        get_settings.cache_clear()


def test_community_edition_ignores_external_database_url_by_default(monkeypatch, tmp_path: Path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://idp:secret@db.example:3306/idp?charset=utf8mb4")
    monkeypatch.delenv("IDP_COMMUNITY_ALLOW_EXTERNAL_DATABASE", raising=False)
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))

    try:
        settings = get_settings()
        assert settings.idp_edition == "community"
        assert settings.database_url == _build_sqlite_database_url(tmp_path / "runtime")
    finally:
        get_settings.cache_clear()


def test_community_edition_can_opt_into_external_database_url(monkeypatch, tmp_path: Path) -> None:
    get_settings.cache_clear()
    external_url = "mysql+pymysql://idp:secret@db.example:3306/idp?charset=utf8mb4"
    monkeypatch.setenv("IDP_EDITION", "community")
    monkeypatch.setenv("DATABASE_URL", external_url)
    monkeypatch.setenv("IDP_COMMUNITY_ALLOW_EXTERNAL_DATABASE", "true")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))

    try:
        settings = get_settings()
        assert settings.idp_edition == "community"
        assert settings.database_url == external_url
    finally:
        get_settings.cache_clear()


def test_commercial_edition_defaults_to_mysql_when_database_url_is_missing(monkeypatch, tmp_path: Path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("IDP_EDITION", "commercial")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_NAME", "idp")
    monkeypatch.setenv("DB_USER", "idp_user")
    monkeypatch.setenv("DB_PASSWORD", "secret")

    try:
        settings = get_settings()
        assert settings.idp_edition == "commercial"
        assert settings.database_url == "mysql+pymysql://idp_user:secret@db.example:3307/idp?charset=utf8mb4"
    finally:
        get_settings.cache_clear()


def test_normalize_idp_edition_keeps_unknown_values_community() -> None:
    assert _normalize_idp_edition(None) == "community"
    assert _normalize_idp_edition("COMMERCIAL") == "commercial"
    assert _normalize_idp_edition("enterprise") == "commercial"
    assert _normalize_idp_edition("unexpected") == "community"


def test_normalize_object_storage_provider() -> None:
    assert _normalize_object_storage_provider(None) == "auto"
    assert _normalize_object_storage_provider("OSS") == "oss"
    assert _normalize_object_storage_provider("aliyun-oss") == "oss"
    assert _normalize_object_storage_provider("local") == "local"
    assert _normalize_object_storage_provider("unexpected") == "auto"


def test_read_secret_env_treats_placeholders_as_missing(monkeypatch) -> None:
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "replace-with-your-oss-access-key-id")
    monkeypatch.setenv("MINERU_TOKEN", "your-token")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "real-key")

    assert _read_secret_env("OSS_ACCESS_KEY_ID") is None
    assert _read_secret_env("MINERU_TOKEN") is None
    assert _read_secret_env("DASHSCOPE_API_KEY") == "real-key"


def test_evidence_v2_shadow_feature_flag(monkeypatch, tmp_path: Path) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("EVIDENCE_V2_SHADOW_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_V2_MODEL_INPUT_ENABLED", "false")
    monkeypatch.setenv("SEMANTIC_LOCATOR_SKIP_RERANK_MIN_CONFIDENCE", "0.91")

    try:
        settings = get_settings()
        assert settings.evidence_v2_shadow_enabled is False
        assert settings.evidence_v2_model_input_enabled is False
        assert settings.semantic_locator_skip_rerank_min_confidence == 0.91
    finally:
        get_settings.cache_clear()
