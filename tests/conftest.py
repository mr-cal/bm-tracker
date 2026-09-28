"""Shared test fixtures for bm-tracker."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from bm_tracker.app import create_app
from bm_tracker.database import get_engine, get_session_factory
from bm_tracker.models import Base
from bm_tracker.settings import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip end-to-end tests unless BM_TRACKER_E2E=1.

    Mirrors craft-dashboard's convention so the two suites behave the same way
    from the command line.
    """
    if os.environ.get("BM_TRACKER_E2E") == "1":
        return
    skip_e2e = pytest.mark.skip(reason="set BM_TRACKER_E2E=1 to run end-to-end tests")
    for item in items:
        if item.get_closest_marker("e2e"):
            item.add_marker(skip_e2e)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Return development-mode settings pointed at this test's own database.

    APP_ENV is forced to development so the production guards in `Settings` —
    which require a session secret — do not fire on every construction.

    The database is a per-test file rather than a shared one, so rows cannot
    leak between tests. It stays file-backed rather than in-memory because an
    in-memory database keeps everything on a single connection, which would make
    the PRAGMA tests pass for the wrong reason.
    """
    return Settings(
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        debug=False,
    )


@pytest.fixture
async def test_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Yield a file-backed engine with the app's PRAGMAs applied."""
    engine = get_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(
    test_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the test engine."""
    return get_session_factory(test_engine)


@pytest.fixture
async def session(
    test_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session against a freshly created schema.

    `create_all` runs against an engine connection rather than through the
    session: `MetaData.create_all` needs something exposing the DDL visitor, and
    a Session is not that. The migration itself is covered separately in
    `tests/integration/test_migrations.py`, so drift between the schema and the
    migration surfaces there rather than here.
    """
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as db_session:
        yield db_session


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """Yield an HTTP client wired to the app, with lifespan events run."""
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://testserver") as http_client,
        app.router.lifespan_context(app),
    ):
        yield http_client
