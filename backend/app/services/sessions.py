"""Opaque session lifecycle: create, validate (idle/absolute), revoke, list."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import Unauthorized
from app.core.security import SessionPolicy, hash_token, new_session_material
from app.database.models.identity import User, UserSession
from app.services.serializers import jsonable

TOUCH_THROTTLE_SECONDS = 60


def aware(value: datetime | None) -> datetime | None:
    """SQLite may return naive datetimes; all stored values are UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass
class SessionCheck:
    ok: bool
    reason: str | None = None
    session_row: UserSession | None = None
    user: User | None = None


class SessionService:
    @staticmethod
    def policy(settings: Settings | None = None) -> SessionPolicy:
        return SessionPolicy.from_settings(settings or get_settings())

    @classmethod
    def create(
        cls,
        db: Session,
        user: User,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_info: str | None = None,
        settings: Settings | None = None,
        now: datetime | None = None,
    ) -> tuple[UserSession, str]:
        policy = cls.policy(settings)
        current = now or datetime.now(timezone.utc)
        material = new_session_material(policy)

        active = cls.list_active(db, user.id, now=current)
        while len(active) >= policy.max_concurrent:
            oldest = active.pop(0)
            oldest.revoked_at = current
            oldest.revoke_reason = "max_concurrent"
            oldest.updated_at = current
            oldest.updated_by = user.id
            oldest.row_version = (oldest.row_version or 1) + 1
            db.flush()

        row = UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=material.token_hash,
            device_info=(device_info or "")[:255] or None,
            ip_address=(ip_address or "")[:45] or None,
            user_agent=(user_agent or "")[:255] or None,
            issued_at=material.issued_at,
            expires_at=material.expires_at,
            idle_expires_at=material.idle_expires_at,
            last_activity_at=material.issued_at,
            created_at=material.issued_at,
            created_by=user.id,
            updated_at=material.issued_at,
            updated_by=user.id,
            row_version=1,
        )
        db.add(row)
        db.flush()
        # the raw token leaves the service exactly once and is never persisted
        return row, material.token

    @classmethod
    def validate(
        cls,
        db: Session,
        token: str | None,
        *,
        settings: Settings | None = None,
        now: datetime | None = None,
        touch: bool = True,
    ) -> SessionCheck:
        if not token:
            return SessionCheck(ok=False, reason="missing")
        token_hash = hash_token(token)
        row = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
        if row is None:
            return SessionCheck(ok=False, reason="invalid")
        current = now or datetime.now(timezone.utc)

        if row.revoked_at is not None:
            return SessionCheck(ok=False, reason="revoked", session_row=row)
        expires_at = aware(row.expires_at)
        idle_expires_at = aware(row.idle_expires_at)
        if expires_at is None or expires_at <= current:
            return SessionCheck(ok=False, reason="expired", session_row=row)
        if idle_expires_at is None or idle_expires_at <= current:
            return SessionCheck(ok=False, reason="idle_expired", session_row=row)

        user = db.get(User, row.user_id)
        if user is None or user.is_deleted or not user.is_active:
            return SessionCheck(ok=False, reason="user_inactive", session_row=row, user=user)

        if touch:
            last_activity = aware(row.last_activity_at)
            throttle = TOUCH_THROTTLE_SECONDS
            if last_activity is None or (current - last_activity).total_seconds() >= throttle:
                row.last_activity_at = current
                row.idle_expires_at = current + timedelta(
                    seconds=cls.policy(settings).idle_timeout_seconds
                )
                row.updated_at = current
                row.row_version = (row.row_version or 1) + 1
                db.flush()
        return SessionCheck(ok=True, session_row=row, user=user)

    @staticmethod
    def revoke(
        db: Session,
        row: UserSession,
        *,
        reason: str,
        actor_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(timezone.utc)
        if row.revoked_at is None:
            row.revoked_at = current
        row.revoke_reason = reason[:64]
        row.updated_at = current
        row.updated_by = actor_id
        row.row_version = (row.row_version or 1) + 1
        db.flush()

    @classmethod
    def revoke_by_token(
        cls, db: Session, token: str | None, *, reason: str, actor_id: uuid.UUID | None = None
    ) -> UserSession | None:
        if not token:
            return None
        row = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
        if row is not None:
            cls.revoke(db, row, reason=reason, actor_id=actor_id)
        return row

    @classmethod
    def revoke_all_for_user(
        cls,
        db: Session,
        user_id: uuid.UUID,
        *,
        reason: str,
        actor_id: uuid.UUID | None = None,
        keep_session_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        current = now or datetime.now(timezone.utc)
        rows = list(
            db.scalars(
                select(UserSession).where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                )
            )
        )
        revoked = 0
        for row in rows:
            if keep_session_id is not None and row.id == keep_session_id:
                continue
            cls.revoke(db, row, reason=reason, actor_id=actor_id, now=current)
            revoked += 1
        return revoked

    @classmethod
    def list_active(
        cls,
        db: Session,
        user_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> list[UserSession]:
        current = now or datetime.now(timezone.utc)
        rows = list(
            db.scalars(
                select(UserSession)
                .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
                .order_by(UserSession.issued_at.asc())
            )
        )
        return [
            row
            for row in rows
            if (aware(row.expires_at) or current) > current
            and (aware(row.idle_expires_at) or current) > current
        ]

    @staticmethod
    def require_valid_token(token: str | None, db: Session) -> SessionCheck:
        check = SessionService.validate(db, token)
        if not check.ok:
            raise Unauthorized(message="نشست معتبر نیست. دوباره وارد شوید.")
        return check

    @staticmethod
    def serialize(
        row: UserSession, *, current_session_id: uuid.UUID | None = None
    ) -> dict[str, object]:
        return {
            "id": str(row.id),
            "device_info": row.device_info,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "issued_at": jsonable(row.issued_at),
            "expires_at": jsonable(row.expires_at),
            "idle_expires_at": jsonable(row.idle_expires_at),
            "last_activity_at": jsonable(row.last_activity_at),
            "revoked_at": jsonable(row.revoked_at),
            "revoke_reason": row.revoke_reason,
            "current": bool(current_session_id and row.id == current_session_id),
        }

