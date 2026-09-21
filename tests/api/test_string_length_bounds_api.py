"""Postgres enforces `VARCHAR(n)`; SQLite (the test database) does not. An
over-long identifier used to be stored happily in tests and 500 in production."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _ingest(**over: object) -> dict:
    return {
        "application_id": "len-app",
        "model": "mock:sentinel-flash",
        "provider": "mock",
        "prompt": "q",
        "response": "a",
        "evaluate": False,
        **over,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,limit",
    [
        ("trace_id", 64),
        ("request_id", 64),
        ("application_id", 200),
        ("environment", 50),
        ("model", 100),
        ("provider", 50),
        ("prompt_id", 200),
    ],
)
async def test_ingest_rejects_identifiers_longer_than_their_column(
    client: AsyncClient, field: str, limit: int
) -> None:
    ok = await client.post("/api/v1/traces", json=_ingest(**{field: "x" * limit}))
    too_long = await client.post("/api/v1/traces", json=_ingest(**{field: "x" * (limit + 1)}))

    assert ok.status_code == 201
    assert too_long.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,limit",
    [("application_id", 200), ("environment", 50), ("preferred_model", 100), ("prompt_id", 200)],
)
async def test_generate_rejects_identifiers_longer_than_their_column(
    client: AsyncClient, seeded_models: AsyncSession, field: str, limit: int
) -> None:
    body = {
        "application_id": "len-app",
        "question": "q",
        "preferred_model": "mock:sentinel-flash",
        "use_cache": False,
        "evaluate": False,
    }
    resp = await client.post("/api/v1/generate", json={**body, field: "x" * (limit + 1)})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_rejects_an_overlong_fallback_model_name(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/generate",
        json={"application_id": "a", "question": "q", "fallback_models": ["m" * 101]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/v1/applications", {"name": "n" * 201}),
        ("/api/v1/datasets", {"name": "n" * 201, "version": "1"}),
        ("/api/v1/datasets", {"name": "n", "version": "v" * 51}),
        ("/api/v1/prompts", {"prompt_id": "p" * 201, "template": "t"}),
        ("/api/v1/prompts", {"prompt_id": "p", "template": "t", "author": "a" * 201}),
        (
            "/api/v1/models",
            {
                "id": "x" * 101,
                "name": "n",
                "provider": "p",
                "input_price_per_1k": 0,
                "output_price_per_1k": 0,
            },
        ),
        (
            "/api/v1/models",
            {
                "id": "a:b",
                "name": "n" * 101,
                "provider": "p",
                "input_price_per_1k": 0,
                "output_price_per_1k": 0,
            },
        ),
        (
            "/api/v1/models",
            {
                "id": "a:b",
                "name": "n",
                "provider": "p" * 51,
                "input_price_per_1k": 0,
                "output_price_per_1k": 0,
            },
        ),
    ],
)
async def test_registry_writes_reject_overlong_names(
    client: AsyncClient, path: str, body: dict
) -> None:
    assert (await client.post(path, json=body)).status_code == 422


@pytest.mark.asyncio
async def test_dataset_import_form_fields_are_bounded_too(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/datasets/import",
        data={"name": "n" * 201, "version": "1"},
        files={"file": ("d.jsonl", b'{"question": "q"}\n', "application/x-ndjson")},
    )
    assert resp.status_code == 422
