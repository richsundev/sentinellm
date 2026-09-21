"""`/generate` serves prompts from the registry: the template for the requested
(or current production) version is rendered server-side, the model sees it, and
the trace records exactly which version produced the answer."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.llm.base import LLMRequest
from sentinellm.llm.mock_provider import MockProvider

_FLASH = "mock:sentinel-flash"
_DOCS = [{"doc_id": "d1", "content": "Refunds within 30 days.", "score": 1.0, "rank": 0}]


async def _prompt(client: AsyncClient, template: str, *, status: str = "production", **kw) -> dict:
    resp = await client.post(
        "/api/v1/prompts",
        json={"prompt_id": "support", "template": template, "status": status, **kw},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _gen(**over: object) -> dict:
    return {
        "application_id": "serve-app",
        "question": "What is the refund policy?",
        "preferred_model": _FLASH,
        "prompt_id": "support",
        "prompt_variables": {},
        "retrieved_documents": _DOCS,
        "use_cache": False,
        "evaluate": False,
        **over,
    }


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[LLMRequest]:
    calls: list[LLMRequest] = []
    original = MockProvider.complete

    async def spy(self: MockProvider, request: LLMRequest):
        calls.append(request)
        return await original(self, request)

    monkeypatch.setattr(MockProvider, "complete", spy)
    return calls


def _system(calls: list[LLMRequest]) -> str:
    return next(m.content for m in calls[-1].messages if m.role == "system")


@pytest.mark.asyncio
async def test_the_production_template_is_rendered_and_sent_to_the_model(
    client: AsyncClient, seeded_models: AsyncSession, seen: list[LLMRequest]
) -> None:
    await _prompt(client, "For {{audience}}: answer {{question}} using {{context}}.")

    resp = await client.post("/api/v1/generate", json=_gen(prompt_variables={"audience": "admins"}))

    assert resp.status_code == 200
    trace = resp.json()
    expected = "For admins: answer What is the refund policy? using Refunds within 30 days.."
    assert _system(seen) == expected
    assert seen[-1].messages[-1].role == "user"
    assert seen[-1].messages[-1].content == "What is the refund policy?"
    assert trace["prompt"] == "What is the refund policy?"  # the question, not the template
    assert trace["prompt_id"] == "support"
    assert trace["prompt_version"] == 1
    assert trace["metadata"]["rendered_prompt"] == expected
    assert trace["metadata"]["prompt_variables"] == {"audience": "admins"}


@pytest.mark.asyncio
async def test_the_newest_production_version_is_served_unless_one_is_requested(
    client: AsyncClient, seeded_models: AsyncSession, seen: list[LLMRequest]
) -> None:
    await _prompt(client, "v1 {{question}}")
    await _prompt(client, "v2 {{question}}")
    await _prompt(client, "v3 draft {{question}}", status="draft")

    default = (await client.post("/api/v1/generate", json=_gen())).json()
    assert default["prompt_version"] == 2
    assert _system(seen).startswith("v2 ")

    pinned = (await client.post("/api/v1/generate", json=_gen(prompt_version=1))).json()
    assert pinned["prompt_version"] == 1
    assert _system(seen).startswith("v1 ")

    draft = (await client.post("/api/v1/generate", json=_gen(prompt_version=3))).json()
    assert draft["prompt_version"] == 3  # a draft is servable when asked for by number


@pytest.mark.asyncio
async def test_a_missing_prompt_or_version_is_a_404(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    none = await client.post("/api/v1/generate", json=_gen(prompt_id="ghost"))
    assert none.status_code == 404
    assert "no production version" in none.json()["detail"]

    await _prompt(client, "hi {{question}}")
    bad_version = await client.post("/api/v1/generate", json=_gen(prompt_version=9))
    assert bad_version.status_code == 404


@pytest.mark.asyncio
async def test_a_template_variable_nobody_supplied_is_a_422_naming_it(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _prompt(client, "Hi {{name}}, {{question}}")

    resp = await client.post("/api/v1/generate", json=_gen())

    assert resp.status_code == 422
    assert "name" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_prompt_variables_require_a_prompt_id(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.post("/api/v1/generate", json=_gen(prompt_id=None))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_supplying_no_prompt_variables_keeps_prompt_id_a_plain_tag(
    client: AsyncClient, seeded_models: AsyncSession, seen: list[LLMRequest]
) -> None:
    """Existing callers pass `prompt_id` purely as a label; that must not start
    rendering (or failing on a missing production version)."""
    body = _gen(prompt_id="just-a-label", prompt_version=7)
    del body["prompt_variables"]

    resp = await client.post("/api/v1/generate", json=body)

    assert resp.status_code == 200
    assert resp.json()["prompt_version"] == 7
    assert "rendered_prompt" not in resp.json()["metadata"]


@pytest.mark.asyncio
async def test_a_value_containing_a_placeholder_is_not_expanded(
    client: AsyncClient, seeded_models: AsyncSession, seen: list[LLMRequest]
) -> None:
    await _prompt(client, "A={{a}} B={{b}}")

    await client.post("/api/v1/generate", json=_gen(prompt_variables={"a": "{{b}}", "b": "secret"}))

    assert _system(seen) == "A={{b}} B=secret"


@pytest.mark.asyncio
async def test_an_explicit_system_prompt_is_kept_in_front_of_the_rendered_template(
    client: AsyncClient, seeded_models: AsyncSession, seen: list[LLMRequest]
) -> None:
    await _prompt(client, "TEMPLATE {{question}}")

    await client.post("/api/v1/generate", json=_gen(system_prompt="Be brief."))

    assert _system(seen) == "Be brief.\n\nTEMPLATE What is the refund policy?"


@pytest.mark.asyncio
async def test_cached_answers_are_not_shared_across_prompt_versions(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _prompt(client, "v1 {{question}}")
    await _prompt(client, "v2 {{question}}")
    cached = _gen(use_cache=True)

    first = await client.post("/api/v1/generate", json={**cached, "prompt_version": 1})
    other_version = await client.post("/api/v1/generate", json={**cached, "prompt_version": 2})
    same_version = await client.post("/api/v1/generate", json={**cached, "prompt_version": 1})

    assert first.json()["cache_hit"] is False
    assert other_version.json()["cache_hit"] is False
    assert same_version.json()["cache_hit"] is True


@pytest.mark.asyncio
async def test_replay_reproduces_the_version_and_variables_and_can_change_the_version(
    client: AsyncClient, seeded_models: AsyncSession, seen: list[LLMRequest]
) -> None:
    await _prompt(client, "v1 {{tone}} {{question}}")
    await _prompt(client, "v2 {{tone}} {{question}}")
    original = (
        await client.post(
            "/api/v1/generate", json=_gen(prompt_version=1, prompt_variables={"tone": "formal"})
        )
    ).json()

    same = (await client.post(f"/api/v1/traces/{original['trace_id']}/replay", json={})).json()
    assert same["prompt_version"] == 1
    assert _system(seen).startswith("v1 formal ")
    assert same["metadata"]["prompt_variables"] == {"tone": "formal"}

    newer = (
        await client.post(
            f"/api/v1/traces/{original['trace_id']}/replay", json={"prompt_version": 2}
        )
    ).json()
    assert newer["prompt_version"] == 2
    assert _system(seen).startswith("v2 formal ")
    assert newer["metadata"]["rendered_prompt"].startswith("v2 formal ")


@pytest.mark.asyncio
async def test_the_stored_rendered_prompt_is_redacted_when_pii_redaction_is_on(
    client: AsyncClient,
    seeded_models: AsyncSession,
    seen: list[LLMRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "pii_redaction_enabled", True)
    await _prompt(client, "Contact {{who}}: {{question}}")

    resp = await client.post(
        "/api/v1/generate", json=_gen(prompt_variables={"who": "jane.doe@example.com"})
    )

    assert "jane.doe@example.com" in _system(seen)  # the model still sees it
    meta = resp.json()["metadata"]
    assert "jane.doe@example.com" not in meta["rendered_prompt"]
    assert "jane.doe@example.com" not in str(meta["prompt_variables"])


@pytest.mark.asyncio
async def test_the_preview_endpoint_renders_without_calling_a_model(
    client: AsyncClient, seen: list[LLMRequest]
) -> None:
    await _prompt(client, "Hi {{name}}")

    resp = await client.post(
        "/api/v1/prompts/support/versions/1/render", json={"variables": {"name": "Ana"}}
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "prompt_id": "support",
        "version": 1,
        "rendered": "Hi Ana",
        "missing": [],
    }
    assert seen == []

    missing = await client.post("/api/v1/prompts/support/versions/1/render", json={"variables": {}})
    assert missing.status_code == 200
    assert missing.json()["missing"] == ["name"]
    assert missing.json()["rendered"] is None


@pytest.mark.asyncio
async def test_experiments_serve_the_template_once_through_the_same_path(
    client: AsyncClient, seeded_models: AsyncSession, seen: list[LLMRequest]
) -> None:
    """The runner used to render the template itself, pass it as a system prompt
    *and* attach the context, so the model saw the context twice."""
    await _prompt(client, "T {{question}} | {{context}}")
    dataset = (
        await client.post(
            "/api/v1/datasets",
            json={
                "name": "d",
                "version": "1",
                "records": [{"question": "q1", "context": "ctx1", "expected_answer": "a"}],
            },
        )
    ).json()

    resp = await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "e",
            "model": _FLASH,
            "prompt_id": "support",
            "prompt_version": 1,
            "dataset_id": dataset["id"],
        },
    )

    assert resp.status_code == 201, resp.text
    # seen[0] is the generation; later calls are the LLM judge scoring it.
    assert _system(seen[:1]) == "T q1 | ctx1"
    traces = (
        await client.get("/api/v1/traces", params={"application_id": "experiment-runner"})
    ).json()["items"]
    assert traces[0]["metadata"]["rendered_prompt"] == "T q1 | ctx1"
    assert traces[0]["prompt_version"] == 1


@pytest.mark.asyncio
async def test_a_versions_declared_variables_are_derived_from_its_template(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/prompts", json={"prompt_id": "auto", "template": "{{ a }} and {{b}} and {{a}}"}
    )

    assert resp.status_code == 201
    assert resp.json()["variables"] == ["a", "b"]


@pytest.mark.asyncio
async def test_a_template_using_an_undeclared_variable_is_rejected_when_created(
    client: AsyncClient,
) -> None:
    """It could only ever fail later, at serve time, for every caller."""
    resp = await client.post(
        "/api/v1/prompts",
        json={"prompt_id": "bad", "template": "{{a}} {{b}}", "variables": ["a"]},
    )

    assert resp.status_code == 422
    assert "b" in resp.text
