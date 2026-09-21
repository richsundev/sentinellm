from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    # Rounding can push a vector's similarity to itself a hair past 1.0, which
    # then fails any `le=1.0` score validation downstream.
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
