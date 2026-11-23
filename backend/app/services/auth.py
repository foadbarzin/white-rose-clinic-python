"""Authentication: login, logout, password change and user projection."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AuthFailed,
    AuthLocked,
    Forbidden,
    NotFound,
    Unauthorized,
    ValidationFailure,
)
from app.core.permissions import Principal
from app.core.security import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.database.models.identity import User
from app.database.models.rbac import Role, UserRole
from app.services.audit import AuditService
from app.services.context import ActorContext
from app.services.rbac import RbacService
from app.services.serializers import jsonable
from app.services.sessions import SessionService

UNIFORM_AUTH_MESSAGE = "نام کاربری یا رمز عبور نادرست است."
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    """A throwaway hash so unknown usernames cost the same as wrong passwords."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing", pepper="dummy-pepper").encoded
    return _DUMMY_HASH


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    # ----------------------------------------------------------------- helpers
    @staticmethod
    def find_user(db: Session, username: str) -> User | None:
        normalized = (username or "").strip().lower()
        if not normalized:
            return None
        return db.scalar(
            select(User).where(
                func.lower(User.username) == normalized,
                User.is_deleted.is_(False),
            )
        )

    @classmethod
    def effective_permissions(cls, db: Session, user_id: uuid.UUID) -> frozenset[str]:
        return RbacService.effective_permissions(db, user_id)

    @classmethod
    def serialize_user(cls, db: Session, user: User, *, with_permissions: bool = False) -> dict:
        roles = RbacService.roles_for_user(db, user.id)
        payload: dict[str, object] = {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,  # legacy projection for the existing UI
            "roles": [role.code for role in roles],
            "role_names": [role.name for role in roles],
            "linked_doctor_id": str(user.linked_doctor_id) if user.linked_doctor_id else "",
            "linked_operator_id": str(user.linked_operator_id) if user.linked_operator_id else "",
            "is_active": bool(user.is_active),
            "must_change_password": bool(user.must_change_password),
            "failed_attempts": int(user.failed_attempts or 0),
            "locked_until": jsonable(user.locked_until),
            "last_login_at": jsonable(user.last_login_at),
            "created_at": jsonable(user.created_at),
        }
        if with_permissions:
            payload["permissions"] = sorted(cls.effective_permissions(db, user.id))
        return payload

    @staticmethod
    def principal_for(db: Session, user: User, session_id: uuid.UUID | None = None) -> Principal:
        permissions = RbacService.effective_permissions(db, user.id)
        return Principal(
            user_id=str(user.id),
            username=user.username,
            role=user.role,
            linked_doctor_id=str(user.linked_doctor_id) if user.linked_doctor_id else None,
            linked_operator_id=str(user.linked_operator_id) if user.linked_operator_id else None,
            permissions=permissions,
            must_change_password=bool(user.must_change_password),
            session_id=str(session_id) if session_id else None,
        )

    # ------------------------------------------------------------------ login
    @classmethod
    def login(
        cls,
        db: Session,
        *,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_info: str | None = None,
        request_id: str | None = None,
        settings: Settings | None = None,
    ) -> dict[str, object]:
        settings = settings or get_settings()
        now = _utcnow()
        username_norm = (username or "").strip().lower()
        user = cls.find_user(db, username_norm)

        if user is None:
            # equalize timing and never reveal whether the account exists
            verify_password(password or "", _dummy_hash(), pepper=settings.secret_key)
            AuditService.log(
                db,
                action="auth.login_failed",
                entity="users",
                entity_id=username_norm[:64] or None,
                result="fail",
                actor_username=username_norm[:64],
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                details={"reason": "unknown_user"},
            )
            db.commit()
            raise AuthFailed(message=UNIFORM_AUTH_MESSAGE)

        locked_until = user.locked_until
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until is not None and locked_until > now:
            minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
            AuditService.log(
                db,
                action="auth.login_blocked",
                entity="users",
                entity_id=user.id,
                result="fail",
                actor_user_id=user.id,
                actor_username=user.username,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                details={"reason": "locked"},
            )
            db.commit()
            raise AuthLocked(
                message=f"حساب موقتاً قفل شده است. پس از {minutes} دقیقه دوباره تلاش کنید."
            )

        if not user.is_active:
            verify_password(password or "", user.password_hash, pepper=settings.secret_key)
            AuditService.log(
                db,
                action="auth.login_failed",
                entity="users",
                entity_id=user.id,
                result="fail",
                actor_user_id=user.id,
                actor_username=user.username,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                details={"reason": "inactive"},
            )
            db.commit()
            raise AuthFailed(message=UNIFORM_AUTH_MESSAGE)

        if not verify_password(password or "", user.password_hash, pepper=settings.secret_key):
            cls._record_failure(db, user, settings, now, ip_address, user_agent, request_id)
            AuditService.log(
                db,
                action="auth.login_failed",
                entity="users",
                entity_id=user.id,
                result="fail",
                actor_user_id=user.id,
                actor_username=user.username,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                details={"reason": "bad_password"},
            )
            db.commit()
            raise AuthFailed(message=UNIFORM_AUTH_MESSAGE)

        user.failed_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        user.updated_at = now
        user.row_version = (user.row_version or 1) + 1
        db.flush()

        row, token = SessionService.create(
            db,
            user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info=device_info,
            settings=settings,
            now=now,
        )
        AuditService.log(
            db,
            action="auth.login_success",
            entity="users",
            entity_id=user.id,
            actor_user_id=user.id,
            actor_username=user.username,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            details={"session_id": str(row.id)},
        )
        db.flush()
        return {
            "token": token,
            "user": cls.serialize_user(db, user, with_permissions=True),
            "mustChangePassword": bool(user.must_change_password),
            "session": SessionService.serialize(row, current_session_id=row.id),
        }

    @classmethod
    def _record_failure(
        cls,
        db: Session,
        user: User,
        settings: Settings,
        now: datetime,
        ip_address: str | None,
        user_agent: str | None,
        request_id: str | None,
    ) -> int:
        attempts = int(user.failed_attempts or 0) + 1
        user.failed_attempts = attempts
        user.updated_at = now
        user.row_version = (user.row_version or 1) + 1
        if attempts >= settings.login_max_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            user.failed_attempts = 0
            AuditService.log(
                db,
                action="account.locked",
                entity="users",
                entity_id=user.id,
                actor_user_id=user.id,
                actor_username=user.username,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                details={"locked_minutes": settings.login_lock_minutes},
            )
        db.flush()
        return attempts

    # ------------------------------------------------------------- passwords
    @classmethod
    def change_password(
        cls,
        db: Session,
        *,
        user: User,
        old_password: str,
        new_password: str,
        current_session_id: uuid.UUID | None,
        actor: ActorContext,
        settings: Settings | None = None,
    ) -> dict[str, object]:
        settings = settings or get_settings()
        if not verify_password(old_password or "", user.password_hash, pepper=settings.secret_key):
            AuditService.log(
                db,
                action="auth.password_change_failed",
                entity="users",
                entity_id=user.id,
                result="fail",
                actor_user_id=user.id,
                actor_username=user.username,
                ip_address=actor.ip_address,
                user_agent=actor.user_agent,
                request_id=actor.request_id,
                details={"reason": "bad_old_password"},
            )
            raise AuthFailed(message="رمز فعلی نادرست است.")
        validate_password_strength(new_password, username=user.username)
        if verify_password(new_password, user.password_hash, pepper=settings.secret_key):
            raise ValidationFailure(message="رمز جدید نباید با رمز فعلی یکسان باشد.")
        hashed = hash_password(
            new_password,
            pepper=settings.secret_key,
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
        )
        now = _utcnow()
        user.password_hash = hashed.encoded
        user.password_algo = hashed.algo
        user.password_params = hashed.params
        user.must_change_password = False
        user.last_password_change_at = now
        user.updated_at = now
        user.row_version = (user.row_version or 1) + 1
        db.flush()
        revoked = SessionService.revoke_all_for_user(
            db,
            user.id,
            reason="password_change",
            actor_id=user.id,
            keep_session_id=current_session_id,
            now=now,
        )
        AuditService.log(
            db,
            action="auth.password_changed",
            entity="users",
            entity_id=user.id,
            actor_user_id=user.id,
            actor_username=user.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"sessions_revoked": revoked},
        )
        return {"ok": True, "sessions_revoked": revoked}

    # ---------------------------------------------------------------- logout
    @classmethod
    def logout(
        cls,
        db: Session,
        *,
        token: str,
        session_row,
        actor: ActorContext,
    ) -> dict[str, object]:
        SessionService.revoke_by_token(db, token, reason="logout", actor_id=actor.user_id)
        AuditService.log(
            db,
            action="auth.logout",
            entity="users",
            entity_id=actor.user_id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"session_id": str(session_row.id) if session_row else None},
        )
        return {"ok": True}

    @classmethod
    def logout_all(
        cls,
        db: Session,
        *,
        user: User,
        actor: ActorContext,
    ) -> dict[str, object]:
        revoked = SessionService.revoke_all_for_user(
            db, user.id, reason="logout_all", actor_id=user.id
        )
        AuditService.log(
            db,
            action="auth.logout_all",
            entity="users",
            entity_id=user.id,
            actor_user_id=user.id,
            actor_username=user.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"sessions_revoked": revoked},
        )
        return {"ok": True, "sessions_revoked": revoked}

    @staticmethod
    def require_user(db: Session, user_id: uuid.UUID | str) -> User:
        try:
            key = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            raise NotFound(message="کاربر یافت نشد.") from None
        user = db.get(User, key)
        if user is None or user.is_deleted:
            raise NotFound(message="کاربر یافت نشد.")
        return user


