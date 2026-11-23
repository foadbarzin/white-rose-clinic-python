"""Health, readiness and metadata endpoints (no authentication)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import check_connection, get_engine
from app.schemas.api import DesktopInfoResponse, HealthResponse, ReadyResponse, VersionResponse

router = APIRouter(tags=["system"])


def _schema_info() -> tuple[str | None, str | None]:
    """Return ``(schema_version, detail)`` when the database is reachable.

    ``meta.schema_version`` is authoritative; when it is not set yet we fall
    back to the Alembic head recorded in ``alembic_version`` so readiness can
    tell "migrated" from "not migrated" without inserting any seed row.
    """
    try:
        with get_engine().connect() as connection:
            row = connection.execute(
                text("SELECT value FROM meta WHERE key = 'schema_version'")
            ).first()
            if row and row[0] is not None:
                return str(row[0]), "migrated"
            try:
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).first()
            except Exception:
                revision = None
            if revision and revision[0]:
                return str(revision[0]), "migrated"
            return None, "not_migrated"
    except Exception:  # pragma: no cover - database may not be reachable yet
        return None, None


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
def healthz() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        application=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )


@router.get("/readyz", response_model=ReadyResponse, summary="Readiness probe")
def readyz(response: Response) -> ReadyResponse:
    ok, error = check_connection()
    if not ok:
        response.status_code = 503
        return ReadyResponse(status="degraded", database="unavailable", detail=error)
    schema_version, detail = _schema_info()
    return ReadyResponse(status="ok", database="ok", schema_version=schema_version, detail=detail)


@router.get("/api/meta/version", response_model=VersionResponse, summary="App metadata")
def version() -> VersionResponse:
    settings = get_settings()
    return VersionResponse(
        application=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        api_contract="action-v1",
        timezone=settings.timezone,
    )


@router.get("/desktop/info", response_model=DesktopInfoResponse, summary="Desktop shell info")
def desktop_info() -> DesktopInfoResponse:
    settings = get_settings()
    return DesktopInfoResponse(desktop=False, version=settings.app_version, mode="server")
