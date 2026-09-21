"""Floating-point and real-model output shapes the evaluators must survive."""

from __future__ import annotations

import pytest

from sentinellm.embeddings.similarity import cosine_similarity
from sentinellm.evaluation.base import EvaluationContext
from sentinellm.evaluation.judge import (
    JUDGE_EVALUATOR_VERSION,
    JUDGE_FALLBACK_VERSION,
    JudgeEvaluator,
)
from sentinellm.llm.base import LLMRequest, LLMResponse


def test_cosine_similarity_never_exceeds_one() -> None:
    """`dot / (|a||b|)` of a vector with itself can land a hair above 1.0."""
    v = [0.901, 0.031, 0.025]
    assert cosine_similarity(v, v) <= 1.0
    assert cosine_similarity(v, [-x for x in v]) >= -1.0


@pytest.mark.asyncio
async def test_judge_fallback_survives_an_answer_identical_to_the_question() -> None:
    """The fallback scores question/answer similarity, which is a hair above 1
    for identical text — that used to fail the verdict's `le=1.0` validation
    and fail the whole evaluation job."""
    evaluator = JudgeEvaluator(_Scripted(["not json"]), max_attempts=1)

    result = await evaluator.evaluate(
        EvaluationContext(question="hello world foo", answer="hello world foo", context="")
    )

    assert result.evaluator_version == JUDGE_FALLBACK_VERSION
    assert result.score <= 1.0


class _Scripted:
    name = "scripted"

    def __init__(self, replies: list[str | None]) -> None:
        self._replies = replies
        self.calls = 0

    def supports_model(self, model: str) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return LLMResponse(
            content=reply,  # type: ignore[arg-type]
            model=request.model,
            provider=self.name,
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
        )


_VERDICT = '{"score": 0.8, "reasoning": "grounded", "evidence": [], "confidence": 0.9}'
_CTX = EvaluationContext(question="q?", answer="a.", context="c")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        f"```json\n{_VERDICT}\n```",
        f"```\n{_VERDICT}\n```",
        f"Here is my verdict:\n{_VERDICT}\nHope that helps!",
    ],
)
async def test_judge_accepts_a_verdict_wrapped_in_fences_or_prose(reply: str) -> None:
    """Real chat models wrap JSON in markdown fences no matter how firmly the
    prompt forbids it; that used to burn every retry and fall back to a
    meaningless similarity score."""
    provider = _Scripted([reply])

    result = await JudgeEvaluator(provider, max_attempts=3).evaluate(_CTX)

    assert result.evaluator_version == JUDGE_EVALUATOR_VERSION
    assert result.score == 0.8
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_judge_treats_a_null_reply_as_malformed_not_a_crash() -> None:
    provider = _Scripted([None, _VERDICT])

    result = await JudgeEvaluator(provider, max_attempts=3).evaluate(_CTX)

    assert result.evaluator_version == JUDGE_EVALUATOR_VERSION
    assert provider.calls == 2
