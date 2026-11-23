"""Authentication request schemas (POST /api payloads)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    deviceInfo: str | None = Field(default=None, max_length=255)


class LogoutRequest(_Strict):
    token: str | None = Field(default=None, max_length=512)


class ChangePasswordRequest(_Strict):
    oldPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=8, max_length=256)


class EmptyRequest(_Strict):
    pass
