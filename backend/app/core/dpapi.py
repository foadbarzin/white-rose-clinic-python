"""Windows DPAPI key protection (no external dependency).

Used to protect the SQLCipher database key (TDR-008). The key itself is only
ever held in memory; the encrypted blob lives in the per-user profile and is
bound to the Windows user account (``CRYPTPROTECT_LOCAL_MACHINE`` is *not*
used by default).

This module is a no-op on non-Windows platforms: callers must check
``is_supported()`` and use the documented fallback (see SECURITY_DESIGN §۱۲).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import secrets
from pathlib import Path

CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04
DEFAULT_ENTROPY = b"WRC-DB-KEY-v1"
DEFAULT_KEY_BYTES = 32


class DpapiError(RuntimeError):
    """Raised when DPAPI protection/unprotection fails."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def is_supported() -> bool:
    return os.name == "nt"


def _load_libraries():  # pragma: no cover - Windows only
    if not is_supported():
        raise DpapiError("DPAPI is only available on Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return crypt32, kernel32


if is_supported():  # pragma: no cover - exercised on Windows only
    _CRYPT32, _KERNEL32 = _load_libraries()

    _CRYPT32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _CRYPT32.CryptProtectData.restype = wintypes.BOOL

    _CRYPT32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _CRYPT32.CryptUnprotectData.restype = wintypes.BOOL

    _KERNEL32.LocalFree.argtypes = [ctypes.c_void_p]
    _KERNEL32.LocalFree.restype = ctypes.c_void_p


def _to_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _from_blob(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _free(blob: _DataBlob) -> None:  # pragma: no cover - Windows only
    if blob.pbData:
        _KERNEL32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect(data: bytes, *, entropy: bytes = DEFAULT_ENTROPY, machine_scope: bool = False) -> bytes:
    """Encrypt ``data`` with DPAPI bound to the current Windows user."""
    if not is_supported():  # pragma: no cover
        raise DpapiError("DPAPI is only available on Windows")
    data_blob, data_buffer = _to_blob(bytes(data))
    entropy_blob, entropy_buffer = _to_blob(bytes(entropy)) if entropy else (None, None)
    out_blob = _DataBlob()
    flags = CRYPTPROTECT_UI_FORBIDDEN | (CRYPTPROTECT_LOCAL_MACHINE if machine_scope else 0)
    ok = _CRYPT32.CryptProtectData(
        ctypes.byref(data_blob),
        "WhiteRoseClinic",
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    _ = data_buffer, entropy_buffer  # keep buffers alive
    if not ok:  # pragma: no cover
        raise DpapiError(f"CryptProtectData failed (error={ctypes.get_last_error()})")
    try:
        return _from_blob(out_blob)
    finally:
        _free(out_blob)


def unprotect(blob: bytes, *, entropy: bytes = DEFAULT_ENTROPY) -> bytes:
    """Decrypt a DPAPI blob produced by :func:`protect`."""
    if not is_supported():  # pragma: no cover
        raise DpapiError("DPAPI is only available on Windows")
    data_blob, data_buffer = _to_blob(bytes(blob))
    entropy_blob, entropy_buffer = _to_blob(bytes(entropy)) if entropy else (None, None)
    out_blob = _DataBlob()
    ok = _CRYPT32.CryptUnprotectData(
        ctypes.byref(data_blob),
        None,
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    _ = data_buffer, entropy_buffer
    if not ok:  # pragma: no cover
        raise DpapiError(f"CryptUnprotectData failed (error={ctypes.get_last_error()})")
    try:
        return _from_blob(out_blob)
    finally:
        _free(out_blob)


def default_key_path() -> Path:
    """Standard per-user location for the protected database key."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "WhiteRoseClinic" / "keys" / "db.key.dpapi"


def load_or_create_key(path: Path | None = None) -> bytes:
    """Load the protected DB key, creating a new random one when missing.

    The raw key is returned to the caller (in memory only) and is never written
    outside the DPAPI-protected blob.
    """
    key_path = Path(path) if path else default_key_path()
    if key_path.exists():
        return unprotect(key_path.read_bytes())
    key = secrets.token_bytes(DEFAULT_KEY_BYTES)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(protect(key))
    return key
