"""Authentication request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AuthUserResponse(BaseModel):
    id: str
    username: str
    role: Literal["admin", "user", "customer"]
    displayName: str
    customerIds: list[str]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user: AuthUserResponse


class CreateCustomerAccountRequest(BaseModel):
    username: str = Field(min_length=3)
    password: str = Field(min_length=6)
    displayName: str = Field(min_length=1)
    customerIds: list[str] = Field(default_factory=list)
