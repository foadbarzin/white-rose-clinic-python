"""Windows DPAPI tests (skipped on other platforms)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core import dpapi

pytestmark = pytest.mark.skipif(not dpapi.is_supported(), reason="DPAPI requires Windows")


def test_protect_unprotect_roundtrip() -> None:
    secret = os.urandom(32)
    blob = dpapi.protect(secret)
    assert blob != secret
    assert len(blob) > len(secret)
    assert dpapi.unprotect(blob) == secret


def test_blob_is_bound_to_entropy() -> None:
    secret = os.urandom(32)
    blob = dpapi.protect(secret, entropy=b"WRC-DB-KEY-v1")
    assert dpapi.unprotect(blob, entropy=b"WRC-DB-KEY-v1") == secret
    with pytest.raises(dpapi.DpapiError):
        dpapi.unprotect(blob, entropy=b"other-entropy")


def test_tampered_blob_is_rejected() -> None:
    blob = bytearray(dpapi.protect(os.urandom(32)))
    blob[-1] ^= 0xFF
    with pytest.raises(dpapi.DpapiError):
        dpapi.unprotect(bytes(blob))


def test_load_or_create_key_is_stable(tmp_path: Path) -> None:
    key_path = tmp_path / "db.key.dpapi"
    first = dpapi.load_or_create_key(key_path)
    assert len(first) == 32
    second = dpapi.load_or_create_key(key_path)
    assert first == second
    raw = key_path.read_bytes()
    assert first not in raw  # key is never stored in clear text
