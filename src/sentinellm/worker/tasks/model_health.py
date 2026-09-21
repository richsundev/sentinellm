"""Periodic model-health check.

`ModelPricing.status` used to be a purely manual field — the router already
excludes `down` models from candidates (see `services/generation._load_candidates`),
but nothing ever set that status from real traffic, only a human `PATCH
/models/{id}`. This closes that gap: a model's trailing error rate over the
window below is used to flip it between healthy/degraded/down automatically.

A model a human has explicitly PATCHed keeps `status_auto=False` (set by
`routers/models.update_model` whenever `status` is part of the payload) and
is skipped here, so an operator's manual call is never silently overridden.

Evidence for a model is the traces it served (cache hits excluded) plus the
attempts recorded in `trace_metadata["failed_attempts"]` — calls that failed
before a fallback answered. A model that is down and has no evidence left in
the window is moved back to `degraded` so it can be tried again.
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
_WINDOW_LABEL = f"{int(_WINDOW.total_seconds() // 3600)}h"


async def evaluate_model_health(session: AsyncSession) -> list[ModelPricing]:
    since = datetime.now(UTC) - _WINDOW
    rows = (
        await session.execute(
            select(Trace.model, Trace.status, Trace.cache_hit, Trace.trace_metadata).where(
                Trace.created_at >= since
            )
        )
    ).all()

    requests: dict[str, int] = {}
    errors: dict[str, int] = {}
    for model, status, cache_hit, metadata in rows:
        # A cache hit never called the model: it says nothing about its health.
        if not cache_hit:
            requests[model] = requests.get(model, 0) + 1
            if status == "error":
                errors[model] = errors.get(model, 0) + 1
        # Attempts that failed before a fallback model answered. The served
        # trace looks like a success for the *fallback*; without these a model
        # failing every call behind a working fallback is never flagged, and
        # keeps being tried (and retried) first.
        for attempt in (metadata or {}).get("failed_attempts", []):
            failed_model = attempt.get("model") if isinstance(attempt, dict) else None
            if failed_model:
                requests[failed_model] = requests.get(failed_model, 0) + 1
                errors[failed_model] = errors.get(failed_model, 0) + 1

    auto_managed = (
        (await session.execute(select(ModelPricing).where(ModelPricing.status_auto.is_(True))))
        .scalars()
        .all()
    )

    changed: list[ModelPricing] = []
    transitions: list[tuple[str, str]] = []
    for row in auto_managed:
        sample = requests.get(row.id, 0)
        if sample < _MIN_SAMPLE:
            if row.status == "down":
                # Half-open: a down model is excluded from routing, so it earns
                # no new traffic and its failures simply age out of the window.
                # With nothing left to judge it by it would stay down until an
                # operator noticed. Make it routable (degraded) again and let
                # fresh traffic decide.
                row.status = "degraded"
                row.status_reason = (
                    f"no evidence in the trailing {_WINDOW_LABEL}; retrying after being down"
                )
                changed.append(row)
                transitions.append((row.id, "degraded"))
            continue

        error_rate = errors.get(row.id, 0) / sample
        if error_rate >= _DOWN_ERROR_RATE:
            new_status = "down"
        elif error_rate >= _DEGRADED_ERROR_RATE:
            new_status = "degraded"
        else:
            new_status = "healthy"
        reason = (
            f"error rate {error_rate:.0%} over last {sample} requests (trailing {_WINDOW_LABEL})"
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
