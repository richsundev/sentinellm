"""Core evaluation abstractions.

Every evaluator — deterministic or LLM-judge — implements the same
`Evaluator` interface and returns the same `EvaluationMetricResult` shape
(metric_name, score, threshold, passed, reason, evaluator_version), so the
pipeline, storage layer, and dashboard never need to special-case which kind
of evaluator produced a metric.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievedDoc:
    doc_id: str
    content: str
    score: float = 0.0
    rank: int = 0


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    question: str
    answer: str
    context: str = ""
    retrieved_documents: list[RetrievedDoc] = field(default_factory=list)
    latency_ms: float = 0.0
    cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationMetricResult:
    metric_name: str
    score: float
    threshold: float | None
    passed: bool | None
    reason: str
    evaluator_version: str


class Evaluator(ABC):
    metric_name: str
    version: str = "v1"

    @abstractmethod
    async def evaluate(self, ctx: EvaluationContext) -> EvaluationMetricResult: ...
