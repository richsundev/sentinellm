"""Every read endpoint, given hostile-but-plausible query parameters, must answer
with a 2xx/4xx — never a 5xx. (SQLite happily accepts inputs that Postgres
rejects, so this also guards the values that reach the database.)"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from sentinellm.core.config import get_settings

_HOSTILE_VALUES = [
    "",
    "0",
    "-1",
    "1e400",
    "99999999999999999999",
    "%",
    "_",
    "\\",
    "'; DROP TABLE traces; --",
    "🙂" * 300,
    "x" * 5000,
    "../../etc/passwd",
    "null",
]


def _read_operations(app) -> list[tuple[str, list[str], list[str]]]:
    """(path template, query parameter names, path parameter names) per GET.
    Read from the OpenAPI schema so routers of any nesting are covered."""
    operations = []
    for path, item in app.openapi()["paths"].items():
        get = item.get("get")
        if get is None or path in {"/metrics"}:
            continue
        params = get.get("parameters", [])
        operations.append(
            (
                path,
                [p["name"] for p in params if p["in"] == "query"],
                [p["name"] for p in params if p["in"] == "path"],
            )
        )
    return operations


@pytest.mark.asyncio
async def test_read_endpoints_never_return_a_server_error(
    app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 10**6)  # thousands of requests
    failures: list[str] = []
    seen = 0
    for template, query_names, path_names in _read_operations(app):
        neutral = template
        for name in path_names:
            neutral = neutral.replace("{" + name + "}", "x")
        for value in _HOSTILE_VALUES:
            # every query parameter at once...
            params = dict.fromkeys(query_names, value)
            resp = await client.get(neutral, params=params)
            seen += 1
            if resp.status_code >= 500:
                failures.append(f"GET {neutral} {params!r:.80} -> {resp.status_code}")
            # ...and the path parameters
            if path_names and value and "/" not in value and "?" not in value and "#" not in value:
                hostile = template
                for name in path_names:
                    hostile = hostile.replace("{" + name + "}", value)
                seen += 1
                if (await client.get(hostile)).status_code >= 500:
                    failures.append(f"GET {hostile[:80]} -> 5xx")
    assert seen > 200, "the fuzz didn't actually run"
    assert not failures, "\n".join(failures[:20])
