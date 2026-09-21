"""Thin Anthropic Messages API provider, implemented directly over httpx."""

from __future__ import annotations

import re
import time

import httpx

from sentinellm.llm.base import (
    LLMErrorKind,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
)

_ANTHROPIC_VERSION = "2023-06-01"
# Anthropic reports an over-long prompt as `prompt is too long: N tokens > M
# maximum`. (The old check matched any 400 mentioning `max_tokens`, which
# also caught plain request-configuration errors.)
_CONTEXT_OVERFLOW_RE = re.compile(r"prompt is too long|context (window|length)", re.IGNORECASE)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def supports_model(self, model: str) -> bool:
        return model.startswith("anthropic:") or model.startswith("claude-")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model_name = request.model.split(":", 1)[-1]
        system = "\n".join(m.content for m in request.messages if m.role == "system") or None
        turns = [
            {"role": m.role, "content": m.content} for m in request.messages if m.role != "system"
        ]

        payload: dict = {
            "model": model_name,
            "messages": turns,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if system:
            payload["system"] = system

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": _ANTHROPIC_VERSION,
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(LLMErrorKind.TIMEOUT, str(exc), retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(LLMErrorKind.PROVIDER_ERROR, str(exc), retryable=True) from exc

        latency_ms = (time.perf_counter() - start) * 1000

        if resp.status_code == 429:
            raise ProviderError(
                LLMErrorKind.RATE_LIMIT, "rate limited by Anthropic", retryable=True
            )
        if resp.status_code == 400 and _CONTEXT_OVERFLOW_RE.search(resp.text):
            raise ProviderError(LLMErrorKind.CONTEXT_OVERFLOW, resp.text, retryable=False)
        if resp.status_code >= 400:
            transient = resp.status_code >= 500 or resp.status_code in (408, 409)
            raise ProviderError(LLMErrorKind.PROVIDER_ERROR, resp.text, retryable=transient)

        try:
            data = resp.json()
            blocks = data.get("content") or []
            content = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            usage = data.get("usage") or {}
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ProviderError(LLMErrorKind.MALFORMED_RESPONSE, str(exc), retryable=True) from exc

        return LLMResponse(
            content=content,
            model=request.model,
            provider=self.name,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=round(latency_ms, 2),
        )
