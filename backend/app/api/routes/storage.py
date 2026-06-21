"""Local object storage routes."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.api.dependencies import get_current_user, get_oss_service
from app.services.auth import SessionUser
from app.services.oss import LocalObjectStorageService, OssStorageService

router = APIRouter(tags=["storage"])


def _get_local_storage(storage: OssStorageService) -> LocalObjectStorageService:
    if isinstance(storage, LocalObjectStorageService):
        return storage
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local object storage is not enabled")


@router.get("/objects/{objectKey:path}")
def get_local_object(
    objectKey: str,
    _: SessionUser = Depends(get_current_user),
    storage: OssStorageService = Depends(get_oss_service),
) -> FileResponse:
    local_storage = _get_local_storage(storage)
    try:
        target = local_storage.resolve_object_path(objectKey)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid object key") from error
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Object not found")
    media_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(target, media_type=media_type or "application/octet-stream")


@router.put("/objects/{objectKey:path}")
async def put_local_object(
    objectKey: str,
    request: Request,
    _: SessionUser = Depends(get_current_user),
    storage: OssStorageService = Depends(get_oss_service),
) -> dict[str, str]:
    local_storage = _get_local_storage(storage)
    try:
        target = local_storage.resolve_object_path(objectKey)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid object key") from error
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await request.body())
    return {
        "provider": local_storage.provider,
        "objectKey": objectKey,
        "publicUrl": local_storage.public_url_for_object_key(objectKey),
    }
