"""Domain error model + API error envelope (compatible with the legacy UI).

The existing HTML/CSS/JS client only understands::

    { "ok": true,  "data": ... }
    { "ok": false, "error": { "code": "...", "message": "...", "details": ... } }

Every error raised inside the action gateway is mapped to that envelope.
Internal exceptions are never leaked to the client (no stack traces).
"""

from __future__ import annotations

from typing import Any, Final


class ErrorCode:
    """Stable machine-readable error codes (contract, do not rename)."""

    VALIDATION: Final = "VALIDATION"
    UNAUTHORIZED: Final = "UNAUTHORIZED"
    FORBIDDEN: Final = "FORBIDDEN"
    NOT_FOUND: Final = "NOT_FOUND"
    DUPLICATE: Final = "DUPLICATE"
    INVALID_STATE: Final = "INVALID_STATE"
    CONFLICT: Final = "CONFLICT"
    LOCK_TIMEOUT: Final = "LOCK_TIMEOUT"
    AUTH_FAILED: Final = "AUTH_FAILED"
    AUTH_LOCKED: Final = "AUTH_LOCKED"
    RATE_LIMITED: Final = "RATE_LIMITED"
    SYNC_REJECTED: Final = "SYNC_REJECTED"
    ACTION_NOT_IMPLEMENTED: Final = "ACTION_NOT_IMPLEMENTED"
    NOT_READY: Final = "NOT_READY"
    INTERNAL: Final = "INTERNAL"


DEFAULT_MESSAGES: Final[dict[str, str]] = {
    ErrorCode.VALIDATION: "اطلاعات ارسالی معتبر نیست.",
    ErrorCode.UNAUTHORIZED: "نشست معتبر نیست. دوباره وارد شوید.",
    ErrorCode.FORBIDDEN: "دسترسی مجاز نیست.",
    ErrorCode.NOT_FOUND: "مورد درخواستی یافت نشد.",
    ErrorCode.DUPLICATE: "مورد تکراری است.",
    ErrorCode.INVALID_STATE: "وضعیت فعلی اجازهٔ این عملیات را نمی‌دهد.",
    ErrorCode.CONFLICT: "تعارض داده رخ داده است.",
    ErrorCode.LOCK_TIMEOUT: "سیستم مشغول است، کمی بعد دوباره تلاش کنید.",
    ErrorCode.AUTH_FAILED: "نام کاربری یا رمز عبور نادرست است.",
    ErrorCode.AUTH_LOCKED: "حساب موقتاً قفل شده است. بعداً تلاش کنید.",
    ErrorCode.RATE_LIMITED: "تعداد درخواست‌ها بیش از حد مجاز است.",
    ErrorCode.SYNC_REJECTED: "عملیات همگام‌سازی پذیرفته نشد.",
    ErrorCode.ACTION_NOT_IMPLEMENTED: "این قابلیت در نسخهٔ فعلی موتور فعال نشده است.",
    ErrorCode.NOT_READY: "سرویس آماده نیست.",
    ErrorCode.INTERNAL: "خطای داخلی سرور رخ داد.",
}


class WrcError(Exception):
    """Base domain error carrying a stable code and a safe Persian message."""

    code: str = ErrorCode.INTERNAL
    http_status: int = 200  # legacy contract: domain errors travel over HTTP 200

    def __init__(
        self,
        code: str | None = None,
        message: str | None = None,
        details: Any | None = None,
        *,
        http_status: int | None = None,
    ) -> None:
        self.code = code or self.code
        self.message = message or DEFAULT_MESSAGES.get(self.code, "خطای سیستمی")
        self.details = details
        if http_status is not None:
            self.http_status = http_status
        super().__init__(self.message)

    def to_error(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<{type(self).__name__} code={self.code!r} message={self.message!r}>"


class ValidationFailure(WrcError):
    code = ErrorCode.VALIDATION


class Unauthorized(WrcError):
    code = ErrorCode.UNAUTHORIZED


class Forbidden(WrcError):
    code = ErrorCode.FORBIDDEN


class NotFound(WrcError):
    code = ErrorCode.NOT_FOUND


class Duplicate(WrcError):
    code = ErrorCode.DUPLICATE


class InvalidState(WrcError):
    code = ErrorCode.INVALID_STATE


class Conflict(WrcError):
    code = ErrorCode.CONFLICT


class LockTimeout(WrcError):
    code = ErrorCode.LOCK_TIMEOUT


class RateLimited(WrcError):
    code = ErrorCode.RATE_LIMITED


class NotImplementedAction(WrcError):
    code = ErrorCode.ACTION_NOT_IMPLEMENTED


class NotReady(WrcError):
    code = ErrorCode.NOT_READY
    http_status = 503


class InternalFailure(WrcError):
    code = ErrorCode.INTERNAL
    http_status = 500


def success_envelope(data: Any) -> dict[str, Any]:
    """Wrap a payload in the contract used by the existing frontend."""
    return {"ok": True, "data": data}


def error_envelope(
    code: str,
    message: str | None = None,
    details: Any | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the legacy-compatible error envelope."""
    payload: dict[str, Any] = {
        "ok": False,
        "error": {
            "code": code,
            "message": message or DEFAULT_MESSAGES.get(code, "خطای سیستمی"),
            "details": details,
        },
    }
    if request_id:
        payload["request_id"] = request_id
    return payload


def to_envelope(exc: WrcError, request_id: str | None = None) -> dict[str, Any]:
    return error_envelope(exc.code, exc.message, exc.details, request_id)
