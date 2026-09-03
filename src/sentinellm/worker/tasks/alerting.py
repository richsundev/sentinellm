"""Alert rule evaluation over a recent rolling window, with webhook
notification and dedup so a persistently-breached threshold doesn't spam a
new alert every poll cycle.

Rule *thresholds* are configurable at runtime (the `alert_rules` table,
editable from the Settings page / `PATCH /api/v1/alerts/rules/{rule}`)
rather than fixed at the env-var values in `Settings` — those env vars now
serve only as the seed value the first time a rule is created, via
`ensure_default_alert_rules`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.core.logging import get_logger
from sentinellm.db.models import Alert, AlertRuleConfig, Application, Evaluation, Trace

logger = get_logger(__name__)

_WINDOW = timedelta(hours=1)
_DEDUPE_WINDOW = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule: str
    default_threshold_attr: str
    severity: str
    service: str
    direction: str  # "above" | "below" — which side of the threshold fires
    description: str


RULE_DEFINITIONS: list[RuleDefinition] = [
    RuleDefinition(
        "error_rate",
        "error_rate_threshold",
        "high",
        "sentinel-api",
        "above",
        "Fraction of requests returning an error status in the trailing 1h window.",
    ),
    RuleDefinition(
        "p95_latency",
        "p95_latency_threshold_ms",
        "medium",
        "sentinel-api",
        "above",
        "P95 end-to-end request latency (ms) in the trailing 1h window.",
    ),
    RuleDefinition(
        "daily_cost",
        "daily_cost_budget",
        "medium",
        "sentinel-router",
        "above",
        "Total estimated LLM spend (USD) in the trailing 1h window.",
    ),
    RuleDefinition(
        "quality_score",
        "quality_score_threshold",
        "high",
        "sentinel-evaluator",
        "below",
        "Average overall_quality across evaluated traces in the trailing 1h window.",
    ),
    RuleDefinition(
        "hallucination_rate",
        "hallucination_rate_threshold",
        "critical",
        "sentinel-evaluator",
        "above",
        "Average hallucination_score across evaluated traces in the trailing 1h window.",
    ),
]
_DEFINITIONS_BY_RULE = {d.rule: d for d in RULE_DEFINITIONS}


async def ensure_default_alert_rules(session: AsyncSession) -> list[AlertRuleConfig]:
    """Idempotently creates any `AlertRuleConfig` row that doesn't exist yet,
    seeded from the current `Settings` values. Safe to call on every
    evaluation pass — a fresh install (or a freshly-added rule definition)
    gets sane defaults with zero manual setup, and existing operator-edited
    thresholds are never touched.
    """
    settings = get_settings()
    existing = {r.rule for r in (await session.execute(select(AlertRuleConfig))).scalars().all()}
    created: list[AlertRuleConfig] = []
    for definition in RULE_DEFINITIONS:
        if definition.rule in existing:
            continue
        row = AlertRuleConfig(
            rule=definition.rule,
            threshold=getattr(settings, definition.default_threshold_attr),
            severity=definition.severity,
            enabled=True,
            description=definition.description,
        )
        session.add(row)
        created.append(row)
    if created:
        await session.commit()
    return created


async def _already_alerted(
    session: AsyncSession, rule: str, affected_service: str | None = None
) -> bool:
    stmt = select(Alert).where(
        Alert.rule == rule, Alert.timestamp >= datetime.now(UTC) - _DEDUPE_WINDOW
    )
    if affected_service is not None:
        stmt = stmt.where(Alert.affected_service == affected_service)
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
    await ensure_default_alert_rules(session)
    rule_configs = {
        r.rule: r for r in (await session.execute(select(AlertRuleConfig))).scalars().all()
    }

    since = datetime.now(UTC) - _WINDOW
    traces = (await session.execute(select(Trace).where(Trace.created_at >= since))).scalars().all()
    fired: list[Alert] = []
    if not traces:
        return fired

    current_values: dict[str, float] = {
        "error_rate": sum(1 for t in traces if t.status == "error") / len(traces),
        "daily_cost": sum(t.estimated_cost for t in traces),
    }
    latencies = sorted(t.latency_ms for t in traces)
    current_values["p95_latency"] = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]

    trace_ids = [t.id for t in traces]
    evaluations = (
        (await session.execute(select(Evaluation).where(Evaluation.trace_id.in_(trace_ids))))
        .scalars()
        .all()
    )
    if evaluations:
        current_values["quality_score"] = sum(e.overall_quality for e in evaluations) / len(
            evaluations
        )
        current_values["hallucination_rate"] = sum(
            e.hallucination_score for e in evaluations
        ) / len(evaluations)

    for rule_name, current in current_values.items():
        config = rule_configs.get(rule_name)
        definition = _DEFINITIONS_BY_RULE[rule_name]
        if config is None or not config.enabled:
            continue

        breached = (
            current > config.threshold
            if definition.direction == "above"
            else current < config.threshold
        )
        if not breached or await _already_alerted(session, rule_name):
            continue

        fired.append(
            await _fire(
                session,
                rule_name,
                current,
                config.threshold,
                config.severity,
                definition.service,
                None,
            )
        )

    fired.extend(await _evaluate_application_budgets(session, traces))

    if fired:
        await session.commit()
    return fired


async def _evaluate_application_budgets(
    session: AsyncSession, traces: Sequence[Trace]
) -> list[Alert]:
    """Per-`Application.daily_cost_budget` overage check, over the same
    trailing window as `daily_cost` above. Separate from `RULE_DEFINITIONS`
    because the threshold is per-application rather than a single global
    value, so it can't live in the one-row-per-rule `alert_rules` table.
    Traces are matched against both `Application.id` and `Application.name`
    since `Trace.application_id` is a free-form string set by the caller
    (SDK examples use a human slug, the seed script uses the row's id) —
    not a declared foreign key.
    """
    budgeted_apps = (
        (
            await session.execute(
                select(Application).where(Application.daily_cost_budget.isnot(None))
            )
        )
        .scalars()
        .all()
    )
    if not budgeted_apps:
        return []

    cost_by_application_id: dict[str, float] = {}
    for t in traces:
        cost_by_application_id[t.application_id] = (
            cost_by_application_id.get(t.application_id, 0.0) + t.estimated_cost
        )

    fired: list[Alert] = []
    for app in budgeted_apps:
        budget = app.daily_cost_budget
        if budget is None:
            continue
        current = cost_by_application_id.get(app.id, 0.0) + cost_by_application_id.get(
            app.name, 0.0
        )
        affected_service = f"app:{app.name}"
        if current <= budget or await _already_alerted(
            session, "app_cost_budget", affected_service=affected_service
        ):
            continue
        fired.append(
            await _fire(
                session, "app_cost_budget", current, budget, "medium", affected_service, None
            )
        )
    return fired
