"""Default model catalog: pricing + quality/latency priors.

This catalog is the single source of truth for model economics used by (a)
the demo seed script to populate the `models` table, (b) the MockProvider's
per-model behavior profile, and (c) the router's priors before it has
observed real trace history for a model. Prices are illustrative, modeled on
public per-1K-token pricing tiers as of 2025 for well-known model families —
they are not live prices and should not be read as such.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelProfile:
    id: str  # "provider:model"
    name: str
    provider: str
    input_price_per_1k: float
    output_price_per_1k: float
    context_window: int
    quality_tier: float  # prior belief in [0, 1], higher = better answers
    avg_latency_ms_prior: float
    hallucination_tendency: float  # prior probability an unsupported claim slips in


DEFAULT_MODEL_CATALOG: dict[str, ModelProfile] = {
    p.id: p
    for p in [
        ModelProfile(
            id="mock:sentinel-nano",
            name="sentinel-nano",
            provider="mock",
            input_price_per_1k=0.0001,
            output_price_per_1k=0.0002,
            context_window=8_000,
            quality_tier=0.55,
            avg_latency_ms_prior=280,
            hallucination_tendency=0.40,
        ),
        ModelProfile(
            id="mock:sentinel-flash",
            name="sentinel-flash",
            provider="mock",
            input_price_per_1k=0.00015,
            output_price_per_1k=0.0006,
            context_window=32_000,
            quality_tier=0.72,
            avg_latency_ms_prior=420,
            hallucination_tendency=0.12,
        ),
        ModelProfile(
            id="mock:sentinel-pro",
            name="sentinel-pro",
            provider="mock",
            input_price_per_1k=0.0025,
            output_price_per_1k=0.01,
            context_window=128_000,
            quality_tier=0.90,
            avg_latency_ms_prior=950,
            hallucination_tendency=0.05,
        ),
        ModelProfile(
            id="mock:sentinel-opus",
            name="sentinel-opus",
            provider="mock",
            input_price_per_1k=0.015,
            output_price_per_1k=0.075,
            context_window=200_000,
            quality_tier=0.97,
            avg_latency_ms_prior=1800,
            hallucination_tendency=0.02,
        ),
        ModelProfile(
            id="mock:sentinel-judge",
            name="sentinel-judge",
            provider="mock",
            input_price_per_1k=0.003,
            output_price_per_1k=0.012,
            context_window=128_000,
            quality_tier=0.93,
            avg_latency_ms_prior=700,
            hallucination_tendency=0.03,
        ),
    ]
}


def get_profile(model_id: str) -> ModelProfile:
    if model_id in DEFAULT_MODEL_CATALOG:
        return DEFAULT_MODEL_CATALOG[model_id]
    return ModelProfile(
        id=model_id,
        name=model_id.split(":")[-1],
        provider=model_id.split(":")[0] if ":" in model_id else "unknown",
        input_price_per_1k=0.001,
        output_price_per_1k=0.003,
        context_window=16_000,
        quality_tier=0.6,
        avg_latency_ms_prior=600,
        hallucination_tendency=0.15,
    )
