from sentinellm.pricing.calculator import calculate_cost


def test_calculate_cost_uses_explicit_prices() -> None:
    cost = calculate_cost(
        "mock:sentinel-pro", 1000, 500, input_price_per_1k=0.001, output_price_per_1k=0.002
    )
    assert cost == round(1000 / 1000 * 0.001 + 500 / 1000 * 0.002, 8)


def test_calculate_cost_falls_back_to_catalog() -> None:
    cost = calculate_cost("mock:sentinel-nano", 1000, 1000)
    assert cost > 0


def test_calculate_cost_unknown_model_uses_default_profile() -> None:
    cost = calculate_cost("openai:some-future-model", 1000, 1000)
    assert cost > 0
