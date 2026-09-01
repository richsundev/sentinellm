"""SDK tests, mocked at the HTTP boundary with respx.

The SDK's only contract with the rest of the platform is the shape of the
HTTP requests it sends — it never imports server-side code — so mocking at
that boundary (rather than needing a running server) verifies exactly what
matters: the right method/URL/headers/payload for the traces and generate
endpoints, and that HTTP errors surface as exceptions rather than being
swallowed.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from sentinellm.sdk.client import RecordedSpan, SentinelClient, SpanRecorder

BASE_URL = "http://testserver"


@pytest.fixture
def client() -> SentinelClient:
    return SentinelClient(base_url=BASE_URL, api_key="sk_sentinel_test123")


@respx.mock
def test_submit_trace_sends_expected_request_and_returns_response(client: SentinelClient) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/traces").mock(
        return_value=httpx.Response(201, json={"id": "abc", "trace_id": "trc_1"})
    )

    result = client.submit_trace(
        application_id="support-bot",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="What is the refund policy?",
        response="Refunds within 30 days.",
        input_tokens=42,
        output_tokens=18,
        latency_ms=610.0,
    )

    assert route.called
    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "sk_sentinel_test123"
    assert request.headers["Content-Type"] == "application/json"

    import json

    body = json.loads(request.content)
    assert body["application_id"] == "support-bot"
    assert body["model"] == "mock:sentinel-flash"
    assert body["input_tokens"] == 42
    assert body["spans"] == []
    assert result == {"id": "abc", "trace_id": "trc_1"}


@respx.mock
def test_submit_trace_serializes_spans(client: SentinelClient) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/traces").mock(return_value=httpx.Response(201, json={}))
    spans = [
        RecordedSpan(
            name="retrieval",
            start_ms=0.0,
            duration_ms=12.5,
            status="ok",
            metadata={"documents_found": 3},
        ),
        RecordedSpan(name="llm_generation", start_ms=12.5, duration_ms=800.0, status="error"),
    ]

    client.submit_trace(
        application_id="support-bot",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1.0,
        spans=spans,
    )

    import json

    body = json.loads(route.calls.last.request.content)
    assert body["spans"] == [
        {
            "name": "retrieval",
            "start_ms": 0.0,
            "duration_ms": 12.5,
            "status": "ok",
            "metadata": {"documents_found": 3},
        },
        {
            "name": "llm_generation",
            "start_ms": 12.5,
            "duration_ms": 800.0,
            "status": "error",
            "metadata": {},
        },
    ]


@respx.mock
def test_submit_trace_raises_on_http_error(client: SentinelClient) -> None:
    respx.post(f"{BASE_URL}/api/v1/traces").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid or revoked API key"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.submit_trace(
            application_id="support-bot",
            model="mock:sentinel-flash",
            provider="mock",
            prompt="q",
            response="a",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
        )


@respx.mock
def test_generate_sends_kwargs_as_json_body(client: SentinelClient) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/generate").mock(
        return_value=httpx.Response(200, json={"trace_id": "trc_2", "model": "mock:sentinel-pro"})
    )

    result = client.generate(
        application_id="support-bot", question="What is your refund policy?", use_cache=False
    )

    assert route.called
    import json

    body = json.loads(route.calls.last.request.content)
    assert body == {
        "application_id": "support-bot",
        "question": "What is your refund policy?",
        "use_cache": False,
    }
    assert result == {"trace_id": "trc_2", "model": "mock:sentinel-pro"}


def test_span_recorder_captures_ok_and_error_status() -> None:
    recorder = SpanRecorder()
    with recorder:
        with recorder.span("retrieval", documents_found=2):
            pass
        with pytest.raises(ValueError), recorder.span("llm_generation"):
            raise ValueError("boom")

    assert [s.name for s in recorder.spans] == ["retrieval", "llm_generation"]
    assert recorder.spans[0].status == "ok"
    assert recorder.spans[0].metadata == {"documents_found": 2}
    assert recorder.spans[1].status == "error"
    assert recorder.spans[1].duration_ms >= 0
