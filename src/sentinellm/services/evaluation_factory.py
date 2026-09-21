"""Builds the configured `EvaluationPipeline` from settings — the single
place that decides which embedding provider and judge model back the
pipeline, so the worker, the benchmark script, and tests all agree.
"""

from __future__ import annotations

from functools import lru_cache

from sentinellm.core.config import Settings, get_settings
from sentinellm.embeddings.factory import get_embedding_provider
from sentinellm.evaluation.pipeline import EvaluationPipeline
from sentinellm.llm.factory import get_provider_for_model

_DEFAULT_JUDGE_MODELS = {
    "mock": "mock:sentinel-judge",
    "openai": "openai:gpt-4o-mini",
    "anthropic": "anthropic:claude-haiku-4-5-20251001",
}


def resolve_judge_model(settings: Settings) -> str:
    """The judge is an ordinary model call, so it needs a real model id for
    whichever provider serves it — the old hard-coded `mock:sentinel-judge`
    was sent to OpenAI/Anthropic verbatim, failing every call."""
    return settings.judge_model or _DEFAULT_JUDGE_MODELS[settings.llm_provider]


@lru_cache
def get_evaluation_pipeline() -> EvaluationPipeline:
    settings = get_settings()
    embeddings = get_embedding_provider(settings.embedding_provider)
    judge_model = resolve_judge_model(settings)
    return EvaluationPipeline(
        embeddings=embeddings,
        judge_provider=get_provider_for_model(judge_model),
        judge_model=judge_model,
        run_judge=True,
    )
