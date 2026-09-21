"""PII redaction hook.

Off by default (`SENTINEL_PII_REDACTION_ENABLED=false`): redaction is lossy
and can itself degrade evaluation quality (a faithfulness check against a
redacted answer is checking something slightly different from what the
model actually said), so it's an explicit opt-in applied at ingestion time
in `api/routers/traces.py` and `services/generation.py`, not a silent
default. What is redacted is what gets *persisted* (the trace and the
semantic-cache entry, which is replayed to other callers); the model still
receives the original text. The `Protocol` keeps the regex implementation swappable for a
real NER-based redactor (e.g. Presidio) without touching call sites.
"""

from __future__ import annotations

import re
from typing import Protocol

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


class PIIRedactor(Protocol):
    def redact(self, text: str) -> str: ...


class RegexPIIRedactor:
    """Deterministic, dependency-free default. Catches common structured
    PII (emails, phone numbers, SSNs, card-number-shaped digit runs) — not
    a substitute for a trained NER model, which is the natural production
    upgrade for unstructured PII (names, addresses)."""

    def redact(self, text: str) -> str:
        text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
        text = _SSN_RE.sub("[REDACTED_SSN]", text)
        text = _CREDIT_CARD_RE.sub("[REDACTED_CARD]", text)
        text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
        return text


_default_redactor = RegexPIIRedactor()


def redact_pii(text: str, redactor: PIIRedactor | None = None) -> str:
    return (redactor or _default_redactor).redact(text)


def redact_documents(documents: list[dict]) -> list[dict]:
    """Copies of retrieved-document dicts with their `content` redacted."""
    return [{**d, "content": redact_pii(d.get("content", ""))} for d in documents]
