"""Database session, migration and integrity tests (SQLite, throwaway files)."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from app.database import models  # noqa: F401
from app.database.base import Base, uuid7
from app.database.models.system import Meta
from app.database.session import check_connection, session_scope

EXPECTED_TABLES = {
    "audit_log",
    "backup_jobs",
    "change_feed",
    "commission_rules",
    "commissions",
    "devices",
    "doctors",
    "expenses",
    "invoice_amendment_items",
    "invoice_amendments",
    "invoice_discount_events",
    "invoice_items",
    "invoice_number_history",
    "invoices",
    "meta",
    "operators",
    "other_income",
    "patient_credit_accounts",
    "patient_credit_transactions",
    "patients",
    "payments",
    "sequences",
    "services",
    "settings",
    "sync_conflicts",
    "sync_operations",
    "user_sessions",
    "users",
}


def test_metadata_contains_all_domain_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert len(Base.metadata.tables) == 28


def test_uuid7_is_time_ordered() -> None:
    first = uuid7()
    second = uuid7()
    assert isinstance(first, uuid.UUID)
    assert first.version == 7
    assert second.int > first.int


def test_engine_connection(migrated_db, settings) -> None:
    ok, error = check_connection(settings)
    assert ok is True
    assert error is None


def test_transactional_session_roundtrip(migrated_db, settings) -> None:
    with session_scope(settings) as session:
        session.add(Meta(key="schema_version", value="1"))
    with session_scope(settings) as session:
        record = session.get(Meta, "schema_version")
        assert record is not None
        assert record.value == "1"


def test_rollback_on_error(migrated_db, settings) -> None:
    with pytest.raises(RuntimeError):
        with session_scope(settings) as session:
            session.add(Meta(key="rollback_test", value="x"))
            raise RuntimeError("boom")
    with session_scope(settings) as session:
        assert session.get(Meta, "rollback_test") is None


def test_database_is_empty_after_migration(migrated_db) -> None:
    """No seed data: business tables must be empty right after ``upgrade head``."""
    connection = sqlite3.connect(migrated_db)
    try:
        for table in ("users", "patients", "services", "invoices", "settings", "audit_log"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"table {table} must be empty"
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version and version[0]
    finally:
        connection.close()


def test_money_and_monetary_columns_use_decimal() -> None:
    from app.database.models.invoicing import Invoice

    column = Invoice.__table__.c.total_toman
    assert column.type.precision == 18
    assert column.type.scale == 1
    assert column.type.asdecimal is True


def test_foreign_keys_are_enabled(migrated_db, settings) -> None:
    from app.database.session import get_engine
    from sqlalchemy import text

    with get_engine(settings).connect() as connection:
        pragma = connection.execute(text("PRAGMA foreign_keys")).scalar()
    assert pragma == 1
