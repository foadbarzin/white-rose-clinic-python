"""Finance tables: commission rules/records, expenses, other income, patient credit."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import (
    Base,
    EntityMixin,
    UUIDPrimaryKeyMixin,
    money_type,
    quantity_type,
    utcnow,
)


class CommissionRule(EntityMixin, Base):
    """Commission rule: person+service > person > service > service default."""

    __tablename__ = "commission_rules"

    applies_to: Mapped[str] = mapped_column(String(8), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[Decimal] = mapped_column(money_type(), nullable=False, server_default=text("0"))
    calc_unit: Mapped[str] = mapped_column(String(16), nullable=False, server_default="line")
    basis_scope: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="invoice_item"
    )
    priority: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=100, server_default=text("100")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("applies_to IN ('doctor','operator')", name="applies_to"),
        CheckConstraint("type IN ('percent','fixed_per_unit')", name="type"),
        CheckConstraint("value >= 0", name="value_non_negative"),
        CheckConstraint("type <> 'percent' OR value <= 100", name="percent_max"),
        Index("ix_commission_rules_lookup", "applies_to", "is_active", "priority"),
        Index("ix_commission_rules_person", "person_id"),
        Index("ix_commission_rules_service", "service_id"),
    )


class Commission(EntityMixin, Base):
    """Calculated commission with lifecycle calculated → payable → paid."""

    __tablename__ = "commissions"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoice_items.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    person_type: Mapped[str] = mapped_column(String(8), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commission_basis_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    quantity: Mapped[Decimal] = mapped_column(
        quantity_type(), nullable=False, server_default=text("1")
    )
    rate_or_amount_snapshot: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    commission_amount_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="calculated")

    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calculated_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    approved_payable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_payable_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voided_or_adjusted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_or_adjusted_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    adjustment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_commission_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("person_type IN ('doctor','operator')", name="person_type"),
        CheckConstraint(
            "status IN ('calculated','payable','paid','void','adjusted')", name="status"
        ),
        CheckConstraint("commission_amount_toman >= 0", name="amount_non_negative"),
        CheckConstraint("status <> 'paid' OR paid_at IS NOT NULL", name="paid_at_required"),
        CheckConstraint(
            "status <> 'void' OR (adjustment_reason IS NOT NULL AND adjustment_reason <> '')",
            name="void_reason_required",
        ),
        Index("ix_commissions_invoice", "invoice_id"),
        Index("ix_commissions_person_status", "person_type", "person_id", "status"),
        Index("ix_commissions_status", "status"),
    )


class Expense(EntityMixin, Base):
    """Clinic expense (soft delete, never physically removed by users)."""

    __tablename__ = "expenses"

    date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    amount_toman: Mapped[Decimal] = mapped_column(money_type(), nullable=False)
    payee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")

    __table_args__ = (
        CheckConstraint("amount_toman > 0", name="amount_positive"),
        CheckConstraint("status IN ('active','void')", name="status"),
        Index("ix_expenses_date", "date"),
        Index("ix_expenses_status_date", "status", "date"),
    )


class OtherIncome(EntityMixin, Base):
    """Miscellaneous income (legacy sheet: ``Revenue``). Not invoice payments."""

    __tablename__ = "other_income"

    date: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="misc")
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_toman: Mapped[Decimal] = mapped_column(money_type(), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")

    __table_args__ = (
        CheckConstraint("amount_toman > 0", name="amount_positive"),
        CheckConstraint("status IN ('active','void')", name="status"),
        Index("ix_other_income_date", "date"),
        Index("ix_other_income_status_date", "status", "date"),
    )


class PatientCreditAccount(EntityMixin, Base):
    """Per-patient credit wallet. ``balance_toman`` is a cache of the ledger sum."""

    __tablename__ = "patient_credit_accounts"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    balance_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    last_transaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("patient_id", name="uq_patient_credit_accounts_patient_id"),
        CheckConstraint("balance_toman >= 0", name="balance_non_negative"),
    )


class PatientCreditTransaction(UUIDPrimaryKeyMixin, Base):
    """Append-only credit ledger row (increase/decrease) — TDR-016."""

    __tablename__ = "patient_credit_transactions"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patient_credit_accounts.id", ondelete="RESTRICT"), nullable=True
    )
    txn_type: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_toman: Mapped[Decimal] = mapped_column(money_type(), nullable=False)
    signed_amount_toman: Mapped[Decimal] = mapped_column(money_type(), nullable=False)
    balance_after_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), nullable=True
    )
    related_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patient_credit_transactions.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "txn_type IN ('overpayment','credit_applied','refund','adjustment','reversal')",
            name="txn_type",
        ),
        CheckConstraint("direction IN ('in','out')", name="direction"),
        CheckConstraint("amount_toman > 0", name="amount_positive"),
        CheckConstraint(
            "(direction = 'in' AND signed_amount_toman = amount_toman) OR "
            "(direction = 'out' AND signed_amount_toman = -amount_toman)",
            name="signed_amount_consistent",
        ),
        CheckConstraint(
            "txn_type NOT IN ('adjustment','reversal') OR "
            "(reason IS NOT NULL AND length(trim(reason)) >= 3)",
            name="reason_required",
        ),
        UniqueConstraint("idempotency_key", name="uq_patient_credit_transactions_idempotency_key"),
        Index("ix_credit_txn_patient", "patient_id", "created_at"),
        Index("ix_credit_txn_invoice", "invoice_id"),
        Index("ix_credit_txn_type", "txn_type"),
    )

