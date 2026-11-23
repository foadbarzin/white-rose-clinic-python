"""Preserved UI tests: the existing HTML is served unchanged (plus a shim)."""

from __future__ import annotations


def test_index_renders_preserved_ui(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "ROSE SEFID BEAUTY CLINIC" in html
    assert 'dir="rtl"' in html
    assert "Client_Styles" not in html  # includes already resolved
    assert "<?!=" not in html  # no unresolved Apps Script scriptlets


def test_shim_provides_api_call(client) -> None:
    html = client.get("/").text
    assert "window.google.script" in html
    assert "apiCall" in html
    assert "/api" in html


def test_all_navigation_routes_are_preserved(client) -> None:
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
        assert f"id:'{route}'" in html, f"route {route} missing from the preserved UI"


def test_brand_assets_are_preserved(client) -> None:
    html = client.get("/").text
    assert "WRC_LOGO_HTML" in html
    assert "rslGold" in html  # logo gradient id from the reference brand asset


def test_favicon_no_content(client) -> None:
    assert client.get("/favicon.ico").status_code == 204


def test_logo_asset_is_served(client) -> None:
    response = client.get("/assets/logo.svg")
    assert response.status_code == 200
    assert "<svg" in response.text


def test_html_security_headers(client) -> None:
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
