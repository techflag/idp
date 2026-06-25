# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""MinerU v4 client for task submission, polling and result download."""

from __future__ import annotations

import json
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import AppSettings

MINERU_APPLY_URL = "https://mineru.net/?source=github"


class MineruConfigurationError(RuntimeError):
    """Raised when MinerU is required but not configured."""


class MineruProviderError(RuntimeError):
    """Raised when MinerU responds but does not accept or describe the task."""


@dataclass
class MineruTaskSnapshot:
    taskId: str
    state: str
    traceId: str | None = None
    errorMessage: str | None = None
    fullZipUrl: str | None = None
    dataId: str | None = None
    extractedPages: int = 0
    totalPages: int = 0
    startTime: str | None = None


class MineruService(ABC):
    def ensure_configured(self) -> None:
        return None

    @abstractmethod
    def submit_url(self, *, fileUrl: str, dataId: str | None = None, callbackUrl: str | None = None) -> MineruTaskSnapshot:
        """Create a MinerU parse task from an object-storage accessible file URL."""

    @abstractmethod
    def get_task(self, mineruTaskId: str) -> MineruTaskSnapshot:
        """Fetch the latest MinerU task snapshot."""

    @abstractmethod
    def download_result_bundle(self, fullZipUrl: str) -> bytes:
        """Download the final extracted bundle from MinerU CDN/storage."""


class HttpMineruService(MineruService):
    def __init__(self, settings: AppSettings) -> None:
        if not settings.mineru_token:
            raise MineruConfigurationError("MINERU_TOKEN is not configured")
        self._settings = settings

    def submit_url(self, *, fileUrl: str, dataId: str | None = None, callbackUrl: str | None = None) -> MineruTaskSnapshot:
        payload: dict[str, Any] = {
            "url": fileUrl,
            "model_version": self._settings.mineru_model_version,
            "language": self._settings.mineru_language,
            "enable_formula": self._settings.mineru_enable_formula,
            "enable_table": self._settings.mineru_enable_table,
            "is_ocr": self._settings.mineru_enable_ocr,
        }
        if dataId:
            payload["data_id"] = dataId
        if callbackUrl:
            payload["callback"] = callbackUrl

        body = self._request("POST", "/extract/task", payload)
        data = _extract_response_data(body, context="提交文档解析任务")
        task_id = data.get("task_id")
        if not task_id:
            raise MineruProviderError(_format_unexpected_response("提交文档解析任务", body))
        return MineruTaskSnapshot(
            taskId=str(task_id),
            state="pending",
            traceId=body.get("trace_id"),
            dataId=dataId,
        )

    def get_task(self, mineruTaskId: str) -> MineruTaskSnapshot:
        body = self._request("GET", f"/extract/task/{mineruTaskId}")
        data = _extract_response_data(body, context="查询文档解析任务")
        progress = data.get("extract_progress") or {}
        return MineruTaskSnapshot(
            taskId=str(data.get("task_id") or mineruTaskId),
            state=str(data.get("state") or "pending"),
            traceId=body.get("trace_id"),
            errorMessage=data.get("err_msg") or None,
            fullZipUrl=data.get("full_zip_url") or None,
            dataId=data.get("data_id") or None,
            extractedPages=int(progress.get("extracted_pages") or 0),
            totalPages=int(progress.get("total_pages") or 0),
            startTime=progress.get("start_time") or None,
        )

    def download_result_bundle(self, fullZipUrl: str) -> bytes:
        request = Request(fullZipUrl, headers={"User-Agent": "idp-poc-backend/1.0"})
        with urlopen(request, timeout=120, context=_build_ssl_context()) as response:
            return response.read()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._settings.mineru_base_url}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self._settings.mineru_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, method=method, headers=headers, data=data)
        try:
            with urlopen(request, timeout=60, context=_build_ssl_context()) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise MineruProviderError("文档解析服务返回了非对象 JSON。")
                return parsed
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"文档解析服务请求失败: HTTP {error.code} {detail}") from error
        except URLError as error:
            raise RuntimeError(f"文档解析服务请求失败: {error.reason}") from error
        except json.JSONDecodeError as error:
            raise MineruProviderError("文档解析服务返回了无法解析的 JSON。") from error


class UnavailableMineruService(MineruService):
    """Return a clear configuration error without failing dependency creation."""

    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason or f"未配置 MinerU Token，请先到 {MINERU_APPLY_URL} 申请并配置 MINERU_TOKEN。"

    def ensure_configured(self) -> None:
        raise MineruConfigurationError(self._reason)

    def submit_url(self, *, fileUrl: str, dataId: str | None = None, callbackUrl: str | None = None) -> MineruTaskSnapshot:
        self.ensure_configured()
        raise AssertionError("unreachable")

    def get_task(self, mineruTaskId: str) -> MineruTaskSnapshot:
        self.ensure_configured()
        raise AssertionError("unreachable")

    def download_result_bundle(self, fullZipUrl: str) -> bytes:
        self.ensure_configured()
        raise AssertionError("unreachable")


def build_mineru_service(settings: AppSettings) -> MineruService:
    if settings.mineru_token:
        return HttpMineruService(settings)
    return UnavailableMineruService()


def _extract_response_data(body: dict[str, Any], *, context: str) -> dict[str, Any]:
    code = body.get("code")
    if code not in (None, 0, "0"):
        raise MineruProviderError(_format_provider_error(context, body))

    data = body.get("data")
    if isinstance(data, dict):
        return data
    if data is None and any(key in body for key in ("task_id", "state", "full_zip_url")):
        return body

    message = _provider_message(body)
    if message:
        raise MineruProviderError(f"{context}失败：{message}")
    raise MineruProviderError(_format_unexpected_response(context, body))


def _format_provider_error(context: str, body: dict[str, Any]) -> str:
    message = _provider_message(body)
    code = body.get("code")
    if message:
        return f"{context}失败：{message} (code={code})"
    return f"{context}失败：文档解析服务返回错误 code={code}。"


def _provider_message(body: dict[str, Any]) -> str:
    for key in ("msg", "message", "err_msg", "error", "detail"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = body.get("data")
    if isinstance(data, dict):
        for key in ("msg", "message", "err_msg", "error", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _format_unexpected_response(context: str, body: dict[str, Any]) -> str:
    visible_keys = ", ".join(sorted(str(key) for key in body.keys())) or "empty"
    return f"{context}失败：文档解析服务返回内容缺少 task_id 或有效 data 字段，返回字段: {visible_keys}。"


def _build_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()
