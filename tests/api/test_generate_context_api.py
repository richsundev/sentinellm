"""What the model is shown, and when a cached answer may be replayed."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.llm.base import LLMRequest
from sentinellm.llm.mock_provider import MockProvider

_BASE = {
    "application_id": "ctx-app",
    "question": "What is the refund policy?",
    "preferred_model": "mock:sentinel-flash",
    "use_cache": True,
}


def _docs(text: str) -> list[dict]:
    return [{"doc_id": "d1", "content": text, "score": 1.0, "rank": 0}]


@pytest.mark.asyncio
async def test_same_question_over_different_documents_is_not_a_cache_hit(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    first = await client.post(
        "/api/v1/generate", json={**_BASE, "retrieved_documents": _docs("Refunds within 30 days.")}
    )
    other_docs = await client.post(
        "/api/v1/generate", json={**_BASE, "retrieved_documents": _docs("Refunds were abolished.")}
    )
    same_docs = await client.post(
        "/api/v1/generate", json={**_BASE, "retrieved_documents": _docs("Refunds within 30 days.")}
    )

    assert first.json()["cache_hit"] is False
    assert other_docs.json()["cache_hit"] is False
    assert same_docs.json()["cache_hit"] is True


@pytest.mark.asyncio
async def test_system_prompt_and_retrieved_documents_both_reach_the_model(
    client: AsyncClient, seeded_models: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[LLMRequest] = []
    original = MockProvider.complete

    async def spy(self: MockProvider, request: LLMRequest):
        seen.append(request)
        return await original(self, request)

    monkeypatch.setattr(MockProvider, "complete", spy)

    resp = await client.post(
        "/api/v1/generate",
        json={
            **_BASE,
            "use_cache": False,
            "system_prompt": "Answer briefly.",
            "retrieved_documents": _docs("Refunds within 30 days."),
        },
    )

    assert resp.status_code == 200
    system = next(m.content for m in seen[-1].messages if m.role == "system")
    assert "Answer briefly." in system
    assert "Refunds within 30 days." in system
