# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Application settings shared across the backend service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus


def _strip_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _load_local_env_file(env_file: Path) -> None:
    """Load simple KEY=VALUE pairs without overriding existing env vars."""

    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        env_name = key.strip()
        if not env_name:
            continue
        os.environ.setdefault(env_name, _strip_env_value(raw_value))


def _get_latest_runtime_bundle_dir(runtime_data_dir: Path) -> Path | None:
    """Prefer a real parsed bundle under `.runtime/artifacts/*/bundle` when present."""

    artifacts_dir = runtime_data_dir / "artifacts"
    if not artifacts_dir.exists():
        return None

    bundle_dirs = [path for path in artifacts_dir.glob("*/bundle") if path.is_dir()]
    if not bundle_dirs:
        return None

    def bundle_mtime(path: Path) -> float:
        latest_mtime = path.stat().st_mtime
        for child in path.rglob("*"):
            try:
                latest_mtime = max(latest_mtime, child.stat().st_mtime)
            except FileNotFoundError:
                continue
        return latest_mtime

    return max(bundle_dirs, key=bundle_mtime)


def _resolve_sample_doc_dir(runtime_data_dir: Path) -> Path:
    configured = os.getenv("SAMPLE_DOC_DIR")
    if configured:
        return Path(configured)

    latest_bundle_dir = _get_latest_runtime_bundle_dir(runtime_data_dir)
    if latest_bundle_dir is not None:
        return latest_bundle_dir

    return runtime_data_dir / "sample-doc"


@dataclass(frozen=True)
class AppSettings:
    """Keep runtime configuration in one place and avoid hardcoded secrets."""

    app_name: str
    api_prefix: str
    root_dir: Path
    sample_doc_dir: Path
    runtime_data_dir: Path
    backend_public_base_url: str
    cors_origins: tuple[str, ...]
    oss_bucket: str
    oss_region: str
    oss_public_base_url: str
    oss_access_key_id: str | None
    oss_access_key_secret: str | None
    object_storage_provider: str
    mineru_token: str | None
    mineru_base_url: str
    mineru_model_version: str
    mineru_language: str
    mineru_enable_formula: bool
    mineru_enable_table: bool
    mineru_enable_ocr: bool
    dashscope_api_key: str | None
    dashscope_base_url: str
    dashscope_model: str
    prompt_default_page_group_size: int
    auth_secret: str
    auth_cookie_name: str
    auth_session_ttl_seconds: int
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    database_url: str
    db_pool_size: int
    db_max_overflow: int
    db_pool_recycle_seconds: int
    db_echo: bool
    idp_edition: str = "community"
    oss_endpoint: str = ""
    semantic_locator_llm_rerank_enabled: bool = False
    semantic_locator_llm_rerank_model: str = ""
    semantic_locator_llm_rerank_top_k: int = 6
    semantic_locator_llm_rerank_gap_threshold: float = 0.18
    semantic_locator_skip_rerank_min_confidence: float = 0.86
    evidence_v2_shadow_enabled: bool = True
    evidence_v2_model_input_enabled: bool = True


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _read_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _build_database_url(*, host: str, port: int, name: str, user: str, password: str) -> str:
    encoded_user = quote_plus(user)
    encoded_password = quote_plus(password)
    return f"mysql+pymysql://{encoded_user}:{encoded_password}@{host}:{port}/{name}?charset=utf8mb4"


def _build_sqlite_database_url(runtime_data_dir: Path) -> str:
    return f"sqlite+pysqlite:///{(runtime_data_dir / 'idp-community.db').as_posix()}"


def _is_sqlite_database_url(value: str | None) -> bool:
    return bool(value and value.strip().lower().startswith("sqlite"))


def _normalize_idp_edition(raw: str | None) -> str:
    normalized = (raw or "community").strip().lower()
    if normalized in {"commercial", "enterprise"}:
        return "commercial"
    return "community"


def _normalize_object_storage_provider(raw: str | None) -> str:
    normalized = (raw or "auto").strip().lower()
    if normalized in {"oss", "aliyun", "aliyun-oss"}:
        return "oss"
    if normalized in {"local", "filesystem", "file"}:
        return "local"
    return "auto"


def _read_secret_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip().strip("'\"")
    if not stripped:
        return None
    normalized = stripped.lower()
    if (
        normalized.startswith("replace-with-")
        or normalized.startswith("your-")
        or normalized in {"changeme", "change-me", "your-token", "your-api-key", "your-secret"}
        or "replace-with-your" in normalized
    ):
        return None
    return stripped


def _default_oss_endpoint(region: str) -> str:
    normalized = region.strip()
    return f"https://oss-{normalized}.aliyuncs.com" if normalized else ""


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Build settings once so route handlers can reuse the same configuration."""

    root_dir = Path(__file__).resolve().parents[3]
    _load_local_env_file(root_dir / "backend" / ".env.local")
    runtime_data_dir = Path(os.getenv("RUNTIME_DATA_DIR", root_dir / "backend" / ".runtime"))
    sample_doc_dir = _resolve_sample_doc_dir(runtime_data_dir)
    idp_edition = _normalize_idp_edition(os.getenv("IDP_EDITION"))
    cors_raw = os.getenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    )
    public_base_url = os.getenv("OSS_PUBLIC_BASE_URL", "https://example-bucket.oss-cn-beijing.aliyuncs.com")
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_port = max(1, int(os.getenv("DB_PORT", "3306")))
    db_name = os.getenv("DB_NAME", "techflag_poc")
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    configured_database_url = os.getenv("DATABASE_URL")
    allow_community_external_database = _read_bool_env("IDP_COMMUNITY_ALLOW_EXTERNAL_DATABASE", False)
    if idp_edition == "community":
        if _is_sqlite_database_url(configured_database_url) or (
            configured_database_url and allow_community_external_database
        ):
            database_url = configured_database_url
        else:
            database_url = _build_sqlite_database_url(runtime_data_dir)
    else:
        database_url = configured_database_url or _build_database_url(
            host=db_host,
            port=db_port,
            name=db_name,
            user=db_user,
            password=db_password,
        )

    return AppSettings(
        app_name=os.getenv("APP_NAME", "IDP PoC Workbench Backend"),
        api_prefix=os.getenv("API_PREFIX", "/api"),
        idp_edition=idp_edition,
        root_dir=root_dir,
        sample_doc_dir=sample_doc_dir,
        runtime_data_dir=runtime_data_dir,
        backend_public_base_url=os.getenv("BACKEND_PUBLIC_BASE_URL", "").rstrip("/"),
        cors_origins=tuple(origin.strip() for origin in cors_raw.split(",") if origin.strip()),
        oss_bucket=os.getenv("OSS_BUCKET", "idp-poc-demo"),
        oss_region=os.getenv("OSS_REGION", "cn-beijing"),
        oss_public_base_url=public_base_url.rstrip("/"),
        oss_endpoint=(os.getenv("OSS_ENDPOINT") or _default_oss_endpoint(os.getenv("OSS_REGION", "cn-beijing"))).rstrip("/"),
        oss_access_key_id=_read_secret_env("OSS_ACCESS_KEY_ID"),
        oss_access_key_secret=_read_secret_env("OSS_ACCESS_KEY_SECRET"),
        object_storage_provider=_normalize_object_storage_provider(os.getenv("OBJECT_STORAGE_PROVIDER")),
        mineru_token=_read_secret_env("MINERU_TOKEN"),
        mineru_base_url=os.getenv("MINERU_BASE_URL", "https://mineru.net/api/v4").rstrip("/"),
        mineru_model_version=os.getenv("MINERU_MODEL_VERSION", "vlm"),
        mineru_language=os.getenv("MINERU_LANGUAGE", "ch"),
        mineru_enable_formula=_read_bool_env("MINERU_ENABLE_FORMULA", True),
        mineru_enable_table=_read_bool_env("MINERU_ENABLE_TABLE", True),
        mineru_enable_ocr=_read_bool_env("MINERU_ENABLE_OCR", False),
        dashscope_api_key=_read_secret_env("DASHSCOPE_API_KEY"),
        dashscope_base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).rstrip("/"),
        dashscope_model=os.getenv("DASHSCOPE_MODEL", "qwen3.6-27b"),
        semantic_locator_llm_rerank_enabled=_read_bool_env("SEMANTIC_LOCATOR_LLM_RERANK_ENABLED", False),
        semantic_locator_llm_rerank_model=os.getenv("SEMANTIC_LOCATOR_LLM_RERANK_MODEL", ""),
        semantic_locator_llm_rerank_top_k=_read_int_env("SEMANTIC_LOCATOR_LLM_RERANK_TOP_K", 6, minimum=1, maximum=12),
        semantic_locator_llm_rerank_gap_threshold=_read_float_env(
            "SEMANTIC_LOCATOR_LLM_RERANK_GAP_THRESHOLD",
            0.18,
            minimum=0.0,
            maximum=1.0,
        ),
        semantic_locator_skip_rerank_min_confidence=_read_float_env(
            "SEMANTIC_LOCATOR_SKIP_RERANK_MIN_CONFIDENCE",
            0.86,
            minimum=0.0,
            maximum=1.0,
        ),
        evidence_v2_shadow_enabled=_read_bool_env("EVIDENCE_V2_SHADOW_ENABLED", True),
        evidence_v2_model_input_enabled=_read_bool_env("EVIDENCE_V2_MODEL_INPUT_ENABLED", True),
        prompt_default_page_group_size=max(1, int(os.getenv("PROMPT_DEFAULT_PAGE_GROUP_SIZE", "3"))),
        auth_secret=os.getenv("AUTH_SECRET", "idp-poc-dev-auth-secret"),
        auth_cookie_name=os.getenv("AUTH_COOKIE_NAME", "idp_poc_session"),
        auth_session_ttl_seconds=max(300, int(os.getenv("AUTH_SESSION_TTL_SECONDS", "604800"))),
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        database_url=database_url,
        db_pool_size=max(1, int(os.getenv("DB_POOL_SIZE", "5"))),
        db_max_overflow=max(0, int(os.getenv("DB_MAX_OVERFLOW", "10"))),
        db_pool_recycle_seconds=max(60, int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))),
        db_echo=_read_bool_env("DB_ECHO", False),
    )
