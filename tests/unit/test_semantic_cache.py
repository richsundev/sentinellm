from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.caching.semantic_cache import SemanticCache, context_key_for, prune_expired_entries
from sentinellm.db.models import SemanticCacheEntry
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider


@pytest.mark.asyncio
async def test_cache_miss_when_empty(db_session: AsyncSession) -> None:
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.9)
    result = await cache.lookup(
        db_session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="What is the refund policy?",
    )
    assert result is None


@pytest.mark.asyncio
async def test_cache_hit_on_near_duplicate_query(db_session: AsyncSession) -> None:
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.85)
    await cache.store(
        db_session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="What is your refund policy for annual subscriptions?",
        response="Refunds within 30 days.",
    )

    result = await cache.lookup(
        db_session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="What is your refund policy for annual subscriptions?",
    )
    assert result is not None
    assert result.response == "Refunds within 30 days."
    assert result.similarity_score >= 0.85


@pytest.mark.asyncio
async def test_cache_miss_for_dissimilar_query(db_session: AsyncSession) -> None:
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.9)
    await cache.store(
        db_session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="What is your refund policy?",
        response="Refunds within 30 days.",
    )

    result = await cache.lookup(
        db_session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="How do I reset my password?",
    )
    assert result is None


@pytest.mark.asyncio
async def test_cache_scoped_by_application_and_model(db_session: AsyncSession) -> None:
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.85)
    await cache.store(
        db_session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="What is your refund policy?",
        response="Refunds within 30 days.",
    )

    other_app = await cache.lookup(
        db_session,
        application_id="app-2",
        model="mock:sentinel-flash",
        query_text="What is your refund policy?",
    )
    other_model = await cache.lookup(
        db_session,
        application_id="app-1",
        model="mock:sentinel-pro",
        query_text="What is your refund policy?",
    )

    assert other_app is None
    assert other_model is None


async def _store(cache: SemanticCache, session: AsyncSession, **kwargs: str) -> None:
    await cache.store(
        session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="What is your refund policy?",
        response="Refunds within 30 days.",
        **kwargs,
    )


async def _lookup(cache: SemanticCache, session: AsyncSession, **kwargs: str):
    return await cache.lookup(
        session,
        application_id="app-1",
        model="mock:sentinel-flash",
        query_text="What is your refund policy?",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_same_question_with_different_context_is_a_miss(db_session: AsyncSession) -> None:
    """A RAG answer depends on the retrieved documents, not just the question."""
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.9)
    await _store(cache, db_session, context_key=context_key_for("doc: refunds within 30 days"))

    assert await _lookup(cache, db_session, context_key=context_key_for("doc: no refunds")) is None
    assert await _lookup(cache, db_session) is None  # ...nor a context-free lookup
    same = await _lookup(
        cache, db_session, context_key=context_key_for("doc: refunds within 30 days")
    )
    assert same is not None


@pytest.mark.asyncio
async def test_expired_entries_are_not_served_and_are_pruned(db_session: AsyncSession) -> None:
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.9, ttl_seconds=3600)
    await _store(cache, db_session)
    entry = (await db_session.execute(select(SemanticCacheEntry))).scalar_one()
    assert await _lookup(cache, db_session) is not None

    entry.created_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.flush()

    assert await _lookup(cache, db_session) is None
    assert await prune_expired_entries(db_session, 3600) == 1
    assert (await db_session.execute(select(SemanticCacheEntry))).first() is None


@pytest.mark.asyncio
async def test_ttl_zero_never_expires(db_session: AsyncSession) -> None:
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.9, ttl_seconds=0)
    await _store(cache, db_session)
    entry = (await db_session.execute(select(SemanticCacheEntry))).scalar_one()
    entry.created_at = datetime.now(UTC) - timedelta(days=3650)
    await db_session.flush()

    assert await _lookup(cache, db_session) is not None
    assert await prune_expired_entries(db_session, 0) == 0
