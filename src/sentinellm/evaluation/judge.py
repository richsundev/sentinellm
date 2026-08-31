"""LLM-as-a-judge evaluator with structured output validation and retry.

The judge is prompted to return ONLY a JSON object; the response is parsed
and validated against `JudgeVerdict` (Pydantic). Malformed output (invalid
JSON, or JSON that fails schema validation) triggers a bounded retry against
the judge model before falling back to a deterministic heuristic score, so a
single flaky judge call never fails the whole evaluation pipeline.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from sentinellm.core.logging import get_logger
from sentinellm.evaluation.base import EvaluationContext, EvaluationMetricResult, Evaluator
from sentinellm.llm.base import LLMMessage, LLMProvider, LLMRequest, ProviderError

logger = get_logger(__name__)

JUDGE_EVALUATOR_VERSION = "judge-v1"
JUDGE_FALLBACK_VERSION = "judge-fallback-v1"

_DEFAULT_RUBRIC = (
    "You are an exacting evaluation judge for an AI support system. Given a QUESTION, "
    "supporting CONTEXT, and an ANSWER, score how well the answer is supported by the "
    "context and how well it addresses the question. Score from 0.0 (unsupported / off-topic) "
    "to 1.0 (fully supported / on-topic)."
)

_RESPONSE_INSTRUCTIONS = (
    "Respond with ONLY a single JSON object, no prose, no markdown fences, matching exactly: "
    '{"score": <float 0-1>, "reasoning": <string>, "evidence": [<string>, ...], "confidence": <float 0-1>}'
)


class JudgeVerdict(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class JudgeEvaluator(Evaluator):
    metric_name = "judge_quality"
    version = JUDGE_EVALUATOR_VERSION

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str = "mock:sentinel-judge",
        rubric: str = _DEFAULT_RUBRIC,
        max_attempts: int = 3,
        threshold: float = 0.6,
    ) -> None:
        self._provider = provider
        self._model = model
        self._rubric = rubric
        self._max_attempts = max_attempts
        self._threshold = threshold

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        verdict, evaluator_version = await self._get_verdict(ctx)
        passed = verdict.score >= self._threshold
        reason = f"{verdict.reasoning.strip()} (confidence={verdict.confidence:.2f})"
        return EvaluationMetricResult(
            self.metric_name,
            round(verdict.score, 4),
            self._threshold,
            passed,
            reason,
            evaluator_version,
        )

    async def _get_verdict(self, ctx: EvaluationContext) -> tuple[JudgeVerdict, str]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            messages = [
                LLMMessage(role="system", content=f"{self._rubric}\n{_RESPONSE_INSTRUCTIONS}"),
                LLMMessage(
                    role="user",
                    content=f"QUESTION:\n{ctx.question}\n\nCONTEXT:\n{ctx.context}\n\nANSWER:\n{ctx.answer}",
                ),
            ]
            request = LLMRequest(
                model=self._model,
                messages=messages,
                max_tokens=400,
                temperature=0.0,
                metadata={"response_schema": "judge", "judge_attempt": attempt},
            )
            try:
                response = await self._provider.complete(request)
                verdict = JudgeVerdict.model_validate(json.loads(response.content))
                return verdict, self.version
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning("judge_malformed_response", attempt=attempt, error=str(exc))
            except ProviderError as exc:
                last_error = exc
                logger.warning("judge_provider_error", attempt=attempt, error=str(exc))
                if not exc.retryable:
                    break

        logger.error("judge_exhausted_retries", attempts=self._max_attempts, error=str(last_error))
        return await self._deterministic_fallback(ctx), JUDGE_FALLBACK_VERSION

    async def _deterministic_fallback(self, ctx: EvaluationContext) -> JudgeVerdict:
        from sentinellm.embeddings.factory import get_embedding_provider
        from sentinellm.embeddings.similarity import cosine_similarity

        embeddings = get_embedding_provider("mock")
        q_vec = await embeddings.embed(ctx.question)
        a_vec = await embeddings.embed(ctx.answer)
        score = max(0.0, cosine_similarity(q_vec, a_vec))
        return JudgeVerdict(
            score=score,
            reasoning="judge unavailable after retries; deterministic relevance fallback used",
            evidence=[],
            confidence=0.3,
        )
