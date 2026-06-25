# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Persistence helpers for document-tree runtime artifacts."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.schemas.workbench import WorkbenchDocumentTree
from app.services.document_tree_builder import (
    DocumentTreeBuilder,
    DocumentTreeBuildResult,
    build_tree_text,
    extract_modules,
    normalize_document_tree_hierarchy,
)
from app.services.oss import LocalObjectStorageService, OssStorageService
from app.services.result_artifacts import build_task_object_key
from app.services.runtime_store import JsonRuntimeStore


DOCUMENT_TREE_CATEGORY = "document_tree"
_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"
_REMOTE_DOCUMENT_TREE_MAX_BYTES = 50_000_000
_REMOTE_DOCUMENT_TREE_FILES = {
    "tree": "tree.json",
    "treeText": "tree.txt",
    "modules": "modules.json",
    "dispatchPlan": "dispatch_plan.json",
    "status": "status.json",
}

logger = logging.getLogger(__name__)


def build_document_tree_from_raw_artifact(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    raw_json_path: str,
    *,
    oss_service: OssStorageService | None = None,
) -> dict[str, str]:
    content_payload = runtime_store.read_json_artifact(raw_json_path)
    result = DocumentTreeBuilder().build(task_id=task_id, content_payload=content_payload)
    return write_document_tree_artifacts(runtime_store, task_id, result, oss_service=oss_service)


def ensure_document_tree_for_task(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    doc_id: str | None = None,
    *,
    repository: Any | None = None,
    raw_json_path: str | None = None,
    oss_service: OssStorageService | None = None,
) -> WorkbenchDocumentTree | None:
    """Load or build the neutral document tree for a parsed task.

    This keeps upload parsing, workbench task detail, and application runtime on
    the same artifact lifecycle. It does not infer business intent; it only
    materializes the tree from existing OCR raw content when available.
    """

    existing = load_document_tree(runtime_store, task_id, doc_id, oss_service=oss_service)
    if existing is not None:
        ensure_document_tree_artifacts_mirrored(runtime_store, task_id, oss_service=oss_service)
        return existing

    resolved_raw_json_path = raw_json_path or resolve_document_tree_raw_json_path(
        runtime_store,
        task_id,
        repository=repository,
    )
    if not resolved_raw_json_path:
        return None

    try:
        artifact_paths = build_document_tree_from_raw_artifact(
            runtime_store,
            task_id,
            resolved_raw_json_path,
            oss_service=oss_service,
        )
        logger.info(
            "document tree ensured taskId=%s treePath=%s",
            task_id,
            artifact_paths.get("treePath"),
        )
    except Exception as exc:  # pragma: no cover - defensive guard around optional artifact generation
        logger.exception("document tree ensure failed taskId=%s", task_id)
        write_document_tree_error(runtime_store, task_id, exc, oss_service=oss_service)
        return None
    return load_document_tree(runtime_store, task_id, doc_id, oss_service=oss_service)


def resolve_document_tree_raw_json_path(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    *,
    repository: Any | None = None,
) -> str | None:
    if repository is not None:
        try:
            parse_job = repository.get_parse_job(task_id)
        except Exception:
            parse_job = None
        raw_json_path = getattr(parse_job, "rawJsonPath", None)
        if raw_json_path:
            return raw_json_path

    bundle_dir = runtime_store.resolve_artifact_path(task_id, "bundle")
    if not bundle_dir.exists():
        return None
    candidates = sorted(bundle_dir.glob("*content_list_v2.json")) or sorted(bundle_dir.glob("content_list_v2.json"))
    if not candidates:
        return None
    task_root = runtime_store.resolve_artifact_path(task_id, ".")
    relative_to_task = candidates[0].resolve().relative_to(task_root)
    return str(Path("artifacts") / task_id / relative_to_task)


def write_document_tree_artifacts(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    result: DocumentTreeBuildResult,
    *,
    oss_service: OssStorageService | None = None,
) -> dict[str, str]:
    paths = {
        "treePath": runtime_store.write_json_artifact(task_id, DOCUMENT_TREE_CATEGORY, "tree.json", result.tree),
        "treeTextPath": runtime_store.write_text_artifact(task_id, DOCUMENT_TREE_CATEGORY, "tree.txt", result.treeText),
        "modulesPath": runtime_store.write_json_artifact(
            task_id,
            DOCUMENT_TREE_CATEGORY,
            "modules.json",
            {
                "taskId": task_id,
                "modules": result.modules,
            },
        ),
        "dispatchPlanPath": runtime_store.write_json_artifact(
            task_id,
            DOCUMENT_TREE_CATEGORY,
            "dispatch_plan.json",
            result.dispatchPlan,
        ),
    }
    status_payload: dict[str, Any] = {
        "taskId": task_id,
        "status": "completed",
        "artifactType": DOCUMENT_TREE_CATEGORY,
        "counts": {
            "modules": len(result.modules),
            "dispatchSteps": len(result.dispatchPlan.get("steps") or []),
        },
        "paths": dict(paths),
    }
    paths["statusPath"] = runtime_store.write_json_artifact(
        task_id,
        DOCUMENT_TREE_CATEGORY,
        "status.json",
        status_payload,
    )
    status_payload["paths"] = dict(paths)
    remote_metadata = _mirror_document_tree_artifacts_to_oss(
        task_id=task_id,
        tree=result.tree,
        tree_text=result.treeText,
        modules_payload={
            "taskId": task_id,
            "modules": result.modules,
        },
        dispatch_plan=result.dispatchPlan,
        status_payload=status_payload,
        oss_service=oss_service,
    )
    if remote_metadata:
        status_payload.update(remote_metadata)
        paths["statusPath"] = runtime_store.write_json_artifact(
            task_id,
            DOCUMENT_TREE_CATEGORY,
            "status.json",
            status_payload,
        )
        _write_remote_status(task_id, status_payload, oss_service)
    return paths


def write_document_tree_error(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    error: Exception,
    *,
    oss_service: OssStorageService | None = None,
) -> str:
    payload = {
        "taskId": task_id,
        "status": "failed",
        "artifactType": DOCUMENT_TREE_CATEGORY,
        "errorType": error.__class__.__name__,
        "errorMessage": str(error),
    }
    status_path = runtime_store.write_json_artifact(task_id, DOCUMENT_TREE_CATEGORY, "status.json", payload)
    _write_remote_status(task_id, payload, oss_service)
    return status_path


def ensure_document_tree_artifacts_mirrored(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    *,
    oss_service: OssStorageService | None = None,
) -> bool:
    """Mirror existing local document-tree artifacts to configured remote storage."""

    return _ensure_local_document_tree_mirrored_to_oss(runtime_store, task_id, oss_service)


def load_document_tree(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    doc_id: str | None = None,
    *,
    oss_service: OssStorageService | None = None,
) -> WorkbenchDocumentTree | None:
    tree_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/tree.json")
    if not tree_path.exists():
        _hydrate_document_tree_artifacts_from_oss(runtime_store, task_id, oss_service)
    if not tree_path.exists():
        return None

    tree = normalize_document_tree_hierarchy(_read_json_object(tree_path))
    modules_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/modules.json")
    tree_text_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/tree.txt")
    modules_payload = _read_json_object(modules_path) if modules_path.exists() else {}
    stored_modules = modules_payload.get("modules") if isinstance(modules_payload, dict) else []
    modules = extract_modules(tree) if isinstance(tree, dict) else stored_modules
    if isinstance(tree, dict):
        tree_text = build_tree_text(tree)
    else:
        tree_text = tree_text_path.read_text(encoding="utf-8") if tree_text_path.exists() else ""

    return WorkbenchDocumentTree(
        source=DOCUMENT_TREE_CATEGORY,
        docId=doc_id or task_id,
        tree=tree,
        modules=modules if isinstance(modules, list) else [],
        treeText=tree_text,
    )


def _read_json_object(path: Any) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _mirror_document_tree_artifacts_to_oss(
    *,
    task_id: str,
    tree: dict[str, Any],
    tree_text: str,
    modules_payload: dict[str, Any],
    dispatch_plan: dict[str, Any],
    status_payload: dict[str, Any],
    oss_service: OssStorageService | None,
) -> dict[str, Any] | None:
    if not _should_use_remote_document_tree_artifacts(oss_service):
        return None
    assert oss_service is not None
    object_keys = _remote_object_keys(task_id)
    try:
        uploads = {
            "tree": oss_service.write_text_object(
                objectKey=object_keys["tree"],
                content=_dump_json(tree),
                contentType=_JSON_CONTENT_TYPE,
            ),
            "treeText": oss_service.write_text_object(
                objectKey=object_keys["treeText"],
                content=tree_text,
                contentType=_TEXT_CONTENT_TYPE,
            ),
            "modules": oss_service.write_text_object(
                objectKey=object_keys["modules"],
                content=_dump_json(modules_payload),
                contentType=_JSON_CONTENT_TYPE,
            ),
            "dispatchPlan": oss_service.write_text_object(
                objectKey=object_keys["dispatchPlan"],
                content=_dump_json(dispatch_plan),
                contentType=_JSON_CONTENT_TYPE,
            ),
            "status": oss_service.write_text_object(
                objectKey=object_keys["status"],
                content=_dump_json({**status_payload, "objectKeys": object_keys}),
                contentType=_JSON_CONTENT_TYPE,
            ),
        }
    except Exception:
        logger.exception("document tree OSS mirror failed taskId=%s", task_id)
        return None
    first_upload = uploads["tree"]
    return {
        "objectKeys": object_keys,
        "publicUrls": {key: upload.publicUrl for key, upload in uploads.items()},
        "storage": {
            "provider": first_upload.provider,
            "bucket": first_upload.bucket,
            "region": first_upload.region,
        },
    }


def _write_remote_status(
    task_id: str,
    payload: dict[str, Any],
    oss_service: OssStorageService | None,
) -> None:
    if not _should_use_remote_document_tree_artifacts(oss_service):
        return
    assert oss_service is not None
    try:
        oss_service.write_text_object(
            objectKey=_remote_object_keys(task_id)["status"],
            content=_dump_json(payload),
            contentType=_JSON_CONTENT_TYPE,
        )
    except Exception:
        logger.exception("document tree OSS status write failed taskId=%s", task_id)


def _hydrate_document_tree_artifacts_from_oss(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    oss_service: OssStorageService | None,
) -> bool:
    if not _should_use_remote_document_tree_artifacts(oss_service):
        return False
    assert oss_service is not None
    object_keys = _remote_object_keys(task_id)
    try:
        tree_text = oss_service.read_text_object(
            objectKey=object_keys["tree"],
            maxBytes=_REMOTE_DOCUMENT_TREE_MAX_BYTES,
        )
        tree_payload = json.loads(tree_text)
    except Exception:
        return False
    if not isinstance(tree_payload, dict):
        return False
    runtime_store.write_json_artifact(task_id, DOCUMENT_TREE_CATEGORY, "tree.json", tree_payload)

    optional_json_files = {
        "modules": "modules.json",
        "dispatchPlan": "dispatch_plan.json",
        "status": "status.json",
    }
    for key, file_name in optional_json_files.items():
        try:
            text = oss_service.read_text_object(
                objectKey=object_keys[key],
                maxBytes=_REMOTE_DOCUMENT_TREE_MAX_BYTES,
            )
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            runtime_store.write_json_artifact(task_id, DOCUMENT_TREE_CATEGORY, file_name, payload)

    try:
        text_payload = oss_service.read_text_object(
            objectKey=object_keys["treeText"],
            maxBytes=_REMOTE_DOCUMENT_TREE_MAX_BYTES,
        )
    except Exception:
        text_payload = ""
    if text_payload:
        runtime_store.write_text_artifact(task_id, DOCUMENT_TREE_CATEGORY, "tree.txt", text_payload)
    return True


def _ensure_local_document_tree_mirrored_to_oss(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    oss_service: OssStorageService | None,
) -> bool:
    if not _should_use_remote_document_tree_artifacts(oss_service):
        return False
    status_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/status.json")
    if status_path.exists():
        status_payload = _read_json_object(status_path)
        if isinstance(status_payload.get("objectKeys"), dict):
            return True
    else:
        status_payload = {}

    tree_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/tree.json")
    if not tree_path.exists():
        return False
    modules_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/modules.json")
    dispatch_plan_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/dispatch_plan.json")
    tree_text_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/tree.txt")

    tree = _read_json_object(tree_path)
    normalized_tree = normalize_document_tree_hierarchy(tree)
    modules_payload = _read_json_object(modules_path) if modules_path.exists() else {
        "taskId": task_id,
        "modules": extract_modules(normalized_tree),
    }
    modules = modules_payload.get("modules") if isinstance(modules_payload, dict) else []
    dispatch_plan = _read_json_object(dispatch_plan_path) if dispatch_plan_path.exists() else {"steps": []}
    tree_text = tree_text_path.read_text(encoding="utf-8") if tree_text_path.exists() else build_tree_text(normalized_tree)
    paths = status_payload.get("paths") if isinstance(status_payload.get("paths"), dict) else {
        "treePath": f"artifacts/{task_id}/{DOCUMENT_TREE_CATEGORY}/tree.json",
        "treeTextPath": f"artifacts/{task_id}/{DOCUMENT_TREE_CATEGORY}/tree.txt",
        "modulesPath": f"artifacts/{task_id}/{DOCUMENT_TREE_CATEGORY}/modules.json",
        "dispatchPlanPath": f"artifacts/{task_id}/{DOCUMENT_TREE_CATEGORY}/dispatch_plan.json",
        "statusPath": f"artifacts/{task_id}/{DOCUMENT_TREE_CATEGORY}/status.json",
    }
    next_status_payload = {
        **status_payload,
        "taskId": task_id,
        "status": "completed",
        "artifactType": DOCUMENT_TREE_CATEGORY,
        "counts": {
            "modules": len(modules) if isinstance(modules, list) else 0,
            "dispatchSteps": len(dispatch_plan.get("steps") or []),
        },
        "paths": paths,
    }
    remote_metadata = _mirror_document_tree_artifacts_to_oss(
        task_id=task_id,
        tree=tree,
        tree_text=tree_text,
        modules_payload=modules_payload,
        dispatch_plan=dispatch_plan,
        status_payload=next_status_payload,
        oss_service=oss_service,
    )
    if not remote_metadata:
        return False
    next_status_payload.update(remote_metadata)
    runtime_store.write_json_artifact(task_id, DOCUMENT_TREE_CATEGORY, "status.json", next_status_payload)
    _write_remote_status(task_id, next_status_payload, oss_service)
    logger.info("document tree mirrored to OSS taskId=%s", task_id)
    return True


def _remote_object_keys(task_id: str) -> dict[str, str]:
    return {
        key: build_task_object_key(task_id, DOCUMENT_TREE_CATEGORY, file_name)
        for key, file_name in _REMOTE_DOCUMENT_TREE_FILES.items()
    }


def _should_use_remote_document_tree_artifacts(oss_service: OssStorageService | None) -> bool:
    if oss_service is None:
        return False
    return not isinstance(oss_service, LocalObjectStorageService)


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
