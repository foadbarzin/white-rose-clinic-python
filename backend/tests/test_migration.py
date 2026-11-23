"""Alembic migration tests: upgrade, downgrade and repeatability."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.database.base import Base

BACKEND = Path(__file__).resolve().parents[1]


def _config(db_path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{db_path.as_posix()}")
    return cfg


def _tables(db_path: Path) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {row[0] for row in rows}
    finally:
        connection.close()


def test_upgrade_head_creates_all_tables(db_path: Path) -> None:
    command.upgrade(_config(db_path), "head")
    tables = _tables(db_path)
    assert "alembic_version" in tables
    assert set(Base.metadata.tables).issubset(tables)
    assert len(Base.metadata.tables) == 31


def test_alembic_version_is_recorded(db_path: Path) -> None:
    command.upgrade(_config(db_path), "head")
    connection = sqlite3.connect(db_path)
    try:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()
    assert version is not None
    assert len(version[0]) >= 8


def test_migration_is_repeatable(db_path: Path) -> None:
    cfg = _config(db_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    remaining = _tables(db_path)
    assert remaining == {"alembic_version"} or remaining == set()
    command.upgrade(cfg, "head")
    assert set(Base.metadata.tables).issubset(_tables(db_path))


def test_no_seed_during_migration(db_path: Path) -> None:
    command.upgrade(_config(db_path), "head")
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM patient_credit_transactions").fetchone()[0]
            == 0
        )
    finally:
        connection.close()
