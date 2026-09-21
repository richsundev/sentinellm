from __future__ import annotations

import math
from operator import mul


def normalized(vector: list[float]) -> list[float]:
    """The unit vector (a zero vector is returned unchanged)."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else list(vector)


def dot(a: list[float], b: list[float]) -> float:
    """Dot product; for unit vectors this *is* the cosine similarity, without
    recomputing both norms on every comparison."""
    if len(a) != len(b):
        return 0.0
    return sum(map(mul, a, b))


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
