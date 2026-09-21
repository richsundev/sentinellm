"""Periodic model-health check.

`ModelPricing.status` used to be a purely manual field — the router already
excludes `down` models from candidates (see `services/generation._load_candidates`),
but nothing ever set that status from real traffic, only a human `PATCH
/models/{id}`. This closes that gap: a model's trailing error rate over the
window below is used to flip it between healthy/degraded/down automatically.

A model a human has explicitly PATCHed keeps `status_auto=False` (set by
`routers/models.update_model` whenever `status` is part of the payload) and
is skipped here, so an operator's manual call is never silently overridden.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.db.models import ModelPricing, Trace
from sentinellm.observability.metrics import MODEL_STATUS_CHANGES_TOTAL

logger = get_logger(__name__)

_WINDOW = timedelta(hours=1)
_MIN_SAMPLE = 5
_DOWN_ERROR_RATE = 0.5
_DEGRADED_ERROR_RATE = 0.2


async def evaluate_model_health(session: AsyncSession) -> list[ModelPricing]:
    since = datetime.now(UTC) - _WINDOW
    traces = (await session.execute(select(Trace).where(Trace.created_at >= since))).scalars().all()
    if not traces:
        return []

    traces_by_model: dict[str, list[Trace]] = {}
    for t in traces:
        traces_by_model.setdefault(t.model, []).append(t)

    auto_managed = (
        (await session.execute(select(ModelPricing).where(ModelPricing.status_auto.is_(True))))
        .scalars()
        .all()
    )

    changed: list[ModelPricing] = []
    transitions: list[tuple[str, str]] = []
    for row in auto_managed:
        model_traces = traces_by_model.get(row.id)
        if model_traces is None or len(model_traces) < _MIN_SAMPLE:
            continue

        error_rate = sum(1 for t in model_traces if t.status == "error") / len(model_traces)
        if error_rate >= _DOWN_ERROR_RATE:
            new_status = "down"
        elif error_rate >= _DEGRADED_ERROR_RATE:
            new_status = "degraded"
        else:
            new_status = "healthy"
        reason = (
            f"error rate {error_rate:.0%} over last {len(model_traces)} requests "
            f"(trailing {int(_WINDOW.total_seconds() // 3600)}h)"
        )

        if row.status != new_status or row.status_reason != reason:
            if row.status != new_status:
                transitions.append((row.id, new_status))
            row.status = new_status
            row.status_reason = reason
            changed.append(row)

    if changed:
        await session.commit()
        # A refreshed reason on an unchanged status isn't a transition.
        for model_id, status in transitions:
            MODEL_STATUS_CHANGES_TOTAL.labels(model=model_id, status=status).inc()
    return changed
