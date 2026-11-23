"""User administration request schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UserListRequest(_Strict):
    q: str | None = Field(default=None, max_length=120)
    include_inactive: bool = True


class UserGetRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)


class UserCreateRequest(_Strict):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)
    role_codes: list[str] = Field(default_factory=list, max_length=20)
    linked_doctor_id: str | None = Field(default=None, max_length=64)
    linked_operator_id: str | None = Field(default=None, max_length=64)
    must_change_password: bool = True


class UserUpdateRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)
    display_name: str | None = Field(default=None, max_length=120)
    linked_doctor_id: str | None = Field(default=None, max_length=64)
    linked_operator_id: str | None = Field(default=None, max_length=64)
    must_change_password: bool | None = None


class UserStateRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)


class UserPasswordRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)
    new_password: str = Field(min_length=8, max_length=256)


class UserSessionsRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)


class UserRevokeSessionsRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=64)


class UserActivityRequest(_Strict):
    user_id: str = Field(min_length=8, max_length=64)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
