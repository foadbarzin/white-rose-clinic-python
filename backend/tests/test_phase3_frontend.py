"""Phase 3 frontend integration tests (preserved RTL UI + new admin screens)."""

from __future__ import annotations


def test_version_is_visible_and_injected(client) -> None:
    html = client.get("/").text
    assert 'window.WRC_APP_VERSION = "0.6.0"' in html
    assert "js-app-version" in html


def test_login_page_is_preserved_without_public_bootstrap(client) -> None:
    html = client.get("/").text
    assert "ورود به سامانه" in html
    assert 'id="loginUser"' in html
    assert 'id="loginPass"' in html
    assert 'id="bootUser"' not in html
    assert 'id="bootBtn"' not in html
    assert "setup.bootstrapAdmin" not in html
    assert "ابزار مدیریت سرور" in html


def test_admin_views_are_registered(client) -> None:
    html = client.get("/").text
    for marker in (
        "id:'roles'",
        "id:'audit'",
        "function viewRoles(",
        "function viewAudit(",
        "function viewUsers(",
        "roles.list",
        "audit.list",
        "permissions.list",
    ):
        assert marker in html, marker


def test_session_controls_in_shell(client) -> None:
    html = client.get("/").text
    assert "logoutAllBtn" in html
    assert "auth.logout_all" in html
    assert "auth.changePassword" in html
    assert "auth.me" in html


def test_users_management_actions_present(client) -> None:
    html = client.get("/").text
    for marker in (
        "users.create",
        "users.disable",
        "users.enable",
        "users.unlock",
        "users.sessions",
        "users.revoke_sessions",
        "users.activity",
        "roles.assign",
        "roles.revoke",
    ):
        assert marker in html, marker


def test_existing_routes_and_brand_are_intact(client) -> None:
    html = client.get("/").text
    for route in (
        "dashboard",
        "invoices",
        "customers",
        "commissions",
        "expenses",
        "reports",
        "doctors",
        "operators",
        "services",
        "commissionRules",
        "users",
        "settings",
    ):
        assert f"id:'{route}'" in html, route
    assert "ROSE SEFID" in html
    assert 'dir="rtl"' in html
    assert "rslGold" in html  # original brand asset is still inlined


def test_ui_uses_legacy_contract(client) -> None:
    html = client.get("/").text
    assert "apiCall" in html
    assert "google.script.run" in html
    assert "fetch('/api'" in html
