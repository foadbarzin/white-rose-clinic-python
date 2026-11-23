"""RBAC request schemas (roles and permissions)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RoleCreateRequest(_Strict):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=200)
    legacy_role: str | None = Field(default=None, pattern="^(admin|operator|doctor)$")


class RoleUpdateRequest(_Strict):
    code: str = Field(min_length=2, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    legacy_role: str | None = Field(default=None, pattern="^(admin|operator|doctor)$")


class RoleAssignRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)
    role_codes: list[str] = Field(min_length=1, max_length=20)


class RoleRevokeRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)
    role_codes: list[str] = Field(min_length=1, max_length=20)


class PermissionAssignRequest(_Strict):
    role_code: str = Field(min_length=2, max_length=64)
    permission_codes: list[str] = Field(min_length=1, max_length=200)


class PermissionRevokeRequest(_Strict):
    role_code: str = Field(min_length=2, max_length=64)
    permission_codes: list[str] = Field(min_length=1, max_length=200)


class RoleListRequest(_Strict):
    pass
