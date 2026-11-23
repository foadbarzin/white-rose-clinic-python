"""Phase 3 user administration tests."""

from __future__ import annotations

from sqlalchemy import select

from app.database.models.system import AuditLog
from app.database.session import session_scope

OWNER_ACTIVE = "Owner#Phase3-Active"


def _login(call, client, username: str, password: str) -> dict:
    return call(client, "auth.login", {"username": username, "password": password})


def _make_role(call, client, token, code="reception", permissions=("patients.read",)) -> None:
    body = call(
        client,
        "roles.create",
        {"code": code, "name": code, "permissions": list(permissions)},
        token=token,
    )
    assert body["ok"] is True, body


def test_create_list_and_get_user(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _make_role(call, client, token)
    created = call(
        client,
        "users.create",
        {
            "username": "reception2",
            "password": "Reception#456",
            "display_name": "پذیرش دو",
            "role_codes": ["reception"],
        },
        token=token,
    )
    assert created["ok"] is True, created
    data = created["data"]
    assert data["username"] == "reception2"
    assert data["roles"] == ["reception"]
    assert data["must_change_password"] is True
    assert "password_hash" not in data and "password" not in data

    listed = call(client, "users.list", token=token)
    assert listed["ok"] is True
    assert listed["data"]["count"] == 2
    fetched = call(client, "users.get", {"user_id": data["id"]}, token=token)
    assert fetched["data"]["permissions"] == ["patients.read"]
    assert fetched["data"]["roles_detail"][0]["code"] == "reception"


def test_duplicate_and_weak_password_rejected(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _make_role(call, client, token)
    first = call(
        client,
        "users.create",
        {"username": "dup1", "password": "Dup#Password1", "role_codes": ["reception"]},
        token=token,
    )
    assert first["ok"] is True
    duplicate = call(
        client,
        "users.create",
        {"username": "dup1", "password": "Dup#Password2", "role_codes": ["reception"]},
        token=token,
    )
    assert duplicate["error"]["code"] == "DUPLICATE"
    weak = call(
        client,
        "users.create",
        {"username": "weak1", "password": "short", "role_codes": ["reception"]},
        token=token,
    )
    assert weak["error"]["code"] == "VALIDATION"
    invalid_name = call(
        client,
        "users.create",
        {"username": "A B!", "password": "Dup#Password3", "role_codes": ["reception"]},
        token=token,
    )
    assert invalid_name["error"]["code"] == "VALIDATION"


def test_update_user_is_audited(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _make_role(call, client, token)
    created = call(
        client,
        "users.create",
        {"username": "upd1", "password": "Update#Pass1", "role_codes": ["reception"]},
        token=token,
    )
    user_id = created["data"]["id"]
    updated = call(
        client,
        "users.update",
        {"user_id": user_id, "display_name": "نام تازه", "must_change_password": False},
        token=token,
    )
    assert updated["ok"] is True
    assert updated["data"]["display_name"] == "نام تازه"
    with session_scope() as db:
        row = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "user.updated")
            .order_by(AuditLog.occurred_at.desc())
        )
        assert row is not None
        assert row.before_json["display_name"] != row.after_json["display_name"]
        assert row.after_json["must_change_password"] is False
        assert "password_hash" not in str(row.after_json)


def test_cannot_disable_or_edit_own_account(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    user_id = owner_session["user"]["id"]
    disabled = call(client, "users.disable", {"user_id": user_id}, token=token)
    assert disabled["ok"] is False
    assert disabled["error"]["code"] == "FORBIDDEN"


def test_last_rbac_holder_cannot_be_disabled(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    call(
        client,
        "roles.create",
        {"code": "desk", "name": "پذیرش", "permissions": ["users.manage"]},
        token=token,
    )
    call(
        client,
        "users.create",
        {
            "username": "desk1",
            "password": "Desk#Password1",
            "role_codes": ["desk"],
            "must_change_password": False,
        },
        token=token,
    )
    desk_token = _login(call, client, "desk1", "Desk#Password1")["data"]["token"]
    owner_id = owner_session["user"]["id"]
    blocked = call(client, "users.disable", {"user_id": owner_id}, token=desk_token)
    assert blocked["ok"] is False
    assert "مدیریت نقش" in blocked["error"]["message"]


def test_admin_password_reset_enforces_change(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _make_role(call, client, token)
    created = call(
        client,
        "users.create",
        {"username": "reset1", "password": "Reset#Pass1", "role_codes": ["reception"]},
        token=token,
    )
    user_id = created["data"]["id"]
    call(client, "users.update", {"user_id": user_id, "must_change_password": False}, token=token)
    old_token = _login(call, client, "reset1", "Reset#Pass1")["data"]["token"]
    reset = call(
        client,
        "users.change_password",
        {"user_id": user_id, "new_password": "Reset#Pass2"},
        token=token,
    )
    assert reset["ok"] is True
    assert reset["data"]["sessions_revoked"] >= 1
    assert call(client, "auth.me", token=old_token)["error"]["code"] == "UNAUTHORIZED"
    assert _login(call, client, "reset1", "Reset#Pass1")["error"]["code"] == "AUTH_FAILED"
    login = _login(call, client, "reset1", "Reset#Pass2")
    assert login["ok"] is True
    assert login["data"]["mustChangePassword"] is True


def test_self_change_password_validation(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    wrong = call(
        client,
        "auth.change_password",
        {"oldPassword": "Wrong#Old123", "newPassword": "Whatever#123"},
        token=token,
    )
    assert wrong["error"]["code"] == "AUTH_FAILED"
    same = call(
        client,
        "auth.change_password",
        {"oldPassword": OWNER_ACTIVE, "newPassword": OWNER_ACTIVE},
        token=token,
    )
    assert same["error"]["code"] == "VALIDATION"


def test_user_activity_and_no_delete_action(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    _make_role(call, client, token)
    created = call(
        client,
        "users.create",
        {"username": "act1", "password": "Activity#Pass1", "role_codes": ["reception"]},
        token=token,
    )
    user_id = created["data"]["id"]
    activity = call(client, "users.activity", {"user_id": user_id}, token=token)
    assert activity["ok"] is True
    actions = [row["action"] for row in activity["data"]["rows"]]
    assert "user.created" in actions
    deleted = call(client, "users.delete", {"user_id": user_id}, token=token)
    assert deleted["ok"] is False
    assert deleted["error"]["code"] == "NOT_FOUND"

