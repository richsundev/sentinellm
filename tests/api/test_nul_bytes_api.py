"""Postgres cannot store a NUL character in a text column: a request carrying
one used to sail through the SQLite test suite and 500 in production."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

_NUL = "\x00"


@pytest.mark.asyncio
async def test_ingested_text_has_nul_characters_removed(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/traces",
        json={
            "application_id": "nul-app",
            "model": "mock:sentinel-flash",
            "provider": "mock",
            "prompt": f"he{_NUL}llo",
            "response": f"wor{_NUL}ld",
            "retrieved_documents": [{"doc_id": "d", "content": f"do{_NUL}c", "rank": 0}],
            "metadata": {"k": f"v{_NUL}"},
            "evaluate": False,
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["prompt"] == "hello"
    assert body["response"] == "world"
    assert body["retrieved_documents"][0]["content"] == "doc"
    assert body["metadata"] == {"k": "v"}


@pytest.mark.asyncio
async def test_generate_strips_nul_from_the_question(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "nul-app",
            "question": f"ques{_NUL}tion",
            "preferred_model": "mock:sentinel-flash",
            "evaluate": False,
            "use_cache": False,
        },
    )

    assert resp.status_code == 200
    assert _NUL not in resp.json()["prompt"]
    assert _NUL not in resp.json()["response"]


@pytest.mark.asyncio
async def test_a_generated_response_containing_nul_is_still_stored(
    client: AsyncClient, seeded_models: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model's output isn't the caller's fault — dropping the trace after the
    money was spent would be the worst outcome."""
    from sentinellm.llm.base import LLMRequest, LLMResponse
    from sentinellm.llm.mock_provider import MockProvider

    async def dirty(self: MockProvider, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=f"an{_NUL}swer",
            model=request.model,
            provider="mock",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
        )

    monkeypatch.setattr(MockProvider, "complete", dirty)

    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "nul-app",
            "question": "q",
            "preferred_model": "mock:sentinel-flash",
            "evaluate": False,
            "use_cache": False,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["response"] == "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/traces?q=a%00b", "/api/v1/traces/trc%00x", "/api/v1/traces?tag=%00"]
)
async def test_nul_in_the_url_is_a_400_not_a_database_error(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 400
