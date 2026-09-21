# The router

## Goal

Given a request, pick the model that best balances predicted quality,
cost, latency, and risk — and be able to explain the choice.

## Pipeline

[`routing/router.py`](../src/sentinellm/routing/router.py):

1. **Classify task complexity** — `simple` / `medium` / `complex`, from a
   keyword + length heuristic
   ([`routing/complexity.py`](../src/sentinellm/routing/complexity.py)):
   a prompt over 120 words, or a shorter prompt containing a reasoning cue
   ("analyze", "compare", "root cause", "step by step", ...) past 25 words,
   is `complex`; shorter/plainer prompts are `medium` or `simple`. This is
   deliberately an explainable rule, not a learned classifier — a
   portfolio-scale project has no labeled complexity dataset to train one
   on, and "why did the router call this complex?" needs a one-line answer
   you can show a stakeholder. A learned classifier is a natural v2.

2. **Assess risk** — `0.10` baseline, `0.85` if the prompt contains a
   high-risk term (legal/medical/financial/security-incident/self-harm
   vocabulary), `0.90` if metadata explicitly overrides it.

3. **Determine the quality floor** — `0.0` for simple, `0.45` for medium,
   `0.80` for complex; raised to at least `0.85` if risk ≥ 0.8. This is
   what turns "prefer a strong model for complex/risky work" from a soft
   weight-driven preference into a guarantee — see [design decision
   8](design-decisions.md#8-the-router-excludes-before-it-scores).

4. **Exclude candidates**: any model with observed `status == "down"` is
   dropped outright (provider outage → automatic fallback to a healthy
   candidate); any model whose context window can't hold the request
   (estimated at ~1.4 tokens per word of prompt + context) is dropped; any
   model whose `predicted_quality` is below the floor is dropped. Both exclusions are recorded with a human-readable
   `excluded_reason`, visible via the API.

5. **Score the survivors**:

   ```
   routing_score = quality_weight   * predicted_quality
                  - cost_weight      * normalized_cost
                  - latency_weight   * normalized_latency
                  - risk_weight      * risk
   ```

   `normalized_cost`/`normalized_latency` are **min-max normalized** across
   the full candidate set (`(value - min) / (max - min)`), not divided by
   the max alone. This matters: dividing by the max compresses every
   non-outlier candidate's normalized value toward zero whenever one
   candidate (e.g. a frontier model) is priced far above the rest —
   which washed out the cost signal enough in early testing that a
   `simple` classification task still routed to the priciest model. Default
   weights are `quality=0.35, cost=0.35, latency=0.15, risk=0.15` (must sum
   to 1.0, validated at settings load).

6. **Pick the max score**, build a fallback chain from the remaining
   eligible candidates ranked by score, and persist the full decision:
   selected model, human-readable reason, every candidate's score/
   quality/cost/latency/risk/exclusion status, task complexity, and risk
   level.

## Predicted quality: prior blended with observed history

[`routing/stats.py`](../src/sentinellm/routing/stats.py)'s
`DBModelStatsProvider` queries the most recent 200 traces for a model. With
fewer than 5 evaluated samples, `predicted_quality` is just the static
catalog prior (`ModelProfile.quality_tier`). Past that, it blends observed
average `overall_quality` with the prior, with the blend weight increasing
toward "fully trust observed data" as the sample count grows (capped at
`sample_count / 20`). A model whose observed success rate drops below 85%
is marked `degraded` (risk penalty ×1.5); below 50%, `down` (excluded
outright).

## Fallback + resilience

Once the router picks a chain, actual execution goes through
[`llm/resilient.py`](../src/sentinellm/llm/resilient.py)'s
`ResilientLLMClient`: each model in the chain gets up to
`max_retries_per_model` attempts (default 2) with exponential backoff +
full jitter between them, then execution moves to the *next model*, not
another retry of the same one — spreading load away from a struggling
backend instead of hammering it harder (this is the retry-storm mitigation
called for in section 10 of the spec). A `CONTEXT_OVERFLOW` error never
retries (it's not going to fix itself) and moves straight to the next
model. See `tests/unit/test_llm_resilient.py` for the full matrix (timeout
→ fallback succeeds, context overflow → no retry, all models exhausted →
`AllModelsFailedError`).

## Worked example (from the seeded demo data)

A simple question ("What time is it?"-equivalent) with the default
catalog (nano/flash/pro/opus quality tiers 0.55/0.72/0.90/0.97):

- Floor = 0.0 (simple task) → all four candidates eligible.
- `sentinel-flash`'s blend of moderate quality with low normalized cost/
  latency (both near the low end of the candidate range) usually wins over
  `sentinel-pro`'s higher quality but proportionally higher cost/latency.
- A complex reasoning prompt raises the floor to 0.80, excluding nano and
  flash outright — `sentinel-pro` or `sentinel-opus` wins by construction,
  not by tuning luck.

Reproduce this yourself: `curl -X POST /api/v1/generate` with a short vs.
long/complex `question` and compare `routing_decision.reason` in the
response (see [README API examples](../README.md#api-examples)).
