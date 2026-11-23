"""System-level tables: meta, settings, sequences, audit, devices, backups."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base, EntityMixin, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Meta(Base):
    """Key/value system metadata (schema version, installation id, ...)."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class Setting(Base):
    """Business settings — validated against the catalog in code."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(12), nullable=False, server_default="text")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("value_type IN ('boolean','number','text')", name="value_type"),
    )


class Sequence(Base):
    """Server-side counters (official invoice numbers only, never offline)."""

    __tablename__ = "sequences"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_value: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default=text("1")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only audit trail with a hash chain (never updated/deleted)."""

    __tablename__ = "audit_log"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_username: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(8), nullable=False, server_default="ok")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    context: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hash_prev: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_self: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint("result IN ('ok','fail')", name="result"),
        Index("ix_audit_log_entity_time", "entity", "entity_id", "occurred_at"),
        Index("ix_audit_log_action_time", "action", "occurred_at"),
    )


class Device(EntityMixin, Base):
    """Registered desktop agent (sync identity, node code for provisional numbers)."""

    __tablename__ = "devices"

    node_code: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    device_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    enrolled_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_pull_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=false())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("node_code", name="uq_devices_node_code"),
        UniqueConstraint("device_token_hash", name="uq_devices_device_token_hash"),
    )


class BackupJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Metadata of backup/restore operations (files live outside the database)."""

    __tablename__ = "backup_jobs"

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="running")
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    row_counts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('manual','scheduled','pre_restore','pre_wipe')", name="kind"),
        CheckConstraint("status IN ('running','ok','failed')", name="status"),
    )

