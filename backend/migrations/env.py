"""Alembic environment (sync engine, SQLite + PostgreSQL).

Database URL resolution order:
  1. ``-x db_url=...`` command line override (used by tests)
  2. ``sqlalchemy.url`` from alembic.ini (normally empty)
  3. application settings (``DATABASE_URL``)
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

# Make ``app`` importable when alembic runs from the repository root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database import models  # noqa: E402,F401  (populate metadata)

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    xargs = context.get_x_argument(as_dictionary=True)
    override = (xargs or {}).get("db_url")
    if override:
        return override
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return get_settings().database_url


def _ensure_sqlite_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return
    database = parsed.database or ""
    if database in ("", ":memory:"):
        return
    path = Path(database)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    _ensure_sqlite_dir(url)
    connectable = create_engine(url, poolclass=pool.NullPool, future=True)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
