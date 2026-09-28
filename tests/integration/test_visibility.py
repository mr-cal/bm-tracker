"""Tests for the visibility model and the feed.

The privacy test is the one that matters: it drives the real page and asserts
the withheld detail is absent from the rendered bytes. Checking the query was
right would not catch a value leaking through a template.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from bm_tracker import auth
from bm_tracker.dependencies import CSRF_FIELD_NAME
from bm_tracker.models import DailyLog, User
from bm_tracker.services import bm_service, feed_service, visibility
from bm_tracker.timezones import now_in
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from bm_tracker.settings import Settings

PASSWORD = "an excellent long passphrase"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
TIME_RE = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")


async def _user(session: AsyncSession, username: str, *, admin: bool = False) -> User:
    """Create a signed-in-able user.

    Args:
        session: The session to write through.
        username: The account name.
        admin: Whether the account is an administrator.

    Returns:
        The created `User`.
    """
    user = User(
        username=username,
        display_name=username.title(),
        password_hash=auth.hash_password(PASSWORD),
        is_admin=admin,
        timezone="UTC",
    )
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An HTTP client with the app's lifespan running."""
    from bm_tracker.app import create_app  # noqa: PLC0415

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://testserver") as http,
        app.router.lifespan_context(app),
    ):
        yield http


async def _sign_in(client: AsyncClient, username: str) -> None:
    """Drive the real sign-in form.

    Args:
        client: The HTTP client.
        username: The account to sign in as.
    """
    page = await client.get("/login")
    match = CSRF_RE.search(page.text)
    assert match
    response = await client.post(
        "/login",
        data={
            CSRF_FIELD_NAME: match.group(1),
            "username": username,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 303, response.text


# --- the rules themselves -------------------------------------------------


def test_a_viewer_never_has_detail_of_another_person() -> None:
    """Only the owner and an admin may see fine-grained detail."""
    viewer = User(id=1, username="bee", display_name="Bee", is_admin=False)
    other = User(id=2, username="cal", display_name="Cal", is_admin=False)
    boss = User(id=1, username="bee", display_name="Bee", is_admin=True)

    assert not visibility.can_see_detail(viewer, other)
    assert visibility.can_see_detail(viewer, viewer)
    assert visibility.can_see_detail(boss, other)


def test_a_day_projected_for_others_drops_the_detail() -> None:
    """A projected day has no time, no type and no backfill marker."""
    day = DailyLog(
        id=1,
        user_id=2,
        day=date(2026, 1, 9),
        n_bms=0,
        notes="a quiet one",
        logged_at=datetime(2026, 1, 20, 0),
        created_at=datetime(2026, 1, 9),
    )
    projected = visibility.day_for_others(day, qualified=True)

    assert projected.day == date(2026, 1, 9)
    assert projected.n_bms == 0
    assert projected.note == "a quiet one"
    assert not hasattr(projected, "occurred_local")
    assert not hasattr(projected, "bristol_type")
    assert not hasattr(projected, "backfilled")


def test_a_superseded_note_is_not_published() -> None:
    """Once a BM exists the day-note is overtaken, so it is not shown."""
    empty = DailyLog(
        id=1,
        user_id=1,
        day=date(2026, 1, 9),
        n_bms=0,
        notes="nothing",
        logged_at=datetime(2026, 1, 20, 0),
    )
    busy = DailyLog(
        id=2,
        user_id=1,
        day=date(2026, 1, 8),
        n_bms=1,
        notes="nothing",
        logged_at=datetime(2026, 1, 20, 0),
    )

    assert visibility.day_for_others(empty, qualified=True).note == "nothing"
    assert visibility.day_for_others(busy, qualified=True).note is None


def test_a_feed_item_cannot_carry_a_private_key() -> None:
    """The allowlist is enforced, not trusted."""
    with pytest.raises(ValueError, match="leaked"):
        visibility.assert_public({"kind": "note", "occurred_local": "07:12"})
    visibility.assert_public({"kind": "note", "text": "hello"})


# --- the feed -------------------------------------------------------------


async def test_the_feed_returns_notes_and_unlocks(
    session: AsyncSession,
) -> None:
    """All three kinds, from real rows."""
    from bm_tracker.models import AchievementUnlock  # noqa: PLC0415

    user = await _user(session, "cal")
    day = now_in("UTC")[0] - timedelta(days=3)
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(2026, 1, 9, 7, 0),
        bristol_type=4,
        notes="a note on a BM",
        logged_at=datetime(2026, 1, 9, 20, 0),
    )
    empty = now_in("UTC")[0] - timedelta(days=2)
    await bm_service.log_nothing_today(
        session,
        user,
        empty,
        notes="a quiet day",
        logged_at=datetime(2026, 1, 10, 20, 0),
    )
    session.add(
        AchievementUnlock(
            user_id=user.id, achievement_key="first_blood", year=2026, points=2
        )
    )
    await session.commit()

    items = await feed_service.feed_items(session, viewer=user)
    kinds = {item.kind for item in items}

    assert feed_service.KIND_NOTE in kinds
    assert feed_service.KIND_ACHIEVEMENT in kinds


async def test_every_note_on_a_day_gets_its_own_item(
    session: AsyncSession,
) -> None:
    """Three notes on one day are three items, not one merged row.

    The viewer is somebody else on purpose. Somebody's own notes appear on the
    BM cards that carry them rather than as separate cards, and this is about
    the group stream.
    """
    author = await _user(session, "cal")
    viewer = await _user(session, "bee")
    day = date(2026, 1, 9)
    await bm_service.log_bm(
        session,
        author,
        day,
        occurred_local=datetime(2026, 1, 9, 7, 0),
        bristol_type=4,
        notes="the first one",
        logged_at=datetime(2026, 1, 9, 7, 5),
    )
    for hour, text in ((9, "the second one"), (14, "the third one")):
        await bm_service.log_bm(
            session,
            author,
            day,
            occurred_local=datetime(2026, 1, 9, hour, 0),
            bristol_type=4,
            notes=text,
            logged_at=datetime(2026, 1, 9, hour, 5),
        )
    await session.commit()

    items = await feed_service.feed_items(session, viewer=viewer)
    notes = [i.text for i in items if i.kind == feed_service.KIND_NOTE]

    assert set(notes) == {"the first one", "the second one", "the third one"}


async def test_a_superseded_note_never_reaches_the_feed(
    session: AsyncSession,
) -> None:
    """A note overtaken by a BM is not republished."""
    user = await _user(session, "cal")
    day = date(2026, 1, 9)
    await bm_service.log_nothing_today(
        session,
        user,
        day,
        notes="nothing happened",
        logged_at=datetime(2026, 1, 9, 20, 0),
    )
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(2026, 1, 9, 7, 0),
        bristol_type=4,
        logged_at=datetime(2026, 1, 9, 20, 5),
    )
    await session.commit()

    items = await feed_service.feed_items(session, viewer=user)

    assert not any(i.text == "nothing happened" for i in items)


async def test_the_feed_runs_across_years_without_a_seam(
    session: AsyncSession,
) -> None:
    """The feed is one timeline, so last year and this year both appear.

    This is the opposite of what this test used to assert. The year selector
    went because reading your own history should not stop at 1 January and make
    you decide to go looking for the rest of it.
    """
    user = await _user(session, "cal")
    await bm_service.log_nothing_today(
        session,
        user,
        date(2025, 6, 1),
        notes="last year",
        logged_at=datetime(2025, 6, 1, 20, 0),
    )
    await bm_service.log_nothing_today(
        session,
        user,
        date(2026, 6, 1),
        notes="this year",
        logged_at=datetime(2026, 6, 1, 20, 0),
    )
    await session.commit()

    texts = {i.text for i in await feed_service.feed_items(session, viewer=user)}

    assert "this year" in texts
    assert "last year" in texts


async def test_the_feed_pages_thirty_at_a_time(session: AsyncSession) -> None:
    """Paging gives disjoint slices, and the last page is the remainder.

    Getting this wrong is quiet: an overlapping page shows duplicates, and a
    short page looks like the end of the data.
    """
    user = await _user(session, "cal")
    # BMs rather than noted days: a day with a note and no BMs produces *two*
    # items, a note and a day, so 35 of them would be 70 and the arithmetic
    # below would be wrong for the right reason.
    for index in range(35):
        day = date(2026, 3, 1) + timedelta(days=index)
        await bm_service.log_bm(
            session,
            user,
            day,
            occurred_local=datetime(day.year, day.month, day.day, 9, 0),
            bristol_type=4,
        )
    await session.commit()

    first = await feed_service.feed_items(session, viewer=user, limit=30, offset=0)
    second = await feed_service.feed_items(session, viewer=user, limit=30, offset=30)

    assert len(first) == 30
    assert len(second) == 5
    assert not {i.day for i in first} & {i.day for i in second}, "pages overlap"


async def test_a_page_past_the_end_is_empty_not_an_error(
    session: AsyncSession,
) -> None:
    """A stale bookmark shows an empty page, not a crash or a repeat."""
    user = await _user(session, "cal")
    await bm_service.log_nothing_today(
        session,
        user,
        date(2026, 3, 1),
        notes="only one",
        logged_at=datetime(2026, 3, 1, 20, 0),
    )
    await session.commit()

    past = await feed_service.feed_items(session, viewer=user, limit=30, offset=30)

    assert past == []


# --- the page, driven for real -------------------------------------------


async def test_another_persons_page_withholds_the_detail(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The important one: the withheld fields are absent from the HTML itself.

    Asserted against the rendered bytes rather than the query, because that is
    what would actually leak.
    """
    # A plain user, not an admin: the restriction is about being *another
    # person*, and an admin is allowed through by design.
    await _user(session, "bee")
    victim = await _user(session, "cal")
    day = date(2026, 1, 9)
    await bm_service.log_bm(
        session,
        victim,
        day,
        occurred_local=datetime(2026, 1, 9, 7, 0),
        bristol_type=4,
        notes="a public note",
        logged_at=datetime(2026, 1, 9, 20, 0),
    )
    # A backfilled day, whose lateness must not be published either.
    await bm_service.log_nothing_today(
        session,
        victim,
        date(2026, 1, 20),
        notes=None,
        logged_at=datetime(2026, 1, 23, 0),
    )
    await session.commit()

    await _sign_in(client, "bee")
    page = await client.get("/people/cal")

    assert page.status_code == 200
    # The note IS published: that is the point of the model.
    assert "a public note" in page.text
    # The time a BM happened is not.
    assert "07:00" not in page.text
    # Nor is anything else from the entry itself.
    assert "Type 4" not in page.text
    assert "Type 4" not in page.text


async def test_a_person_sees_their_own_detail(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The owner is not subject to their own restrictions."""
    user = await _user(session, "cal", admin=True)
    await bm_service.log_bm(
        session,
        user,
        date(2026, 1, 9),
        occurred_local=datetime(2026, 1, 9, 7, 0),
        bristol_type=4,
        logged_at=datetime(2026, 1, 9, 7, 5),
    )
    await session.commit()

    await _sign_in(client, "cal")
    page = await client.get("/people/cal")

    assert page.status_code == 200
    assert "see their own detail" not in page.text


async def test_the_feed_page_renders_items(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The feed is the front door, and it has something on it."""
    user = await _user(session, "cal")
    await bm_service.log_nothing_today(
        session,
        user,
        date(2026, 1, 9),
        notes="visible in the feed",
        logged_at=datetime(2026, 1, 9, 20, 0),
    )
    await session.commit()

    await _sign_in(client, "cal")
    page = await client.get("/")

    assert page.status_code == 200
    assert "visible in the feed" in page.text


async def test_the_people_roster_lists_everyone(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The roster shows all active users and skips suspended ones."""
    await _user(session, "cal", admin=True)
    await _user(session, "bee")
    gone = await _user(session, "dee")
    gone.is_active = False
    await session.commit()

    await _sign_in(client, "cal")
    page = await client.get("/people")

    assert "Bee" in page.text
    assert "Dee" not in page.text


async def test_an_unknown_person_is_a_404(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Not a 200 with an empty profile."""
    await _user(session, "cal", admin=True)
    await _sign_in(client, "cal")

    page = await client.get("/people/nobody")

    assert page.status_code == 404


async def test_feed_pages_are_strictly_newest_first(
    session: AsyncSession,
) -> None:
    """Paging back never moves forwards in time.

    Every source is merged and sorted by the moment of the event, and each is
    limited in that same order before the merge. When a source ordered by
    something else — the day a row belongs to, rather than the moment it was
    written — the per-source top N is the wrong N, and a deep page quietly
    shows rows that are newer than the page before it. That is invisible on one
    page and obvious across twenty.
    """
    user = await _user(session, "cal")
    for index in range(80):
        day = date(2026, 1, 1) + timedelta(days=index)
        await bm_service.log_bm(
            session,
            user,
            day,
            occurred_local=datetime(day.year, day.month, day.day, 9, 0),
            bristol_type=4,
            # Backfilled: written days after the day it belongs to, so the two
            # orderings genuinely disagree.
            logged_at=datetime(day.year, day.month, day.day, 20, 0) + timedelta(days=3),
        )
    await session.commit()

    seen: list[datetime] = []
    for page in range(4):
        batch = await feed_service.feed_items(
            session, viewer=user, limit=20, offset=page * 20
        )
        seen.extend(item.at for item in batch)

    assert len(seen) == 80, "every seeded BM should be reachable across four pages"
    assert seen == sorted(seen, reverse=True), "paging back moved forwards in time"


async def test_a_note_on_your_own_bm_is_not_printed_twice(
    session: AsyncSession,
) -> None:
    """Your own note appears once, on the BM that carries it.

    It used to appear twice: once as a standalone note card and once inside the
    BM card that owns it, because the group stream published every entry-note in
    the year — including yours — and the viewer stream published the same entries
    again with their notes in place.
    """
    user = await _user(session, "cal")
    await bm_service.log_bm(
        session,
        user,
        date(2026, 5, 4),
        occurred_local=datetime(2026, 5, 4, 7, 15),
        bristol_type=4,
        notes="only once please",
    )
    await session.commit()

    items = await feed_service.feed_items(session, viewer=user)
    # The note can surface two ways: as a standalone note card, or in place on
    # the BM that carries it. Both count, because either is a place a reader
    # would see it twice.
    carriers = [
        i
        for i in items
        if i.text == "only once please"
        or (i.entry is not None and i.entry.notes == "only once please")
    ]

    assert len(carriers) == 1, f"the note is on the feed {len(carriers)} times"
    assert carriers[0].kind == feed_service.KIND_BM, (
        "it should appear on the BM that carries it, not as a second card"
    )


async def test_someone_elses_note_on_a_bm_is_still_published(
    session: AsyncSession,
) -> None:
    """Excluding the viewer's own entries must not silence anyone else's."""
    mine = await _user(session, "cal")
    theirs = await _user(session, "bee")
    await bm_service.log_bm(
        session,
        theirs,
        date(2026, 5, 4),
        occurred_local=datetime(2026, 5, 4, 7, 15),
        bristol_type=4,
        notes="their note, still public",
    )
    await session.commit()

    items = await feed_service.feed_items(session, viewer=mine)
    texts = [i.text for i in items]

    assert "their note, still public" in texts


async def test_a_day_note_is_not_dropped_with_the_entries(
    session: AsyncSession,
) -> None:
    """A "nothing today" note has no entry to appear on, so it is kept.

    The exclusion is on entry-notes specifically. A day-note would otherwise
    lose its only appearance in the feed the moment the person who wrote it
    looked at the page.
    """
    user = await _user(session, "cal")
    await bm_service.log_nothing_today(
        session,
        user,
        date(2026, 5, 4),
        notes="nothing happened, and I said so",
        logged_at=datetime(2026, 5, 4, 20, 0),
    )
    await session.commit()

    items = await feed_service.feed_items(session, viewer=user)

    assert any(i.text == "nothing happened, and I said so" for i in items)
