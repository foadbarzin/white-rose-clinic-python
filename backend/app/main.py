"""FastAPI application factory (Phase 2 foundation).

No migrations, seeds or admin accounts are created here. Startup only wires
routers, logging, error handling and (optionally) the static UI directory.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import health
from app.api.router import router as api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import ErrorCode, WrcError, error_envelope, to_envelope
from app.core.logging import (
    REQUEST_ID_HEADER,
    configure_logging,
    get_request_id,
    set_request_id,
)
from app.database import models  # noqa: F401  (registers all table metadata)
from app.database.session import dispose_engines
from app.webui.renderer import FRONTEND_DIR, router as webui_router

logger = logging.getLogger("white_rose_clinic")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


def _register_exception_handlers(app: FastAPI) -> None:
    def _safe_errors(exc: Exception) -> list[dict]:
        errors_attr = getattr(exc, "errors", None)
        if errors_attr is None:
            return []
        try:
            return list(errors_attr(include_url=False))
        except TypeError:  # different signature across FastAPI versions
            return list(errors_attr())

    @app.exception_handler(WrcError)
    async def _wrc_error_handler(request: Request, exc: WrcError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(to_envelope(exc, get_request_id()), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"errors": _safe_errors(exc)}
        if request.url.path == "/api":
            # Legacy contract: domain/validation errors travel over HTTP 200.
            return JSONResponse(
                error_envelope(ErrorCode.VALIDATION, None, details, get_request_id())
            )
        return JSONResponse(
            error_envelope(ErrorCode.VALIDATION, None, details, get_request_id()), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        logger.exception("unhandled application error")
        return JSONResponse(
            error_envelope(ErrorCode.INTERNAL, None, None, get_request_id()), status_code=500
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application starting",
            extra={
                "app": settings.app_name,
                "version": settings.app_version,
                "environment": settings.app_env,
                "database": "sqlite" if settings.is_sqlite else "postgresql",
            },
        )
        try:
            yield
        finally:
            dispose_engines()
            logger.info("application stopped")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="White Rose Clinic engine — action gateway compatible with the existing UI.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def _request_context(request: Request, call_next):  # noqa: ANN001, ANN202
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = (incoming.strip()[:64] if incoming else "") or uuid.uuid4().hex
        set_request_id(request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    _register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router)
    app.include_router(webui_router)

    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    return app


app = create_app()
