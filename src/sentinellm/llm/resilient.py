"""Resilient LLM execution: bounded retries with exponential backoff + jitter
per model, then fallback to the next model in the chain.

Design: a *retry storm* happens when every failed request immediately retries
the same overloaded backend, amplifying the outage. We cap retries per model
(default 2 attempts), back off exponentially with jitter between them, and
escalate to a different model (not just a retry) after a model's budget is
exhausted — spreading load away from the failing backend instead of hammering
it harder.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from sentinellm.core.logging import get_logger
from sentinellm.llm.base import (
    LLMErrorKind,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class FallbackAttempt:
    model: str
    error_kind: str | None
    error_message: str | None
    succeeded: bool
    attempts: int


@dataclass(slots=True)
class ResilientResult:
    response: LLMResponse
    model_used: str
    attempts_log: list[FallbackAttempt]


class AllModelsFailedError(Exception):
    def __init__(self, attempts_log: list[FallbackAttempt]) -> None:
        self.attempts_log = attempts_log
        super().__init__(f"All {len(attempts_log)} model(s) in fallback chain failed")


class ResilientLLMClient:
    """Executes a request against a primary model with automatic fallback."""

    def __init__(
        self,
        provider_resolver,
        *,
        max_retries_per_model: int = 2,
        base_backoff_s: float = 0.2,
        max_backoff_s: float = 4.0,
    ) -> None:
        self._resolve = provider_resolver
        self._max_retries = max_retries_per_model
        self._base_backoff_s = base_backoff_s
        self._max_backoff_s = max_backoff_s

    async def complete_with_fallback(
        self, request: LLMRequest, fallback_models: list[str]
    ) -> ResilientResult:
        chain = [request.model, *[m for m in fallback_models if m != request.model]]
        attempts_log: list[FallbackAttempt] = []

        for model in chain:
            provider: LLMProvider = self._resolve(model)
            model_request = LLMRequest(
                model=model,
                messages=request.messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                timeout_s=request.timeout_s,
                metadata=request.metadata,
            )
            outcome = await self._complete_with_retry(provider, model_request)
            attempts_log.append(outcome[1])
            if outcome[0] is not None:
                return ResilientResult(
                    response=outcome[0], model_used=model, attempts_log=attempts_log
                )

        raise AllModelsFailedError(attempts_log)

    async def _complete_with_retry(
        self, provider: LLMProvider, request: LLMRequest
    ) -> tuple[LLMResponse | None, FallbackAttempt]:
        last_error: ProviderError | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await provider.complete(request)
                return response, FallbackAttempt(
                    model=request.model,
                    error_kind=None,
                    error_message=None,
                    succeeded=True,
                    attempts=attempt,
                )
            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "llm_call_failed",
                    model=request.model,
                    kind=exc.kind.value,
                    attempt=attempt,
                    retryable=exc.retryable,
                )
                if exc.kind == LLMErrorKind.CONTEXT_OVERFLOW or not exc.retryable:
                    break
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff_delay(attempt))

        assert last_error is not None
        return None, FallbackAttempt(
            model=request.model,
            error_kind=last_error.kind.value,
            error_message=str(last_error),
            succeeded=False,
            attempts=self._max_retries,
        )

    def _backoff_delay(self, attempt: int) -> float:
        exp = min(self._base_backoff_s * (2**attempt), self._max_backoff_s)
        return random.uniform(0, exp)
