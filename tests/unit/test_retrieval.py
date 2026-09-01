import pytest

from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.retrieval.reranker import ScoreJitterReranker
from sentinellm.retrieval.retriever import Document, EmbeddingRetriever, RetrievedResult


@pytest.fixture
def corpus() -> list[Document]:
    return [
        Document(doc_id="d1", content="Refunds are honored within 30 days of purchase."),
        Document(doc_id="d2", content="Standard shipping takes 3 to 5 business days."),
        Document(doc_id="d3", content="Enterprise plans include a dedicated account manager."),
    ]


@pytest.mark.asyncio
async def test_retrieve_ranks_most_relevant_document_first(corpus: list[Document]) -> None:
    retriever = EmbeddingRetriever(MockEmbeddingProvider(), corpus)

    # MockEmbeddingProvider is a literal bag-of-words hash (no stemming or
    # synonyms — "refund" and "refunds" are different tokens), so the query
    # deliberately reuses d1's exact vocabulary to get an unambiguous signal
    # rather than relying on hash-collision noise between near-zero-overlap
    # candidates.
    results = await retriever.retrieve("refunds within 30 days of purchase", top_k=3)

    assert results[0].doc_id == "d1"
    assert results[0].rank == 0
    assert results[0].score >= results[1].score >= results[2].score


@pytest.mark.asyncio
async def test_retrieve_respects_top_k(corpus: list[Document]) -> None:
    retriever = EmbeddingRetriever(MockEmbeddingProvider(), corpus)

    results = await retriever.retrieve("shipping question", top_k=2)

    assert len(results) == 2
    assert [r.rank for r in results] == [0, 1]


@pytest.mark.asyncio
async def test_retrieve_empty_corpus_returns_empty_list() -> None:
    retriever = EmbeddingRetriever(MockEmbeddingProvider(), [])

    results = await retriever.retrieve("anything", top_k=3)

    assert results == []


@pytest.mark.asyncio
async def test_retrieve_top_k_larger_than_corpus_returns_all(corpus: list[Document]) -> None:
    retriever = EmbeddingRetriever(MockEmbeddingProvider(), corpus)

    results = await retriever.retrieve("shipping and refunds", top_k=10)

    assert len(results) == len(corpus)


def test_reranker_reassigns_contiguous_ranks_after_resorting() -> None:
    # new_score = 0.7 * base_score + 0.3 * lexical_overlap(query, content).
    # a: 0.7*0.5 + 0.3*0   = 0.35
    # b: 0.7*0.3 + 0.3*1.0 = 0.51  (every query word appears in b's content)
    # so full lexical overlap is enough to overturn a meaningful base-score
    # gap, which is the reranker's whole purpose.
    reranker = ScoreJitterReranker()
    results = [
        RetrievedResult(
            doc_id="a", content="totally unrelated content about weather", score=0.5, rank=0
        ),
        RetrievedResult(doc_id="b", content="refund policy", score=0.3, rank=1),
    ]

    reranked = reranker.rerank("refund policy", results)

    assert [r.rank for r in reranked] == [0, 1]
    assert {r.doc_id for r in reranked} == {"a", "b"}
    assert reranked[0].doc_id == "b"
    assert reranked[0].score == pytest.approx(0.51)
    assert reranked[1].score == pytest.approx(0.35)


def test_reranker_handles_empty_results() -> None:
    assert ScoreJitterReranker().rerank("anything", []) == []


def test_reranker_scores_are_bounded_at_one() -> None:
    reranker = ScoreJitterReranker()
    results = [
        RetrievedResult(doc_id="a", content="refund policy refund policy", score=1.0, rank=0)
    ]

    reranked = reranker.rerank("refund policy", results)

    assert reranked[0].score <= 1.0
