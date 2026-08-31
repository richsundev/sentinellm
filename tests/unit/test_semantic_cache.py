import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.caching.semantic_cache import SemanticCache
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
