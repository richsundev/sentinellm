"""Prompt-injection detection hook.

A heuristic pattern-matcher over the incoming prompt, on the same
philosophy as the deterministic evaluators (fast, free, dependency-free,
and a legitimate first line of defense — not a claim that this catches
every jailbreak). Wired into evaluation as `PromptInjectionEvaluator`
(see evaluation/deterministic.py) so injection risk shows up as an
ordinary evaluation metric on every trace, not a separate bolted-on system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS = re.compile(
    r"\b(ignore (the )?(above|previous|prior) instructions?|disregard (the )?(above|previous) "
    r"(instructions?|prompt)|you are now|forget (you are|your instructions)|"
    r"reveal (your|the) (system prompt|instructions)|act as (if )?you (have no|are not) "
    r"(restrictions?|filters?)|do anything now|jailbreak|override your (guidelines|instructions))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PromptInjectionResult:
    risk_score: float  # 0 (clean) - 1 (matched a known injection pattern)
    matched_patterns: list[str]


def detect_prompt_injection(text: str) -> PromptInjectionResult:
    matches = sorted({m.group(0).lower() for m in _INJECTION_PATTERNS.finditer(text)})
    return PromptInjectionResult(risk_score=1.0 if matches else 0.0, matched_patterns=matches)
