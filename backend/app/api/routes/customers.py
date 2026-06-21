"""Customer, document and upload-contract endpoints."""

from __future__ import annotations

from typing import Optional, TypeVar, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from app.api.dependencies import (
    ensure_customer_access,
    get_admin_user,
    get_auth_service,
    get_current_user,
    get_oss_service,
    get_parse_pipeline_service,
    get_repository,
    to_auth_user_response,
)
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    CreateCustomerRequest,
    CreateCustomerProvisionRequest,
    CreateCustomerProvisionResponse,
    CustomerSummary,
    CustomerWorkspaceResponse,
    DocumentDetail,
    DocumentSummary,
    PaginatedResponse,
    OssUploadContractRequest,
    OssUploadContractResponse,
    RegisterDocumentRequest,
    RegisterDocumentResponse,
    TaskSummary,
    UploadAndParseResponse,
)
from app.services.oss import OssStorageService
from app.services.parse_pipeline import ParsePipelineService
from app.services.auth import SessionUser
from app.services.db_auth import DbAuthService

router = APIRouter(prefix="/customers", tags=["customers"])
T = TypeVar("T")


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


@router.get("", response_model=None)
def list_customers(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> Union[PaginatedResponse[CustomerSummary], list[CustomerSummary]]:
    customers = repository.list_customers()
    if current_user.role == "admin":
        visible_customers = customers
    else:
        visible_customer_ids = set(current_user.customerIds)
        visible_customers = [customer for customer in customers if customer.id in visible_customer_ids]
    if "page" not in request.query_params and "pageSize" not in request.query_params:
        return visible_customers
    return _paginate_items(visible_customers, page, pageSize)


@router.post("", response_model=CustomerSummary, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CreateCustomerRequest,
    _: SessionUser = Depends(get_admin_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> CustomerSummary:
    return repository.create_customer(payload)


@router.post("/provision", response_model=CreateCustomerProvisionResponse, status_code=status.HTTP_201_CREATED)
def provision_customer(
    payload: CreateCustomerProvisionRequest,
    _: SessionUser = Depends(get_admin_user),
    repository: WorkbenchRepository = Depends(get_repository),
    auth_service: DbAuthService = Depends(get_auth_service),
) -> CreateCustomerProvisionResponse:
    if not auth_service.is_username_available(payload.account.username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="登录账号已存在，请更换用户名")

    try:
        customer = repository.create_customer(payload.customer)
        account = auth_service.create_customer_user(
            username=payload.account.username,
            password=payload.account.password,
            display_name=payload.account.displayName,
            customer_ids=[customer.id, *payload.account.customerIds],
        )
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return CreateCustomerProvisionResponse(
        customer=customer,
        account=to_auth_user_response(account),
    )


@router.get("/{customerId}", response_model=CustomerWorkspaceResponse)
def get_customer_workspace(
    customerId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> CustomerWorkspaceResponse:
    ensure_customer_access(customerId, current_user)
    return repository.get_customer_workspace(customerId)


@router.get("/{customerId}/documents", response_model=PaginatedResponse[DocumentSummary])
def list_customer_documents(
    customerId: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> PaginatedResponse[DocumentSummary]:
    ensure_customer_access(customerId, current_user)
    return _paginate_items(repository.list_documents(customerId), page, pageSize)


@router.post("/{customerId}/upload-contracts", response_model=OssUploadContractResponse)
def create_upload_contract(
    customerId: str,
    payload: OssUploadContractRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
    oss_service: OssStorageService = Depends(get_oss_service),
) -> OssUploadContractResponse:
    ensure_customer_access(customerId, current_user)
    repository.get_customer_workspace(customerId)
    return oss_service.create_upload_contract(
        customerId=customerId,
        fileName=payload.fileName,
        contentType=payload.contentType,
    )


@router.post("/{customerId}/documents", response_model=RegisterDocumentResponse, status_code=status.HTTP_201_CREATED)
def register_document(
    customerId: str,
    payload: RegisterDocumentRequest,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> RegisterDocumentResponse:
    ensure_customer_access(customerId, current_user)
    return repository.register_document(
        customerId,
        payload.model_copy(
            update={
                "uploadedByUserId": current_user.username,
                "uploadedByName": current_user.displayName,
                "roleScope": ["admin", "customer"] if current_user.role == "admin" else ["customer"],
            }
        ),
    )


@router.post(
    "/{customerId}/documents/upload-and-parse",
    response_model=UploadAndParseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_and_parse_document(
    customerId: str,
    taskName: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: SessionUser = Depends(get_current_user),
    pipeline_service: ParsePipelineService = Depends(get_parse_pipeline_service),
) -> UploadAndParseResponse:
    try:
        ensure_customer_access(customerId, current_user)
        return pipeline_service.upload_and_parse(
            customerId=customerId,
            fileName=file.filename or "upload.bin",
            contentType=file.content_type or "application/octet-stream",
            data=await file.read(),
            uploadedByUserId=current_user.username,
            uploadedByName=current_user.displayName,
            roleScope=["admin", "customer"] if current_user.role == "admin" else ["customer"],
            taskName=taskName,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


@router.get("/{customerId}/documents/{documentId}", response_model=DocumentDetail)
def get_document_detail(
    customerId: str,
    documentId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> DocumentDetail:
    ensure_customer_access(customerId, current_user)
    return repository.get_document(customerId, documentId)


@router.get("/{customerId}/tasks", response_model=list[TaskSummary])
def list_customer_tasks(
    customerId: str,
    current_user: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> list[TaskSummary]:
    ensure_customer_access(customerId, current_user)
    return repository.list_customer_tasks(customerId)
