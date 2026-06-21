"""Task-oriented read APIs for admin, user and workbench consumers."""

from __future__ import annotations

import mimetypes
from typing import Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.api.dependencies import (
    ensure_customer_access,
    get_admin_user,
    get_current_user,
    get_parse_pipeline_service,
    get_prompt_pipeline_service,
    get_repository,
)
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    AdminOverviewResponse,
    ExtractionSkillRunRequest,
    FailedPromptRerunRequest,
    ObjectOperationExecutionResponse,
    ObjectOperationResult,
    ObjectOperationRunRequest,
    PaginatedResponse,
    PageResultDetail,
    PageOperationTargetsResponse,
    ParseTaskStatusResponse,
    PostProcessRunRequest,
    PromptExecutionRequest,
    PromptExecutionResponse,
    SchemaRunRequest,
    SkillRunRequest,
    SummaryExecutionRequest,
    TaskSummary,
)
from app.services.parse_pipeline import ParsePipelineService
from app.services.prompt_pipeline import PromptPipelineService
from app.services.workbench_builder import build_llm_trace_summary, build_object_operation_result
from app.services.auth import SessionUser

router = APIRouter(tags=["tasks"])
T = TypeVar("T")


def _ensure_task_access(repository: WorkbenchRepository, taskId: str, current_user: SessionUser) -> None:
    task = repository.get_task_record(taskId)
    ensure_customer_access(task.customerId, current_user)


def _paginate_items(items: list[T], page: int, page_size: int) -> PaginatedResponse[T]:
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse[T](
        items=items[start:end],
        total=total,
        page=page,
        pageSize=page_size,
    )


@router.get("/overview/admin", response_model=AdminOverviewResponse)
def get_admin_overview(
    _: SessionUser = Depends(get_admin_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> AdminOverviewResponse:
    return repository.get_admin_overview()


@router.get("/admin/tasks", response_model=PaginatedResponse[TaskSummary])
def list_admin_tasks(
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    customerId: Optional[str] = Query(None),
    _: SessionUser = Depends(get_admin_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PaginatedResponse[TaskSummary]:
    response = repository.get_admin_overview()
    tasks = response.tasks
    if customerId:
        tasks = [task for task in tasks if task.customerId == customerId]
    return _paginate_items(tasks, page, pageSize)


@router.get("/me/tasks", response_model=PaginatedResponse[TaskSummary])
def list_my_tasks(
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PaginatedResponse[TaskSummary]:
    response = repository.list_user_tasks(current_user.username)
    if current_user.role == "admin":
        return _paginate_items(response.tasks, page, pageSize)
    visible_tasks = [task for task in response.tasks if task.customerId in current_user.customerIds]
    return _paginate_items(visible_tasks, page, pageSize)


@router.get("/users/{userId}/tasks", response_model=PaginatedResponse[TaskSummary])
def list_user_tasks(
    userId: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PaginatedResponse[TaskSummary]:
    requested_user = userId
    if current_user.role != "admin":
        if userId == current_user.id:
            # Frontend/client may pass user.id while task ownership is stored by username.
            requested_user = current_user.username
        elif userId != current_user.username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权查看其他用户任务")
    response = repository.list_user_tasks(requested_user)
    if current_user.role == "admin":
        return _paginate_items(response.tasks, page, pageSize)
    visible_tasks = [task for task in response.tasks if task.customerId in current_user.customerIds]
    return _paginate_items(visible_tasks, page, pageSize)


@router.get("/tasks/{taskId}", response_model=TaskSummary)
def get_task_summary(
    taskId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> TaskSummary:
    _ensure_task_access(repository, taskId, current_user)
    return repository.get_task_summary(taskId)


@router.post("/tasks/{taskId}/parse", response_model=ParseTaskStatusResponse)
def start_task_parse(
    taskId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    pipeline_service: ParsePipelineService = Depends(get_parse_pipeline_service),
) -> ParseTaskStatusResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return pipeline_service.start_parse(taskId)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


@router.post("/tasks/{taskId}/parse/poll", response_model=ParseTaskStatusResponse)
def poll_task_parse(
    taskId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    pipeline_service: ParsePipelineService = Depends(get_parse_pipeline_service),
) -> ParseTaskStatusResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return pipeline_service.poll_parse(taskId)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@router.get("/tasks/{taskId}/parse", response_model=ParseTaskStatusResponse)
def get_task_parse_status(
    taskId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    pipeline_service: ParsePipelineService = Depends(get_parse_pipeline_service),
) -> ParseTaskStatusResponse:
    _ensure_task_access(repository, taskId, current_user)
    return pipeline_service.get_parse_status(taskId)


@router.get("/tasks/{taskId}/artifacts/{artifactPath:path}")
def get_task_artifact(
    taskId: str,
    artifactPath: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    pipeline_service: ParsePipelineService = Depends(get_parse_pipeline_service),
) -> FileResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        target = pipeline_service.get_artifact_path(taskId, artifactPath)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    media_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(target, media_type=media_type or "application/octet-stream")


@router.post("/tasks/{taskId}/prompt-runs", response_model=PromptExecutionResponse)
def execute_task_prompt_runs(
    taskId: str,
    payload: PromptExecutionRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> PromptExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.execute_prompt_runs(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/tasks/{taskId}/extraction-skill-runs", response_model=PromptExecutionResponse)
def execute_task_extraction_skill_run(
    taskId: str,
    payload: ExtractionSkillRunRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> PromptExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.execute_extraction_skill_run(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/tasks/{taskId}/prompt-runs/{runId}", response_model=PageResultDetail)
def get_task_prompt_run_detail(
    taskId: str,
    runId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PageResultDetail:
    _ensure_task_access(repository, taskId, current_user)
    detail = repository.get_task_page_result_detail(taskId, runId)
    detail.llmTraceSummary = build_llm_trace_summary(repository.list_llm_call_traces(taskId, runId=runId))
    return detail


@router.post("/tasks/{taskId}/post-process-runs", response_model=PromptExecutionResponse)
def execute_task_post_process_runs(
    taskId: str,
    payload: PostProcessRunRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> PromptExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.execute_post_process_runs(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/tasks/{taskId}/post-process-runs/{runId}", response_model=PageResultDetail)
def get_task_post_process_run_detail(
    taskId: str,
    runId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PageResultDetail:
    _ensure_task_access(repository, taskId, current_user)
    detail = repository.get_task_page_result_detail(taskId, runId)
    detail.llmTraceSummary = build_llm_trace_summary(repository.list_llm_call_traces(taskId, runId=runId))
    return detail


@router.get("/tasks/{taskId}/pages/{pageNo}/operation-targets", response_model=PageOperationTargetsResponse)
def get_task_page_operation_targets(
    taskId: str,
    pageNo: int,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PageOperationTargetsResponse:
    _ensure_task_access(repository, taskId, current_user)
    return repository.get_task_page_operation_targets(taskId, pageNo)


@router.post("/tasks/{taskId}/object-operation-runs", response_model=ObjectOperationExecutionResponse)
def execute_task_object_operation_run(
    taskId: str,
    payload: ObjectOperationRunRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> ObjectOperationExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.execute_object_operation_run(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/tasks/{taskId}/skill-runs", response_model=ObjectOperationExecutionResponse)
def execute_task_skill_run(
    taskId: str,
    payload: SkillRunRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> ObjectOperationExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.execute_skill_run(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/tasks/{taskId}/object-operation-runs/{runId}", response_model=ObjectOperationResult)
def get_task_object_operation_run_detail(
    taskId: str,
    runId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> ObjectOperationResult:
    _ensure_task_access(repository, taskId, current_user)
    run = repository.get_prompt_run(runId)
    if run.taskId != taskId:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Object operation run not found")
    built = build_object_operation_result(run)
    if not built:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Object operation result not found")
    built.llmTraceSummary = build_llm_trace_summary(repository.list_llm_call_traces(taskId, runId=runId))
    return built


@router.post("/tasks/{taskId}/schema-runs", response_model=PromptExecutionResponse)
def execute_task_schema_runs(
    taskId: str,
    payload: SchemaRunRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> PromptExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.execute_schema_runs(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/tasks/{taskId}/schema-runs/{runId}", response_model=PageResultDetail)
def get_task_schema_run_detail(
    taskId: str,
    runId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PageResultDetail:
    _ensure_task_access(repository, taskId, current_user)
    detail = repository.get_task_page_result_detail(taskId, runId)
    detail.llmTraceSummary = build_llm_trace_summary(repository.list_llm_call_traces(taskId, runId=runId))
    return detail


@router.post("/tasks/{taskId}/prompt-runs/rerun-failed", response_model=PromptExecutionResponse)
def rerun_failed_task_prompt_runs(
    taskId: str,
    payload: FailedPromptRerunRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> PromptExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.rerun_failed_pages(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/tasks/{taskId}/summary-runs", response_model=PromptExecutionResponse)
def execute_task_summary_run(
    taskId: str,
    payload: SummaryExecutionRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    prompt_pipeline_service: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> PromptExecutionResponse:
    _ensure_task_access(repository, taskId, current_user)
    try:
        return prompt_pipeline_service.run_summary(taskId, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
