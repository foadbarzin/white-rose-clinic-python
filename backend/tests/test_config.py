"""Configuration validation tests (no real secrets, no external services)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

GOOD_SECRET = "unit-test-secret-" + "a" * 40


def make(**overrides) -> Settings:
    data = {"secret_key": GOOD_SECRET, "_env_file": None}
    data.update(overrides)
    return Settings(**data)  # type: ignore[arg-type]


def test_development_defaults() -> None:
    settings = make()
    assert settings.app_name == "White Rose Clinic"
    assert settings.app_version == "0.6.0"
    assert settings.app_env == "development"
    assert settings.is_sqlite is True
    assert settings.timezone == "Asia/Tehran"
    assert settings.tzinfo.key == "Asia/Tehran"
    assert settings.api_port == 8000
    assert settings.session_ttl == 12 * 60 * 60
    assert settings.session_idle_seconds == 30 * 60


def test_timezone_is_configurable() -> None:
    assert make(timezone="UTC").timezone == "UTC"


def test_invalid_timezone_rejected() -> None:
    with pytest.raises(ValidationError):
        make(timezone="Mars/Olympus")


def test_invalid_environment_rejected() -> None:
    with pytest.raises(ValidationError):
        make(app_env="staging")


def test_short_secret_rejected() -> None:
    with pytest.raises(ValidationError):
        make(secret_key="short")


def test_postgres_url_uses_psycopg_driver() -> None:
    settings = make(database_url="postgresql://user:pass@localhost:5432/wrc")
    assert settings.database_url == "postgresql+psycopg://user:pass@localhost:5432/wrc"
    assert settings.is_postgresql is True
    assert settings.is_sqlite is False


def test_unknown_database_scheme_rejected() -> None:
    with pytest.raises(ValidationError):
        make(database_url="mysql://user:pass@localhost/wrc")


def test_production_rejects_sqlite() -> None:
    with pytest.raises(ValidationError):
        make(
            app_env="production",
            database_url="sqlite+pysqlite:///./var/prod.db",
            secret_key="prod-" + "b" * 50,
        )


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ValidationError):
        make(
            app_env="production",
            database_url="postgresql+psycopg://user:pass@localhost/wrc",
            secret_key="CHANGE_ME_generate_a_random_48_char_secret_key_before_use",
        )


def test_production_rejects_debug() -> None:
    with pytest.raises(ValidationError):
        make(
            app_env="production",
            debug=True,
            database_url="postgresql+psycopg://user:pass@localhost/wrc",
            secret_key="prod-" + "c" * 50,
        )


def test_production_accepts_valid_configuration() -> None:
    settings = make(
        app_env="production",
        database_url="postgresql+psycopg://user:pass@db:5432/wrc",
        secret_key="prod-" + "d" * 50,
    )
    assert settings.is_production is True
    assert settings.is_sqlite is False


def test_sqlite_file_path_helpers() -> None:
    file_settings = make(database_url="sqlite+pysqlite:///./var/dev.db")
    assert file_settings.sqlite_file_path is not None
    assert str(file_settings.sqlite_file_path).endswith("dev.db")

    memory_settings = make(database_url="sqlite+pysqlite:///:memory:")
    assert memory_settings.sqlite_file_path is None
