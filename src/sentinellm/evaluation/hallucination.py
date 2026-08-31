"""Dedicated hallucination detection pipeline.

Claim extraction and claim verification are each behind a small `Protocol`
so either strategy can evolve independently — e.g. swapping the naive
sentence-splitting extractor for an LLM-based claim decomposer, or the
embedding-similarity verifier for an NLI (natural language inference) model,
without touching `HallucinationDetector` or any caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.embeddings.similarity import cosine_similarity
from sentinellm.evaluation.deterministic import split_sentences

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"

_SUPPORTED_THRESHOLD = 0.6
_PARTIAL_THRESHOLD = 0.3


@dataclass(frozen=True, slots=True)
class Claim:
    text: str


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    claim: str
    status: str
    support_score: float
    evidence: str


@dataclass(frozen=True, slots=True)
class HallucinationResult:
    hallucination_score: float
    claims: list[ClaimVerdict]


class ClaimExtractor(Protocol):
    def extract(self, answer: str) -> list[Claim]: ...


class ClaimVerifier(Protocol):
    async def verify(self, claim: Claim, context: str) -> ClaimVerdict: ...


class SentenceSplitClaimExtractor:
    """Treats each sentence of the answer as one atomic claim.

    A more sophisticated extractor (e.g. LLM-based decomposition of
    compound sentences into single-fact claims) can be substituted without
    changing `HallucinationDetector`.
    """

    def extract(self, answer: str) -> list[Claim]:
        return [Claim(text=s) for s in split_sentences(answer)]


class EmbeddingSimilarityVerifier:
    """Verifies a claim by its embedding similarity to the source context."""

    def __init__(self, embeddings: EmbeddingProvider) -> None:
        self._embeddings = embeddings

    async def verify(self, claim: Claim, context: str) -> ClaimVerdict:
        if not context.strip():
            return ClaimVerdict(
                claim.text, PARTIALLY_SUPPORTED, 0.5, "no context available to verify against"
            )

        context_sentences = split_sentences(context) or [context]
        claim_vec = await self._embeddings.embed(claim.text)

        best_score = 0.0
        best_sentence = ""
        for sentence in context_sentences:
            sent_vec = await self._embeddings.embed(sentence)
            score = max(0.0, cosine_similarity(claim_vec, sent_vec))
            if score > best_score:
                best_score, best_sentence = score, sentence

        if best_score >= _SUPPORTED_THRESHOLD:
            status = SUPPORTED
        elif best_score >= _PARTIAL_THRESHOLD:
            status = PARTIALLY_SUPPORTED
        else:
            status = UNSUPPORTED

        evidence = best_sentence if best_score > 0 else "no supporting sentence found in context"
        return ClaimVerdict(claim.text, status, round(best_score, 4), evidence)


class HallucinationDetector:
    def __init__(
        self,
        embeddings: EmbeddingProvider,
        extractor: ClaimExtractor | None = None,
        verifier: ClaimVerifier | None = None,
    ) -> None:
        self._extractor = extractor or SentenceSplitClaimExtractor()
        self._verifier = verifier or EmbeddingSimilarityVerifier(embeddings)

    async def detect(self, question: str, context: str, answer: str) -> HallucinationResult:
        claims = self._extractor.extract(answer)
        if not claims:
            return HallucinationResult(hallucination_score=0.0, claims=[])

        verdicts = [await self._verifier.verify(claim, context) for claim in claims]
        unsupported_weight = {SUPPORTED: 0.0, PARTIALLY_SUPPORTED: 0.5, UNSUPPORTED: 1.0}
        score = sum(unsupported_weight[v.status] for v in verdicts) / len(verdicts)
        return HallucinationResult(hallucination_score=round(score, 4), claims=verdicts)
