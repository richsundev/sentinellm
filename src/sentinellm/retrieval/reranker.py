"""Reranking stage. `ScoreJitterReranker` is a deterministic stand-in for a
cross-encoder reranker: it nudges scores based on lexical overlap with the
query, which is enough to produce a plausible, order-changing reranking span
in traces without loading a real cross-encoder model.
"""

from __future__ import annotations

import re

from sentinellm.retrieval.retriever import RetrievedResult


def _lexical_overlap(query: str, text: str) -> float:
    q = set(re.findall(r"[a-z0-9]+", query.lower()))
    t = set(re.findall(r"[a-z0-9]+", text.lower()))
    if not q or not t:
        return 0.0
    return len(q & t) / len(q)


class ScoreJitterReranker:
    def rerank(self, query: str, results: list[RetrievedResult]) -> list[RetrievedResult]:
        rescored = []
        for r in results:
            lexical = _lexical_overlap(query, r.content)
            new_score = round(min(1.0, 0.7 * r.score + 0.3 * lexical), 4)
            rescored.append((r, new_score))
        rescored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            RetrievedResult(doc_id=r.doc_id, content=r.content, score=score, rank=i)
            for i, (r, score) in enumerate(rescored)
        ]
