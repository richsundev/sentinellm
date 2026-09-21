"""A small in-process cache of embedded dataset corpora.

`/generate` with a `dataset_id` retrieves from that dataset's records. It used
to load every record and embed every document for each request; with a real
embedding model that is hundreds of model calls per question. A dataset's
records don't change after it is created, so the corpus is indexed once —
documents and their vectors — and reused.

The cache key includes the record count, so a dataset that does gain records is
re-indexed rather than served stale. The cache is per process and bounded (LRU);
a cold replica just builds its own.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from sentinellm.retrieval.retriever import Document

CAPACITY = 16

# (dataset_id, embedding provider name, record count)
CacheKey = tuple[str, str, int]


@dataclass(frozen=True, slots=True)
class CorpusIndex:
    documents: tuple[Document, ...]
    vectors: tuple[list[float], ...]  # unit vectors: comparing is a dot product


_indexes: OrderedDict[CacheKey, CorpusIndex] = OrderedDict()


def get(key: CacheKey) -> CorpusIndex | None:
    index = _indexes.get(key)
    if index is not None:
        _indexes.move_to_end(key)
    return index


def put(key: CacheKey, index: CorpusIndex) -> None:
    _indexes[key] = index
    _indexes.move_to_end(key)
    while len(_indexes) > CAPACITY:
        _indexes.popitem(last=False)


def size() -> int:
    return len(_indexes)


def clear() -> None:
    _indexes.clear()
