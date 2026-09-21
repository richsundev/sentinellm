"""Provider construction from settings/env — the one place that knows about
concrete provider classes and API keys.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from sentinellm.llm.base import LLMProvider
from sentinellm.llm.mock_provider import MockProvider


@lru_cache
def get_provider(name: str) -> LLMProvider:
    if name == "mock":
        return MockProvider()
    if name == "openai":
        from sentinellm.llm.openai_provider import OpenAIProvider

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required to use the openai provider")
        return OpenAIProvider(api_key=api_key)
    if name == "anthropic":
        from sentinellm.llm.anthropic_provider import AnthropicProvider

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required to use the anthropic provider")
        return AnthropicProvider(api_key=api_key)
    raise ValueError(f"Unknown LLM provider: {name}")


_BARE_OPENAI_RE = re.compile(r"^(gpt-|chatgpt-|o[134](-|$))", re.IGNORECASE)
_BARE_ANTHROPIC_RE = re.compile(r"^claude-", re.IGNORECASE)


def provider_name_for_model(model_id: str) -> str:
    """The provider a model id belongs to: the `provider:` prefix if present,
    else inferred from the well-known bare names (`gpt-4o`, `claude-...`) the
    providers' own `supports_model` accepts. Anything else is the mock
    provider — which used to be the answer for *every* bare id, so
    `gpt-4o-mini` silently returned fabricated mock answers."""
    if ":" in model_id:
        return model_id.split(":", 1)[0]
    if _BARE_OPENAI_RE.match(model_id):
        return "openai"
    if _BARE_ANTHROPIC_RE.match(model_id):
        return "anthropic"
    return "mock"


def get_provider_for_model(model_id: str) -> LLMProvider:
    """Resolve a provider from a `provider:model` id, e.g. `mock:sentinel-pro`."""
    return get_provider(provider_name_for_model(model_id))
