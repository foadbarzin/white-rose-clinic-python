"""Base definitions: patients, doctors, operators, services."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    String,
    Text,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, EntityMixin, money_type, rate_type


class Patient(EntityMixin, Base):
    """Patient (legacy API name: ``customers``)."""

    __tablename__ = "patients"

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(16), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(16), nullable=True)
    national_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="status"),
        Index("ix_patients_name", "full_name"),
        Index("ix_patients_mobile", "mobile"),
        Index("ix_patients_status", "status"),
    )


class Doctor(EntityMixin, Base):
    __tablename__ = "doctors"

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=false())
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    __table_args__ = (Index("ix_doctors_active", "is_active"),)


class Operator(EntityMixin, Base):
    __tablename__ = "operators"

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(16), nullable=True)
    role_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=false())
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    __table_args__ = (Index("ix_operators_active", "is_active"),)


class Service(EntityMixin, Base):
    """Service definition with default doctor/operator commissions (v0.4.1 parity)."""

    __tablename__ = "services"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    base_price_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    default_tax_rate: Mapped[Decimal | None] = mapped_column(rate_type(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=false())
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    doctor_commission_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    doctor_commission_value: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    operator_commission_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    operator_commission_value: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )

    __table_args__ = (
        CheckConstraint("base_price_toman >= 0", name="base_price_non_negative"),
        CheckConstraint("duration_min >= 0", name="duration_non_negative"),
        CheckConstraint(
            "default_tax_rate IS NULL OR (default_tax_rate >= 0 AND default_tax_rate <= 100)",
            name="default_tax_rate_range",
        ),
        CheckConstraint(
            "doctor_commission_type IS NULL OR doctor_commission_type IN ('','percent','fixed_per_unit')",
            name="doctor_commission_type",
        ),
        CheckConstraint(
            "operator_commission_type IS NULL OR operator_commission_type IN ('','percent','fixed_per_unit')",
            name="operator_commission_type",
        ),
        CheckConstraint(
            "doctor_commission_type <> 'percent' OR doctor_commission_value <= 100",
            name="doctor_commission_percent_max",
        ),
        CheckConstraint(
            "operator_commission_type <> 'percent' OR operator_commission_value <= 100",
            name="operator_commission_percent_max",
        ),
        Index("ix_services_name", "name"),
        Index("ix_services_active", "is_active"),
    )

