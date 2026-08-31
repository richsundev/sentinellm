"""Deterministic request cost calculation from token counts + a pricing source."""

from __future__ import annotations

from sentinellm.pricing.catalog import get_profile


def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    *,
    input_price_per_1k: float | None = None,
    output_price_per_1k: float | None = None,
) -> float:
    """Compute request cost. Pass explicit prices (e.g. from the DB `models`
    table) when available; otherwise falls back to the static catalog prior.
    """
    if input_price_per_1k is None or output_price_per_1k is None:
        profile = get_profile(model_id)
        input_price_per_1k = (
            input_price_per_1k if input_price_per_1k is not None else profile.input_price_per_1k
        )
        output_price_per_1k = (
            output_price_per_1k if output_price_per_1k is not None else profile.output_price_per_1k
        )
    cost = (input_tokens / 1000) * input_price_per_1k + (output_tokens / 1000) * output_price_per_1k
    return round(cost, 8)
