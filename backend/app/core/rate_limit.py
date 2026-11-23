"""Best-effort in-memory rate limiter (sliding window).

Used for login brute-force protection. It complements (not replaces) the
database-backed account lockout and is intentionally process-local: in a
single-clinic deployment the API runs as one process behind the reverse proxy.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Final

_MAX_KEYS: Final = 5000


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Register a hit; return False when the limit is exceeded."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            if len(self._hits) > _MAX_KEYS:
                for stale in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
                    self._hits.pop(stale, None)
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return self.limit
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            return max(0, self.limit - len(bucket))

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def get_limiter(limit: int | None = None) -> RateLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None or (limit is not None and _limiter.limit != limit):
            _limiter = RateLimiter(limit or 10)
        return _limiter


def reset_limiter() -> None:
    global _limiter
    with _limiter_lock:
        if _limiter is not None:
            _limiter.reset()
        _limiter = None
