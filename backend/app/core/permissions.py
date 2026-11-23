"""Role-based access control (RBAC) matrix.

Source of truth: ``docs/architecture/DOMAIN_MODEL.md`` §۱۹ and
``docs/architecture/SECURITY_DESIGN.md`` §۴ and §۱۳.

Rules:
  * default deny — an action that is not listed is forbidden for every role;
  * the router adds a second admin-only gate for sensitive actions
    (defence in depth);
  * doctor data scoping must also be enforced in SQL by repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.core.exceptions import Forbidden

ADMIN: Final = "admin"
OPERATOR: Final = "operator"
DOCTOR: Final = "doctor"
VALID_ROLES: Final[frozenset[str]] = frozenset({ADMIN, OPERATOR, DOCTOR})

_ALL: Final[frozenset[str]] = frozenset({ADMIN, OPERATOR, DOCTOR})
_ADMIN_OPERATOR: Final[frozenset[str]] = frozenset({ADMIN, OPERATOR})
_ADMIN_ONLY: Final[frozenset[str]] = frozenset({ADMIN})
_NOBODY: Final[frozenset[str]] = frozenset()

# action -> roles allowed
_MATRIX: Final[dict[str, frozenset[str]]] = {
    # authentication / self-service
    "auth.me": _ALL,
    "auth.logout": _ALL,
    "auth.change_password": _ALL,
    "auth.login": _NOBODY,  # public action: handled before session resolution
    "setup.bootstrapAdmin": _NOBODY,  # public, one-time
    # users
    "users.manage": _ADMIN_ONLY,
    # patients (legacy name: customers)
    "patients.read": _ADMIN_OPERATOR,
    "patients.read.limited": frozenset({ADMIN, OPERATOR, DOCTOR}),
    "patients.create": _ADMIN_OPERATOR,
    "patients.update": _ADMIN_OPERATOR,
    "patients.delete": _ADMIN_ONLY,
    "customers.read": _ADMIN_OPERATOR,
    "customers.read.limited": frozenset({ADMIN, OPERATOR, DOCTOR}),
    "customers.create": _ADMIN_OPERATOR,
    "customers.update": _ADMIN_OPERATOR,
    "customers.delete": _ADMIN_ONLY,
    # base definitions
    "doctors.read": _ADMIN_OPERATOR,
    "doctors.manage": _ADMIN_ONLY,
    "operators.read": _ADMIN_OPERATOR,
    "operators.manage": _ADMIN_ONLY,
    "services.read": _ALL,
    "services.manage": _ADMIN_ONLY,
    "definitions.manage": _ADMIN_ONLY,
    # invoices
    "invoices.read": _ADMIN_OPERATOR,
    "invoices.read.own": frozenset({ADMIN, DOCTOR}),
    "invoices.create": _ADMIN_OPERATOR,
    "invoices.update_draft": _ADMIN_OPERATOR,
    "invoices.request_discount": _ADMIN_OPERATOR,
    "invoices.approve_discount": _ADMIN_ONLY,
    "invoices.issue": _ADMIN_OPERATOR,
    "invoices.void": _ADMIN_ONLY,
    "invoice_items.read": _ADMIN_OPERATOR,
    "invoice_items.read.own": frozenset({ADMIN, DOCTOR}),
    # invoice amendments (TDR-012)
    "invoices.amend.request": _ADMIN_ONLY,
    "invoices.amend.issue": _ADMIN_ONLY,
    "invoices.amend.void": _ADMIN_ONLY,
    # payments
    "payments.read": _ADMIN_OPERATOR,
    "payments.create": _ADMIN_OPERATOR,
    "payments.void": _ADMIN_ONLY,
    # patient credit (TDR-016)
    "credits.balance": _ADMIN_OPERATOR,
    "credits.transactions": _ADMIN_ONLY,
    "credits.adjust": _ADMIN_ONLY,
    "credits.refund": _ADMIN_ONLY,
    # expenses / other income
    "expenses.read": _ADMIN_OPERATOR,
    "expenses.create": _ADMIN_OPERATOR,
    "expenses.delete": _ADMIN_ONLY,
    "revenue.read": _ADMIN_OPERATOR,
    "revenue.create": _ADMIN_ONLY,
    # commissions
    "commissions.read.all": _ADMIN_ONLY,
    "commissions.read.own": frozenset({ADMIN, DOCTOR}),
    "commissions.approve_payable": _ADMIN_ONLY,
    "commissions.mark_paid": _ADMIN_ONLY,
    "commission_rules.manage": _ADMIN_ONLY,
    # reports
    "reports.read.operational": _ADMIN_OPERATOR,
    "reports.read.financial_sensitive": _ADMIN_ONLY,
    "reports.read.profit": _ADMIN_ONLY,
    "reports.dashboard": _ALL,
    "dashboard.read": _ADMIN_OPERATOR,
    "dashboard.read.own": frozenset({ADMIN, DOCTOR}),
    # settings / system
    "settings.manage": _ADMIN_ONLY,
    "setup.run": _ADMIN_ONLY,
    "system.admin": _ADMIN_ONLY,
    "system.backup": _ADMIN_ONLY,
    "system.restore": _ADMIN_ONLY,
    "system.archive": _ADMIN_ONLY,
    "system.purge": _ADMIN_ONLY,
    "system.diagnostics": _ADMIN_ONLY,
    "audit.read": _ADMIN_ONLY,
    # sync is device-scoped, never a human session
    "sync.push": _NOBODY,
    "sync.pull": _NOBODY,
    "sync.handshake": _NOBODY,
}


@dataclass(frozen=True)
class Principal:
    """Minimal authenticated principal used by the permission checks."""

    user_id: str
    username: str
    role: str
    linked_doctor_id: str | None = None
    linked_operator_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN

    @property
    def is_doctor(self) -> bool:
        return self.role == DOCTOR

    @property
    def is_operator(self) -> bool:
        return self.role == OPERATOR


def is_known_action(action: str) -> bool:
    return action in _MATRIX


def roles_for(action: str) -> frozenset[str]:
    return _MATRIX.get(action, _NOBODY)


def can(action: str, role: str | None) -> bool:
    """Default-deny permission check for a role."""
    if not role or role not in VALID_ROLES:
        return False
    return role in _MATRIX.get(action, _NOBODY)


def can_principal(action: str, principal: Principal | None) -> bool:
    if principal is None:
        return False
    return can(action, principal.role)


def require(action: str, principal: Principal | None) -> Principal:
    """Assert permission and return the principal (raises ``Forbidden``)."""
    if principal is None:
        raise Forbidden(message="نشست معتبر نیست. دوباره وارد شوید.")
    if not can(action, principal.role):
        raise Forbidden(message="دسترسی مجاز نیست.")
    return principal


def doctor_scope(principal: Principal) -> str | None:
    """Return the doctor id that limits a doctor's data scope (None otherwise)."""
    if principal is None or not principal.is_doctor:
        return None
    return (principal.linked_doctor_id or "").strip() or None
