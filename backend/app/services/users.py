"""User administration: CRUD-lite, state changes, sessions and activity."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import Duplicate, Forbidden, NotFound, ValidationFailure
from app.core.permissions import DOCTOR, OPERATOR
from app.core.security import hash_password, validate_password_strength
from app.database.models.identity import User
from app.database.models.system import AuditLog
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.context import ActorContext
from app.services.rbac import RbacService
from app.services.serializers import jsonable
from app.services.sessions import SessionService, aware

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserService:
    @staticmethod
    def _serialize(db: Session, user: User, roles: list | None = None) -> dict[str, object]:
        role_objs = roles if roles is not None else RbacService.roles_for_user(db, user.id)
        active_sessions = len(SessionService.list_active(db, user.id))
        locked = False
        locked_until = aware(user.locked_until)
        if locked_until is not None and locked_until > _utcnow():
            locked = True
        return {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "roles": [role.code for role in role_objs],
            "role_names": [role.name for role in role_objs],
            "linked_doctor_id": str(user.linked_doctor_id) if user.linked_doctor_id else "",
            "linked_operator_id": str(user.linked_operator_id) if user.linked_operator_id else "",
            "is_active": bool(user.is_active),
            "must_change_password": bool(user.must_change_password),
            "failed_attempts": int(user.failed_attempts or 0),
            "locked": locked,
            "locked_until": jsonable(user.locked_until),
            "last_login_at": jsonable(user.last_login_at),
            "active_sessions": active_sessions,
            "created_at": jsonable(user.created_at),
        }

    @classmethod
    def list_users(cls, db: Session, *, q: str | None = None, include_inactive: bool = True) -> dict:
        stmt = select(User).where(User.is_deleted.is_(False))
        if not include_inactive:
            stmt = stmt.where(User.is_active.is_(True))
        if q:
            needle = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.username).like(needle),
                    func.lower(User.display_name).like(needle),
                )
            )
        users = list(db.scalars(stmt.order_by(User.username)))
        roles_map = RbacService.roles_by_user(db, [user.id for user in users])
        return {
            "rows": [cls._serialize(db, user, roles_map.get(user.id, [])) for user in users],
            "count": len(users),
        }

    @classmethod
    def get_user(cls, db: Session, user_id: uuid.UUID | str) -> dict[str, object]:
        user = AuthService.require_user(db, user_id)
        payload = cls._serialize(db, user)
        payload["permissions"] = sorted(RbacService.effective_permissions(db, user.id))
        payload["roles_detail"] = [
            {
                "code": role.code,
                "name": role.name,
                "is_system": bool(role.is_system),
                "is_active": bool(role.is_active),
            }
            for role in RbacService.roles_for_user(db, user.id)
        ]
        return payload

    @classmethod
    def create_user(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        role_codes: list[str] | None = None,
        linked_doctor_id: str | None = None,
        linked_operator_id: str | None = None,
        must_change_password: bool = True,
        settings: Settings | None = None,
    ) -> dict[str, object]:
        settings = settings or get_settings()
        normalized = (username or "").strip().lower()
        if not USERNAME_PATTERN.match(normalized):
            raise ValidationFailure(
                message="نام کاربری نامعتبر است (۳ تا ۶۴ نویسه؛ حروف کوچک، عدد، نقطه، خط تیره)."
            )
        if db.scalar(
            select(func.count()).select_from(User).where(func.lower(User.username) == normalized)
        ):
            raise Duplicate(message="نام کاربری تکراری است.")
        validate_password_strength(password, username=normalized)

        doctor_id = cls._optional_uuid(linked_doctor_id, "شناسه پزشک")
        operator_id = cls._optional_uuid(linked_operator_id, "شناسه اپراتور")
        codes = [str(code).strip().lower() for code in (role_codes or []) if str(code).strip()]
        if DOCTOR in codes and doctor_id is None:
            raise ValidationFailure(message="برای نقش پزشک، انتخاب پزشک مرتبط الزامی است.")

        hashed = hash_password(
            password,
            pepper=settings.secret_key,
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
        )
        now = _utcnow()
        user = User(
            id=uuid.uuid4(),
            username=normalized,
            password_hash=hashed.encoded,
            password_algo=hashed.algo,
            password_params=hashed.params,
            display_name=(display_name or normalized).strip()[:120],
            role=OPERATOR,  # projection; corrected by role assignment below
            linked_doctor_id=doctor_id,
            linked_operator_id=operator_id,
            is_active=True,
            must_change_password=bool(must_change_password),
            failed_attempts=0,
            created_at=now,
            created_by=actor.user_id,
            updated_at=now,
            updated_by=actor.user_id,
            row_version=1,
        )
        db.add(user)
        db.flush()
        assigned: list[str] = []
        if codes:
            result = RbacService.assign_roles(db, actor, user_id=user.id, role_codes=codes)
            assigned = list(result["roles"])
        db.flush()
        AuditService.log(
            db,
            action="user.created",
            entity="users",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={
                "username": user.username,
                "display_name": user.display_name,
                "roles": assigned,
                "must_change_password": bool(user.must_change_password),
            },
        )
        return cls.get_user(db, user.id)

    @staticmethod
    def _optional_uuid(value: str | None, label: str) -> uuid.UUID | None:
        if not value:
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError):
            raise ValidationFailure(message=f"{label} معتبر نیست.") from None

    # ------------------------------------------------------------- mutations
    @staticmethod
    def _assert_not_self(actor: ActorContext, user: User) -> None:
        if actor.user_id is not None and actor.user_id == user.id:
            raise Forbidden(message="این عملیات روی حساب خودتان مجاز نیست.")

    @classmethod
    def _assert_not_last_rbac_holder(cls, db: Session, user: User) -> None:
        if "rbac.manage" in RbacService.effective_permissions(db, user.id):
            others = RbacService.count_active_holders(
                db, "rbac.manage", exclude_user_id=user.id
            )
            if others == 0:
                raise Forbidden(message="این کاربر آخرین دارندهٔ دسترسی مدیریت نقش‌ها است.")

    @classmethod
    def update_user(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        user_id: uuid.UUID | str,
        display_name: str | None = None,
        linked_doctor_id: str | None = None,
        linked_operator_id: str | None = None,
        must_change_password: bool | None = None,
    ) -> dict[str, object]:
        user = AuthService.require_user(db, user_id)
        before = {
            "display_name": user.display_name,
            "linked_doctor_id": str(user.linked_doctor_id) if user.linked_doctor_id else "",
            "linked_operator_id": str(user.linked_operator_id) if user.linked_operator_id else "",
            "must_change_password": bool(user.must_change_password),
        }
        if display_name is not None:
            cleaned = str(display_name).strip()
            if not cleaned:
                raise ValidationFailure(message="نام نمایشی الزامی است.")
            user.display_name = cleaned[:120]
        if linked_doctor_id is not None:
            user.linked_doctor_id = cls._optional_uuid(linked_doctor_id, "شناسه پزشک")
        if linked_operator_id is not None:
            user.linked_operator_id = cls._optional_uuid(linked_operator_id, "شناسه اپراتور")
        if must_change_password is not None:
            user.must_change_password = bool(must_change_password)
        user.updated_at = _utcnow()
        user.updated_by = actor.user_id
        user.row_version = (user.row_version or 1) + 1
        db.flush()
        after = {
            "display_name": user.display_name,
            "linked_doctor_id": str(user.linked_doctor_id) if user.linked_doctor_id else "",
            "linked_operator_id": str(user.linked_operator_id) if user.linked_operator_id else "",
            "must_change_password": bool(user.must_change_password),
        }
        AuditService.log(
            db,
            action="user.updated",
            entity="users",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            before=before,
            details=after,
        )
        return cls.get_user(db, user.id)

    @classmethod
    def set_active(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        user_id: uuid.UUID | str,
        active: bool,
    ) -> dict[str, object]:
        user = AuthService.require_user(db, user_id)
        if not active:
            cls._assert_not_self(actor, user)
            cls._assert_not_last_rbac_holder(db, user)
        if bool(user.is_active) == bool(active):
            return cls.get_user(db, user.id)
        user.is_active = bool(active)
        user.updated_at = _utcnow()
        user.updated_by = actor.user_id
        user.row_version = (user.row_version or 1) + 1
        db.flush()
        revoked = 0
        if not active:
            revoked = SessionService.revoke_all_for_user(
                db, user.id, reason="user_disabled", actor_id=actor.user_id
            )
        AuditService.log(
            db,
            action="user.enabled" if active else "user.disabled",
            entity="users",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"username": user.username, "sessions_revoked": revoked},
        )
        return cls.get_user(db, user.id)

    @classmethod
    def unlock(
        cls, db: Session, actor: ActorContext, *, user_id: uuid.UUID | str
    ) -> dict[str, object]:
        user = AuthService.require_user(db, user_id)
        user.failed_attempts = 0
        user.locked_until = None
        user.updated_at = _utcnow()
        user.updated_by = actor.user_id
        user.row_version = (user.row_version or 1) + 1
        db.flush()
        AuditService.log(
            db,
            action="account.unlocked",
            entity="users",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"username": user.username},
        )
        return cls.get_user(db, user.id)

    @classmethod
    def reset_password(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        user_id: uuid.UUID | str,
        new_password: str,
        settings: Settings | None = None,
    ) -> dict[str, object]:
        settings = settings or get_settings()
        user = AuthService.require_user(db, user_id)
        validate_password_strength(new_password, username=user.username)
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
        user.must_change_password = True
        user.failed_attempts = 0
        user.locked_until = None
        user.updated_at = now
        user.updated_by = actor.user_id
        user.row_version = (user.row_version or 1) + 1
        db.flush()
        revoked = SessionService.revoke_all_for_user(
            db, user.id, reason="password_reset", actor_id=actor.user_id, now=now
        )
        AuditService.log(
            db,
            action="user.password_reset",
            entity="users",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"username": user.username, "sessions_revoked": revoked},
        )
        return {"ok": True, "user": cls.get_user(db, user.id), "sessions_revoked": revoked}

    @classmethod
    def list_sessions(
        cls, db: Session, *, user_id: uuid.UUID | str, current_session_id: uuid.UUID | None = None
    ) -> dict[str, object]:
        user = AuthService.require_user(db, user_id)
        rows = SessionService.list_active(db, user.id)
        return {
            "user_id": str(user.id),
            "sessions": [
                SessionService.serialize(row, current_session_id=current_session_id) for row in rows
            ],
            "count": len(rows),
        }

    @classmethod
    def revoke_sessions(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        user_id: uuid.UUID | str,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, object]:
        user = AuthService.require_user(db, user_id)
        note = (reason or "admin_revoke").strip()[:64]
        revoked = 0
        if session_id:
            try:
                key = uuid.UUID(str(session_id))
            except (ValueError, TypeError):
                raise ValidationFailure(message="شناسهٔ نشست معتبر نیست.") from None
            row = db.get(UserSession, key)
            if row is None or row.user_id != user.id:
                raise NotFound(message="نشست یافت نشد.")
            if row.revoked_at is None:
                SessionService.revoke(db, row, reason=note, actor_id=actor.user_id)
                revoked = 1
        else:
            revoked = SessionService.revoke_all_for_user(
                db, user.id, reason=note, actor_id=actor.user_id
            )
        AuditService.log(
            db,
            action="auth.session_revoked",
            entity="users",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={
                "username": user.username,
                "session_id": session_id,
                "sessions_revoked": revoked,
                "reason": note,
            },
        )
        return {"ok": True, "sessions_revoked": revoked}

    @classmethod
    def activity(
        cls,
        db: Session,
        *,
        user_id: uuid.UUID | str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        user = AuthService.require_user(db, user_id)
        condition = or_(
            AuditLog.actor_user_id == user.id,
            (AuditLog.entity == "users") & (AuditLog.entity_id == str(user.id)),
        )
        total = int(db.scalar(select(func.count()).select_from(AuditLog).where(condition)) or 0)
        rows = list(
            db.scalars(
                select(AuditLog)
                .where(condition)
                .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
                .limit(max(1, min(limit, 200)))
                .offset(max(0, offset))
            )
        )
        return {
            "user_id": str(user.id),
            "username": user.username,
            "rows": [AuditService.serialize(row) for row in rows],
            "total": total,
        }




