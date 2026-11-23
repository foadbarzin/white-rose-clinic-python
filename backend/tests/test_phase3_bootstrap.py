"""Phase 3 secure bootstrap tests (CLI only, no default accounts)."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import select

from app.cli import bootstrap_owner, main
from app.core.permissions import PERMISSION_CODES
from app.database.models.identity import User
from app.database.models.rbac import Role, RolePermission, UserRole
from app.database.session import session_scope

INITIAL = "Owner#Phase3-Initial"
ACTIVE = "Owner#Phase3-Active"


def test_fresh_database_has_no_accounts_or_roles(migrated_db, migrated_client, call) -> None:
    with session_scope() as db:
        for model in (User, Role, RolePermission, UserRole):
            assert db.scalar(select(model).limit(1)) is None
    status = call(migrated_client, "system.bootstrapStatus")
    assert status["ok"] is True
    assert status["data"]["hasAdmin"] is False
    assert status["data"]["bootstrapAvailable"] is True
    assert status["data"]["databaseReady"] is True


def test_bootstrap_creates_protected_owner_role(owner_credentials, migrated_client, call) -> None:
    with session_scope() as db:
        role = db.scalar(select(Role).where(Role.code == "owner"))
        assert role is not None
        assert role.is_system is True
        assert role.legacy_role == "admin"
        perms = {
            row.permission_code
            for row in db.scalars(
                select(RolePermission).where(RolePermission.role_id == role.id)
            )
        }
        assert perms == set(PERMISSION_CODES)
        user = db.scalar(select(User).where(User.username == "owner"))
        assert user is not None
        assert user.must_change_password is True
        assert user.password_hash.startswith("$argon2") or user.password_hash.startswith(
            "pbkdf2_sha256$"
        )
    login = call(
        migrated_client, "auth.login", {"username": "owner", "password": INITIAL}
    )
    assert login["ok"] is True
    assert login["data"]["mustChangePassword"] is True


def test_second_bootstrap_is_refused(owner_credentials) -> None:
    with pytest.raises(SystemExit):
        bootstrap_owner("intruder", "Intruder#Pass1", "نفوذی", generated=False)


def test_cli_requires_explicit_confirmation(migrated_db) -> None:
    with pytest.raises(SystemExit):
        main(["bootstrap-owner", "--username", "owner2", "--generate-password"])
    with pytest.raises(SystemExit):
        main(["bootstrap-owner", "--username", "owner2", "--confirm"])


def test_cli_password_stdin_bootstrap(monkeypatch, migrated_db, migrated_client, call) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Cli#Password123\n"))
    code = main(
        ["bootstrap-owner", "--username", "cliowner", "--password-stdin", "--confirm"]
    )
    assert code == 0
    login = call(
        migrated_client, "auth.login", {"username": "cliowner", "password": "Cli#Password123"}
    )
    assert login["ok"] is True
    assert login["data"]["mustChangePassword"] is True


def test_public_bootstrap_action_is_disabled(migrated_client, call) -> None:
    body = call(
        migrated_client,
        "setup.bootstrapAdmin",
        {"username": "attacker", "password": "Attacker#Pass1"},
    )
    assert body["ok"] is False
    assert body["error"]["code"] == "ACTION_NOT_IMPLEMENTED"
    with session_scope() as db:
        assert db.scalar(select(User).where(User.username == "attacker")) is None


def test_cli_status_reports_counts(owner_credentials, capsys) -> None:
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "users=1" in output
    assert "roles=1" in output
