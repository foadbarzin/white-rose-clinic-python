"""Action gateway — preserves the legacy ``POST /api`` contract.

Request:   ``{"action": "...", "payload": {...}, "token": "..."}``
Response:  ``{"ok": true, "data": ...}`` or ``{"ok": false, "error": {...}}``

Phase 2 scope: the router, error handling, session resolution hook and three
public actions (``system.ping``, ``system.bootstrapStatus``, ``system.calendar``).
Every other documented action answers ``ACTION_NOT_IMPLEMENTED`` so that no
financial operation can run before its service exists.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Final

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.exceptions import (
    ErrorCode,
    NotImplementedAction,
    NotFound,
    Unauthorized,
    ValidationFailure,
    WrcError,
    error_envelope,
    success_envelope,
)
from app.core.jalali import calendar_info
from app.core.logging import get_request_id
from app.core.permissions import Principal, is_known_action, require
from app.database.models.identity import User
from app.database.session import session_scope
from app.schemas.api import ApiRequest

logger = logging.getLogger("white_rose_clinic.api")

router = APIRouter(tags=["api"])

Handler = Callable[[dict[str, Any], Principal | None], Any]

PUBLIC_ACTIONS: Final[frozenset[str]] = frozenset(
    {"system.ping", "system.bootstrapStatus", "system.calendar", "auth.login", "setup.bootstrapAdmin"}
)


@dataclass(frozen=True)
class ActionSpec:
    name: str
    handler: Handler
    permission: str | None = None
    public: bool = False


ACTIONS: dict[str, ActionSpec] = {}


def action(
    name: str, *, permission: str | None = None, public: bool = False
) -> Callable[[Handler], Handler]:
    """Register an implemented action (single gateway, explicit registry)."""

    def decorator(handler: Handler) -> Handler:
        if name in ACTIONS:
            raise RuntimeError(f"duplicate action registration: {name}")
        ACTIONS[name] = ActionSpec(name=name, handler=handler, permission=permission, public=public)
        return handler

    return decorator


# --------------------------------------------------------------------------- auth hook
def resolve_session(token: str | None) -> Principal:
    """Resolve an opaque session token into a principal.

    Authentication (login/session storage) is implemented in phase 3. Until
    then every protected action is rejected — this guarantees that no action
    can be executed without a real, validated session.
    """
    _ = token
    raise Unauthorized(message="احراز هویت در این نسخه فعال نشده است.")


# ------------------------------------------------------------------------- actions
@action("system.ping", public=True)
def _system_ping(payload: dict[str, Any], principal: Principal | None) -> dict[str, Any]:
    _ = payload, principal
    settings = get_settings()
    return {
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "timezone": settings.timezone,
        },
        "ts": calendar_info()["today"],
    }


@action("system.bootstrapStatus", public=True)
def _system_bootstrap_status(
    payload: dict[str, Any], principal: Principal | None
) -> dict[str, Any]:
    _ = payload, principal
    settings = get_settings()
    has_admin = False
    database_ready = True
    try:
        with session_scope() as session:
            count = session.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == "admin",
                    User.is_active.is_(True),
                    User.is_deleted.is_(False),
                )
            )
        has_admin = bool(count)
    except Exception:
        database_ready = False

    return {
        "hasAdmin": has_admin,
        "databaseReady": database_ready,
        "spreadsheetConfigured": False,  # Google Sheets is retired in this engine
        "pepperConfigured": bool(settings.secret_key),
    }


@action("system.calendar", public=True)
def _system_calendar(payload: dict[str, Any], principal: Principal | None) -> dict[str, Any]:
    _ = payload, principal
    settings = get_settings()
    info = calendar_info()
    info["timezone"] = settings.timezone
    return info


# ------------------------------------------------------------------------ endpoint
_KNOWN_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "auth",
        "users",
        "patients",
        "customers",
        "doctors",
        "operators",
        "services",
        "definitions",
        "invoices",
        "payments",
        "credits",
        "expenses",
        "revenue",
        "commissions",
        "commissionRules",
        "reports",
        "settings",
        "setup",
        "system",
        "sync",
    }
)


def is_documented_action(action: str) -> bool:
    """True when the action belongs to the documented contract (implemented or not)."""
    if action in ACTIONS or action in PUBLIC_ACTIONS or is_known_action(action):
        return True
    return action.split(".", 1)[0] in _KNOWN_PREFIXES


def _dispatch(req: ApiRequest, request_id: str) -> JSONResponse:
    spec = ACTIONS.get(req.action)

    if spec is not None and spec.public:
        data = spec.handler(req.payload, None)
    elif req.action in PUBLIC_ACTIONS:
        # documented public action, not implemented in phase 2 (e.g. auth.login)
        raise NotImplementedAction()
    else:
        if not is_documented_action(req.action):
            raise NotFound(message="اکشن نامعتبر است.")
        # Every protected action requires a real validated session, even when
        # its service is not implemented yet (no action runs unauthenticated).
        principal = resolve_session(req.token)
        if spec is None:
            raise NotImplementedAction()
        if spec.permission:
            require(spec.permission, principal)
        data = spec.handler(req.payload, principal)

    payload = success_envelope(data)
    payload["request_id"] = request_id
    return JSONResponse(payload)


@router.post("/api", summary="Single action gateway (legacy contract)")
def api_gateway(body: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    request_id = get_request_id()
    started = time.perf_counter()
    action_name = "?"
    try:
        try:
            req = ApiRequest.model_validate(body or {})
        except PydanticValidationError as exc:
            raise ValidationFailure(
                message="درخواست نامعتبر است (action الزامی است).",
                details={"errors": exc.errors(include_url=False)},
            ) from exc

        action_name = req.action
        response = _dispatch(req, request_id)
        logger.info(
            "api action completed",
            extra={
                "action": action_name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "result": "ok",
            },
        )
        return response
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
    """Self-description of the gateway (useful for diagnostics and tooling)."""
    return {
        "ok": True,
        "data": {
            "contract": "action-v1",
            "implemented": sorted(ACTIONS),
            "envelope": {"ok": True, "data": "...", "error": {"code": "...", "message": "..."}},
        },
    }

