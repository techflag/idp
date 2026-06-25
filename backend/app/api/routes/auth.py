# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Authentication endpoints backed by JSON user storage."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import get_app_settings, get_auth_service, get_current_user, to_auth_user_response
from app.core.config import AppSettings
from app.schemas.auth import AuthUserResponse, LoginRequest, LoginResponse
from app.services.auth import SessionUser
from app.services.db_auth import DbAuthService

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("uvicorn.error")


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    settings: AppSettings = Depends(get_app_settings),
    auth_service: DbAuthService = Depends(get_auth_service),
) -> LoginResponse:
    try:
        user = auth_service.authenticate(payload.username, payload.password)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except Exception:
        logger.exception("Authentication failed unexpectedly for username=%s", payload.username)
        raise

    response.set_cookie(
        key=settings.auth_cookie_name,
        value=auth_service.build_session_token(user),
        httponly=True,
        max_age=settings.auth_session_ttl_seconds,
        samesite="lax",
        secure=False,
        path="/",
    )
    return LoginResponse(user=to_auth_user_response(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    settings: AppSettings = Depends(get_app_settings),
) -> Response:
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return response


@router.get("/me", response_model=AuthUserResponse)
def get_me(current_user: SessionUser = Depends(get_current_user)) -> AuthUserResponse:
    return to_auth_user_response(current_user)
