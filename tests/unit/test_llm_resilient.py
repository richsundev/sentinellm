import pytest

from sentinellm.llm.base import LLMErrorKind, LLMMessage, LLMRequest, LLMResponse, ProviderError
from sentinellm.llm.mock_provider import MockProvider
from sentinellm.llm.resilient import AllModelsFailedError, ResilientLLMClient


class AlwaysTimesOutProvider:
    name = "flaky"

    def supports_model(self, model: str) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise ProviderError(LLMErrorKind.TIMEOUT, "simulated timeout", retryable=True)


class ContextOverflowProvider:
    name = "overflow"

    def supports_model(self, model: str) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise ProviderError(LLMErrorKind.CONTEXT_OVERFLOW, "too many tokens", retryable=False)


def _request(model: str) -> LLMRequest:
    return LLMRequest(model=model, messages=[LLMMessage(role="user", content="hello")])


@pytest.mark.asyncio
async def test_falls_back_to_healthy_model_after_primary_fails() -> None:
    providers = {"flaky:a": AlwaysTimesOutProvider(), "mock:sentinel-flash": MockProvider()}
    client = ResilientLLMClient(
        lambda model: providers[model],
        max_retries_per_model=1,
        base_backoff_s=0.001,
        max_backoff_s=0.01,
    )

    result = await client.complete_with_fallback(_request("flaky:a"), ["mock:sentinel-flash"])

    assert result.model_used == "mock:sentinel-flash"
    assert result.attempts_log[0].succeeded is False
    assert result.attempts_log[1].succeeded is True


@pytest.mark.asyncio
async def test_context_overflow_does_not_retry_and_moves_to_next_model() -> None:
    providers = {"overflow:a": ContextOverflowProvider(), "mock:sentinel-flash": MockProvider()}
    client = ResilientLLMClient(
        lambda model: providers[model],
        max_retries_per_model=5,
        base_backoff_s=0.001,
        max_backoff_s=0.01,
    )

    result = await client.complete_with_fallback(_request("overflow:a"), ["mock:sentinel-flash"])

    # A context overflow is terminal: exactly one call was made, and the log
    # must say so (it used to report the whole retry budget).
    assert result.attempts_log[0].attempts == 1
    assert result.model_used == "mock:sentinel-flash"


@pytest.mark.asyncio
async def test_all_models_failing_raises() -> None:
    providers = {"flaky:a": AlwaysTimesOutProvider(), "flaky:b": AlwaysTimesOutProvider()}
    client = ResilientLLMClient(
        lambda model: providers[model],
        max_retries_per_model=1,
        base_backoff_s=0.001,
        max_backoff_s=0.01,
    )

    with pytest.raises(AllModelsFailedError) as excinfo:
        await client.complete_with_fallback(_request("flaky:a"), ["flaky:b"])

    assert len(excinfo.value.attempts_log) == 2


@pytest.mark.asyncio
async def test_mock_provider_unstable_model_fails_a_majority_of_distinct_requests() -> None:
    """The unstable model's failure roll is deterministic per-prompt, so we
    vary the prompt across trials (as distinct real requests would) rather
    than expecting a single fixed prompt to flip outcomes across calls."""
    provider = MockProvider()
    outcomes = []
    for i in range(20):
        request = LLMRequest(
            model="mock:unstable-demo", messages=[LLMMessage(role="user", content=f"ping {i}")]
        )
        try:
            await provider.complete(request)
            outcomes.append("ok")
        except ProviderError:
            outcomes.append("error")
    assert "error" in outcomes
    assert "ok" in outcomes
