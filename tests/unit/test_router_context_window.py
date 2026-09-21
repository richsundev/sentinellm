"""`ModelCandidate.context_window` was carried into the router and never read."""

from __future__ import annotations

import pytest

from sentinellm.routing.router import ModelCandidate, NoHealthyCandidateError, Router
from sentinellm.routing.stats import StaticModelStatsProvider

_SMALL = ModelCandidate("mock:sentinel-nano", 0.0001, 0.0002, 2_000)
_LARGE = ModelCandidate("mock:sentinel-pro", 0.0025, 0.01, 128_000)


def _router(*candidates: ModelCandidate) -> Router:
    return Router(
        list(candidates),
        StaticModelStatsProvider(),
        quality_weight=0.45,
        cost_weight=0.25,
        latency_weight=0.15,
        risk_weight=0.15,
    )


@pytest.mark.asyncio
async def test_a_model_whose_window_cannot_hold_the_request_is_not_chosen() -> None:
    # ~5,000 words of context cannot fit in a 2k-token window, however cheap it is.
    result = await _router(_SMALL, _LARGE).route("What time is it?", context_length=5_000)

    assert result.selected_model == "mock:sentinel-pro"
    excluded = {c.model: c.excluded_reason for c in result.candidates}
    assert "context window" in (excluded["mock:sentinel-nano"] or "")


@pytest.mark.asyncio
async def test_short_requests_still_use_the_small_window_model() -> None:
    result = await _router(_SMALL, _LARGE).route("What time is it?", context_length=50)

    assert result.selected_model == "mock:sentinel-nano"


@pytest.mark.asyncio
async def test_a_request_no_model_can_hold_is_unroutable() -> None:
    # Quality-wise eligible (a "pro" model), just with a window that is too small.
    tiny_pro = ModelCandidate("mock:sentinel-pro", 0.0025, 0.01, 2_000)
    with pytest.raises(NoHealthyCandidateError):
        await _router(tiny_pro).route("What time is it?", context_length=50_000)
