"""The guard-rail decision shared by every progressive rollout (models, prompts).

Given the challenger's and the incumbent's traffic over the same evidence
window, decide whether the challenger has broken a guard rail. What a rollout
*does* with the answer (step traffic up, promote, roll back, alert) stays with
the caller; this is only the judgment, so a model canary and a prompt canary
can't drift apart in how strict they are.

Gates, in order: challenger error rate over `max_error_rate` → challenger
quality under the absolute `quality_floor` → challenger quality more than
`max_quality_regression` below the *incumbent's own* quality over the same
window. The quality gates only apply once an arm has `min_sample_size`
*evaluated* traces — with less, the pass judges on error rate alone rather
than acting on one or two noisy scores — and the relative gate additionally
needs the incumbent to have that much evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from sentinellm.services.rollouts import ArmWindow


@dataclass(frozen=True, slots=True)
class Guards:
    quality_floor: float
    max_quality_regression: float
    max_error_rate: float
    min_sample_size: int


@dataclass(frozen=True, slots=True)
class Violation:
    reason: str
    current: float
    threshold: float


@dataclass(frozen=True, slots=True)
class Verdict:
    violation: Violation | None
    requests: int
    error_rate: float
    # None until the challenger has `min_sample_size` evaluated traces.
    challenger_quality: float | None

    def evidence(self) -> str:
        quality = (
            f", avg_quality={self.challenger_quality:.2f}"
            if self.challenger_quality is not None
            else ""
        )
        return (
            f"{self.requests} healthy challenger requests "
            f"(error_rate={self.error_rate:.0%}{quality})"
        )


def judge_challenger(challenger: ArmWindow, incumbent: ArmWindow, guards: Guards) -> Verdict:
    n = challenger.request_count
    error_rate = challenger.error_rate
    challenger_quality = (
        challenger.avg_quality if challenger.evaluated_count >= guards.min_sample_size else None
    )
    incumbent_quality = (
        incumbent.avg_quality if incumbent.evaluated_count >= guards.min_sample_size else None
    )

    violation: Violation | None = None
    if error_rate > guards.max_error_rate:
        violation = Violation(
            f"challenger error_rate={error_rate:.0%} over {n} requests "
            f"(max {guards.max_error_rate:.0%})",
            error_rate,
            guards.max_error_rate,
        )
    elif challenger_quality is not None and challenger_quality < guards.quality_floor:
        violation = Violation(
            f"challenger avg_quality={challenger_quality:.2f} over {n} requests "
            f"(floor {guards.quality_floor:.2f})",
            challenger_quality,
            guards.quality_floor,
        )
    elif (
        challenger_quality is not None
        and incumbent_quality is not None
        and challenger_quality < incumbent_quality - guards.max_quality_regression
    ):
        violation = Violation(
            f"challenger avg_quality={challenger_quality:.2f} regressed more than "
            f"{guards.max_quality_regression:.2f} below the incumbent's "
            f"{incumbent_quality:.2f} over the same window",
            challenger_quality,
            incumbent_quality - guards.max_quality_regression,
        )
    return Verdict(violation, n, error_rate, challenger_quality)


def next_traffic(current: float, step: float, ceiling: float) -> tuple[float, bool]:
    """(new traffic %, whether it reached the ceiling and should be promoted)."""
    new = min(ceiling, current + step)
    return new, new >= ceiling
