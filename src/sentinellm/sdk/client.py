"""SentinelLLM client SDK.

The SDK is intentionally the *only* thing an integrating application needs
to depend on — it never imports from `sentinellm.db`, `sentinellm.llm`, etc.
It talks to the platform purely over its public HTTP API, exactly like any
external caller would, which is what lets its request-shape contract be
verified with an HTTP-level mock rather than a running server (see
tests/unit/test_sdk_client.py).

Usage:

    client = SentinelClient(base_url="http://localhost:8000", api_key="sk_...")
    with SpanRecorder() as spans:
        with spans.span("retrieval"):
            docs = my_retriever.search(query)
        with spans.span("llm_generation"):
            answer = my_llm.complete(query)
    client.submit_trace(
        application_id="support-bot", model="openai:gpt-4o-mini", provider="openai",
        prompt=query, response=answer, input_tokens=120, output_tokens=48,
        latency_ms=812.0, spans=spans.spans,
    )
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(slots=True)
class RecordedSpan:
    name: str
    start_ms: float
    duration_ms: float
    status: str = "ok"
    metadata: dict[str, Any] = field(default_factory=dict)


class SpanRecorder:
    """Tiny helper for timing nested stages of a request without pulling in
    OpenTelemetry SDK machinery client-side."""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self.spans: list[RecordedSpan] = []

    def __enter__(self) -> SpanRecorder:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    @contextmanager
    def span(self, name: str, **metadata: Any) -> Iterator[None]:
        start_ms = (time.perf_counter() - self._start) * 1000
        t0 = time.perf_counter()
        status = "ok"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            self.spans.append(
                RecordedSpan(
                    name=name,
                    start_ms=round(start_ms, 2),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                    status=status,
                    metadata=metadata,
                )
            )


class SentinelClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._timeout = timeout

    def submit_trace(
        self,
        *,
        application_id: str,
        model: str,
        provider: str,
        prompt: str,
        response: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        environment: str = "production",
        system_prompt: str | None = None,
        retrieved_documents: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        spans: list[RecordedSpan] | None = None,
        status: str = "ok",
        error: str | None = None,
        trace_id: str | None = None,
        prompt_id: str | None = None,
        prompt_version: int | None = None,
        evaluate: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "application_id": application_id,
            "environment": environment,
            "model": model,
            "provider": provider,
            "prompt": prompt,
            "system_prompt": system_prompt,
            "response": response,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "retrieved_documents": retrieved_documents or [],
            "metadata": metadata or {},
            "status": status,
            "error": error,
            "trace_id": trace_id,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "evaluate": evaluate,
            "spans": [
                {
                    "name": s.name,
                    "start_ms": s.start_ms,
                    "duration_ms": s.duration_ms,
                    "status": s.status,
                    "metadata": s.metadata,
                }
                for s in (spans or [])
            ],
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._base_url}/api/v1/traces", json=payload, headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()

    def generate(self, **kwargs: Any) -> dict[str, Any]:
        """Delegates generation itself to SentinelLLM (routing + fallback +
        caching applied server-side) rather than reporting a trace after the
        fact. See `sentinellm.api.schemas.generate.GenerateRequest` for the
        full set of accepted fields."""
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._base_url}/api/v1/generate", json=kwargs, headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()
