"""Persistence helpers for document-tree runtime artifacts."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.workbench import WorkbenchDocumentTree
from app.services.document_tree_builder import (
    DocumentTreeBuilder,
    DocumentTreeBuildResult,
    build_tree_text,
    extract_modules,
    normalize_document_tree_hierarchy,
)
from app.services.runtime_store import JsonRuntimeStore


DOCUMENT_TREE_CATEGORY = "document_tree"


def build_document_tree_from_raw_artifact(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    raw_json_path: str,
) -> dict[str, str]:
    content_payload = runtime_store.read_json_artifact(raw_json_path)
    result = DocumentTreeBuilder().build(task_id=task_id, content_payload=content_payload)
    return write_document_tree_artifacts(runtime_store, task_id, result)


def write_document_tree_artifacts(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    result: DocumentTreeBuildResult,
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
    paths["statusPath"] = runtime_store.write_json_artifact(
        task_id,
        DOCUMENT_TREE_CATEGORY,
        "status.json",
        {
            "taskId": task_id,
            "status": "completed",
            "artifactType": DOCUMENT_TREE_CATEGORY,
            "counts": {
                "modules": len(result.modules),
                "dispatchSteps": len(result.dispatchPlan.get("steps") or []),
            },
            "paths": dict(paths),
        },
    )
    return paths


def write_document_tree_error(
    runtime_store: JsonRuntimeStore,
    task_id: str,
    error: Exception,
) -> str:
    return runtime_store.write_json_artifact(
        task_id,
        DOCUMENT_TREE_CATEGORY,
        "status.json",
        {
            "taskId": task_id,
            "status": "failed",
            "artifactType": DOCUMENT_TREE_CATEGORY,
            "errorType": error.__class__.__name__,
            "errorMessage": str(error),
        },
    )


def load_document_tree(runtime_store: JsonRuntimeStore, task_id: str, doc_id: str | None = None) -> WorkbenchDocumentTree | None:
    tree_path = runtime_store.resolve_artifact_path(task_id, f"{DOCUMENT_TREE_CATEGORY}/tree.json")
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
