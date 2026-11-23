"""Pydantic schemas for the HTTP surface (request/response contracts)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiRequest(BaseModel):
    """Request body of ``POST /api`` (legacy contract: action/payload/token)."""

    model_config = ConfigDict(extra="ignore")

    action: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    token: str | None = Field(default=None, max_length=512)


class ApiError(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ApiResponse(BaseModel):
    """Envelope used by the existing frontend: ``{ok, data}`` or ``{ok, error}``."""

    ok: bool
    data: Any | None = None
    error: ApiError | None = None
    request_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    application: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    schema_version: str | None = None
    detail: str | None = None


class VersionResponse(BaseModel):
    application: str
    version: str
    environment: str
    api_contract: str
    timezone: str


class DesktopInfoResponse(BaseModel):
    desktop: bool
    version: str
    mode: str
