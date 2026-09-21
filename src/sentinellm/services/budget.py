"""Per-application daily cost budgets, enforced at admission.

`Application.daily_cost_budget` used to feed an alert and nothing else, so an
application could blow straight through it. With `budget_action` set to
`downgrade` or `block`, `/generate` checks the application's trailing-24h spend
(the same window the alert uses) before spending any more:

* `alert`     — nothing here; the worker's `app_cost_budget` alert is the only reaction.
* `downgrade` — the request is served from the cheapest healthy model instead.
* `block`     — the request is refused with a 402.

The check is deliberately *approximate*. It reads a database aggregate, cached
for `SENTINEL_BUDGET_CACHE_SECONDS` per replica, and requests already in flight
aren't counted — so an application can overshoot by whatever it spends in that
gap. That is the price of not summing a day of traces on every request; a hard
real-time cap would need a shared atomic counter (Redis) and a reservation
step, which nothing here needs yet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.db.models import Application, Trace

BUDGET_WINDOW = timedelta(hours=24)


def _money(amount: float) -> str:
    """Two decimals for ordinary amounts; enough significant digits that a tiny
    budget doesn't read as `$0.0000`."""
    return f"{amount:.2f}" if amount >= 0.01 else f"{amount:.6g}"


class BudgetExceededError(Exception):
    """The application's budget is spent and its action is `block` (a 402)."""

    def __init__(self, application: str, budget: float, spent: float) -> None:
        self.application, self.budget, self.spent = application, budget, spent
        super().__init__(
            f"application '{application}' has spent ${_money(spent)} of its ${_money(budget)} "
            "daily budget over the last 24 hours"
        )


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    application_id: str  # the Application row's id
    application_name: str
    budget: float | None
    action: str
    spent: float

    @property
    def exceeded(self) -> bool:
        # `>=`: a budget of 0 means "nothing may be spent", which `>` would
        # allow until the first cent had already gone.
        return self.budget is not None and self.spent >= self.budget

    @property
    def remaining(self) -> float | None:
        return None if self.budget is None else max(0.0, self.budget - self.spent)


@dataclass(frozen=True, slots=True)
class _Registration:
    application_id: str
    name: str
    budget: float | None
    action: str


# Per replica, and short-lived: see the module docstring.
_registrations: dict[str, tuple[float, _Registration | None]] = {}
_spend: dict[str, tuple[float, float]] = {}


def reset_budget_cache() -> None:
    _registrations.clear()
    _spend.clear()


async def _registration(session: AsyncSession, application: str) -> _Registration | None:
    ttl = get_settings().budget_cache_seconds
    now = time.monotonic()
    cached = _registrations.get(application)
    if ttl > 0 and cached is not None and cached[0] > now:
        return cached[1]
    row = (
        await session.execute(
            select(Application)
            .where(or_(Application.id == application, Application.name == application))
            .limit(1)
        )
    ).scalar_one_or_none()
    found = (
        None
        if row is None
        else _Registration(row.id, row.name, row.daily_cost_budget, row.budget_action)
    )
    if ttl > 0:
        _registrations[application] = (now + ttl, found)
    return found


async def spend_over_the_day(
    session: AsyncSession, application_id: str, application_name: str, *, use_cache: bool = True
) -> float:
    """Estimated cost recorded over the trailing 24h under the application's id or name."""
    ttl = get_settings().budget_cache_seconds
    now = time.monotonic()
    cached = _spend.get(application_id)
    if use_cache and ttl > 0 and cached is not None and cached[0] > now:
        return cached[1]
    since = datetime.now(UTC) - BUDGET_WINDOW
    spent = float(
        (
            await session.execute(
                select(func.coalesce(func.sum(Trace.estimated_cost), 0.0)).where(
                    Trace.application_id.in_({application_id, application_name}),
                    Trace.created_at >= since,
                )
            )
        ).scalar_one()
    )
    if ttl > 0:
        _spend[application_id] = (now + ttl, spent)
    return spent


async def enforced_budget(session: AsyncSession, application: str) -> BudgetStatus | None:
    """The application's budget status if — and only if — it has a budget that
    is enforced (`downgrade`/`block`). None means "nothing to enforce", and costs
    no spend query."""
    registration = await _registration(session, application)
    if registration is None or registration.budget is None or registration.action == "alert":
        return None
    spent = await spend_over_the_day(session, registration.application_id, registration.name)
    return BudgetStatus(
        registration.application_id,
        registration.name,
        registration.budget,
        registration.action,
        spent,
    )


async def live_budget_status(session: AsyncSession, application: Application) -> BudgetStatus:
    """The uncached status, for the status endpoint (any action)."""
    spent = await spend_over_the_day(session, application.id, application.name, use_cache=False)
    return BudgetStatus(
        application.id,
        application.name,
        application.daily_cost_budget,
        application.budget_action,
        spent,
    )
