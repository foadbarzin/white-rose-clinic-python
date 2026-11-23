"""Synchronization tables: server dedupe, change feed, conflict queue."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base, UUIDPrimaryKeyMixin, utcnow

# SQLite can only autoincrement an INTEGER primary key; PG uses BIGSERIAL.
RevisionType = BigInteger().with_variant(Integer, "sqlite")


class SyncOperation(Base):
    """Server-side idempotency ledger for offline operation envelopes (TDR-007)."""

    __tablename__ = "sync_operations"

    op_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"), nullable=True
    )
    device_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    op_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    base_row_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint("op_type IN ('create','update','delete','command')", name="op_type"),
        CheckConstraint("status IN ('applied','rejected','conflict','duplicate')", name="status"),
        UniqueConstraint("device_id", "device_seq", name="uq_sync_operations_device_seq"),
        Index("ix_sync_operations_entity", "entity", "entity_id"),
        Index("ix_sync_operations_status", "status", "received_at"),
    )


class ChangeFeed(Base):
    """Monotonic change stream used by ``sync.pull`` (one row per applied change)."""

    __tablename__ = "change_feed"

    revision: Mapped[int] = mapped_column(RevisionType, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    op: Mapped[str] = mapped_column(String(8), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    origin_device_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("op IN ('upsert','delete')", name="op"),
        Index("ix_change_feed_entity_revision", "entity", "revision"),
    )


class SyncConflict(UUIDPrimaryKeyMixin, Base):
    """Open conflict that requires a manager decision (never auto-merged financially)."""

    __tablename__ = "sync_conflicts"

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"), nullable=True
    )
    op_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    client_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    server_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    resolution_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('state_conflict','version_conflict','validation','business_rule')",
            name="kind",
        ),
        CheckConstraint(
            "status IN ('open','resolved_client','resolved_server','discarded')", name="status"
        ),
        Index("ix_sync_conflicts_open", "status", "created_at"),
        Index("ix_sync_conflicts_entity", "entity", "entity_id"),
    )
