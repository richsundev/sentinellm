# Evaluation methodology

## Overview

Every evaluator implements the same interface
([`evaluation/base.py`](../src/sentinellm/evaluation/base.py)):

```python
class Evaluator(ABC):
    metric_name: str
    version: str = "v1"
    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult: ...
```

`EvaluationMetricResult` always carries `metric_name`, `score` (0–1),
`threshold`, `passed` (`True`/`False`/`None` if not applicable),
`reason` (a human-readable explanation, shown in the dashboard), and
`evaluator_version` — so the pipeline, storage layer, and dashboard never
special-case which kind of evaluator produced a metric.

## Deterministic evaluators

All eight live in
[`evaluation/deterministic.py`](../src/sentinellm/evaluation/deterministic.py).
Six of them share one primitive: cosine similarity over the platform's
`EmbeddingProvider` abstraction (the same one the semantic cache and
retriever use).

| Evaluator | What it measures | How |
|---|---|---|
| `relevance` | Does the answer address the question? | cosine(question, answer) |
| `faithfulness` | Is the answer grounded in the context? | avg cosine(each answer sentence, context) |
| `context_utilization` | Was retrieved context actually used? | max cosine(answer, each retrieved doc) |
| `retrieval_quality` | Do retrieved docs relate to the question? | avg cosine(question, each retrieved doc) |
| `safety` | Does the answer contain blocked content? | configurable term blocklist |
| `prompt_injection_risk` | Does the *question* attempt to hijack the system prompt? | pattern match, see [docs/security.md](security.md) |
| `latency` | Was the response fast enough? | `1 - latency_ms / (2 × threshold)` |
| `cost_efficiency` | Was the response cheap enough? | `1 - cost / (2 × threshold)` |

These run on every trace, for free, with no LLM call — which is why the
spec requires them to exist independent of the judge (section 5): a judge
outage should never mean "no evaluation happened at all."

## LLM-as-judge

[`evaluation/judge.py`](../src/sentinellm/evaluation/judge.py) prompts a
judge model with the question/context/answer and an instruction to return
*only* a JSON object matching:

```json
{"score": 0.0-1.0, "reasoning": "...", "evidence": ["..."], "confidence": 0.0-1.0}
```

The response is parsed with `json.loads` and validated against a Pydantic
`JudgeVerdict` model. On `JSONDecodeError` or `ValidationError`, the judge
is retried (up to 3 attempts by default) with a fresh call. If every
attempt fails, `JudgeEvaluator` falls back to a deterministic
question/answer relevance score (`evaluator_version` becomes
`judge-fallback-v1` instead of `judge-v1`, so it's visible in the data
which path produced a given score) — a judge that's down or misbehaving
degrades the evaluation, it never crashes it.

`MockProvider` simulates this realistically: when asked for a judge
response it returns real JSON built from actual word-overlap between the
supplied context and answer, blended with a small amount of deterministic
noise — and a small deterministic fraction of *first* attempts are
truncated (invalid JSON) specifically so the retry path is exercised by
real generated traffic, not just a hand-built malformed string in a unit
test (see `tests/unit/test_judge.py` for both).

## Hallucination detection

[`evaluation/hallucination.py`](../src/sentinellm/evaluation/hallucination.py)
is a two-stage, explicitly pluggable pipeline:

```python
class ClaimExtractor(Protocol):
    def extract(self, answer: str) -> list[Claim]: ...

class ClaimVerifier(Protocol):
    async def verify(self, claim: Claim, context: str) -> ClaimVerdict: ...
```

The shipped defaults: `SentenceSplitClaimExtractor` (each sentence is one
claim — simple, and correct often enough that a compound-sentence LLM-based
decomposer is a natural v2, not a blocker) and
`EmbeddingSimilarityVerifier` (best-matching context sentence's cosine
similarity determines SUPPORTED ≥0.6 / PARTIALLY_SUPPORTED ≥0.3 /
UNSUPPORTED below that).

`hallucination_score` is the mean of `{SUPPORTED: 0, PARTIALLY_SUPPORTED:
0.5, UNSUPPORTED: 1.0}` across all claims — i.e. the fraction of the answer
that isn't grounded, weighted by how ungrounded each claim is. The
dashboard's trace detail page renders every claim with its status,
support score, and the specific evidence sentence (or lack thereof).

## RAG evaluation metrics

[`evaluation/rag_metrics.py`](../src/sentinellm/evaluation/rag_metrics.py)
implements the classic IR metrics — Recall@K, Precision@K, MRR, NDCG@K,
and a lexical `context_coverage` proxy — for use against the benchmark
dataset ([`datasets/support_bench_v1.jsonl`](../datasets/support_bench_v1.jsonl),
20 realistic customer-support Q&A records with category/difficulty
metadata) where ground-truth relevant documents are known. These are
distinct from the per-trace deterministic evaluators above: per-trace
evaluation has no ground truth to compare against (that's what
`retrieval_quality`/`context_utilization` approximate instead), while a
dataset evaluation run *does* have labeled expected answers/context to
score against directly.

## Aggregation: `overall_quality`

```python
_QUALITY_WEIGHTS = {"relevance": 0.30, "faithfulness": 0.35, "judge_quality": 0.35}

base = weighted_average(relevance, faithfulness, judge_quality)   # over whichever ran
quality = base * safety_score                                     # safety gates everything
quality = max(0, quality - 0.4 * hallucination_score               # hallucination penalizes
                          - 0.3 * prompt_injection_risk)            # so does a detected injection attempt
```

This weighting is a tuned choice, not a derived constant — it's isolated
in one function
(`_aggregate_quality` in [`evaluation/pipeline.py`](../src/sentinellm/evaluation/pipeline.py))
specifically so it can be revisited without touching evaluator
implementations.

## Idempotency

`EvaluationPipeline.run_and_persist` checks for an existing `Evaluation`
row (by `trace_id`) before doing any work, and the worker additionally
claims the trace with a guarded `UPDATE ... WHERE evaluation_status =
'pending'` before invoking the pipeline at all — see [design decision
10](design-decisions.md#10-idempotent-ingestion-and-idempotent-evaluation-at-two-different-layers).
