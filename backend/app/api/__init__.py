"""API package: health endpoints and the single action gateway."""

from app.api import health, router as action_router

__all__ = ["health", "action_router"]
