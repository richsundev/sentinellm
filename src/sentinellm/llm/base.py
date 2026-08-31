"""Provider-agnostic LLM interface.

Every model call in the platform — including the LLM-as-judge evaluator and
the demo seed generator — goes through this interface. No calling code ever
imports `openai` or `anthropic` directly; that keeps the platform runnable
with zero API keys (MockProvider) and makes adding a new provider a matter of
implementing one class, not touching call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class LLMErrorKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    PROVIDER_ERROR = "provider_error"
    MALFORMED_RESPONSE = "malformed_response"
    CONTEXT_OVERFLOW = "context_overflow"


class ProviderError(Exception):
    """Raised by an LLMProvider when a call fails in a classifiable way."""

    def __init__(self, kind: LLMErrorKind, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str = "provider request timed out") -> None:
        super().__init__(LLMErrorKind.TIMEOUT, message, retryable=True)


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    model: str
    messages: list[LLMMessage]
    max_tokens: int = 512
    temperature: float = 0.2
    timeout_s: float = 30.0
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    finish_reason: str = "stop"


class LLMProvider(ABC):
    """Abstract base for a chat-completion capable model provider."""

    name: str

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    def supports_model(self, model: str) -> bool: ...
