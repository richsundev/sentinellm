"""`/generate` with `dataset_id` loaded every record and re-embedded the whole
corpus on every request — with a real embedding model, hundreds of model calls
per question. The corpus is now indexed once and reused."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Dataset, DatasetRecord
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.retrieval import corpus_cache
from sentinellm.retrieval.retriever import Document, EmbeddingRetriever
from sentinellm.services import generation


class _CountingEmbeddings(MockEmbeddingProvider):
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return await super().embed(text)


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    corpus_cache.clear()


@pytest.fixture
def embeddings(monkeypatch: pytest.MonkeyPatch) -> _CountingEmbeddings:
    provider = _CountingEmbeddings()
    monkeypatch.setattr(generation, "get_embedding_provider", lambda _name: provider)
    return provider


async def _dataset(session: AsyncSession, n: int = 6) -> Dataset:
    dataset = Dataset(name=f"corpus-{n}", version="v1")
    dataset.records = [
        DatasetRecord(question=f"q{i}", context=f"Refund policy number {i} applies to plan {i}.")
        for i in range(n)
    ]
    session.add(dataset)
    await session.commit()
    return dataset


@pytest.mark.asyncio
async def test_the_corpus_is_embedded_once_not_per_request(
    db_session: AsyncSession, embeddings: _CountingEmbeddings
) -> None:
    dataset = await _dataset(db_session, 6)

    first, *_ = await generation._retrieve_and_rerank(db_session, dataset.id, "refund plan 3", 3)
    after_first = len(embeddings.texts)
    second, *_ = await generation._retrieve_and_rerank(db_session, dataset.id, "refund plan 4", 3)

    assert after_first == 6 + 1  # every document once, plus the question
    assert len(embeddings.texts) == after_first + 1  # only the new question
    assert [d.doc_id for d in first] != [d.doc_id for d in second]  # still question-dependent


@pytest.mark.asyncio
async def test_a_precomputed_index_ranks_exactly_like_embedding_on_the_fly() -> None:
    embeddings = MockEmbeddingProvider()
    corpus = [Document(f"d{i}", f"Refund policy {i} plan {i % 3} days {i * 7}") for i in range(12)]
    vectors = [await embeddings.embed(d.content) for d in corpus]

    live = await EmbeddingRetriever(embeddings, corpus).retrieve("refund plan 2 days 70", 5)
    indexed = await EmbeddingRetriever(embeddings, corpus, vectors=vectors).retrieve(
        "refund plan 2 days 70", 5
    )

    assert indexed == live


@pytest.mark.asyncio
async def test_unit_vectors_score_exactly_like_full_cosine_similarity() -> None:
    from sentinellm.embeddings.similarity import normalized

    embeddings = MockEmbeddingProvider()
    corpus = [Document(f"d{i}", f"Refund policy {i} plan {i % 3} days {i * 7}") for i in range(12)]
    unit = [normalized(await embeddings.embed(d.content)) for d in corpus]

    live = await EmbeddingRetriever(embeddings, corpus).retrieve("refund plan 2 days 70", 12)
    fast = await EmbeddingRetriever(embeddings, corpus, vectors=unit, unit_vectors=True).retrieve(
        "refund plan 2 days 70", 12
    )

    assert [(r.doc_id, r.score) for r in fast] == [(r.doc_id, r.score) for r in live]


@pytest.mark.asyncio
async def test_a_changed_record_count_rebuilds_the_index(
    db_session: AsyncSession, embeddings: _CountingEmbeddings
) -> None:
    dataset = await _dataset(db_session, 4)
    await generation._retrieve_and_rerank(db_session, dataset.id, "refund", 2)
    embedded = len(embeddings.texts)

    db_session.add(DatasetRecord(dataset_id=dataset.id, question="new", context="A brand new doc."))
    await db_session.commit()
    docs, *_ = await generation._retrieve_and_rerank(db_session, dataset.id, "brand new doc", 5)

    assert len(embeddings.texts) == embedded + 5 + 1  # re-indexed all five, plus the question
    assert any("brand new" in d.content for d in docs)


@pytest.mark.asyncio
async def test_datasets_do_not_share_an_index_and_the_cache_is_bounded(
    db_session: AsyncSession, embeddings: _CountingEmbeddings
) -> None:
    a = await _dataset(db_session, 3)
    b = await _dataset(db_session, 5)

    docs_a, *_ = await generation._retrieve_and_rerank(db_session, a.id, "refund", 10)
    docs_b, *_ = await generation._retrieve_and_rerank(db_session, b.id, "refund", 10)

    assert (len(docs_a), len(docs_b)) == (3, 5)
    assert corpus_cache.size() == 2
    for i in range(corpus_cache.CAPACITY + 3):
        corpus_cache.put((f"ds-{i}", "mock", 1), corpus_cache.CorpusIndex((), ()))
    assert corpus_cache.size() == corpus_cache.CAPACITY


@pytest.mark.asyncio
async def test_a_dataset_without_usable_text_yields_nothing(
    db_session: AsyncSession, embeddings: _CountingEmbeddings
) -> None:
    empty = Dataset(name="empty-corpus", version="v1")
    empty.records = [DatasetRecord(question="q", context="", expected_answer="")]
    db_session.add(empty)
    await db_session.commit()

    assert await generation._retrieve_and_rerank(db_session, empty.id, "q", 3) == ([], 0.0, 0.0)


@pytest.mark.asyncio
async def test_the_sentence_transformer_provider_embeds_a_batch_in_one_call() -> None:
    """Indexing a corpus was one thread hop and one model call per document."""
    from sentinellm.embeddings.sentence_transformer_provider import (
        SentenceTransformerEmbeddingProvider,
    )

    class _Encoded:
        def __init__(self, rows: list[list[float]]) -> None:
            self._rows = rows

        def tolist(self) -> list[list[float]]:
            return self._rows

    calls: list[object] = []

    class _Model:
        def encode(self, texts: object) -> _Encoded:
            calls.append(texts)
            return _Encoded([[float(len(t)), 1.0] for t in texts])  # type: ignore[attr-defined]

    provider = object.__new__(SentenceTransformerEmbeddingProvider)
    provider._model = _Model()  # type: ignore[attr-defined]

    vectors = await provider.embed_batch(["a", "bb", "ccc"])

    assert vectors == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]
    assert len(calls) == 1
    assert await provider.embed_batch([]) == []
