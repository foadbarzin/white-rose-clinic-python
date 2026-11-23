"""Security primitives: tokens, hashing, session policy, RBAC."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import Forbidden, ValidationFailure
from app.core.permissions import (
    ADMIN,
    DOCTOR,
    OPERATOR,
    Principal,
    can,
    can_principal,
    doctor_scope,
    require,
    roles_for,
)
from app.core.security import (
    PasswordHash,
    SessionPolicy,
    generate_session_token,
    hash_password,
    hash_token,
    new_session_material,
    password_needs_rehash,
    token_matches,
    validate_password_strength,
    verify_password,
)

PEPPER = "pepper-" + "p" * 20


def test_session_token_is_opaque_and_hashed() -> None:
    token = generate_session_token()
    assert len(token) >= 40
    digest = hash_token(token)
    assert len(digest) == 64
    assert token not in digest
    assert token_matches(token, digest)
    assert not token_matches(token + "x", digest)


def test_tokens_are_unique() -> None:
    tokens = {generate_session_token() for _ in range(50)}
    assert len(tokens) == 50


def test_password_hash_roundtrip() -> None:
    result: PasswordHash = hash_password("Clinic#Passw0rd", pepper=PEPPER)
    assert result.algo in ("argon2id", "pbkdf2_sha256")
    assert "Clinic#Passw0rd" not in result.encoded
    assert verify_password("Clinic#Passw0rd", result.encoded, pepper=PEPPER)
    assert not verify_password("wrong-password", result.encoded, pepper=PEPPER)
    assert not verify_password("Clinic#Passw0rd", result.encoded, pepper="other-pepper")


def test_password_needs_rehash_detects_legacy() -> None:
    legacy = "pbkdf2_sha256$1000$c2FsdA==$aGFzaA=="
    assert password_needs_rehash(legacy) is True


def test_password_strength_rules() -> None:
    with pytest.raises(ValidationFailure):
        validate_password_strength("short")
    with pytest.raises(ValidationFailure):
        validate_password_strength("password")
    with pytest.raises(ValidationFailure):
        validate_password_strength("Reception123", username="reception123")
    validate_password_strength("Reception#123", username="reception")


def test_session_material_uses_policy() -> None:
    policy = SessionPolicy(absolute_ttl_seconds=3600, idle_timeout_seconds=600, max_concurrent=3)
    material = new_session_material(policy)
    assert material.issued_at.tzinfo is not None
    delta = (material.expires_at - material.issued_at).total_seconds()
    assert delta == 3600
    idle = (material.idle_expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 0 < idle <= 600


def test_rbac_matrix_defaults_to_deny() -> None:
    assert can("users.manage", ADMIN) is True
    assert can("users.manage", OPERATOR) is False
    assert can("users.manage", DOCTOR) is False
    assert can("unknown.action", ADMIN) is False
    assert can("users.manage", None) is False
    assert roles_for("unknown.action") == frozenset()


def test_rbac_new_financial_permissions() -> None:
    # TDR-012 / TDR-016: amendments and credit operations are admin-only
    assert can("invoices.amend.issue", ADMIN) is True
    assert can("invoices.amend.issue", OPERATOR) is False
    assert can("credits.adjust", ADMIN) is True
    assert can("credits.balance", OPERATOR) is True
    assert can("credits.balance", DOCTOR) is False


def test_require_raises_forbidden() -> None:
    admin = Principal(user_id="u1", username="admin", role=ADMIN)
    operator = Principal(user_id="u2", username="op", role=OPERATOR)
    assert require("settings.manage", admin) is admin
    with pytest.raises(Forbidden):
        require("settings.manage", operator)
    with pytest.raises(Forbidden):
        require("settings.manage", None)


def test_principal_helpers_and_doctor_scope() -> None:
    doctor = Principal(user_id="u3", username="doc", role=DOCTOR, linked_doctor_id="doc-1")
    assert doctor.is_doctor is True
    assert doctor_scope(doctor) == "doc-1"
    assert can_principal("invoices.read.own", doctor) is True
    assert can_principal("invoices.read.own", None) is False
    assert doctor_scope(Principal(user_id="u4", username="a", role=ADMIN)) is None
