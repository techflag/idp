"""Schema template CRUD APIs."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user, get_repository
from app.domain.models import SchemaTemplateRecord
from app.repositories.protocols import WorkbenchRepository
from app.schemas.workbench import (
    SchemaFieldDefinition,
    SchemaTemplateDetail,
    SchemaTemplateSummary,
    SchemaTemplateUpsertRequest,
)
from app.services.auth import SessionUser

router = APIRouter(tags=["schema-templates"])


def _count_schema_fields(fields: list[dict]) -> int:
    total = 0
    for field in fields:
        if not isinstance(field, dict):
            continue
        total += 1
        children = field.get("children")
        if isinstance(children, list):
            total += _count_schema_fields(children)
        item_schema = field.get("itemSchema")
        if isinstance(item_schema, dict):
            total += _count_schema_fields([item_schema])
    return total


def _to_template_summary(record: SchemaTemplateRecord) -> SchemaTemplateSummary:
    fields = record.schemaDefinition.get("fields") if isinstance(record.schemaDefinition, dict) else []
    return SchemaTemplateSummary(
        id=record.id,
        name=record.name,
        description=record.description,
        documentType=record.documentType,
        scope="page",
        fieldCount=_count_schema_fields(fields if isinstance(fields, list) else []),
        updatedAt=record.updatedAt,
    )


def _to_template_detail(record: SchemaTemplateRecord) -> SchemaTemplateDetail:
    fields = record.schemaDefinition.get("fields") if isinstance(record.schemaDefinition, dict) else []
    return SchemaTemplateDetail(
        **_to_template_summary(record).model_dump(),
        schemaDefinition=[SchemaFieldDefinition.model_validate(item) for item in fields if isinstance(item, dict)],
        instructions=record.instructions,
        bindingConfig=record.bindingConfig,
    )


@router.get("/schema-templates", response_model=list[SchemaTemplateSummary])
def list_schema_templates(
    _: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> list[SchemaTemplateSummary]:
    return [_to_template_summary(record) for record in repository.list_schema_templates()]


@router.post("/schema-templates", response_model=SchemaTemplateDetail)
def create_schema_template(
    payload: SchemaTemplateUpsertRequest,
    _: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SchemaTemplateDetail:
    record = SchemaTemplateRecord(
        id=f"schema-template-{uuid4().hex[:10]}",
        name=payload.name,
        description=payload.description,
        documentType=payload.documentType,
        scope=payload.scope,
        schemaDefinition={"fields": [item.model_dump() for item in payload.schemaDefinition]},
        instructions=payload.instructions,
        bindingConfig=payload.bindingConfig,
    )
    return _to_template_detail(repository.save_schema_template(record))


@router.get("/schema-templates/{templateId}", response_model=SchemaTemplateDetail)
def get_schema_template(
    templateId: str,
    _: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SchemaTemplateDetail:
    return _to_template_detail(repository.get_schema_template(templateId))


@router.patch("/schema-templates/{templateId}", response_model=SchemaTemplateDetail)
def update_schema_template(
    templateId: str,
    payload: SchemaTemplateUpsertRequest,
    _: SessionUser = Depends(get_current_user),
    repository: WorkbenchRepository = Depends(get_repository),
) -> SchemaTemplateDetail:
    current = repository.get_schema_template(templateId)
    updated = SchemaTemplateRecord(
        id=current.id,
        name=payload.name,
        description=payload.description,
        documentType=payload.documentType,
        scope=payload.scope,
        schemaDefinition={"fields": [item.model_dump() for item in payload.schemaDefinition]},
        instructions=payload.instructions,
        bindingConfig=payload.bindingConfig,
        createdAt=current.createdAt,
    )
    return _to_template_detail(repository.save_schema_template(updated))
