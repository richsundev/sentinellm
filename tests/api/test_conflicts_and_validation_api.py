"""Requests that used to end in an unhandled 500, or that a caller could use
to poison aggregates (`status="failed"` is invisible to every `== "error"`
check; a negative cost subtracts from every total)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _trace(**over) -> dict:
    payload = {
        "application_id": "val-app",
        "model": "mock:sentinel-flash",
        "provider": "mock",
        "prompt": "q",
        "response": "a",
        "evaluate": False,
    }
    payload.update(over)
    return payload


# --- conflicts ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_application_name_is_a_409_not_a_500(client: AsyncClient) -> None:
    first = await client.post("/api/v1/applications", json={"name": "dup-app"})
    second = await client.post("/api/v1/applications", json={"name": "dup-app"})

    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_dataset_name_and_version_is_a_409(client: AsyncClient) -> None:
    body = {"name": "ds", "version": "v1", "records": [{"question": "q"}]}
    assert (await client.post("/api/v1/datasets", json=body)).status_code == 201
    assert (await client.post("/api/v1/datasets", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_creating_an_api_key_for_an_unknown_application_is_a_404(
    client: AsyncClient,
) -> None:
    """On Postgres the foreign key fails at flush; nothing checked up front."""
    resp = await client.post(
        "/api/v1/applications/api-keys", json={"application_id": "no-such-app", "name": "k"}
    )
    assert resp.status_code == 404


# --- trace validation ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status_value", ["failed", "ERROR", "success", ""])
async def test_trace_status_must_be_ok_or_error(client: AsyncClient, status_value: str) -> None:
    resp = await client.post("/api/v1/traces", json=_trace(status=status_value))
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "latency_ms", "estimated_cost"])
async def test_negative_trace_numbers_are_rejected(client: AsyncClient, field: str) -> None:
    resp = await client.post("/api/v1/traces", json=_trace(**{field: -1}))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_negative_span_timings_are_rejected(client: AsyncClient) -> None:
    span = {"name": "s", "start_ms": -5.0, "duration_ms": 1.0}
    assert (await client.post("/api/v1/traces", json=_trace(spans=[span]))).status_code == 422
    span = {"name": "s", "start_ms": 0.0, "duration_ms": -1.0}
    assert (await client.post("/api/v1/traces", json=_trace(spans=[span]))).status_code == 422


@pytest.mark.asyncio
async def test_valid_traces_with_zero_values_still_ingest(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/traces",
        json=_trace(status="error", input_tokens=0, latency_ms=0.0, estimated_cost=0.0),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_alert_thresholds_cannot_be_negative(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.patch("/api/v1/alerts/rules/error_rate", json={"threshold": -0.5})
    assert resp.status_code == 422
    ok = await client.patch("/api/v1/alerts/rules/error_rate", json={"threshold": 0.2})
    assert ok.status_code == 200
