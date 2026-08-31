"""Deterministic (non-LLM) evaluators.

Section 5 of the platform spec is explicit that evaluation must not rely
entirely on an LLM-as-judge: judges are slow, costly, and themselves
occasionally wrong. Every metric here is a pure function of its inputs and
the shared `EmbeddingProvider` similarity primitive, so it is fast, free,
and 100% reproducible — a real production system runs these on every trace
and reserves the judge for a sampled subset or for high-risk requests.
"""

from __future__ import annotations

import re

from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.embeddings.similarity import cosine_similarity
from sentinellm.evaluation.base import EvaluationContext, EvaluationMetricResult, Evaluator
from sentinellm.security.prompt_injection import detect_prompt_injection

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_UNSAFE_TERMS = frozenset(
    {
        "kill yourself",
        "make a bomb",
        "how to hack into",
        "credit card dump",
        "child exploitation",
        "synthesize nerve agent",
    }
)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


class RelevanceEvaluator(Evaluator):
    """Does the answer semantically address the question?"""

    metric_name = "relevance"
    version = "v1"
    threshold = 0.35

    def __init__(self, embeddings: EmbeddingProvider) -> None:
        self._embeddings = embeddings

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        if not ctx.answer.strip():
            return EvaluationMetricResult(
                self.metric_name, 0.0, self.threshold, False, "empty answer", self.version
            )
        q_vec = await self._embeddings.embed(ctx.question)
        a_vec = await self._embeddings.embed(ctx.answer)
        score = max(0.0, cosine_similarity(q_vec, a_vec))
        passed = score >= self.threshold
        reason = f"question/answer similarity={score:.3f} (threshold={self.threshold})"
        return EvaluationMetricResult(
            self.metric_name, round(score, 4), self.threshold, passed, reason, self.version
        )


class FaithfulnessEvaluator(Evaluator):
    """Deterministic fallback faithfulness: average per-sentence support of
    the answer against the provided context, using embedding similarity as
    the support signal. This is the metric used when no context is available
    to fall back to relevance-style grounding, and as a sanity check against
    the LLM judge's faithfulness score.
    """

    metric_name = "faithfulness"
    version = "v1"
    threshold = 0.55

    def __init__(self, embeddings: EmbeddingProvider) -> None:
        self._embeddings = embeddings

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        if not ctx.context.strip():
            return EvaluationMetricResult(
                self.metric_name,
                0.5,
                self.threshold,
                None,
                "no context provided; faithfulness not applicable",
                self.version,
            )
        sentences = split_sentences(ctx.answer) or [ctx.answer]
        context_vec = await self._embeddings.embed(ctx.context)
        scores = []
        for sentence in sentences:
            sent_vec = await self._embeddings.embed(sentence)
            scores.append(max(0.0, cosine_similarity(sent_vec, context_vec)))
        avg = sum(scores) / len(scores) if scores else 0.0
        passed = avg >= self.threshold
        reason = f"{len(sentences)} sentence(s) checked against context, avg support={avg:.3f}"
        return EvaluationMetricResult(
            self.metric_name, round(avg, 4), self.threshold, passed, reason, self.version
        )


class ContextUtilizationEvaluator(Evaluator):
    """Was retrieved context actually used, or ignored, by the generation?"""

    metric_name = "context_utilization"
    version = "v1"
    threshold = 0.25

    def __init__(self, embeddings: EmbeddingProvider) -> None:
        self._embeddings = embeddings

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        if not ctx.retrieved_documents:
            return EvaluationMetricResult(
                self.metric_name, 0.0, self.threshold, None, "no retrieved documents", self.version
            )
        answer_vec = await self._embeddings.embed(ctx.answer)
        doc_scores = []
        for doc in ctx.retrieved_documents:
            doc_vec = await self._embeddings.embed(doc.content)
            doc_scores.append(max(0.0, cosine_similarity(answer_vec, doc_vec)))
        utilization = max(doc_scores) if doc_scores else 0.0
        passed = utilization >= self.threshold
        reason = f"best-matching retrieved doc similarity to answer={utilization:.3f}"
        return EvaluationMetricResult(
            self.metric_name, round(utilization, 4), self.threshold, passed, reason, self.version
        )


class RetrievalQualityEvaluator(Evaluator):
    """Do the retrieved documents actually relate to the question?"""

    metric_name = "retrieval_quality"
    version = "v1"
    threshold = 0.3

    def __init__(self, embeddings: EmbeddingProvider) -> None:
        self._embeddings = embeddings

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        if not ctx.retrieved_documents:
            return EvaluationMetricResult(
                self.metric_name, 0.0, self.threshold, None, "no retrieved documents", self.version
            )
        q_vec = await self._embeddings.embed(ctx.question)
        sims = []
        for doc in ctx.retrieved_documents:
            doc_vec = await self._embeddings.embed(doc.content)
            sims.append(max(0.0, cosine_similarity(q_vec, doc_vec)))
        avg = sum(sims) / len(sims)
        passed = avg >= self.threshold
        reason = f"avg similarity of {len(sims)} retrieved doc(s) to question={avg:.3f}"
        return EvaluationMetricResult(
            self.metric_name, round(avg, 4), self.threshold, passed, reason, self.version
        )


class SafetyEvaluator(Evaluator):
    """Configurable deterministic safety/toxicity screen.

    A production deployment would plug in a real classifier here (e.g. a
    moderation model); the interface is identical either way — this is the
    local, dependency-free default so the pipeline runs everywhere.
    """

    metric_name = "safety"
    version = "v1"
    threshold = 1.0

    def __init__(self, blocklist: frozenset[str] = _UNSAFE_TERMS) -> None:
        self._blocklist = blocklist

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        lowered = ctx.answer.lower()
        hits = [term for term in self._blocklist if term in lowered]
        score = 0.0 if hits else 1.0
        passed = not hits
        reason = f"blocked terms detected: {hits}" if hits else "no unsafe content detected"
        return EvaluationMetricResult(
            self.metric_name, score, self.threshold, passed, reason, self.version
        )


class LatencyEvaluator(Evaluator):
    metric_name = "latency"
    version = "v1"

    def __init__(self, threshold_ms: float = 3000.0) -> None:
        self._threshold_ms = threshold_ms

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        score = max(0.0, min(1.0, 1 - (ctx.latency_ms / (self._threshold_ms * 2))))
        passed = ctx.latency_ms <= self._threshold_ms
        reason = f"latency={ctx.latency_ms:.0f}ms (threshold={self._threshold_ms:.0f}ms)"
        return EvaluationMetricResult(
            self.metric_name, round(score, 4), self._threshold_ms, passed, reason, self.version
        )


class CostEvaluator(Evaluator):
    metric_name = "cost_efficiency"
    version = "v1"

    def __init__(self, threshold_usd: float = 0.02) -> None:
        self._threshold_usd = threshold_usd

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        score = max(0.0, min(1.0, 1 - (ctx.cost / (self._threshold_usd * 2))))
        passed = ctx.cost <= self._threshold_usd
        reason = f"cost=${ctx.cost:.5f} (threshold=${self._threshold_usd:.5f})"
        return EvaluationMetricResult(
            self.metric_name, round(score, 4), self._threshold_usd, passed, reason, self.version
        )


class PromptInjectionEvaluator(Evaluator):
    """Flags requests whose *question* (the untrusted, user-supplied part
    of the prompt) matches a known prompt-injection pattern. See
    `sentinellm.security.prompt_injection` for the pattern list and why
    this is a heuristic first line of defense, not a completeness claim.
    """

    metric_name = "prompt_injection_risk"
    version = "v1"
    threshold = 0.5

    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult:
        result = detect_prompt_injection(ctx.question)
        passed = result.risk_score < self.threshold
        reason = (
            f"matched pattern(s): {result.matched_patterns}"
            if result.matched_patterns
            else "no known injection pattern matched"
        )
        return EvaluationMetricResult(
            self.metric_name, result.risk_score, self.threshold, passed, reason, self.version
        )


def default_deterministic_evaluators(embeddings: EmbeddingProvider) -> list[Evaluator]:
    return [
        RelevanceEvaluator(embeddings),
        FaithfulnessEvaluator(embeddings),
        ContextUtilizationEvaluator(embeddings),
        RetrievalQualityEvaluator(embeddings),
        SafetyEvaluator(),
        PromptInjectionEvaluator(),
        LatencyEvaluator(),
        CostEvaluator(),
    ]
