"""Tests for the rotating form hints.

The log form says five dry things. Fixed wording on a form you open several
times a day stops being a hint, so they rotate — and they rotate by the same
fair rule as the celebration lines, not at random, or somebody would only ever
see two of them.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import pytest
from bm_tracker import auth, celebrate
from bm_tracker.app import create_app
from bm_tracker.database import get_engine, get_session_factory
from bm_tracker.models import User
from bm_tracker.settings import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

PASSWORD = "an excellent long passphrase"
SLOTS = ("noting", "nothing_today", "strain_1", "strain_2", "strain_3")
CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'hints.db'}",
    )


@pytest.fixture
async def engine(settings: Settings):
    """A file-backed engine for the rotation's own bookkeeping."""
    engine = get_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """A session with the schema built."""
    from bm_tracker.models import Base  # noqa: PLC0415

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = get_session_factory(engine)
    async with factory() as db_session:
        yield db_session


@pytest.fixture
async def account(session: AsyncSession) -> User:
    """Somebody to rotate for."""
    person = User(
        username="cal",
        display_name="Cal",
        password_hash=auth.hash_password(PASSWORD),
        timezone="Europe/London",
    )
    session.add(person)
    await session.commit()
    return person


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An HTTP client with the app's lifespan running."""
    app = create_app(settings)
    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http,
        app.router.lifespan_context(app),
    ):
        yield http


def test_every_hint_slot_has_more_than_one_line() -> None:
    """A slot with one line is not a rotation."""
    for slot in SLOTS:
        assert len(celebrate._VARIANTS_BY_SLOT.get(slot, ())) >= 3, slot


def test_every_strain_level_has_its_own_slot() -> None:
    """The three effort levels say different things and must not share a pool."""
    ids = [m.id for slot in SLOTS for m in celebrate._VARIANTS_BY_SLOT[slot]]
    assert len(set(ids)) == len(ids), "a hint appears in two slots"


async def test_hints_rotate_rather_than_repeating(
    session: AsyncSession, account: User
) -> None:
    """Successive renders cycle the pool before any line repeats.

    The rule is fewest showings wins, ties to longest unseen — the same one the
    celebration lines use. A plain random pick would let somebody see the same
    joke three times running.
    """
    pool = len(celebrate._VARIANTS_BY_SLOT["nothing_today"])
    seen = [
        await celebrate.variant(session, account.id, "nothing_today")
        for _ in range(pool)
    ]
    await session.commit()

    assert len(set(seen)) == pool, f"a line repeated inside one cycle: {seen}"


async def test_the_log_form_shows_lines_from_the_pools(
    client: AsyncClient, session: AsyncSession, account: User
) -> None:
    """The form draws its wording from the catalogue, not from the template.

    Checking that the *old* strings are absent would be wrong: they are the
    first entries in their pools, and the point is that one of the pool is used
    rather than a literal.
    """
    page = await client.get("/login")
    token = CSRF.search(page.text).group(1)
    await client.post(
        "/login",
        data={"csrf_token": token, "username": account.username, "password": PASSWORD},
    )

    body = (await client.get("/log")).text

    for slot in SLOTS:
        pool = celebrate._VARIANTS_BY_SLOT[slot]
        assert any(m.text in body for m in pool), f"no hint from {slot!r} on the form"
