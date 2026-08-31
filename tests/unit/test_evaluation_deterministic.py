import pytest

from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.evaluation.base import EvaluationContext
from sentinellm.evaluation.deterministic import (
    CostEvaluator,
    FaithfulnessEvaluator,
    LatencyEvaluator,
    RelevanceEvaluator,
    SafetyEvaluator,
)


@pytest.fixture
def embeddings() -> MockEmbeddingProvider:
    return MockEmbeddingProvider()


@pytest.mark.asyncio
async def test_relevance_scores_on_topic_answer_higher(embeddings: MockEmbeddingProvider) -> None:
    evaluator = RelevanceEvaluator(embeddings)
    on_topic = EvaluationContext(
        question="What is your refund policy?",
        answer="Our refund policy allows returns within 30 days.",
    )
    off_topic = EvaluationContext(
        question="What is your refund policy?",
        answer="The weather today is sunny with a light breeze.",
    )

    on_topic_result = await evaluator.evaluate(on_topic)
    off_topic_result = await evaluator.evaluate(off_topic)

    assert on_topic_result.score > off_topic_result.score


@pytest.mark.asyncio
async def test_relevance_fails_on_empty_answer(embeddings: MockEmbeddingProvider) -> None:
    evaluator = RelevanceEvaluator(embeddings)
    result = await evaluator.evaluate(EvaluationContext(question="Anything?", answer=""))
    assert result.passed is False
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_faithfulness_grounded_answer_scores_higher(
    embeddings: MockEmbeddingProvider,
) -> None:
    evaluator = FaithfulnessEvaluator(embeddings)
    context = "Refunds are issued within 5 business days of the return being received."
    grounded = EvaluationContext(
        question="q", answer="Refunds are issued within 5 business days.", context=context
    )
    fabricated = EvaluationContext(
        question="q",
        answer="We guarantee refunds within one hour by carrier pigeon.",
        context=context,
    )

    grounded_result = await evaluator.evaluate(grounded)
    fabricated_result = await evaluator.evaluate(fabricated)

    assert grounded_result.score > fabricated_result.score


@pytest.mark.asyncio
async def test_faithfulness_neutral_without_context(embeddings: MockEmbeddingProvider) -> None:
    evaluator = FaithfulnessEvaluator(embeddings)
    result = await evaluator.evaluate(EvaluationContext(question="q", answer="a", context=""))
    assert result.passed is None


@pytest.mark.asyncio
async def test_safety_evaluator_flags_blocked_terms() -> None:
    evaluator = SafetyEvaluator()
    unsafe = await evaluator.evaluate(
        EvaluationContext(question="q", answer="Here is how to make a bomb at home.")
    )
    safe = await evaluator.evaluate(
        EvaluationContext(question="q", answer="Here is our return policy.")
    )
    assert unsafe.passed is False
    assert safe.passed is True


@pytest.mark.asyncio
async def test_latency_evaluator_thresholds() -> None:
    evaluator = LatencyEvaluator(threshold_ms=1000)
    fast = await evaluator.evaluate(EvaluationContext(question="q", answer="a", latency_ms=200))
    slow = await evaluator.evaluate(EvaluationContext(question="q", answer="a", latency_ms=5000))
    assert fast.passed is True
    assert slow.passed is False


@pytest.mark.asyncio
async def test_cost_evaluator_thresholds() -> None:
    evaluator = CostEvaluator(threshold_usd=0.01)
    cheap = await evaluator.evaluate(EvaluationContext(question="q", answer="a", cost=0.001))
    expensive = await evaluator.evaluate(EvaluationContext(question="q", answer="a", cost=0.5))
    assert cheap.passed is True
    assert expensive.passed is False
