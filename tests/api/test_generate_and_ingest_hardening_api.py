"""Second-pass hardening of `/generate`, replay, trace ingestion and search."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.db.models import ModelPricing, SemanticCacheEntry
from sentinellm.llm.base import LLMRequest
from sentinellm.llm.mock_provider import MockProvider

_FLASH = "mock:sentinel-flash"


def _gen(**over: object) -> dict:
    return {
        "application_id": "hard-app",
        "question": "What is the refund policy?",
        "preferred_model": _FLASH,
        "use_cache": False,
        "evaluate": False,
        **over,
    }


def _ingest(**over: object) -> dict:
    return {
        "application_id": "hard-app",
        "model": _FLASH,
        "provider": "mock",
        "prompt": "q",
        "response": "a",
        "evaluate": False,
        **over,
    }


# --- request validation ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"top_k": 0}, {"top_k": -1}, {"top_k": 10_000}, {"question": ""}])
async def test_generate_rejects_nonsensical_parameters(
    client: AsyncClient, seeded_models: AsyncSession, bad: dict
) -> None:
    resp = await client.post("/api/v1/generate", json=_gen(**bad))
    assert resp.status_code == 422


# --- failures hidden by a fallback -------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_first_choice_is_recorded_on_the_trace_that_fell_back(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/generate",
        json=_gen(preferred_model="openai:gpt-4o", fallback_models=[_FLASH]),
    )

    body = resp.json()
    assert body["status"] == "ok"
    assert body["model"] == _FLASH
    assert [a["model"] for a in body["metadata"]["failed_attempts"]] == ["openai:gpt-4o"]


# --- replay -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_does_not_inherit_the_originals_internal_bookkeeping(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    """`failed_attempts` (and rollout attribution) describe *that* request's
    execution. Copied onto a replay they would count as phantom failures."""
    original = await client.post(
        "/api/v1/generate",
        json=_gen(
            preferred_model="openai:gpt-4o",
            fallback_models=[_FLASH],
            metadata={"customer": "acme", "rollout_id": "r-old", "rollout_arm": "challenger"},
        ),
    )
    assert original.json()["metadata"]["failed_attempts"]

    replay = await client.post(
        f"/api/v1/traces/{original.json()['trace_id']}/replay", json={"model": _FLASH}
    )

    meta = replay.json()["metadata"]
    assert meta["customer"] == "acme"  # the caller's own metadata is preserved
    assert meta["replay_of"] == original.json()["trace_id"]
    for internal in ("failed_attempts", "rollout_id", "rollout_arm"):
        assert internal not in meta


# --- PII ----------------------------------------------------------------------


@pytest.fixture
def pii_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "pii_redaction_enabled", True)


@pytest.mark.asyncio
async def test_generate_stores_no_raw_pii_when_redaction_is_enabled(
    client: AsyncClient,
    seeded_models: AsyncSession,
    pii_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redaction used to be applied only to `POST /traces`; a `/generate` trace
    (and its semantic-cache entry, which is replayed to *other* callers) kept
    the raw text. The model still gets the real question — only what is
    persisted is redacted."""
    seen: list[LLMRequest] = []
    original = MockProvider.complete

    async def spy(self: MockProvider, request: LLMRequest):
        seen.append(request)
        return await original(self, request)

    monkeypatch.setattr(MockProvider, "complete", spy)

    resp = await client.post(
        "/api/v1/generate",
        json=_gen(
            question="Email jane.doe@example.com about order 42",
            system_prompt="Call 555-123-4567 if needed",
            retrieved_documents=[
                {
                    "doc_id": "d",
                    "content": "Contact bob@corp.io for refunds.",
                    "score": 1,
                    "rank": 0,
                }
            ],
            use_cache=True,
        ),
    )

    trace = resp.json()
    assert "jane.doe@example.com" in seen[-1].messages[-1].content  # the model saw it
    stored = " ".join(
        [
            trace["prompt"],
            trace["system_prompt"],
            trace["response"],
            *(d["content"] for d in trace["retrieved_documents"]),
        ]
    )
    for raw in ("jane.doe@example.com", "555-123-4567", "bob@corp.io"):
        assert raw not in stored
    assert "[REDACTED_EMAIL]" in trace["prompt"]

    entries = (await seeded_models.execute(select(SemanticCacheEntry))).scalars().all()
    assert entries
    for entry in entries:
        assert "jane.doe@example.com" not in entry.query_text + entry.response


@pytest.mark.asyncio
async def test_ingest_redacts_retrieved_documents_too(client: AsyncClient, pii_on: None) -> None:
    resp = await client.post(
        "/api/v1/traces",
        json=_ingest(
            retrieved_documents=[{"doc_id": "d", "content": "write to bob@corp.io", "rank": 0}]
        ),
    )
    assert "bob@corp.io" not in resp.json()["retrieved_documents"][0]["content"]


# --- ingestion cost -------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingested_traces_are_priced_from_the_registry_not_the_static_catalog(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`/generate` prices from the model registry (operators edit prices
    there); ingestion used the built-in catalog, so the same tokens cost
    different amounts depending on how the trace arrived."""
    db_session.add(
        ModelPricing(
            id="acme:custom",
            name="custom",
            provider="acme",
            input_price_per_1k=1.0,
            output_price_per_1k=2.0,
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/traces",
        json=_ingest(model="acme:custom", provider="acme", input_tokens=1000, output_tokens=500),
    )

    assert resp.json()["estimated_cost"] == pytest.approx(1.0 * 1 + 2.0 * 0.5)


@pytest.mark.asyncio
async def test_an_explicit_cost_on_ingest_still_wins(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/traces", json=_ingest(input_tokens=1000, estimated_cost=0.123)
    )
    assert resp.json()["estimated_cost"] == pytest.approx(0.123)


# --- tags and search --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tags", [[f"t{i}" for i in range(50)], ["x" * 500]], ids=["too-many", "too-long"]
)
async def test_tag_updates_are_bounded(client: AsyncClient, tags: list[str]) -> None:
    trace = (await client.post("/api/v1/traces", json=_ingest())).json()

    resp = await client.patch(f"/api/v1/traces/{trace['trace_id']}/tags", json={"tags": tags})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_treats_percent_and_underscore_literally(client: AsyncClient) -> None:
    """`q=100%` used to be the LIKE pattern `%100%%`, and `a_b` matched `axb`."""
    literal = (await client.post("/api/v1/traces", json=_ingest(prompt="a 100% guarantee"))).json()
    await client.post("/api/v1/traces", json=_ingest(prompt="a 1000 point plan"))
    await client.post("/api/v1/traces", json=_ingest(prompt="axb"))
    underscore = (await client.post("/api/v1/traces", json=_ingest(prompt="a_b"))).json()

    percent_hits = (await client.get("/api/v1/traces", params={"q": "100%"})).json()["items"]
    underscore_hits = (await client.get("/api/v1/traces", params={"q": "a_b"})).json()["items"]

    assert [t["trace_id"] for t in percent_hits] == [literal["trace_id"]]
    assert [t["trace_id"] for t in underscore_hits] == [underscore["trace_id"]]


@pytest.mark.asyncio
async def test_replaying_a_trace_with_an_empty_prompt_is_a_clean_422(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    """Ingestion accepts an empty prompt; `/generate` does not, so replaying
    one used to surface a raw validation error as a 500."""
    trace = (await client.post("/api/v1/traces", json=_ingest(prompt=""))).json()

    resp = await client.post(f"/api/v1/traces/{trace['trace_id']}/replay", json={})

    assert resp.status_code == 422
