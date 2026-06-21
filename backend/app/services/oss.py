"""OSS upload services for stable-contract and real-upload modes."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from app.core.config import AppSettings
from app.schemas.workbench import OssUploadContractResponse

try:
    import alibabacloud_oss_v2 as oss
except ImportError:  # pragma: no cover - exercised via service selection in runtime/tests
    oss = None


class UploadedObject:
    def __init__(self, *, provider: str, bucket: str, region: str, objectKey: str, publicUrl: str) -> None:
        self.provider = provider
        self.bucket = bucket
        self.region = region
        self.objectKey = objectKey
        self.publicUrl = publicUrl


class OssStorageService(ABC):
    """Describe the upload contract the document APIs rely on."""

    @abstractmethod
    def create_upload_contract(
        self,
        *,
        customerId: str,
        fileName: str,
        contentType: str,
    ) -> OssUploadContractResponse:
        """Reserve an OSS object key and return upload metadata for the caller."""

    @abstractmethod
    def upload_file(
        self,
        *,
        customerId: str,
        fileName: str,
        contentType: str,
        data: bytes,
    ) -> UploadedObject:
        """Upload a local file buffer to storage and return the persisted object metadata."""

    @abstractmethod
    def write_text_object(
        self,
        *,
        objectKey: str,
        content: str,
        contentType: str = "application/json; charset=utf-8",
    ) -> UploadedObject:
        """Write a UTF-8 text object to an exact storage key."""

    @abstractmethod
    def read_text_object(self, *, objectKey: str, maxBytes: int = 2_000_000) -> str:
        """Read a UTF-8 text object from storage for server-side previews."""


class AliyunOssStorageService(OssStorageService):
    """Upload files through the official OSS v2 SDK when credentials are available."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        if oss is None:
            raise RuntimeError("alibabacloud_oss_v2 is not installed")
        if not settings.oss_access_key_id or not settings.oss_access_key_secret:
            raise RuntimeError("OSS credentials are not configured")

        cfg = oss.config.load_default()
        cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
            settings.oss_access_key_id,
            settings.oss_access_key_secret,
        )
        cfg.region = settings.oss_region
        cfg.endpoint = settings.oss_endpoint or _default_oss_endpoint(settings.oss_region)
        self._client = oss.Client(cfg)

    def create_upload_contract(
        self,
        *,
        customerId: str,
        fileName: str,
        contentType: str,
    ) -> OssUploadContractResponse:
        safe_name = _slugify_filename(fileName)
        object_key = f"poc/{customerId}/{datetime.now(timezone.utc):%Y%m%d}/{uuid4().hex}-{safe_name}"
        public_url = f"{self._settings.oss_public_base_url}/{object_key}"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        return OssUploadContractResponse(
            provider="aliyun-oss",
            bucket=self._settings.oss_bucket,
            region=self._settings.oss_region,
            objectKey=object_key,
            uploadUrl=public_url,
            publicUrl=public_url,
            headers={
                "Content-Type": contentType,
                "x-oss-object-acl": "private",
            },
            expiresAt=expires_at.isoformat(),
        )

    def upload_file(
        self,
        *,
        customerId: str,
        fileName: str,
        contentType: str,
        data: bytes,
    ) -> UploadedObject:
        contract = self.create_upload_contract(customerId=customerId, fileName=fileName, contentType=contentType)
        with NamedTemporaryFile(delete=True) as temp_file:
            temp_file.write(data)
            temp_file.flush()
            self._client.put_object_from_file(
                oss.PutObjectRequest(
                    bucket=contract.bucket,
                    key=contract.objectKey,
                ),
                temp_file.name,
            )

        return UploadedObject(
            provider=contract.provider,
            bucket=contract.bucket,
            region=contract.region,
            objectKey=contract.objectKey,
            publicUrl=contract.publicUrl,
        )

    def write_text_object(
        self,
        *,
        objectKey: str,
        content: str,
        contentType: str = "application/json; charset=utf-8",
    ) -> UploadedObject:
        with NamedTemporaryFile(delete=True) as temp_file:
            temp_file.write(content.encode("utf-8"))
            temp_file.flush()
            self._client.put_object_from_file(
                oss.PutObjectRequest(
                    bucket=self._settings.oss_bucket,
                    key=objectKey,
                ),
                temp_file.name,
            )

        public_url = f"{self._settings.oss_public_base_url}/{objectKey}"
        return UploadedObject(
            provider="aliyun-oss",
            bucket=self._settings.oss_bucket,
            region=self._settings.oss_region,
            objectKey=objectKey,
            publicUrl=public_url,
        )

    def read_text_object(self, *, objectKey: str, maxBytes: int = 2_000_000) -> str:
        result = self._client.get_object(
            oss.GetObjectRequest(
                bucket=self._settings.oss_bucket,
                key=objectKey,
                range_header=f"bytes=0-{maxBytes - 1}",
            )
        )
        body = getattr(result, "body", None)
        if body is None:
            return ""
        try:
            data = body.read()
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if isinstance(data, str):
            return data[:maxBytes]
        return bytes(data or b"")[:maxBytes].decode("utf-8", errors="replace")


def _slugify_filename(fileName: str) -> str:
    """Keep object keys browser-safe while preserving the extension."""

    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", fileName.strip())
    return sanitized.strip("-") or f"upload-{uuid4().hex}.bin"


def _default_oss_endpoint(region: str) -> str:
    normalized = region.strip()
    return f"https://oss-{normalized}.aliyuncs.com" if normalized else ""


class LocalObjectStorageService(OssStorageService):
    """Store object assets under the local runtime directory."""

    provider = "local-object-storage"
    bucket = "local-runtime"
    region = "local"

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._root = settings.runtime_data_dir / "objects"
        self._root.mkdir(parents=True, exist_ok=True)

    def create_upload_contract(
        self,
        *,
        customerId: str,
        fileName: str,
        contentType: str,
    ) -> OssUploadContractResponse:
        safe_name = _slugify_filename(fileName)
        object_key = f"poc/{_safe_object_key_part(customerId)}/{datetime.now(timezone.utc):%Y%m%d}/{uuid4().hex}-{safe_name}"
        public_url = self.public_url_for_object_key(object_key)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        return OssUploadContractResponse(
            provider=self.provider,
            bucket=self.bucket,
            region=self.region,
            objectKey=object_key,
            uploadUrl=public_url,
            publicUrl=public_url,
            headers={"Content-Type": contentType},
            expiresAt=expires_at.isoformat(),
        )

    def upload_file(
        self,
        *,
        customerId: str,
        fileName: str,
        contentType: str,
        data: bytes,
    ) -> UploadedObject:
        contract = self.create_upload_contract(customerId=customerId, fileName=fileName, contentType=contentType)
        target = self.resolve_object_path(contract.objectKey)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return UploadedObject(
            provider=contract.provider,
            bucket=contract.bucket,
            region=contract.region,
            objectKey=contract.objectKey,
            publicUrl=contract.publicUrl,
        )

    def write_text_object(
        self,
        *,
        objectKey: str,
        content: str,
        contentType: str = "application/json; charset=utf-8",
    ) -> UploadedObject:
        target = self.resolve_object_path(objectKey)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return UploadedObject(
            provider=self.provider,
            bucket=self.bucket,
            region=self.region,
            objectKey=objectKey,
            publicUrl=self.public_url_for_object_key(objectKey),
        )

    def read_text_object(self, *, objectKey: str, maxBytes: int = 2_000_000) -> str:
        target = self.resolve_object_path(objectKey)
        return target.read_bytes()[:maxBytes].decode("utf-8", errors="replace")

    def resolve_object_path(self, objectKey: str) -> Path:
        target = (self._root / objectKey).resolve()
        target.relative_to(self._root.resolve())
        return target

    def public_url_for_object_key(self, objectKey: str) -> str:
        object_path = f"{self._settings.api_prefix}/objects/{objectKey.lstrip('/')}"
        if self._settings.backend_public_base_url:
            return f"{self._settings.backend_public_base_url}{object_path}"
        return object_path


def build_oss_storage_service(settings: AppSettings) -> OssStorageService:
    if settings.object_storage_provider == "local":
        return LocalObjectStorageService(settings)
    if settings.object_storage_provider == "oss":
        return AliyunOssStorageService(settings)
    if settings.oss_access_key_id and settings.oss_access_key_secret:
        return AliyunOssStorageService(settings)
    return LocalObjectStorageService(settings)


def _safe_object_key_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._=-]+", "-", str(value or "").strip())
    return safe.strip("-") or "object"
