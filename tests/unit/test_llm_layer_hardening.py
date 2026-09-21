"""Regression tests for bugs found auditing the LLM layer: an unresolvable
provider used to crash the whole fallback chain instead of falling back,
attempt counts were misreported, provider error/response classification was
wrong, and bare model ids were silently routed to the mock provider."""

import httpx
import pytest
import respx

from sentinellm.llm.anthropic_provider import AnthropicProvider
from sentinellm.llm.base import LLMErrorKind, LLMMessage, LLMRequest, ProviderError
from sentinellm.llm.factory import get_provider_for_model, provider_name_for_model
from sentinellm.llm.mock_provider import MockProvider
from sentinellm.llm.openai_provider import OpenAIProvider
from sentinellm.llm.resilient import AllModelsFailedError, ResilientLLMClient


def _request(model: str = "mock:sentinel-flash") -> LLMRequest:
    return LLMRequest(model=model, messages=[LLMMessage(role="user", content="hello")])


# --- resilient client --------------------------------------------------------


@pytest.mark.asyncio
async def test_unresolvable_provider_falls_through_to_the_next_model() -> None:
    """A chain like [openai:gpt-4o (no API key), mock:...] must fall back, not
    crash with the RuntimeError the provider factory raised."""

    def resolve(model: str):
        if model.startswith("openai:"):
            raise RuntimeError("OPENAI_API_KEY is required to use the openai provider")
        return MockProvider()

    client = ResilientLLMClient(resolve, base_backoff_s=0.001)
    result = await client.complete_with_fallback(_request("openai:gpt-4o"), ["mock:sentinel-flash"])

    assert result.model_used == "mock:sentinel-flash"
    first = result.attempts_log[0]
    assert first.model == "openai:gpt-4o"
    assert first.succeeded is False
    assert first.error_kind == LLMErrorKind.PROVIDER_ERROR.value
    assert "OPENAI_API_KEY" in (first.error_message or "")


@pytest.mark.asyncio
async def test_unknown_provider_with_no_fallback_reports_a_failed_chain() -> None:
    def resolve(model: str):
        raise ValueError(f"Unknown LLM provider: {model}")

    client = ResilientLLMClient(resolve)
    with pytest.raises(AllModelsFailedError) as exc_info:
        await client.complete_with_fallback(_request("foo:bar"), [])

    assert exc_info.value.attempts_log[0].error_kind == LLMErrorKind.PROVIDER_ERROR.value


class _NonRetryableProvider:
    name = "x"

    def supports_model(self, model: str) -> bool:
        return True

    async def complete(self, request: LLMRequest):
        raise ProviderError(LLMErrorKind.PROVIDER_ERROR, "bad request", retryable=False)


@pytest.mark.asyncio
async def test_attempt_count_reflects_calls_actually_made() -> None:
    """A non-retryable error stops after one call; the log used to claim
    `max_retries` attempts regardless."""
    client = ResilientLLMClient(lambda m: _NonRetryableProvider(), max_retries_per_model=3)
    with pytest.raises(AllModelsFailedError) as exc_info:
        await client.complete_with_fallback(_request(), [])

    assert exc_info.value.attempts_log[0].attempts == 1


@pytest.mark.asyncio
async def test_zero_retry_budget_still_makes_one_attempt() -> None:
    """`max_retries_per_model=0` used to skip the loop and trip an assert."""
    client = ResilientLLMClient(lambda m: MockProvider(), max_retries_per_model=0)
    result = await client.complete_with_fallback(_request(), [])
    assert result.attempts_log[0].attempts == 1


# --- provider response handling ------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_prompt_too_long_is_classified_as_context_overflow() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            400,
            json={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "prompt is too long: 250000 tokens > 200000 maximum",
                },
            },
        )
    )
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicProvider("k").complete(_request("anthropic:claude-x"))

    assert exc_info.value.kind == LLMErrorKind.CONTEXT_OVERFLOW
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_max_tokens_config_error_is_not_context_overflow() -> None:
    """The old check matched any 400 mentioning `max_tokens`."""
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(400, json={"error": {"message": "max_tokens: Field required"}})
    )
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicProvider("k").complete(_request("anthropic:claude-x"))

    assert exc_info.value.kind == LLMErrorKind.PROVIDER_ERROR


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("body", [[], None, "text", 42])
async def test_anthropic_non_object_json_is_a_malformed_response_not_a_crash(body) -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=body)
    )
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicProvider("k").complete(_request("anthropic:claude-x"))

    assert exc_info.value.kind == LLMErrorKind.MALFORMED_RESPONSE


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_null_usage_is_tolerated() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, json={"content": [{"type": "text", "text": "hi"}], "usage": None}
        )
    )
    response = await AnthropicProvider("k").complete(_request("anthropic:claude-x"))
    assert response.content == "hi"
    assert response.input_tokens == 0


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("body", [[], None, "text", {"choices": None}, {"choices": ["x"]}])
async def test_openai_unexpected_json_is_a_malformed_response_not_a_crash(body) -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=body)
    )
    with pytest.raises(ProviderError) as exc_info:
        await OpenAIProvider("k").complete(_request("openai:gpt-4o"))

    assert exc_info.value.kind == LLMErrorKind.MALFORMED_RESPONSE


@pytest.mark.asyncio
@respx.mock
async def test_openai_null_content_and_null_usage_are_tolerated() -> None:
    """`content: null` happens on refusals / tool calls; it used to flow
    through as None and crash the evaluators downstream."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": None}, "finish_reason": "content_filter"}],
                "usage": None,
            },
        )
    )
    response = await OpenAIProvider("k").complete(_request("openai:gpt-4o"))
    assert response.content == ""
    assert response.output_tokens == 0


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [408, 409])
async def test_transient_4xx_statuses_are_retryable(status) -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(status, text="try again")
    )
    with pytest.raises(ProviderError) as exc_info:
        await OpenAIProvider("k").complete(_request("openai:gpt-4o"))
    assert exc_info.value.retryable is True


# --- provider resolution --------------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("mock:sentinel-pro", "mock"),
        ("openai:gpt-4o", "openai"),
        ("anthropic:claude-x", "anthropic"),
        ("gpt-4o-mini", "openai"),
        ("o3-mini", "openai"),
        ("claude-haiku-4-5", "anthropic"),
        ("sentinel-flash", "mock"),
    ],
)
def test_provider_is_inferred_from_bare_model_ids(model_id: str, expected: str) -> None:
    """`gpt-4o` used to be routed to the mock provider, returning fake answers
    while the provider's own supports_model() claimed the id."""
    assert provider_name_for_model(model_id) == expected


def test_bare_openai_id_resolves_to_the_openai_provider(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_provider_for_model.__globals__["get_provider"].cache_clear()
    try:
        assert isinstance(get_provider_for_model("gpt-4o-mini"), OpenAIProvider)
    finally:
        get_provider_for_model.__globals__["get_provider"].cache_clear()
