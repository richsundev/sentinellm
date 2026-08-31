"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sentinellm.api.middleware import CorrelationAndMetricsMiddleware, RateLimitMiddleware
from sentinellm.api.routers import (
    alerts,
    applications,
    datasets,
    evaluations,
    experiments,
    generate,
    metrics,
    models,
    prompts,
    routing,
    traces,
    webhook,
)
from sentinellm.core.config import get_settings
from sentinellm.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("sentinellm_api_starting", env=settings.env, llm_provider=settings.llm_provider)
    yield
    logger.info("sentinellm_api_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SentinelLLM API",
        description="Autonomous LLM Reliability, Evaluation & Optimization Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_exception_handler(RequestValidationError, _validation_error_handler)

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CorrelationAndMetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.env in {"local", "test"} else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        traces.router,
        generate.router,
        evaluations.router,
        datasets.router,
        experiments.router,
        prompts.router,
        models.router,
        routing.router,
        alerts.alerts_router,
        alerts.regressions_router,
        metrics.router,
        applications.router,
        webhook.router,
    ):
        app.include_router(router)

    @app.get("/health", tags=["internal"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", tags=["internal"])
    async def metrics_endpoint() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


async def _validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": exc.errors()}
    )


app = create_app()
