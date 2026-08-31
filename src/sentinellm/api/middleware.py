"""Correlation-ID, Prometheus instrumentation, and rate-limiting middleware."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sentinellm.api.rate_limit import check_rate_limit, rate_limit_key
from sentinellm.core.logging import request_id_var
from sentinellm.observability.metrics import REQUEST_LATENCY_SECONDS, REQUESTS_TOTAL

_EXEMPT_PATHS = {"/health", "/metrics"}


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
        route_path = request.url.path
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        path_template = route.path if route is not None else route_path
        REQUESTS_TOTAL.labels(
            method=request.method, path=path_template, status=response.status_code
        ).inc()
        REQUEST_LATENCY_SECONDS.labels(method=request.method, path=path_template).observe(elapsed)

        response.headers["X-Request-ID"] = request_id
        return response
