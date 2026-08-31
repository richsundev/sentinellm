import pytest

from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.evaluation.hallucination import SUPPORTED, UNSUPPORTED, HallucinationDetector


@pytest.mark.asyncio
async def test_fully_grounded_answer_has_low_hallucination_score() -> None:
    detector = HallucinationDetector(MockEmbeddingProvider())
    context = (
        "The product ships within 3 business days. Standard shipping is free for orders over $50."
    )
    answer = (
        "The product ships within 3 business days. Standard shipping is free for orders over $50."
    )

    result = await detector.detect("How fast does it ship?", context, answer)

    assert result.hallucination_score < 0.3
    assert any(c.status == SUPPORTED for c in result.claims)


@pytest.mark.asyncio
async def test_fabricated_claim_is_marked_unsupported() -> None:
    detector = HallucinationDetector(MockEmbeddingProvider())
    context = "The product ships within 3 business days."
    answer = "This product was rated the best gadget of the decade by a major national magazine."

    result = await detector.detect("How fast does it ship?", context, answer)

    assert result.hallucination_score > 0.5
    assert any(c.status == UNSUPPORTED for c in result.claims)


@pytest.mark.asyncio
async def test_no_context_yields_partial_support_not_full_confidence() -> None:
    detector = HallucinationDetector(MockEmbeddingProvider())
    result = await detector.detect("q", "", "Some answer with claims.")
    assert 0.0 < result.hallucination_score <= 1.0


@pytest.mark.asyncio
async def test_empty_answer_has_no_claims() -> None:
    detector = HallucinationDetector(MockEmbeddingProvider())
    result = await detector.detect("q", "context", "")
    assert result.claims == []
    assert result.hallucination_score == 0.0
