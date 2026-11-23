"""SQLCipher compatibility test (Windows x64 / Python 3.13).

The test is skipped when the optional driver is missing so the suite stays
green on machines without the desktop extra. It proves:
  * an encrypted database can be created, written and reopened with the key;
  * a wrong key cannot read the data;
  * plain SQLite cannot read the file;
  * the SQLAlchemy helper in ``app.database.session`` works end-to-end.
"""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

import pytest

sqlcipher3 = pytest.importorskip(
    "sqlcipher3", reason="install the 'desktop' extra (sqlcipher3-wheels)"
)

KEY = secrets.token_bytes(32)
WRONG_KEY = secrets.token_bytes(32)


def _connect(path: Path, key: bytes):
    connection = sqlcipher3.dbapi2.connect(str(path))
    connection.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
    return connection


def test_sqlcipher_encrypts_and_reopens(tmp_path: Path) -> None:
    db = tmp_path / "encrypted.db"
    connection = _connect(db, KEY)
    try:
        connection.execute("CREATE TABLE secret (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO secret (value) VALUES ('white-rose')")
        connection.commit()
    finally:
        connection.close()

    reopened = _connect(db, KEY)
    try:
        assert reopened.execute("SELECT value FROM secret").fetchone()[0] == "white-rose"
    finally:
        reopened.close()


def test_sqlcipher_rejects_wrong_key(tmp_path: Path) -> None:
    db = tmp_path / "wrong-key.db"
    connection = _connect(db, KEY)
    try:
        connection.execute("CREATE TABLE t (x INTEGER)")
        connection.execute("INSERT INTO t VALUES (1)")
        connection.commit()
    finally:
        connection.close()

    wrong = _connect(db, WRONG_KEY)
    try:
        with pytest.raises(Exception):
            wrong.execute("SELECT * FROM t").fetchall()
    finally:
        wrong.close()


def test_plain_sqlite_cannot_read_encrypted_file(tmp_path: Path) -> None:
    db = tmp_path / "plain-read.db"
    connection = _connect(db, KEY)
    try:
        connection.execute("CREATE TABLE t (x INTEGER)")
        connection.commit()
    finally:
        connection.close()

    plain = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            plain.execute("SELECT * FROM t").fetchall()
    finally:
        plain.close()


def test_sqlalchemy_sqlcipher_engine(tmp_path: Path) -> None:
    from sqlalchemy import text

    from app.database.session import build_sqlcipher_engine

    db = tmp_path / "engine.db"
    engine = build_sqlcipher_engine(db, KEY)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE demo (id INTEGER PRIMARY KEY, label TEXT)"))
            connection.execute(text("INSERT INTO demo (label) VALUES ('ok')"))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT label FROM demo")).scalar() == "ok"
    finally:
        engine.dispose()


def test_sqlcipher_rejects_short_key(tmp_path: Path) -> None:
    from app.database.session import build_sqlcipher_engine

    with pytest.raises(ValueError):
        build_sqlcipher_engine(tmp_path / "short.db", b"short")
