"""Evaluation orchestration: runs every configured evaluator against a trace,
aggregates an overall quality score, and persists the result idempotently.

Idempotency: `evaluations.trace_id` has a unique constraint. If a row already
exists for the trace (e.g. the worker crashed after evaluating but before
acking the job, and redelivers it), `run_and_persist` detects the existing
row and returns it unchanged instead of writing a duplicate evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.db.models import Evaluation, EvaluationMetric, HallucinationClaim, Trace
from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.evaluation.base import (
    EvaluationContext,
    EvaluationMetricResult,
    Evaluator,
    RetrievedDoc,
)
from sentinellm.evaluation.deterministic import default_deterministic_evaluators
from sentinellm.evaluation.hallucination import HallucinationDetector, HallucinationResult
from sentinellm.evaluation.judge import JudgeEvaluator
from sentinellm.llm.base import LLMProvider

logger = get_logger(__name__)

_QUALITY_WEIGHTS = {"relevance": 0.30, "faithfulness": 0.35, "judge_quality": 0.35}


@dataclass(slots=True)
class EvaluationRunResult:
    trace_db_id: str
    overall_quality: float
    metrics: list[EvaluationMetricResult]
    hallucination: HallucinationResult
    evaluator_version: str


def _aggregate_quality(metrics: list[EvaluationMetricResult], hallucination_score: float) -> float:
    by_name = {m.metric_name: m.score for m in metrics}
    weighted_sum = 0.0
    weight_total = 0.0
    for name, weight in _QUALITY_WEIGHTS.items():
        if name in by_name:
            weighted_sum += by_name[name] * weight
            weight_total += weight
    base = weighted_sum / weight_total if weight_total > 0 else 0.0

    safety_score = by_name.get("safety", 1.0)
    injection_risk = by_name.get("prompt_injection_risk", 0.0)
    quality = base * safety_score
    quality = max(0.0, quality - 0.4 * hallucination_score - 0.3 * injection_risk)
    return round(min(1.0, quality), 4)


class EvaluationPipeline:
    def __init__(
        self,
        embeddings: EmbeddingProvider,
        judge_provider: LLMProvider | None = None,
        extra_evaluators: list[Evaluator] | None = None,
        run_judge: bool = True,
        judge_model: str = "mock:sentinel-judge",
    ) -> None:
        self._embeddings = embeddings
        self._evaluators = default_deterministic_evaluators(embeddings) + (extra_evaluators or [])
        self._hallucination = HallucinationDetector(embeddings)
        self._judge = (
            JudgeEvaluator(judge_provider, model=judge_model)
            if (run_judge and judge_provider)
            else None
        )

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationRunResult:
        metrics = [await evaluator.evaluate(ctx) for evaluator in self._evaluators]
        if self._judge is not None:
            metrics.append(await self._judge.evaluate(ctx))

        hallucination = await self._hallucination.detect(ctx.question, ctx.context, ctx.answer)
        overall_quality = _aggregate_quality(metrics, hallucination.hallucination_score)

        return EvaluationRunResult(
            trace_db_id="",
            overall_quality=overall_quality,
            metrics=metrics,
            hallucination=hallucination,
            evaluator_version="pipeline-v1",
        )

    async def run_and_persist(self, session: AsyncSession, trace: Trace) -> Evaluation:
        existing = await session.execute(select(Evaluation).where(Evaluation.trace_id == trace.id))
        if (row := existing.scalar_one_or_none()) is not None:
            logger.info("evaluation_already_exists", trace_id=trace.trace_id)
            return row

        retrieved = [
            RetrievedDoc(
                doc_id=d.get("doc_id", ""),
                content=d.get("content", ""),
                score=d.get("score", 0.0),
                rank=d.get("rank", 0),
            )
            for d in (trace.retrieved_documents or [])
        ]
        context_text = "\n".join(d.content for d in retrieved) or (trace.system_prompt or "")
        ctx = EvaluationContext(
            question=trace.prompt,
            answer=trace.response,
            context=context_text,
            retrieved_documents=retrieved,
            latency_ms=trace.latency_ms,
            cost=trace.estimated_cost,
        )
        result = await self.evaluate(ctx)

        evaluation = Evaluation(
            trace_id=trace.id,
            overall_quality=result.overall_quality,
            hallucination_score=result.hallucination.hallucination_score,
            evaluator_version=result.evaluator_version,
        )
        evaluation.metrics = [
            EvaluationMetric(
                metric_name=m.metric_name,
                score=m.score,
                threshold=m.threshold,
                passed=m.passed,
                reason=m.reason,
                evaluator_version=m.evaluator_version,
            )
            for m in result.metrics
        ]
        evaluation.claims = [
            HallucinationClaim(
                claim=c.claim, status=c.status, support_score=c.support_score, evidence=c.evidence
            )
            for c in result.hallucination.claims
        ]
        session.add(evaluation)
        await session.flush()
        logger.info(
            "evaluation_completed",
            trace_id=trace.trace_id,
            overall_quality=result.overall_quality,
            hallucination_score=result.hallucination.hallucination_score,
        )
        return evaluation
