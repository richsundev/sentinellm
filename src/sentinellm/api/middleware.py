"""Correlation-ID, Prometheus instrumentation, and rate-limiting middleware."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sentinellm.api.rate_limit import check_rate_limit, rate_limit_key
from sentinellm.core.config import get_settings
from sentinellm.core.logging import request_id_var
from sentinellm.observability.metrics import REQUEST_LATENCY_SECONDS, REQUESTS_TOTAL

_EXEMPT_PATHS = {"/health", "/metrics"}


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Refuses a body whose declared size is over `max_request_bytes` before any
    of it is read or parsed — otherwise a single request can make the API hold
    an arbitrarily large JSON document in memory. (A chunked upload declares no
    length; the dataset import endpoint bounds its own read.)"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        raw_target = (
            (request.scope.get("raw_path") or b"").decode("latin-1")
            + "?"
            + (request.scope.get("query_string") or b"").decode("latin-1")
        )
        if "%00" in raw_target:
            # Path/query values reach the database as parameters; Postgres
            # rejects NUL there just as it does in a body.
            return JSONResponse(status_code=400, content={"detail": "invalid character in URL"})
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > get_settings().max_request_bytes:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path not in _EXEMPT_PATHS and not check_rate_limit(rate_limit_key(request)):
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        return await call_next(request)


class CorrelationAndMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", f"req_{uuid.uuid4().hex}")
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # An unhandled exception is the 5xx that matters most, and it
            # propagates straight through here (Starlette turns it into the
            # 500 response further out). Count it before re-raising or the
            # error-rate alert never sees it.
            self._record(request, 500, time.perf_counter() - start)
            raise
        finally:
            request_id_var.reset(token)

        self._record(request, response.status_code, time.perf_counter() - start)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _record(request: Request, status_code: int, elapsed: float) -> None:
        route = request.scope.get("route")
        # Requests that never matched a route (404s, and 429s rejected before
        # routing) have nothing but their raw URL to label with — one new time
        # series per distinct path. A single fixed label keeps cardinality
        # bounded.
        path_template = route.path if route is not None else "unmatched"
        REQUESTS_TOTAL.labels(method=request.method, path=path_template, status=status_code).inc()
        REQUEST_LATENCY_SECONDS.labels(method=request.method, path=path_template).observe(elapsed)
