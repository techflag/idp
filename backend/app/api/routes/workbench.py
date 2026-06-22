"""Workbench endpoints for task workspace data."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import ensure_customer_access, get_current_user, get_oss_service, get_repository, get_runtime_store
from app.api.route_metrics import log_response_metric, metric_start
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    ApplicationWorkshopStepDraft,
    ApplicationWorkshopStepDraftUpsertRequest,
    WorkbenchDataset,
    WorkbenchDocumentTree,
    WorkbenchTaskDetail,
)
from app.services.auth import SessionUser
from app.services.document_tree_artifacts import (
    build_document_tree_from_raw_artifact,
    ensure_document_tree_artifacts_mirrored,
    load_document_tree,
    write_document_tree_error,
)
from app.services.oss import OssStorageService
from app.services.runtime_store import JsonRuntimeStore

router = APIRouter(prefix="/workbench", tags=["workbench"])
logger = logging.getLogger(__name__)


@router.get("/dataset", response_model=WorkbenchDataset)
def get_workbench_dataset(
    include_details: bool = Query(False, alias="includeDetails"),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> WorkbenchDataset:
    dataset = repository.get_dataset(include_details=include_details)
    if current_user.role == "admin":
        return dataset

    visible_customer_ids = set(current_user.customerIds)
    visible_customers = [customer for customer in dataset.customers if customer.id in visible_customer_ids]

    visible_tasks = [
        task
        for task in dataset.tasks
        if task.customerId in visible_customer_ids
    ]
    visible_task_ids = {task.id for task in visible_tasks}
    visible_details = {
        task_id: detail
        for task_id, detail in dataset.taskDetails.items()
        if task_id in visible_task_ids
    }
    return WorkbenchDataset(
        customers=visible_customers,
        tasks=visible_tasks,
        taskDetails=visible_details,
    )


@router.get("/tasks/{taskId}", response_model=WorkbenchTaskDetail)
def get_workbench_task_detail(
    taskId: str,
    include_document_tree: bool = Query(True, alias="includeDocumentTree"),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    runtime_store: JsonRuntimeStore = Depends(get_runtime_store),
    oss_service: OssStorageService = Depends(get_oss_service),
) -> WorkbenchTaskDetail:
    started_at = metric_start()
    task = repository.get_task_record(taskId)
    ensure_customer_access(task.customerId, current_user)
    detail = repository.get_task_detail(taskId, lightPromptRuns=not include_document_tree)
    if include_document_tree:
        detail.documentTree = _load_or_build_document_tree(
            repository,
            runtime_store,
            taskId,
            detail.document.id,
            oss_service,
        )
    log_response_metric(
        "workbench_task_detail",
        started_at=started_at,
        payload=detail,
        taskId=taskId,
        status=detail.task.status,
        pageCount=len(detail.pages),
        pageResultCount=len(detail.pageResults),
        includeDocumentTree=include_document_tree,
        hasDocumentTree=detail.documentTree is not None,
    )
    return detail


@router.get("/tasks/{taskId}/document-tree", response_model=WorkbenchDocumentTree | None)
def get_workbench_task_document_tree(
    taskId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    runtime_store: JsonRuntimeStore = Depends(get_runtime_store),
    oss_service: OssStorageService = Depends(get_oss_service),
) -> WorkbenchDocumentTree | None:
    started_at = metric_start()
    task = repository.get_task_record(taskId)
    ensure_customer_access(task.customerId, current_user)
    tree = _load_or_build_document_tree(repository, runtime_store, taskId, task.documentId, oss_service)
    log_response_metric(
        "workbench_document_tree",
        started_at=started_at,
        payload=tree,
        taskId=taskId,
        status=task.status,
        hasDocumentTree=tree is not None,
    )
    return tree


@router.get("/tasks/{taskId}/application-step-drafts", response_model=list[ApplicationWorkshopStepDraft])
def list_application_step_drafts(
    taskId: str,
    light: bool = Query(False),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> list[ApplicationWorkshopStepDraft]:
    task = repository.get_task_record(taskId)
    ensure_customer_access(task.customerId, current_user)
    return repository.list_application_workshop_step_drafts(taskId, light=light)


@router.get("/tasks/{taskId}/application-step-drafts/{draftId}", response_model=ApplicationWorkshopStepDraft)
def get_application_step_draft(
    taskId: str,
    draftId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> ApplicationWorkshopStepDraft:
    task = repository.get_task_record(taskId)
    ensure_customer_access(task.customerId, current_user)
    return repository.get_application_workshop_step_draft(taskId, draftId)


@router.put("/tasks/{taskId}/application-step-drafts/{draftId}", response_model=ApplicationWorkshopStepDraft)
def save_application_step_draft(
    taskId: str,
    draftId: str,
    payload: ApplicationWorkshopStepDraftUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> ApplicationWorkshopStepDraft:
    task = repository.get_task_record(taskId)
    ensure_customer_access(task.customerId, current_user)
    normalized = payload.model_copy(update={"id": draftId})
    return repository.save_application_workshop_step_draft(taskId, normalized, userId=current_user.username)


@router.delete("/tasks/{taskId}/application-step-drafts/{draftId}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application_step_draft(
    taskId: str,
    draftId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> Response:
    task = repository.get_task_record(taskId)
    ensure_customer_access(task.customerId, current_user)
    repository.delete_application_workshop_step_draft(taskId, draftId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _load_or_build_document_tree(
    repository: WorkbenchRepository,
    runtime_store: JsonRuntimeStore,
    task_id: str,
    document_id: str,
    oss_service: OssStorageService,
) -> WorkbenchDocumentTree | None:
    existing = load_document_tree(runtime_store, task_id, document_id, oss_service=oss_service)
    if existing is not None:
        ensure_document_tree_artifacts_mirrored(runtime_store, task_id, oss_service=oss_service)
        return existing

    raw_json_path = _resolve_raw_json_path(repository, runtime_store, task_id)
    if not raw_json_path:
        return None

    try:
        artifact_paths = build_document_tree_from_raw_artifact(
            runtime_store,
            task_id,
            raw_json_path,
            oss_service=oss_service,
        )
        logger.info("document tree built on workbench load taskId=%s treePath=%s", task_id, artifact_paths.get("treePath"))
    except Exception as exc:  # pragma: no cover - defensive guard for optional workbench enrichment
        logger.exception("document tree lazy build failed taskId=%s", task_id)
        write_document_tree_error(runtime_store, task_id, exc, oss_service=oss_service)
        return None
    return load_document_tree(runtime_store, task_id, document_id, oss_service=oss_service)


def _resolve_raw_json_path(
    repository: WorkbenchRepository,
    runtime_store: JsonRuntimeStore,
    task_id: str,
) -> str | None:
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
