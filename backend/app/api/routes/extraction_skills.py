"""Extraction skill registry APIs."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import ensure_customer_access, get_current_user, get_extraction_skill_registry
from app.schemas.workbench import ExtractionSkillDetail, ExtractionSkillUpsertRequest
from app.services.auth import SessionUser
from app.services.extraction_skills import ExtractionSkillRegistry
from app.services.skill_assist_service import ensure_extraction_skill_semantic_governance

router = APIRouter(tags=["extraction-skills"])


@router.get("/extraction-skills", response_model=list[ExtractionSkillDetail])
def list_extraction_skills(
    customerId: Optional[str] = Query(None),
    current_user: SessionUser = Depends(get_current_user),
    registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> list[ExtractionSkillDetail]:
    if customerId:
        ensure_customer_access(customerId, current_user)
    return registry.list_skills(customer_id=customerId)


@router.post("/extraction-skills", response_model=ExtractionSkillDetail)
def create_extraction_skill(
    payload: ExtractionSkillUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> ExtractionSkillDetail:
    customer_id = payload.customerId or _default_customer_id(current_user)
    ensure_customer_access(customer_id, current_user)
    try:
        skill_text = ensure_extraction_skill_semantic_governance(payload.skillText)
        return registry.save_customer_skill(skill_text, customer_id=customer_id, updated_by=current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.patch("/extraction-skills/{skillId}", response_model=ExtractionSkillDetail)
def update_extraction_skill(
    skillId: str,
    payload: ExtractionSkillUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    registry: ExtractionSkillRegistry = Depends(get_extraction_skill_registry),
) -> ExtractionSkillDetail:
    customer_id = payload.customerId or _default_customer_id(current_user)
    ensure_customer_access(customer_id, current_user)
    try:
        skill_text = ensure_extraction_skill_semantic_governance(payload.skillText)
        skill = registry.parse_markdown(skill_text, customer_id=customer_id)
        if skill.id != skillId:
            raise ValueError("路径中的 skillId 与 SKILL.md id 不一致。")
        return registry.save_customer_skill(skill_text, customer_id=customer_id, updated_by=current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


def _default_customer_id(current_user: SessionUser) -> str:
    if current_user.customerIds:
        return current_user.customerIds[0]
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 customerId。")
