import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_alert_rules_seeds_defaults_on_first_call(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/alerts/rules")
    assert resp.status_code == 200
    rules = resp.json()
    assert {r["rule"] for r in rules} == {
        "error_rate",
        "p95_latency",
        "daily_cost",
        "quality_score",
        "hallucination_rate",
    }
    assert all(r["enabled"] is True for r in rules)


@pytest.mark.asyncio
async def test_update_alert_rule_threshold_and_enabled(client: AsyncClient) -> None:
    await client.get("/api/v1/alerts/rules")  # ensure defaults exist

    resp = await client.patch(
        "/api/v1/alerts/rules/error_rate", json={"threshold": 0.2, "enabled": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["threshold"] == 0.2
    assert body["enabled"] is False

    listing = await client.get("/api/v1/alerts/rules")
    updated = next(r for r in listing.json() if r["rule"] == "error_rate")
    assert updated["threshold"] == 0.2
    assert updated["enabled"] is False


@pytest.mark.asyncio
async def test_update_unknown_alert_rule_returns_404(client: AsyncClient) -> None:
    resp = await client.patch("/api/v1/alerts/rules/not-a-real-rule", json={"threshold": 0.5})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_alert_rule_partial_payload_leaves_other_field_unchanged(
    client: AsyncClient,
) -> None:
    await client.get("/api/v1/alerts/rules")

    first = await client.patch("/api/v1/alerts/rules/daily_cost", json={"threshold": 100.0})
    assert first.json()["threshold"] == 100.0
    assert first.json()["enabled"] is True

    second = await client.patch("/api/v1/alerts/rules/daily_cost", json={"enabled": False})
    assert second.json()["enabled"] is False
    assert second.json()["threshold"] == 100.0
