"""The LLM-as-judge used a hard-coded `mock:sentinel-judge` model even when
the platform was pointed at a real provider — it would send that name to
OpenAI/Anthropic, fail every call, and silently fall back to the heuristic
for every evaluation."""

import pytest

from sentinellm.core.config import Settings
from sentinellm.llm.mock_provider import MockProvider
from sentinellm.llm.openai_provider import OpenAIProvider
from sentinellm.services import evaluation_factory
from sentinellm.services.evaluation_factory import resolve_judge_model


@pytest.mark.parametrize(
    ("provider", "explicit", "expected"),
    [
        ("mock", None, "mock:sentinel-judge"),
        ("openai", None, "openai:gpt-4o-mini"),
        ("anthropic", None, "anthropic:claude-haiku-4-5-20251001"),
        ("openai", "openai:gpt-4.1", "openai:gpt-4.1"),
        ("mock", "anthropic:claude-x", "anthropic:claude-x"),
    ],
)
def test_judge_model_defaults_follow_the_configured_provider(provider, explicit, expected) -> None:
    settings = Settings(llm_provider=provider, judge_model=explicit)
    assert resolve_judge_model(settings) == expected


def test_default_pipeline_judges_with_the_mock_model_offline(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluation_factory, "get_settings", lambda: Settings(llm_provider="mock", judge_model=None)
    )
    evaluation_factory.get_evaluation_pipeline.cache_clear()
    try:
        pipeline = evaluation_factory.get_evaluation_pipeline()
        judge = pipeline._judge
        assert judge is not None
        assert judge._model == "mock:sentinel-judge"
        assert isinstance(judge._provider, MockProvider)
    finally:
        evaluation_factory.get_evaluation_pipeline.cache_clear()


def test_pipeline_judge_uses_the_provider_of_the_judge_model(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        evaluation_factory,
        "get_settings",
        lambda: Settings(llm_provider="openai", judge_model=None),
    )
    evaluation_factory.get_evaluation_pipeline.cache_clear()
    from sentinellm.llm.factory import get_provider

    get_provider.cache_clear()
    try:
        judge = evaluation_factory.get_evaluation_pipeline()._judge
        assert judge is not None
        assert judge._model == "openai:gpt-4o-mini"
        assert isinstance(judge._provider, OpenAIProvider)
    finally:
        evaluation_factory.get_evaluation_pipeline.cache_clear()
        get_provider.cache_clear()
