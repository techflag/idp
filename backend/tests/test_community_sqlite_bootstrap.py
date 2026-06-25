from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _community_env(runtime_dir: Path, overrides: dict[str, str] | None = None) -> dict[str, str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "IDP_EDITION": "community",
            "DATABASE_URL": "",
            "IDP_COMMUNITY_ALLOW_EXTERNAL_DATABASE": "false",
            "RUNTIME_DATA_DIR": str(runtime_dir),
            "OBJECT_STORAGE_PROVIDER": "local",
            "MINERU_TOKEN": "",
            "OSS_ACCESS_KEY_ID": "",
            "OSS_ACCESS_KEY_SECRET": "",
        }
    )
    if overrides:
        env.update(overrides)
    return env


def _run_backend_command(args: list[str], *, runtime_dir: Path, env_overrides: dict[str, str] | None = None) -> None:
    subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND_ROOT,
        env=_community_env(runtime_dir, env_overrides),
        check=True,
        capture_output=True,
        text=True,
    )


def _run_backend_python(
    code: str,
    *,
    runtime_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT,
        env=_community_env(runtime_dir, env_overrides),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _customer_rows(runtime_dir: Path) -> list[tuple[str, str]]:
    engine = create_engine(f"sqlite+pysqlite:///{runtime_dir / 'idp-community.db'}")
    with engine.connect() as connection:
        rows = connection.execute(text("select id, name from customers order by id")).all()
    return [(str(row[0]), str(row[1])) for row in rows]


def test_community_sqlite_bootstrap_only_seeds_scene_workspace(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"

    _run_backend_command(["-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], runtime_dir=runtime_dir)
    assert _customer_rows(runtime_dir) == []

    _run_backend_command(
        ["scripts/diagnose_auth.py", "--ensure-admin", "--password", "demo-pass"],
        runtime_dir=runtime_dir,
    )

    assert _customer_rows(runtime_dir) == [("community-scenario-app", "场景应用")]


def test_community_upload_keeps_document_when_mineru_is_missing(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    _run_backend_command(["-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], runtime_dir=runtime_dir)
    _run_backend_command(
        ["scripts/diagnose_auth.py", "--ensure-admin", "--password", "demo-pass"],
        runtime_dir=runtime_dir,
    )

    result = _run_backend_python(
        """
import json
from app.core.config import get_settings
from app.repositories.mysql_repository import MysqlWorkbenchRepository
from app.services.mineru import build_mineru_service
from app.services.oss import build_oss_storage_service
from app.services.parse_pipeline import ParsePipelineService
from app.services.runtime_store import JsonRuntimeStore

settings = get_settings()
store = JsonRuntimeStore(settings)
oss = build_oss_storage_service(settings)
repository = MysqlWorkbenchRepository(store, settings, oss)
pipeline = ParsePipelineService(
    repository=repository,
    oss_service=oss,
    mineru_service=build_mineru_service(settings),
    runtime_store=store,
    settings=settings,
)
response = pipeline.upload_and_parse(
    customerId='community-scenario-app',
    fileName='sample.pdf',
    contentType='application/pdf',
    data=b'%PDF-1.4\\ncommunity sample\\n',
    uploadedByUserId='idp-admin',
    uploadedByName='管理员',
    roleScope=['admin', 'customer'],
)
poll = pipeline.poll_parse(response.createdTask.id)
print(json.dumps({
    'documentId': response.document.id,
    'documentParseStatus': response.document.parseStatus,
    'taskId': response.createdTask.id,
    'taskStatus': response.createdTask.status,
    'parseState': response.parse.state,
    'mineruState': response.parse.mineruState,
    'errorMessage': response.parse.errorMessage,
    'pollState': poll.state,
    'pollMineruState': poll.mineruState,
}, ensure_ascii=False))
""",
        runtime_dir=runtime_dir,
    )

    assert result["documentId"]
    assert result["taskId"]
    assert result["documentParseStatus"] == "failed"
    assert result["taskStatus"] == "failed"
    assert result["parseState"] == "failed"
    assert result["mineruState"] == "not_configured"
    assert result["pollState"] == "failed"
    assert result["pollMineruState"] == "not_configured"
    assert "MINERU_TOKEN" in str(result["errorMessage"])


def test_community_local_storage_with_mineru_token_fails_without_public_file_url(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    env_overrides = {"MINERU_TOKEN": "test-token"}
    _run_backend_command(["-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], runtime_dir=runtime_dir, env_overrides=env_overrides)
    _run_backend_command(
        ["scripts/diagnose_auth.py", "--ensure-admin", "--password", "demo-pass"],
        runtime_dir=runtime_dir,
        env_overrides=env_overrides,
    )

    result = _run_backend_python(
        """
import json
from app.core.config import get_settings
from app.repositories.mysql_repository import MysqlWorkbenchRepository
from app.services.mineru import build_mineru_service
from app.services.oss import build_oss_storage_service
from app.services.parse_pipeline import ParsePipelineService
from app.services.runtime_store import JsonRuntimeStore

settings = get_settings()
store = JsonRuntimeStore(settings)
oss = build_oss_storage_service(settings)
repository = MysqlWorkbenchRepository(store, settings, oss)
pipeline = ParsePipelineService(
    repository=repository,
    oss_service=oss,
    mineru_service=build_mineru_service(settings),
    runtime_store=store,
    settings=settings,
)
response = pipeline.upload_and_parse(
    customerId='community-scenario-app',
    fileName='sample.pdf',
    contentType='application/pdf',
    data=b'%PDF-1.4\\ncommunity sample\\n',
    uploadedByUserId='idp-admin',
    uploadedByName='管理员',
    roleScope=['admin', 'customer'],
)
poll = pipeline.poll_parse(response.createdTask.id)
print(json.dumps({
    'sourceUrl': response.document.sourceUrl,
    'parseState': response.parse.state,
    'mineruState': response.parse.mineruState,
    'errorMessage': response.parse.errorMessage,
    'pollState': poll.state,
}, ensure_ascii=False))
""",
        runtime_dir=runtime_dir,
        env_overrides=env_overrides,
    )

    assert str(result["sourceUrl"]).startswith("/api/objects/")
    assert result["parseState"] == "failed"
    assert result["mineruState"] == "failed"
    assert result["pollState"] == "failed"
    assert "BACKEND_PUBLIC_BASE_URL" in str(result["errorMessage"])
