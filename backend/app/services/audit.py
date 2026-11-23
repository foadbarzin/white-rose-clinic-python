"""Structured, append-only audit trail with a hash chain.

Rules (phase 3):
  * secrets are never written (password/token/secret/hash/... keys are dropped);
  * rows are only inserted — there is no update/delete service;
  * sensitive operations call :meth:`AuditService.log` inside their transaction;
  * ``hash_prev``/``hash_self`` make silent tampering detectable.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models.system import AuditLog
from app.services.serializers import jsonable

_SENSITIVE_MARKERS = ("password", "token", "secret", "salt", "credential", "private_key")
_SAFE_KEYS = frozenset({"must_change_password"})

_timestamp_lock = threading.Lock()
_last_timestamp: datetime | None = None


def _next_timestamp() -> datetime:
    """Monotonic, unique timestamps so the hash chain can be verified by order."""
    global _last_timestamp
    with _timestamp_lock:
        now = datetime.now(timezone.utc)
        if _last_timestamp is not None and now <= _last_timestamp:
            now = _last_timestamp + timedelta(microseconds=1)
        _last_timestamp = now
        return now


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _SAFE_KEYS:
                clean[str(key)] = _sanitize(item, depth + 1)
            elif any(marker in lowered for marker in _SENSITIVE_MARKERS):
                clean[str(key)] = "[redacted]"
            else:
                clean[str(key)] = _sanitize(item, depth + 1)
        return clean
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "…"
    return jsonable(value)


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


class AuditService:
    """Write and read audit events (no mutation API by design)."""

    @staticmethod
    def _last_hash(session: Session) -> str | None:
        row = session.execute(
            select(AuditLog.hash_self).order_by(AuditLog.occurred_at.desc()).limit(1)
        ).first()
        return str(row[0]) if row and row[0] else None

    @classmethod
    def log(
        cls,
        session: Session,
        *,
        action: str,
        entity: str,
        entity_id: str | uuid.UUID | None = None,
        result: str = "ok",
        actor_user_id: uuid.UUID | None = None,
        actor_username: str = "",
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        message: str | None = None,
        request_id: str | uuid.UUID | None = None,
    ) -> AuditLog:
        occurred_at = _next_timestamp()
        clean_details = _sanitize(details or {})
        clean_before = _sanitize(before or {})
        correlation: uuid.UUID | None
        if isinstance(request_id, uuid.UUID):
            correlation = request_id
        else:
            try:
                correlation = uuid.UUID(str(request_id)) if request_id else None
            except (ValueError, TypeError):
                correlation = None

        prev_hash = cls._last_hash(session)
        body = {
            "at": occurred_at.isoformat(),
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "result": result,
            "actor": actor_username or "",
            "details": clean_details,
            "before": clean_before,
        }
        digest_input = f"{prev_hash or ''}|{_canonical(body)}"
        hash_self = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()

        row = AuditLog(
            id=uuid.uuid4(),
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            actor_username=(actor_username or "")[:64],
            action=action[:64],
            entity=entity[:40],
            entity_id=str(entity_id) if entity_id is not None else None,
            before_json=clean_before or None,
            after_json=clean_details or None,
            result=result,
            message=(message or "")[:2000] or None,
            request_id=correlation,
            context=None,
            ip_address=ip_address or None,
            user_agent=(user_agent or None) if user_agent else None,
            hash_prev=prev_hash,
            hash_self=hash_self,
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def serialize(row: AuditLog) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "occurred_at": jsonable(row.occurred_at),
            "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
            "actor_username": row.actor_username,
            "action": row.action,
            "entity": row.entity,
            "entity_id": row.entity_id,
            "result": row.result,
            "message": row.message,
            "details": row.after_json or {},
            "before": row.before_json or {},
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "request_id": str(row.request_id) if row.request_id else None,
            "hash_prev": row.hash_prev,
            "hash_self": row.hash_self,
        }

    @classmethod
    def list_events(
        cls,
        session: Session,
        *,
        action: str | None = None,
        entity: str | None = None,
        entity_id: str | None = None,
        actor_user_id: uuid.UUID | str | None = None,
        result: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        conditions = []
        if action:
            conditions.append(AuditLog.action == action)
        if entity:
            conditions.append(AuditLog.entity == entity)
        if entity_id:
            conditions.append(AuditLog.entity_id == str(entity_id))
        if actor_user_id:
            try:
                conditions.append(AuditLog.actor_user_id == uuid.UUID(str(actor_user_id)))
            except (ValueError, TypeError):
                conditions.append(AuditLog.actor_user_id.is_(None))
        if result:
            conditions.append(AuditLog.result == result)
        if occurred_from is not None:
            conditions.append(AuditLog.occurred_at >= occurred_from)
        if occurred_to is not None:
            conditions.append(AuditLog.occurred_at <= occurred_to)

        base = select(AuditLog)
        count_stmt = select(func.count()).select_from(AuditLog)
        for condition in conditions:
            base = base.where(condition)
            count_stmt = count_stmt.where(condition)

        total = int(session.scalar(count_stmt) or 0)
        rows = list(
            session.scalars(
                base.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
                .limit(max(1, min(limit, 200)))
                .offset(max(0, offset))
            )
        )
        return rows, total

    @classmethod
    def get(cls, session: Session, event_id: uuid.UUID | str) -> AuditLog | None:
        try:
            key = uuid.UUID(str(event_id))
        except (ValueError, TypeError):
            return None
        return session.get(AuditLog, key)

    @classmethod
    def verify_chain(cls, session: Session, rows: Iterable[AuditLog]) -> bool:
        """Verify hash linkage for a chronological sequence of rows."""
        previous: str | None = None
        for row in rows:
            occurred = row.occurred_at
            if occurred.tzinfo is None:
                occurred = occurred.replace(tzinfo=timezone.utc)
            body = {
                "at": occurred.astimezone(timezone.utc).isoformat(),
                "action": row.action,
                "entity": row.entity,
                "entity_id": row.entity_id,
                "result": row.result,
                "actor": row.actor_username or "",
                "details": row.after_json or {},
                "before": row.before_json or {},
            }
            expected = hashlib.sha256(
                f"{previous or ''}|{_canonical(body)}".encode("utf-8")
            ).hexdigest()
            if expected != row.hash_self:
                return False
            previous = row.hash_self
        return True

