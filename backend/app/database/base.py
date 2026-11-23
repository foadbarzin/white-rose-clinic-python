"""Declarative base, shared column mixins and UUIDv7 generation.

Every domain table carries the same audit/soft-delete/sync columns so that
PostgreSQL (server) and SQLite (desktop agent) share one logical schema
(see ``docs/architecture/DATABASE_DESIGN.md`` §۲).
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    MetaData,
    Numeric,
    Uuid,
    false,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# money is stored in Toman with exactly one decimal digit (= whole Rial, DEC-05)
MONEY_PRECISION = 18
MONEY_SCALE = 1
QUANTITY_PRECISION = 12
QUANTITY_SCALE = 2
RATE_PRECISION = 5
RATE_SCALE = 2

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp (all stored timestamps are UTC)."""
    return datetime.now(timezone.utc)


def money_type() -> Numeric:
    """Toman amount with one decimal digit (nearest whole Rial)."""
    return Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True)


def quantity_type() -> Numeric:
    return Numeric(QUANTITY_PRECISION, QUANTITY_SCALE, asdecimal=True)


def rate_type() -> Numeric:
    return Numeric(RATE_PRECISION, RATE_SCALE, asdecimal=True)


_uuid_lock = threading.Lock()
_last_ms: int = 0
_last_seq: int = 0


def uuid7() -> uuid.UUID:
    """Generate a time-ordered UUIDv7 (TDR-005).

    Layout (RFC 9562): 48-bit unix_ts_ms | version 7 | 12-bit counter | variant | 62 random bits.
    """
    global _last_ms, _last_seq
    with _uuid_lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms < _last_ms:
            now_ms = _last_ms
        if now_ms == _last_ms:
            _last_seq = (_last_seq + 1) & 0xFFF
            if _last_seq == 0:
                now_ms = _last_ms + 1
        else:
            _last_seq = random.getrandbits(12)
        _last_ms = now_ms
        seq = _last_seq
    rand_b = random.getrandbits(62)
    value = (
        ((now_ms & ((1 << 48) - 1)) << 80)
        | (0x7 << 76)
        | (seq << 64)
        | (0b10 << 62)
        | rand_b
    )
    return uuid.UUID(int=value)


class Base(DeclarativeBase):
    """Declarative base with a deterministic constraint naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Time-ordered UUID primary key generated on the client (offline-ready)."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class TimestampMixin:
    """Created/updated audit columns plus optimistic-lock row version."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    row_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default=text("1")
    )


class SoftDeleteMixin:
    """Soft delete: rows are never physically removed by user operations."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class SyncColumnsMixin:
    """Synchronization metadata shared by server and desktop agent."""

    origin_node_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


class EntityMixin(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, SyncColumnsMixin):
    """Full column set used by all domain entities."""

    __abstract__ = True
