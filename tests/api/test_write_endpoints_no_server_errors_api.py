"""Every JSON write endpoint, driven from its own OpenAPI schema with hostile
values in each field and each path segment, must answer 2xx/4xx — never 5xx.

SQLite accepts a great deal that Postgres rejects (NUL, over-long strings,
integers past 32 bits), so this pairs with the live fuzz in the audit
checklist; here it guards the validation layer that keeps those values away
from the database in the first place."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from sentinellm.core.config import get_settings

_STRINGS = [
    "",
    " ",
    "x" * 5000,
    "a\x00b",
    "🙂" * 200,
    "%",
    "_",
    "'; DROP TABLE traces; --",
    "../..",
    "{{x}}",
]
_INTS = [0, -1, 2**31, 2**63, 10**30, -(10**30)]
_FLOATS = [-1.0, 1e308, 0.0]
_PATH_VALUES = ["x", "0", "-1", str(2**31), str(10**30), "%", "🙂", "x" * 300, "%00"]


def _resolve(spec: dict, schema: dict) -> dict:
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    if "anyOf" in schema:  # optional fields: pick the first non-null branch
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        return _resolve(spec, non_null[0]) if non_null else {"type": "null"}
    return schema


def _plausible(spec: dict, schema: dict, depth: int = 0) -> Any:
    schema = _resolve(spec, schema)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    match schema.get("type"):
        case "string":
            return "x" * max(1, schema.get("minLength", 1))
        case "integer":
            return max(1, int(schema.get("minimum", 1)))
        case "number":
            return max(1.0, float(schema.get("minimum", 1.0)))
        case "boolean":
            return False
        case "array":
            return []
        case "object" | None:
            if depth > 3:
                return {}
            required = schema.get("required", [])
            return {
                name: _plausible(spec, sub, depth + 1)
                for name, sub in schema.get("properties", {}).items()
                if name in required
            }
    return None


def _hostile_for(spec: dict, schema: dict) -> list[Any]:
    schema = _resolve(spec, schema)
    match schema.get("type"):
        case "string":
            return list(_STRINGS)
        case "integer":
            return list(_INTS)
        case "number":
            return list(_INTS) + list(_FLOATS)
        case "boolean":
            return ["true", 2]
        case "array":
            return [[None], [{}], [_STRINGS[2]] * 3, "nope"]
        case "object":
            return [{"k": "a\x00b"}, {"": 1}, [], "nope"]
    return [None, "x", 1]


def _operations(spec: dict) -> list[tuple[str, str, dict]]:
    ops = []
    for path, item in spec["paths"].items():
        for method in ("post", "patch", "put", "delete"):
            op = item.get(method)
            if op is None:
                continue
            content = op.get("requestBody", {}).get("content", {})
            if content and "application/json" not in content:
                continue  # multipart upload — covered by its own tests
            ops.append((method.upper(), path, op))
    return ops


@pytest.mark.asyncio
async def test_json_write_endpoints_never_return_a_server_error(
    app, client: AsyncClient, seeded_models, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 10**7)
    spec = app.openapi()
    failures: list[str] = []
    sent = 0

    async def send(method: str, path: str, body: Any) -> None:
        nonlocal sent
        sent += 1
        try:
            resp = await client.request(
                method, path, json=body, headers={"Content-Type": "application/json"}
            )
        except Exception as exc:  # the ASGI transport re-raises unhandled app errors
            failures.append(
                f"{method} {path[:70]} body={str(body)[:90]!r} -> {type(exc).__name__}: {str(exc)[:60]}"
            )
            return
        if resp.status_code >= 500:
            failures.append(f"{method} {path[:70]} body={str(body)[:90]!r} -> {resp.status_code}")

    for method, template, op in _operations(spec):
        path_params = [p["name"] for p in op.get("parameters", []) if p["in"] == "path"]
        neutral = template
        for name in path_params:
            neutral = neutral.replace("{" + name + "}", "x")

        body_schema = (
            op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
        )
        base = _plausible(spec, body_schema) if body_schema else None

        await send(method, neutral, base)
        await send(method, neutral, {})  # missing everything
        for value in _PATH_VALUES:
            hostile = template
            for name in path_params:
                hostile = hostile.replace("{" + name + "}", value)
            await send(method, hostile, base)

        if body_schema:
            resolved = _resolve(spec, body_schema)
            for field, sub in resolved.get("properties", {}).items():
                for value in _hostile_for(spec, sub):
                    await send(method, neutral, {**(base or {}), field: value})

    assert sent > 500, "the fuzz didn't actually run"
    assert not failures, f"{len(failures)} server errors:\n" + "\n".join(failures[:25])
