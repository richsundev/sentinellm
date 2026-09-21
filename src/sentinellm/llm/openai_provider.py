"""Thin OpenAI-compatible provider. Talks REST directly via httpx — no SDK
dependency — so it also works against any OpenAI-compatible gateway
(vLLM, LiteLLM, Azure OpenAI with a base_url override, etc).
"""

from __future__ import annotations

import time

import httpx

from sentinellm.llm.base import (
    LLMErrorKind,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def supports_model(self, model: str) -> bool:
        return model.startswith("openai:") or model.startswith("gpt-")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model_name = request.model.split(":", 1)[-1]
        payload = {
            "model": model_name,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(LLMErrorKind.TIMEOUT, str(exc), retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(LLMErrorKind.PROVIDER_ERROR, str(exc), retryable=True) from exc

        latency_ms = (time.perf_counter() - start) * 1000

        if resp.status_code == 429:
            raise ProviderError(LLMErrorKind.RATE_LIMIT, "rate limited by OpenAI", retryable=True)
        if resp.status_code == 400 and (
            "context_length" in resp.text or "maximum context length" in resp.text
        ):
            raise ProviderError(LLMErrorKind.CONTEXT_OVERFLOW, resp.text, retryable=False)
        if resp.status_code >= 400:
            # 408 (request timeout) and 409 (conflict) are transient; the rest
            # of the 4xx range is the caller's fault and retrying can't help.
            transient = resp.status_code >= 500 or resp.status_code in (408, 409)
            raise ProviderError(LLMErrorKind.PROVIDER_ERROR, resp.text, retryable=transient)

        try:
            data = resp.json()
            choice = data["choices"][0]
            # `content` is null for refusals / tool calls; downstream
            # evaluators assume a string.
            content = choice["message"]["content"] or ""
            usage = data.get("usage") or {}
            finish_reason = choice.get("finish_reason") or "stop"
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            raise ProviderError(LLMErrorKind.MALFORMED_RESPONSE, str(exc), retryable=True) from exc

        return LLMResponse(
            content=content,
            model=request.model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=round(latency_ms, 2),
            finish_reason=finish_reason,
        )
