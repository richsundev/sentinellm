"""Semantic response cache.

Flow: embed the incoming query -> search recent, unexpired cache entries for
the same (application, model, context) -> if cosine similarity exceeds the
configured threshold, return the cached response instead of calling the model.

The *context key* (a hash of the system prompt and retrieved documents) is part
of the match: the question alone doesn't determine a RAG answer, so replaying
one against different documents would serve a stale, ungrounded response. The
*TTL* bounds how long any answer is replayed (and lets `prune` reclaim rows).

Scaling note: candidate search here is a linear scan over the most recent N
entries for the (application, model) pair, done in Python. That is fine at
the demo/portfolio scale this project runs at. At production scale the
candidate lookup would move to a proper ANN index (pgvector's IVFFlat/HNSW,
or Redis' vector search) — the `SemanticCache` interface would not need to
change, only what sits behind `_find_candidates`. See docs/design-decisions.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
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


def context_key_for(*parts: str | None) -> str:
    """Stable fingerprint of the non-question inputs to a generation ("" if none)."""
    content = "\x1f".join(p for p in parts if p)
    return hashlib.sha256(content.encode()).hexdigest()[:32] if content else ""


class SemanticCache:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 0,
    ) -> None:
        self._embeddings = embedding_provider
        self._threshold = similarity_threshold
        self._ttl_seconds = ttl_seconds  # 0 = entries never expire

    async def lookup(
        self,
        session: AsyncSession,
        *,
        application_id: str,
        model: str,
        query_text: str,
        context_key: str = "",
    ) -> CacheLookupResult | None:
        query_vector = await self._embeddings.embed(query_text)
        candidates = await self._find_candidates(
            session, application_id=application_id, model=model, context_key=context_key
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
        context_key: str = "",
    ) -> None:
        vector = await self._embeddings.embed(query_text)
        entry = SemanticCacheEntry(
            application_id=application_id,
            model=model,
            query_text=query_text,
            context_key=context_key,
            embedding=vector,
            response=response,
        )
        session.add(entry)
        await session.flush()

    async def _find_candidates(
        self, session: AsyncSession, *, application_id: str, model: str, context_key: str
    ) -> list[SemanticCacheEntry]:
        stmt = select(SemanticCacheEntry).where(
            SemanticCacheEntry.application_id == application_id,
            SemanticCacheEntry.model == model,
            SemanticCacheEntry.context_key == context_key,
        )
        if self._ttl_seconds > 0:
            stmt = stmt.where(
                SemanticCacheEntry.created_at
                >= datetime.now(UTC) - timedelta(seconds=self._ttl_seconds)
            )
        result = await session.execute(
            stmt.order_by(SemanticCacheEntry.created_at.desc()).limit(_CANDIDATE_SCAN_LIMIT)
        )
        return list(result.scalars().all())


async def prune_expired_entries(session: AsyncSession, ttl_seconds: int) -> int:
    """Deletes cache entries older than the TTL; returns how many. No-op when
    expiry is off. Lookups already ignore expired rows — this reclaims them."""
    if ttl_seconds <= 0:
        return 0
    result: CursorResult = await session.execute(  # type: ignore[assignment]
        delete(SemanticCacheEntry).where(
            SemanticCacheEntry.created_at < datetime.now(UTC) - timedelta(seconds=ttl_seconds)
        )
    )
    await session.commit()
    return result.rowcount or 0
