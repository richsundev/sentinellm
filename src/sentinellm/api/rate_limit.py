"""Per-API-key (falling back to per-IP) rate limiting.

Built directly on the `limits` library (a moving-window counter backed by
in-memory storage) rather than a framework-integration wrapper: this
platform's request path is simple enough — one global per-key limit, no
per-route overrides — that owning the ~20 lines of enforcement logic is less
fragile than depending on a thin adapter package tracking every FastAPI/
Starlette internal routing change.
"""

from __future__ import annotations

from limits import RateLimitItemPerMinute, storage, strategies
from starlette.requests import Request

from sentinellm.core.config import get_settings

_storage = storage.MemoryStorage()
_strategy = strategies.MovingWindowRateLimiter(_storage)


def _limit_item() -> RateLimitItemPerMinute:
    return RateLimitItemPerMinute(get_settings().rate_limit_per_minute)


def rate_limit_key(request: Request) -> str:
    return request.headers.get("X-API-Key") or (
        request.client.host if request.client else "unknown"
    )


def check_rate_limit(key: str) -> bool:
    """Returns True if the request is allowed, False if the limit is exceeded."""
    return _strategy.hit(_limit_item(), key)
