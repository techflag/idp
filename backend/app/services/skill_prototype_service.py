"""Community stub for extraction skill prototype optimization service."""

from __future__ import annotations

# @edition-scope community-stub
# @capability skill.prototypeOptimization
# @community-export include

from typing import Any

from fastapi import HTTPException, status

COMMUNITY_SKILL_PROTOTYPE_SERVICE_STUB = True

UNAVAILABLE_DETAIL = (
    "抽取反推 Skill / SkillOpt 不包含在社区版中。"
    "社区版保留 API 契约，但未发布商业候选优化、训练评测和 SkillNet 实现。"
)


def _raise_not_available() -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=UNAVAILABLE_DETAIL)


class SkillPrototypeService:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def list_projects(self) -> list[Any]:
        return []

    def create_project(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def get_project(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def update_project(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def update_dataset(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def generate_baseline(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def update_baseline(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def generate_candidates(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def get_candidate_detail(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def evaluate(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def create_skillnet_entry(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def submit_gate(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def publish(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def list_published(self) -> list[Any]:
        return []
