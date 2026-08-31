"""Builds the configured `EvaluationPipeline` from settings — the single
place that decides which embedding provider and judge model back the
pipeline, so the worker, the benchmark script, and tests all agree.
"""

from __future__ import annotations

from functools import lru_cache

from sentinellm.core.config import get_settings
from sentinellm.embeddings.factory import get_embedding_provider
from sentinellm.evaluation.pipeline import EvaluationPipeline
from sentinellm.llm.factory import get_provider


@lru_cache
def get_evaluation_pipeline() -> EvaluationPipeline:
    settings = get_settings()
    embeddings = get_embedding_provider(settings.embedding_provider)
    judge_provider = get_provider(settings.llm_provider)
    return EvaluationPipeline(embeddings=embeddings, judge_provider=judge_provider, run_judge=True)
