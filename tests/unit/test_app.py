"""Tests for the application factory and the health endpoint."""

from __future__ import annotations

import pytest
from bm_tracker.app import create_app
from bm_tracker.settings import MIN_SESSION_SECRET_BYTES, Settings
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_health_reports_ok(client: AsyncClient) -> None:
    """A healthy database answers 200 with a status and nothing else."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_body_carries_no_internals(client: AsyncClient) -> None:
    """The endpoint is unauthenticated, so it must not leak driver or path.

    A regression guard: adding a `database: "sqlite"` field for convenience
    would tell an unauthenticated caller where the file lives.
    """
    body = (await client.get("/health")).text

    for leak in ("sqlite", ".db", "aiosqlite", "://", "Traceback"):
        assert leak not in body


async def test_health_reports_degraded_when_database_is_unreachable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken database yields 503 rather than an exception page."""
    app = create_app(settings)

    async def _broken(_engine: AsyncEngine) -> bool:
        return False

    monkeypatch.setattr("bm_tracker.app.check_database", _broken)

    from httpx import ASGITransport  # noqa: PLC0415

    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http_client,
        app.router.lifespan_context(app),
    ):
        response = await http_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}


async def test_unknown_path_renders_the_404_page(client: AsyncClient) -> None:
    """A missing page gets the friendly template, not a JSON error."""
    response = await client.get("/definitely-not-a-real-page")

    assert response.status_code == 404
    assert "Nothing here" in response.text


async def test_app_serves_its_database_from_settings(
    settings: Settings, test_engine: AsyncEngine
) -> None:
    """The lifespan must hand the configured database to the request handlers."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        engine: AsyncEngine = app.state.engine
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT 1"))).scalar() == 1

    assert engine is not test_engine


async def test_session_factory_is_available_after_startup(
    settings: Settings,
) -> None:
    """`app.state.session_factory` exists once the lifespan has run."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert app.state.session_factory is not None


# --- settings guards -----------------------------------------------------


def test_production_refuses_a_missing_session_secret() -> None:
    """A production boot with no signing secret must fail loudly."""
    with pytest.raises(ValueError, match="SESSION_SECRET is required"):
        Settings(app_env="production", session_secret="", database_url="sqlite://")


def test_production_refuses_a_short_session_secret() -> None:
    """A short secret weakens the cookie's HMAC, so it is refused."""
    with pytest.raises(ValueError, match="at least"):
        Settings(
            app_env="production",
            session_secret="too-short",
            database_url="sqlite://",
        )


def test_production_refuses_debug() -> None:
    """Debug tracebacks leak SQL and configuration, so they are refused."""
    with pytest.raises(ValueError, match="DEBUG=true is refused"):
        Settings(
            app_env="production",
            session_secret="x" * MIN_SESSION_SECRET_BYTES,
            debug=True,
            database_url="sqlite://",
        )


def test_production_accepts_a_well_formed_secret() -> None:
    """The guard must not block a correct configuration."""
    settings = Settings(
        app_env="production",
        session_secret="x" * 64,
        database_url="sqlite://",
    )

    assert settings.is_production


def test_development_needs_no_secret() -> None:
    """Local development must not require a signing secret to start."""
    settings = Settings(app_env="development", database_url="sqlite://")

    assert not settings.is_production


def test_database_url_is_not_logged_with_a_password() -> None:
    """A URL carrying a password must be redacted before it reaches a log."""
    from bm_tracker.app import _redact  # noqa: PLC0415

    redacted = _redact("postgresql+asyncpg://user:hunter2@postgres/bm_tracker")

    assert "hunter2" not in redacted
    assert redacted == "postgresql+asyncpg://***@postgres/bm_tracker"


async def test_health_endpoint_is_unauthenticated(client: AsyncClient) -> None:
    """The deploy health check hits this without credentials, by design."""
    response = await client.get("/health")

    assert response.status_code == 200
