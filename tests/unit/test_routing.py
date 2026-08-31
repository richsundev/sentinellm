import pytest

from sentinellm.routing.complexity import TaskComplexity, assess_risk, classify_complexity
from sentinellm.routing.router import ModelCandidate, NoHealthyCandidateError, Router
from sentinellm.routing.stats import ModelStats, StaticModelStatsProvider

_CANDIDATES = [
    ModelCandidate("mock:sentinel-nano", 0.0001, 0.0002, 8_000),
    ModelCandidate("mock:sentinel-flash", 0.00015, 0.0006, 32_000),
    ModelCandidate("mock:sentinel-pro", 0.0025, 0.01, 128_000),
    ModelCandidate("mock:sentinel-opus", 0.015, 0.075, 200_000),
]


def _router() -> Router:
    return Router(
        _CANDIDATES,
        StaticModelStatsProvider(),
        quality_weight=0.45,
        cost_weight=0.25,
        latency_weight=0.15,
        risk_weight=0.15,
    )


def test_classify_complexity_simple_short_prompt() -> None:
    assert classify_complexity("What time is it?") == TaskComplexity.SIMPLE


def test_classify_complexity_complex_reasoning_prompt() -> None:
    prompt = (
        "Can you analyze the trade-offs between our current caching architecture and a "
        "distributed approach, explain the root cause of the latency regression we saw last "
        "week, and propose a step by step migration plan that accounts for backward compatibility?"
    )
    assert classify_complexity(prompt) == TaskComplexity.COMPLEX


def test_assess_risk_flags_high_risk_terms() -> None:
    assert assess_risk("What is the recommended dosage for this prescription medication?") >= 0.8
    assert assess_risk("What's your return policy?") < 0.5


@pytest.mark.asyncio
async def test_simple_task_routes_to_cheaper_model() -> None:
    result = await _router().route("What time is it?")
    assert result.selected_model in {"mock:sentinel-nano", "mock:sentinel-flash"}
    assert result.task_complexity == TaskComplexity.SIMPLE


@pytest.mark.asyncio
async def test_complex_task_routes_to_stronger_model() -> None:
    prompt = (
        "Analyze the trade-offs between our current caching architecture and a distributed "
        "approach, explain the root cause of the regression, and design a step by step migration "
        "plan with rollback considerations for the production database."
    )
    result = await _router().route(prompt)
    assert result.selected_model in {"mock:sentinel-pro", "mock:sentinel-opus"}


@pytest.mark.asyncio
async def test_high_risk_request_excludes_weak_models() -> None:
    result = await _router().route(
        "What is the correct prescription dosage for this medical condition?"
    )
    assert result.selected_model in {"mock:sentinel-pro", "mock:sentinel-opus"}
    excluded_weak = [c for c in result.candidates if c.model == "mock:sentinel-nano"]
    assert excluded_weak[0].excluded_reason is not None


@pytest.mark.asyncio
async def test_provider_outage_excludes_candidate_and_falls_back() -> None:
    class DownForNano:
        async def get_stats(self, model_id: str) -> ModelStats:
            if model_id == "mock:sentinel-nano":
                return ModelStats(
                    predicted_quality=0.55,
                    avg_latency_ms=280,
                    reliability=0.0,
                    sample_count=10,
                    status="down",
                )
            return await StaticModelStatsProvider().get_stats(model_id)

    router = Router(
        _CANDIDATES,
        DownForNano(),
        quality_weight=0.45,
        cost_weight=0.25,
        latency_weight=0.15,
        risk_weight=0.15,
    )
    result = await router.route("What time is it?")
    assert result.selected_model != "mock:sentinel-nano"
    nano_result = next(c for c in result.candidates if c.model == "mock:sentinel-nano")
    assert nano_result.excluded_reason == "provider outage"


@pytest.mark.asyncio
async def test_no_healthy_candidate_raises() -> None:
    class AllDown:
        async def get_stats(self, model_id: str) -> ModelStats:
            return ModelStats(
                predicted_quality=0.9,
                avg_latency_ms=100,
                reliability=0.0,
                sample_count=10,
                status="down",
            )

    router = Router(
        _CANDIDATES,
        AllDown(),
        quality_weight=0.45,
        cost_weight=0.25,
        latency_weight=0.15,
        risk_weight=0.15,
    )
    with pytest.raises(NoHealthyCandidateError):
        await router.route("hello")
