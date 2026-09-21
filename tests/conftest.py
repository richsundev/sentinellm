"""Shared pytest fixtures.

Every test runs against an in-memory (or per-test temp-file) SQLite database
via aiosqlite and the MockProvider/MockEmbeddingProvider — no external
service (Postgres, Redis, a real LLM API) is required to run the suite.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

os.environ.setdefault("SENTINEL_ENV", "test")
os.environ.setdefault("SENTINEL_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SENTINEL_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("SENTINEL_LLM_PROVIDER", "mock")
os.environ.setdefault("SENTINEL_EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("SENTINEL_SECRET_KEY", "test-secret")
os.environ.setdefault("SENTINEL_DEMO_API_KEY", "test-api-key")
os.environ.setdefault("SENTINEL_RATE_LIMIT_PER_MINUTE", "20")
# Budget enforcement reads are cached in production; tests want each request to
# see the spend that just happened.
os.environ.setdefault("SENTINEL_BUDGET_CACHE_SECONDS", "0")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.pool import StaticPool

from sentinellm.core.config import get_settings
from sentinellm.db.base import Base
from sentinellm.db.models import APIKey, Application, ModelPricing
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.pricing.catalog import DEFAULT_MODEL_CATALOG


@pytest.fixture(autouse=True, scope="session")
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    from sqlalchemy.ext.asyncio import create_async_engine

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_models(db_session: AsyncSession) -> AsyncSession:
    for profile in DEFAULT_MODEL_CATALOG.values():
        db_session.add(
            ModelPricing(
                id=profile.id,
                name=profile.name,
                provider=profile.provider,
                input_price_per_1k=profile.input_price_per_1k,
                output_price_per_1k=profile.output_price_per_1k,
                context_window=profile.context_window,
                quality_tier=profile.quality_tier,
                avg_latency_ms_prior=profile.avg_latency_ms_prior,
                status="healthy",
            )
        )
    await db_session.commit()
    return db_session


@pytest_asyncio.fixture
async def app_and_key(db_session: AsyncSession) -> tuple[Application, str]:
    from sentinellm.api.security import generate_api_key, hash_api_key, key_display_prefix

    app_row = Application(name="test-app")
    db_session.add(app_row)
    await db_session.flush()

    plaintext = generate_api_key()
    key_row = APIKey(
        application_id=app_row.id,
        name="test-key",
        role="admin",
        key_hash=hash_api_key(plaintext),
        key_prefix=key_display_prefix(plaintext),
    )
    db_session.add(key_row)
    await db_session.commit()
    return app_row, plaintext


@pytest.fixture
def app(engine: AsyncEngine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from sentinellm.api.deps import get_db
    from sentinellm.api.main import create_app

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session
            await session.commit()

    fastapi_app = create_app()
    fastapi_app.dependency_overrides[get_db] = _override_get_db
    return fastapi_app


@pytest_asyncio.fixture
async def client(app, app_and_key: tuple[Application, str]) -> AsyncIterator[AsyncClient]:
    _, api_key = app_and_key
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac


@pytest.fixture
def mock_embeddings() -> MockEmbeddingProvider:
    return MockEmbeddingProvider()
