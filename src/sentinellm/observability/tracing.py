"""OpenTelemetry tracer configuration.

Exports to an OTLP collector when `SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT` is
set (e.g. pointed at the Jaeger/Tempo collector in docker-compose); otherwise
falls back to an in-process no-op-safe console-less setup so local dev and
tests never need a collector running.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)


def configure_tracing(service_name: str, otlp_endpoint: str | None = None) -> None:
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def get_tracer(name: str):
    return trace.get_tracer(name)
