"""Intelligent model router.

routing_score = quality_weight * predicted_quality
              - cost_weight    * normalized_cost
              - latency_weight * normalized_latency
              - risk_weight    * risk

Candidates whose provider health is "down" are excluded outright (provider
outage -> automatic fallback to a healthy candidate). Candidates below the
task's quality floor (raised for complex or high-risk requests) are excluded
before scoring, which is what makes "complex reasoning -> a stronger model"
and "high-risk request -> a high-quality model" actual guarantees rather than
soft preferences the weights might not produce.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinellm.routing.complexity import (
    TaskComplexity,
    assess_risk,
    classify_complexity,
    quality_floor_for,
)
from sentinellm.routing.stats import ModelStats, ModelStatsProvider


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    model_id: str
    input_price_per_1k: float
    output_price_per_1k: float
    context_window: int


@dataclass(frozen=True, slots=True)
class RoutingCandidateResult:
    model: str
    routing_score: float
    predicted_quality: float
    normalized_cost: float
    normalized_latency: float
    risk: float
    excluded_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RoutingResult:
    selected_model: str
    reason: str
    task_complexity: TaskComplexity
    risk_level: str
    candidates: list[RoutingCandidateResult] = field(default_factory=list)


# Words → tokens. Deliberately on the generous side: this only has to keep a
# request away from a window it clearly cannot fit, not predict a tokenizer.
_TOKENS_PER_WORD = 1.4


class NoHealthyCandidateError(Exception):
    pass


class Router:
    def __init__(
        self,
        candidates: list[ModelCandidate],
        stats_provider: ModelStatsProvider,
        *,
        quality_weight: float,
        cost_weight: float,
        latency_weight: float,
        risk_weight: float,
    ) -> None:
        self._candidates = candidates
        self._stats_provider = stats_provider
        self._weights = {
            "quality": quality_weight,
            "cost": cost_weight,
            "latency": latency_weight,
            "risk": risk_weight,
        }

    async def route(
        self, prompt: str, *, context_length: int = 0, metadata: dict | None = None
    ) -> RoutingResult:
        complexity = classify_complexity(prompt, context_length)
        risk = assess_risk(prompt, metadata)
        quality_floor = quality_floor_for(complexity)
        if risk >= 0.8:
            quality_floor = max(quality_floor, 0.85)

        estimated_tokens = int((len(prompt.split()) + context_length) * _TOKENS_PER_WORD)

        stats_by_model: dict[str, ModelStats] = {
            c.model_id: await self._stats_provider.get_stats(c.model_id) for c in self._candidates
        }

        blended_costs = [
            (c.input_price_per_1k + c.output_price_per_1k) / 2 for c in self._candidates
        ]
        min_cost, max_cost = min(blended_costs), max(blended_costs)
        cost_range = (max_cost - min_cost) or 1.0

        latencies = [s.avg_latency_ms for s in stats_by_model.values()]
        min_latency, max_latency = min(latencies, default=0.0), max(latencies, default=1.0)
        latency_range = (max_latency - min_latency) or 1.0

        results: list[RoutingCandidateResult] = []
        for candidate in self._candidates:
            stats = stats_by_model[candidate.model_id]
            blended_cost = (candidate.input_price_per_1k + candidate.output_price_per_1k) / 2
            # Min-max (not divide-by-max) normalization: dividing by the max
            # alone compresses every non-outlier candidate toward 0, which
            # washes out the cost signal whenever one candidate (e.g. a
            # frontier model) is priced far above the rest.
            normalized_cost = (blended_cost - min_cost) / cost_range
            normalized_latency = (stats.avg_latency_ms - min_latency) / latency_range
            candidate_risk = risk * (1.5 if stats.status == "degraded" else 1.0)
            candidate_risk = min(1.0, candidate_risk)

            if stats.status == "down":
                results.append(
                    RoutingCandidateResult(
                        candidate.model_id,
                        -1.0,
                        stats.predicted_quality,
                        normalized_cost,
                        normalized_latency,
                        candidate_risk,
                        excluded_reason="provider outage",
                    )
                )
                continue
            if estimated_tokens > candidate.context_window:
                results.append(
                    RoutingCandidateResult(
                        candidate.model_id,
                        -1.0,
                        stats.predicted_quality,
                        normalized_cost,
                        normalized_latency,
                        candidate_risk,
                        excluded_reason=(
                            f"request (~{estimated_tokens} tokens) exceeds the model's "
                            f"{candidate.context_window}-token context window"
                        ),
                    )
                )
                continue
            if stats.predicted_quality < quality_floor:
                results.append(
                    RoutingCandidateResult(
                        candidate.model_id,
                        -1.0,
                        stats.predicted_quality,
                        normalized_cost,
                        normalized_latency,
                        candidate_risk,
                        excluded_reason=f"below quality floor {quality_floor:.2f} for {complexity.value} task",
                    )
                )
                continue

            score = (
                self._weights["quality"] * stats.predicted_quality
                - self._weights["cost"] * normalized_cost
                - self._weights["latency"] * normalized_latency
                - self._weights["risk"] * candidate_risk
            )
            results.append(
                RoutingCandidateResult(
                    candidate.model_id,
                    round(score, 4),
                    stats.predicted_quality,
                    round(normalized_cost, 4),
                    round(normalized_latency, 4),
                    round(candidate_risk, 4),
                )
            )

        eligible = [r for r in results if r.excluded_reason is None]
        if not eligible:
            raise NoHealthyCandidateError("no candidate model passed health/quality gating")

        winner = max(eligible, key=lambda r: r.routing_score)
        runner_up = sorted(
            (r for r in eligible if r.model != winner.model), key=lambda r: -r.routing_score
        )
        runner_up_note = ""
        if runner_up:
            ru = runner_up[0]
            runner_up_note = f"; runner-up {ru.model} scored {ru.routing_score:.3f}"

        reason = (
            f"complexity={complexity.value}, risk={risk:.2f} (floor={quality_floor:.2f}); "
            f"selected {winner.model} with routing_score={winner.routing_score:.3f} "
            f"(quality={winner.predicted_quality:.2f}, cost_norm={winner.normalized_cost:.2f}, "
            f"latency_norm={winner.normalized_latency:.2f}, risk={winner.risk:.2f}){runner_up_note}"
        )

        return RoutingResult(
            selected_model=winner.model,
            reason=reason,
            task_complexity=complexity,
            risk_level="high" if risk >= 0.8 else "medium" if risk >= 0.4 else "low",
            candidates=results,
        )
