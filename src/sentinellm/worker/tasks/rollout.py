"""Autonomous progressive-rollout evaluation.

Runs on the same cadence as alerting/regression/model-health. For every
`ModelRollout` still in `stage="running"`, inspects the challenger's real
traffic (and both arms' model-health status) since the last decision and
either steps `traffic_pct` up, auto-promotes at `max_pct`, or auto-rolls-back
to 0% — the one place routing, live evaluation, model health, and alerting
all close the loop without an operator in it. See `db/models.ModelRollout`
for the full design rationale.

How a pass decides
------------------
* **Evidence window.** `(last_decision, now - grace]`. The cursor
  (`last_evaluated_at`) only moves when a decision is made, so a low-traffic
  rollout keeps accumulating challenger requests across passes until it has
  `min_sample_size` of them — it doesn't discard thin windows.
* **Grace period.** Evaluations are produced asynchronously by the worker
  queue, so the newest traces are still unevaluated. Excluding the last
  `_EVALUATION_GRACE` keeps "not evaluated *yet*" from being mistaken for
  "no quality evidence".
* **Gates, in order:** either arm's model flagged down (immediate, needs no
  evidence) → challenger error rate over `max_error_rate` → challenger
  quality under the absolute `quality_floor` → challenger quality more than
  `max_quality_regression` below the *incumbent's own* quality over the same
  window. The quality gates only apply once the arm has `min_sample_size`
  *evaluated* traces; with less, the pass judges on error rate alone rather
  than acting on one or two noisy scores. The relative gate additionally
  needs the incumbent to have that much evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.db.models import Alert, ModelPricing, ModelRollout
from sentinellm.observability.metrics import ROLLOUT_DECISIONS_TOTAL
from sentinellm.services.rollouts import load_arm_window
from sentinellm.worker.tasks.alerting import publish_alert

logger = get_logger(__name__)

_EVALUATION_GRACE = timedelta(seconds=15)


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes even for timezone-aware columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _rollback(rollout: ModelRollout, reason: str) -> None:
    rollout.stage = "rolled_back"
    rollout.traffic_pct = 0.0
    rollout.outcome_reason = reason
    logger.warning(
        "rollout_auto_rolled_back",
        rollout_id=rollout.id,
        application_id=rollout.application_id,
        challenger=rollout.challenger_model,
        reason=reason,
    )


async def _fire_rollback_alert(
    session: AsyncSession, rollout: ModelRollout, current: float, threshold: float
) -> None:
    alert = Alert(
        rule="rollout_auto_rollback",
        current_value=round(current, 4),
        threshold=round(threshold, 4),
        severity="high",
        affected_service=f"rollout:{rollout.application_id}",
        affected_model=rollout.challenger_model,
    )
    session.add(alert)
    await session.flush()
    await publish_alert(alert)


async def evaluate_rollouts(session: AsyncSession) -> list[ModelRollout]:
    # Row-locked for the pass: an operator's pause/promote/rollback on the
    # same row either finishes first (and this pass then sees the new stage)
    # or waits for this commit. `skip_locked` means a rollout an operator is
    # mid-way through changing is simply left to the next pass.
    rollouts = (
        (
            await session.execute(
                select(ModelRollout)
                .where(ModelRollout.stage == "running")
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    changed: list[ModelRollout] = []
    decisions: list[str] = []

    for rollout in rollouts:
        now = datetime.now(UTC)

        challenger_pricing = await session.get(ModelPricing, rollout.challenger_model)
        incumbent_pricing = await session.get(ModelPricing, rollout.incumbent_model)
        unhealthy_model = None
        if challenger_pricing is not None and challenger_pricing.status == "down":
            unhealthy_model = rollout.challenger_model
        elif incumbent_pricing is not None and incumbent_pricing.status == "down":
            unhealthy_model = rollout.incumbent_model

        if unhealthy_model is not None:
            rollout.last_evaluated_at = now
            _rollback(
                rollout, f"model '{unhealthy_model}' was auto-flagged down by the health monitor"
            )
            await _fire_rollback_alert(session, rollout, current=1.0, threshold=0.0)
            changed.append(rollout)
            decisions.append("rollback")
            continue

        since = _aware(rollout.last_evaluated_at or rollout.created_at)
        until = now - _EVALUATION_GRACE
        if until <= since:
            continue

        challenger = await load_arm_window(
            session,
            application_id=rollout.application_id,
            model=rollout.challenger_model,
            since=since,
            until=until,
        )
        if challenger.request_count < rollout.min_sample_size:
            # Not enough evidence yet — leave the cursor where it is so these
            # requests still count toward the next pass.
            continue

        incumbent = await load_arm_window(
            session,
            application_id=rollout.application_id,
            model=rollout.incumbent_model,
            since=since,
            until=until,
        )

        error_rate = challenger.error_rate
        challenger_quality = (
            challenger.avg_quality
            if challenger.evaluated_count >= rollout.min_sample_size
            else None
        )
        incumbent_quality = (
            incumbent.avg_quality if incumbent.evaluated_count >= rollout.min_sample_size else None
        )
        n = challenger.request_count

        rollback: tuple[str, float, float] | None = None
        if error_rate > rollout.max_error_rate:
            rollback = (
                f"challenger error_rate={error_rate:.0%} over {n} requests "
                f"(max {rollout.max_error_rate:.0%})",
                error_rate,
                rollout.max_error_rate,
            )
        elif challenger_quality is not None and challenger_quality < rollout.quality_floor:
            rollback = (
                f"challenger avg_quality={challenger_quality:.2f} over {n} requests "
                f"(floor {rollout.quality_floor:.2f})",
                challenger_quality,
                rollout.quality_floor,
            )
        elif (
            challenger_quality is not None
            and incumbent_quality is not None
            and challenger_quality < incumbent_quality - rollout.max_quality_regression
        ):
            allowed = incumbent_quality - rollout.max_quality_regression
            rollback = (
                f"challenger avg_quality={challenger_quality:.2f} regressed more than "
                f"{rollout.max_quality_regression:.2f} below the incumbent's "
                f"{incumbent_quality:.2f} over the same window",
                challenger_quality,
                allowed,
            )

        rollout.last_evaluated_at = until
        if rollback is not None:
            reason, current, threshold = rollback
            _rollback(rollout, reason)
            await _fire_rollback_alert(session, rollout, current=current, threshold=threshold)
            decisions.append("rollback")
        else:
            rollout.traffic_pct = min(rollout.max_pct, rollout.traffic_pct + rollout.step_pct)
            quality_note = (
                f", avg_quality={challenger_quality:.2f}" if challenger_quality is not None else ""
            )
            evidence = (
                f"{n} healthy challenger requests (error_rate={error_rate:.0%}{quality_note})"
            )
            if rollout.traffic_pct >= rollout.max_pct:
                rollout.stage = "promoted"
                rollout.outcome_reason = f"promoted to {rollout.traffic_pct:.0f}% after {evidence}"
                decisions.append("promote")
            else:
                rollout.outcome_reason = f"advanced to {rollout.traffic_pct:.0f}% after {evidence}"
                decisions.append("advance")

        changed.append(rollout)

    if changed:
        await session.commit()
        # Counted only once the decisions are durable.
        for decision in decisions:
            ROLLOUT_DECISIONS_TOTAL.labels(decision=decision).inc()
    return changed
