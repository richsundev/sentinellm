import pytest

from sentinellm.evaluation.base import EvaluationContext
from sentinellm.evaluation.judge import (
    JUDGE_EVALUATOR_VERSION,
    JUDGE_FALLBACK_VERSION,
    JudgeEvaluator,
)
from sentinellm.llm.base import LLMRequest, LLMResponse
from sentinellm.llm.mock_provider import MockProvider


class AlwaysMalformedProvider:
    name = "malformed"
    calls = 0

    def supports_model(self, model: str) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content="not valid json {{{",
            model=request.model,
            provider=self.name,
            input_tokens=5,
            output_tokens=5,
            latency_ms=1.0,
        )


@pytest.mark.asyncio
async def test_judge_falls_back_after_exhausting_retries_on_malformed_output() -> None:
    provider = AlwaysMalformedProvider()
    evaluator = JudgeEvaluator(provider, max_attempts=3)

    result = await evaluator.evaluate(
        EvaluationContext(
            question="What is the refund window?",
            answer="30 days.",
            context="Refunds are honored within 30 days.",
        )
    )

    assert result.evaluator_version == JUDGE_FALLBACK_VERSION
    assert 0.0 <= result.score <= 1.0
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_judge_evaluator_against_mock_provider_always_yields_valid_result() -> None:
    """Exercises the real MockProvider's simulated judge JSON generation
    (including its occasional deliberately-malformed first attempt) across
    many distinct inputs — the evaluator must never propagate a parse error."""
    evaluator = JudgeEvaluator(MockProvider(), model="mock:sentinel-judge")

    for i in range(15):
        ctx = EvaluationContext(
            question=f"How does feature {i} work?",
            answer=f"Feature {i} works by processing the request and returning a response, item {i}.",
            context=f"Feature {i} documentation: it processes requests and returns responses.",
        )
        result = await evaluator.evaluate(ctx)
        assert 0.0 <= result.score <= 1.0
        assert result.evaluator_version in {JUDGE_EVALUATOR_VERSION, JUDGE_FALLBACK_VERSION}
