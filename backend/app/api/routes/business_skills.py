# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Business skill registry APIs."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import ensure_customer_access, get_business_skill_registry, get_current_user
from app.schemas.workbench import BusinessSkillDetail, BusinessSkillUpsertRequest
from app.services.auth import SessionUser
from app.services.business_skills import BusinessSkillRegistry

router = APIRouter(tags=["business-skills"])


@router.get("/business-skills", response_model=list[BusinessSkillDetail])
def list_business_skills(
    customerId: Optional[str] = Query(None),
    current_user: SessionUser = Depends(get_current_user),
    registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
) -> list[BusinessSkillDetail]:
    if customerId:
        ensure_customer_access(customerId, current_user)
    return registry.list_skills(customer_id=customerId)


@router.post("/business-skills", response_model=BusinessSkillDetail)
def create_business_skill(
    payload: BusinessSkillUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
) -> BusinessSkillDetail:
    customer_id = payload.customerId or _default_customer_id(current_user)
    ensure_customer_access(customer_id, current_user)
    try:
        parsed = registry.parse_markdown(payload.skillText, customer_id=customer_id)
        _ensure_controlled_python_admin(parsed.executor, current_user)
        return registry.save_customer_skill(payload.skillText, customer_id=customer_id, updated_by=current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.patch("/business-skills/{skillId}", response_model=BusinessSkillDetail)
def update_business_skill(
    skillId: str,
    payload: BusinessSkillUpsertRequest,
    current_user: SessionUser = Depends(get_current_user),
    registry: BusinessSkillRegistry = Depends(get_business_skill_registry),
) -> BusinessSkillDetail:
    customer_id = payload.customerId or _default_customer_id(current_user)
    ensure_customer_access(customer_id, current_user)
    try:
        skill = registry.parse_markdown(payload.skillText, customer_id=customer_id)
        if skill.id != skillId:
            raise ValueError("路径中的 skillId 与 SKILL.md id 不一致。")
        _ensure_controlled_python_admin(skill.executor, current_user)
        return registry.save_customer_skill(payload.skillText, customer_id=customer_id, updated_by=current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


def _default_customer_id(current_user: SessionUser) -> str:
    if current_user.customerIds:
        return current_user.customerIds[0]
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 customerId。")


def _ensure_controlled_python_admin(executor: str, current_user: SessionUser) -> None:
    if executor == "controlled_python" and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="controlled_python 仅管理员可发布。")
