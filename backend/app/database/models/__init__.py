"""Import every model so ``Base.metadata`` is complete for Alembic."""

from app.database.models.base_data import Doctor, Operator, Patient, Service
from app.database.models.finance import (
    Commission,
    CommissionRule,
    Expense,
    OtherIncome,
    PatientCreditAccount,
    PatientCreditTransaction,
)
from app.database.models.identity import User, UserSession
from app.database.models.invoicing import (
    Invoice,
    InvoiceAmendment,
    InvoiceAmendmentItem,
    InvoiceDiscountEvent,
    InvoiceItem,
    InvoiceNumberHistory,
    Payment,
)
from app.database.models.rbac import Role, RolePermission, UserRole
from app.database.models.sync import ChangeFeed, SyncConflict, SyncOperation
from app.database.models.system import (
    AuditLog,
    BackupJob,
    Device,
    Meta,
    Sequence,
    Setting,
)

__all__ = [
    "AuditLog",
    "BackupJob",
    "ChangeFeed",
    "Commission",
    "CommissionRule",
    "Device",
    "Doctor",
    "Expense",
    "Invoice",
    "InvoiceAmendment",
    "InvoiceAmendmentItem",
    "InvoiceDiscountEvent",
    "InvoiceItem",
    "InvoiceNumberHistory",
    "Meta",
    "Operator",
    "OtherIncome",
    "Patient",
    "PatientCreditAccount",
    "PatientCreditTransaction",
    "Payment",
    "Role",
    "RolePermission",
    "Sequence",
    "Service",
    "Setting",
    "SyncConflict",
    "SyncOperation",
    "User",
    "UserRole",
    "UserSession",
]
