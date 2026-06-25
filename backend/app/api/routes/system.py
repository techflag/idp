# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""System capability endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_settings
from app.core.config import AppSettings
from app.core.edition_policy import build_system_capabilities
from app.schemas.system import SystemCapabilitiesResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/capabilities", response_model=SystemCapabilitiesResponse)
def get_system_capabilities(settings: AppSettings = Depends(get_app_settings)) -> SystemCapabilitiesResponse:
    return build_system_capabilities(settings)

