"""Phase 3 security hardening tests (CORS, headers, no leakage, entropy)."""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import Settings
from app.core.security import generate_session_token, hash_password
from app.database.models.identity import User
from app.database.session import session_scope

OWNER_ACTIVE = "Owner#Phase3-Active"


def test_cors_default_is_same_origin_only(migrated_client) -> None:
    response = migrated_client.options(
        "/api",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}


def test_cors_can_be_configured_explicitly(settings, migrated_db) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    payload = settings.model_dump()
    payload["cors_allow_origins"] = ["http://localhost:3000"]
    configured = Settings.model_validate(payload)
    with TestClient(create_app(configured)) as client:
        response = client.options(
            "/api",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_security_headers_present(migrated_client) -> None:
    response = migrated_client.get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"


def test_validation_errors_do_not_echo_secret_values(migrated_client) -> None:
    secret = "SuperSecret#Value#123"
    response = migrated_client.post(
        "/api",
        json={"action": "auth.login", "payload": {"username": ["bad"], "password": secret}, "token": ""},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "VALIDATION"
    assert secret not in response.text
    assert "input" not in str(body["error"]["details"])


def test_password_salts_are_unique(owner_credentials) -> None:
    first = hash_password("Same#Password1", pepper="pepper-value")
    second = hash_password("Same#Password1", pepper="pepper-value")
    assert first.encoded != second.encoded


def test_session_tokens_are_long_and_unique() -> None:
    tokens = {generate_session_token() for _ in range(20)}
    assert len(tokens) == 20
    for token in tokens:
        assert len(token) >= 40


def test_sqli_like_username_is_safe(migrated_client, call) -> None:
    body = call(
        migrated_client,
        "auth.login",
        {"username": "' OR 1=1 --", "password": "Anything#123"},
    )
    assert body["ok"] is False
    assert body["error"]["code"] == "AUTH_FAILED"
    with session_scope() as db:
        assert db.scalar(select(User).where(User.username == "owner")) is None


def test_owner_account_password_hash_never_exposed(owner_session, call) -> None:
    fetched = call(
        owner_session["client"],
        "users.get",
        {"user_id": owner_session["user"]["id"]},
        token=owner_session["token"],
    )
    assert fetched["ok"] is True
    payload = str(fetched)
    assert "password_hash" not in payload
    assert "argon2" not in payload
