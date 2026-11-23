"""SQLAlchemy engine/session management (sync, TDR-001).

One logical schema, two engines:
  * server   → PostgreSQL (``postgresql+psycopg``)
  * desktop  → SQLite (plain for tests, SQLCipher in the packaged agent)

Every request gets a short transaction via :func:`session_scope`; domain
errors must roll back. Jobs that need long transactions must use their own
session and never share one with an HTTP request.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings

logger = logging.getLogger("white_rose_clinic.database")

_ENGINE_CACHE: dict[tuple[str, bool], Engine] = {}
_SESSION_FACTORIES: dict[tuple[str, bool], sessionmaker[Session]] = {}


def _ensure_sqlite_directory(settings: Settings) -> None:
    path = settings.sqlite_file_path
    if path is None:
        return
    parent = path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def _is_memory_url(url: str) -> bool:
    return ":memory:" in url


def _apply_sqlite_pragmas(engine: Engine, *, memory: bool) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            if not memory:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create (and configure) an engine for the given URL."""
    url = make_url(database_url)
    kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": True, "future": True}

    if url.get_backend_name() == "sqlite":
        memory = _is_memory_url(database_url)
        kwargs["connect_args"] = {"check_same_thread": False}
        if memory:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(database_url, **kwargs)
        _apply_sqlite_pragmas(engine, memory=memory)
        return engine

    # PostgreSQL: conservative pool sized for a single clinic (3..15 users).
    kwargs.update({"pool_size": 5, "max_overflow": 5, "pool_recycle": 1800})
    return create_engine(database_url, **kwargs)


def get_engine(settings: Settings | None = None) -> Engine:
    """Return the cached engine for the current settings."""
    settings = settings or get_settings()
    key = (settings.database_url, settings.debug)
    engine = _ENGINE_CACHE.get(key)
    if engine is None:
        _ensure_sqlite_directory(settings)
        engine = build_engine(settings.database_url, echo=settings.debug)
        _ENGINE_CACHE[key] = engine
        logger.info("database engine created", extra={"dialect": engine.dialect.name})
    return engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    settings = settings or get_settings()
    key = (settings.database_url, settings.debug)
    factory = _SESSION_FACTORIES.get(key)
    if factory is None:
        factory = sessionmaker(
            bind=get_engine(settings),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        _SESSION_FACTORIES[key] = factory
    return factory


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on any exception."""
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a transactional session."""
    with session_scope() as session:
        yield session


def check_connection(settings: Settings | None = None) -> tuple[bool, str | None]:
    """Cheap readiness probe (``SELECT 1``). Returns (ok, error message)."""
    try:
        with get_engine(settings).connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # pragma: no cover - depends on runtime state
        logger.warning("database readiness check failed: %s", type(exc).__name__)
        return False, type(exc).__name__


def dispose_engines() -> None:
    """Dispose all cached engines (tests / shutdown)."""
    for engine in _ENGINE_CACHE.values():
        engine.dispose()
    _ENGINE_CACHE.clear()
    _SESSION_FACTORIES.clear()


def build_sqlcipher_engine(db_path: str | Path, key: bytes, *, echo: bool = False) -> Engine:
    """Build a SQLCipher-backed SQLite engine (desktop agent, TDR-008).

    Requires the optional ``sqlcipher3-wheels`` package. The raw key must come
    from Windows DPAPI (:mod:`app.core.dpapi`) and is never persisted by us.
    """
    try:  # pragma: no cover - optional dependency
        import sqlcipher3  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "SQLCipher driver is not installed; install the 'desktop' extra "
            "(sqlcipher3-wheels) or use the documented fallback."
        ) from exc

    if len(key) != 32:
        raise ValueError("SQLCipher key must be 32 bytes")

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key_hex = key.hex()

    def _creator():  # pragma: no cover - optional dependency
        return sqlcipher3.dbapi2.connect(str(path), check_same_thread=False)

    engine = create_engine("sqlite://", creator=_creator, echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _apply_key(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA key = \"x'{key_hex}'\"")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine

