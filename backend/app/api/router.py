"""Action gateway — preserves the legacy ``POST /api`` contract.

Phase 3 implements auth, users, RBAC and audit. Every action is registered with
an explicit schema, permission requirement and authentication flag; anything
outside this phase stays ``ACTION_NOT_IMPLEMENTED`` (never silently allowed).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Callable, Final

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ErrorCode,
    Forbidden,
    NotFound,
    NotImplementedAction,
    PasswordChangeRequired,
    RateLimited,
    Unauthorized,
    ValidationFailure,
    WrcError,
    error_envelope,
    success_envelope,
)
from app.core.jalali import calendar_info
from app.core.logging import get_client_ip, get_request_id, get_user_agent
from app.core.permissions import ACTION_PERMISSIONS, Principal, has_permission
from app.core.rate_limit import get_limiter
from app.database.models.identity import User, UserSession
from app.database.models.rbac import Role, UserRole
from app.database.session import session_scope
from app.schemas.api import ApiRequest
from app.schemas.audit import AuditGetRequest, AuditListRequest
from app.schemas.auth import ChangePasswordRequest, EmptyRequest, LoginRequest, LogoutRequest
from app.schemas.rbac import (
    PermissionAssignRequest,
    PermissionRevokeRequest,
    RoleAssignRequest,
    RoleCreateRequest,
    RoleListRequest,
    RoleRevokeRequest,
    RoleUpdateRequest,
)
from app.schemas.users import (
    UserActivityRequest,
    UserCreateRequest,
    UserGetRequest,
    UserListRequest,
    UserPasswordRequest,
    UserRevokeSessionsRequest,
    UserSessionsRequest,
    UserStateRequest,
    UserUpdateRequest,
)
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.context import ActorContext
from app.services.rbac import RbacService
from app.services.serializers import jsonable
from app.services.sessions import SessionService
from app.services.users import UserService

logger = logging.getLogger("white_rose_clinic.api")
router = APIRouter(tags=["api"])

PUBLIC_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "system.ping",
        "system.bootstrapStatus",
        "system.calendar",
        "auth.login",
        "setup.bootstrapAdmin",
    }
)
PASSWORD_CHANGE_ALLOWED: Final[frozenset[str]] = frozenset(
    {"auth.me", "auth.change_password", "auth.logout", "auth.logout_all", "auth.sessions"}
)

Handler = Callable[[Session | None, BaseModel, "AuthContext | None"], Any]


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    user: User
    session_row: UserSession
    token: str
    ip_address: str | None
    user_agent: str | None
    request_id: str

    def actor(self) -> ActorContext:
        return ActorContext(
            user_id=self.user.id,
            username=self.user.username,
            permissions=self.principal.permissions,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
            request_id=self.request_id,
            session_id=self.session_row.id,
        )


@dataclass(frozen=True)
class ActionSpec:
    name: str
    handler: Handler
    schema: type[BaseModel] | None = None
    permission: str | None = None
    public: bool = False
    needs_db: bool = True


ACTIONS: dict[str, ActionSpec] = {}


def action(
    name: str,
    *,
    schema: type[BaseModel] | None = None,
    permission: str | None = None,
    public: bool = False,
    needs_db: bool = True,
) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        if name in ACTIONS:
            raise RuntimeError(f"duplicate action registration: {name}")
        ACTIONS[name] = ActionSpec(
            name=name,
            handler=handler,
            schema=schema,
            permission=permission,
            public=public,
            needs_db=needs_db,
        )
        return handler

    return decorator


# --------------------------------------------------------------------------- helpers
def _client_ip(request) -> str | None:  # noqa: ANN001
    try:
        return request.client.host if request and request.client else None
    except Exception:  # pragma: no cover
        return None


def _user_agent(request) -> str | None:  # noqa: ANN001
    try:
        value = request.headers.get("user-agent") if request else None
        return value[:255] if value else None
    except Exception:  # pragma: no cover
        return None


def _safe_validation_errors(exc: PydanticValidationError) -> list[dict[str, Any]]:
    """Never echo submitted values (they may contain passwords)."""
    safe: list[dict[str, Any]] = []
    for error in exc.errors():
        safe.append(
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": error.get("type"),
                "msg": error.get("msg"),
            }
        )
    return safe


def _parse_datetime(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text[:10])
        except ValueError:
            raise ValidationFailure(message="بازهٔ زمانی معتبر نیست.") from None
        return datetime.combine(
            parsed_date, dt_time.max if end_of_day else dt_time.min, tzinfo=timezone.utc
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _login_limiter(settings: Settings):
    return get_limiter(settings.login_rate_limit_per_minute)


# ------------------------------------------------------------------ public actions
@action("system.ping", public=True, needs_db=False)
def _system_ping(db: Session | None, payload: BaseModel, ctx: "AuthContext | None") -> dict[str, Any]:
    settings = get_settings()
    return {
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "timezone": settings.timezone,
        },
        "ts": calendar_info()["today"],
        "authenticated": False,
    }


@action("system.calendar", public=True, needs_db=False)
def _system_calendar(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    settings = get_settings()
    info = calendar_info()
    info["timezone"] = settings.timezone
    return info


@action("system.bootstrapStatus", public=True)
def _system_bootstrap_status(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    settings = get_settings()
    ready = db is not None
    users = 0
    owners = 0
    if db is not None:
        try:
            users = int(db.scalar(select(func.count()).select_from(User)) or 0)
            owners = int(
                db.scalar(
                    select(func.count(func.distinct(UserRole.user_id)))
                    .select_from(UserRole)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(Role.code == "owner", Role.is_active.is_(True))
                )
                or 0
            )
        except Exception:
            ready = False
    return {
        "hasAdmin": owners > 0,
        "bootstrapAvailable": ready and users == 0,
        "databaseReady": ready,
        "spreadsheetConfigured": False,
        "pepperConfigured": bool(settings.secret_key),
    }


@action("setup.bootstrapAdmin", public=True, needs_db=False)
def _bootstrap_admin(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    # Public bootstrap is intentionally disabled (manager decision).
    raise NotImplementedAction(
        message="راه‌اندازی اولیه فقط از طریق ابزار مدیریت سرور (CLI) مجاز است."
    )


# ------------------------------------------------------------------- auth actions
@action("auth.login", schema=LoginRequest, public=True)
def _auth_login(db: Session | None, payload: BaseModel, ctx: "AuthContext | None") -> dict[str, Any]:
    assert db is not None
    settings = get_settings()
    request: LoginRequest = payload  # type: ignore[assignment]
    ip = get_client_ip()
    ua = get_user_agent()
    limiter = _login_limiter(settings)
    keys = [f"login:{ip or '-'}:{request.username.lower()}", f"login-ip:{ip or '-'}"]
    if not all(limiter.hit(key) for key in keys):
        try:
            with session_scope() as audit_db:
                AuditService.log(
                    audit_db,
                    action="auth.login_rate_limited",
                    entity="users",
                    result="fail",
                    actor_username=request.username.lower()[:64],
                    ip_address=ip,
                    user_agent=ua,
                    request_id=get_request_id(),
                    details={"reason": "rate_limited"},
                )
        except Exception:  # pragma: no cover - best effort only
            logger.warning("could not persist rate-limit audit event")
        raise RateLimited(
            message="تلاش‌های ورود بیش از حد مجاز است. کمی بعد دوباره تلاش کنید."
        )
    return AuthService.login(
        db,
        username=request.username,
        password=request.password,
        ip_address=ip,
        user_agent=ua,
        device_info=request.deviceInfo,
        request_id=get_request_id(),
        settings=settings,
    )


@action("auth.me", schema=EmptyRequest)
def _auth_me(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    return {
        "user": AuthService.serialize_user(db, ctx.user, with_permissions=True),
        "session": SessionService.serialize(ctx.session_row, current_session_id=ctx.session_row.id),
    }


@action("auth.sessions", schema=EmptyRequest)
def _auth_sessions(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    rows = SessionService.list_active(db, ctx.user.id)
    return {
        "sessions": [
            SessionService.serialize(row, current_session_id=ctx.session_row.id) for row in rows
        ],
        "count": len(rows),
    }


@action("auth.logout", schema=LogoutRequest)
def _auth_logout(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    return AuthService.logout(
        db, token=ctx.token, session_row=ctx.session_row, actor=ctx.actor()
    )


@action("auth.logout_all", schema=EmptyRequest)
def _auth_logout_all(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    return AuthService.logout_all(db, user=ctx.user, actor=ctx.actor())


@action("auth.change_password", schema=ChangePasswordRequest)
def _auth_change_password(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: ChangePasswordRequest = payload  # type: ignore[assignment]
    return AuthService.change_password(
        db,
        user=ctx.user,
        old_password=request.oldPassword,
        new_password=request.newPassword,
        current_session_id=ctx.session_row.id,
        actor=ctx.actor(),
        settings=get_settings(),
    )


# ------------------------------------------------------------------ users actions
@action("users.list", schema=UserListRequest, permission="users.manage")
def _users_list(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None
    request: UserListRequest = payload  # type: ignore[assignment]
    return UserService.list_users(db, q=request.q, include_inactive=request.include_inactive)


@action("users.get", schema=UserGetRequest, permission="users.manage")
def _users_get(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None
    request: UserGetRequest = payload  # type: ignore[assignment]
    return UserService.get_user(db, request.user_id)


@action("users.create", schema=UserCreateRequest, permission="users.manage")
def _users_create(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: UserCreateRequest = payload  # type: ignore[assignment]
    return UserService.create_user(
        db,
        ctx.actor(),
        username=request.username,
        password=request.password,
        display_name=request.display_name,
        role_codes=request.role_codes,
        linked_doctor_id=request.linked_doctor_id,
        linked_operator_id=request.linked_operator_id,
        must_change_password=request.must_change_password,
        settings=get_settings(),
    )


@action("users.update", schema=UserUpdateRequest, permission="users.manage")
def _users_update(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: UserUpdateRequest = payload  # type: ignore[assignment]
    return UserService.update_user(
        db,
        ctx.actor(),
        user_id=request.user_id,
        display_name=request.display_name,
        linked_doctor_id=request.linked_doctor_id,
        linked_operator_id=request.linked_operator_id,
        must_change_password=request.must_change_password,
    )


def _user_state(active: bool):
    def handler(
        db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
    ) -> dict[str, Any]:
        assert db is not None and ctx is not None
        request: UserStateRequest = payload  # type: ignore[assignment]
        return UserService.set_active(db, ctx.actor(), user_id=request.user_id, active=active)

    return handler


ACTIONS["users.disable"] = ActionSpec(
    name="users.disable",
    handler=_user_state(False),
    schema=UserStateRequest,
    permission="users.manage",
)
ACTIONS["users.enable"] = ActionSpec(
    name="users.enable",
    handler=_user_state(True),
    schema=UserStateRequest,
    permission="users.manage",
)


@action("users.unlock", schema=UserStateRequest, permission="users.manage")
def _users_unlock(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: UserStateRequest = payload  # type: ignore[assignment]
    return UserService.unlock(db, ctx.actor(), user_id=request.user_id)


@action("users.change_password", schema=UserPasswordRequest, permission="users.manage")
def _users_change_password(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: UserPasswordRequest = payload  # type: ignore[assignment]
    return UserService.reset_password(
        db,
        ctx.actor(),
        user_id=request.user_id,
        new_password=request.new_password,
        settings=get_settings(),
    )


@action("users.sessions", schema=UserSessionsRequest, permission="users.manage")
def _users_sessions(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None
    request: UserSessionsRequest = payload  # type: ignore[assignment]
    return UserService.list_sessions(db, user_id=request.user_id)


@action("users.revoke_sessions", schema=UserRevokeSessionsRequest, permission="users.manage")
def _users_revoke_sessions(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: UserRevokeSessionsRequest = payload  # type: ignore[assignment]
    return UserService.revoke_sessions(
        db,
        ctx.actor(),
        user_id=request.user_id,
        session_id=request.session_id,
        reason=request.reason,
    )


@action("users.activity", schema=UserActivityRequest, permission="users.manage")
def _users_activity(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None
    request: UserActivityRequest = payload  # type: ignore[assignment]
    return UserService.activity(
        db, user_id=request.user_id, limit=request.limit, offset=request.offset
    )


# ------------------------------------------------------------------- RBAC actions
@action("roles.list", schema=RoleListRequest, permission="rbac.manage")
def _roles_list(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None
    return {"roles": RbacService.list_roles(db)}


@action("roles.create", schema=RoleCreateRequest, permission="rbac.manage")
def _roles_create(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: RoleCreateRequest = payload  # type: ignore[assignment]
    return RbacService.create_role(
        db,
        ctx.actor(),
        code=request.code,
        name=request.name,
        description=request.description or "",
        permissions=request.permissions,
        legacy_role=request.legacy_role,
    )


@action("roles.update", schema=RoleUpdateRequest, permission="rbac.manage")
def _roles_update(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: RoleUpdateRequest = payload  # type: ignore[assignment]
    return RbacService.update_role(
        db,
        ctx.actor(),
        code=request.code,
        name=request.name,
        description=request.description,
        is_active=request.is_active,
        legacy_role=request.legacy_role,
    )


@action("roles.assign", schema=RoleAssignRequest, permission="rbac.manage")
def _roles_assign(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: RoleAssignRequest = payload  # type: ignore[assignment]
    return RbacService.assign_roles(
        db,
        ctx.actor(),
        user_id=_as_uuid(request.user_id, "شناسهٔ کاربر"),
        role_codes=request.role_codes,
    )


@action("roles.revoke", schema=RoleRevokeRequest, permission="rbac.manage")
def _roles_revoke(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: RoleRevokeRequest = payload  # type: ignore[assignment]
    try:
        user_id = uuid.UUID(request.user_id)
    except (ValueError, TypeError):
        raise ValidationFailure(message="شناسهٔ کاربر معتبر نیست.") from None
    return RbacService.revoke_roles(
        db, ctx.actor(), user_id=user_id, role_codes=request.role_codes
    )


@action("permissions.list", schema=EmptyRequest, permission="rbac.manage")
def _permissions_list(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    return RbacService.permissions_catalog()


@action("permissions.assign", schema=PermissionAssignRequest, permission="rbac.manage")
def _permissions_assign(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: PermissionAssignRequest = payload  # type: ignore[assignment]
    return RbacService.assign_permissions(
        db,
        ctx.actor(),
        role_code=request.role_code,
        permission_codes=request.permission_codes,
    )


@action("permissions.revoke", schema=PermissionRevokeRequest, permission="rbac.manage")
def _permissions_revoke(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None and ctx is not None
    request: PermissionRevokeRequest = payload  # type: ignore[assignment]
    return RbacService.revoke_permissions(
        db,
        ctx.actor(),
        role_code=request.role_code,
        permission_codes=request.permission_codes,
    )


# ------------------------------------------------------------------ audit actions
@action("audit.list", schema=AuditListRequest, permission="audit.read")
def _audit_list(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None
    request: AuditListRequest = payload  # type: ignore[assignment]
    rows, total = AuditService.list_events(
        db,
        action=request.action,
        entity=request.entity,
        entity_id=request.entity_id,
        actor_user_id=request.actor_user_id,
        result=request.result,
        occurred_from=_parse_datetime(request.from_date),
        occurred_to=_parse_datetime(request.to_date, end_of_day=True),
        limit=request.limit,
        offset=request.offset,
    )
    return {
        "rows": [AuditService.serialize(row) for row in rows],
        "total": total,
        "limit": request.limit,
        "offset": request.offset,
    }


@action("audit.get", schema=AuditGetRequest, permission="audit.read")
def _audit_get(
    db: Session | None, payload: BaseModel, ctx: "AuthContext | None"
) -> dict[str, Any]:
    assert db is not None
    request: AuditGetRequest = payload  # type: ignore[assignment]
    row = AuditService.get(db, request.id)
    if row is None:
        raise NotFound(message="رویداد یافت نشد.")
    return {"event": AuditService.serialize(row)}


# ----------------------------------------------------------------------- dispatch
def _as_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise ValidationFailure(message=f"{label} معتبر نیست.") from None


def _authenticate(db: Session, token: str | None) -> AuthContext:
    check = SessionService.validate(db, token)
    if not check.ok:
        row = check.session_row
        if check.reason in ("expired", "idle_expired"):
            AuditService.log(
                db,
                action="auth.session_expired",
                entity="user_sessions",
                entity_id=row.id if row else None,
                result="fail",
                actor_user_id=row.user_id if row else None,
                ip_address=get_client_ip(),
                user_agent=get_user_agent(),
                request_id=get_request_id(),
                details={"reason": check.reason},
            )
            db.commit()
            raise Unauthorized(message="نشست منقضی شده است. دوباره وارد شوید.")
        if check.reason == "revoked":
            AuditService.log(
                db,
                action="auth.session_revoked",
                entity="user_sessions",
                entity_id=row.id if row else None,
                result="fail",
                actor_user_id=row.user_id if row else None,
                ip_address=get_client_ip(),
                user_agent=get_user_agent(),
                request_id=get_request_id(),
                details={"reason": "reuse_after_revoke"},
            )
            db.commit()
            raise Unauthorized(message="این نشست ابطال شده است. دوباره وارد شوید.")
        raise Unauthorized(message="نشست معتبر نیست. دوباره وارد شوید.")

    assert check.user is not None and check.session_row is not None
    principal = AuthService.principal_for(db, check.user, session_id=check.session_row.id)
    return AuthContext(
        principal=principal,
        user=check.user,
        session_row=check.session_row,
        token=token or "",
        ip_address=get_client_ip(),
        user_agent=get_user_agent(),
        request_id=get_request_id(),
    )


def _run(spec: ActionSpec, payload: BaseModel, token: str | None) -> dict[str, Any]:
    if spec.public:
        if spec.needs_db:
            with session_scope() as db:
                return spec.handler(db, payload, None)
        return spec.handler(None, payload, None)

    with session_scope() as db:
        ctx = _authenticate(db, token)
        if ctx.user.must_change_password and spec.name not in PASSWORD_CHANGE_ALLOWED:
            raise PasswordChangeRequired()
        if spec.permission and not has_permission(ctx.principal, spec.permission):
            AuditService.log(
                db,
                action="auth.permission_denied",
                entity="actions",
                entity_id=spec.name,
                result="fail",
                actor_user_id=ctx.user.id,
                actor_username=ctx.user.username,
                ip_address=ctx.ip_address,
                user_agent=ctx.user_agent,
                request_id=ctx.request_id,
                details={"permission": spec.permission},
            )
            raise Forbidden(message="دسترسی مجاز نیست.")
        return spec.handler(db, payload, ctx)


def _documented(action_name: str) -> bool:
    return (
        action_name in ACTIONS
        or action_name in PUBLIC_ACTIONS
        or action_name in ACTION_PERMISSIONS
    )


@router.post("/api", summary="Single action gateway (legacy contract)")
def api_gateway(body: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    request_id = get_request_id()
    started = time.perf_counter()
    action_name = "?"
    try:
        try:
            request = ApiRequest.model_validate(body or {})
        except PydanticValidationError as exc:
            raise ValidationFailure(
                message="درخواست نامعتبر است (action الزامی است).",
                details={"errors": _safe_validation_errors(exc)},
            ) from exc

        action_name = request.action
        spec = ACTIONS.get(request.action)

        if spec is None:
            if request.action in PUBLIC_ACTIONS:
                raise NotImplementedAction()
            if _documented(request.action):
                # documented but not implemented: still require a real session
                with session_scope() as db:
                    _authenticate(db, request.token)
                raise NotImplementedAction()
            raise NotFound(message="اکشن نامعتبر است.")

        payload: BaseModel = EmptyRequest()
        if spec.schema is not None:
            try:
                payload = spec.schema.model_validate(request.payload)
            except PydanticValidationError as exc:
                raise ValidationFailure(
                    message="اطلاعات ارسالی معتبر نیست.",
                    details={"errors": _safe_validation_errors(exc)},
                ) from exc

        data = _run(spec, payload, request.token)
        response = success_envelope(data)
        response["request_id"] = request_id
        logger.info(
            "api action completed",
            extra={
                "action": action_name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "result": "ok",
            },
        )
        return JSONResponse(response)
    except WrcError as exc:
        logger.info(
            "api action rejected",
            extra={"action": action_name, "code": exc.code, "result": "error"},
        )
        return JSONResponse(error_envelope(exc.code, exc.message, exc.details, request_id))
    except Exception:  # pragma: no cover - safety net, never leak details
        logger.exception("unhandled api error", extra={"action": action_name})
        return JSONResponse(
            error_envelope(ErrorCode.INTERNAL, None, None, request_id),
            status_code=500,
        )


@router.get("/api/meta/contract", summary="Action contract metadata")
def contract() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "contract": "action-v1",
            "implemented": sorted(ACTIONS),
            "public": sorted(PUBLIC_ACTIONS),
            "envelope": {
                "ok": True,
                "data": "...",
                "error": {"code": "...", "message": "..."},
            },
        },
    }






