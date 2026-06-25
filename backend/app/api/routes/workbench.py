# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Workbench endpoints for task workspace data."""

from __future__ import annotations

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
from app.services.document_tree_artifacts import ensure_document_tree_for_task
from app.services.oss import OssStorageService
from app.services.runtime_store import JsonRuntimeStore

router = APIRouter(prefix="/workbench", tags=["workbench"])


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
        detail.documentTree = ensure_document_tree_for_task(
            runtime_store,
            taskId,
            detail.document.id,
            repository=repository,
            oss_service=oss_service,
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
    tree = ensure_document_tree_for_task(
        runtime_store,
        taskId,
        task.documentId,
        repository=repository,
        oss_service=oss_service,
    )
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
