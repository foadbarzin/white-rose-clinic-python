"""Phase 3 RBAC tests (multi-role, effective permissions, escalation guards)."""

from __future__ import annotations

from sqlalchemy import select

from app.database.models.rbac import Role
from app.database.models.system import AuditLog
from app.database.session import session_scope

OWNER_ACTIVE = "Owner#Phase3-Active"


def _login(call, client, username: str, password: str) -> dict:
    return call(client, "auth.login", {"username": username, "password": password})


def _create_role(call, client, token, code, permissions):
    return call(
        client,
        "roles.create",
        {"code": code, "name": code, "permissions": list(permissions)},
        token=token,
    )


def test_permission_catalog(owner_session, call) -> None:
    body = call(owner_session["client"], "permissions.list", token=owner_session["token"])
    assert body["ok"] is True
    codes = {item["code"] for item in body["data"]["permissions"]}
    assert {"users.manage", "rbac.manage", "audit.read", "invoices.write"} <= codes
    assert any(module["module"] == "invoices" for module in body["data"]["modules"])


def test_role_create_validation(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    ok = _create_role(call, client, token, "frontdesk", ["patients.read", "users.manage"])
    assert ok["ok"] is True
    assert "users.manage" in ok["data"]["permissions"]
    duplicate = _create_role(call, client, token, "frontdesk", ["patients.read"])
    assert duplicate["error"]["code"] == "DUPLICATE"
    bad_code = _create_role(call, client, token, "Bad Code!", ["patients.read"])
    assert bad_code["error"]["code"] == "VALIDATION"
    bad_perm = _create_role(call, client, token, "weird", ["does.not.exist"])
    assert bad_perm["error"]["code"] == "VALIDATION"
    reserved = _create_role(call, client, token, "owner", ["patients.read"])
    assert reserved["error"]["code"] == "VALIDATION"


def test_multi_role_effective_permissions(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _create_role(call, client, token, "reader", ["patients.read"])
    _create_role(call, client, token, "cashier", ["payments.write", "invoices.read"])
    created = call(
        client,
        "users.create",
        {"username": "multi1", "password": "Multi#Pass123", "role_codes": ["reader"]},
        token=token,
    )
    user_id = created["data"]["id"]
    assigned = call(
        client,
        "roles.assign",
        {"user_id": user_id, "role_codes": ["cashier"]},
        token=token,
    )
    assert assigned["ok"] is True
    assert sorted(assigned["data"]["roles"]) == ["cashier", "reader"]
    fetched = call(client, "users.get", {"user_id": user_id}, token=token)
    assert set(fetched["data"]["permissions"]) == {"patients.read", "payments.write", "invoices.read"}
    assert len(fetched["data"]["roles"]) == 2


def test_role_assign_and_revoke_are_audited(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _create_role(call, client, token, "temp", ["patients.read"])
    created = call(
        client,
        "users.create",
        {"username": "temp1", "password": "Temp#Pass123"},
        token=token,
    )
    user_id = created["data"]["id"]
    assert call(client, "roles.assign", {"user_id": user_id, "role_codes": ["temp"]}, token=token)["ok"]
    revoked = call(client, "roles.revoke", {"user_id": user_id, "role_codes": ["temp"]}, token=token)
    assert revoked["ok"] is True
    assert revoked["data"]["removed"] == ["temp"]
    with session_scope() as db:
        actions = [row.action for row in db.scalars(select(AuditLog).order_by(AuditLog.occurred_at))]
    assert "role.assigned" in actions
    assert "role.revoked" in actions
    assert "role.created" in actions


def test_no_privilege_escalation(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _create_role(call, client, token, "hr", ["users.manage"])
    _create_role(call, client, token, "auditor", ["audit.read"])
    call(
        client,
        "users.create",
        {"username": "hr1", "password": "Hr#Password123", "role_codes": ["hr"], "must_change_password": False},
        token=token,
    )
    hr = _login(call, client, "hr1", "Hr#Password123")
    assert hr["ok"] is True
    hr_token = hr["data"]["token"]

    cannot_create = call(
        client,
        "roles.create",
        {"code": "sneaky", "name": "sneaky", "permissions": ["audit.read"]},
        token=hr_token,
    )
    assert cannot_create["ok"] is False
    assert cannot_create["error"]["code"] == "FORBIDDEN"

    cannot_assign = call(
        client,
        "roles.assign",
        {"user_id": hr["data"]["user"]["id"], "role_codes": ["auditor"]},
        token=hr_token,
    )
    assert cannot_assign["ok"] is False
    assert cannot_assign["error"]["code"] == "FORBIDDEN"

    denied = call(client, "roles.list", token=hr_token)
    assert denied["error"]["code"] == "FORBIDDEN"
    audit_denied = call(client, "audit.list", token=hr_token)
    assert audit_denied["error"]["code"] == "FORBIDDEN"
    users_allowed = call(client, "users.list", token=hr_token)
    assert users_allowed["ok"] is True


def test_cannot_change_own_roles(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _create_role(call, client, token, "selfrole", ["patients.read"])
    body = call(
        client,
        "roles.assign",
        {"user_id": owner_session["user"]["id"], "role_codes": ["selfrole"]},
        token=token,
    )
    assert body["ok"] is False
    assert body["error"]["code"] == "FORBIDDEN"


def test_system_role_is_protected(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    updated = call(client, "roles.update", {"code": "owner", "name": "x"}, token=token)
    assert updated["ok"] is False
    assert updated["error"]["code"] == "FORBIDDEN"
    perms = call(
        client,
        "permissions.assign",
        {"role_code": "owner", "permission_codes": ["audit.read"]},
        token=token,
    )
    assert perms["ok"] is False
    assert perms["error"]["code"] == "FORBIDDEN"
    revoked = call(
        client,
        "permissions.revoke",
        {"role_code": "owner", "permission_codes": ["audit.read"]},
        token=token,
    )
    assert revoked["ok"] is False


def test_permission_assign_revoke_and_role_update(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _create_role(call, client, token, "ops", ["patients.read"])
    granted = call(
        client,
        "permissions.assign",
        {"role_code": "ops", "permission_codes": ["expenses.read", "reports.operational"]},
        token=token,
    )
    assert granted["ok"] is True
    assert {"patients.read", "expenses.read", "reports.operational"} <= set(granted["data"]["permissions"])
    revoked = call(
        client,
        "permissions.revoke",
        {"role_code": "ops", "permission_codes": ["reports.operational"]},
        token=token,
    )
    assert revoked["ok"] is True
    assert "reports.operational" not in revoked["data"]["permissions"]

    updated = call(
        client,
        "roles.update",
        {"code": "ops", "name": "عملیات", "description": "نقش عملیاتی", "is_active": True},
        token=token,
    )
    assert updated["ok"] is True
    assert updated["data"]["name"] == "عملیات"

    with session_scope() as db:
        actions = [row.action for row in db.scalars(select(AuditLog).order_by(AuditLog.occurred_at))]
        role = db.scalar(select(Role).where(Role.code == "ops"))
        assert role is not None
        assert role.name == "عملیات"
    assert "permission.assigned" in actions
    assert "permission.revoked" in actions
    assert "role.updated" in actions


def test_inactive_role_grants_no_permissions(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _create_role(call, client, token, "sleepy", ["patients.read"])
    created = call(
        client,
        "users.create",
        {"username": "sleepy1", "password": "Sleepy#Pass1", "role_codes": ["sleepy"]},
        token=token,
    )
    user_id = created["data"]["id"]
    call(client, "roles.update", {"code": "sleepy", "is_active": False}, token=token)
    fetched = call(client, "users.get", {"user_id": user_id}, token=token)
    assert fetched["data"]["permissions"] == []


def test_unknown_role_assignment_is_rejected(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    created = call(
        client,
        "users.create",
        {"username": "norole1", "password": "NoRole#Pass1"},
        token=token,
    )
    body = call(
        client,
        "roles.assign",
        {"user_id": created["data"]["id"], "role_codes": ["missing-role"]},
        token=token,
    )
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"

