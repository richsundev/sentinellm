"""Retriever abstraction over a document corpus.

`EmbeddingRetriever` is an in-memory cosine-similarity retriever — enough to
demonstrate the RAG pipeline and generate realistic retrieval spans/scores in
the demo seed data without standing up a real vector database. Swapping in a
pgvector- or a hosted-vector-DB-backed retriever means implementing this same
tiny interface; nothing upstream (the trace ingestion, evaluation, or router)
needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.embeddings.similarity import cosine_similarity, dot, normalized


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    content: str


@dataclass(frozen=True, slots=True)
class RetrievedResult:
    doc_id: str
    content: str
    score: float
    rank: int


class Retriever(ABC):
    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedResult]: ...


class EmbeddingRetriever(Retriever):
    def __init__(
        self,
        embeddings: EmbeddingProvider,
        corpus: Sequence[Document],
        vectors: Sequence[list[float]] | None = None,
        unit_vectors: bool = False,
    ) -> None:
        """`vectors`, if given, are the corpus's embeddings (same order) — the
        documents are then not embedded again on each `retrieve`. With
        `unit_vectors` they are already normalised, so a comparison is a plain
        dot product."""
        if vectors is not None and len(vectors) != len(corpus):
            raise ValueError("vectors must match the corpus one-to-one")
        self._embeddings = embeddings
        self._corpus = corpus
        self._vectors = vectors
        self._unit = unit_vectors and vectors is not None

    async def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedResult]:
        if not self._corpus:
            return []
        query_vec = await self._embeddings.embed(query)
        query_unit = normalized(query_vec) if self._unit else query_vec
        scored = []
        for i, doc in enumerate(self._corpus):
            if self._unit and self._vectors is not None:
                score = dot(query_unit, self._vectors[i])
            else:
                doc_vec = (
                    self._vectors[i]
                    if self._vectors is not None
                    else await self._embeddings.embed(doc.content)
                )
                score = cosine_similarity(query_vec, doc_vec)
            scored.append((doc, max(0.0, score)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        top = scored[:top_k]
        return [
            RetrievedResult(doc_id=doc.doc_id, content=doc.content, score=round(score, 4), rank=i)
            for i, (doc, score) in enumerate(top)
        ]
