# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Extraction skill prototype workflow APIs."""

from __future__ import annotations

# @edition-scope shared-api-contract
# @capability skill.prototypeOptimization
# @community-export include

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user, get_prompt_llm_service, get_prompt_pipeline_service
from app.core.config import get_settings
from app.schemas.skill_prototype import (
    BaselineGenerateRequest,
    BaselineUpdateRequest,
    CandidateDetailResponse,
    CandidateGenerateRequest,
    MainlineGateRequest,
    PrototypeCreateRequest,
    PrototypeJobStatus,
    PrototypeListResponse,
    PrototypeProject,
    PrototypeUpdateDatasetRequest,
    PrototypeUpdateRequest,
    PublishRequest,
    SkillNetCreateRequest,
)
from app.services.auth import SessionUser
from app.services.llm import PromptLlmService
from app.services.prompt_pipeline import PromptPipelineService
from app.services.skill_prototype_job_service import SkillPrototypeJobService
from app.services.skill_prototype_service import SkillPrototypeService

router = APIRouter(tags=["skill-prototypes"])


def get_skill_prototype_service(
    llm_service: PromptLlmService = Depends(get_prompt_llm_service),
    prompt_pipeline: PromptPipelineService = Depends(get_prompt_pipeline_service),
) -> SkillPrototypeService:
    return SkillPrototypeService(get_settings(), llm_service=llm_service, prompt_pipeline=prompt_pipeline)


def get_skill_prototype_job_service(
    llm_service: PromptLlmService = Depends(get_prompt_llm_service),
) -> SkillPrototypeJobService:
    return SkillPrototypeJobService(get_settings(), llm_service=llm_service)


# @edition-action list community=stub_empty commercial=full
# @capability skill.prototypeOptimization
@router.get("/skill-prototypes", response_model=PrototypeListResponse)
def list_skill_prototypes(
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeListResponse:
    items = service.list_projects()
    return PrototypeListResponse(items=items, total=len(items))


# @edition-action create community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes", response_model=PrototypeProject)
def create_skill_prototype(
    payload: PrototypeCreateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.create_project(payload, created_by=current_user.id)


# @edition-action detail community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.get("/skill-prototypes/{prototypeId}", response_model=PrototypeProject)
def get_skill_prototype(
    prototypeId: str,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.get_project(prototypeId)


# @edition-action update community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.put("/skill-prototypes/{prototypeId}", response_model=PrototypeProject)
def update_skill_prototype(
    prototypeId: str,
    payload: PrototypeUpdateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.update_project(prototypeId, payload)


# @edition-action dataset_update community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.put("/skill-prototypes/{prototypeId}/dataset", response_model=PrototypeProject)
def update_skill_prototype_dataset(
    prototypeId: str,
    payload: PrototypeUpdateDatasetRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.update_dataset(prototypeId, payload)


# @edition-action baseline_generate community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes/{prototypeId}/baseline", response_model=PrototypeProject)
def generate_skill_prototype_baseline(
    prototypeId: str,
    payload: BaselineGenerateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.generate_baseline(prototypeId, payload)


# @edition-action baseline_update community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.put("/skill-prototypes/{prototypeId}/baseline", response_model=PrototypeProject)
def update_skill_prototype_baseline(
    prototypeId: str,
    payload: BaselineUpdateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.update_baseline(prototypeId, payload)


# @edition-action candidates_generate community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes/{prototypeId}/candidates", response_model=PrototypeProject)
def generate_skill_prototype_candidates(
    prototypeId: str,
    payload: CandidateGenerateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.generate_candidates(prototypeId, payload)


# @edition-action candidate_detail community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.get("/skill-prototypes/{prototypeId}/candidates/{candidateId}/detail", response_model=CandidateDetailResponse)
def get_skill_prototype_candidate_detail(
    prototypeId: str,
    candidateId: str,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> CandidateDetailResponse:
    return service.get_candidate_detail(prototypeId, candidateId)


# @edition-action candidate_job_start community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes/{prototypeId}/candidate-jobs", response_model=PrototypeJobStatus)
def start_skill_prototype_candidate_job(
    prototypeId: str,
    payload: CandidateGenerateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeJobService = Depends(get_skill_prototype_job_service),
) -> PrototypeJobStatus:
    return service.start_candidate_generation(prototypeId, payload)


# @edition-action candidate_job_latest community=stub_empty commercial=full
# @capability skill.prototypeOptimization
@router.get("/skill-prototypes/{prototypeId}/candidate-jobs/latest", response_model=PrototypeJobStatus | None)
def get_latest_skill_prototype_candidate_job(
    prototypeId: str,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeJobService = Depends(get_skill_prototype_job_service),
) -> PrototypeJobStatus | None:
    return service.get_latest_candidate_generation(prototypeId)


# @edition-action candidate_job_detail community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.get("/skill-prototypes/{prototypeId}/candidate-jobs/{jobId}", response_model=PrototypeJobStatus)
def get_skill_prototype_candidate_job(
    prototypeId: str,
    jobId: str,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeJobService = Depends(get_skill_prototype_job_service),
) -> PrototypeJobStatus:
    return service.get_job(prototypeId, jobId)


# @edition-action evaluate community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes/{prototypeId}/evaluate", response_model=PrototypeProject)
def evaluate_skill_prototype(
    prototypeId: str,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.evaluate(prototypeId)


# @edition-action skillnet_create community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes/{prototypeId}/skillnet", response_model=PrototypeProject)
def create_skillnet_entry(
    prototypeId: str,
    payload: SkillNetCreateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.create_skillnet_entry(prototypeId, payload)


# @edition-action mainline_gate community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes/{prototypeId}/mainline-gate", response_model=PrototypeProject)
def submit_skill_prototype_gate(
    prototypeId: str,
    payload: MainlineGateRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.submit_gate(prototypeId, payload)


# @edition-action publish community=stub_403 commercial=full
# @capability skill.prototypeOptimization
@router.post("/skill-prototypes/{prototypeId}/publish", response_model=PrototypeProject)
def publish_skill_prototype(
    prototypeId: str,
    payload: PublishRequest,
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> PrototypeProject:
    return service.publish(prototypeId, payload)


# @edition-action published_list community=stub_empty commercial=full
# @capability skill.prototypeOptimization
@router.get("/skill-prototypes-published")
def list_published_skill_packages(
    current_user: SessionUser = Depends(get_current_user),
    service: SkillPrototypeService = Depends(get_skill_prototype_service),
) -> dict[str, object]:
    items = service.list_published()
    return {"items": items, "total": len(items)}
