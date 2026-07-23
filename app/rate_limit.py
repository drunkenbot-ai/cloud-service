"""In-memory, per-IP rate limiting for the public validation endpoints.

Deliberate v1 simplification: this state lives in one process's memory, so
it resets on restart and does not coordinate across multiple instances. If
this service is ever horizontally scaled, replace this with a shared store
(e.g. Redis) -- until then, this is enough to blunt casual brute-forcing of
license keys / API keys without adding an external dependency.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings

_WINDOW_SECONDS = 60.0
_lock = threading.Lock()
_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)


def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency: reject requests once an IP exceeds its budget.

    Args:
        request: Incoming request, used to identify the client IP.

    Raises:
        HTTPException: 429 if the client has exceeded its per-minute budget.
    """

    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _lock:
        timestamps = _requests_by_ip[client_ip]
        while timestamps and now - timestamps[0] > _WINDOW_SECONDS:
            timestamps.popleft()
        if len(timestamps) >= settings.rate_limit_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down and try again shortly.",
            )
        timestamps.append(now)
