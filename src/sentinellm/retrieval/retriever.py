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
from dataclasses import dataclass

from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.embeddings.similarity import cosine_similarity


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
    def __init__(self, embeddings: EmbeddingProvider, corpus: list[Document]) -> None:
        self._embeddings = embeddings
        self._corpus = corpus

    async def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedResult]:
        if not self._corpus:
            return []
        query_vec = await self._embeddings.embed(query)
        scored = []
        for doc in self._corpus:
            doc_vec = await self._embeddings.embed(doc.content)
            scored.append((doc, max(0.0, cosine_similarity(query_vec, doc_vec))))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        top = scored[:top_k]
        return [
            RetrievedResult(doc_id=doc.doc_id, content=doc.content, score=round(score, 4), rank=i)
            for i, (doc, score) in enumerate(top)
        ]
