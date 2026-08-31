from __future__ import annotations

from functools import lru_cache

from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider


@lru_cache
def get_embedding_provider(name: str = "mock") -> EmbeddingProvider:
    if name == "mock":
        return MockEmbeddingProvider()
    if name == "sentence-transformers":
        from sentinellm.embeddings.sentence_transformer_provider import (
            SentenceTransformerEmbeddingProvider,
        )

        return SentenceTransformerEmbeddingProvider()
    raise ValueError(f"Unknown embedding provider: {name}")
