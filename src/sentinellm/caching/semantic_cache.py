"""Semantic response cache.

Flow: embed the incoming query -> search recent cache entries for the same
(application, model) -> if cosine similarity exceeds the configured
threshold, return the cached response instead of calling the model.

Scaling note: candidate search here is a linear scan over the most recent N
entries for the (application, model) pair, done in Python. That is fine at
the demo/portfolio scale this project runs at. At production scale the
candidate lookup would move to a proper ANN index (pgvector's IVFFlat/HNSW,
or Redis' vector search) — the `SemanticCache` interface would not need to
change, only what sits behind `_find_candidates`. See docs/design-decisions.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.db.models import SemanticCacheEntry
from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.embeddings.similarity import cosine_similarity

logger = get_logger(__name__)

_CANDIDATE_SCAN_LIMIT = 200


@dataclass(slots=True)
class CacheLookupResult:
    response: str
    similarity_score: float
    entry_id: str


class SemanticCache:
    def __init__(
        self, embedding_provider: EmbeddingProvider, similarity_threshold: float = 0.95
    ) -> None:
        self._embeddings = embedding_provider
        self._threshold = similarity_threshold

    async def lookup(
        self, session: AsyncSession, *, application_id: str, model: str, query_text: str
    ) -> CacheLookupResult | None:
        query_vector = await self._embeddings.embed(query_text)
        candidates = await self._find_candidates(
            session, application_id=application_id, model=model
        )

        best: CacheLookupResult | None = None
        for entry in candidates:
            score = cosine_similarity(query_vector, entry.embedding)
            if score >= self._threshold and (best is None or score > best.similarity_score):
                best = CacheLookupResult(
                    response=entry.response, similarity_score=score, entry_id=entry.id
                )

        if best is not None:
            entry = next(e for e in candidates if e.id == best.entry_id)
            entry.hit_count += 1
            await session.flush()
            logger.info(
                "semantic_cache_hit",
                application_id=application_id,
                model=model,
                score=best.similarity_score,
            )
        return best

    async def store(
        self,
        session: AsyncSession,
        *,
        application_id: str,
        model: str,
        query_text: str,
        response: str,
    ) -> None:
        vector = await self._embeddings.embed(query_text)
        entry = SemanticCacheEntry(
            application_id=application_id,
            model=model,
            query_text=query_text,
            embedding=vector,
            response=response,
        )
        session.add(entry)
        await session.flush()

    async def _find_candidates(
        self, session: AsyncSession, *, application_id: str, model: str
    ) -> list[SemanticCacheEntry]:
        stmt = (
            select(SemanticCacheEntry)
            .where(
                SemanticCacheEntry.application_id == application_id,
                SemanticCacheEntry.model == model,
            )
            .order_by(SemanticCacheEntry.created_at.desc())
            .limit(_CANDIDATE_SCAN_LIMIT)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
