"""Autonomous progressive-rollout evaluation for prompt versions.

The prompt-side twin of `worker.tasks.rollout`: same cadence, same evidence
window (`(last_decision, now - grace]`, the cursor moving only when a decision is
made, so a thin window keeps accumulating), and — through
`services.rollout_policy` — exactly the same guard rails. What differs is the
arms (two versions of one prompt, told apart by `Trace.prompt_version`) and the
extra gate that has no model equivalent: a challenger version that has since
been deprecated is rolled back at once, without waiting for evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.db.models import Alert, PromptRollout, PromptVersion
from sentinellm.observability.metrics import PROMPT_ROLLOUT_DECISIONS_TOTAL
from sentinellm.services.prompt_rollouts import load_prompt_arm_window
from sentinellm.services.rollout_policy import Guards, judge_challenger, next_traffic
from sentinellm.worker.tasks.alerting import publish_alert

logger = get_logger(__name__)

# Evaluations are produced asynchronously; the newest traces are still
# unevaluated, and "not evaluated *yet*" must not read as "no quality evidence".
_EVALUATION_GRACE = timedelta(seconds=15)


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes even for timezone-aware columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _rollback(rollout: PromptRollout, reason: str) -> None:
    rollout.stage = "rolled_back"
    rollout.traffic_pct = 0.0
    rollout.outcome_reason = reason
    logger.warning(
        "prompt_rollout_auto_rolled_back",
        rollout_id=rollout.id,
        application_id=rollout.application_id,
        prompt_id=rollout.prompt_id,
        challenger_version=rollout.challenger_version,
        reason=reason,
    )


async def _fire_rollback_alert(
    session: AsyncSession, rollout: PromptRollout, current: float, threshold: float
) -> None:
    alert = Alert(
        rule="prompt_rollout_auto_rollback",
        current_value=round(current, 4),
        threshold=round(threshold, 4),
        severity="high",
        affected_service=f"prompt-rollout:{rollout.application_id}"[:100],
        affected_model=f"{rollout.prompt_id}@v{rollout.challenger_version}"[:100],
    )
    session.add(alert)
    await session.flush()
    await publish_alert(alert)


async def evaluate_prompt_rollouts(session: AsyncSession) -> list[PromptRollout]:
    # Row-locked for the pass (see `worker.tasks.rollout`): an operator's action
    # on the same row either finishes first or waits for this commit.
    rollouts = (
        (
            await session.execute(
                select(PromptRollout)
                .where(PromptRollout.stage == "running")
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    changed: list[PromptRollout] = []
    decisions: list[str] = []

    for rollout in rollouts:
        now = datetime.now(UTC)

        challenger_row = (
            await session.execute(
                select(PromptVersion).where(
                    PromptVersion.prompt_id == rollout.prompt_id,
                    PromptVersion.version == rollout.challenger_version,
                )
            )
        ).scalar_one_or_none()
        if challenger_row is None or challenger_row.status == "deprecated":
            reason = f"challenger '{rollout.prompt_id}' v{rollout.challenger_version} " + (
                "no longer exists" if challenger_row is None else "was deprecated"
            )
            rollout.last_evaluated_at = now
            _rollback(rollout, reason)
            await _fire_rollback_alert(session, rollout, current=1.0, threshold=0.0)
            changed.append(rollout)
            decisions.append("rollback")
            continue

        since = _aware(rollout.last_evaluated_at or rollout.created_at)
        until = now - _EVALUATION_GRACE
        if until <= since:
            continue

        challenger = await load_prompt_arm_window(
            session,
            application_id=rollout.application_id,
            prompt_id=rollout.prompt_id,
            version=rollout.challenger_version,
            since=since,
            until=until,
        )
        if challenger.request_count < rollout.min_sample_size:
            # Not enough evidence yet — leave the cursor so these requests still
            # count toward the next pass.
            continue
        incumbent = await load_prompt_arm_window(
            session,
            application_id=rollout.application_id,
            prompt_id=rollout.prompt_id,
            version=rollout.incumbent_version,
            since=since,
            until=until,
        )

        verdict = judge_challenger(
            challenger,
            incumbent,
            Guards(
                quality_floor=rollout.quality_floor,
                max_quality_regression=rollout.max_quality_regression,
                max_error_rate=rollout.max_error_rate,
                min_sample_size=rollout.min_sample_size,
            ),
        )

        rollout.last_evaluated_at = until
        if verdict.violation is not None:
            _rollback(rollout, verdict.violation.reason)
            await _fire_rollback_alert(
                session,
                rollout,
                current=verdict.violation.current,
                threshold=verdict.violation.threshold,
            )
            decisions.append("rollback")
        else:
            rollout.traffic_pct, reached_ceiling = next_traffic(
                rollout.traffic_pct, rollout.step_pct, rollout.max_pct
            )
            evidence = verdict.evidence()
            if reached_ceiling:
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
            PROMPT_ROLLOUT_DECISIONS_TOTAL.labels(decision=decision).inc()
    return changed
