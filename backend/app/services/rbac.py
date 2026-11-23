"""RBAC service: roles, permission assignment and effective permissions."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import Duplicate, Forbidden, NotFound, ValidationFailure
from app.core.permissions import (
    ADMIN,
    DOCTOR,
    OPERATOR,
    PERMISSION_CODES,
    PERMISSIONS,
    PERMISSIONS_BY_MODULE,
    legacy_role_for_role_codes,
)
from app.database.models.identity import User
from app.database.models.rbac import Role, RolePermission, UserRole
from app.services.audit import AuditService
from app.services.context import ActorContext
from app.services.serializers import jsonable

ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
MAX_PERMISSIONS_PER_ROLE = 200
SYSTEM_ROLE_CODE = "owner"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RbacService:
    # ------------------------------------------------------------------ reads
    @staticmethod
    def permissions_catalog() -> dict[str, object]:
        return {
            "permissions": [
                {"code": p.code, "module": p.module, "description": p.description}
                for p in PERMISSIONS
            ],
            "modules": [
                {
                    "module": module,
                    "permissions": [
                        {"code": p.code, "description": p.description} for p in items
                    ],
                }
                for module, items in PERMISSIONS_BY_MODULE.items()
            ],
        }

    @staticmethod
    def roles_by_user(db: Session, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[Role]]:
        ids = list(user_ids)
        if not ids:
            return {}
        rows = db.execute(
            select(UserRole.user_id, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(ids))
            .order_by(Role.code)
        ).all()
        grouped: dict[uuid.UUID, list[Role]] = {}
        for user_id, role in rows:
            grouped.setdefault(user_id, []).append(role)
        return grouped

    @classmethod
    def roles_for_user(cls, db: Session, user_id: uuid.UUID) -> list[Role]:
        return list(
            db.scalars(
                select(Role)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
                .order_by(Role.code)
            )
        )

    @classmethod
    def role_codes_for_user(cls, db: Session, user_id: uuid.UUID) -> list[str]:
        return [role.code for role in cls.roles_for_user(db, user_id)]

    @classmethod
    def effective_permissions(cls, db: Session, user_id: uuid.UUID) -> frozenset[str]:
        rows = db.scalars(
            select(RolePermission.permission_code)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Role.is_active.is_(True),
                Role.is_deleted.is_(False),
            )
        )
        return frozenset(code for code in rows if code in PERMISSION_CODES)

    @classmethod
    def list_roles(cls, db: Session) -> list[dict[str, object]]:
        counts = dict(
            db.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id)).all()
        )
        roles = list(
            db.scalars(select(Role).where(Role.is_deleted.is_(False)).order_by(Role.code))
        )
        result: list[dict[str, object]] = []
        for role in roles:
            perms = list(
                db.scalars(
                    select(RolePermission.permission_code)
                    .where(RolePermission.role_id == role.id)
                    .order_by(RolePermission.permission_code)
                )
            )
            result.append(
                {
                    "id": str(role.id),
                    "code": role.code,
                    "name": role.name,
                    "description": role.description or "",
                    "is_system": bool(role.is_system),
                    "is_active": bool(role.is_active),
                    "legacy_role": role.legacy_role,
                    "permissions": sorted(perms),
                    "users_count": int(counts.get(role.id, 0)),
                    "created_at": jsonable(role.created_at),
                    "updated_at": jsonable(role.updated_at),
                }
            )
        return result

    @classmethod
    def get_role(cls, db: Session, code: str) -> Role:
        role = db.scalar(select(Role).where(Role.code == code, Role.is_deleted.is_(False)))
        if role is None:
            raise NotFound(message="نقش یافت نشد.")
        return role

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _validate_codes(codes: Iterable[str]) -> list[str]:
        cleaned = sorted({str(code).strip() for code in codes if str(code).strip()})
        unknown = [code for code in cleaned if code not in PERMISSION_CODES]
        if unknown:
            raise ValidationFailure(
                message="مجوز نامعتبر است.", details={"unknown": unknown[:10]}
            )
        if len(cleaned) > MAX_PERMISSIONS_PER_ROLE:
            raise ValidationFailure(message="تعداد مجوزهای نقش بیش از حد مجاز است.")
        return cleaned

    @staticmethod
    def _assert_can_grant(actor: ActorContext, codes: Iterable[str]) -> None:
        """Prevent privilege escalation: you may only grant what you hold."""
        missing = sorted(set(codes) - set(actor.permissions))
        if missing:
            raise Forbidden(
                message="امکان اعطای مجوزی که خودتان ندارید وجود ندارد.",
                details={"missing": missing[:10]},
            )

    @staticmethod
    def _assert_not_self(actor: ActorContext, user_id: uuid.UUID) -> None:
        if actor.user_id is not None and actor.user_id == user_id:
            raise Forbidden(message="تغییر نقش‌های حساب خودتان مجاز نیست.")

    @staticmethod
    def _role_snapshot(role: Role) -> dict[str, object]:
        return {
            "code": role.code,
            "name": role.name,
            "description": role.description or "",
            "is_active": bool(role.is_active),
            "legacy_role": role.legacy_role,
        }

    @classmethod
    def _set_role_permissions(
        cls, db: Session, role: Role, codes: list[str], actor: ActorContext
    ) -> None:
        existing = set(
            db.scalars(
                select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
            )
        )
        wanted = set(codes)
        for code in sorted(wanted - existing):
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_code=code,
                    assigned_by=actor.user_id,
                )
            )
        for code in sorted(existing - wanted):
            row = db.get(RolePermission, {"role_id": role.id, "permission_code": code})
            if row is not None:
                db.delete(row)
        db.flush()

    @classmethod
    def _role_payload(cls, db: Session, role: Role) -> dict[str, object]:
        perms = sorted(
            db.scalars(
                select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
            )
        )
        return {
            "id": str(role.id),
            "code": role.code,
            "name": role.name,
            "description": role.description or "",
            "is_system": bool(role.is_system),
            "is_active": bool(role.is_active),
            "legacy_role": role.legacy_role,
            "permissions": perms,
        }

    # -------------------------------------------------------------- writes
    @classmethod
    def create_role(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        code: str,
        name: str,
        description: str = "",
        permissions: Iterable[str] = (),
        legacy_role: str | None = None,
    ) -> dict[str, object]:
        normalized = str(code or "").strip().lower()
        if not ROLE_CODE_PATTERN.match(normalized):
            raise ValidationFailure(
                message="کد نقش نامعتبر است (حروف کوچک انگلیسی، عدد و _؛ ۲ تا ۶۴ نویسه)."
            )
        if normalized == SYSTEM_ROLE_CODE:
            raise ValidationFailure(message="این کد نقش رزرو شده است.")
        if db.scalar(select(func.count()).select_from(Role).where(Role.code == normalized)):
            raise Duplicate(message="کد نقش تکراری است.")
        codes = cls._validate_codes(permissions)
        cls._assert_can_grant(actor, codes)
        if legacy_role is not None and legacy_role not in (ADMIN, OPERATOR, DOCTOR):
            raise ValidationFailure(message="نقش نمایشی نامعتبر است.")

        now = _now()
        role = Role(
            id=uuid.uuid4(),
            code=normalized,
            name=str(name or "").strip()[:120] or normalized,
            description=(description or "").strip() or None,
            is_system=False,
            is_active=True,
            legacy_role=legacy_role or ADMIN,
            created_at=now,
            created_by=actor.user_id,
            updated_at=now,
            updated_by=actor.user_id,
            row_version=1,
        )
        db.add(role)
        db.flush()
        cls._set_role_permissions(db, role, codes, actor)
        AuditService.log(
            db,
            action="role.created",
            entity="roles",
            entity_id=role.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"code": role.code, "permissions": codes},
        )
        return cls._role_payload(db, role)

    @classmethod
    def update_role(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        code: str,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        legacy_role: str | None = None,
    ) -> dict[str, object]:
        role = cls.get_role(db, code)
        if role.is_system:
            raise Forbidden(message="نقش سیستمی قابل ویرایش نیست.")
        before = cls._role_snapshot(role)
        if name is not None:
            role.name = str(name).strip()[:120] or role.name
        if description is not None:
            role.description = str(description).strip() or None
        if legacy_role is not None:
            if legacy_role not in (ADMIN, OPERATOR, DOCTOR):
                raise ValidationFailure(message="نقش نمایشی نامعتبر است.")
            role.legacy_role = legacy_role
        if is_active is not None:
            if not is_active and role.code == SYSTEM_ROLE_CODE:
                raise Forbidden(message="غیرفعال‌سازی نقش سیستمی مجاز نیست.")
            role.is_active = bool(is_active)
        role.updated_at = _now()
        role.updated_by = actor.user_id
        role.row_version = (role.row_version or 1) + 1
        db.flush()
        AuditService.log(
            db,
            action="role.updated",
            entity="roles",
            entity_id=role.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            before=before,
            details=cls._role_snapshot(role),
        )
        return cls._role_payload(db, role)

    @classmethod
    def _sync_legacy_role(cls, db: Session, user: User) -> None:
        """Keep the legacy UI role column in sync (display projection only)."""
        codes = cls.role_codes_for_user(db, user.id)
        projected = legacy_role_for_role_codes(codes)
        if user.role != projected:
            user.role = projected
            user.updated_at = _now()
            user.row_version = (user.row_version or 1) + 1
            db.flush()

    @staticmethod
    def count_active_holders(
        db: Session, permission_code: str, *, exclude_user_id: uuid.UUID | None = None
    ) -> int:
        stmt = (
            select(func.count(func.distinct(UserRole.user_id)))
            .select_from(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(User, User.id == UserRole.user_id)
            .where(
                RolePermission.permission_code == permission_code,
                Role.is_active.is_(True),
                Role.is_deleted.is_(False),
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            )
        )
        if exclude_user_id is not None:
            stmt = stmt.where(UserRole.user_id != exclude_user_id)
        return int(db.scalar(stmt) or 0)

    @classmethod
    def assign_roles(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        user_id: uuid.UUID,
        role_codes: Iterable[str],
    ) -> dict[str, object]:
        cls._assert_not_self(actor, user_id)
        user = db.get(User, user_id)
        if user is None or user.is_deleted:
            raise NotFound(message="کاربر یافت نشد.")
        codes = sorted({str(code).strip().lower() for code in role_codes if str(code).strip()})
        if not codes:
            raise ValidationFailure(message="حداقل یک نقش لازم است.")
        roles = list(
            db.scalars(select(Role).where(Role.code.in_(codes), Role.is_deleted.is_(False)))
        )
        found = {role.code: role for role in roles}
        missing = [code for code in codes if code not in found]
        if missing:
            raise NotFound(message="نقش یافت نشد.", details={"missing": missing})
        for role in roles:
            if not role.is_active:
                raise ValidationFailure(message=f"نقش «{role.code}» غیرفعال است.")
            perms = db.scalars(
                select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
            )
            cls._assert_can_grant(actor, list(perms))

        existing = {
            row.role_id
            for row in db.scalars(select(UserRole).where(UserRole.user_id == user.id))
        }
        added: list[str] = []
        for code in codes:
            role = found[code]
            if role.id in existing:
                continue
            db.add(
                UserRole(
                    user_id=user.id,
                    role_id=role.id,
                    assigned_by=actor.user_id,
                    assigned_at=_now(),
                )
            )
            added.append(code)
        db.flush()
        cls._sync_legacy_role(db, user)
        if added:
            AuditService.log(
                db,
                action="role.assigned",
                entity="users",
                entity_id=user.id,
                actor_user_id=actor.user_id,
                actor_username=actor.username,
                ip_address=actor.ip_address,
                user_agent=actor.user_agent,
                request_id=actor.request_id,
                details={"username": user.username, "roles": added},
            )
        return {
            "user_id": str(user.id),
            "username": user.username,
            "roles": cls.role_codes_for_user(db, user.id),
            "added": added,
        }

    @classmethod
    def revoke_roles(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        user_id: uuid.UUID,
        role_codes: Iterable[str],
    ) -> dict[str, object]:
        cls._assert_not_self(actor, user_id)
        user = db.get(User, user_id)
        if user is None or user.is_deleted:
            raise NotFound(message="کاربر یافت نشد.")
        codes = sorted({str(code).strip().lower() for code in role_codes if str(code).strip()})
        if not codes:
            raise ValidationFailure(message="حداقل یک نقش لازم است.")

        current_codes = set(cls.role_codes_for_user(db, user.id))
        if SYSTEM_ROLE_CODE in codes and SYSTEM_ROLE_CODE in current_codes:
            raise Forbidden(message="نقش سیستمی مالک قابل حذف نیست.")
        losing = set(codes) & current_codes
        if not losing:
            return {"user_id": str(user.id), "roles": sorted(current_codes), "removed": []}

        if "rbac.manage" in cls.effective_permissions(db, user.id):
            remaining = current_codes - losing
            remaining_perms: set[str] = set()
            if remaining:
                remaining_perms = set(
                    db.scalars(
                        select(RolePermission.permission_code)
                        .join(Role, Role.id == RolePermission.role_id)
                        .join(UserRole, UserRole.role_id == Role.id)
                        .where(
                            UserRole.user_id == user.id,
                            Role.code.in_(remaining),
                            Role.is_active.is_(True),
                        )
                    )
                )
            if "rbac.manage" not in remaining_perms:
                others = cls.count_active_holders(db, "rbac.manage", exclude_user_id=user.id)
                if others == 0:
                    raise Forbidden(message="حذف آخرین دسترسی مدیریت نقش‌ها مجاز نیست.")

        removed: list[str] = []
        for code in losing:
            role = cls.get_role(db, code)
            row = db.get(UserRole, {"user_id": user.id, "role_id": role.id})
            if row is not None:
                db.delete(row)
                removed.append(code)
        db.flush()
        cls._sync_legacy_role(db, user)
        AuditService.log(
            db,
            action="role.revoked",
            entity="users",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
            details={"username": user.username, "roles": sorted(removed)},
        )
        return {
            "user_id": str(user.id),
            "username": user.username,
            "roles": cls.role_codes_for_user(db, user.id),
            "removed": sorted(removed),
        }

    # ------------------------------------------------- role permissions
    @classmethod
    def assign_permissions(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        role_code: str,
        permission_codes: Iterable[str],
    ) -> dict[str, object]:
        role = cls.get_role(db, role_code)
        if role.is_system:
            raise Forbidden(message="مجوزهای نقش سیستمی قابل تغییر نیست.")
        codes = cls._validate_codes(permission_codes)
        cls._assert_can_grant(actor, codes)
        existing = set(
            db.scalars(
                select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
            )
        )
        added = sorted(set(codes) - existing)
        for code in added:
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_code=code,
                    assigned_by=actor.user_id,
                )
            )
        db.flush()
        if added:
            AuditService.log(
                db,
                action="permission.assigned",
                entity="roles",
                entity_id=role.id,
                actor_user_id=actor.user_id,
                actor_username=actor.username,
                ip_address=actor.ip_address,
                user_agent=actor.user_agent,
                request_id=actor.request_id,
                details={"role": role.code, "permissions": added},
            )
        return cls._role_payload(db, role)

    @classmethod
    def revoke_permissions(
        cls,
        db: Session,
        actor: ActorContext,
        *,
        role_code: str,
        permission_codes: Iterable[str],
    ) -> dict[str, object]:
        role = cls.get_role(db, role_code)
        if role.is_system:
            raise Forbidden(message="مجوزهای نقش سیستمی قابل تغییر نیست.")
        codes = cls._validate_codes(permission_codes)
        if "rbac.manage" in set(codes):
            holders = {
                row.user_id
                for row in db.scalars(select(UserRole).where(UserRole.role_id == role.id))
            }
            for user_id in holders:
                others = cls.count_active_holders(db, "rbac.manage", exclude_user_id=user_id)
                if others == 0:
                    raise Forbidden(message="حذف آخرین دسترسی مدیریت نقش‌ها مجاز نیست.")
        removed: list[str] = []
        for code in sorted(set(codes)):
            row = db.get(RolePermission, {"role_id": role.id, "permission_code": code})
            if row is not None:
                db.delete(row)
                removed.append(code)
        db.flush()
        if removed:
            AuditService.log(
                db,
                action="permission.revoked",
                entity="roles",
                entity_id=role.id,
                actor_user_id=actor.user_id,
                actor_username=actor.username,
                ip_address=actor.ip_address,
                user_agent=actor.user_agent,
                request_id=actor.request_id,
                details={"role": role.code, "permissions": removed},
            )
        return cls._role_payload(db, role)




