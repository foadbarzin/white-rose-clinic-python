"""Shared pytest fixtures. Every test is independent and repeatable."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(ROOT)

TEST_SECRET = "test-secret-" + "x" * 40


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the application at a throwaway SQLite database."""
    path = tmp_path / "test.db"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("TIMEZONE", "Asia/Tehran")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{path.as_posix()}")
    # keep Argon2id but cheaper in tests (production defaults remain strong)
    monkeypatch.setenv("ARGON2_MEMORY_KIB", "8192")
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")

    from app.core.config import reset_settings_cache
    from app.core.rate_limit import reset_limiter
    from app.database.session import dispose_engines

    reset_settings_cache()
    reset_limiter()
    dispose_engines()
    yield path
    reset_settings_cache()
    reset_limiter()
    dispose_engines()


@pytest.fixture()
def settings(db_path: Path):
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture()
def migrated_db(db_path: Path) -> Path:
    """Run the real Alembic chain against the test database."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")
    return db_path


@pytest.fixture()
def app(settings):
    from app.main import create_app

    return create_app(settings)


@pytest.fixture()
def client(app) -> Iterator["object"]:
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def migrated_client(migrated_db, settings) -> Iterator["object"]:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


OWNER_INITIAL_PASSWORD = "Owner#Phase3-Initial"
OWNER_PASSWORD = "Owner#Phase3-Active"


@pytest.fixture()
def call():
    """Call a gateway action and return the decoded envelope."""

    def _call(client, action: str, payload: dict | None = None, token: str = "") -> dict:
        response = client.post(
            "/api", json={"action": action, "payload": payload or {}, "token": token}
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _call


@pytest.fixture()
def owner_credentials(migrated_db):
    """Create the first owner through the secure CLI (no default password)."""
    from app.cli import bootstrap_owner

    return bootstrap_owner(
        "owner", OWNER_INITIAL_PASSWORD, "مالک آزمایشی", generated=False
    )


@pytest.fixture()
def owner_session(owner_credentials, migrated_client, call):
    """Owner with a completed forced password change (ready for admin actions)."""
    login = call(
        migrated_client,
        "auth.login",
        {"username": "owner", "password": OWNER_INITIAL_PASSWORD},
    )
    assert login["ok"], login
    assert login["data"]["mustChangePassword"] is True
    token = login["data"]["token"]
    changed = call(
        migrated_client,
        "auth.change_password",
        {"oldPassword": OWNER_INITIAL_PASSWORD, "newPassword": OWNER_PASSWORD},
        token=token,
    )
    assert changed["ok"], changed
    return {
        "client": migrated_client,
        "token": token,
        "password": OWNER_PASSWORD,
        "user": login["data"]["user"],
    }
