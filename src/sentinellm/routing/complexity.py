"""Heuristic task-complexity and risk classification.

These are deliberately simple, explainable rules rather than a learned
classifier: a portfolio-scale project has no labeled complexity dataset to
train one on, and an explainable heuristic is exactly what you want to be
able to show a stakeholder asking "why did the router pick this model?".
A learned complexity classifier is a natural v2 (see docs/routing.md).
"""

from __future__ import annotations

import re
from enum import StrEnum

_REASONING_CUES = re.compile(
    r"\b(why|compare|analyze|explain|trade-?off|step by step|design|architecture|root cause|"
    r"debug|optimi[sz]e|prove|derive)\b",
    re.IGNORECASE,
)
_HIGH_RISK_TERMS = re.compile(
    r"\b(legal|lawsuit|diagnos|medical|prescription|financial advice|tax filing|security incident|"
    r"breach|suicide|self-harm)\b",
    re.IGNORECASE,
)


class TaskComplexity(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


_QUALITY_FLOOR = {
    TaskComplexity.SIMPLE: 0.0,
    TaskComplexity.MEDIUM: 0.45,
    TaskComplexity.COMPLEX: 0.80,
}


def classify_complexity(prompt: str, context_length: int = 0) -> TaskComplexity:
    word_count = len(prompt.split())
    has_reasoning_cue = bool(_REASONING_CUES.search(prompt))
    multi_part = prompt.count("?") > 1 or prompt.count("\n") > 3

    if word_count > 120 or (has_reasoning_cue and word_count > 25) or context_length > 6000:
        return TaskComplexity.COMPLEX
    if word_count > 30 or has_reasoning_cue or multi_part or context_length > 1500:
        return TaskComplexity.MEDIUM
    return TaskComplexity.SIMPLE


def quality_floor_for(complexity: TaskComplexity) -> float:
    return _QUALITY_FLOOR[complexity]


def assess_risk(prompt: str, metadata: dict | None = None) -> float:
    """Returns a risk score in [0, 1]. High-risk requests (legal/medical/
    financial/safety-sensitive) should be routed to the most reliable model
    regardless of cost, so the router treats this as both a scoring penalty
    for weak models AND a quality floor override.
    """
    base = 0.10
    if _HIGH_RISK_TERMS.search(prompt):
        base = 0.85
    if metadata and metadata.get("risk_override") == "high":
        base = max(base, 0.9)
    return base
