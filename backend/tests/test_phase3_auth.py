"""Phase 3 authentication and session tests (real DB, real Argon2id)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import argon2_available, hash_token
from app.database.models.identity import User, UserSession
from app.database.models.system import AuditLog
from app.database.session import session_scope

OWNER_INITIAL = "Owner#Phase3-Initial"
OWNER_ACTIVE = "Owner#Phase3-Active"


def _login(call, client, username: str, password: str) -> dict:
    return call(client, "auth.login", {"username": username, "password": password})


def _audit_actions() -> list[str]:
    with session_scope() as db:
        return [row.action for row in db.scalars(select(AuditLog).order_by(AuditLog.occurred_at))]


def test_login_success_and_password_must_change(owner_credentials, migrated_client, call) -> None:
    body = _login(call, migrated_client, "owner", OWNER_INITIAL)
    assert body["ok"] is True
    data = body["data"]
    assert data["mustChangePassword"] is True
    assert data["token"]
    assert data["user"]["username"] == "owner"
    assert data["user"]["role"] == "admin"
    assert "rbac.manage" in data["user"]["permissions"]
    assert "auth.login_success" in _audit_actions()


def test_must_change_password_blocks_admin_actions(owner_credentials, migrated_client, call) -> None:
    login = _login(call, migrated_client, "owner", OWNER_INITIAL)
    token = login["data"]["token"]
    blocked = call(migrated_client, "users.list", token=token)
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert call(migrated_client, "auth.me", token=token)["ok"] is True


def test_wrong_password_and_unknown_user_are_indistinguishable(
    owner_session, migrated_client, call
) -> None:
    wrong = _login(call, migrated_client, "owner", "Wrong#Password1")
    unknown = _login(call, migrated_client, "no-such-user", "Wrong#Password1")
    assert wrong["error"]["code"] == unknown["error"]["code"] == "AUTH_FAILED"
    assert wrong["error"]["message"] == unknown["error"]["message"]
    assert wrong["error"]["message"] == "نام کاربری یا رمز عبور نادرست است."


def test_password_and_token_are_hashed(owner_session, migrated_client, call) -> None:
    token = owner_session["token"]
    with session_scope() as db:
        user = db.scalar(select(User).where(User.username == "owner"))
        assert user is not None
        if argon2_available():
            assert user.password_hash.startswith("$argon2")
        assert OWNER_ACTIVE not in user.password_hash
        session_row = db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_token(token))
        )
        assert session_row is not None
        assert session_row.token_hash != token
        assert len(session_row.token_hash) == 64
        assert token not in (session_row.token_hash or "")


def test_inactive_user_cannot_login_and_loses_session(
    owner_session, migrated_client, call
) -> None:
    client, token = owner_session["client"], owner_session["token"]
    role = call(
        client,
        "roles.create",
        {"code": "reception", "name": "پذیرش", "permissions": ["patients.read"]},
        token=token,
    )
    assert role["ok"] is True, role
    created = call(
        client,
        "users.create",
        {
            "username": "reception1",
            "password": "Reception#123",
            "display_name": "پذیرش یک",
            "role_codes": ["reception"],
            "must_change_password": False,
        },
        token=token,
    )
    assert created["ok"] is True, created
    user_id = created["data"]["id"]
    login = _login(call, client, "reception1", "Reception#123")
    assert login["ok"] is True
    operator_token = login["data"]["token"]

    disabled = call(client, "users.disable", {"user_id": user_id}, token=token)
    assert disabled["ok"] is True, disabled
    assert call(client, "auth.me", token=operator_token)["error"]["code"] == "UNAUTHORIZED"
    assert _login(call, client, "reception1", "Reception#123")["error"]["code"] == "AUTH_FAILED"


def test_account_lockout_and_admin_unlock(owner_session, migrated_client, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    call(
        client,
        "roles.create",
        {"code": "lab", "name": "آزمایشگاه", "permissions": ["patients.read"]},
        token=token,
    )
    created = call(
        client,
        "users.create",
        {
            "username": "lab1",
            "password": "Lab#Password1",
            "role_codes": ["lab"],
            "must_change_password": False,
        },
        token=token,
    )
    user_id = created["data"]["id"]
    for _ in range(5):
        _login(call, client, "lab1", "Bad#Password1")
    locked = _login(call, client, "lab1", "Lab#Password1")
    assert locked["error"]["code"] == "AUTH_LOCKED"
    assert "account.locked" in _audit_actions()

    unlocked = call(client, "users.unlock", {"user_id": user_id}, token=token)
    assert unlocked["ok"] is True
    assert _login(call, client, "lab1", "Lab#Password1")["ok"] is True
    assert "account.unlocked" in _audit_actions()


def test_login_rate_limit_per_ip(owner_session, migrated_client, call) -> None:
    responses = [
        _login(call, migrated_client, f"ghost{index}", "Wrong#Password1") for index in range(11)
    ]
    codes = [item["error"]["code"] for item in responses if not item["ok"]]
    assert codes[-1] == "RATE_LIMITED"
    assert "auth.login_rate_limited" in _audit_actions()


def test_idle_and_absolute_expiry(owner_session, migrated_client, call) -> None:
    login = _login(call, migrated_client, "owner", OWNER_ACTIVE)
    token = login["data"]["token"]
    session_id = login["data"]["session"]["id"]

    with session_scope() as db:
        row = db.get(UserSession, uuid.UUID(session_id))
        assert row is not None
        row.idle_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    expired = call(migrated_client, "auth.me", token=token)
    assert expired["ok"] is False
    assert expired["error"]["code"] == "UNAUTHORIZED"
    assert "منقضی" in expired["error"]["message"]
    assert "auth.session_expired" in _audit_actions()

    login2 = _login(call, migrated_client, "owner", OWNER_ACTIVE)
    token2 = login2["data"]["token"]
    with session_scope() as db:
        row = db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_token(token2))
        )
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert call(migrated_client, "auth.me", token=token2)["error"]["code"] == "UNAUTHORIZED"


def test_logout_and_token_reuse(owner_session, migrated_client, call) -> None:
    login = _login(call, migrated_client, "owner", OWNER_ACTIVE)
    token = login["data"]["token"]
    assert call(migrated_client, "auth.logout", token=token)["ok"] is True
    reuse = call(migrated_client, "auth.me", token=token)
    assert reuse["error"]["code"] == "UNAUTHORIZED"
    assert "ابطال" in reuse["error"]["message"]
    actions = _audit_actions()
    assert "auth.logout" in actions
    assert "auth.session_revoked" in actions


def test_logout_all_closes_every_session(owner_session, migrated_client, call) -> None:
    first = _login(call, migrated_client, "owner", OWNER_ACTIVE)["data"]["token"]
    second = _login(call, migrated_client, "owner", OWNER_ACTIVE)["data"]["token"]
    assert first != second
    body = call(migrated_client, "auth.logout_all", token=first)
    assert body["ok"] is True
    assert body["data"]["sessions_revoked"] >= 2
    assert call(migrated_client, "auth.me", token=second)["error"]["code"] == "UNAUTHORIZED"
    assert "auth.logout_all" in _audit_actions()


def test_admin_can_revoke_user_sessions(owner_session, migrated_client, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    call(
        client,
        "roles.create",
        {"code": "assistant", "name": "دستیار", "permissions": ["patients.read"]},
        token=token,
    )
    created = call(
        client,
        "users.create",
        {
            "username": "assistant1",
            "password": "Assistant#123",
            "role_codes": ["assistant"],
            "must_change_password": False,
        },
        token=token,
    )
    user_id = created["data"]["id"]
    user_token = _login(call, client, "assistant1", "Assistant#123")["data"]["token"]
    listed = call(client, "users.sessions", {"user_id": user_id}, token=token)
    assert listed["ok"] is True
    assert listed["data"]["count"] == 1
    revoked = call(client, "users.revoke_sessions", {"user_id": user_id}, token=token)
    assert revoked["ok"] is True
    assert call(client, "auth.me", token=user_token)["error"]["code"] == "UNAUTHORIZED"


def test_password_change_revokes_other_sessions(owner_session, migrated_client, call) -> None:
    first = owner_session["token"]
    second = _login(call, migrated_client, "owner", OWNER_ACTIVE)["data"]["token"]
    changed = call(
        migrated_client,
        "auth.change_password",
        {"oldPassword": OWNER_ACTIVE, "newPassword": "Owner#Phase3-Third"},
        token=first,
    )
    assert changed["ok"] is True
    assert changed["data"]["sessions_revoked"] >= 1
    assert call(migrated_client, "auth.me", token=second)["error"]["code"] == "UNAUTHORIZED"
    assert call(migrated_client, "auth.me", token=first)["ok"] is True
    assert "auth.password_changed" in _audit_actions()


def test_session_headers_carry_no_cookie(owner_session, migrated_client, call) -> None:
    response = migrated_client.post(
        "/api",
        json={"action": "auth.login", "payload": {"username": "owner", "password": OWNER_ACTIVE}, "token": ""},
    )
    assert response.status_code == 200
    assert "set-cookie" not in {key.lower() for key in response.headers.keys()}

