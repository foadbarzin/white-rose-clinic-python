"""Serialization helpers: UTC storage → Asia/Tehran ISO strings, safe money."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def _tz() -> ZoneInfo:
    return get_settings().tzinfo


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def iso_local(value: datetime | None) -> str | None:
    """Persian-facing timestamp in the clinic timezone (Asia/Tehran)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_tz()).isoformat()


def iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def money(value: Decimal | int | float | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantized = value.quantize(Decimal("0.1"))
    return format(quantized, "f")


def as_id(value: uuid.UUID | str | None) -> str | None:
    return str(value) if value is not None else None


def jsonable(value: Any) -> Any:
    """Recursively convert values into JSON-safe primitives."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return iso_local(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value
