"""Deterministic local embedding provider using feature hashing.

Real sentence embeddings require a downloaded model, which breaks the
"zero setup, zero API keys" demo promise. Feature hashing (the "hashing
trick") over lowercased tokens is a legitimate, decades-old technique that
still produces vectors where lexically-similar text lands close together —
enough to demonstrate semantic caching and retrieval-relevance scoring
offline. `SentenceTransformerEmbeddingProvider` is the drop-in production
upgrade path (see factory.py).
"""

from __future__ import annotations

import hashlib
import math
import re

from sentinellm.embeddings.base import EmbeddingProvider

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DIMENSIONS = 256


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _bucket(token: str, dimensions: int) -> int:
    digest = hashlib.md5(token.encode(), usedforsecurity=False).hexdigest()
    return int(digest[:8], 16) % dimensions


class MockEmbeddingProvider(EmbeddingProvider):
    name = "mock"
    dimensions = _DIMENSIONS

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            idx = _bucket(token, self.dimensions)
            vector[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]
