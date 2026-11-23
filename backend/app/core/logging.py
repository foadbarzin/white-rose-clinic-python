"""Structured JSON logging with request correlation (no secrets in logs)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Final

from app.core.config import Settings

REQUEST_ID_HEADER: Final = "X-Request-Id"
_request_id: ContextVar[str] = ContextVar("wrc_request_id", default="")

_STANDARD_LOG_KEYS: Final = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
}


def set_request_id(value: str) -> None:
    _request_id.set(value or "")


def get_request_id() -> str:
    return _request_id.get()


class JsonLogFormatter(logging.Formatter):
    """Render every log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - stdlib API
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "") or get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_KEYS or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings, stream: Any | None = None) -> logging.Logger:
    """Configure the root logger once (idempotent)."""
    root = logging.getLogger()
    level = logging.DEBUG if settings.debug else logging.INFO
    root.setLevel(level)

    handler = None
    for existing in root.handlers:
        if getattr(existing, "_wrc_json_handler", False):
            handler = existing
            break

    if handler is None:
        handler = logging.StreamHandler(stream or sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        handler._wrc_json_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    # Reduce noisy access logs into our structured output.
    logging.getLogger("uvicorn.access").propagate = True
    return logging.getLogger("white_rose_clinic")
