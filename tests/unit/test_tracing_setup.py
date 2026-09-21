"""Tracing was configured nowhere, so `SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT`
(and the docs describing it) did nothing."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from sentinellm.observability import tracing


def test_tracing_is_off_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(tracing, "configure_tracing", lambda *a: calls.append(a))

    assert tracing.setup_tracing("svc", None) is False
    assert tracing.setup_tracing("svc", "") is False
    assert calls == []


def test_tracing_is_configured_and_the_app_instrumented_when_an_endpoint_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    configured: list[tuple] = []
    instrumented: list[FastAPI] = []
    monkeypatch.setattr(tracing, "configure_tracing", lambda *a: configured.append(a))
    monkeypatch.setattr(FastAPIInstrumentor, "instrument_app", lambda app: instrumented.append(app))
    app = FastAPI()

    assert tracing.setup_tracing("svc", "http://collector:4317", app) is True
    assert configured == [("svc", "http://collector:4317")]
    assert instrumented == [app]


def test_a_broken_exporter_does_not_stop_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object) -> None:
        raise RuntimeError("bad endpoint")

    monkeypatch.setattr(tracing, "configure_tracing", boom)

    assert tracing.setup_tracing("svc", "http://collector:4317") is False


def test_create_app_enables_tracing_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from sentinellm.api import main
    from sentinellm.core.config import get_settings

    seen: list[tuple] = []
    monkeypatch.setattr(main, "setup_tracing", lambda *a: seen.append(a))
    monkeypatch.setenv("SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    get_settings.cache_clear()
    try:
        app = main.create_app()
    finally:
        monkeypatch.delenv("SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT")
        get_settings.cache_clear()

    assert seen == [("sentinellm-api", "http://collector:4317", app)]
