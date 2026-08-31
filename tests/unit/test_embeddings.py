import pytest

from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.embeddings.similarity import cosine_similarity


@pytest.mark.asyncio
async def test_identical_text_has_similarity_one() -> None:
    provider = MockEmbeddingProvider()
    vec = await provider.embed("What is the refund policy?")
    assert cosine_similarity(vec, vec) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_similar_text_scores_higher_than_unrelated_text() -> None:
    provider = MockEmbeddingProvider()
    base = await provider.embed("What is the refund policy for annual subscriptions?")
    similar = await provider.embed("What is the refund policy for a yearly subscription?")
    unrelated = await provider.embed("How do I reset my password on a mobile device?")

    assert cosine_similarity(base, similar) > cosine_similarity(base, unrelated)


@pytest.mark.asyncio
async def test_empty_text_returns_zero_vector() -> None:
    provider = MockEmbeddingProvider()
    vec = await provider.embed("")
    assert all(v == 0.0 for v in vec)


def test_cosine_similarity_handles_mismatched_or_empty_vectors() -> None:
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
