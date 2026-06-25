# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Community application API boundary.

COMMUNITY_APPLICATION_ROUTES_STUB

The GitHub community repository intentionally does not ship the full
application-run planner, cross-page semantic locator orchestration, or
commercial long-document execution chain.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(tags=["applications"])

_COMMUNITY_DETAIL = (
    "GitHub 社区版不包含完整文档应用运行/长文档链路。"
    "请使用单页样例抽取与基础 Skill 调试；完整长文档运行属于商业私有扩展。"
)


def _community_unavailable() -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_COMMUNITY_DETAIL)


@router.get("/applications")
def list_applications(
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    publishedOnly: bool = Query(False),
    scope: str | None = Query(None),
) -> dict[str, Any]:
    _ = publishedOnly, scope
    return {"items": [], "total": 0, "page": page, "pageSize": pageSize}


@router.get("/applications/runs/{runId}")
def get_application_run_detail(runId: str) -> None:
    _ = runId
    _community_unavailable()


@router.post("/applications/runs/{runId}/review-feedback")
def submit_application_run_review_feedback(runId: str, payload: dict[str, Any]) -> None:
    _ = runId, payload
    _community_unavailable()


@router.post("/applications")
def create_application_draft(payload: dict[str, Any]) -> None:
    _ = payload
    _community_unavailable()


@router.get("/applications/{applicationId}")
def get_application_detail(applicationId: str) -> None:
    _ = applicationId
    _community_unavailable()


@router.patch("/applications/{applicationId}")
def update_application_draft(applicationId: str, payload: dict[str, Any]) -> None:
    _ = applicationId, payload
    _community_unavailable()


@router.post("/applications/{applicationId}/publish")
def publish_application(applicationId: str, payload: dict[str, Any]) -> None:
    _ = applicationId, payload
    _community_unavailable()


@router.post("/applications/{applicationId}/run")
def upload_and_run_application(applicationId: str) -> None:
    _ = applicationId
    _community_unavailable()


@router.post("/applications/{applicationId}/runs")
def run_application(applicationId: str, payload: dict[str, Any]) -> None:
    _ = applicationId, payload
    _community_unavailable()


@router.post("/applications/{applicationId}/runs/plan")
def plan_application_run(applicationId: str, payload: dict[str, Any]) -> None:
    _ = applicationId, payload
    _community_unavailable()
