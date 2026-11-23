"""Request/actor context shared by services (no secrets, audit-ready)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ActorContext:
    """Who is performing the operation, from where, under which correlation id."""

    user_id: uuid.UUID | None
    username: str
    permissions: frozenset[str]
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    session_id: uuid.UUID | None = None
