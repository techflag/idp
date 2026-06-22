"""Document upload and MinerU parse orchestration."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import AppSettings
from app.domain.models import ParseJobRecord
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    ParseArtifactUrls,
    ParseProgress,
    ParseTaskStatusResponse,
    RegisterDocumentRequest,
    UploadAndParseResponse,
)
from app.services.mineru import MineruConfigurationError, MineruProviderError, MineruService
from app.services.oss import OssStorageService
from app.services.document_tree_artifacts import (
    DOCUMENT_TREE_CATEGORY,
    build_document_tree_from_raw_artifact,
    ensure_document_tree_artifacts_mirrored,
    write_document_tree_error,
)
from app.services.runtime_store import JsonRuntimeStore

logger = logging.getLogger(__name__)


class ParsePipelineService:
    """Bridge upload, MinerU lifecycle and persisted artifact indexing."""

    def __init__(
        self,
        repository: WorkbenchRepository,
        oss_service: OssStorageService,
        mineru_service: MineruService,
        runtime_store: JsonRuntimeStore,
        settings: AppSettings,
    ) -> None:
        self._repository = repository
        self._oss_service = oss_service
        self._mineru_service = mineru_service
        self._runtime_store = runtime_store
        self._settings = settings

    def upload_and_parse(
        self,
        *,
        customerId: str,
        fileName: str,
        contentType: str,
        data: bytes,
        uploadedByUserId: str,
        uploadedByName: str,
        roleScope: list[str],
        taskName: str | None = None,
    ) -> UploadAndParseResponse:
        file_sha256 = hashlib.sha256(data).hexdigest()
        uploaded = self._oss_service.upload_file(
            customerId=customerId,
            fileName=fileName,
            contentType=contentType,
            data=data,
        )
        register_response = self._repository.register_document(
            customerId,
            RegisterDocumentRequest(
                fileName=fileName,
                fileType=_detect_file_type(fileName),
                objectKey=uploaded.objectKey,
                sourceUrl=uploaded.publicUrl,
                pageCount=0,
                uploadedByUserId=uploadedByUserId,
                uploadedByName=uploadedByName,
                roleScope=roleScope,
                taskName=taskName,
            ),
        )
        self._runtime_store.write_json_log(
            "ocr",
            register_response.createdTask.id,
            "upload.json",
            {
                "taskId": register_response.createdTask.id,
                "customerId": customerId,
                "fileName": fileName,
                "contentType": contentType,
                "sizeBytes": len(data),
                "sha256": file_sha256,
                "objectKey": uploaded.objectKey,
                "sourceUrl": uploaded.publicUrl,
                "uploadedAt": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info(
            "parse upload taskId=%s fileName=%s sizeBytes=%s sha256=%s objectKey=%s",
            register_response.createdTask.id,
            fileName,
            len(data),
            file_sha256,
            uploaded.objectKey,
        )
        task_id = register_response.createdTask.id
        document_id = register_response.document.id
        try:
            parse_status = self.start_parse(task_id)
        except MineruConfigurationError as error:
            logger.info("parse skipped after upload taskId=%s reason=%s", task_id, error)
            parse_status = self._mark_parse_failed(task_id, str(error), mineruState="not_configured")
        except RuntimeError as error:
            logger.info("parse failed after upload taskId=%s reason=%s", task_id, error)
            parse_status = self._mark_parse_failed(task_id, str(error), mineruState="failed")
        return UploadAndParseResponse(
            document=self._repository.get_document(customerId, document_id),
            createdTask=self._repository.get_task_summary(task_id),
            parse=parse_status,
        )

    def start_parse(self, taskId: str) -> ParseTaskStatusResponse:
        task = self._repository.get_task_record(taskId)
        document = self._repository.get_document_record(task.documentId)
        parse_job = self._repository.get_parse_job(taskId)

        if parse_job.mineruTaskId and parse_job.state in {"pending", "running", "completed"}:
            return self.get_parse_status(taskId)

        ensure_configured = getattr(self._mineru_service, "ensure_configured", None)
        try:
            if callable(ensure_configured):
                ensure_configured()
            _ensure_mineru_accessible_source_url(document.sourceUrl, self._settings)
            snapshot = self._mineru_service.submit_url(fileUrl=document.sourceUrl, dataId=taskId)
        except MineruConfigurationError as error:
            logger.info("parse submit skipped taskId=%s reason=%s", taskId, error)
            return self._mark_parse_failed(taskId, str(error), mineruState="not_configured")
        except (MineruProviderError, RuntimeError) as error:
            logger.info("parse submit failed taskId=%s reason=%s", taskId, error)
            return self._mark_parse_failed(taskId, str(error), mineruState="failed")
        self._runtime_store.write_json_log(
            "ocr",
            taskId,
            "mineru-submit.json",
            {
                "taskId": taskId,
                "documentId": document.id,
                "fileName": document.fileName,
                "sourceUrl": document.sourceUrl,
                "mineruTaskId": snapshot.taskId,
                "mineruTraceId": snapshot.traceId,
                "submittedAt": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "url": document.sourceUrl,
                    "model_version": self._settings.mineru_model_version,
                    "language": self._settings.mineru_language,
                    "enable_formula": self._settings.mineru_enable_formula,
                    "enable_table": self._settings.mineru_enable_table,
                    "is_ocr": self._settings.mineru_enable_ocr,
                    "data_id": taskId,
                },
            },
        )
        logger.info(
            "parse submit taskId=%s mineruTaskId=%s traceId=%s sourceUrl=%s",
            taskId,
            snapshot.taskId,
            snapshot.traceId,
            document.sourceUrl,
        )
        parse_job.mineruTaskId = snapshot.taskId
        parse_job.mineruState = snapshot.state
        parse_job.state = _map_mineru_state(snapshot.state)
        parse_job.errorMessage = snapshot.errorMessage
        parse_job.updatedAt = datetime.now(timezone.utc).isoformat()
        self._repository.upsert_parse_job(parse_job)
        return self.get_parse_status(taskId)

    def _mark_parse_failed(self, taskId: str, message: str, *, mineruState: str) -> ParseTaskStatusResponse:
        parse_job = self._repository.get_parse_job(taskId)
        parse_job.state = "failed"
        parse_job.mineruState = mineruState
        parse_job.errorMessage = message
        parse_job.updatedAt = datetime.now(timezone.utc).isoformat()
        self._repository.upsert_parse_job(parse_job)
        return self.get_parse_status(taskId)

    def poll_parse(self, taskId: str) -> ParseTaskStatusResponse:
        parse_job = self._repository.get_parse_job(taskId)
        if not parse_job.mineruTaskId:
            if _map_mineru_state(parse_job.state) in {"completed", "failed", "needs_review"}:
                return self.get_parse_status(taskId)
            raise RuntimeError("当前任务尚未提交到文档解析服务。")

        snapshot = self._mineru_service.get_task(parse_job.mineruTaskId)
        parse_job.mineruState = snapshot.state
        parse_job.state = _map_mineru_state(snapshot.state)
        parse_job.errorMessage = snapshot.errorMessage
        parse_job.extractedPages = snapshot.extractedPages
        parse_job.totalPages = snapshot.totalPages
        parse_job.startTime = snapshot.startTime
        parse_job.fullZipSourceUrl = snapshot.fullZipUrl
        if snapshot.fullZipUrl:
            self._runtime_store.write_json_log(
                "ocr",
                taskId,
                "mineru-latest.json",
                {
                    "taskId": taskId,
                    "mineruTaskId": parse_job.mineruTaskId,
                    "mineruState": snapshot.state,
                    "mineruTraceId": snapshot.traceId,
                    "fullZipUrl": snapshot.fullZipUrl,
                    "errorMessage": snapshot.errorMessage,
                    "extractedPages": snapshot.extractedPages,
                    "totalPages": snapshot.totalPages,
                    "startTime": snapshot.startTime,
                    "polledAt": datetime.now(timezone.utc).isoformat(),
                },
            )
            logger.info(
                "parse poll taskId=%s mineruTaskId=%s state=%s fullZipUrl=%s",
                taskId,
                parse_job.mineruTaskId,
                snapshot.state,
                snapshot.fullZipUrl,
            )

        if snapshot.state == "done" and snapshot.fullZipUrl and not parse_job.markdownPath:
            artifact_paths = self._runtime_store.persist_result_bundle(taskId, self._mineru_service.download_result_bundle(snapshot.fullZipUrl))
            parse_job.fullZipPath = artifact_paths["fullZipPath"]
            parse_job.markdownPath = artifact_paths["markdownPath"]
            parse_job.rawJsonPath = artifact_paths["rawJsonPath"]
            parse_job.layoutPath = artifact_paths["layoutPath"]
            parse_job.blockListPath = artifact_paths["blockListPath"]
            parse_job.modelJsonPath = artifact_paths["modelJsonPath"]
            inferred_total_pages = _infer_page_count_from_content_list(
                self._runtime_store.read_json_artifact(parse_job.rawJsonPath)
            )
            if inferred_total_pages > 0:
                parse_job.totalPages = inferred_total_pages
                parse_job.extractedPages = max(parse_job.extractedPages, inferred_total_pages)

        if parse_job.rawJsonPath and not parse_job.totalPages:
            inferred_total_pages = _infer_page_count_from_content_list(
                self._runtime_store.read_json_artifact(parse_job.rawJsonPath)
            )
            if inferred_total_pages > 0:
                parse_job.totalPages = inferred_total_pages
                parse_job.extractedPages = max(parse_job.extractedPages, inferred_total_pages)

        self._repository.upsert_parse_job(parse_job)
        if parse_job.markdownPath or parse_job.rawJsonPath:
            self._repository.attach_parse_artifacts(taskId, self._build_artifact_urls(taskId, parse_job))
        if _map_mineru_state(parse_job.state) == "completed" and (parse_job.markdownPath or parse_job.rawJsonPath):
            if parse_job.rawJsonPath:
                self._ensure_document_tree_artifacts(taskId, parse_job)
            pages = self._repository.get_task_execution_context(taskId).pages
            if pages:
                self._repository.save_page_recognition_snapshots(taskId, pages)
        return self.get_parse_status(taskId)

    def get_parse_status(self, taskId: str) -> ParseTaskStatusResponse:
        parse_job = self._repository.get_parse_job(taskId)
        return ParseTaskStatusResponse(
            taskId=parse_job.taskId,
            customerId=parse_job.customerId,
            documentId=parse_job.documentId,
            state=_map_mineru_state(parse_job.state),
            mineruState=parse_job.mineruState,
            mineruTaskId=parse_job.mineruTaskId,
            errorMessage=parse_job.errorMessage,
            progress=ParseProgress(
                extractedPages=parse_job.extractedPages,
                totalPages=parse_job.totalPages,
                startTime=parse_job.startTime,
            ),
            artifacts=ParseArtifactUrls(**self._build_artifact_urls(taskId, parse_job)),
        )

    def get_artifact_path(self, taskId: str, artifactPath: str) -> Path:
        return self._runtime_store.resolve_artifact_path(taskId, artifactPath)

    def _ensure_document_tree_artifacts(self, taskId: str, parse_job: ParseJobRecord) -> None:
        tree_path = self._runtime_store.resolve_artifact_path(taskId, f"{DOCUMENT_TREE_CATEGORY}/tree.json")
        if tree_path.exists():
            ensure_document_tree_artifacts_mirrored(
                self._runtime_store,
                taskId,
                oss_service=self._oss_service,
            )
            return
        try:
            artifact_paths = build_document_tree_from_raw_artifact(
                self._runtime_store,
                taskId,
                parse_job.rawJsonPath,
                oss_service=self._oss_service,
            )
            logger.info(
                "document tree built taskId=%s treePath=%s",
                taskId,
                artifact_paths.get("treePath"),
            )
        except Exception as exc:  # pragma: no cover - defensive guard around optional artifact generation
            logger.exception("document tree build failed taskId=%s", taskId)
            write_document_tree_error(self._runtime_store, taskId, exc, oss_service=self._oss_service)

    def _build_artifact_urls(self, taskId: str, job: ParseJobRecord) -> dict[str, str | None]:
        artifact_base_url = f"{self._settings.api_prefix}/tasks/{taskId}/artifacts"
        return {
            "artifactBaseUrl": artifact_base_url,
            "fullZipUrl": _artifact_url(artifact_base_url, "result.zip", job.fullZipPath),
            "markdownUrl": _artifact_url(artifact_base_url, "bundle/full.md", job.markdownPath),
            "rawJsonUrl": _artifact_url(artifact_base_url, _relative_bundle_path(job.rawJsonPath), job.rawJsonPath),
            "layoutUrl": _artifact_url(artifact_base_url, _relative_bundle_path(job.layoutPath), job.layoutPath),
            "blockListUrl": _artifact_url(artifact_base_url, _relative_bundle_path(job.blockListPath), job.blockListPath),
            "modelJsonUrl": _artifact_url(artifact_base_url, _relative_bundle_path(job.modelJsonPath), job.modelJsonPath),
        }


def _detect_file_type(fileName: str) -> str:
    suffix = Path(fileName).suffix.lower()
    if suffix == ".pdf":
        return "PDF"
    guessed, _ = mimetypes.guess_type(fileName)
    if guessed:
        return guessed.upper()
    return suffix.replace(".", "").upper() or "BINARY"


def _ensure_mineru_accessible_source_url(sourceUrl: str, settings: AppSettings) -> None:
    parsed = urlparse(sourceUrl)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            "已配置 MinerU Token，但当前上传文件使用本地对象存储地址，云端文档解析服务无法访问该文件。"
            "请配置 OSS，或设置 BACKEND_PUBLIC_BASE_URL 为公网可访问的后端地址后重新上传/重新识别。"
        )

    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} and not _is_local_mineru_endpoint(settings):
        raise RuntimeError(
            "已配置 MinerU Token，但文件地址指向本机地址，云端文档解析服务无法访问。"
            "请配置 OSS，或使用公网隧道/反向代理并设置 BACKEND_PUBLIC_BASE_URL。"
        )


def _is_local_mineru_endpoint(settings: AppSettings) -> bool:
    parsed = urlparse(settings.mineru_base_url)
    return (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _infer_page_count_from_content_list(payload: Any) -> int:
    if not isinstance(payload, list) or not payload:
        return 0
    if all(isinstance(page, list) for page in payload):
        return len(payload)

    page_indexes: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_page_idx = item.get("page_idx")
        if isinstance(raw_page_idx, int):
            page_indexes.add(raw_page_idx)
            continue
        raw_page_no = item.get("page_no") or item.get("pageNo")
        if isinstance(raw_page_no, int) and raw_page_no > 0:
            page_indexes.add(raw_page_no - 1)
    return max(page_indexes) + 1 if page_indexes else 0


def _map_mineru_state(state: str) -> str:
    mapping = {
        "done": "completed",
        "pending": "pending",
        "running": "running",
        "converting": "running",
        "completed": "completed",
        "failed": "failed",
    }
    return mapping.get(state, "pending")


def _artifact_url(base: str, fallback_relative: str | None, stored_relative: str | None) -> str | None:
    relative = _relative_bundle_path(stored_relative) or fallback_relative
    if not relative:
        return None
    return f"{base}/{relative}"


def _relative_bundle_path(stored_relative: str | None) -> str | None:
    if not stored_relative:
        return None
    parts = Path(stored_relative).parts
    if "bundle" in parts:
        bundle_index = parts.index("bundle")
        return "/".join(parts[bundle_index:])
    return Path(stored_relative).name
