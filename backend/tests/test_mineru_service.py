from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.mineru import HttpMineruService, MineruProviderError


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        mineru_token="test-token",
        mineru_base_url="https://mineru.test/api/v4",
        mineru_model_version="vlm",
        mineru_language="ch",
        mineru_enable_formula=True,
        mineru_enable_table=True,
        mineru_enable_ocr=False,
    )


def test_mineru_submit_reports_provider_error_response(monkeypatch) -> None:
    def fake_urlopen(request, timeout=0, context=None):
        _ = (request, timeout, context)
        return _FakeResponse({"code": 1001, "msg": "URL is not accessible", "data": {}})

    monkeypatch.setattr("app.services.mineru.urlopen", fake_urlopen)

    service = HttpMineruService(_settings())  # type: ignore[arg-type]

    with pytest.raises(MineruProviderError, match="URL is not accessible"):
        service.submit_url(fileUrl="https://example.invalid/sample.pdf", dataId="task-1")


def test_mineru_submit_rejects_success_response_without_task_id(monkeypatch) -> None:
    def fake_urlopen(request, timeout=0, context=None):
        _ = (request, timeout, context)
        return _FakeResponse({"code": 0, "msg": "ok", "data": {"state": "accepted"}})

    monkeypatch.setattr("app.services.mineru.urlopen", fake_urlopen)

    service = HttpMineruService(_settings())  # type: ignore[arg-type]

    with pytest.raises(MineruProviderError, match="缺少 task_id"):
        service.submit_url(fileUrl="https://example.invalid/sample.pdf", dataId="task-1")
