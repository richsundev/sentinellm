"""Prompt canary rollouts: management API, tenant scoping, and how a running
rollout decides which version `/generate` serves."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.llm.base import LLMRequest
from sentinellm.llm.mock_provider import MockProvider

_FLASH = "mock:sentinel-flash"


async def _versions(client: AsyncClient, *statuses: str) -> None:
    for i, status in enumerate(statuses, start=1):
        resp = await client.post(
            "/api/v1/prompts",
            json={"prompt_id": "support", "template": f"v{i} {{{{question}}}}", "status": status},
        )
        assert resp.status_code == 201


def _body(**over: object) -> dict:
    return {
        "application_id": "canary-app",
        "prompt_id": "support",
        "incumbent_version": 1,
        "challenger_version": 2,
        **over,
    }


def _gen(**over: object) -> dict:
    return {
        "application_id": "canary-app",
        "question": "hello",
        "preferred_model": _FLASH,
        "prompt_id": "support",
        "prompt_variables": {},
        "use_cache": False,
        "evaluate": False,
        **over,
    }


@pytest.mark.asyncio
async def test_create_get_and_list(client: AsyncClient) -> None:
    await _versions(client, "production", "testing")

    created = await client.post("/api/v1/prompt-rollouts", json=_body(initial_pct=20))
    assert created.status_code == 201
    rollout = created.json()
    assert (rollout["stage"], rollout["traffic_pct"]) == ("running", 20.0)

    detail = (await client.get(f"/api/v1/prompt-rollouts/{rollout['id']}")).json()
    assert detail["incumbent_stats"]["version"] == 1
    assert detail["challenger_stats"] == {
        "version": 2,
        "request_count": 0,
        "error_rate": 0.0,
        "avg_quality": None,
        "avg_latency_ms": 0.0,
        "avg_cost": 0.0,
    }
    listed = (await client.get("/api/v1/prompt-rollouts", params={"prompt_id": "support"})).json()
    assert [r["id"] for r in listed["items"]] == [rollout["id"]]


@pytest.mark.asyncio
async def test_rollouts_need_two_distinct_existing_versions(client: AsyncClient) -> None:
    await _versions(client, "production", "testing")

    assert (
        await client.post("/api/v1/prompt-rollouts", json=_body(challenger_version=1))
    ).status_code == 422
    assert (
        await client.post("/api/v1/prompt-rollouts", json=_body(challenger_version=9))
    ).status_code == 404
    assert (
        await client.post("/api/v1/prompt-rollouts", json=_body(prompt_id="ghost"))
    ).status_code == 404
    assert (
        await client.post("/api/v1/prompt-rollouts", json=_body(initial_pct=60, max_pct=50))
    ).status_code == 422


@pytest.mark.asyncio
async def test_only_one_active_rollout_per_application_and_prompt(client: AsyncClient) -> None:
    await _versions(client, "production", "testing")
    first = (await client.post("/api/v1/prompt-rollouts", json=_body())).json()

    dup = await client.post("/api/v1/prompt-rollouts", json=_body())
    assert dup.status_code == 409

    other_app = await client.post("/api/v1/prompt-rollouts", json=_body(application_id="other"))
    assert other_app.status_code == 201  # a different application is independent

    await client.post(f"/api/v1/prompt-rollouts/{first['id']}/rollback")
    again = await client.post("/api/v1/prompt-rollouts", json=_body())
    assert again.status_code == 201


@pytest.mark.asyncio
async def test_operator_actions_move_the_stage(client: AsyncClient) -> None:
    await _versions(client, "production", "testing")
    rid = (await client.post("/api/v1/prompt-rollouts", json=_body())).json()["id"]
    base = f"/api/v1/prompt-rollouts/{rid}"

    assert (await client.post(f"{base}/resume")).status_code == 400  # not paused
    assert (await client.post(f"{base}/pause")).json()["stage"] == "paused"
    assert (await client.post(f"{base}/pause")).status_code == 400
    assert (await client.post(f"{base}/resume")).json()["stage"] == "running"

    promoted = (await client.post(f"{base}/promote")).json()
    assert (promoted["stage"], promoted["traffic_pct"]) == ("promoted", 100.0)
    assert "manually promoted" in promoted["outcome_reason"]
    assert (await client.post(f"{base}/rollback")).status_code == 400  # already finished


@pytest.mark.asyncio
async def test_a_scoped_key_only_sees_and_controls_its_own_applications_rollouts(
    app, client: AsyncClient
) -> None:
    await _versions(client, "production", "testing")
    mine_app = (await client.post("/api/v1/applications", json={"name": "mine"})).json()["id"]
    key = (
        await client.post(
            "/api/v1/applications/api-keys",
            json={
                "application_id": mine_app,
                "name": "scoped",
                "role": "write",
                "scoped_to_application": True,
            },
        )
    ).json()["plaintext_key"]
    theirs = (
        await client.post("/api/v1/prompt-rollouts", json=_body(application_id="someone-else"))
    ).json()
    mine = (
        await client.post("/api/v1/prompt-rollouts", json=_body(application_id=mine_app))
    ).json()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t", headers={"X-API-Key": key}
    ) as scoped:
        listed = (await scoped.get("/api/v1/prompt-rollouts")).json()
        assert [r["id"] for r in listed["items"]] == [mine["id"]]
        assert (await scoped.get(f"/api/v1/prompt-rollouts/{theirs['id']}")).status_code == 404
        assert (
            await scoped.post(f"/api/v1/prompt-rollouts/{theirs['id']}/pause")
        ).status_code == 404
        forbidden = await scoped.post(
            "/api/v1/prompt-rollouts", json=_body(application_id="someone-else")
        )
        assert forbidden.status_code == 403


# --- how /generate uses a rollout ---------------------------------------------


@pytest.fixture
def systems(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    original = MockProvider.complete

    async def spy(self: MockProvider, request: LLMRequest):
        seen.append(next(m.content for m in request.messages if m.role == "system"))
        return await original(self, request)

    monkeypatch.setattr(MockProvider, "complete", spy)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("pct,expected_version,arm", [(100, 2, "challenger"), (0, 1, "incumbent")])
async def test_traffic_share_decides_the_served_version(
    client: AsyncClient,
    seeded_models: AsyncSession,
    systems: list[str],
    pct: float,
    expected_version: int,
    arm: str,
) -> None:
    await _versions(client, "production", "testing")
    rollout = (await client.post("/api/v1/prompt-rollouts", json=_body(initial_pct=pct))).json()

    trace = (await client.post("/api/v1/generate", json=_gen())).json()

    assert trace["prompt_version"] == expected_version
    assert systems[-1].startswith(f"v{expected_version} ")
    assert trace["metadata"]["prompt_rollout_id"] == rollout["id"]
    assert trace["metadata"]["prompt_rollout_arm"] == arm


@pytest.mark.asyncio
async def test_a_split_sends_a_share_of_traffic_to_each_version(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _versions(client, "production", "testing")
    await client.post("/api/v1/prompt-rollouts", json=_body(initial_pct=50))

    versions = [
        (await client.post("/api/v1/generate", json=_gen(question=f"q{i}"))).json()[
            "prompt_version"
        ]
        for i in range(16)
    ]

    assert 1 in versions and 2 in versions


@pytest.mark.asyncio
async def test_an_explicit_version_bypasses_the_rollout(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _versions(client, "production", "testing")
    await client.post("/api/v1/prompt-rollouts", json=_body(initial_pct=100))

    trace = (await client.post("/api/v1/generate", json=_gen(prompt_version=1))).json()

    assert trace["prompt_version"] == 1
    assert "prompt_rollout_id" not in trace["metadata"]


@pytest.mark.asyncio
async def test_other_applications_and_plain_tag_requests_are_unaffected(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _versions(client, "production", "testing")
    await client.post("/api/v1/prompt-rollouts", json=_body(initial_pct=100))

    other = (await client.post("/api/v1/generate", json=_gen(application_id="not-canary"))).json()
    assert other["prompt_version"] == 1  # the production version

    tag_only = _gen(prompt_version=None)
    del tag_only["prompt_variables"]
    tagged = (await client.post("/api/v1/generate", json=tag_only)).json()
    assert tagged["prompt_version"] is None  # `prompt_id` alone is still just a label


@pytest.mark.asyncio
async def test_a_terminal_rollout_keeps_pinning_the_application(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _versions(client, "production", "testing")
    rid = (await client.post("/api/v1/prompt-rollouts", json=_body(initial_pct=50))).json()["id"]

    await client.post(f"/api/v1/prompt-rollouts/{rid}/promote")
    promoted = {
        (await client.post("/api/v1/generate", json=_gen(question=f"a{i}"))).json()[
            "prompt_version"
        ]
        for i in range(6)
    }
    assert promoted == {2}

    newer = (
        await client.post(
            "/api/v1/prompt-rollouts",
            json=_body(incumbent_version=2, challenger_version=1, initial_pct=0),
        )
    ).json()
    assert newer["stage"] == "running"
    after = {
        (await client.post("/api/v1/generate", json=_gen(question=f"b{i}"))).json()[
            "prompt_version"
        ]
        for i in range(6)
    }
    assert after == {2}  # the newer rollout (0% to v1) supersedes the old pin


@pytest.mark.asyncio
async def test_a_deprecated_challenger_cannot_be_rolled_out(client: AsyncClient) -> None:
    """The worker rolls a deprecated challenger back on its first pass, so
    starting one is only ever a rollout that dies immediately (and alerts)."""
    await _versions(client, "production", "deprecated")

    resp = await client.post("/api/v1/prompt-rollouts", json=_body())

    assert resp.status_code == 409
    assert "deprecated" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_deprecated_incumbent_is_fine_it_is_being_replaced(client: AsyncClient) -> None:
    await _versions(client, "deprecated", "testing")

    assert (await client.post("/api/v1/prompt-rollouts", json=_body())).status_code == 201


@pytest.mark.asyncio
async def test_prompt_templates_and_declared_variables_are_bounded(client: AsyncClient) -> None:
    huge = await client.post(
        "/api/v1/prompts", json={"prompt_id": "big", "template": "x" * 300_000}
    )
    many = await client.post(
        "/api/v1/prompts",
        json={"prompt_id": "many", "template": "t", "variables": [f"v{i}" for i in range(80)]},
    )
    long_name = await client.post(
        "/api/v1/prompts", json={"prompt_id": "long", "template": "t", "variables": ["v" * 80]}
    )

    assert huge.status_code == 422
    assert many.status_code == 422
    assert long_name.status_code == 422
