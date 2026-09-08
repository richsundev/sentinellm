"""Autonomous progressive-rollout evaluation.

Runs on the same cadence as alerting/regression/model-health. For every
`ModelRollout` still in `stage="running"`, inspects the challenger's real
traffic (and both arms' model-health status) since the last pass and either
steps `traffic_pct` up, auto-promotes at `max_pct`, or auto-rolls-back to
0% — the one place routing, live evaluation, model health, and alerting
all close the loop without an operator in it. See `db/models.ModelRollout`
for the full design rationale.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.db.models import Alert, Evaluation, ModelPricing, ModelRollout, Trace
from sentinellm.worker.tasks.alerting import deliver_alert_webhook

logger = get_logger(__name__)


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
        threshold=threshold,
        severity="high",
        affected_service=f"rollout:{rollout.application_id}",
        affected_model=rollout.challenger_model,
    )
    session.add(alert)
    await session.flush()
    await deliver_alert_webhook(alert)


async def evaluate_rollouts(session: AsyncSession) -> list[ModelRollout]:
    rollouts = (
        (await session.execute(select(ModelRollout).where(ModelRollout.stage == "running")))
        .scalars()
        .all()
    )
    changed: list[ModelRollout] = []

    for rollout in rollouts:
        since = rollout.last_evaluated_at or rollout.created_at
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
            continue

        traces = (
            (
                await session.execute(
                    select(Trace).where(
                        Trace.application_id == rollout.application_id,
                        Trace.model == rollout.challenger_model,
                        Trace.created_at > since,
                    )
                )
            )
            .scalars()
            .all()
        )
        rollout.last_evaluated_at = now

        if len(traces) < rollout.min_sample_size:
            continue

        error_count = sum(1 for t in traces if t.status == "error")
        error_rate = error_count / len(traces)

        trace_ids = [t.id for t in traces]
        evaluations = (
            (await session.execute(select(Evaluation).where(Evaluation.trace_id.in_(trace_ids))))
            .scalars()
            .all()
        )
        avg_quality = (
            sum(e.overall_quality for e in evaluations) / len(evaluations) if evaluations else None
        )

        if error_rate > rollout.max_error_rate:
            _rollback(
                rollout,
                f"challenger error_rate={error_rate:.0%} over {len(traces)} requests "
                f"(max {rollout.max_error_rate:.0%})",
            )
            await _fire_rollback_alert(
                session, rollout, current=error_rate, threshold=rollout.max_error_rate
            )
        elif avg_quality is not None and avg_quality < rollout.quality_floor:
            _rollback(
                rollout,
                f"challenger avg_quality={avg_quality:.2f} over {len(traces)} requests "
                f"(floor {rollout.quality_floor:.2f})",
            )
            await _fire_rollback_alert(
                session, rollout, current=avg_quality, threshold=rollout.quality_floor
            )
        else:
            rollout.traffic_pct = min(rollout.max_pct, rollout.traffic_pct + rollout.step_pct)
            quality_note = f", avg_quality={avg_quality:.2f}" if avg_quality is not None else ""
            if rollout.traffic_pct >= rollout.max_pct:
                rollout.stage = "promoted"
                rollout.outcome_reason = (
                    f"promoted to {rollout.traffic_pct:.0f}% after {len(traces)} healthy "
                    f"challenger requests (error_rate={error_rate:.0%}{quality_note})"
                )
            else:
                rollout.outcome_reason = (
                    f"advanced to {rollout.traffic_pct:.0f}% after {len(traces)} healthy "
                    f"challenger requests (error_rate={error_rate:.0%}{quality_note})"
                )

        changed.append(rollout)

    if changed:
        await session.commit()
    return changed
