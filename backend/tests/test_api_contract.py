"""Action gateway contract tests (legacy ``{action,payload,token}`` envelope)."""

from __future__ import annotations

import pytest


def post(client, action: str, payload: dict | None = None, token: str = ""):
    return client.post("/api", json={"action": action, "payload": payload or {}, "token": token})


def test_ping_contract(client) -> None:
    response = post(client, "system.ping")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["app"]["version"] == "0.5.0"
    assert body["data"]["app"]["timezone"] == "Asia/Tehran"
    assert response.headers.get("X-Request-Id")


def test_calendar_is_public_and_jalali(client) -> None:
    body = post(client, "system.calendar").json()
    assert body["ok"] is True
    data = body["data"]
    assert data["timezone"] == "Asia/Tehran"
    assert data["week_label"] == "شنبه‌محور"
    assert data["jalali"]["year"] > 1300
    assert data["month_start"] <= data["today"] <= data["month_end"]


def test_unknown_action_returns_not_found(client) -> None:
    body = post(client, "does.not.exist").json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_protected_action_requires_session(client) -> None:
    for action in ("users.list", "customers.list", "invoices.issue"):
        body = post(client, action).json()
        assert body["ok"] is False, action
        assert body["error"]["code"] == "UNAUTHORIZED", action
        assert body["request_id"]


def test_unimplemented_action_with_session(client, monkeypatch) -> None:
    from app.api import router as api_router
    from app.core.permissions import ADMIN, Principal

    principal = Principal(user_id="00000000-0000-7000-8000-000000000001", username="admin", role=ADMIN)
    monkeypatch.setattr(api_router, "resolve_session", lambda token: principal)
    body = post(client, "customers.list", token="opaque-token").json()
    assert body["ok"] is False
    assert body["error"]["code"] == "ACTION_NOT_IMPLEMENTED"


def test_login_is_documented_but_not_implemented(client) -> None:
    body = post(client, "auth.login", {"username": "admin", "password": "secret"}).json()
    assert body["ok"] is False
    assert body["error"]["code"] == "ACTION_NOT_IMPLEMENTED"


def test_invalid_body_is_rejected_with_envelope(client) -> None:
    response = client.post("/api", json={"payload": {}})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"


def test_malformed_json_is_rejected_without_stack_trace(client) -> None:
    response = client.post(
        "/api", content=b"{not-json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"
    assert "Traceback" not in response.text


def test_bootstrap_status_before_migration_is_safe(client) -> None:
    body = post(client, "system.bootstrapStatus").json()
    assert body["ok"] is True
    data = body["data"]
    assert data["hasAdmin"] is False
    assert data["spreadsheetConfigured"] is False
    assert "databaseReady" in data


def test_bootstrap_status_after_migration_has_no_seeded_admin(migrated_client) -> None:
    body = post(migrated_client, "system.bootstrapStatus").json()
    data = body["data"]
    assert data["databaseReady"] is True
    assert data["hasAdmin"] is False


def test_contract_metadata(client) -> None:
    body = client.get("/api/meta/contract").json()
    assert body["ok"] is True
    assert "system.ping" in body["data"]["implemented"]
    assert body["data"]["contract"] == "action-v1"


@pytest.mark.parametrize("action", ["invoices.issue", "payments.add", "reports.summary"])
def test_financial_actions_are_not_executed(client, action: str) -> None:
    body = post(client, action).json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"
