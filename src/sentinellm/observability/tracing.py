"""OpenTelemetry tracer configuration.

Tracing is opt-in: it is only switched on when
`SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT` is set (e.g. the Jaeger/Tempo collector
in docker-compose). Unset, no provider is installed, `get_tracer()` hands out
no-op tracers, and every `start_as_current_span` in the code costs nothing — so
local dev and tests never need a collector, and never print span dumps.
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from sentinellm.core.logging import get_logger

logger = get_logger(__name__)


def configure_tracing(service_name: str, otlp_endpoint: str | None = None) -> None:
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def setup_tracing(service_name: str, otlp_endpoint: str | None, app: FastAPI | None = None) -> bool:
    """Turns tracing on when an OTLP endpoint is configured. Returns whether it
    did. A misconfigured exporter must not stop the service from starting."""
    if not otlp_endpoint:
        return False
    try:
        configure_tracing(service_name, otlp_endpoint)
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
    except Exception:
        logger.exception("tracing_setup_failed", service=service_name, endpoint=otlp_endpoint)
        return False
    logger.info("tracing_enabled", service=service_name, endpoint=otlp_endpoint)
    return True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
