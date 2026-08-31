from sentinellm.evaluation.rag_metrics import (
    context_coverage,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_recall_and_precision_at_k() -> None:
    retrieved = ["d1", "d2", "d3", "d4"]
    relevant = {"d2", "d4", "d9"}
    assert recall_at_k(retrieved, relevant, k=4) == 2 / 3
    assert precision_at_k(retrieved, relevant, k=4) == 2 / 4


def test_mrr_finds_first_relevant_rank() -> None:
    assert mean_reciprocal_rank(["d1", "d2", "d3"], {"d2"}) == 0.5
    assert mean_reciprocal_rank(["d1", "d2", "d3"], {"d9"}) == 0.0
    assert mean_reciprocal_rank(["d1"], {"d1"}) == 1.0


def test_ndcg_rewards_relevant_docs_ranked_higher() -> None:
    high = ndcg_at_k(["d1", "d2", "d3"], {"d1"}, k=3)
    low = ndcg_at_k(["d2", "d3", "d1"], {"d1"}, k=3)
    assert high > low
    assert ndcg_at_k([], {"d1"}, k=3) == 0.0


def test_context_coverage_reflects_lexical_overlap() -> None:
    covered = context_coverage(
        ["refunds are processed within five business days"],
        "our refunds are processed within five business days of return",
    )
    uncovered = context_coverage(
        ["the weather report for tomorrow is sunny"],
        "our refunds are processed within five business days of return",
    )
    assert covered > uncovered
