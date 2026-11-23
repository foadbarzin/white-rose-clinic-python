"""RBAC: permission catalog, action mapping and effective-permission helpers.

Phase 3 model (independent Users / Roles / Permissions):
  * permissions are **defined in code** (a stable catalog, no sample data);
  * roles are **database rows** created by an authorised administrator;
  * role↔permission and user↔role links live in the database;
  * a user may hold several roles; effective permissions are the union.

Backward compatibility:
  * the legacy ``admin``/``operator``/``doctor`` matrix is kept **only** as a
    projection for the existing UI and for records created before phase 3;
  * backend authorization always checks permission codes, never the UI role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from app.core.exceptions import Forbidden

ADMIN: Final = "admin"
OPERATOR: Final = "operator"
DOCTOR: Final = "doctor"
VALID_ROLES: Final[frozenset[str]] = frozenset({ADMIN, OPERATOR, DOCTOR})
LEGACY_ROLE_ORDER: Final[tuple[str, ...]] = (ADMIN, OPERATOR, DOCTOR)


@dataclass(frozen=True)
class PermissionDef:
    code: str
    module: str
    description: str


# ------------------------------------------------------------------ catalog
PERMISSIONS: Final[tuple[PermissionDef, ...]] = (
    PermissionDef("users.manage", "users", "مدیریت کاربران، وضعیت حساب و بازنشانی رمز"),
    PermissionDef("rbac.manage", "users", "مدیریت نقش‌ها و تخصیص مجوز"),
    PermissionDef("audit.read", "audit", "مشاهدهٔ گزارش رویدادهای امنیتی"),
    PermissionDef("patients.read", "patients", "مشاهدهٔ بیماران"),
    PermissionDef("patients.write", "patients", "ایجاد و ویرایش بیماران"),
    PermissionDef("patients.delete", "patients", "حذف نرم بیماران"),
    PermissionDef("doctors.read", "definitions", "مشاهدهٔ پزشکان"),
    PermissionDef("doctors.write", "definitions", "مدیریت پزشکان"),
    PermissionDef("operators.read", "definitions", "مشاهدهٔ اپراتورها"),
    PermissionDef("operators.write", "definitions", "مدیریت اپراتورها"),
    PermissionDef("services.read", "definitions", "مشاهدهٔ خدمات"),
    PermissionDef("services.write", "definitions", "مدیریت خدمات و تعرفه‌ها"),
    PermissionDef("invoices.read", "invoices", "مشاهدهٔ فاکتورها"),
    PermissionDef("invoices.write", "invoices", "ایجاد/ویرایش پیش‌نویس و صدور فاکتور"),
    PermissionDef("invoices.discount", "invoices", "تأیید یا رد تخفیف"),
    PermissionDef("invoices.void", "invoices", "ابطال فاکتور"),
    PermissionDef("invoices.amend", "invoices", "اصلاح ثبت‌شدهٔ فاکتور"),
    PermissionDef("payments.write", "payments", "ثبت پرداخت"),
    PermissionDef("payments.void", "payments", "ابطال پرداخت"),
    PermissionDef("credits.read", "credits", "مشاهدهٔ اعتبار بیمار"),
    PermissionDef("credits.write", "credits", "تغییر اعتبار بیمار"),
    PermissionDef("commissions.read", "commissions", "مشاهدهٔ پورسانت"),
    PermissionDef("commissions.manage", "commissions", "تأیید/پرداخت پورسانت و قواعد"),
    PermissionDef("expenses.read", "finance", "مشاهدهٔ هزینه‌ها"),
    PermissionDef("expenses.write", "finance", "ثبت هزینه"),
    PermissionDef("revenue.read", "finance", "مشاهدهٔ درآمد متفرقه"),
    PermissionDef("revenue.write", "finance", "ثبت درآمد متفرقه"),
    PermissionDef("reports.operational", "reports", "گزارش‌های عملیاتی"),
    PermissionDef("reports.financial", "reports", "گزارش‌های مالی و سود"),
    PermissionDef("settings.manage", "system", "مدیریت تنظیمات سیستم"),
    PermissionDef("system.admin", "system", "عملیات مدیریتی سیستم (پشتیبان/بازیابی)"),
    PermissionDef("sync.device", "sync", "همگام‌سازی دستگاه دسکتاپ"),
)

PERMISSION_CODES: Final[frozenset[str]] = frozenset(permission.code for permission in PERMISSIONS)
PERMISSIONS_BY_MODULE: Final[dict[str, tuple[PermissionDef, ...]]] = {
    module: tuple(permission for permission in PERMISSIONS if permission.module == module)
    for module in dict.fromkeys(permission.module for permission in PERMISSIONS)
}

_ADMIN_ALL: Final[frozenset[str]] = PERMISSION_CODES
_OPERATOR_CODES: Final[frozenset[str]] = frozenset(
    {
        "patients.read",
        "patients.write",
        "doctors.read",
        "operators.read",
        "services.read",
        "invoices.read",
        "invoices.write",
        "payments.write",
        "credits.read",
        "expenses.read",
        "expenses.write",
        "revenue.read",
        "reports.operational",
    }
)
_DOCTOR_CODES: Final[frozenset[str]] = frozenset(
    {"invoices.read", "services.read", "commissions.read"}
)

# Legacy projection only — never used for new authorization decisions.
LEGACY_ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    ADMIN: _ADMIN_ALL,
    OPERATOR: _OPERATOR_CODES,
    DOCTOR: _DOCTOR_CODES,
}

# action -> required permission code (None = authenticated user is enough)
ACTION_PERMISSIONS: Final[dict[str, str | None]] = {
    # authentication / self service
    "auth.me": None,
    "auth.logout": None,
    "auth.logout_all": None,
    "auth.sessions": None,
    "auth.change_password": None,
    "auth.login": None,
    "setup.bootstrapAdmin": None,
    # users
    "users.list": "users.manage",
    "users.get": "users.manage",
    "users.create": "users.manage",
    "users.update": "users.manage",
    "users.disable": "users.manage",
    "users.enable": "users.manage",
    "users.unlock": "users.manage",
    "users.change_password": "users.manage",
    "users.sessions": "users.manage",
    "users.revoke_sessions": "users.manage",
    "users.activity": "users.manage",
    # rbac
    "roles.list": "rbac.manage",
    "roles.create": "rbac.manage",
    "roles.update": "rbac.manage",
    "roles.assign": "rbac.manage",
    "roles.revoke": "rbac.manage",
    "permissions.list": "rbac.manage",
    "permissions.assign": "rbac.manage",
    "permissions.revoke": "rbac.manage",
    # audit
    "audit.list": "audit.read",
    "audit.get": "audit.read",
    # future modules (documented; not implemented in phase 3)
    "customers.list": "patients.read",
    "customers.create": "patients.write",
    "customers.update": "patients.write",
    "customers.delete": "patients.delete",
    "patients.list": "patients.read",
    "doctors.list": "doctors.read",
    "operators.list": "operators.read",
    "services.list": "services.read",
    "invoices.list": "invoices.read",
    "invoices.query": "invoices.read",
    "invoices.get": "invoices.read",
    "invoices.preview": "invoices.write",
    "invoices.saveDraft": "invoices.write",
    "invoices.requestDiscount": "invoices.write",
    "invoices.approveDiscount": "invoices.discount",
    "invoices.issue": "invoices.write",
    "invoices.void": "invoices.void",
    "invoices.amendments.list": "invoices.read",
    "invoices.amendments.get": "invoices.read",
    "invoices.amendments.preview": "invoices.amend",
    "invoices.amendments.create": "invoices.amend",
    "invoices.amendments.update": "invoices.amend",
    "invoices.amendments.issue": "invoices.amend",
    "invoices.amendments.void": "invoices.amend",
    "payments.add": "payments.write",
    "credits.balance": "credits.read",
    "credits.transactions": "credits.read",
    "credits.adjust": "credits.write",
    "expenses.list": "expenses.read",
    "expenses.create": "expenses.write",
    "revenue.list": "revenue.read",
    "revenue.create": "revenue.write",
    "commissions.list": "commissions.read",
    "commissions.approvePayable": "commissions.manage",
    "commissions.markPaid": "commissions.manage",
    "commissionRules.list": "commissions.read",
    "commissionRules.upsert": "commissions.manage",
    "reports.dashboard": "reports.operational",
    "reports.summary": "reports.financial",
    "reports.period": "reports.financial",
    "reports.insights": "reports.financial",
    "reports.customers": "reports.operational",
    "reports.services": "reports.operational",
    "settings.get": "settings.manage",
    "settings.set": "settings.manage",
    "settings.setMany": "settings.manage",
    "settings.catalog": "settings.manage",
    "setup.run": "settings.manage",
    "system.admin": "system.admin",
    "system.dataSummary": "system.admin",
    "system.exportData": "system.admin",
    "system.wipeData": "system.admin",
    "sync.push": "sync.device",
    "sync.pull": "sync.device",
    "sync.handshake": "sync.device",
}

PERMISSION_ALIASES: Final[dict[str, str]] = {
    "invoices.approve_discount": "invoices.discount",
    "invoices.amend.request": "invoices.amend",
    "invoices.amend.issue": "invoices.amend",
    "invoices.amend.void": "invoices.amend",
    "commissions.read.own": "commissions.read",
    "commissions.read.all": "commissions.read",
    "reports.read.operational": "reports.operational",
    "reports.read.financial_sensitive": "reports.financial",
    "reports.read.profit": "reports.financial",
    "commission_rules.manage": "commissions.manage",
    "customers.read": "patients.read",
    "customers.read.limited": "patients.read",
    "doctors.manage": "doctors.write",
    "operators.manage": "operators.write",
    "services.manage": "services.write",
    "invoices.read.own": "invoices.read",
    "invoice_items.read": "invoices.read",
    "invoice_items.read.own": "invoices.read",
    "dashboard.read": "reports.operational",
    "dashboard.read.own": "reports.operational",
    "system.backup": "system.admin",
    "system.restore": "system.admin",
    "system.archive": "system.admin",
    "system.purge": "system.admin",
    "system.diagnostics": "system.admin",
    "credits.refund": "credits.write",
}


def permission_code_for(key: str) -> str | None:
    """Resolve an action name / alias into a catalog permission code."""
    if key in PERMISSION_CODES:
        return key
    if key in ACTION_PERMISSIONS:
        return ACTION_PERMISSIONS[key]
    return PERMISSION_ALIASES.get(key)


def is_known_action(action: str) -> bool:
    return action in ACTION_PERMISSIONS or action in PERMISSION_ALIASES


def roles_for(action: str) -> frozenset[str]:
    """Legacy projection: which legacy roles would satisfy this action."""
    code = permission_code_for(action)
    if code is None:
        return frozenset()
    return frozenset(role for role, codes in LEGACY_ROLE_PERMISSIONS.items() if code in codes)


@dataclass(frozen=True)
class Principal:
    """Authenticated principal (DB-derived permissions preferred)."""

    user_id: str
    username: str
    role: str
    linked_doctor_id: str | None = None
    linked_operator_id: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    must_change_password: bool = False
    session_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN

    @property
    def is_doctor(self) -> bool:
        return self.role == DOCTOR

    @property
    def is_operator(self) -> bool:
        return self.role == OPERATOR


def legacy_role_for_role_codes(role_codes: list[str]) -> str:
    """Project assigned role codes onto the legacy UI role (display only)."""
    lowered = {str(code).lower() for code in role_codes}
    if ADMIN in lowered:
        return ADMIN
    if OPERATOR in lowered:
        return OPERATOR
    if DOCTOR in lowered:
        return DOCTOR
    return OPERATOR


def can(key: str, role: str | None) -> bool:
    """Legacy role check (kept for compatibility and projections)."""
    if not role or role not in VALID_ROLES:
        return False
    code = permission_code_for(key)
    if code is None:
        return False
    return code in LEGACY_ROLE_PERMISSIONS[role]


def has_permission(principal: Principal | None, code: str | None) -> bool:
    """Check a permission code against a DB-derived principal."""
    if principal is None:
        return False
    if code is None:
        return True
    if principal.permissions:
        return code in principal.permissions
    # fallback for principals created before phase 3 (tests/tooling)
    return code in LEGACY_ROLE_PERMISSIONS.get(principal.role, frozenset())


def can_principal(key: str, principal: Principal | None) -> bool:
    if principal is None:
        return False
    return has_permission(principal, permission_code_for(key))


def require(key: str, principal: Principal | None) -> Principal:
    """Assert an action/permission and return the principal."""
    if principal is None:
        raise Forbidden(message="نشست معتبر نیست. دوباره وارد شوید.")
    if not has_permission(principal, permission_code_for(key)):
        raise Forbidden(message="دسترسی مجاز نیست.")
    return principal


def require_permission(principal: Principal | None, code: str) -> Principal:
    if principal is None:
        raise Forbidden(message="نشست معتبر نیست. دوباره وارد شوید.")
    if not has_permission(principal, code):
        raise Forbidden(message="دسترسی مجاز نیست.")
    return principal


def doctor_scope(principal: Principal) -> str | None:
    if principal is None or not principal.is_doctor:
        return None
    return (principal.linked_doctor_id or "").strip() or None


