"""Phase 3 audit trail tests (filters, immutability, no secrets, hash chain)."""

from __future__ import annotations

from sqlalchemy import select

from app.core.security import hash_token
from app.database.models.identity import UserSession
from app.database.models.system import AuditLog
from app.database.session import session_scope
from app.services.audit import AuditService

OWNER_ACTIVE = "Owner#Phase3-Active"


def test_audit_list_and_filters(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    call(
        client,
        "auth.login",
        {"username": "owner", "password": "Wrong#Password1"},
    )
    listed = call(client, "audit.list", {"limit": 20}, token=token)
    assert listed["ok"] is True
    assert listed["data"]["total"] > 0
    assert listed["data"]["rows"][0]["request_id"] or listed["data"]["rows"][0]["id"]

    failed = call(client, "audit.list", {"result": "fail", "limit": 20}, token=token)
    assert failed["ok"] is True
    assert all(row["result"] == "fail" for row in failed["data"]["rows"])

    logins = call(client, "audit.list", {"action": "auth.login_success"}, token=token)
    assert logins["ok"] is True
    assert all(row["action"] == "auth.login_success" for row in logins["data"]["rows"])


def test_audit_get_and_not_found(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    listed = call(client, "audit.list", {"limit": 1}, token=token)
    event_id = listed["data"]["rows"][0]["id"]
    fetched = call(client, "audit.get", {"id": event_id}, token=token)
    assert fetched["ok"] is True
    assert fetched["data"]["event"]["id"] == event_id
    missing = call(client, "audit.get", {"id": "00000000-0000-4000-8000-000000000000"}, token=token)
    assert missing["error"]["code"] == "NOT_FOUND"


def test_audit_never_contains_secrets(owner_session, call) -> None:
    client = owner_session["client"]
    marker_password = "Marker#Secret#987654"
    call(client, "auth.login", {"username": "owner", "password": marker_password})
    token = owner_session["token"]
    # refresh token in a session row to ensure the raw token is not in audit
    with session_scope() as db:
        rows = list(db.scalars(select(AuditLog)))
        blob = " ".join(
            f"{row.action} {row.before_json} {row.after_json} {row.message}" for row in rows
        )
        assert marker_password not in blob
        assert token not in blob
        stored = db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_token(token))
        )
        assert stored is not None
    listed = call(client, "audit.list", {"limit": 200}, token=token)
    assert marker_password not in str(listed)


def test_audit_hash_chain_detects_tampering(owner_session, call) -> None:
    token = owner_session["token"]
    with session_scope() as db:
        rows = list(db.scalars(select(AuditLog).order_by(AuditLog.occurred_at)))
        assert len(rows) >= 2
        assert AuditService.verify_chain(db, rows) is True
        target = rows[-1]
        original = target.after_json
        target.after_json = {"tampered": True}
        db.flush()
        assert AuditService.verify_chain(db, rows) is False
        target.after_json = original
        db.flush()
    _ = token


def test_audit_is_read_only_through_api(owner_session, call) -> None:
    client, token = owner_session["client"], owner_session["token"]
    for action in ("audit.update", "audit.delete", "audit.wipe"):
        body = call(client, action, token=token)
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"


def test_audit_timestamps_use_tehran_offset(owner_session, call) -> None:
    body = call(owner_session["client"], "audit.list", {"limit": 1}, token=owner_session["token"])
    occurred = body["data"]["rows"][0]["occurred_at"]
    assert occurred is not None
    assert "+03:30" in occurred


def test_audit_requires_permission(migrated_client, call) -> None:
    body = call(migrated_client, "audit.list")
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"
