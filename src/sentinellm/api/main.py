"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import get_db
from sentinellm.api.middleware import (
    CorrelationAndMetricsMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)
from sentinellm.api.routers import (
    alerts,
    applications,
    datasets,
    evaluations,
    experiments,
    generate,
    metrics,
    models,
    prompt_rollouts,
    prompts,
    rollouts,
    routing,
    traces,
    webhook,
)
from sentinellm.core.config import get_settings
from sentinellm.core.logging import configure_logging, get_logger
from sentinellm.observability.tracing import setup_tracing
from sentinellm.routing.router import NoHealthyCandidateError
from sentinellm.services.budget import BudgetExceededError
from sentinellm.services.prompts import PromptNotFoundError, PromptRenderError

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
    app.add_exception_handler(NoHealthyCandidateError, _no_route_handler)
    app.add_exception_handler(IntegrityError, _conflict_handler)
    app.add_exception_handler(BudgetExceededError, _budget_exceeded_handler)
    app.add_exception_handler(PromptNotFoundError, _prompt_not_found_handler)
    app.add_exception_handler(PromptRenderError, _prompt_render_handler)

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
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
        rollouts.router,
        prompt_rollouts.router,
    ):
        app.include_router(router)

    # The local webhook receiver is unauthenticated and logs whatever it is
    # sent, so it only exists where there is no real webhook to point at.
    if settings.env in {"local", "test"}:
        app.include_router(webhook.router)

    # Instrumentation adds middleware, so it has to happen here, not in `lifespan`.
    setup_tracing("sentinellm-api", settings.otel_exporter_otlp_endpoint, app)

    @app.get("/health", tags=["internal"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["internal"])
    async def ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
        """Readiness: can this instance serve requests? `/health` (liveness)
        deliberately doesn't look at the database — restarting the API doesn't
        fix a database outage — but a load balancer should stop routing to an
        instance that can't reach it. Redis is not required: enqueueing an
        evaluation is best-effort."""
        try:
            await db.execute(text("SELECT 1"))
        except Exception:
            logger.warning("readiness_check_failed", exc_info=True)
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(content={"status": "ready"})

    @app.get("/metrics", tags=["internal"])
    async def metrics_endpoint() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


async def _validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # exc.errors() can carry a raw exception instance in ctx["error"] for a
    # ValueError raised from a @model_validator/@field_validator (a normal
    # Pydantic v2 pattern for cross-field checks) — jsonable_encoder is what
    # turns that into a string instead of crashing json.dumps.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        # The echoed `input` is dropped: it can itself be unserialisable (the
        # NaN/Infinity that was just rejected) and needn't be reflected back.
        content={
            "detail": jsonable_encoder(
                [{k: v for k, v in err.items() if k != "input"} for err in exc.errors()]
            )
        },
    )


async def _no_route_handler(_request: Request, exc: Exception) -> JSONResponse:
    """A request the router can't place (every model down / below the quality
    floor) is a capacity condition, not a server bug."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


async def _budget_exceeded_handler(_request: Request, exc: Exception) -> JSONResponse:
    """The application chose `budget_action=block` and has spent its day's
    budget: nothing wrong with the request, so not a 4xx about its content."""
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={"detail": str(exc)},
        headers={"X-Budget-Action": "block"},
    )


async def _prompt_not_found_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _prompt_render_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)}
    )


async def _conflict_handler(_request: Request, _exc: Exception) -> JSONResponse:
    """A unique/foreign-key violation that no endpoint checked for up front
    (duplicate name, a concurrent create) — the caller's conflict, not a 500."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "the request conflicts with an existing record"},
    )


app = create_app()
