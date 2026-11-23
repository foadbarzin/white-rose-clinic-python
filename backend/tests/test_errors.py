"""Error handling tests: safe envelopes, no stack traces, legacy status codes."""

from __future__ import annotations


def test_unhandled_exception_is_masked(client) -> None:
    from fastapi import HTTPException

    def boom() -> None:
        raise RuntimeError("very-secret-internal-detail")

    client.app.add_api_route("/__boom", boom, methods=["GET"])
    response = client.get("/__boom")
    assert response.status_code == 500
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INTERNAL"
    assert "very-secret-internal-detail" not in response.text
    assert "Traceback" not in response.text
    assert body["request_id"]
    _ = HTTPException  # imported to document that app-level HTTP errors are unchanged


def test_wrc_error_uses_legacy_envelope(client) -> None:
    from app.core.exceptions import Forbidden

    def forbidden() -> None:
        raise Forbidden()

    client.app.add_api_route("/__forbidden", forbidden, methods=["GET"])
    response = client.get("/__forbidden")
    # legacy contract: domain errors travel over HTTP 200
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["error"]["message"] == "دسترسی مجاز نیست."


def test_validation_errors_outside_api_are_422(client) -> None:
    def needs_int(x: int) -> dict[str, int]:
        return {"x": x}

    client.app.add_api_route("/__validate", needs_int, methods=["GET"])
    response = client.get("/__validate?x=not-a-number")
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"


def test_error_messages_are_persian(client) -> None:
    body = client.post("/api", json={"action": "does.not.exist"}).json()
    message = body["error"]["message"]
    assert any("\u0600" <= char <= "\u06FF" for char in message)
