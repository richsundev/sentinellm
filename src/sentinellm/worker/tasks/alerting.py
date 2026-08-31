"""Alert rule evaluation over a recent rolling window, with webhook
notification and dedup so a persistently-breached threshold doesn't spam a
new alert every poll cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.core.logging import get_logger
from sentinellm.db.models import Alert, Evaluation, Trace

logger = get_logger(__name__)

_WINDOW = timedelta(hours=1)
_DEDUPE_WINDOW = timedelta(hours=1)


async def _already_alerted(session: AsyncSession, rule: str) -> bool:
    stmt = select(Alert).where(
        Alert.rule == rule, Alert.timestamp >= datetime.now(UTC) - _DEDUPE_WINDOW
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _fire(
    session: AsyncSession,
    rule: str,
    current: float,
    threshold: float,
    severity: str,
    service: str,
    model: str | None,
) -> Alert:
    alert = Alert(
        rule=rule,
        current_value=round(current, 4),
        threshold=threshold,
        severity=severity,
        affected_service=service,
        affected_model=model,
    )
    session.add(alert)
    await session.flush()

    settings = get_settings()
    if settings.alert_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    settings.alert_webhook_url,
                    json={
                        "rule": rule,
                        "current_value": current,
                        "threshold": threshold,
                        "severity": severity,
                        "affected_service": service,
                        "affected_model": model,
                    },
                )
        except httpx.HTTPError:
            logger.warning("alert_webhook_delivery_failed", rule=rule)
    return alert


async def evaluate_alert_rules(session: AsyncSession) -> list[Alert]:
    settings = get_settings()
    since = datetime.now(UTC) - _WINDOW
    traces = (await session.execute(select(Trace).where(Trace.created_at >= since))).scalars().all()
    fired: list[Alert] = []
    if not traces:
        return fired

    error_rate = sum(1 for t in traces if t.status == "error") / len(traces)
    if error_rate > settings.error_rate_threshold and not await _already_alerted(
        session, "error_rate"
    ):
        fired.append(
            await _fire(
                session,
                "error_rate",
                error_rate,
                settings.error_rate_threshold,
                "high",
                "sentinel-api",
                None,
            )
        )

    latencies = sorted(t.latency_ms for t in traces)
    p95 = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
    if p95 > settings.p95_latency_threshold_ms and not await _already_alerted(
        session, "p95_latency"
    ):
        fired.append(
            await _fire(
                session,
                "p95_latency",
                p95,
                settings.p95_latency_threshold_ms,
                "medium",
                "sentinel-api",
                None,
            )
        )

    daily_cost = sum(t.estimated_cost for t in traces)
    if daily_cost > settings.daily_cost_budget and not await _already_alerted(
        session, "daily_cost"
    ):
        fired.append(
            await _fire(
                session,
                "daily_cost",
                daily_cost,
                settings.daily_cost_budget,
                "medium",
                "sentinel-router",
                None,
            )
        )

    trace_ids = [t.id for t in traces]
    evaluations = (
        (await session.execute(select(Evaluation).where(Evaluation.trace_id.in_(trace_ids))))
        .scalars()
        .all()
    )
    if evaluations:
        avg_quality = sum(e.overall_quality for e in evaluations) / len(evaluations)
        if avg_quality < settings.quality_score_threshold and not await _already_alerted(
            session, "quality_score"
        ):
            fired.append(
                await _fire(
                    session,
                    "quality_score",
                    avg_quality,
                    settings.quality_score_threshold,
                    "high",
                    "sentinel-evaluator",
                    None,
                )
            )

        avg_hallucination = sum(e.hallucination_score for e in evaluations) / len(evaluations)
        if avg_hallucination > settings.hallucination_rate_threshold and not await _already_alerted(
            session, "hallucination_rate"
        ):
            fired.append(
                await _fire(
                    session,
                    "hallucination_rate",
                    avg_hallucination,
                    settings.hallucination_rate_threshold,
                    "critical",
                    "sentinel-evaluator",
                    None,
                )
            )

    if fired:
        await session.commit()
    return fired
