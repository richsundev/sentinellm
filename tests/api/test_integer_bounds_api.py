"""Values beyond a 32-bit column are a validation error, not a database error."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

_HUGE = 3_000_000_000  # > 2**31 - 1, the largest value an INTEGER column stores


def _ingest(**over: object) -> dict:
    return {
        "application_id": "bounds",
        "model": "mock:sentinel-flash",
        "provider": "mock",
        "prompt": "q",
        "response": "a",
        "evaluate": False,
        **over,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"input_tokens": _HUGE},
        {"output_tokens": _HUGE},
        {"prompt_version": _HUGE},
        {"prompt_version": 0},
        {"prompt_version": -3},
        {"retrieved_documents": [{"doc_id": "d", "content": "c", "rank": _HUGE}]},
    ],
)
async def test_ingest_rejects_out_of_range_integers(client: AsyncClient, bad: dict) -> None:
    assert (await client.post("/api/v1/traces", json=_ingest(**bad))).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/traces", "/api/v1/models", "/api/v1/prompts"])
async def test_an_absurd_offset_is_a_422(client: AsyncClient, path: str) -> None:
    resp = await client.get(path, params={"offset": 10**30})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_model_cannot_be_registered_with_an_unstorable_context_window(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/models",
        json={
            "id": "acme:big",
            "name": "big",
            "provider": "acme",
            "input_price_per_1k": 1,
            "output_price_per_1k": 1,
            "context_window": _HUGE,
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN"])
async def test_non_finite_numbers_are_rejected_not_stored(
    client: AsyncClient, literal: str
) -> None:
    """Python's JSON parser accepts `Infinity`/`NaN`. A stored infinite latency
    then poisons every aggregate, and the overview fails to serialise."""
    body = (
        '{"application_id": "a", "model": "m", "provider": "p", "prompt": "q", '
        f'"latency_ms": {literal}, "evaluate": false}}'
    )

    resp = await client.post(
        "/api/v1/traces", content=body, headers={"Content-Type": "application/json"}
    )

    assert resp.status_code == 422
    assert (await client.get("/api/v1/metrics/overview")).status_code == 200
