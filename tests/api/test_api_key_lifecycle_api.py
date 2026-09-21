"""API keys can be issued with a lifetime, revoked, and rotated — until now a
leaked key could not be revoked at all (`revoked` had no endpoint)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import APIKey


def _as(app, key: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t", headers={"X-API-Key": key}
    )


async def _application(client: AsyncClient, name: str) -> str:
    return (await client.post("/api/v1/applications", json={"name": name})).json()["id"]


async def _key(client: AsyncClient, application_id: str, **over: object) -> dict:
    resp = await client.post(
        "/api/v1/applications/api-keys",
        json={"application_id": application_id, "name": "k", **over},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _row(session: AsyncSession, key_id: str) -> APIKey:
    session.expire_all()
    return (await session.execute(select(APIKey).where(APIKey.id == key_id))).scalar_one()


@pytest.mark.asyncio
async def test_a_key_can_be_issued_with_a_lifetime(client: AsyncClient) -> None:
    app_id = await _application(client, "lifetime")

    key = await _key(client, app_id, expires_in_days=30)

    listed = (await client.get("/api/v1/applications/api-keys", params={"limit": 200})).json()
    row = next(k for k in listed["items"] if k["id"] == key["id"])
    expires = datetime.fromisoformat(row["expires_at"])
    assert (
        timedelta(days=29, hours=23)
        < expires - datetime.now(UTC).replace(tzinfo=None)
        < timedelta(days=30, hours=1)
    )
    assert row["revoked_at"] is None


@pytest.mark.asyncio
async def test_an_expired_key_stops_authenticating(
    app, client: AsyncClient, db_session: AsyncSession
) -> None:
    app_id = await _application(client, "expiring")
    key = await _key(client, app_id, role="read")
    async with _as(app, key["plaintext_key"]) as as_key:
        assert (await as_key.get("/api/v1/traces")).status_code == 200

        row = await _row(db_session, key["id"])
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()

        resp = await as_key.get("/api/v1/traces")
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_revoked_key_stops_working_at_once(app, client: AsyncClient) -> None:
    app_id = await _application(client, "revocable")
    key = await _key(client, app_id, role="read")
    async with _as(app, key["plaintext_key"]) as as_key:
        assert (await as_key.get("/api/v1/traces")).status_code == 200

        revoked = await client.post(f"/api/v1/applications/api-keys/{key['id']}/revoke")

        assert revoked.status_code == 200
        body = revoked.json()
        assert body["revoked"] is True and body["revoked_at"] is not None
        assert (await as_key.get("/api/v1/traces")).status_code == 401
    # idempotent
    assert (
        await client.post(f"/api/v1/applications/api-keys/{key['id']}/revoke")
    ).status_code == 200


@pytest.mark.asyncio
async def test_a_key_cannot_revoke_itself_and_unknown_keys_are_404(
    app, client: AsyncClient
) -> None:
    app_id = await _application(client, "selfish")
    key = await _key(client, app_id, role="admin")
    async with _as(app, key["plaintext_key"]) as admin:
        own = await admin.post(f"/api/v1/applications/api-keys/{key['id']}/revoke")
        assert own.status_code == 409
        assert "rotate" in own.json()["detail"]
        assert (await admin.get("/api/v1/traces")).status_code == 200  # still alive

    assert (
        await client.post("/api/v1/applications/api-keys/does-not-exist/revoke")
    ).status_code == 404


@pytest.mark.asyncio
async def test_only_admins_can_revoke_and_scoped_admins_only_their_own_application(
    app, client: AsyncClient
) -> None:
    mine = await _application(client, "mine")
    theirs = await _application(client, "theirs")
    my_admin = await _key(client, mine, role="admin", scoped_to_application=True)
    my_writer = await _key(client, mine, role="write")
    their_key = await _key(client, theirs, role="read")
    sibling = await _key(client, mine, role="read")

    async with _as(app, my_writer["plaintext_key"]) as writer:
        denied = await writer.post(f"/api/v1/applications/api-keys/{sibling['id']}/revoke")
        assert denied.status_code == 403

    async with _as(app, my_admin["plaintext_key"]) as scoped:
        other = await scoped.post(f"/api/v1/applications/api-keys/{their_key['id']}/revoke")
        assert other.status_code == 404  # not even visible to it
        ok = await scoped.post(f"/api/v1/applications/api-keys/{sibling['id']}/revoke")
        assert ok.status_code == 200


@pytest.mark.asyncio
async def test_rotation_returns_a_replacement_and_retires_the_old_key(
    app, client: AsyncClient
) -> None:
    app_id = await _application(client, "rotating")
    old = await _key(client, app_id, role="write", scoped_to_application=True)

    rotated = await client.post(f"/api/v1/applications/api-keys/{old['id']}/rotate", json={})

    assert rotated.status_code == 201
    new = rotated.json()
    assert new["id"] != old["id"] and new["plaintext_key"] != old["plaintext_key"]
    assert (new["role"], new["scoped_to_application"]) == ("write", True)
    async with _as(app, old["plaintext_key"]) as as_old, _as(app, new["plaintext_key"]) as as_new:
        assert (await as_old.get("/api/v1/traces")).status_code == 401
        assert (await as_new.get("/api/v1/traces")).status_code == 200


@pytest.mark.asyncio
async def test_rotation_with_a_grace_period_keeps_the_old_key_until_it_lapses(
    app, client: AsyncClient, db_session: AsyncSession
) -> None:
    """Clients need time to pick up the new key; revoking instantly would break
    them before they could."""
    app_id = await _application(client, "graceful")
    old = await _key(client, app_id, role="read")

    new = (
        await client.post(
            f"/api/v1/applications/api-keys/{old['id']}/rotate", json={"grace_minutes": 30}
        )
    ).json()

    row = await _row(db_session, old["id"])
    assert row.revoked is False
    remaining = row.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)
    assert timedelta(minutes=29) < remaining < timedelta(minutes=31)
    async with _as(app, old["plaintext_key"]) as as_old, _as(app, new["plaintext_key"]) as as_new:
        assert (await as_old.get("/api/v1/traces")).status_code == 200
        assert (await as_new.get("/api/v1/traces")).status_code == 200
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
        assert (await as_old.get("/api/v1/traces")).status_code == 401


@pytest.mark.asyncio
async def test_a_key_can_rotate_itself(app, client: AsyncClient) -> None:
    app_id = await _application(client, "self-rotating")
    key = await _key(client, app_id, role="admin")
    async with _as(app, key["plaintext_key"]) as admin:
        resp = await admin.post(f"/api/v1/applications/api-keys/{key['id']}/rotate", json={})
        assert resp.status_code == 201
    async with _as(app, resp.json()["plaintext_key"]) as fresh:
        assert (await fresh.get("/api/v1/traces")).status_code == 200


@pytest.mark.asyncio
async def test_last_used_is_recorded_but_not_written_on_every_request(
    app, client: AsyncClient, db_session: AsyncSession
) -> None:
    """Every authenticated request used to issue an UPDATE (and a flush) just to
    bump a timestamp — a write per read on the hottest path."""
    app_id = await _application(client, "usage")
    key = await _key(client, app_id, role="read")
    async with _as(app, key["plaintext_key"]) as as_key:
        await as_key.get("/api/v1/traces")
        first = (await _row(db_session, key["id"])).last_used_at
        assert first is not None

        await as_key.get("/api/v1/traces")
        assert (await _row(db_session, key["id"])).last_used_at == first  # within the interval

        row = await _row(db_session, key["id"])
        row.last_used_at = datetime.now(UTC) - timedelta(minutes=10)
        await db_session.commit()
        await as_key.get("/api/v1/traces")
        assert (await _row(db_session, key["id"])).last_used_at > first - timedelta(minutes=1)
        assert (await _row(db_session, key["id"])).last_used_at.replace(tzinfo=UTC) > datetime.now(
            UTC
        ) - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_key_lifetimes_are_bounded(client: AsyncClient) -> None:
    app_id = await _application(client, "bounds")
    for bad in (0, -1, 100_000):
        resp = await client.post(
            "/api/v1/applications/api-keys",
            json={"application_id": app_id, "expires_in_days": bad},
        )
        assert resp.status_code == 422
    key = await _key(client, app_id)
    for body in ({"grace_minutes": -1}, {"grace_minutes": 10**9}, {"expires_in_days": 0}):
        resp = await client.post(f"/api/v1/applications/api-keys/{key['id']}/rotate", json=body)
        assert resp.status_code == 422
