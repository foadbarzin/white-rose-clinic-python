"""Security primitives: session tokens, password hashing, session policy.

Design decisions honoured here (see ``TECHNICAL_DECISIONS.md``):
  * TDR-002 — opaque server-side session tokens; only the SHA-256 hash is stored.
  * Password hashing — Argon2id when ``argon2-cffi`` is installed, otherwise a
    PBKDF2-HMAC-SHA256 fallback (encoded with algorithm + parameters so records
    can be upgraded lazily at the next successful login).
  * Passwords/tokens are never logged and never stored in plain text.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final

from app.core.config import Settings
from app.core.exceptions import ValidationFailure

MIN_PASSWORD_LENGTH: Final = 8
SESSION_TOKEN_BYTES: Final = 32
PBKDF2_ITERATIONS: Final = 390_000
PBKDF2_SALT_BYTES: Final = 16
ARGON2_MEMORY_KIB: Final = 65_536
ARGON2_TIME_COST: Final = 3
ARGON2_PARALLELISM: Final = 4

_COMMON_PASSWORDS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "password1",
        "12345678",
        "123456789",
        "qwerty123",
        "admin123",
        "white rose",
        "whiterose",
    }
)

try:  # pragma: no cover - depends on optional dependency
    from argon2 import PasswordHasher as _Argon2PasswordHasher
    from argon2.exceptions import (
        InvalidHashError,
        VerificationError,
        VerifyMismatchError,
    )

    _ARGON2_AVAILABLE = True
except Exception:  # pragma: no cover
    _Argon2PasswordHasher = None  # type: ignore[assignment]
    InvalidHashError = VerificationError = VerifyMismatchError = Exception  # type: ignore[misc,assignment]
    _ARGON2_AVAILABLE = False


def argon2_available() -> bool:
    return _ARGON2_AVAILABLE


# --------------------------------------------------------------------------- tokens
def generate_session_token() -> str:
    """Return a new opaque session token (256 bits of entropy, URL-safe)."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hash a session token for storage (SHA-256 hex)."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def token_matches(token: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented token against a stored hash."""
    return hmac.compare_digest(hash_token(token), (stored_hash or "").lower())


# ------------------------------------------------------------------------- passwords
@dataclass(frozen=True)
class PasswordHash:
    algo: str
    encoded: str
    params: dict[str, int] = field(default_factory=dict)


def _combine(password: str, pepper: str) -> str:
    return f"{password}:{pepper}"


def hash_password(
    password: str,
    *,
    pepper: str = "",
    memory_kib: int | None = None,
    time_cost: int | None = None,
    parallelism: int | None = None,
) -> PasswordHash:
    """Hash a password with Argon2id (preferred) or PBKDF2-SHA256 fallback."""
    material = _combine(password or "", pepper)
    if _ARGON2_AVAILABLE:
        mem = int(memory_kib or ARGON2_MEMORY_KIB)
        rounds = int(time_cost or ARGON2_TIME_COST)
        lanes = int(parallelism or ARGON2_PARALLELISM)
        hasher = _Argon2PasswordHasher(
            time_cost=rounds,
            memory_cost=mem,
            parallelism=lanes,
            hash_len=32,
            salt_len=16,
        )
        encoded = hasher.hash(material)
        return PasswordHash(
            algo="argon2id",
            encoded=encoded,
            params={"time_cost": rounds, "memory_cost": mem, "parallelism": lanes},
        )

    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", material.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=32)
    encoded = "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )
    return PasswordHash(algo="pbkdf2_sha256", encoded=encoded, params={"iterations": PBKDF2_ITERATIONS})


def verify_password(password: str, encoded: str, *, pepper: str = "") -> bool:
    """Verify a password against a stored encoded hash (constant-time)."""
    material = _combine(password or "", pepper)
    encoded = encoded or ""
    if encoded.startswith("$argon2"):
        if not _ARGON2_AVAILABLE:
            return False
        hasher = _Argon2PasswordHasher()
        try:
            return bool(hasher.verify(encoded, material))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    if encoded.startswith("pbkdf2_sha256$"):
        parts = encoded.split("$")
        if len(parts) != 4:
            return False
        _, iterations_raw, salt_b64, digest_b64 = parts
        try:
            iterations = int(iterations_raw)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(digest_b64)
        except (ValueError, TypeError):
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", material.encode("utf-8"), salt, iterations, dklen=len(expected)
        )
        return hmac.compare_digest(candidate, expected)
    return False


def password_needs_rehash(encoded: str) -> bool:
    """True when a stored hash uses weaker parameters than the current policy."""
    encoded = encoded or ""
    if _ARGON2_AVAILABLE:
        return not encoded.startswith("$argon2id$")
    if encoded.startswith("pbkdf2_sha256$"):
        parts = encoded.split("$")
        if len(parts) == 4:
            try:
                return int(parts[1]) < PBKDF2_ITERATIONS
            except ValueError:
                return True
    return True


def validate_password_strength(password: str, *, username: str | None = None) -> None:
    """Raise ``ValidationFailure`` when a password is too weak."""
    value = password or ""
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValidationFailure(message=f"رمز عبور باید حداقل {MIN_PASSWORD_LENGTH} نویسه باشد.")
    if value.lower() in _COMMON_PASSWORDS:
        raise ValidationFailure(message="رمز عبور انتخابی بسیار ساده است.")
    if username and value.lower() == (username or "").lower():
        raise ValidationFailure(message="رمز عبور نباید با نام کاربری یکسان باشد.")


# ------------------------------------------------------------------- session policy
@dataclass(frozen=True)
class SessionPolicy:
    absolute_ttl_seconds: int = 12 * 60 * 60
    idle_timeout_seconds: int = 30 * 60
    max_concurrent: int = 3

    @classmethod
    def from_settings(cls, settings: Settings) -> "SessionPolicy":
        return cls(
            absolute_ttl_seconds=settings.session_ttl,
            idle_timeout_seconds=settings.session_idle_seconds,
            max_concurrent=settings.session_max_concurrent,
        )

    def expires_at(self, issued_at: datetime) -> datetime:
        return issued_at + timedelta(seconds=self.absolute_ttl_seconds)

    def idle_expires_at(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self.idle_timeout_seconds)


@dataclass(frozen=True)
class SessionMaterial:
    token: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    idle_expires_at: datetime


def new_session_material(policy: SessionPolicy) -> SessionMaterial:
    """Generate a token plus its storage material (hash + timestamps)."""
    token = generate_session_token()
    now = datetime.now(timezone.utc)
    return SessionMaterial(
        token=token,
        token_hash=hash_token(token),
        issued_at=now,
        expires_at=policy.expires_at(now),
        idle_expires_at=policy.idle_expires_at(now),
    )


def mask_secret(value: str, *, keep: int = 2) -> str:
    """Mask a secret for logs/debug output."""
    value = value or ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}***{value[-keep:]}"

