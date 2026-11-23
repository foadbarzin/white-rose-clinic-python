"""Cross-cutting concerns: configuration, errors, logging, security, RBAC."""

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    Conflict,
    Duplicate,
    Forbidden,
    InternalFailure,
    InvalidState,
    NotFound,
    NotImplementedAction,
    NotReady,
    Unauthorized,
    ValidationFailure,
    WrcError,
    error_envelope,
    success_envelope,
)

__all__ = [
    "Settings",
    "get_settings",
    "WrcError",
    "ValidationFailure",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "Duplicate",
    "InvalidState",
    "Conflict",
    "NotImplementedAction",
    "NotReady",
    "InternalFailure",
    "error_envelope",
    "success_envelope",
]
