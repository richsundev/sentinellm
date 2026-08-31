import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_generate_end_to_end_produces_trace_with_routing_decision(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "support-bot",
            "question": "What is your refund policy?",
            "system_prompt": "Refunds are honored within 30 days of purchase.",
            "use_cache": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["response"]
    assert body["routing_decision"] is not None
    assert body["routing_decision"]["selected_model"] == body["model"]
    assert len(body["spans"]) >= 3
    assert body["estimated_cost"] >= 0


@pytest.mark.asyncio
async def test_generate_complex_question_routes_to_stronger_model(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    prompt = (
        "Analyze the trade-offs between our current caching architecture and a distributed "
        "approach, explain the root cause of the regression, and design a step by step migration "
        "plan with rollback considerations for the production database."
    )
    resp = await client.post(
        "/api/v1/generate",
        json={"application_id": "support-bot", "question": prompt, "use_cache": False},
    )
    body = resp.json()
    assert body["routing_decision"]["candidates"]
    assert body["model"] in {"mock:sentinel-pro", "mock:sentinel-opus"}


@pytest.mark.asyncio
async def test_generate_uses_semantic_cache_on_repeat_question(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    payload = {
        "application_id": "support-bot",
        "question": "What is your refund policy for annual plans?",
        "preferred_model": "mock:sentinel-flash",
        "use_cache": True,
        "use_router": False,
    }
    first = await client.post("/api/v1/generate", json=payload)
    second = await client.post("/api/v1/generate", json=payload)

    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert second.json()["similarity_score"] is not None
    assert second.json()["estimated_cost"] == 0.0


@pytest.mark.asyncio
async def test_generate_with_retrieved_documents_populates_context(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "support-bot",
            "question": "How long does shipping take?",
            "preferred_model": "mock:sentinel-flash",
            "use_cache": False,
            "retrieved_documents": [
                {
                    "doc_id": "d1",
                    "content": "Standard shipping takes 3-5 business days.",
                    "score": 0.9,
                    "rank": 0,
                }
            ],
        },
    )
    body = resp.json()
    assert len(body["retrieved_documents"]) == 1
    assert body["retrieved_documents"][0]["doc_id"] == "d1"
