"""Community stub for extraction skill prototype background jobs."""

from __future__ import annotations

# @edition-scope community-stub
# @capability skill.prototypeOptimization
# @community-export include

from typing import Any

from fastapi import HTTPException, status

COMMUNITY_SKILL_PROTOTYPE_JOB_SERVICE_STUB = True

UNAVAILABLE_DETAIL = (
    "抽取反推 Skill / SkillOpt 不包含在社区版中。"
    "社区版不会启动候选优化后台任务。"
)


def _raise_not_available() -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=UNAVAILABLE_DETAIL)


class SkillPrototypeJobService:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def start_candidate_generation(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()

    def get_latest_candidate_generation(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_job(self, *args: Any, **kwargs: Any) -> None:
        _raise_not_available()
