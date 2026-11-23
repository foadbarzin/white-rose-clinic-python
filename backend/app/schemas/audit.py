"""Audit log request schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AuditListRequest(_Strict):
    action: str | None = Field(default=None, max_length=64)
    entity: str | None = Field(default=None, max_length=40)
    entity_id: str | None = Field(default=None, max_length=64)
    actor_user_id: str | None = Field(default=None, max_length=64)
    result: str | None = Field(default=None, pattern="^(ok|fail)$")
    from_date: str | None = Field(default=None, max_length=40, alias="from")
    to_date: str | None = Field(default=None, max_length=40, alias="to")
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class AuditGetRequest(_Strict):
    id: str = Field(min_length=8, max_length=64)
