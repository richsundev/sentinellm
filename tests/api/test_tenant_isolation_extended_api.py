"""Tenant isolation for the endpoints the first scoping pass missed.

A scoped key must only ever see or write its own application's data. These
endpoints returned every tenant's rows (evaluations — including hallucination
evidence text lifted from private context — routing decisions, regressions,
alerts), let a scoped key write traces into any application via experiments,
let it change platform-wide configuration, and let `POST /traces` hand back
another tenant's trace when given its id."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import (
    Alert,
    Evaluation,
    HallucinationClaim,
    Regression,
    RoutingDecision,
    Trace,
)


async def _scoped_client(admin: AsyncClient, app, name: str) -> tuple[AsyncClient, str]:
    app_id = (await admin.post("/api/v1/applications", json={"name": name})).json()["id"]
    key = (
        await admin.post(
            "/api/v1/applications/api-keys",
            json={
                "application_id": app_id,
                "name": "scoped",
                "role": "admin",
                "scoped_to_application": True,
            },
        )
    ).json()["plaintext_key"]
    client = AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers={"X-API-Key": key}
    )
    return client, app_id


async def _tenant_rows(session: AsyncSession, application_id: str, tag: str) -> str:
    """One trace with an evaluation (+claim evidence) and a routing decision."""
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="r",
        application_id=application_id,
        model="mock:sentinel-flash",
        provider="mock",
        prompt=f"{tag} prompt",
        response="a",
        latency_ms=1.0,
        estimated_cost=0.0,
        evaluation_status="completed",
    )
    session.add(trace)
    await session.flush()
    evaluation = Evaluation(trace_id=trace.id, overall_quality=0.5, hallucination_score=0.5)
    evaluation.claims = [
        HallucinationClaim(
            claim="c", status="UNSUPPORTED", support_score=0.1, evidence=f"{tag} PRIVATE CONTEXT"
        )
    ]
    session.add(evaluation)
    session.add(
        RoutingDecision(
            trace_id=trace.id,
            selected_model="mock:sentinel-flash",
            reason=f"{tag} reason",
            candidates=[],
        )
    )
    session.add(
        Regression(
            metric_name="overall_quality",
            previous_value=0.9,
            new_value=0.5,
            delta_pct=44.0,
            severity="critical",
            application_id=application_id,
            likely_cause=f"{tag} cause",
        )
    )
    await session.commit()
    return trace.trace_id


@pytest.mark.asyncio
async def test_evaluations_are_limited_to_the_keys_own_application(
    client: AsyncClient, app, db_session: AsyncSession
) -> None:
    scoped, a_id = await _scoped_client(client, app, "iso-a")
    b_id = (await client.post("/api/v1/applications", json={"name": "iso-b"})).json()["id"]
    a_trace = await _tenant_rows(db_session, a_id, "A")
    b_trace = await _tenant_rows(db_session, b_id, "B")

    async with scoped:
        listing = (await scoped.get("/api/v1/evaluations")).json()
        by_trace = (await scoped.get("/api/v1/evaluations", params={"trace_id": b_trace})).json()

    assert [e["trace_id"] for e in listing["items"]] == [a_trace]
    assert listing["total"] == 1
    assert "B PRIVATE CONTEXT" not in str(listing)
    assert by_trace["items"] == []
    assert by_trace["total"] == 0


@pytest.mark.asyncio
async def test_routing_decisions_are_limited_to_the_keys_own_application(
    client: AsyncClient, app, db_session: AsyncSession
) -> None:
    scoped, a_id = await _scoped_client(client, app, "iso-a2")
    b_id = (await client.post("/api/v1/applications", json={"name": "iso-b2"})).json()["id"]
    a_trace = await _tenant_rows(db_session, a_id, "A")
    await _tenant_rows(db_session, b_id, "B")

    async with scoped:
        body = (await scoped.get("/api/v1/routing/decisions")).json()

    assert [d["trace_id"] for d in body["items"]] == [a_trace]
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_regressions_are_limited_to_the_keys_own_application(
    client: AsyncClient, app, db_session: AsyncSession
) -> None:
    scoped, a_id = await _scoped_client(client, app, "iso-a3")
    b_id = (await client.post("/api/v1/applications", json={"name": "iso-b3"})).json()["id"]
    await _tenant_rows(db_session, a_id, "A")
    await _tenant_rows(db_session, b_id, "B")

    async with scoped:
        body = (await scoped.get("/api/v1/regressions")).json()

    assert {r["application_id"] for r in body["items"]} == {a_id}
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_alerts_are_limited_to_the_keys_own_application(
    client: AsyncClient, app, db_session: AsyncSession
) -> None:
    scoped, a_id = await _scoped_client(client, app, "iso-a4")
    now = datetime.now(UTC)
    for service in (
        "app:iso-a4",
        f"rollout:{a_id}",
        "app:someone-else",
        "rollout:other-app",
        "sentinel-api",
    ):
        db_session.add(
            Alert(
                rule="r",
                current_value=1.0,
                threshold=0.5,
                severity="high",
                affected_service=service,
                timestamp=now,
            )
        )
    await db_session.commit()

    async with scoped:
        body = (await scoped.get("/api/v1/alerts")).json()

    assert {a["affected_service"] for a in body["items"]} == {"app:iso-a4", f"rollout:{a_id}"}
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_unscoped_keys_still_see_everything(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _tenant_rows(db_session, "tenant-1", "A")
    await _tenant_rows(db_session, "tenant-2", "B")

    assert (await client.get("/api/v1/evaluations")).json()["total"] == 2
    assert (await client.get("/api/v1/routing/decisions")).json()["total"] == 2
    assert (await client.get("/api/v1/regressions")).json()["total"] == 2


async def _experiment_fixtures(admin: AsyncClient) -> tuple[str, int]:
    dataset = await admin.post(
        "/api/v1/datasets",
        json={
            "name": "iso-ds",
            "version": "v1",
            "records": [{"question": "q1", "context": "c1", "expected_answer": "a1"}],
        },
    )
    prompt = await admin.post(
        "/api/v1/prompts",
        json={"prompt_id": "iso-p", "template": "{{context}} {{question}}", "variables": []},
    )
    return dataset.json()["id"], prompt.json()["version"]


@pytest.mark.asyncio
async def test_a_scoped_key_cannot_run_experiments_into_another_application(
    client: AsyncClient, app, seeded_models: AsyncSession
) -> None:
    dataset_id, version = await _experiment_fixtures(client)
    scoped, _ = await _scoped_client(client, app, "iso-a5")

    async with scoped:
        resp = await scoped.post(
            "/api/v1/experiments/run",
            json={
                "name": "e",
                "model": "mock:sentinel-flash",
                "prompt_id": "iso-p",
                "prompt_version": version,
                "dataset_id": dataset_id,
                "sample_size": 1,
                "application_id": "victim-app",
            },
        )

    assert resp.status_code == 403
    assert (await client.get("/api/v1/traces", params={"application_id": "victim-app"})).json()[
        "total"
    ] == 0


@pytest.mark.asyncio
async def test_a_scoped_keys_experiments_default_to_its_own_application(
    client: AsyncClient, app, seeded_models: AsyncSession
) -> None:
    dataset_id, version = await _experiment_fixtures(client)
    scoped, a_id = await _scoped_client(client, app, "iso-a6")

    async with scoped:
        resp = await scoped.post(
            "/api/v1/experiments/run",
            json={
                "name": "e",
                "model": "mock:sentinel-flash",
                "prompt_id": "iso-p",
                "prompt_version": version,
                "dataset_id": dataset_id,
                "sample_size": 1,
            },
        )
        own = (await scoped.get("/api/v1/traces")).json()

    assert resp.status_code == 201
    assert own["total"] == 1
    assert own["items"][0]["application_id"] == a_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "post",
            "/api/v1/models",
            {
                "id": "x:y",
                "name": "y",
                "provider": "x",
                "input_price_per_1k": 0.1,
                "output_price_per_1k": 0.1,
            },
        ),
        ("patch", "/api/v1/models/mock:sentinel-flash", {"status": "down"}),
        ("patch", "/api/v1/alerts/rules/error_rate", {"threshold": 0.99}),
        ("post", "/api/v1/prompts", {"prompt_id": "p", "template": "t"}),
        ("patch", "/api/v1/prompts/p/versions/1", {"status": "production"}),
        ("post", "/api/v1/prompts/p/versions/1/promote", {}),
        ("post", "/api/v1/datasets", {"name": "n", "version": "v", "records": []}),
    ],
)
async def test_scoped_keys_cannot_change_shared_platform_configuration(
    client: AsyncClient, app, seeded_models: AsyncSession, method: str, path: str, body: dict
) -> None:
    """Models, alert thresholds, prompts and datasets are shared by every
    tenant — one tenant flipping a model to `down` reroutes all of them."""
    scoped, _ = await _scoped_client(client, app, f"iso-cfg-{method}-{abs(hash(path)) % 9999}")

    async with scoped:
        resp = await getattr(scoped, method)(path, json=body)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_scoped_key_can_still_read_the_shared_catalogs(
    client: AsyncClient, app, seeded_models: AsyncSession
) -> None:
    scoped, _ = await _scoped_client(client, app, "iso-read")
    async with scoped:
        assert (await scoped.get("/api/v1/models")).status_code == 200
        assert (await scoped.get("/api/v1/prompts")).status_code == 200
        assert (await scoped.get("/api/v1/alerts/rules")).status_code == 200


def _trace_payload(trace_id: str, application_id: str) -> dict:
    return {
        "trace_id": trace_id,
        "application_id": application_id,
        "model": "mock:sentinel-flash",
        "provider": "mock",
        "prompt": "mine",
        "response": "mine",
        "evaluate": False,
    }


@pytest.mark.asyncio
async def test_ingesting_another_tenants_trace_id_does_not_return_their_trace(
    client: AsyncClient, app, db_session: AsyncSession
) -> None:
    """`POST /traces` is idempotent on `trace_id` and returned the *existing*
    trace — whoever owned it. Any scoped key that learned an id (it appears in
    logs, CSV exports, the dashboard) could read the other tenant's prompt."""
    scoped, a_id = await _scoped_client(client, app, "iso-a7")
    victim_trace = await _tenant_rows(db_session, "victim-app", "VICTIM")

    async with scoped:
        resp = await scoped.post("/api/v1/traces", json=_trace_payload(victim_trace, a_id))

    assert resp.status_code == 409
    assert "VICTIM" not in resp.text


@pytest.mark.asyncio
async def test_ingest_is_still_idempotent_within_one_application(client: AsyncClient) -> None:
    payload = _trace_payload("trc_same_app_replay", "app-x")
    first = await client.post("/api/v1/traces", json=payload)
    second = await client.post("/api/v1/traces", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
