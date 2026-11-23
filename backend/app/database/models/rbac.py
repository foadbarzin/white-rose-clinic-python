"""RBAC tables: roles, role-permission links and user-role assignments."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, EntityMixin, utcnow


class Role(EntityMixin, Base):
    """A named set of permissions.

    Roles are created by an administrator; the ``owner`` role is created by the
    one-time secure bootstrap and is protected from edits.
    """

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    # projection for the legacy RTL UI menu (admin/operator/doctor)
    legacy_role: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("code", name="uq_roles_code"),
        CheckConstraint("length(trim(code)) >= 2", name="code_required"),
        CheckConstraint(
            "legacy_role IS NULL OR legacy_role IN ('admin','operator','doctor')",
            name="legacy_role",
        ),
        Index("ix_roles_active", "is_active"),
    )


class RolePermission(Base):
    """Permission code granted to a role (codes come from the code catalog)."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("ix_role_permissions_code", "permission_code"),)


class UserRole(Base):
    """Assignment of a role to a user (a user may hold several roles)."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("ix_user_roles_role", "role_id"),)
