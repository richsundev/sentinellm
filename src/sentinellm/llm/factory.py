"""Provider construction from settings/env — the one place that knows about
concrete provider classes and API keys.
"""

from __future__ import annotations

import os
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


def get_provider_for_model(model_id: str) -> LLMProvider:
    """Resolve a provider from a `provider:model` id, e.g. `mock:sentinel-pro`."""
    provider_name = model_id.split(":", 1)[0] if ":" in model_id else "mock"
    return get_provider(provider_name)
