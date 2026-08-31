"""Classic information-retrieval metrics for RAG evaluation runs.

These operate on ranked retrieved document IDs against a ground-truth
relevant set (from a benchmark dataset record), independent of any specific
vector store — used by the dataset evaluation pipeline (`scripts/run_
benchmarks.py` and the `/experiments` flow), not by per-trace evaluation
(which uses the embedding-similarity proxies in `deterministic.py` since it
has no ground truth).
"""

from __future__ import annotations

import math


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(top_k & relevant_ids) / len(relevant_ids)


def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / len(top_k)


def mean_reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    top_k = retrieved_ids[:k]
    dcg = sum(1.0 / math.log2(i + 2) for i, doc_id in enumerate(top_k) if doc_id in relevant_ids)
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def context_coverage(context_texts: list[str], answer: str) -> float:
    """Fraction of context "chunks" whose vocabulary meaningfully overlaps
    the answer — a cheap proxy for whether the answer drew on the retrieved
    context at all.
    """
    import re

    answer_words = set(re.findall(r"[a-z0-9]+", answer.lower()))
    if not context_texts or not answer_words:
        return 0.0
    covered = 0
    for chunk in context_texts:
        chunk_words = set(re.findall(r"[a-z0-9]+", chunk.lower()))
        if not chunk_words:
            continue
        overlap = len(chunk_words & answer_words) / len(chunk_words)
        if overlap > 0.15:
            covered += 1
    return covered / len(context_texts)
