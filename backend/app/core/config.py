"""Application configuration (Pydantic Settings).

All values come from environment variables (and an optional local ``.env``).
No secret is ever hard-coded: the default ``SECRET_KEY`` is an explicit
placeholder that is rejected in ``production``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]

_PLACEHOLDER_MARKERS = (
    "change_me",
    "change-me",
    "changeme",
    "placeholder",
    "example",
    "dev-secret",
    "secret-key-here",
)

_ALLOWED_URL_SCHEMES = (
    "sqlite",
    "sqlite+pysqlite",
    "postgresql",
    "postgresql+psycopg",
)

_WHITESPACE = re.compile(r"\s+")


class Settings(BaseSettings):
    """Central settings object — a single source of truth for runtime config."""

    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # --- application ---------------------------------------------------------
    app_name: str = "White Rose Clinic"
    app_version: str = "0.6.0"
    app_env: AppEnv = "development"
    debug: bool = False

    # --- network -------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    # --- database ------------------------------------------------------------
    # Development default: local SQLite file (created under ./var, gitignored).
    # Production target: postgresql+psycopg://user:pass@host:5432/db
    database_url: str = "sqlite+pysqlite:///./var/wrc-dev.db"

    # --- security ------------------------------------------------------------
    secret_key: str = Field(
        default="CHANGE_ME_generate_a_random_48_char_secret_key_before_use",
        description="Server-side secret (>= 32 chars). Never commit a real value.",
    )
    # manager decision (phase 3): 12h absolute lifetime, 30m idle timeout
    session_ttl: int = Field(default=12 * 60 * 60, ge=300, le=7 * 24 * 60 * 60)
    session_idle_seconds: int = Field(default=30 * 60, ge=60, le=24 * 60 * 60)
    session_max_concurrent: int = Field(default=3, ge=1, le=20)
    login_max_attempts: int = Field(default=5, ge=3, le=20)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)
    login_rate_limit_per_minute: int = Field(default=10, ge=3, le=200)
    # Argon2id parameters (tests use lower values for speed; production defaults stay strong)
    argon2_memory_kib: int = Field(default=65_536, ge=8_192, le=1_048_576)
    argon2_time_cost: int = Field(default=3, ge=1, le=20)
    argon2_parallelism: int = Field(default=4, ge=1, le=16)
    # explicit CORS policy: empty list = same-origin only (recommended)
    cors_allow_origins: list[str] = Field(default_factory=list)

    # --- bootstrap (CLI only; never exposed through the public API) ----------
    bootstrap_key: str | None = Field(
        default=None,
        description="Optional extra guard for the CLI bootstrap (>= 16 chars).",
    )

    # --- locale --------------------------------------------------------------
    timezone: str = "Asia/Tehran"

    # === validators ==========================================================
    @field_validator("app_name", "app_version")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = _WHITESPACE.sub(" ", value or "").strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("api_host")
    @classmethod
    def _host_non_empty(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("API_HOST must not be empty")
        return value

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        url = (value or "").strip()
        if not url:
            raise ValueError("DATABASE_URL must not be empty")
        # Bare postgres URLs must use the sync psycopg (v3) driver.
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        scheme = url.split("://", 1)[0].lower()
        if scheme not in _ALLOWED_URL_SCHEMES:
            raise ValueError(
                "DATABASE_URL scheme must be one of: " + ", ".join(_ALLOWED_URL_SCHEMES)
            )
        return url

    @field_validator("secret_key")
    @classmethod
    def _secret_strength(cls, value: str) -> str:
        secret = value or ""
        if len(secret) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return secret

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:  # pragma: no cover
            raise ValueError(f"unknown timezone: {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _production_hardening(self) -> "Settings":
        if self.session_idle_seconds >= self.session_ttl:
            raise ValueError("SESSION_IDLE_SECONDS must be smaller than SESSION_TTL")
        for origin in self.cors_allow_origins:
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"invalid CORS origin: {origin!r}")
        if self.app_env == "production":
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            lowered = self.secret_key.lower()
            if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
                raise ValueError("SECRET_KEY still contains a placeholder value")
            if self.is_sqlite:
                raise ValueError("production must use PostgreSQL, not SQLite")
        return self

    # === helpers =============================================================
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgresql(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def sqlite_file_path(self) -> Path | None:
        """Return the SQLite database file path (None for in-memory DBs)."""
        if not self.is_sqlite:
            return None
        _, _, tail = self.database_url.partition("://")
        path_part = tail.split("?", 1)[0]
        # Windows drive paths appear as "/C:/dir/db.sqlite" after the scheme.
        if path_part.startswith("/") and len(path_part) > 2 and path_part[2] == ":":
            path_part = path_part[1:]
        elif path_part.startswith("//"):
            path_part = path_part[1:]
        if path_part in ("", ":memory:", "/:memory:"):
            return None
        return Path(path_part)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor (clear with ``get_settings.cache_clear()``)."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings (used by tests and CLI tooling)."""
    get_settings.cache_clear()

