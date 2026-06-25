# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""MySQL-backed repository implementation."""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import json
import logging
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
import re
import zipfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, load_only

from app.core.config import AppSettings
from app.db.models import (
    ApplicationModel,
    ApplicationRunModel,
    ApplicationRunStepModel,
    ApplicationStepModel,
    ApplicationVersionModel,
    ApplicationWorkshopStepDraftModel,
    BusinessSkillModel,
    CustomerModel,
    DocumentModel,
    LlmCallTraceModel,
    ParseJobModel,
    PromptConfigModel,
    PromptRunModel,
    SchemaTemplateModel,
    SkillSampleModel,
    SkillTestRunModel,
    TaskOperationTargetModel,
    TaskResultArtifactModel,
    TaskModel,
)
from app.db.session import session_scope
from app.domain.models import (
    ApplicationRecord,
    ApplicationRunRecord,
    ApplicationRunStepRecord,
    ApplicationStepRecord,
    ApplicationVersionRecord,
    BusinessSkillRecord,
    CustomerRecord,
    DocumentRecord,
    LlmCallTraceRecord,
    ParseJobRecord,
    PromptConfigRecord,
    PromptRunRecord,
    SchemaTemplateRecord,
    SkillSampleRecord,
    SkillTestRunRecord,
    TaskOperationTargetRecord,
    TaskResultArtifactRecord,
    TaskRecord,
)
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    AdminOverviewResponse,
    ApplicationDetail,
    ApplicationRunDetail,
    ApplicationRunStepSummary,
    ApplicationRunSummary,
    ApplicationStepSnapshot,
    ApplicationSummary,
    ApplicationVersionSummary,
    ApplicationWorkshopStepDraft,
    ApplicationWorkshopStepDraftUpsertRequest,
    CreateCustomerRequest,
    CustomerSummary,
    CustomerWorkspaceResponse,
    DocumentDetail,
    DocumentSummary,
    PageOperationTargetsResponse,
    PromptExecutionContext,
    RegisterDocumentRequest,
    RegisterDocumentResponse,
    OperationTargetRef,
    WorkbenchDataset,
    TaskSummary,
    UserTaskListResponse,
    WorkbenchBlock,
    WorkbenchDocument,
    WorkbenchMarkdownSegment,
    WorkbenchPageDetail,
    WorkbenchTaskDetail,
)
from app.services.oss import OssStorageService
from app.services.result_artifacts import (
    build_task_object_key,
    load_json_payload,
    safe_target_file_name,
    write_json_artifact,
)
from app.services.runtime_store import JsonRuntimeStore
from app.services.workbench_builder import (
    build_page_result_detail,
    build_pages_from_artifacts,
    build_task_detail,
)


def _attach_model_payload(block_payload, model_payload):
    if model_payload is None:
        return block_payload
    if block_payload is None:
        return model_payload
    if isinstance(block_payload, dict):
        merged = dict(block_payload)
        merged["_model_payload"] = model_payload
        return merged
    return {"_primary_payload": block_payload, "_model_payload": model_payload}


def _raw_item_looks_like_content_list_v2(item: dict) -> bool:
    content = item.get("content")
    if not isinstance(content, dict):
        return False
    return any(
        key in content
        for key in (
            "paragraph_content",
            "title_content",
            "list_items",
            "html",
            "table_type",
            "table_nest_level",
            "image_source",
            "table_caption",
            "table_footnote",
            "page_header_content",
            "page_footer_content",
            "page_number_content",
            "page_aside_text_content",
            "page_footnote_content",
            "image_caption",
            "image_footnote",
            "chart_caption",
            "chart_footnote",
            "math_content",
            "code_content",
            "algorithm_content",
        )
    )


def _pages_use_content_list_v2(pages: list[WorkbenchPageDetail]) -> bool:
    for page in pages:
        for item in page.rawItems or []:
            if isinstance(item, dict) and _raw_item_looks_like_content_list_v2(item):
                return True
    return False


def _is_content_list_v2_ref(value: str | None) -> bool:
    if not value:
        return False
    name = Path(urlparse(value).path).name
    return name == "content_list_v2.json" or name.endswith("_content_list_v2.json")


logger = logging.getLogger(__name__)


class MysqlWorkbenchRepository(WorkbenchRepository):
    """Serve the existing workbench contract from SQLAlchemy-backed records."""

    _LIGHT_OUTPUT_SUMMARY_KEYS = {
        "summary",
        "resultSummary",
        "preview",
        "resultKind",
        "outputCount",
        "fieldCount",
        "tableCount",
        "structuredObjectCount",
        "validationErrorCount",
        "recordCount",
        "rowCount",
        "outputShapes",
        "planId",
        "planStepId",
        "planReason",
    }

    _LIGHT_RUN_METRIC_KEYS = {
        "durationMs",
        "inputChars",
        "outputChars",
        "totalTokens",
        "evidenceBuildMs",
        "candidateSelectMs",
        "modelCallMs",
        "reviewCallMs",
        "fastPathPreviewMs",
        "localStructuredBuildMs",
        "inputPayloadBytes",
        "factsBytes",
        "fullFactsBytes",
        "reviewFactsBytes",
        "evidenceIndexBytes",
        "selectedEvidenceCount",
        "skippedEvidenceCount",
        "selectedTableRowCount",
        "tableCount",
        "tableRowCount",
        "fullTableRowCount",
        "maxTableRows",
        "evidenceExpansionLevel",
        "uncertaintyFlags",
        "reviewCount",
        "tableFastPath",
    }

    _LIGHT_EVIDENCE_SELECTION_KEYS = {
        "mode",
        "expansionLevel",
        "selectedPageNos",
        "selectedBlockCount",
        "skippedBlockCount",
        "selectedTableRowCount",
        "totalTableRowCount",
        "selectionReasons",
        "warnings",
        "uncertainties",
        "fullFactsPreserved",
    }

    def __init__(
        self,
        store: JsonRuntimeStore,
        settings: AppSettings,
        oss_service: OssStorageService | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._oss_service = oss_service

    def get_dataset(self, *, include_details: bool = False) -> WorkbenchDataset:
        task_records = sorted(self._list_all_task_records(), key=lambda item: item.updatedAt, reverse=True)
        tasks = [self._to_task_summary(task) for task in task_records]
        return WorkbenchDataset(
            customers=self.list_customers(),
            tasks=tasks,
            taskDetails=self._build_task_details(task_records) if include_details else {},
        )

    def list_customers(self) -> list[CustomerSummary]:
        with session_scope() as session:
            counts = self._customer_counts(session)
            models = session.execute(select(CustomerModel)).scalars().all()
            return [
                self._to_customer_summary(self._to_customer_record(model, counts.get(model.id, (0, 0))))
                for model in models
            ]

    def create_customer(self, payload: CreateCustomerRequest) -> CustomerSummary:
        model = CustomerModel(
            id=f"customer-{uuid4().hex[:8]}",
            name=payload.name,
            project_code=payload.projectCode,
            owner=payload.owner,
            description=payload.description,
            created_at=self._now_dt(),
        )
        with session_scope() as session:
            session.add(model)
        return self._to_customer_summary(self._to_customer_record(model, (0, 0)))

    def get_customer_workspace(self, customerId: str) -> CustomerWorkspaceResponse:
        customer = self._get_customer_summary(customerId)
        return CustomerWorkspaceResponse(
            customer=customer,
            documents=self.list_documents(customerId),
            tasks=self.list_customer_tasks(customerId),
        )

    def list_documents(self, customerId: str) -> list[DocumentSummary]:
        self._get_customer_summary(customerId)
        with session_scope() as session:
            models = session.execute(
                select(DocumentModel).where(DocumentModel.customer_id == customerId)
            ).scalars().all()
            documents = [self._to_document_summary(self._to_document_record(model)) for model in models]
            return sorted(documents, key=lambda item: item.updatedAt, reverse=True)

    def get_document(self, customerId: str, documentId: str) -> DocumentDetail:
        self._get_customer_summary(customerId)
        with session_scope() as session:
            model = session.get(DocumentModel, documentId)
            if not model or model.customer_id != customerId:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

            record = self._to_document_record(model)
            related_tasks = [
                self._to_task_summary(self._to_task_record(task_model))
                for task_model in session.execute(
                    select(TaskModel).where(TaskModel.document_id == documentId)
                ).scalars().all()
            ]
            return DocumentDetail(
                **self._to_document_summary(record).model_dump(),
                markdownUrl=record.markdownUrl,
                rawJsonUrl=record.rawJsonUrl,
                layoutUrl=record.layoutUrl,
                blockListUrl=record.blockListUrl,
                modelJsonUrl=record.modelJsonUrl,
                artifactBaseUrl=record.artifactBaseUrl,
                parseTaskId=record.parseTaskId,
                parseError=record.parseError,
                relatedTasks=related_tasks,
            )

    def register_document(self, customerId: str, payload: RegisterDocumentRequest) -> RegisterDocumentResponse:
        customer = self._get_customer_summary(customerId)
        timestamp = self._now_dt()
        document_id = f"doc-{uuid4().hex[:10]}"
        task_id = f"task-{uuid4().hex[:10]}"
        task_name = payload.taskName or f"{payload.fileName} 解析任务"

        with session_scope() as session:
            document_model = DocumentModel(
                id=document_id,
                customer_id=customerId,
                file_name=payload.fileName,
                file_type=payload.fileType,
                source_url=payload.sourceUrl,
                object_key=payload.objectKey,
                page_count=payload.pageCount,
                parse_status="pending",
                uploaded_by_user_id=payload.uploadedByUserId,
                uploaded_by_name=payload.uploadedByName,
                uploaded_at=timestamp,
                updated_at=timestamp,
                parse_task_id=task_id,
                latest_task_id=task_id,
            )
            task_model = TaskModel(
                id=task_id,
                customer_id=customerId,
                document_id=document_id,
                customer_name=customer.name,
                task_name=task_name,
                document_name=payload.fileName,
                role_scope_json=self._dumps_json(list(payload.roleScope)),
                owner=payload.uploadedByName,
                owner_user_id=payload.uploadedByUserId,
                status="pending",
                upload_time=timestamp,
                updated_at=timestamp,
                page_count=payload.pageCount,
                prompt_run_count=0,
                summary="文档已上传，系统正在准备解析。",
            )
            session.add(document_model)
            session.add(task_model)
            # Flush parent rows first so MariaDB/MySQL FK checks pass before inserting parse_jobs.
            session.flush()
            session.add(
                ParseJobModel(
                    task_id=task_id,
                    customer_id=customerId,
                    document_id=document_id,
                    state="pending",
                    extracted_pages=0,
                    total_pages=0,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )

        return RegisterDocumentResponse(
            document=self.get_document(customerId, document_id),
            createdTask=self.get_task_summary(task_id),
        )

    def list_customer_tasks(self, customerId: str) -> list[TaskSummary]:
        self._get_customer_summary(customerId)
        with session_scope() as session:
            tasks = [
                self._to_task_summary(self._to_task_record(model))
                for model in session.execute(
                    select(TaskModel).where(TaskModel.customer_id == customerId)
                ).scalars().all()
            ]
            return sorted(tasks, key=lambda item: item.updatedAt, reverse=True)

    def list_user_tasks(self, userId: str) -> UserTaskListResponse:
        with session_scope() as session:
            tasks = [
                self._to_task_summary(self._to_task_record(model))
                for model in session.execute(
                    select(TaskModel).where(TaskModel.owner_user_id == userId)
                ).scalars().all()
            ]
            return UserTaskListResponse(
                userId=userId,
                tasks=sorted(tasks, key=lambda item: item.updatedAt, reverse=True),
            )

    def get_admin_overview(self) -> AdminOverviewResponse:
        customers = self.list_customers()
        tasks = sorted(self._list_all_task_summaries(), key=lambda item: item.updatedAt, reverse=True)
        with session_scope() as session:
            total_documents = int(session.execute(select(func.count()).select_from(DocumentModel)).scalar_one() or 0)
        return AdminOverviewResponse(
            customers=customers,
            tasks=tasks,
            totalCustomers=len(customers),
            totalDocuments=total_documents,
            totalTasks=len(tasks),
        )

    def get_task_summary(self, taskId: str) -> TaskSummary:
        return self._to_task_summary(self.get_task_record(taskId))

    def get_task_detail(self, taskId: str, *, lightPromptRuns: bool = False) -> WorkbenchTaskDetail:
        task = self.get_task_record(taskId)
        document = self.get_document_record(task.documentId)
        parse_job = self.get_parse_job(taskId)
        detail = self._build_task_detail(
            task=task,
            document=document,
            parse_job=parse_job,
            prompt_configs=self.list_prompt_configs(taskId),
            prompt_runs=self.list_prompt_runs(taskId, light=lightPromptRuns),
        )
        detail.applicationRun = self._get_latest_application_run_detail_for_task(taskId)
        return detail

    def get_task_execution_context(self, taskId: str) -> PromptExecutionContext:
        task = self.get_task_record(taskId)
        document = self.get_document_record(task.documentId)
        parse_job = self.get_parse_job(taskId)
        return PromptExecutionContext(
            documentId=document.id,
            parseStatus=self._resolve_task_parse_status(task, document, parse_job),
            pages=self._build_runtime_pages(document=document, parse_job=parse_job),
        )

    def _build_task_detail(
        self,
        *,
        task: TaskRecord,
        document: DocumentRecord,
        parse_job: ParseJobRecord,
        prompt_configs: list[PromptConfigRecord],
        prompt_runs: list[PromptRunRecord],
    ) -> WorkbenchTaskDetail:
        pages = self._build_runtime_pages(document=document, parse_job=parse_job)
        document_dto = WorkbenchDocument(
            id=document.id,
            fileName=document.fileName,
            fileType=document.fileType,
            pdfUrl=document.sourceUrl,
            markdownUrl=document.markdownUrl or "",
            rawJsonUrl=document.rawJsonUrl or "",
            pageCount=document.pageCount,
            sampledPageCount=len(pages),
        )
        return build_task_detail(
            task=self._to_task_summary(task),
            document=document_dto,
            parseStatus=self._resolve_task_parse_status(task, document, parse_job),
            pages=pages,
            promptConfigs=prompt_configs,
            promptRuns=prompt_runs,
        )

    def get_task_page_result_detail(self, taskId: str, runId: str):
        self.get_task_record(taskId)
        run = self.get_prompt_run(runId)
        if run.taskId != taskId:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt run not found")
        pages = self._build_runtime_pages_from_prompt_input_path(run.inputPath)
        if not pages:
            task = self.get_task_record(taskId)
            pages = self._build_runtime_pages(
                document=self.get_document_record(task.documentId),
                parse_job=self.get_parse_job(taskId),
            )
        return build_page_result_detail(pages, run)

    def get_task_page_detail(self, taskId: str, pageNo: int):
        prompt_input_page = self._get_latest_prompt_input_page(taskId, pageNo)
        if prompt_input_page is not None:
            return prompt_input_page
        task = self.get_task_record(taskId)
        matched = next(
            (
                page
                for page in self._build_runtime_pages(
                    document=self.get_document_record(task.documentId),
                    parse_job=self.get_parse_job(taskId),
                )
                if page.pageNo == pageNo
            ),
            None,
        )
        if not matched:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page detail not found")
        return matched.model_copy(deep=True)

    def get_task_page_operation_targets(self, taskId: str, pageNo: int) -> PageOperationTargetsResponse:
        self.get_task_record(taskId)
        return PageOperationTargetsResponse(
            pageNo=pageNo,
            targets=self._list_persisted_operation_targets(taskId, pageNo),
        )

    def _get_latest_prompt_input_page(self, task_id: str, page_no: int) -> WorkbenchPageDetail | None:
        with session_scope() as session:
            input_paths = session.execute(
                select(PromptRunModel.input_path)
                .where(
                    PromptRunModel.task_id == task_id,
                    PromptRunModel.run_purpose == "parse_prompt",
                    PromptRunModel.status.in_(["running", "completed", "needs_review"]),
                    PromptRunModel.input_path.is_not(None),
                    PromptRunModel.start_page_no <= page_no,
                    PromptRunModel.end_page_no >= page_no,
                )
                .order_by(PromptRunModel.updated_at.desc())
                .limit(8)
            ).scalars().all()

        for input_path in input_paths:
            pages = self._build_runtime_pages_from_prompt_input_path(input_path)
            matched = next((page for page in pages if page.pageNo == page_no), None)
            if matched is not None:
                return matched
        return None

    def _get_latest_completed_parse_run_for_page(self, task_id: str, page_no: int) -> PromptRunRecord | None:
        with session_scope() as session:
            model = session.execute(
                select(PromptRunModel)
                .where(
                    PromptRunModel.task_id == task_id,
                    PromptRunModel.run_purpose == "parse_prompt",
                    PromptRunModel.status.in_(["completed", "needs_review"]),
                    PromptRunModel.start_page_no <= page_no,
                    PromptRunModel.end_page_no >= page_no,
                )
                .order_by(PromptRunModel.updated_at.desc())
                .limit(1)
            ).scalars().first()
            return self._to_prompt_run_record(model) if model is not None else None

    def _build_runtime_pages_from_prompt_input_path(self, input_path: str | None) -> list[WorkbenchPageDetail]:
        if not input_path:
            return []
        try:
            payload = self._store.read_json_artifact(input_path)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        if not isinstance(payload, dict):
            return []

        pages: list[WorkbenchPageDetail] = []
        for page in payload.get("pages") or []:
            if not isinstance(page, dict):
                continue
            try:
                page_no = int(page.get("pageNo") or 0)
            except (TypeError, ValueError):
                page_no = 0
            if page_no <= 0:
                continue
            page_index = page_no - 1
            blocks = [
                WorkbenchBlock(
                    id=str(block.get("id") or f"page-{page_index}-block-{index}"),
                    pageIndex=page_index,
                    pageNo=page_no,
                    blockPosition=str(block.get("blockPosition") or f"{page_index}-{index}"),
                    type=str(block.get("type") or "text"),
                    title=str(block.get("title") or ""),
                    content=str(block.get("content") or ""),
                    htmlContent=str(block.get("content") or "") if str(block.get("type") or "").lower() == "table" else None,
                    bbox=(0.0, 0.0, 0.0, 0.0),
                )
                for index, block in enumerate(page.get("blocks") or [])
                if isinstance(block, dict)
            ]
            markdown_segments = [
                WorkbenchMarkdownSegment(
                    id=str(segment.get("id") or f"page-{page_index}-segment-{index}"),
                    pageIndex=page_index,
                    pageNo=page_no,
                    blockId=str(segment.get("blockId") or ""),
                    blockPosition=str(segment.get("blockPosition") or f"{page_index}-{index}"),
                    type=str(segment.get("type") or "text"),
                    html=str(segment.get("html") or ""),
                    bbox=(0.0, 0.0, 0.0, 0.0),
                )
                for index, segment in enumerate(page.get("markdownSegments") or [])
                if isinstance(segment, dict)
            ]
            pages.append(
                WorkbenchPageDetail(
                    pageIndex=page_index,
                    pageNo=page_no,
                    prompt="",
                    promptStatus="submitted",
                    markdownSegments=markdown_segments,
                    blocks=blocks,
                    rawItems=[],
                    pageSize=(0.0, 0.0),
                )
            )
        return pages

    def get_task_record(self, taskId: str) -> TaskRecord:
        with session_scope() as session:
            model = session.get(TaskModel, taskId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
            return self._to_task_record(model)

    def get_document_record(self, documentId: str) -> DocumentRecord:
        with session_scope() as session:
            model = session.get(DocumentModel, documentId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
            return self._to_document_record(model)

    def get_parse_job(self, taskId: str) -> ParseJobRecord:
        with session_scope() as session:
            model = session.get(ParseJobModel, taskId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parse job not found")
            return self._to_parse_job_record(model)

    def list_schema_templates(self) -> list[SchemaTemplateRecord]:
        with session_scope() as session:
            models = session.execute(select(SchemaTemplateModel)).scalars().all()
            items = [self._to_schema_template_record(model) for model in models]
            return sorted(items, key=lambda item: item.updatedAt, reverse=True)

    def get_schema_template(self, templateId: str) -> SchemaTemplateRecord:
        with session_scope() as session:
            model = session.get(SchemaTemplateModel, templateId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema template not found")
            return self._to_schema_template_record(model)

    def save_schema_template(self, template: SchemaTemplateRecord) -> SchemaTemplateRecord:
        with session_scope() as session:
            model = session.get(SchemaTemplateModel, template.id)
            if not model:
                model = SchemaTemplateModel(id=template.id)
                session.add(model)
            self._apply_schema_template_record(model, template)
        return template

    def list_business_skills(self, customerId: str | None = None) -> list[BusinessSkillRecord]:
        with session_scope() as session:
            statement = select(BusinessSkillModel)
            if customerId is None:
                statement = statement.where(BusinessSkillModel.customer_id.is_(None))
            else:
                statement = statement.where(BusinessSkillModel.customer_id == customerId)
            models = session.execute(statement).scalars().all()
            items = self._collect_valid_business_skill_records(models)
            return sorted(items, key=lambda item: item.updatedAt, reverse=True)

    def list_business_skills_for_customers(self, customerIds: list[str]) -> list[BusinessSkillRecord]:
        customer_ids = [str(item).strip() for item in customerIds if str(item).strip()]
        with session_scope() as session:
            statement = select(BusinessSkillModel).where(BusinessSkillModel.customer_id.is_(None))
            if customer_ids:
                statement = select(BusinessSkillModel).where(
                    (BusinessSkillModel.customer_id.is_(None))
                    | (BusinessSkillModel.customer_id.in_(customer_ids))
                )
            models = session.execute(statement).scalars().all()
            items = self._collect_valid_business_skill_records(models)
            return sorted(items, key=lambda item: item.updatedAt, reverse=True)

    def _collect_valid_business_skill_records(self, models: list[BusinessSkillModel]) -> list[BusinessSkillRecord]:
        items: list[BusinessSkillRecord] = []
        for model in models:
            try:
                items.append(self._to_business_skill_record(model))
            except HTTPException as exc:
                detail = str(exc.detail or "")
                if exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR and (
                    "business_skills.source_types_json" in detail
                    or "business_skills.target_types_json" in detail
                ):
                    logger.warning(
                        "Skip invalid business skill record while listing skills: skill_id=%s customer_id=%s detail=%s",
                        getattr(model, "skill_id", ""),
                        getattr(model, "customer_id", None),
                        detail,
                    )
                    continue
                raise
        return items

    def get_business_skill(self, skillId: str, customerId: str | None = None) -> BusinessSkillRecord:
        with session_scope() as session:
            statement = select(BusinessSkillModel).where(BusinessSkillModel.skill_id == skillId)
            if customerId is None:
                statement = statement.where(BusinessSkillModel.customer_id.is_(None))
            else:
                statement = statement.where(BusinessSkillModel.customer_id == customerId)
            model = session.execute(statement.order_by(BusinessSkillModel.updated_at.desc()).limit(1)).scalars().first()
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business skill not found")
            return self._to_business_skill_record(model)

    def save_business_skill(self, skill: BusinessSkillRecord) -> BusinessSkillRecord:
        storage_id = self._business_skill_storage_id(skill)
        with session_scope() as session:
            model = session.get(BusinessSkillModel, storage_id)
            if not model:
                statement = select(BusinessSkillModel).where(BusinessSkillModel.skill_id == skill.id)
                statement = statement.where(BusinessSkillModel.version == skill.version)
                if skill.customerId is None:
                    statement = statement.where(BusinessSkillModel.customer_id.is_(None))
                else:
                    statement = statement.where(BusinessSkillModel.customer_id == skill.customerId)
                model = session.execute(statement.limit(1)).scalars().first()
            if not model:
                model = BusinessSkillModel(storage_id=storage_id)
                session.add(model)
            self._apply_business_skill_record(model, skill)
        return skill

    def delete_business_skill(self, skillId: str, customerId: str | None = None) -> None:
        with session_scope() as session:
            statement = select(BusinessSkillModel).where(BusinessSkillModel.skill_id == skillId)
            if customerId is None:
                statement = statement.where(BusinessSkillModel.customer_id.is_(None))
            else:
                statement = statement.where(BusinessSkillModel.customer_id == customerId)
            for model in session.execute(statement).scalars().all():
                session.delete(model)

    def move_business_skill(self, skillId: str, sourceCustomerId: str, targetCustomerId: str) -> BusinessSkillRecord:
        if not sourceCustomerId or not targetCustomerId:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="移动归属必须指定源客户和目标客户。")
        with session_scope() as session:
            source = session.execute(
                select(BusinessSkillModel)
                .where(BusinessSkillModel.skill_id == skillId)
                .where(BusinessSkillModel.customer_id == sourceCustomerId)
                .order_by(BusinessSkillModel.updated_at.desc())
                .limit(1)
            ).scalars().first()
            if not source:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
            target_storage_id = f"{targetCustomerId}:{skillId}:{source.version}"[:191]
            existing_target = session.execute(
                select(BusinessSkillModel)
                .where(BusinessSkillModel.skill_id == skillId)
                .where(BusinessSkillModel.version == source.version)
                .where(BusinessSkillModel.customer_id == targetCustomerId)
                .limit(1)
            ).scalars().first()
            if existing_target:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="目标客户已存在同 ID Skill，请先另存或删除。")
            record = self._to_business_skill_record(source)
            session.delete(source)
            moved = BusinessSkillModel(storage_id=target_storage_id)
            session.add(moved)
            record.customerId = targetCustomerId
            record.updatedAt = self._now_dt().isoformat()
            self._apply_business_skill_record(moved, record)
            return record

    def list_skill_samples(
        self,
        *,
        kind: str,
        skillId: str,
        customerId: str | None = None,
        limit: int = 20,
    ) -> list[SkillSampleRecord]:
        with session_scope() as session:
            statement = (
                select(SkillSampleModel)
                .where(SkillSampleModel.kind == kind)
                .where(SkillSampleModel.skill_id == skillId)
            )
            if customerId is not None:
                statement = statement.where(SkillSampleModel.customer_id == customerId)
            models = session.execute(
                statement.order_by(SkillSampleModel.updated_at.desc()).limit(max(1, min(limit, 100)))
            ).scalars().all()
            return [self._to_skill_sample_record(model) for model in models]

    def save_skill_sample(self, sample: SkillSampleRecord) -> SkillSampleRecord:
        with session_scope() as session:
            model = session.get(SkillSampleModel, sample.id)
            if not model:
                model = SkillSampleModel(id=sample.id)
                session.add(model)
            self._apply_skill_sample_record(model, sample)
            self._refresh_skill_stats(session, kind=sample.kind, skill_id=sample.skillId, customer_id=sample.customerId)
        return sample

    def list_skill_test_runs(
        self,
        *,
        kind: str,
        skillId: str,
        customerId: str | None = None,
        limit: int = 20,
    ) -> list[SkillTestRunRecord]:
        with session_scope() as session:
            statement = (
                select(SkillTestRunModel)
                .where(SkillTestRunModel.kind == kind)
                .where(SkillTestRunModel.skill_id == skillId)
            )
            if customerId is not None:
                statement = statement.where(SkillTestRunModel.customer_id == customerId)
            models = session.execute(
                statement.order_by(SkillTestRunModel.updated_at.desc()).limit(max(1, min(limit, 100)))
            ).scalars().all()
            return [self._to_skill_test_run_record(model) for model in models]

    def save_skill_test_run(self, run: SkillTestRunRecord) -> SkillTestRunRecord:
        with session_scope() as session:
            model = session.get(SkillTestRunModel, run.id)
            if not model:
                model = SkillTestRunModel(id=run.id)
                session.add(model)
            self._apply_skill_test_run_record(model, run)
            self._refresh_skill_stats(session, kind=run.kind, skill_id=run.skillId, customer_id=run.customerId)
        return run

    def list_prompt_configs(self, taskId: str) -> list[PromptConfigRecord]:
        self.get_task_record(taskId)
        with session_scope() as session:
            models = session.execute(
                select(PromptConfigModel).where(PromptConfigModel.task_id == taskId)
            ).scalars().all()
            items = [self._to_prompt_config_record(model) for model in models]
            return sorted(items, key=lambda item: item.updatedAt)

    def save_prompt_config(self, config: PromptConfigRecord) -> PromptConfigRecord:
        self.get_task_record(config.taskId)
        with session_scope() as session:
            model = session.get(PromptConfigModel, config.id)
            if not model:
                model = PromptConfigModel(id=config.id)
                session.add(model)
            self._apply_prompt_config_record(model, config)
        return config

    def list_prompt_runs(self, taskId: str, *, runType: str | None = None, light: bool = False) -> list[PromptRunRecord]:
        self.get_task_record(taskId)
        with session_scope() as session:
            stmt = select(PromptRunModel).where(PromptRunModel.task_id == taskId)
            if runType:
                stmt = stmt.where(PromptRunModel.run_type == runType)
            models = session.execute(stmt).scalars().all()
            items = [self._to_prompt_run_record(model, light=light) for model in models]
            return sorted(items, key=lambda item: item.updatedAt, reverse=True)

    def get_prompt_run(self, runId: str) -> PromptRunRecord:
        with session_scope() as session:
            model = session.get(PromptRunModel, runId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt run not found")
            return self._to_prompt_run_record(model)

    def save_prompt_run(self, run: PromptRunRecord, *, refresh_task: bool = True) -> PromptRunRecord:
        self.get_task_record(run.taskId)
        self.get_document_record(run.documentId)
        with session_scope() as session:
            model = session.get(PromptRunModel, run.id)
            if not model:
                model = PromptRunModel(
                    id=run.id,
                    evidence_block_ids_json="[]",
                    evidence_excerpts_json="[]",
                )
                session.add(model)
            self._apply_prompt_run_record(model, run)
        if refresh_task:
            self._refresh_task_from_prompt_runs(run.taskId)
        return run

    def list_applications(
        self,
        *,
        customerIds: list[str] | None = None,
        publishedOnly: bool = False,
        scope: str | None = None,
    ) -> list[ApplicationSummary]:
        with session_scope() as session:
            stmt = select(ApplicationModel)
            normalized_customer_ids = [item for item in (customerIds or []) if item]
            if normalized_customer_ids:
                stmt = stmt.where(ApplicationModel.customer_id.in_(normalized_customer_ids))
            if publishedOnly:
                stmt = stmt.where(ApplicationModel.latest_published_version.is_not(None))
            if scope:
                stmt = stmt.where(ApplicationModel.scope == scope)
            models = session.execute(stmt.order_by(ApplicationModel.updated_at.desc())).scalars().all()
            return [self._to_application_summary(self._to_application_record(model)) for model in models]

    def get_application(self, applicationId: str) -> ApplicationRecord:
        with session_scope() as session:
            model = session.get(ApplicationModel, applicationId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
            return self._to_application_record(model)

    def save_application(self, application: ApplicationRecord) -> ApplicationRecord:
        with session_scope() as session:
            model = session.get(ApplicationModel, application.id)
            if not model:
                model = ApplicationModel(id=application.id)
                session.add(model)
            self._apply_application_record(model, application)
        return application

    def list_application_versions(self, applicationId: str) -> list[ApplicationVersionRecord]:
        self.get_application(applicationId)
        with session_scope() as session:
            models = session.execute(
                select(ApplicationVersionModel)
                .where(ApplicationVersionModel.application_id == applicationId)
                .order_by(ApplicationVersionModel.created_at.desc())
            ).scalars().all()
            return [self._to_application_version_record(model) for model in models]

    def get_application_version(self, applicationId: str, version: str) -> ApplicationVersionRecord:
        with session_scope() as session:
            model = session.execute(
                select(ApplicationVersionModel)
                .where(
                    ApplicationVersionModel.application_id == applicationId,
                    ApplicationVersionModel.version == version,
                )
                .limit(1)
            ).scalars().first()
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application version not found")
            return self._to_application_version_record(model)

    def save_application_version(self, version: ApplicationVersionRecord) -> ApplicationVersionRecord:
        self.get_application(version.applicationId)
        with session_scope() as session:
            model = session.get(ApplicationVersionModel, version.storageId)
            if not model:
                model = ApplicationVersionModel(storage_id=version.storageId)
                session.add(model)
            self._apply_application_version_record(model, version)
        return version

    def list_application_steps(self, applicationId: str, *, versionLabel: str) -> list[ApplicationStepRecord]:
        self.get_application(applicationId)
        with session_scope() as session:
            models = session.execute(
                select(ApplicationStepModel)
                .where(
                    ApplicationStepModel.application_id == applicationId,
                    ApplicationStepModel.version_label == versionLabel,
                )
                .order_by(ApplicationStepModel.step_order.asc())
            ).scalars().all()
            return [self._to_application_step_record(model) for model in models]

    def replace_application_steps(
        self,
        applicationId: str,
        *,
        versionLabel: str,
        steps: list[ApplicationStepRecord],
    ) -> list[ApplicationStepRecord]:
        self.get_application(applicationId)
        with session_scope() as session:
            session.execute(
                delete(ApplicationStepModel).where(
                    ApplicationStepModel.application_id == applicationId,
                    ApplicationStepModel.version_label == versionLabel,
                )
            )
            for step in steps:
                model = ApplicationStepModel(storage_id=step.storageId)
                self._apply_application_step_record(model, step)
                session.add(model)
        return steps

    def get_application_detail(
        self,
        applicationId: str,
        *,
        version: str | None = None,
        includeDraft: bool = False,
    ) -> ApplicationDetail:
        application = self.get_application(applicationId)
        version_records = self.list_application_versions(applicationId)
        resolved_version = None
        if version:
            resolved_version = version
        elif includeDraft and not application.defaultVersion:
            resolved_version = "draft"
        elif application.defaultVersion:
            resolved_version = application.defaultVersion
        elif application.latestPublishedVersion:
            resolved_version = application.latestPublishedVersion
        else:
            resolved_version = "draft"
        if resolved_version == "draft":
            steps = self.list_application_steps(applicationId, versionLabel="draft")
        else:
            steps = self.list_application_steps(applicationId, versionLabel=resolved_version)
        detail = ApplicationDetail(
            **self._to_application_summary(application).model_dump(),
            resolvedVersion=resolved_version,
            steps=[self._to_application_step_snapshot(item) for item in steps],
            versions=[self._to_application_version_summary(item) for item in version_records],
        )
        if resolved_version != "draft":
            version_record = self.get_application_version(applicationId, resolved_version)
            detail.name = version_record.name
            detail.description = version_record.description
            detail.documentType = version_record.documentType
            detail.scenario = version_record.scenario
            detail.coverText = version_record.coverText
            detail.releaseNotes = version_record.releaseNotes
            detail.status = version_record.status  # type: ignore[assignment]
            detail.publishedAt = version_record.publishedAt
            detail.stepCount = version_record.stepCount
        return detail

    def save_application_run(self, run: ApplicationRunRecord) -> ApplicationRunRecord:
        self.get_application(run.applicationId)
        self.get_task_record(run.taskId)
        self.get_document_record(run.documentId)
        with session_scope() as session:
            model = session.get(ApplicationRunModel, run.id)
            if not model:
                model = ApplicationRunModel(id=run.id)
                session.add(model)
            self._apply_application_run_record(model, run)
        return run

    def get_application_run(self, runId: str) -> ApplicationRunRecord:
        with session_scope() as session:
            model = session.get(ApplicationRunModel, runId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application run not found")
            return self._to_application_run_record(model)

    def save_application_run_step(self, step: ApplicationRunStepRecord) -> ApplicationRunStepRecord:
        self.get_application_run(step.applicationRunId)
        with session_scope() as session:
            model = session.get(ApplicationRunStepModel, step.storageId)
            if not model:
                model = ApplicationRunStepModel(storage_id=step.storageId)
                session.add(model)
            self._apply_application_run_step_record(model, step)
        return step

    def list_application_run_steps(self, runId: str) -> list[ApplicationRunStepRecord]:
        self.get_application_run(runId)
        with session_scope() as session:
            models = session.execute(
                select(ApplicationRunStepModel)
                .where(ApplicationRunStepModel.application_run_id == runId)
                .order_by(ApplicationRunStepModel.step_order.asc())
            ).scalars().all()
            return [self._to_application_run_step_record(model) for model in models]

    def get_application_run_detail(self, runId: str, *, includeFinalOutput: bool = True) -> ApplicationRunDetail:
        with session_scope() as session:
            run_model = session.get(ApplicationRunModel, runId)
            if not run_model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application run not found")
            run = self._to_application_run_record(run_model)
            application = session.get(ApplicationModel, run.applicationId)
            application_name = application.name if application else ""
            step_models = session.execute(
                select(ApplicationRunStepModel)
                .where(ApplicationRunStepModel.application_run_id == runId)
                .order_by(ApplicationRunStepModel.step_order.asc())
            ).scalars().all()
            steps = [self._to_application_run_step_record(model) for model in step_models]
            final_output = None
            if includeFinalOutput:
                step_outputs: list[tuple[ApplicationRunStepRecord, dict]] = []
                for step in steps:
                    step_output = self._load_application_run_step_final_output(session, step)
                    if isinstance(step_output, dict):
                        step_outputs.append((step, step_output))
                final_output = self._merge_application_run_final_outputs(step_outputs)
        return ApplicationRunDetail(
            **self._to_application_run_summary(run, application_name).model_dump(),
            steps=[
                self._to_application_run_step_summary(step, light=not includeFinalOutput)
                for step in steps
            ],
            finalOutput=final_output,
        )

    def _load_application_run_step_final_output(
        self,
        session: Session,
        step: ApplicationRunStepRecord,
    ) -> dict | None:
        prompt_run_ids: list[str] = []
        for candidate_id in (step.executionRunId, step.sourceRunId):
            if candidate_id and candidate_id not in prompt_run_ids:
                prompt_run_ids.append(candidate_id)
        for prompt_run_id in prompt_run_ids:
            prompt_run_model = session.get(PromptRunModel, prompt_run_id)
            if not prompt_run_model:
                continue
            structured_process_result = self._load_structured_process_result(prompt_run_model)
            if isinstance(structured_process_result, dict):
                return structured_process_result
            structured_extraction_result = self._load_structured_extraction_result(prompt_run_model)
            if isinstance(structured_extraction_result, dict):
                return structured_extraction_result
        return None

    @staticmethod
    def _is_structured_process_result_payload(payload: dict) -> bool:
        return "resultKind" in payload or "outputPayload" in payload

    @staticmethod
    def _is_structured_extraction_result_payload(payload: dict) -> bool:
        return any(
            isinstance(payload.get(key), list)
            for key in ("outputs", "fields", "tables", "structuredObjects", "errors", "validationErrors")
        )

    @staticmethod
    def _clone_output_with_step_prefix(output: object, step: ApplicationRunStepRecord, index: int) -> object:
        if not isinstance(output, dict):
            return output
        cloned = dict(output)
        output_id = str(cloned.get("id") or f"output-{index + 1}")
        cloned["id"] = f"step-{step.stepOrder}:{output_id}"
        if not cloned.get("title") and step.skillName:
            cloned["title"] = step.skillName
        return cloned

    def _merge_application_run_final_outputs(
        self,
        step_outputs: list[tuple[ApplicationRunStepRecord, dict]],
    ) -> dict | None:
        if not step_outputs:
            return None

        process_outputs = [
            payload
            for _, payload in step_outputs
            if self._is_structured_process_result_payload(payload)
        ]
        if process_outputs:
            return process_outputs[-1]

        extraction_outputs = [
            (step, payload)
            for step, payload in step_outputs
            if self._is_structured_extraction_result_payload(payload)
        ]
        if not extraction_outputs:
            return step_outputs[-1][1]
        if len(extraction_outputs) == 1:
            return extraction_outputs[0][1]

        summaries = []
        outputs = []
        errors = []
        fields = []
        tables = []
        structured_objects = []
        validation_errors = []
        validation_warnings = []
        source_steps = []
        for step, payload in extraction_outputs:
            summary = str(payload.get("summary") or "").strip()
            if summary:
                summaries.append(summary)
            source_steps.append(
                {
                    "stepOrder": step.stepOrder,
                    "skillId": step.skillId,
                    "skillName": step.skillName,
                    "executionRunId": step.executionRunId,
                    "sourceRunId": step.sourceRunId,
                }
            )
            step_outputs_list = payload.get("outputs")
            if isinstance(step_outputs_list, list):
                outputs.extend(
                    self._clone_output_with_step_prefix(output, step, index)
                    for index, output in enumerate(step_outputs_list)
                )
            for key, target in (
                ("errors", errors),
                ("fields", fields),
                ("tables", tables),
                ("structuredObjects", structured_objects),
                ("validationErrors", validation_errors),
                ("validationWarnings", validation_warnings),
            ):
                value = payload.get(key)
                if isinstance(value, list):
                    target.extend(value)

        return {
            "summary": "\n".join(dict.fromkeys(summaries)),
            "outputs": outputs,
            "errors": list(dict.fromkeys(str(item) for item in errors if str(item).strip())),
            "runMeta": {
                "mergedApplicationRun": True,
                "sourceStepCount": len(extraction_outputs),
                "sourceSteps": source_steps,
            },
            "fields": fields,
            "tables": tables,
            "structuredObjects": structured_objects,
            "validationErrors": list(dict.fromkeys(str(item) for item in validation_errors if str(item).strip())),
            "validationWarnings": list(dict.fromkeys(str(item) for item in validation_warnings if str(item).strip())),
        }

    def _get_latest_application_run_detail_for_task(self, taskId: str) -> ApplicationRunDetail | None:
        with session_scope() as session:
            run_model = session.execute(
                select(ApplicationRunModel)
                .where(ApplicationRunModel.task_id == taskId)
                .order_by(ApplicationRunModel.updated_at.desc(), ApplicationRunModel.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if not run_model:
                return None
            run_id = run_model.id
            run_record = self._to_application_run_record(run_model)
            application_model = session.get(ApplicationModel, run_record.applicationId)
            application_name = application_model.name if application_model else ""
            step_models = session.execute(
                select(ApplicationRunStepModel)
                .where(ApplicationRunStepModel.application_run_id == run_id)
                .order_by(ApplicationRunStepModel.step_order.asc())
            ).scalars().all()
            step_records = [self._to_application_run_step_record(model) for model in step_models]
            include_final_output = run_record.status in {"completed", "needs_review", "failed"}
            final_output = None
            if include_final_output:
                step_outputs: list[tuple[ApplicationRunStepRecord, dict]] = []
                for step in step_records:
                    step_output = self._load_application_run_step_final_output(session, step)
                    if isinstance(step_output, dict):
                        step_outputs.append((step, step_output))
                final_output = self._merge_application_run_final_outputs(step_outputs)

            return ApplicationRunDetail(
                **self._to_application_run_summary(run_record, application_name).model_dump(),
                steps=[
                    self._to_application_run_step_summary(step, light=not include_final_output)
                    for step in step_records
                ],
                finalOutput=final_output,
            )

    def list_application_workshop_step_drafts(
        self,
        taskId: str,
        *,
        light: bool = False,
    ) -> list[ApplicationWorkshopStepDraft]:
        self.get_task_record(taskId)
        with session_scope() as session:
            stmt = (
                select(ApplicationWorkshopStepDraftModel)
                .where(ApplicationWorkshopStepDraftModel.task_id == taskId)
                .order_by(ApplicationWorkshopStepDraftModel.updated_at.asc())
            )
            if light:
                stmt = stmt.options(
                    load_only(
                        ApplicationWorkshopStepDraftModel.id,
                        ApplicationWorkshopStepDraftModel.task_id,
                        ApplicationWorkshopStepDraftModel.kind,
                        ApplicationWorkshopStepDraftModel.status,
                        ApplicationWorkshopStepDraftModel.data_type_name,
                        ApplicationWorkshopStepDraftModel.goal,
                        ApplicationWorkshopStepDraftModel.expected_output,
                        ApplicationWorkshopStepDraftModel.source_title,
                        ApplicationWorkshopStepDraftModel.source_scope,
                        ApplicationWorkshopStepDraftModel.skill_name,
                        ApplicationWorkshopStepDraftModel.errors_json,
                        ApplicationWorkshopStepDraftModel.model,
                        ApplicationWorkshopStepDraftModel.created_at,
                        ApplicationWorkshopStepDraftModel.updated_at,
                    )
                )
            models = session.execute(stmt).scalars().all()
            return [self._to_application_workshop_step_draft(model, light=light) for model in models]

    def get_application_workshop_step_draft(self, taskId: str, draftId: str) -> ApplicationWorkshopStepDraft:
        self.get_task_record(taskId)
        with session_scope() as session:
            model = session.get(ApplicationWorkshopStepDraftModel, draftId)
            if not model or model.task_id != taskId:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application workshop draft not found")
            return self._to_application_workshop_step_draft(model)

    def save_application_workshop_step_draft(
        self,
        taskId: str,
        payload: ApplicationWorkshopStepDraftUpsertRequest,
        *,
        userId: str | None = None,
    ) -> ApplicationWorkshopStepDraft:
        task = self.get_task_record(taskId)
        now = self._now_dt()
        with session_scope() as session:
            model = session.get(ApplicationWorkshopStepDraftModel, payload.id)
            if model and model.task_id != taskId:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application workshop draft not found")
            if not model:
                model = ApplicationWorkshopStepDraftModel(
                    id=payload.id,
                    task_id=task.id,
                    customer_id=task.customerId,
                    document_id=task.documentId,
                    created_by_user_id=userId,
                    created_at=now,
                )
                session.add(model)
            self._apply_application_workshop_step_draft(model, payload, task=task, user_id=userId, updated_at=now)
            session.flush()
            return self._to_application_workshop_step_draft(model)

    def delete_application_workshop_step_draft(self, taskId: str, draftId: str) -> None:
        self.get_task_record(taskId)
        with session_scope() as session:
            model = session.get(ApplicationWorkshopStepDraftModel, draftId)
            if not model or model.task_id != taskId:
                return
            session.delete(model)

    def save_llm_call_trace(self, trace: LlmCallTraceRecord) -> LlmCallTraceRecord:
        self.get_task_record(trace.taskId)
        self.get_document_record(trace.documentId)
        with session_scope() as session:
            model = session.get(LlmCallTraceModel, trace.id)
            if not model:
                model = LlmCallTraceModel(id=trace.id)
                session.add(model)
            self._apply_llm_call_trace_record(model, trace)
        return trace

    def list_llm_call_traces(self, taskId: str, *, runId: str | None = None) -> list[LlmCallTraceRecord]:
        self.get_task_record(taskId)
        with session_scope() as session:
            stmt = select(LlmCallTraceModel).where(LlmCallTraceModel.task_id == taskId)
            if runId is not None:
                stmt = stmt.where(LlmCallTraceModel.run_id == runId)
            models = session.execute(stmt.order_by(LlmCallTraceModel.created_at.asc())).scalars().all()
            return [self._to_llm_call_trace_record(model) for model in models]

    def save_result_artifact(self, artifact: TaskResultArtifactRecord) -> TaskResultArtifactRecord:
        self.get_task_record(artifact.taskId)
        self.get_document_record(artifact.documentId)
        with session_scope() as session:
            model = session.get(TaskResultArtifactModel, artifact.id)
            if not model:
                model = TaskResultArtifactModel(id=artifact.id)
                session.add(model)
            self._apply_result_artifact_record(model, artifact)
        return artifact

    def list_result_artifacts(
        self,
        taskId: str,
        *,
        pageNo: int | None = None,
        runId: str | None = None,
        artifactKind: str | None = None,
        stage: str | None = None,
    ) -> list[TaskResultArtifactRecord]:
        self.get_task_record(taskId)
        with session_scope() as session:
            stmt = select(TaskResultArtifactModel).where(TaskResultArtifactModel.task_id == taskId)
            if pageNo is not None:
                stmt = stmt.where(TaskResultArtifactModel.page_no == pageNo)
            if runId is not None:
                stmt = stmt.where(TaskResultArtifactModel.run_id == runId)
            if artifactKind is not None:
                stmt = stmt.where(TaskResultArtifactModel.artifact_kind == artifactKind)
            if stage is not None:
                stmt = stmt.where(TaskResultArtifactModel.stage == stage)
            models = session.execute(stmt.order_by(TaskResultArtifactModel.updated_at.desc())).scalars().all()
            return [self._to_result_artifact_record(model) for model in models]

    def save_page_recognition_snapshots(self, taskId: str, pages: list[WorkbenchPageDetail]) -> None:
        task = self.get_task_record(taskId)
        self.get_document_record(task.documentId)
        now = self._format_ts(self._now_dt())
        for page in pages:
            object_key = build_task_object_key(
                taskId,
                "recognition",
                "pages",
                str(page.pageNo),
                f"{uuid4().hex}.json",
            )
            stored = self._write_json_object(object_key, page.model_dump(mode="json"))
            self.save_result_artifact(
                TaskResultArtifactRecord(
                    id=f"artifact-{uuid4().hex[:12]}",
                    taskId=taskId,
                    documentId=task.documentId,
                    pageNo=page.pageNo,
                    runId=None,
                    stage="recognition",
                    artifactKind="page_recognition",
                    objectKey=stored.objectKey,
                    contentHash=stored.contentHash,
                    sizeBytes=stored.sizeBytes,
                    contentType=stored.contentType,
                    summary={
                        "pageIndex": page.pageIndex,
                        "blockCount": len(page.blocks),
                        "segmentCount": len(page.markdownSegments),
                        "rawItemCount": len(page.rawItems),
                        "version": "page_snapshot_v1",
                    },
                    createdAt=now,
                    updatedAt=now,
                )
            )

    def replace_operation_targets(
        self,
        taskId: str,
        pageNo: int,
        sourceRunId: str,
        targets: list[OperationTargetRef],
    ) -> list[OperationTargetRef]:
        task = self.get_task_record(taskId)
        now_dt = self._now_dt()
        now = self._format_ts(now_dt)
        target_records: list[TaskOperationTargetRecord] = []
        target_refs: list[OperationTargetRef] = []
        for target in targets:
            target_ref = target.model_copy(update={"sourceRunId": sourceRunId})
            target_refs.append(target_ref)
            data_object_key: str | None = None
            data_content_hash: str | None = None
            if target_ref.data is not None:
                data_object_key = build_task_object_key(
                    taskId,
                    "runs",
                    sourceRunId,
                    "operation-targets",
                    safe_target_file_name(target_ref.id),
                )
                stored_data = self._write_json_object(data_object_key, target_ref.data)
                data_object_key = stored_data.objectKey
                data_content_hash = stored_data.contentHash
            target_records.append(
                TaskOperationTargetRecord(
                    storageId=self._operation_target_storage_id(taskId, target_ref.id),
                    taskId=taskId,
                    pageNo=pageNo,
                    targetId=target_ref.id,
                    sourceRunId=sourceRunId,
                    targetType=target_ref.type,
                    label=target_ref.label,
                    valueText=target_ref.valueText,
                    excerpt=target_ref.excerpt,
                    blockPosition=target_ref.blockPosition,
                    fieldKey=target_ref.fieldKey,
                    rowIndex=target_ref.rowIndex,
                    rowCount=target_ref.rowCount,
                    columnCount=target_ref.columnCount,
                    headers=list(target_ref.headers),
                    blockIds=list(target_ref.blockIds),
                    groupLabel=target_ref.groupLabel,
                    dataObjectKey=data_object_key,
                    dataContentHash=data_content_hash,
                    createdAt=now,
                    updatedAt=now,
                )
            )

        with session_scope() as session:
            session.execute(
                delete(TaskOperationTargetModel).where(
                    TaskOperationTargetModel.task_id == taskId,
                    TaskOperationTargetModel.page_no == pageNo,
                )
            )
            for record in target_records:
                model = TaskOperationTargetModel(storage_id=record.storageId)
                self._apply_operation_target_record(model, record)
                session.add(model)

        targets_payload = [target.model_dump(mode="json") for target in target_refs]
        stored_targets = self._write_json_object(
            build_task_object_key(taskId, "runs", sourceRunId, "operation-targets.json"),
            targets_payload,
        )
        self.save_result_artifact(
            TaskResultArtifactRecord(
                id=f"artifact-{uuid4().hex[:12]}",
                taskId=taskId,
                documentId=task.documentId,
                pageNo=pageNo,
                runId=sourceRunId,
                stage="parse",
                artifactKind="operation_targets",
                objectKey=stored_targets.objectKey,
                contentHash=stored_targets.contentHash,
                sizeBytes=stored_targets.sizeBytes,
                contentType=stored_targets.contentType,
                summary={
                    "targetCount": len(target_refs),
                    "targetTypes": sorted({target.type for target in target_refs}),
                    "version": "operation_targets_v1",
                },
                createdAt=now,
                updatedAt=now,
            )
        )
        return target_refs

    def upsert_parse_job(self, job: ParseJobRecord) -> ParseJobRecord:
        task = self.get_task_record(job.taskId)
        self.get_document_record(job.documentId)
        now = self._now_dt()

        with session_scope() as session:
            model = session.get(ParseJobModel, job.taskId)
            if not model:
                model = ParseJobModel(task_id=job.taskId, created_at=self._coerce_datetime(job.createdAt))
                session.add(model)
            job.updatedAt = now.isoformat()
            self._apply_parse_job_record(model, job)

            task_model = session.get(TaskModel, task.id)
            document_model = session.get(DocumentModel, job.documentId)
            if not task_model or not document_model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

            task_model.status = self._normalize_task_status(job.state)
            task_model.updated_at = now
            task_model.summary = self._build_task_summary_text(job)
            if job.totalPages:
                task_model.page_count = job.totalPages
            document_model.parse_status = task_model.status
            document_model.parse_error = job.errorMessage
            document_model.updated_at = now
            if job.totalPages:
                document_model.page_count = job.totalPages
            document_model.parse_task_id = job.taskId
            document_model.latest_task_id = job.taskId
        return job

    def attach_parse_artifacts(self, taskId: str, artifact_urls: dict[str, str | None]) -> None:
        job = self.get_parse_job(taskId)
        with session_scope() as session:
            document = session.get(DocumentModel, job.documentId)
            if not document:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
            document.artifact_base_url = artifact_urls.get("artifactBaseUrl")
            document.markdown_url = artifact_urls.get("markdownUrl")
            document.raw_json_url = artifact_urls.get("rawJsonUrl")
            document.layout_url = artifact_urls.get("layoutUrl")
            document.block_list_url = artifact_urls.get("blockListUrl")
            document.model_json_url = artifact_urls.get("modelJsonUrl")
            document.updated_at = self._now_dt()

    def resolve_artifact_absolute_path(self, relativePath: str | None) -> Path | None:
        if not relativePath:
            return None
        if relativePath.startswith("/sample-doc/"):
            return self._settings.sample_doc_dir / relativePath.removeprefix("/sample-doc/")
        return self._settings.runtime_data_dir / relativePath

    def _get_customer_summary(self, customerId: str) -> CustomerSummary:
        with session_scope() as session:
            model = session.get(CustomerModel, customerId)
            if not model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
            counts = self._customer_counts(session)
            return self._to_customer_summary(self._to_customer_record(model, counts.get(model.id, (0, 0))))

    def _list_all_task_summaries(self) -> list[TaskSummary]:
        return [self._to_task_summary(record) for record in self._list_all_task_records()]

    def _list_all_task_records(self) -> list[TaskRecord]:
        with session_scope() as session:
            models = session.execute(select(TaskModel)).scalars().all()
            return [self._to_task_record(model) for model in models]

    def _build_task_details(self, task_records: list[TaskRecord]) -> dict[str, WorkbenchTaskDetail]:
        if not task_records:
            return {}

        task_ids = [task.id for task in task_records]
        document_ids = sorted({task.documentId for task in task_records})

        with session_scope() as session:
            document_records = {
                model.id: self._to_document_record(model)
                for model in session.execute(
                    select(DocumentModel).where(DocumentModel.id.in_(document_ids))
                ).scalars().all()
            }
            parse_jobs = {
                model.task_id: self._to_parse_job_record(model)
                for model in session.execute(
                    select(ParseJobModel).where(ParseJobModel.task_id.in_(task_ids))
                ).scalars().all()
            }

            prompt_configs_by_task: dict[str, list[PromptConfigRecord]] = defaultdict(list)
            for model in session.execute(
                select(PromptConfigModel).where(PromptConfigModel.task_id.in_(task_ids))
            ).scalars().all():
                prompt_configs_by_task[model.task_id].append(self._to_prompt_config_record(model))

            prompt_runs_by_task: dict[str, list[PromptRunRecord]] = defaultdict(list)
            for model in session.execute(
                select(PromptRunModel).where(PromptRunModel.task_id.in_(task_ids))
            ).scalars().all():
                prompt_runs_by_task[model.task_id].append(self._to_prompt_run_record(model))

        details: dict[str, WorkbenchTaskDetail] = {}
        for task in task_records:
            document = document_records.get(task.documentId)
            if not document:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
            parse_job = parse_jobs.get(task.id)
            if not parse_job:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Task {task.id} is missing parse_job in database",
                )
            details[task.id] = self._build_task_detail(
                task=task,
                document=document,
                parse_job=parse_job,
                prompt_configs=sorted(prompt_configs_by_task.get(task.id, []), key=lambda item: item.updatedAt),
                prompt_runs=sorted(prompt_runs_by_task.get(task.id, []), key=lambda item: item.updatedAt, reverse=True),
            )
        return details

    def _refresh_task_from_prompt_runs(self, taskId: str) -> None:
        with session_scope() as session:
            task_model = session.get(TaskModel, taskId)
            if not task_model:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

            runs = [
                self._to_prompt_run_record(model)
                for model in session.execute(
                    select(PromptRunModel).where(PromptRunModel.task_id == taskId)
                ).scalars().all()
            ]
            page_runs = [item for item in runs if item.runType != "summary"]
            summary_runs = [item for item in runs if item.runType == "summary"]

            task_model.prompt_run_count = len(page_runs)
            if not page_runs:
                return

            task_model.status = self._aggregate_prompt_status(page_runs)
            latest_summary = max(summary_runs, key=lambda item: item.updatedAt, default=None)
            latest_page_run = max(page_runs, key=lambda item: item.updatedAt)
            task_model.updated_at = max(
                (self._coerce_datetime(item.updatedAt) for item in page_runs + summary_runs),
                default=task_model.updated_at,
            )
            if latest_summary and latest_summary.outputText:
                task_model.summary = latest_summary.outputText[:180]
            elif latest_page_run.outputText:
                task_model.summary = latest_page_run.outputText[:180]
            elif latest_page_run.errorMessage:
                task_model.summary = latest_page_run.errorMessage

    def _customer_counts(self, session: Session) -> dict[str, tuple[int, int]]:
        document_counts = dict(
            session.execute(
                select(DocumentModel.customer_id, func.count(DocumentModel.id)).group_by(DocumentModel.customer_id)
            ).all()
        )
        task_counts = dict(
            session.execute(
                select(TaskModel.customer_id, func.count(TaskModel.id)).group_by(TaskModel.customer_id)
            ).all()
        )
        counts: dict[str, tuple[int, int]] = {}
        for customer_id in set(document_counts) | set(task_counts):
            counts[customer_id] = (
                int(document_counts.get(customer_id, 0) or 0),
                int(task_counts.get(customer_id, 0) or 0),
            )
        return counts

    def _to_customer_summary(self, record: CustomerRecord) -> CustomerSummary:
        return CustomerSummary(
            id=record.id,
            name=record.name,
            projectCode=record.projectCode,
            owner=record.owner,
            documentCount=record.documentCount,
            taskCount=record.taskCount,
            description=record.description,
        )

    def _to_customer_record(self, model: CustomerModel, counts: tuple[int, int]) -> CustomerRecord:
        document_count, task_count = counts
        return CustomerRecord(
            id=model.id,
            name=model.name,
            projectCode=model.project_code,
            owner=model.owner,
            description=model.description,
            documentCount=document_count,
            taskCount=task_count,
            createdAt=model.created_at,
        )

    def _to_document_summary(self, record: DocumentRecord) -> DocumentSummary:
        return DocumentSummary(
            id=record.id,
            customerId=record.customerId,
            fileName=record.fileName,
            fileType=record.fileType,
            sourceUrl=record.sourceUrl,
            objectKey=record.objectKey,
            pageCount=record.pageCount,
            parseStatus=record.parseStatus,
            uploadedByName=record.uploadedByName,
            uploadedAt=record.uploadedAt,
            updatedAt=record.updatedAt,
            latestTaskId=record.latestTaskId,
        )

    def _to_task_summary(self, record: TaskRecord) -> TaskSummary:
        return TaskSummary(
            id=record.id,
            customerId=record.customerId,
            customerName=record.customerName,
            taskName=record.taskName,
            documentName=record.documentName,
            roleScope=record.roleScope,
            owner=record.owner,
            status=self._normalize_task_status(record.status),
            uploadTime=record.uploadTime,
            updatedAt=record.updatedAt,
            pageCount=record.pageCount,
            promptRunCount=record.promptRunCount,
            summary=self._present_task_summary_text(record),
        )

    def _to_document_record(self, model: DocumentModel) -> DocumentRecord:
        return DocumentRecord(
            id=model.id,
            customerId=model.customer_id,
            fileName=model.file_name,
            fileType=model.file_type,
            sourceUrl=model.source_url,
            objectKey=model.object_key,
            pageCount=model.page_count,
            parseStatus=model.parse_status,
            uploadedByUserId=model.uploaded_by_user_id,
            uploadedByName=model.uploaded_by_name,
            uploadedAt=self._format_ts(model.uploaded_at),
            updatedAt=self._format_ts(model.updated_at),
            markdownUrl=model.markdown_url,
            rawJsonUrl=model.raw_json_url,
            layoutUrl=model.layout_url,
            blockListUrl=model.block_list_url,
            modelJsonUrl=model.model_json_url,
            artifactBaseUrl=model.artifact_base_url,
            parseTaskId=model.parse_task_id,
            parseError=model.parse_error,
            latestTaskId=model.latest_task_id,
        )

    def _to_task_record(self, model: TaskModel) -> TaskRecord:
        return TaskRecord(
            id=model.id,
            customerId=model.customer_id,
            documentId=model.document_id,
            customerName=model.customer_name,
            taskName=model.task_name,
            documentName=model.document_name,
            roleScope=self._loads_json_list(model.role_scope_json, field_name="tasks.role_scope_json"),
            owner=model.owner,
            ownerUserId=model.owner_user_id,
            status=model.status,
            uploadTime=self._format_ts(model.upload_time),
            updatedAt=self._format_ts(model.updated_at),
            pageCount=model.page_count,
            promptRunCount=model.prompt_run_count,
            summary=model.summary,
        )

    def _to_parse_job_record(self, model: ParseJobModel) -> ParseJobRecord:
        return ParseJobRecord(
            taskId=model.task_id,
            customerId=model.customer_id,
            documentId=model.document_id,
            state=model.state,
            mineruState=model.mineru_state,
            mineruTaskId=model.mineru_task_id,
            errorMessage=model.error_message,
            extractedPages=model.extracted_pages,
            totalPages=model.total_pages,
            startTime=self._format_ts(model.start_time) if model.start_time else None,
            fullZipSourceUrl=model.full_zip_source_url,
            fullZipPath=model.full_zip_path,
            markdownPath=model.markdown_path,
            rawJsonPath=model.raw_json_path,
            layoutPath=model.layout_path,
            blockListPath=model.block_list_path,
            modelJsonPath=model.model_json_path,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_schema_template_record(self, model: SchemaTemplateModel) -> SchemaTemplateRecord:
        return SchemaTemplateRecord(
            id=model.id,
            name=model.name,
            description=model.description,
            documentType=model.document_type,
            scope=model.scope,
            schemaDefinition=self._loads_json_dict(
                model.schema_definition_json,
                field_name="schema_templates.schema_definition_json",
            ) or {},
            instructions=model.instructions,
            bindingConfig=self._loads_json_dict(
                model.binding_config_json,
                field_name="schema_templates.binding_config_json",
            ),
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_business_skill_record(self, model: BusinessSkillModel) -> BusinessSkillRecord:
        return BusinessSkillRecord(
            id=model.skill_id,
            version=model.version,
            name=model.name,
            category=model.category,
            status=str(getattr(model, "status", "") or ("active" if model.enabled else "disabled")),
            sourceTypes=[
                str(item).strip()
                for item in self._loads_json_list(
                    getattr(model, "source_types_json", "[]"),
                    field_name="business_skills.source_types_json",
                )
                if str(item).strip()
            ],
            targetTypes=[
                str(item).strip()
                for item in self._loads_json_list(
                    model.target_types_json,
                    field_name="business_skills.target_types_json",
                )
                if str(item).strip()
            ],
            executor=model.executor,
            resultKind=model.result_kind,
            renderer=model.renderer,
            configSchema=self._loads_json_dict(
                model.config_schema_json,
                field_name="business_skills.config_schema_json",
            ) or {},
            outputSchema=self._loads_json_dict(
                model.output_schema_json,
                field_name="business_skills.output_schema_json",
            ) or {},
            promptTemplate=model.prompt_template,
            examples=[
                item
                for item in self._loads_json_list(
                    model.examples_json,
                    field_name="business_skills.examples_json",
                )
                if isinstance(item, dict)
            ],
            defaults=self._loads_json_dict(
                model.defaults_json,
                field_name="business_skills.defaults_json",
            ) or {},
            skillTextObjectKey=str(getattr(model, "skill_text_object_key", None) or ""),
            skillTextHash=str(getattr(model, "skill_text_hash", None) or ""),
            skillTextSizeBytes=int(getattr(model, "skill_text_size_bytes", 0) or 0),
            skillTextPreview=str(getattr(model, "skill_text_preview", None) or ""),
            enabled=bool(model.enabled),
            customerId=model.customer_id,
            tags=[
                str(item).strip()
                for item in self._loads_json_list(
                    getattr(model, "tags_json", "[]"),
                    field_name="business_skills.tags_json",
                )
                if str(item).strip()
            ],
            latestTestStatus=getattr(model, "latest_test_status", None),
            sampleCount=int(getattr(model, "sample_count", 0) or 0),
            testRunCount=int(getattr(model, "test_run_count", 0) or 0),
            lastTestedAt=(
                self._format_ts(getattr(model, "last_tested_at", None))
                if getattr(model, "last_tested_at", None)
                else None
            ),
            createdBy=getattr(model, "created_by", None),
            updatedBy=getattr(model, "updated_by", None),
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_skill_sample_record(self, model: SkillSampleModel) -> SkillSampleRecord:
        return SkillSampleRecord(
            id=model.id,
            kind=model.kind,
            skillId=model.skill_id,
            version=model.version,
            customerId=model.customer_id,
            instruction=model.instruction,
            objectKey=model.object_key,
            contentType=model.content_type,
            fileName=model.file_name,
            sizeBytes=int(model.size_bytes or 0),
            preview=model.preview,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_skill_test_run_record(self, model: SkillTestRunModel) -> SkillTestRunRecord:
        return SkillTestRunRecord(
            id=model.id,
            kind=model.kind,
            skillId=model.skill_id,
            version=model.version,
            customerId=model.customer_id,
            status=model.status,
            valid=bool(model.valid),
            errors=self._loads_json_list(model.errors_json, field_name="skill_test_runs.errors_json"),
            summary=self._loads_json_dict(model.summary_json, field_name="skill_test_runs.summary_json"),
            inputObjectKey=getattr(model, "input_object_key", None),
            resultObjectKey=getattr(model, "result_object_key", None),
            factsObjectKey=getattr(model, "facts_object_key", None),
            llmObjectKey=getattr(model, "llm_object_key", None),
            result=self._loads_json_dict(model.result_json, field_name="skill_test_runs.result_json"),
            facts=self._loads_json_dict(model.facts_json, field_name="skill_test_runs.facts_json"),
            sampleId=model.sample_id,
            provider=model.provider,
            model=model.model,
            durationMs=model.duration_ms,
            inputChars=int(model.input_chars or 0),
            outputChars=int(model.output_chars or 0),
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_application_record(self, model: ApplicationModel) -> ApplicationRecord:
        return ApplicationRecord(
            id=model.id,
            customerId=model.customer_id,
            scope=model.scope or "private",
            name=model.name,
            description=model.description,
            documentType=model.document_type,
            scenario=model.scenario,
            coverText=model.cover_text,
            releaseNotes=model.release_notes,
            status=model.status,
            defaultVersion=model.default_version,
            latestPublishedVersion=model.latest_published_version,
            sourceTaskId=model.source_task_id,
            sourceDocumentId=model.source_document_id,
            stepCount=int(model.step_count or 0),
            createdByUserId=model.created_by_user_id,
            createdByName=model.created_by_name,
            updatedByUserId=model.updated_by_user_id,
            updatedByName=model.updated_by_name,
            publishedAt=self._format_ts(model.published_at) if model.published_at else None,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_application_summary(self, record: ApplicationRecord) -> ApplicationSummary:
        return ApplicationSummary(
            id=record.id,
            customerId=record.customerId,
            scope=record.scope,  # type: ignore[arg-type]
            name=record.name,
            description=record.description,
            documentType=record.documentType,
            scenario=record.scenario,
            coverText=record.coverText,
            releaseNotes=record.releaseNotes,
            status=record.status,  # type: ignore[arg-type]
            defaultVersion=record.defaultVersion,
            latestPublishedVersion=record.latestPublishedVersion,
            sourceTaskId=record.sourceTaskId,
            sourceDocumentId=record.sourceDocumentId,
            stepCount=record.stepCount,
            createdByUserId=record.createdByUserId,
            createdByName=record.createdByName,
            updatedByUserId=record.updatedByUserId,
            updatedByName=record.updatedByName,
            publishedAt=record.publishedAt,
            createdAt=record.createdAt,
            updatedAt=record.updatedAt,
        )

    def _to_application_version_record(self, model: ApplicationVersionModel) -> ApplicationVersionRecord:
        return ApplicationVersionRecord(
            storageId=model.storage_id,
            applicationId=model.application_id,
            customerId=model.customer_id,
            version=model.version,
            name=model.name,
            description=model.description,
            documentType=model.document_type,
            scenario=model.scenario,
            coverText=model.cover_text,
            releaseNotes=model.release_notes,
            status=model.status,
            isDefault=bool(model.is_default),
            sourceTaskId=model.source_task_id,
            sourceDocumentId=model.source_document_id,
            stepCount=int(model.step_count or 0),
            publishedByUserId=model.published_by_user_id,
            publishedByName=model.published_by_name,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
            publishedAt=self._format_ts(model.published_at) if model.published_at else None,
        )

    def _to_application_version_summary(self, record: ApplicationVersionRecord) -> ApplicationVersionSummary:
        return ApplicationVersionSummary(
            version=record.version,
            status=record.status,  # type: ignore[arg-type]
            isDefault=record.isDefault,
            stepCount=record.stepCount,
            publishedByUserId=record.publishedByUserId,
            publishedByName=record.publishedByName,
            publishedAt=record.publishedAt,
            createdAt=record.createdAt,
            updatedAt=record.updatedAt,
        )

    def _to_application_step_record(self, model: ApplicationStepModel) -> ApplicationStepRecord:
        return ApplicationStepRecord(
            storageId=model.storage_id,
            applicationId=model.application_id,
            versionLabel=model.version_label,
            stepOrder=int(model.step_order or 0),
            kind=model.kind,
            skillId=model.skill_id,
            skillVersion=model.skill_version,
            skillName=model.skill_name,
            sourceTaskId=model.source_task_id,
            sourceDocumentId=model.source_document_id,
            sourcePageNo=model.source_page_no,
            sourceRunId=model.source_run_id,
            sourceStatus=model.source_status,
            runPurpose=model.run_purpose,
            operationType=model.operation_type,
            resultMode=model.result_mode,
            skillSnapshot=self._loads_json_dict(model.skill_snapshot_json, field_name="application_steps.skill_snapshot_json") or {},
            configSnapshot=self._loads_json_dict(model.config_snapshot_json, field_name="application_steps.config_snapshot_json") or {},
            promptSnapshot=model.prompt_snapshot,
            inputMapping=self._loads_json_dict(model.input_mapping_json, field_name="application_steps.input_mapping_json") or {},
            targetMapping=self._loads_json_dict(model.target_mapping_json, field_name="application_steps.target_mapping_json") or {},
            dependencyRefs=self._loads_json_dict(model.dependency_refs_json, field_name="application_steps.dependency_refs_json") or {},
            outputSummary=self._loads_json_dict(model.output_summary_json, field_name="application_steps.output_summary_json") or {},
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_application_step_snapshot(self, record: ApplicationStepRecord) -> ApplicationStepSnapshot:
        return ApplicationStepSnapshot(
            stepOrder=record.stepOrder,
            kind=record.kind,  # type: ignore[arg-type]
            skillId=record.skillId,
            skillVersion=record.skillVersion,
            skillName=record.skillName,
            sourceTaskId=record.sourceTaskId,
            sourceDocumentId=record.sourceDocumentId,
            sourcePageNo=record.sourcePageNo,
            sourceRunId=record.sourceRunId,
            sourceStatus=record.sourceStatus,
            runPurpose=record.runPurpose,
            operationType=record.operationType,
            resultMode=record.resultMode,
            skillSnapshot=record.skillSnapshot,
            configSnapshot=record.configSnapshot,
            promptSnapshot=record.promptSnapshot,
            inputMapping=record.inputMapping,
            targetMapping=record.targetMapping,
            dependencyRefs=record.dependencyRefs,
            outputSummary=record.outputSummary,
        )

    def _to_application_run_record(self, model: ApplicationRunModel) -> ApplicationRunRecord:
        return ApplicationRunRecord(
            id=model.id,
            applicationId=model.application_id,
            customerId=model.customer_id,
            taskId=model.task_id,
            documentId=model.document_id,
            version=model.version,
            status=model.status,
            stepCount=int(model.step_count or 0),
            completedStepCount=int(model.completed_step_count or 0),
            triggeredByUserId=model.triggered_by_user_id,
            triggeredByName=model.triggered_by_name,
            errorMessage=model.error_message,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _get_application_name(self, application_id: str) -> str:
        with session_scope() as session:
            application = session.get(ApplicationModel, application_id)
            return application.name if application else ""

    def _to_application_run_summary(self, record: ApplicationRunRecord, application_name: str = "") -> ApplicationRunSummary:
        return ApplicationRunSummary(
            id=record.id,
            applicationId=record.applicationId,
            applicationName=application_name,
            customerId=record.customerId,
            taskId=record.taskId,
            documentId=record.documentId,
            version=record.version,
            status=record.status,  # type: ignore[arg-type]
            stepCount=record.stepCount,
            completedStepCount=record.completedStepCount,
            triggeredByUserId=record.triggeredByUserId,
            triggeredByName=record.triggeredByName,
            errorMessage=record.errorMessage,
            createdAt=record.createdAt,
            updatedAt=record.updatedAt,
        )

    def _to_application_run_step_record(self, model: ApplicationRunStepModel) -> ApplicationRunStepRecord:
        return ApplicationRunStepRecord(
            storageId=model.storage_id,
            applicationRunId=model.application_run_id,
            applicationId=model.application_id,
            version=model.version,
            stepOrder=int(model.step_order or 0),
            kind=model.kind,
            skillId=model.skill_id,
            skillVersion=model.skill_version,
            skillName=model.skill_name,
            sourceApplicationStepId=model.source_application_step_id,
            sourcePageNo=model.source_page_no,
            sourceRunId=model.source_run_id,
            executionRunId=model.execution_run_id,
            status=model.status,
            inputMapping=self._loads_json_dict(model.input_mapping_json, field_name="application_run_steps.input_mapping_json") or {},
            targetMapping=self._loads_json_dict(model.target_mapping_json, field_name="application_run_steps.target_mapping_json") or {},
            configSnapshot=self._loads_json_dict(model.config_snapshot_json, field_name="application_run_steps.config_snapshot_json") or {},
            promptSnapshot=model.prompt_snapshot,
            outputSummary=self._loads_json_dict(model.output_summary_json, field_name="application_run_steps.output_summary_json") or {},
            errorMessage=model.error_message,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_application_run_step_summary(
        self,
        record: ApplicationRunStepRecord,
        *,
        light: bool = False,
    ) -> ApplicationRunStepSummary:
        return ApplicationRunStepSummary(
            stepOrder=record.stepOrder,
            kind=record.kind,  # type: ignore[arg-type]
            skillId=record.skillId,
            skillVersion=record.skillVersion,
            skillName=record.skillName,
            sourcePageNo=record.sourcePageNo,
            sourceRunId=record.sourceRunId,
            executionRunId=record.executionRunId,
            status=record.status,  # type: ignore[arg-type]
            inputMapping=self._light_application_run_input_mapping(record.inputMapping) if light else record.inputMapping,
            targetMapping=self._light_application_run_target_mapping(record.targetMapping) if light else record.targetMapping,
            configSnapshot=record.configSnapshot,
            promptSnapshot="" if light else record.promptSnapshot,
            outputSummary=self._light_application_run_output_summary(record.outputSummary) if light else record.outputSummary,
            errorMessage=record.errorMessage,
            createdAt=record.createdAt,
            updatedAt=record.updatedAt,
        )

    @classmethod
    def _light_application_run_input_mapping(cls, value: dict[str, object]) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, object] = {}
        for key in (
            "pageNo",
            "startPageNo",
            "endPageNo",
            "runType",
            "selectionRule",
            "outputKey",
            "planStepId",
            "matchedPageNos",
        ):
            if key in value:
                result[key] = value[key]
        page_scope = value.get("pageScope")
        if isinstance(page_scope, dict):
            result["pageScope"] = {
                key: page_scope[key]
                for key in ("mode", "pageNo", "startPageNo", "endPageNo", "pageRange")
                if key in page_scope
            }
        content_refs = value.get("contentRefs")
        if isinstance(content_refs, list):
            result["contentRefs"] = [
                cls._light_content_ref(item)
                for item in content_refs
                if isinstance(item, dict)
            ]
        return result

    @staticmethod
    def _light_content_ref(value: dict[str, object]) -> dict[str, object]:
        return {
            key: value[key]
            for key in (
                "targetId",
                "type",
                "pageNo",
                "source",
                "pages",
                "evidencePages",
                "treeNodeId",
                "nodeId",
            )
            if key in value
        }

    @staticmethod
    def _light_generated_target(value: dict[str, object]) -> dict[str, object]:
        return {
            key: value[key]
            for key in ("sourceTargetId", "type", "label", "fieldKey", "groupLabel", "rowIndex", "headers")
            if key in value
        }

    @classmethod
    def _light_application_run_target_mapping(cls, value: dict[str, object]) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, object] = {}
        for key in ("pageNo", "selectionMode", "planStepId"):
            if key in value:
                result[key] = value[key]
        generated_targets = value.get("generatedTargets")
        if isinstance(generated_targets, list):
            result["generatedTargetCount"] = len(generated_targets)
            result["generatedTargets"] = [
                cls._light_generated_target(item)
                for item in generated_targets
                if isinstance(item, dict)
            ][:20]
        selected_targets = value.get("selectedTargets")
        if isinstance(selected_targets, list):
            result["selectedTargetCount"] = len(selected_targets)
        locator_result = value.get("locatorResult")
        if isinstance(locator_result, dict):
            result["locatorResult"] = {
                key: locator_result[key]
                for key in ("selectedNodeIds", "confidence", "candidateGap", "warnings", "strategy")
                if key in locator_result
            }
        execution_gate = value.get("executionGate")
        if isinstance(execution_gate, dict):
            result["executionGate"] = {
                key: execution_gate[key]
                for key in ("autoExecute", "needsReview", "confidence", "candidateGap", "warnings")
                if key in execution_gate
            }
        return result

    @classmethod
    def _light_application_run_output_summary(cls, value: dict[str, object]) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, object] = {
            key: value[key]
            for key in cls._LIGHT_OUTPUT_SUMMARY_KEYS
            if key in value
        }
        if isinstance(value.get("validationErrors"), list):
            result["validationErrors"] = cls._bounded_string_list(value["validationErrors"], limit=3)
        if isinstance(value.get("evidenceWarnings"), list):
            result["evidenceWarnings"] = cls._bounded_string_list(value["evidenceWarnings"], limit=3)
        if isinstance(value.get("reviewFeedbacks"), list):
            result["reviewFeedbackCount"] = len(value["reviewFeedbacks"])
        metrics = value.get("runMetrics")
        if isinstance(metrics, dict):
            result["runMetrics"] = cls._light_run_metrics(metrics)
        selection = value.get("evidenceSelection")
        if isinstance(selection, dict):
            result["evidenceSelection"] = cls._light_evidence_selection(selection)
        review_selection = value.get("reviewEvidenceSelection")
        if isinstance(review_selection, dict) and review_selection:
            result["reviewEvidenceSelection"] = cls._light_evidence_selection(review_selection)
        return result

    @classmethod
    def _light_run_metrics(cls, value: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {
            key: value[key]
            for key in cls._LIGHT_RUN_METRIC_KEYS
            if key in value
        }
        table_review_risk = value.get("tableReviewRisk")
        if isinstance(table_review_risk, dict):
            result["tableReviewRisk"] = cls._light_table_review_risk(table_review_risk)
        return result

    @classmethod
    def _light_table_review_risk(cls, value: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {
            key: value[key]
            for key in ("outputType", "tableCount", "riskTableCount", "criticalTableCount")
            if key in value
        }
        if isinstance(value.get("warnings"), list):
            result["warnings"] = cls._bounded_string_list(value["warnings"], limit=3)
        if isinstance(value.get("validationErrors"), list):
            result["validationErrors"] = cls._bounded_string_list(value["validationErrors"], limit=3)
        risks = value.get("risks")
        if isinstance(risks, list):
            result["risks"] = [
                cls._light_table_risk_item(item)
                for item in risks
                if isinstance(item, dict)
            ][:4]
        return result

    @staticmethod
    def _light_table_risk_item(value: dict[str, object]) -> dict[str, object]:
        return {
            key: value[key]
            for key in (
                "pageNo",
                "blockIndex",
                "sourceOrdinal",
                "blockId",
                "title",
                "rowCount",
                "columnCount",
                "uncertainties",
                "severity",
            )
            if key in value
        }

    @classmethod
    def _light_evidence_selection(cls, value: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {
            key: value[key]
            for key in cls._LIGHT_EVIDENCE_SELECTION_KEYS
            if key in value
        }
        selected_evidence = value.get("selectedEvidence")
        if isinstance(selected_evidence, list):
            result["selectedEvidenceCount"] = len(selected_evidence)
        return result

    @staticmethod
    def _bounded_string_list(value: object, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()][:limit]

    @staticmethod
    def _truncate_for_light_response(value: object, *, limit: int = 1200) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _to_application_workshop_step_draft(
        self,
        model: ApplicationWorkshopStepDraftModel,
        *,
        light: bool = False,
    ) -> ApplicationWorkshopStepDraft:
        if light:
            return ApplicationWorkshopStepDraft(
                id=model.id,
                taskId=model.task_id,
                isLight=True,
                kind=model.kind,  # type: ignore[arg-type]
                status=model.status if model.status in {"generated", "verified"} else "generated",  # type: ignore[arg-type]
                dataTypeName=model.data_type_name,
                goal=self._truncate_for_light_response(model.goal, limit=1200),
                expectedOutput=self._truncate_for_light_response(model.expected_output, limit=1200),
                sourceTitle=self._truncate_for_light_response(model.source_title, limit=320),
                sourceScope=self._truncate_for_light_response(model.source_scope, limit=320),
                skillText="",
                skillName=model.skill_name,
                errors=self._loads_json_list(model.errors_json, field_name="application_workshop_step_drafts.errors_json"),
                model=model.model,
                sampleSource=None,
                semanticLocator=None,
                sampleExtraction=None,
                sampleProcessing=None,
                skillDevelopment=None,
                runOption=None,
                createdAt=self._format_ts(model.created_at),
                updatedAt=self._format_ts(model.updated_at),
            )
        sample_source = self._loads_json_dict(
            model.sample_source_json,
            field_name="application_workshop_step_drafts.sample_source_json",
        )
        semantic_locator = sample_source.get("locator") if isinstance(sample_source.get("locator"), dict) else {}
        skill_development = sample_source.pop("skillDevelopment", None)
        if not isinstance(skill_development, dict):
            skill_development = None
        return ApplicationWorkshopStepDraft(
            id=model.id,
            taskId=model.task_id,
            isLight=False,
            kind=model.kind,  # type: ignore[arg-type]
            status=model.status if model.status in {"generated", "verified"} else "generated",  # type: ignore[arg-type]
            dataTypeName=model.data_type_name,
            goal=model.goal,
            expectedOutput=model.expected_output,
            sourceTitle=model.source_title,
            sourceScope=model.source_scope,
            skillText=model.skill_text,
            skillName=model.skill_name,
            errors=self._loads_json_list(model.errors_json, field_name="application_workshop_step_drafts.errors_json"),
            model=model.model,
            sampleSource=sample_source,
            semanticLocator=semantic_locator or None,
            sampleExtraction=self._loads_json_dict(
                model.sample_extraction_json,
                field_name="application_workshop_step_drafts.sample_extraction_json",
            ),
            sampleProcessing=self._loads_json_dict(
                model.sample_processing_json,
                field_name="application_workshop_step_drafts.sample_processing_json",
            ),
            skillDevelopment=skill_development,
            runOption=self._loads_json_dict(
                model.run_option_json,
                field_name="application_workshop_step_drafts.run_option_json",
            ),
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_prompt_config_record(self, model: PromptConfigModel) -> PromptConfigRecord:
        return PromptConfigRecord(
            id=model.id,
            taskId=model.task_id,
            promptName=model.prompt_name,
            promptText=model.prompt_text,
            startPageNo=model.start_page_no,
            endPageNo=model.end_page_no,
            runPurpose=model.run_purpose,
            sourceTemplateId=model.source_template_id,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_prompt_run_record(self, model: PromptRunModel, *, light: bool = False) -> PromptRunRecord:
        if light:
            return PromptRunRecord(
                id=model.id,
                taskId=model.task_id,
                documentId=model.document_id,
                runType=model.run_type,
                runName=model.run_name,
                promptName=model.prompt_name,
                promptText="",
                startPageNo=model.start_page_no,
                endPageNo=model.end_page_no,
                status=model.status,
                runPhase=str(getattr(model, "run_phase", None) or ("model_processing" if model.status == "running" else model.status)),
                runPurpose=model.run_purpose,
                promptConfigId=model.prompt_config_id,
                templateId=model.template_id,
                schemaTemplateName=model.schema_template_name,
                schemaTemplateVersion=model.schema_template_version,
                llmProvider=model.llm_provider,
                llmModel=model.llm_model,
                errorMessage=model.error_message,
                inputPath=None,
                outputPath=None,
                outputText=None,
                inputFactsSnapshot=None,
                schemaDefinition=None,
                schemaOutput=None,
                validationErrors=self._loads_json_list(
                    model.validation_errors_json,
                    field_name="prompt_runs.validation_errors_json",
                ) if model.validation_errors_json else [],
                structuredExtractionResult=None,
                structuredProcessResult=None,
                structuredBusinessResult=None,
                evidenceBlockIds=self._loads_json_list(
                    model.evidence_block_ids_json,
                    field_name="prompt_runs.evidence_block_ids_json",
                ),
                evidenceExcerpts=self._loads_json_list(
                    model.evidence_excerpts_json,
                    field_name="prompt_runs.evidence_excerpts_json",
                ),
                phaseStartedAt=(
                    self._format_ts(getattr(model, "phase_started_at", None))
                    if getattr(model, "phase_started_at", None)
                    else None
                ),
                lastHeartbeatAt=(
                    self._format_ts(getattr(model, "last_heartbeat_at", None))
                    if getattr(model, "last_heartbeat_at", None)
                    else None
                ),
                createdAt=self._format_ts(model.created_at),
                updatedAt=self._format_ts(model.updated_at),
            )
        return PromptRunRecord(
            id=model.id,
            taskId=model.task_id,
            documentId=model.document_id,
            runType=model.run_type,
            runName=model.run_name,
            promptName=model.prompt_name,
            promptText=model.prompt_text,
            startPageNo=model.start_page_no,
            endPageNo=model.end_page_no,
            status=model.status,
            runPhase=str(getattr(model, "run_phase", None) or ("model_processing" if model.status == "running" else model.status)),
            runPurpose=model.run_purpose,
            promptConfigId=model.prompt_config_id,
            templateId=model.template_id,
            schemaTemplateName=model.schema_template_name,
            schemaTemplateVersion=model.schema_template_version,
            llmProvider=model.llm_provider,
            llmModel=model.llm_model,
            errorMessage=model.error_message,
            inputPath=model.input_path,
            outputPath=model.output_path,
            outputText=model.output_text,
            inputFactsSnapshot=self._loads_json_dict(
                model.input_facts_snapshot_json,
                field_name="prompt_runs.input_facts_snapshot_json",
            ),
            schemaDefinition=self._loads_json_dict(
                model.schema_definition_json,
                field_name="prompt_runs.schema_definition_json",
            ),
            schemaOutput=self._loads_json_dict(
                model.schema_output_json,
                field_name="prompt_runs.schema_output_json",
            ),
            validationErrors=self._loads_json_list(
                model.validation_errors_json,
                field_name="prompt_runs.validation_errors_json",
            ) if model.validation_errors_json else [],
            structuredExtractionResult=self._load_structured_extraction_result(model),
            structuredProcessResult=self._load_structured_process_result(model),
            structuredBusinessResult=self._load_structured_business_result(model),
            evidenceBlockIds=self._loads_json_list(
                model.evidence_block_ids_json,
                field_name="prompt_runs.evidence_block_ids_json",
            ),
            evidenceExcerpts=self._loads_json_list(
                model.evidence_excerpts_json,
                field_name="prompt_runs.evidence_excerpts_json",
            ),
            phaseStartedAt=(
                self._format_ts(getattr(model, "phase_started_at", None))
                if getattr(model, "phase_started_at", None)
                else None
            ),
            lastHeartbeatAt=(
                self._format_ts(getattr(model, "last_heartbeat_at", None))
                if getattr(model, "last_heartbeat_at", None)
                else None
            ),
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_llm_call_trace_record(self, model: LlmCallTraceModel) -> LlmCallTraceRecord:
        return LlmCallTraceRecord(
            id=model.id,
            taskId=model.task_id,
            documentId=model.document_id,
            runId=model.run_id,
            stage=model.stage,
            requestKind=model.request_kind,
            status=model.status,
            runPhase=model.run_phase,
            provider=model.provider,
            model=model.model,
            skillId=model.skill_id,
            inputChars=int(model.input_chars or 0),
            outputChars=int(model.output_chars or 0),
            promptTokens=model.prompt_tokens,
            completionTokens=model.completion_tokens,
            totalTokens=model.total_tokens,
            httpMs=model.http_ms,
            totalMs=model.total_ms,
            errorType=model.error_type,
            requestObjectKey=model.request_object_key,
            responseObjectKey=model.response_object_key,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_result_artifact_record(self, model: TaskResultArtifactModel) -> TaskResultArtifactRecord:
        return TaskResultArtifactRecord(
            id=model.id,
            taskId=model.task_id,
            documentId=model.document_id,
            pageNo=model.page_no,
            runId=model.run_id,
            stage=model.stage,
            artifactKind=model.artifact_kind,
            objectKey=model.object_key,
            contentHash=model.content_hash,
            sizeBytes=int(model.size_bytes or 0),
            contentType=model.content_type,
            summary=self._loads_json_dict(
                model.summary_json,
                field_name="task_result_artifacts.summary_json",
            ),
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _to_operation_target_record(self, model: TaskOperationTargetModel) -> TaskOperationTargetRecord:
        return TaskOperationTargetRecord(
            storageId=model.storage_id,
            taskId=model.task_id,
            pageNo=model.page_no,
            targetId=model.target_id,
            sourceRunId=model.source_run_id,
            targetType=model.target_type,
            label=model.label,
            valueText=model.value_text,
            excerpt=model.excerpt,
            blockPosition=model.block_position,
            fieldKey=model.field_key,
            rowIndex=model.row_index,
            rowCount=model.row_count,
            columnCount=model.column_count,
            headers=self._loads_json_list(model.headers_json, field_name="task_operation_targets.headers_json"),
            blockIds=self._loads_json_list(model.block_ids_json, field_name="task_operation_targets.block_ids_json"),
            groupLabel=model.group_label,
            dataObjectKey=model.data_object_key,
            dataContentHash=model.data_content_hash,
            createdAt=self._format_ts(model.created_at),
            updatedAt=self._format_ts(model.updated_at),
        )

    def _operation_target_to_ref(self, record: TaskOperationTargetRecord) -> OperationTargetRef:
        data = self._read_json_object(record.dataObjectKey) if record.dataObjectKey else None
        return OperationTargetRef(
            id=record.targetId,
            pageNo=record.pageNo,
            type=record.targetType,  # type: ignore[arg-type]
            label=record.label,
            valueText=record.valueText,
            sourceRunId=record.sourceRunId,
            excerpt=record.excerpt,
            blockIds=list(record.blockIds),
            blockPosition=record.blockPosition,
            fieldKey=record.fieldKey,
            rowIndex=record.rowIndex,
            rowCount=record.rowCount,
            columnCount=record.columnCount,
            headers=list(record.headers),
            groupLabel=record.groupLabel,
            data=data,
        )

    def _list_persisted_operation_targets(self, taskId: str, pageNo: int) -> list[OperationTargetRef]:
        with session_scope() as session:
            models = session.execute(
                select(TaskOperationTargetModel)
                .where(
                    TaskOperationTargetModel.task_id == taskId,
                    TaskOperationTargetModel.page_no == pageNo,
                )
                .order_by(TaskOperationTargetModel.updated_at.desc(), TaskOperationTargetModel.target_id.asc())
            ).scalars().all()
            records = [self._to_operation_target_record(model) for model in models]
        return [self._operation_target_to_ref(record) for record in records]

    def _apply_prompt_config_record(self, model: PromptConfigModel, record: PromptConfigRecord) -> None:
        model.task_id = record.taskId
        model.prompt_name = record.promptName
        model.prompt_text = record.promptText
        model.start_page_no = record.startPageNo
        model.end_page_no = record.endPageNo
        model.run_purpose = record.runPurpose
        model.source_template_id = record.sourceTemplateId
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_application_record(self, model: ApplicationModel, record: ApplicationRecord) -> None:
        model.customer_id = record.customerId
        model.scope = record.scope
        model.name = record.name
        model.description = record.description
        model.document_type = record.documentType
        model.scenario = record.scenario
        model.cover_text = record.coverText
        model.release_notes = record.releaseNotes
        model.status = record.status
        model.default_version = record.defaultVersion
        model.latest_published_version = record.latestPublishedVersion
        model.source_task_id = record.sourceTaskId
        model.source_document_id = record.sourceDocumentId
        model.step_count = int(record.stepCount or 0)
        model.created_by_user_id = record.createdByUserId
        model.created_by_name = record.createdByName
        model.updated_by_user_id = record.updatedByUserId
        model.updated_by_name = record.updatedByName
        model.published_at = self._coerce_datetime(record.publishedAt) if record.publishedAt else None
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_application_version_record(
        self,
        model: ApplicationVersionModel,
        record: ApplicationVersionRecord,
    ) -> None:
        model.application_id = record.applicationId
        model.customer_id = record.customerId
        model.version = record.version
        model.name = record.name
        model.description = record.description
        model.document_type = record.documentType
        model.scenario = record.scenario
        model.cover_text = record.coverText
        model.release_notes = record.releaseNotes
        model.status = record.status
        model.is_default = bool(record.isDefault)
        model.source_task_id = record.sourceTaskId
        model.source_document_id = record.sourceDocumentId
        model.step_count = int(record.stepCount or 0)
        model.published_by_user_id = record.publishedByUserId
        model.published_by_name = record.publishedByName
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)
        model.published_at = self._coerce_datetime(record.publishedAt) if record.publishedAt else None

    def _apply_application_step_record(self, model: ApplicationStepModel, record: ApplicationStepRecord) -> None:
        model.application_id = record.applicationId
        model.version_label = record.versionLabel
        model.step_order = int(record.stepOrder or 0)
        model.kind = record.kind
        model.skill_id = record.skillId
        model.skill_version = record.skillVersion
        model.skill_name = record.skillName
        model.source_task_id = record.sourceTaskId
        model.source_document_id = record.sourceDocumentId
        model.source_page_no = record.sourcePageNo
        model.source_run_id = record.sourceRunId
        model.source_status = record.sourceStatus
        model.run_purpose = record.runPurpose
        model.operation_type = record.operationType
        model.result_mode = record.resultMode
        model.skill_snapshot_json = self._dumps_json(record.skillSnapshot) or "{}"
        model.config_snapshot_json = self._dumps_json(record.configSnapshot) or "{}"
        model.prompt_snapshot = record.promptSnapshot
        model.input_mapping_json = self._dumps_json(record.inputMapping) or "{}"
        model.target_mapping_json = self._dumps_json(record.targetMapping) or "{}"
        model.dependency_refs_json = self._dumps_json(record.dependencyRefs) or "{}"
        model.output_summary_json = self._dumps_json(record.outputSummary) or "{}"
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_application_run_record(self, model: ApplicationRunModel, record: ApplicationRunRecord) -> None:
        model.application_id = record.applicationId
        model.customer_id = record.customerId
        model.task_id = record.taskId
        model.document_id = record.documentId
        model.version = record.version
        model.status = record.status
        model.step_count = int(record.stepCount or 0)
        model.completed_step_count = int(record.completedStepCount or 0)
        model.triggered_by_user_id = record.triggeredByUserId
        model.triggered_by_name = record.triggeredByName
        model.error_message = record.errorMessage
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_application_run_step_record(
        self,
        model: ApplicationRunStepModel,
        record: ApplicationRunStepRecord,
    ) -> None:
        model.application_run_id = record.applicationRunId
        model.application_id = record.applicationId
        model.version = record.version
        model.step_order = int(record.stepOrder or 0)
        model.kind = record.kind
        model.skill_id = record.skillId
        model.skill_version = record.skillVersion
        model.skill_name = record.skillName
        model.source_application_step_id = record.sourceApplicationStepId
        model.source_page_no = record.sourcePageNo
        model.source_run_id = record.sourceRunId
        model.execution_run_id = record.executionRunId
        model.status = record.status
        model.input_mapping_json = self._dumps_json(record.inputMapping) or "{}"
        model.target_mapping_json = self._dumps_json(record.targetMapping) or "{}"
        model.config_snapshot_json = self._dumps_json(record.configSnapshot) or "{}"
        model.prompt_snapshot = record.promptSnapshot
        model.output_summary_json = self._dumps_json(record.outputSummary) or "{}"
        model.error_message = record.errorMessage
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_application_workshop_step_draft(
        self,
        model: ApplicationWorkshopStepDraftModel,
        payload: ApplicationWorkshopStepDraftUpsertRequest,
        *,
        task: TaskRecord,
        user_id: str | None,
        updated_at: datetime,
    ) -> None:
        model.task_id = task.id
        model.customer_id = task.customerId
        model.document_id = task.documentId
        model.kind = payload.kind
        model.status = payload.status
        model.data_type_name = payload.dataTypeName[:255]
        model.goal = payload.goal
        model.expected_output = payload.expectedOutput
        model.source_title = payload.sourceTitle
        model.source_scope = payload.sourceScope
        model.skill_text = payload.skillText
        model.skill_name = payload.skillName[:255]
        model.errors_json = self._dumps_json(payload.errors) or "[]"
        model.model = payload.model[:128]
        sample_source = dict(payload.sampleSource or {})
        if payload.semanticLocator:
            sample_source["locator"] = payload.semanticLocator
        if payload.skillDevelopment:
            sample_source["skillDevelopment"] = payload.skillDevelopment
        model.sample_source_json = self._dumps_json(sample_source) or "{}"
        model.sample_extraction_json = self._dumps_json(payload.sampleExtraction or {}) or "{}"
        model.sample_processing_json = self._dumps_json(payload.sampleProcessing or {}) or "{}"
        model.run_option_json = self._dumps_json(payload.runOption or {}) or "{}"
        model.updated_by_user_id = user_id
        model.updated_at = updated_at

    def _apply_prompt_run_record(self, model: PromptRunModel, record: PromptRunRecord) -> None:
        model.task_id = record.taskId
        model.document_id = record.documentId
        model.run_type = record.runType
        model.run_name = record.runName
        model.prompt_name = record.promptName
        model.prompt_text = record.promptText
        model.start_page_no = record.startPageNo
        model.end_page_no = record.endPageNo
        model.status = record.status
        model.run_phase = record.runPhase or ("model_processing" if record.status == "running" else record.status)
        model.run_purpose = record.runPurpose
        model.prompt_config_id = record.promptConfigId
        model.template_id = record.templateId
        model.schema_template_name = record.schemaTemplateName
        model.schema_template_version = record.schemaTemplateVersion
        model.llm_provider = record.llmProvider
        model.llm_model = record.llmModel
        model.error_message = record.errorMessage
        model.input_path = record.inputPath
        model.output_path = record.outputPath
        model.output_text = record.outputText
        model.input_facts_snapshot_json = self._dumps_json(record.inputFactsSnapshot)
        model.schema_definition_json = self._dumps_json(record.schemaDefinition)
        model.schema_output_json = self._dumps_json(record.schemaOutput)
        model.validation_errors_json = self._dumps_json(list(record.validationErrors or []))
        # Completed extraction/process/business outputs are the durable source of truth.
        # Artifacts may exist for replay/debug, but task/application detail must be able
        # to reconstruct result views from MySQL alone.
        model.structured_extraction_result_json = self._dumps_json(record.structuredExtractionResult)
        model.structured_process_result_json = self._dumps_json(record.structuredProcessResult)
        model.structured_business_result_json = self._dumps_json(record.structuredBusinessResult)
        model.evidence_block_ids_json = self._dumps_json(list(record.evidenceBlockIds or []))
        model.evidence_excerpts_json = self._dumps_json(list(record.evidenceExcerpts or []))
        model.phase_started_at = self._coerce_datetime(record.phaseStartedAt) if record.phaseStartedAt else None
        model.last_heartbeat_at = self._coerce_datetime(record.lastHeartbeatAt) if record.lastHeartbeatAt else None
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_llm_call_trace_record(self, model: LlmCallTraceModel, record: LlmCallTraceRecord) -> None:
        model.task_id = record.taskId
        model.document_id = record.documentId
        model.run_id = record.runId
        model.stage = record.stage
        model.request_kind = record.requestKind
        model.status = record.status
        model.run_phase = record.runPhase
        model.provider = record.provider
        model.model = record.model
        model.skill_id = record.skillId
        model.input_chars = int(record.inputChars or 0)
        model.output_chars = int(record.outputChars or 0)
        model.prompt_tokens = record.promptTokens
        model.completion_tokens = record.completionTokens
        model.total_tokens = record.totalTokens
        model.http_ms = record.httpMs
        model.total_ms = record.totalMs
        model.error_type = record.errorType
        model.request_object_key = record.requestObjectKey
        model.response_object_key = record.responseObjectKey
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_result_artifact_record(self, model: TaskResultArtifactModel, record: TaskResultArtifactRecord) -> None:
        model.task_id = record.taskId
        model.document_id = record.documentId
        model.page_no = record.pageNo
        model.run_id = record.runId
        model.stage = record.stage
        model.artifact_kind = record.artifactKind
        model.object_key = record.objectKey
        model.content_hash = record.contentHash
        model.size_bytes = int(record.sizeBytes or 0)
        model.content_type = record.contentType
        model.summary_json = self._dumps_json(record.summary)
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_operation_target_record(
        self,
        model: TaskOperationTargetModel,
        record: TaskOperationTargetRecord,
    ) -> None:
        model.task_id = record.taskId
        model.page_no = record.pageNo
        model.target_id = record.targetId
        model.source_run_id = record.sourceRunId
        model.target_type = record.targetType
        model.label = record.label
        model.value_text = record.valueText
        model.excerpt = record.excerpt
        model.block_position = record.blockPosition
        model.field_key = record.fieldKey
        model.row_index = record.rowIndex
        model.row_count = record.rowCount
        model.column_count = record.columnCount
        model.headers_json = self._dumps_json(list(record.headers or [])) or "[]"
        model.block_ids_json = self._dumps_json(list(record.blockIds or [])) or "[]"
        model.group_label = record.groupLabel
        model.data_object_key = record.dataObjectKey
        model.data_content_hash = record.dataContentHash
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_schema_template_record(self, model: SchemaTemplateModel, record: SchemaTemplateRecord) -> None:
        model.name = record.name
        model.description = record.description
        model.document_type = record.documentType
        model.scope = record.scope
        model.instructions = record.instructions
        model.schema_definition_json = self._dumps_json(record.schemaDefinition)
        model.binding_config_json = self._dumps_json(record.bindingConfig)
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_business_skill_record(self, model: BusinessSkillModel, record: BusinessSkillRecord) -> None:
        model.skill_id = record.id
        model.version = record.version
        model.name = record.name
        model.category = record.category
        model.customer_id = record.customerId
        model.enabled = bool(record.enabled)
        model.status = record.status or ("active" if record.enabled else "disabled")
        model.tags_json = self._dumps_json(list(record.tags or [])) or "[]"
        model.source_types_json = self._dumps_json(list(record.sourceTypes or [])) or "[]"
        model.target_types_json = self._dumps_json(record.targetTypes)
        model.executor = record.executor
        model.result_kind = record.resultKind
        model.renderer = record.renderer
        model.config_schema_json = self._dumps_json(record.configSchema)
        model.output_schema_json = self._dumps_json(record.outputSchema)
        model.prompt_template = record.promptTemplate
        model.examples_json = self._dumps_json(record.examples)
        defaults = dict(record.defaults or {})
        defaults.pop("_skillText", None)
        model.defaults_json = self._dumps_json(defaults)
        model.skill_text_object_key = record.skillTextObjectKey or None
        model.skill_text_hash = record.skillTextHash or None
        model.skill_text_size_bytes = int(record.skillTextSizeBytes or 0)
        model.skill_text_preview = record.skillTextPreview or None
        model.latest_test_status = record.latestTestStatus
        model.sample_count = int(record.sampleCount or 0)
        model.test_run_count = int(record.testRunCount or 0)
        model.last_tested_at = self._coerce_datetime(record.lastTestedAt) if record.lastTestedAt else None
        model.created_by = record.createdBy
        model.updated_by = record.updatedBy
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_skill_sample_record(self, model: SkillSampleModel, record: SkillSampleRecord) -> None:
        model.kind = record.kind
        model.skill_id = record.skillId
        model.version = record.version
        model.customer_id = record.customerId
        model.instruction = record.instruction
        model.object_key = record.objectKey
        model.content_type = record.contentType
        model.file_name = record.fileName
        model.size_bytes = int(record.sizeBytes or 0)
        model.preview = record.preview
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    def _apply_skill_test_run_record(self, model: SkillTestRunModel, record: SkillTestRunRecord) -> None:
        model.kind = record.kind
        model.skill_id = record.skillId
        model.version = record.version
        model.customer_id = record.customerId
        model.sample_id = record.sampleId
        model.status = record.status
        model.valid = bool(record.valid)
        model.errors_json = self._dumps_json(list(record.errors or [])) or "[]"
        model.summary_json = self._dumps_json(record.summary)
        model.input_object_key = record.inputObjectKey
        model.result_object_key = record.resultObjectKey
        model.facts_object_key = record.factsObjectKey
        model.llm_object_key = record.llmObjectKey
        model.result_json = self._dumps_json(record.result)
        model.facts_json = self._dumps_json(record.facts)
        model.provider = record.provider
        model.model = record.model
        model.duration_ms = record.durationMs
        model.input_chars = int(record.inputChars or 0)
        model.output_chars = int(record.outputChars or 0)
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    @staticmethod
    def _business_skill_storage_id(record: BusinessSkillRecord) -> str:
        scope = record.customerId or "platform"
        return f"{scope}:{record.id}:{record.version}"[:191]

    def _refresh_skill_stats(self, session, *, kind: str, skill_id: str, customer_id: str | None) -> None:
        skill_statement = select(BusinessSkillModel).where(BusinessSkillModel.skill_id == skill_id)
        if kind == "extraction":
            skill_statement = skill_statement.where(BusinessSkillModel.category == "extraction")
        else:
            skill_statement = skill_statement.where(BusinessSkillModel.category != "extraction")
        if customer_id is None:
            skill_statement = skill_statement.where(BusinessSkillModel.customer_id.is_(None))
        else:
            skill_statement = skill_statement.where(BusinessSkillModel.customer_id == customer_id)
        skills = session.execute(skill_statement).scalars().all()
        if not skills:
            return

        sample_statement = select(SkillSampleModel).where(SkillSampleModel.kind == kind).where(SkillSampleModel.skill_id == skill_id)
        run_statement = select(SkillTestRunModel).where(SkillTestRunModel.kind == kind).where(SkillTestRunModel.skill_id == skill_id)
        if customer_id is None:
            sample_statement = sample_statement.where(SkillSampleModel.customer_id.is_(None))
            run_statement = run_statement.where(SkillTestRunModel.customer_id.is_(None))
        else:
            sample_statement = sample_statement.where(SkillSampleModel.customer_id == customer_id)
            run_statement = run_statement.where(SkillTestRunModel.customer_id == customer_id)
        samples = session.execute(sample_statement).scalars().all()
        runs = session.execute(run_statement.order_by(SkillTestRunModel.updated_at.desc())).scalars().all()
        latest_run = runs[0] if runs else None
        now = self._now_dt()
        for skill in skills:
            skill.sample_count = len(samples)
            skill.test_run_count = len(runs)
            skill.latest_test_status = latest_run.status if latest_run else None
            skill.last_tested_at = latest_run.updated_at if latest_run else None
            skill.updated_at = now

    def _apply_parse_job_record(self, model: ParseJobModel, record: ParseJobRecord) -> None:
        model.customer_id = record.customerId
        model.document_id = record.documentId
        model.state = record.state
        model.mineru_state = record.mineruState
        model.mineru_task_id = record.mineruTaskId
        model.error_message = record.errorMessage
        model.extracted_pages = record.extractedPages
        model.total_pages = record.totalPages
        model.start_time = self._coerce_datetime(record.startTime) if record.startTime else None
        model.full_zip_source_url = record.fullZipSourceUrl
        model.full_zip_path = record.fullZipPath
        model.markdown_path = record.markdownPath
        model.raw_json_path = record.rawJsonPath
        model.layout_path = record.layoutPath
        model.block_list_path = record.blockListPath
        model.model_json_path = record.modelJsonPath
        model.created_at = self._coerce_datetime(record.createdAt)
        model.updated_at = self._coerce_datetime(record.updatedAt)

    @staticmethod
    def _now_dt() -> datetime:
        return datetime.now(timezone.utc)

    def _format_ts(self, value: datetime | None) -> str:
        if value is None:
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    def _coerce_datetime(self, value: str | datetime | None) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not value:
            return self._now_dt()

        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return self._now_dt()

    def _normalize_task_status(self, state: str) -> str:
        if state == "done":
            return "completed"
        if state == "converting":
            return "running"
        if state in {"pending", "running", "completed", "failed", "needs_review"}:
            return state
        return "pending"

    def _build_task_summary_text(self, job: ParseJobRecord) -> str:
        if job.state == "failed":
            return job.errorMessage or "文档解析失败，请重新上传或联系管理员处理。"
        if job.state == "completed":
            if job.totalPages:
                return f"文档解析完成，共 {job.totalPages} 页，可直接进入任务查看结果。"
            return "文档解析完成，可直接进入任务查看结果。"
        if job.extractedPages and job.totalPages:
            return f"文档正在解析中，当前进度 {job.extractedPages}/{job.totalPages} 页。"
        return "文档已上传，系统正在排队解析。"

    def _present_task_summary_text(self, record: TaskRecord) -> str:
        summary = (record.summary or "").strip()
        if summary == "文档已登记，等待 OSS 文件进入后续解析链路。":
            return "文档已上传，系统正在准备解析。"
        if summary == "文档已进入解析流程。":
            return "文档已上传，系统正在排队解析。"
        if summary == "解析结果已保存，可直接用于识别内容展示与后续分页处理。":
            if record.pageCount:
                return f"文档解析完成，共 {record.pageCount} 页，可直接进入任务查看结果。"
            return "文档解析完成，可直接进入任务查看结果。"
        return summary

    def _get_prompt_run_scope_key(self, run: PromptRunRecord) -> str:
        return ":".join(
            [
                run.runType,
                str(run.startPageNo),
                str(run.endPageNo),
                run.runPurpose,
                run.templateId or "",
                run.promptName,
            ]
        )

    def _get_latest_effective_prompt_runs(self, runs: list[PromptRunRecord]) -> list[PromptRunRecord]:
        sorted_runs = sorted(runs, key=lambda item: item.updatedAt, reverse=True)
        seen_keys: set[str] = set()
        effective_runs: list[PromptRunRecord] = []
        for run in sorted_runs:
            scope_key = self._get_prompt_run_scope_key(run)
            if scope_key in seen_keys:
                continue
            seen_keys.add(scope_key)
            effective_runs.append(run)
        return effective_runs

    def _aggregate_prompt_status(self, runs: list[PromptRunRecord]) -> str:
        effective_runs = self._get_latest_effective_prompt_runs(runs)
        if any(item.status == "running" for item in effective_runs):
            return "running"
        if any(item.status == "failed" for item in effective_runs):
            return "failed"
        if any(item.status == "needs_review" for item in effective_runs):
            return "needs_review"
        if effective_runs and all(item.status == "completed" for item in effective_runs):
            return "completed"
        return "pending"

    def _resolve_task_parse_status(
        self,
        task: TaskRecord,
        document: DocumentRecord,
        parse_job: ParseJobRecord,
    ) -> str:
        if parse_job.state:
            return self._normalize_task_status(parse_job.state)
        if document.parseStatus:
            return self._normalize_task_status(document.parseStatus)
        return self._normalize_task_status(task.status)

    def _read_json_artifact_from_path_required(self, relative_path: str, *, task_id: str, field_name: str):
        absolute_path = self.resolve_artifact_absolute_path(relative_path)
        if absolute_path is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {task_id} artifact {field_name} path is empty",
            )
        try:
            return json.loads(absolute_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {task_id} artifact {field_name} not found: {relative_path}",
            ) from error
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {task_id} artifact {field_name} is not valid JSON: {relative_path}",
            ) from error

    def _artifact_path_exists(self, relative_path: str | None) -> bool:
        absolute_path = self.resolve_artifact_absolute_path(relative_path)
        return absolute_path is not None and absolute_path.exists()

    def _read_json_artifact_from_url_required(self, artifact_url: str, *, task_id: str, field_name: str):
        parsed = urlparse(artifact_url)
        route_path = parsed.path or artifact_url

        if route_path.startswith("/sample-doc/"):
            return self._read_json_artifact_from_path_required(route_path, task_id=task_id, field_name=field_name)

        match = re.match(rf"^{re.escape(self._settings.api_prefix)}/tasks/([^/]+)/artifacts/(.+)$", route_path)
        if match:
            artifact_task_id, artifact_path = match.groups()
            try:
                target = self._store.resolve_artifact_path(artifact_task_id, artifact_path)
                return json.loads(target.read_text(encoding="utf-8"))
            except FileNotFoundError as error:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Task {task_id} artifact {field_name} not found via server url: {artifact_url}",
                ) from error
            except json.JSONDecodeError as error:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Task {task_id} artifact {field_name} is not valid JSON via server url: {artifact_url}",
                ) from error

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task {task_id} artifact {field_name} server url is unsupported: {artifact_url}",
        )

    def _read_json_artifact_required(
        self,
        *,
        artifact_url: str | None,
        artifact_path: str | None,
        task_id: str,
        field_name: str,
    ):
        if artifact_url:
            return self._read_json_artifact_from_url_required(artifact_url, task_id=task_id, field_name=field_name)
        if artifact_path:
            return self._read_json_artifact_from_path_required(artifact_path, task_id=task_id, field_name=field_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task {task_id} artifact {field_name} is empty",
        )

    def _download_remote_bundle_required(self, full_zip_url: str, *, task_id: str) -> bytes:
        request = Request(full_zip_url, headers={"User-Agent": "idp-poc-backend/1.0"})
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=120, context=_build_ssl_context()) as response:
                    return response.read()
            except Exception as error:
                last_error = error
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task {task_id} fullZipSourceUrl download failed: {full_zip_url}",
        ) from last_error

    @staticmethod
    def _find_bundle_member_name(
        archive: zipfile.ZipFile,
        *,
        exact_names: set[str],
        suffix: str | None = None,
    ) -> str | None:
        for member_name in archive.namelist():
            if member_name.endswith("/"):
                continue
            base_name = Path(member_name).name
            if base_name in exact_names:
                return member_name
            if suffix and base_name.endswith(suffix):
                return member_name
        return None

    def _read_json_member_from_bundle_required(
        self,
        archive: zipfile.ZipFile,
        *,
        task_id: str,
        full_zip_url: str,
        field_name: str,
        exact_names: set[str],
        suffix: str | None = None,
    ):
        member_name = self._find_bundle_member_name(archive, exact_names=exact_names, suffix=suffix)
        if member_name is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {task_id} artifact {field_name} not found in fullZipSourceUrl: {full_zip_url}",
            )
        try:
            with archive.open(member_name) as fp:
                return json.loads(fp.read().decode("utf-8"))
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {task_id} artifact {field_name} is not valid JSON in fullZipSourceUrl: {full_zip_url}",
            ) from error

    def _read_runtime_artifacts_from_full_zip_required(
        self,
        *,
        full_zip_url: str,
        task_id: str,
    ) -> tuple[object, object | None]:
        bundle = self._download_remote_bundle_required(full_zip_url, task_id=task_id)
        with zipfile.ZipFile(BytesIO(bundle)) as archive:
            content_items = self._read_json_member_from_bundle_required(
                archive,
                task_id=task_id,
                full_zip_url=full_zip_url,
                field_name="content_list_v2.json",
                exact_names={"content_list_v2.json"},
                suffix="_content_list_v2.json",
            )
            block_payload = None
            model_payload = None
            for exact_names, suffix in (
                ({"layout.json", "middle.json"}, None),
                ({"block_list.json"}, None),
            ):
                member_name = self._find_bundle_member_name(archive, exact_names=exact_names, suffix=suffix)
                if member_name is None:
                    continue
                try:
                    with archive.open(member_name) as fp:
                        block_payload = json.loads(fp.read().decode("utf-8"))
                    break
                except json.JSONDecodeError as error:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=(
                            f"Task {task_id} layout/block/model artifact is not valid JSON in "
                            f"fullZipSourceUrl: {full_zip_url}"
                        ),
                    ) from error
            model_member_name = self._find_bundle_member_name(
                archive,
                exact_names={"model.json"},
                suffix="_model.json",
            )
            if model_member_name is not None:
                try:
                    with archive.open(model_member_name) as fp:
                        model_payload = json.loads(fp.read().decode("utf-8"))
                except json.JSONDecodeError as error:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=(
                            f"Task {task_id} model artifact is not valid JSON in "
                            f"fullZipSourceUrl: {full_zip_url}"
                        ),
                    ) from error
            block_payload = _attach_model_payload(block_payload, model_payload)
            return content_items, block_payload

    def _read_runtime_artifacts_from_local_full_zip_required(
        self,
        *,
        full_zip_path: str,
        task_id: str,
    ) -> tuple[object, object | None]:
        absolute_path = self.resolve_artifact_absolute_path(full_zip_path)
        if absolute_path is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {task_id} fullZipPath is empty",
            )
        try:
            with zipfile.ZipFile(absolute_path) as archive:
                content_items = self._read_json_member_from_bundle_required(
                    archive,
                    task_id=task_id,
                    full_zip_url=full_zip_path,
                    field_name="content_list_v2.json",
                    exact_names={"content_list_v2.json"},
                    suffix="_content_list_v2.json",
                )
                block_payload = None
                model_payload = None
                for exact_names, suffix in (
                    ({"layout.json", "middle.json"}, None),
                    ({"block_list.json"}, None),
                ):
                    member_name = self._find_bundle_member_name(archive, exact_names=exact_names, suffix=suffix)
                    if member_name is None:
                        continue
                    try:
                        with archive.open(member_name) as fp:
                            block_payload = json.loads(fp.read().decode("utf-8"))
                        break
                    except json.JSONDecodeError as error:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=(
                                f"Task {task_id} layout/block/model artifact is not valid JSON in "
                                f"fullZipPath: {full_zip_path}"
                            ),
                        ) from error
                model_member_name = self._find_bundle_member_name(
                    archive,
                    exact_names={"model.json"},
                    suffix="_model.json",
                )
                if model_member_name is not None:
                    try:
                        with archive.open(model_member_name) as fp:
                            model_payload = json.loads(fp.read().decode("utf-8"))
                    except json.JSONDecodeError as error:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=(
                                f"Task {task_id} model artifact is not valid JSON in "
                                f"fullZipPath: {full_zip_path}"
                            ),
                        ) from error
                block_payload = _attach_model_payload(block_payload, model_payload)
                return content_items, block_payload
        except FileNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {task_id} fullZipPath not found: {full_zip_path}",
            ) from error

    def _build_runtime_pages(self, *, document: DocumentRecord, parse_job: ParseJobRecord) -> list[WorkbenchPageDetail]:
        persisted_pages = self._load_page_recognition_snapshots(parse_job.taskId)
        if persisted_pages and _pages_use_content_list_v2(persisted_pages):
            return persisted_pages

        normalized_state = self._normalize_task_status(parse_job.state)
        local_content_path = parse_job.rawJsonPath if _is_content_list_v2_ref(parse_job.rawJsonPath) else None
        local_block_path = parse_job.layoutPath or parse_job.blockListPath or parse_job.modelJsonPath
        if local_content_path and self._artifact_path_exists(local_content_path):
            content_items = self._read_json_artifact_from_path_required(
                local_content_path,
                task_id=parse_job.taskId,
                field_name="rawJsonPath",
            )
            block_payload = (
                self._read_json_artifact_from_path_required(
                    local_block_path,
                    task_id=parse_job.taskId,
                    field_name="layoutPath/blockListPath/modelJsonPath",
                )
                if local_block_path and self._artifact_path_exists(local_block_path)
                else None
            )
            if (
                parse_job.modelJsonPath
                and parse_job.modelJsonPath != local_block_path
                and self._artifact_path_exists(parse_job.modelJsonPath)
            ):
                model_payload = self._read_json_artifact_from_path_required(
                    parse_job.modelJsonPath,
                    task_id=parse_job.taskId,
                    field_name="modelJsonPath",
                )
                block_payload = _attach_model_payload(block_payload, model_payload)
            return build_pages_from_artifacts(content_items, block_payload)
        if parse_job.fullZipPath and self._artifact_path_exists(parse_job.fullZipPath):
            content_items, block_payload = self._read_runtime_artifacts_from_local_full_zip_required(
                full_zip_path=parse_job.fullZipPath,
                task_id=parse_job.taskId,
            )
            return build_pages_from_artifacts(content_items, block_payload)
        full_zip_source_error: HTTPException | None = None
        if parse_job.fullZipSourceUrl:
            try:
                content_items, block_payload = self._read_runtime_artifacts_from_full_zip_required(
                    full_zip_url=parse_job.fullZipSourceUrl,
                    task_id=parse_job.taskId,
                )
                return build_pages_from_artifacts(content_items, block_payload)
            except HTTPException as error:
                full_zip_source_error = error
                if not document.rawJsonUrl:
                    raise
        if not document.rawJsonUrl and not local_content_path:
            if full_zip_source_error is not None:
                raise full_zip_source_error
            if normalized_state == "completed":
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Task {parse_job.taskId} completed parse_job is missing content_list_v2 rawJsonUrl/rawJsonPath",
                )
            return []
        if document.rawJsonUrl and not _is_content_list_v2_ref(document.rawJsonUrl):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task {parse_job.taskId} rawJsonUrl must point to content_list_v2.json",
            )
        content_items = self._read_json_artifact_required(
            artifact_url=document.rawJsonUrl,
            artifact_path=None,
            task_id=parse_job.taskId,
            field_name="rawJsonUrl/rawJsonPath",
        )
        block_artifact_url = document.layoutUrl or document.blockListUrl or document.modelJsonUrl
        block_payload = (
            self._read_json_artifact_required(
                artifact_url=block_artifact_url,
                artifact_path=None,
                task_id=parse_job.taskId,
                field_name="layoutUrl/blockListUrl/modelJsonUrl/layoutPath/blockListPath/modelJsonPath",
            )
            if block_artifact_url
            else None
        )
        if document.modelJsonUrl and document.modelJsonUrl != block_artifact_url:
            model_payload = self._read_json_artifact_required(
                artifact_url=document.modelJsonUrl,
                artifact_path=None,
                task_id=parse_job.taskId,
                field_name="modelJsonUrl",
            )
            block_payload = _attach_model_payload(block_payload, model_payload)
        return build_pages_from_artifacts(content_items, block_payload)

    def _load_page_recognition_snapshots(self, task_id: str) -> list[WorkbenchPageDetail]:
        try:
            artifacts = self.list_result_artifacts(
                task_id,
                artifactKind="page_recognition",
                stage="recognition",
            )
        except HTTPException as error:
            if error.status_code == status.HTTP_404_NOT_FOUND:
                return []
            raise
        latest_by_page: dict[int, TaskResultArtifactRecord] = {}
        for artifact in artifacts:
            if artifact.pageNo is None or artifact.pageNo in latest_by_page:
                continue
            latest_by_page[artifact.pageNo] = artifact
        if not latest_by_page:
            return []

        pages: list[WorkbenchPageDetail] = []
        for artifact in sorted(latest_by_page.values(), key=lambda item: item.pageNo or 0):
            payload = self._read_json_object(artifact.objectKey)
            if not isinstance(payload, dict):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Task {task_id} page recognition artifact is not a JSON object",
                )
            pages.append(WorkbenchPageDetail.model_validate(payload))
        return pages

    def _write_json_object(self, object_key: str, payload):
        if not self._oss_service:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OSS service is required to persist task result artifacts",
            )
        return write_json_artifact(
            oss_service=self._oss_service,
            object_key=object_key,
            payload=payload,
        )

    def _read_json_object(self, object_key: str | None):
        if not object_key:
            return None
        if not self._oss_service:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OSS service is required to read task result artifacts",
            )
        try:
            text = self._oss_service.read_text_object(objectKey=object_key, maxBytes=20_000_000)
            return load_json_payload(text)
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task result artifact cannot be read from OSS: {object_key}",
            ) from error

    @staticmethod
    def _operation_target_storage_id(task_id: str, target_id: str) -> str:
        return f"{task_id}:{target_id}"[:191]

    @staticmethod
    def _dumps_json(value) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _loads_json_list(value: str | None, *, field_name: str) -> list[str]:
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{field_name} is null in database",
            )
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{field_name} is not valid JSON in database; value may be truncated by column size",
            ) from error
        if not isinstance(parsed, list):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{field_name} must be a JSON array in database",
            )
        return [str(item) for item in parsed if str(item).strip()]

    @staticmethod
    def _loads_json_dict(value: str | None, *, field_name: str) -> dict | None:
        if not value:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{field_name} is not valid JSON in database",
            ) from error
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{field_name} must be a JSON object in database",
            )
        return parsed

    def _load_prompt_run_output_payload(self, model: PromptRunModel) -> dict | None:
        if not model.output_path:
            return None
        try:
            payload = self._store.read_json_artifact(model.output_path)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def _load_run_artifact_payload_optional(self, task_id: str, run_id: str, artifact_kind: str) -> dict | None:
        try:
            payload = self._load_run_artifact_payload(task_id, run_id, artifact_kind)
        except HTTPException as error:
            if error.status_code < status.HTTP_500_INTERNAL_SERVER_ERROR:
                raise
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _pick_structured_process_result(payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get("structuredProcessResult")
        if isinstance(value, dict):
            return value
        if "resultKind" in payload or "outputPayload" in payload:
            return payload
        return None

    @staticmethod
    def _pick_structured_extraction_result(payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return None
        for key in ("structuredExtractionResult", "extractionResult"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        if isinstance(payload.get("outputs"), list):
            return payload
        return None

    @staticmethod
    def _pick_structured_business_result(payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get("structuredBusinessResult")
        return value if isinstance(value, dict) else None

    def _load_structured_process_result(self, model: PromptRunModel) -> dict | None:
        if model.structured_process_result_json:
            return self._loads_json_dict(
                model.structured_process_result_json,
                field_name="prompt_runs.structured_process_result_json",
            )
        artifact_payload = self._load_run_artifact_payload_optional(model.task_id, model.id, "process_result")
        value = self._pick_structured_process_result(artifact_payload)
        if isinstance(value, dict):
            return value
        artifact_payload = self._load_run_artifact_payload_optional(model.task_id, model.id, "parse_result")
        value = self._pick_structured_process_result(artifact_payload)
        if isinstance(value, dict):
            return value
        value = self._pick_structured_process_result(self._load_prompt_run_output_payload(model))
        if isinstance(value, dict):
            return value
        return None

    def _load_structured_extraction_result(self, model: PromptRunModel) -> dict | None:
        if model.structured_extraction_result_json:
            return self._loads_json_dict(
                model.structured_extraction_result_json,
                field_name="prompt_runs.structured_extraction_result_json",
            )
        artifact_payload = self._load_run_artifact_payload_optional(model.task_id, model.id, "parse_result")
        value = self._pick_structured_extraction_result(artifact_payload)
        if isinstance(value, dict):
            return value
        value = self._pick_structured_extraction_result(self._load_prompt_run_output_payload(model))
        if isinstance(value, dict):
            return value
        return None

    def _load_structured_business_result(self, model: PromptRunModel) -> dict | None:
        if model.structured_business_result_json:
            return self._loads_json_dict(
                model.structured_business_result_json,
                field_name="prompt_runs.structured_business_result_json",
            )
        for artifact_kind in ("parse_result", "process_result"):
            value = self._pick_structured_business_result(
                self._load_run_artifact_payload_optional(model.task_id, model.id, artifact_kind)
            )
            if isinstance(value, dict):
                return value
        value = self._pick_structured_business_result(self._load_prompt_run_output_payload(model))
        if isinstance(value, dict):
            return value
        return None

    def _load_run_artifact_payload(self, task_id: str, run_id: str, artifact_kind: str):
        with session_scope() as session:
            model = session.execute(
                select(TaskResultArtifactModel)
                .where(
                    TaskResultArtifactModel.task_id == task_id,
                    TaskResultArtifactModel.run_id == run_id,
                    TaskResultArtifactModel.artifact_kind == artifact_kind,
                )
                .order_by(TaskResultArtifactModel.updated_at.desc())
                .limit(1)
            ).scalars().first()
            object_key = model.object_key if model else None
        return self._read_json_object(object_key) if object_key else None


def _build_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()
