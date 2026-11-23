"""Invoice aggregate: invoices, items, payments, discount events, numbering, amendments."""

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
    rate_type,
    utcnow,
)

INVOICE_STATUSES = (
    "draft",
    "pending_discount_approval",
    "issued",
    "partially_paid",
    "paid",
    "void",
)


class Invoice(EntityMixin, Base):
    """Invoice header. Official numbers are assigned by the server only (TDR-013)."""

    __tablename__ = "invoices"

    invoice_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    invoice_no_provisional: Mapped[str | None] = mapped_column(String(32), nullable=True)
    numbering_state: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="provisional"
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=True
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operators.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")

    subtotal_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    discount_requested_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    discount_request_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    discount_approved_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    discount_approved_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    discount_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discount_rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    tax_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    total_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    paid_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    balance_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    amended_from_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    amendment_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_amendment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    last_amended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','pending_discount_approval','issued','partially_paid','paid','void')",
            name="status",
        ),
        CheckConstraint(
            "discount_status IN ('none','requested','approved','rejected')", name="discount_status"
        ),
        CheckConstraint("numbering_state IN ('provisional','official')", name="numbering_state"),
        CheckConstraint("subtotal_toman >= 0", name="subtotal_non_negative"),
        CheckConstraint("tax_toman >= 0", name="tax_non_negative"),
        CheckConstraint("total_toman >= 0", name="total_non_negative"),
        CheckConstraint("paid_toman >= 0", name="paid_non_negative"),
        CheckConstraint("balance_toman >= 0", name="balance_non_negative"),
        CheckConstraint(
            "discount_toman >= 0 AND discount_toman <= subtotal_toman", name="discount_range"
        ),
        CheckConstraint(
            "status <> 'void' OR (void_reason IS NOT NULL AND length(trim(void_reason)) >= 3)",
            name="void_reason_required",
        ),
        CheckConstraint(
            "numbering_state <> 'official' OR (invoice_no IS NOT NULL AND invoice_no <> '')",
            name="official_number_required",
        ),
        Index(
            "ux_invoices_invoice_no_active",
            "invoice_no",
            unique=True,
            sqlite_where=text("invoice_no IS NOT NULL AND invoice_no <> '' AND is_deleted = 0"),
            postgresql_where=text(
                "invoice_no IS NOT NULL AND invoice_no <> '' AND is_deleted = false"
            ),
        ),
        Index("ix_invoices_patient_date", "patient_id", "invoice_date"),
        Index("ix_invoices_doctor_date", "doctor_id", "invoice_date"),
        Index("ix_invoices_status_date", "status", "invoice_date"),
        Index("ix_invoices_numbering_state", "numbering_state"),
    )


class InvoiceItem(EntityMixin, Base):
    """Invoice line with monetary snapshots (price, tax rate, commission basis)."""

    __tablename__ = "invoice_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=True
    )
    service_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(
        quantity_type(), nullable=False, default=Decimal("1"), server_default=text("1")
    )
    unit_price_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    line_gross_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    line_discount_alloc_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    line_net_after_discount_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    effective_tax_rate: Mapped[Decimal] = mapped_column(
        rate_type(), nullable=False, server_default=text("0")
    )
    taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    line_tax_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    line_total_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    commission_basis_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    invoice_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_toman >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            "effective_tax_rate >= 0 AND effective_tax_rate <= 100", name="tax_rate_range"
        ),
        Index("ix_invoice_items_invoice", "invoice_id", "sort_order"),
        Index("ix_invoice_items_service", "service_id"),
        Index("ix_invoice_items_version", "invoice_id", "invoice_version"),
    )


class Payment(EntityMixin, Base):
    """Recorded payment. Overpayment turns into patient credit (TDR-016)."""

    __tablename__ = "payments"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_toman: Mapped[Decimal] = mapped_column(money_type(), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="cash")
    reference_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="recorded")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # links to the credit ledger (no FK to avoid a circular dependency)
    credit_transaction_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    overpayment_credit_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("amount_toman > 0", name="amount_positive"),
        CheckConstraint("method IN ('cash','card','transfer','credit','other')", name="method"),
        CheckConstraint("status IN ('recorded','void')", name="status"),
        Index("ix_payments_invoice_date", "invoice_id", "payment_date"),
        Index("ix_payments_date_status", "payment_date", "status"),
    )


class InvoiceDiscountEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only history of discount requests/approvals/rejections."""

    __tablename__ = "invoice_discount_events"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint("event IN ('requested','approved','rejected')", name="event"),
        Index("ix_discount_events_invoice", "invoice_id", "created_at"),
    )


class InvoiceNumberHistory(UUIDPrimaryKeyMixin, Base):
    """Keeps both provisional and official numbers (TDR-013)."""

    __tablename__ = "invoice_number_history"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    number_type: Mapped[str] = mapped_column(String(12), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    assigned_by_device: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint("number_type IN ('provisional','official')", name="number_type"),
        UniqueConstraint("invoice_id", "number", name="uq_invoice_number_history_invoice_number"),
        Index("ix_number_history_invoice", "invoice_id", "assigned_at"),
        Index("ix_number_history_number", "number"),
    )


class InvoiceAmendment(EntityMixin, Base):
    """Recorded amendment of an issued invoice (TDR-012). Never silent rewrites."""

    __tablename__ = "invoice_amendments"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    amendment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="draft")
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    before_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    delta_subtotal_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    delta_discount_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    delta_tax_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    delta_total_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )

    requested_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('draft','issued','void')", name="status"),
        CheckConstraint("length(trim(reason)) >= 3", name="reason_required"),
        CheckConstraint(
            "status <> 'issued' OR issued_at IS NOT NULL", name="issued_at_required"
        ),
        CheckConstraint(
            "status <> 'void' OR (void_reason IS NOT NULL AND length(trim(void_reason)) >= 3)",
            name="void_reason_required",
        ),
        UniqueConstraint("invoice_id", "amendment_no", name="uq_invoice_amendments_invoice_no"),
        Index("ix_amendments_invoice", "invoice_id", "amendment_no"),
        Index("ix_amendments_status", "status", "created_at"),
    )


class InvoiceAmendmentItem(EntityMixin, Base):
    """Per-line delta of an amendment (add / update / remove)."""

    __tablename__ = "invoice_amendment_items"

    amendment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoice_amendments.id", ondelete="CASCADE"), nullable=False
    )
    invoice_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoice_items.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=True
    )
    description_snapshot: Mapped[str] = mapped_column(String(160), nullable=False, server_default="")

    quantity_before: Mapped[Decimal | None] = mapped_column(quantity_type(), nullable=True)
    quantity_after: Mapped[Decimal | None] = mapped_column(quantity_type(), nullable=True)
    unit_price_before_toman: Mapped[Decimal | None] = mapped_column(money_type(), nullable=True)
    unit_price_after_toman: Mapped[Decimal | None] = mapped_column(money_type(), nullable=True)
    taxable_after: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    effective_tax_rate_after: Mapped[Decimal] = mapped_column(
        rate_type(), nullable=False, server_default=text("0")
    )

    line_gross_after_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    line_discount_alloc_after_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    line_tax_after_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    line_total_after_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    commission_basis_after_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, server_default=text("0")
    )
    delta_total_toman: Mapped[Decimal] = mapped_column(
        money_type(), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("action IN ('add','update','remove')", name="action"),
        CheckConstraint("quantity_after IS NULL OR quantity_after > 0", name="quantity_after_positive"),
        Index("ix_amendment_items_amendment", "amendment_id", "sort_order"),
        Index("ix_amendment_items_invoice_item", "invoice_item_id"),
    )



