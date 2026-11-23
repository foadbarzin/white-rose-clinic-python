"""Application startup and health endpoint tests."""

from __future__ import annotations

from app.core.config import get_settings


def test_create_app_uses_settings(app) -> None:
    assert app.title == get_settings().app_name
    assert app.version == get_settings().app_version
    assert app.state.settings.app_env == "test"


def test_healthz_contract(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "application", "version", "environment"}
    assert body["status"] == "ok"
    assert body["application"] == "White Rose Clinic"
    assert body["version"] == "0.6.0"
    assert body["environment"] == "test"


def test_healthz_has_request_id_and_security_headers(client) -> None:
    response = client.get("/healthz")
    assert response.headers.get("X-Request-Id")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in response.headers.get("Content-Security-Policy", "")


def test_readyz_reports_database_state(client) -> None:
    response = client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["database"] in ("ok", "unavailable")
    assert body["status"] in ("ok", "degraded")


def test_readyz_after_migration(migrated_client) -> None:
    body = migrated_client.get("/readyz").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_version_metadata(client) -> None:
    body = client.get("/api/meta/version").json()
    assert body["api_contract"] == "action-v1"
    assert body["timezone"] == "Asia/Tehran"
    assert body["version"] == "0.6.0"


def test_desktop_info_contract(client) -> None:
    body = client.get("/desktop/info").json()
    assert body["desktop"] is False
    assert body["mode"] == "server"
    assert body["version"] == "0.6.0"


def test_openapi_is_not_leaking( client) -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    # only the gateway/health surface exists in phase 2
    paths = response.json()["paths"]
    assert "/healthz" in paths
    assert "/api" in paths
