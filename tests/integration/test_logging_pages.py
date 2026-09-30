"""HTTP tests for the log, dashboard and leaderboard pages.

These drive the real forms, because the things most likely to break are the
interactions between a form, a CSRF header, a session and a row — not the
service calls underneath, which the unit tests already cover.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from bm_tracker import auth, theme
from bm_tracker.achievements import engine, registry
from bm_tracker.dependencies import CSRF_FIELD_NAME, CSRF_HEADER_NAME
from bm_tracker.models import AchievementUnlock, BmEntry, DailyLog, User
from bm_tracker.notes import achievements as note_defs
from bm_tracker.services import bm_service
from bm_tracker.timezones import now_in
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from bm_tracker.settings import Settings

PASSWORD = "an excellent long passphrase"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf_of(html: str) -> str:
    """Return the CSRF token embedded in a page.

    Args:
        html: The rendered page.

    Returns:
        The token.
    """
    match = CSRF_RE.search(html)
    assert match, "no csrf_token in the rendered page"
    return match.group(1)


async def _user(
    session: AsyncSession, username: str = "cal", *, admin: bool = False
) -> User:
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
        timezone="Europe/London",
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


async def _sign_in(client: AsyncClient, username: str = "cal") -> None:
    """Drive the real sign-in form.

    Args:
        client: The HTTP client.
        username: The account to sign in as.
    """
    page = await client.get("/login")
    token = csrf_of(page.text)
    response = await client.post(
        "/login",
        data={
            CSRF_FIELD_NAME: token,
            "username": username,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 303, response.text


def _yesterday() -> date:
    """Return yesterday, so tests do not depend on the clock."""
    return now_in("UTC")[0] - timedelta(days=1)


# --- the log page ---------------------------------------------------------


async def test_log_page_defaults_to_today(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Opening /log with no date shows the user's today."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/log")

    assert page.status_code == 200
    assert "What happened?" in page.text
    assert now_in("Europe/London")[0].isoformat() in page.text


async def test_log_page_shows_the_bristol_scale(
    client: AsyncClient, session: AsyncSession
) -> None:
    """All seven types are offered as cards, and so is "Nothing today".

    "Nothing today" used to be a collapsed section of its own with its own
    form. It is the same kind of answer to the same question and it is scored
    the same way, so it belongs in the same grid — otherwise it is the option
    people forget.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/log")

    for value in range(1, 8):
        assert f'value="bm:{value}"' in page.text
    assert 'value="nothing"' in page.text
    assert "Nothing today" in page.text
    assert "Type 4" in page.text or "type 4" in page.text.lower()


async def test_submitting_a_bm_creates_the_day(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The whole path: form, CSRF, service, row, redirect."""
    user = await _user(session)
    await _sign_in(client)
    day = _yesterday()

    page = await client.get(f"/log?date={day.isoformat()}")
    token = csrf_of(page.text)
    response = await client.post(
        "/log",
        data={
            "choice": "bm:4",
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "time": "07:30",
            "notes": "first of the day",
        },
        headers={CSRF_HEADER_NAME: token},
    )
    assert response.status_code == 303

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 1

    # The logging form no longer shows the day it just wrote. That view moved
    # to the entries list, which is where a correction is made too.
    shown = await client.get(f"/dashboard/entries?year={day.year}")
    assert "first of the day" in shown.text
    assert 'action="/log/entry/' in shown.text, "entries should be removable"


async def test_submitting_nothing_today_creates_an_empty_day(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A first-class outcome, with its own note."""
    user = await _user(session)
    await _sign_in(client)
    day = _yesterday()

    page = await client.get(f"/log?date={day.isoformat()}")
    token = csrf_of(page.text)
    response = await client.post(
        "/log",
        data={
            "choice": "nothing",
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "notes": "all quiet",
        },
        headers={CSRF_HEADER_NAME: token},
    )
    assert response.status_code == 303

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 0
    assert row.is_note_live


async def test_a_bad_bristol_type_re_renders_the_form(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A rejected value explains itself rather than redirecting silently."""
    user = await _user(session)
    await _sign_in(client)
    day = _yesterday()

    page = await client.get(f"/log?date={day.isoformat()}")
    token = csrf_of(page.text)
    response = await client.post(
        "/log",
        data={
            "choice": "bm:9",
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "time": "07:30",
        },
        headers={CSRF_HEADER_NAME: token},
    )

    assert response.status_code == 400
    assert "Bristol" in response.text
    assert await bm_service.get_day(session, user, day) is None


async def test_a_future_day_is_refused(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The server checks, not just the form."""
    await _user(session)
    await _sign_in(client)
    tomorrow = now_in("Europe/London")[0] + timedelta(days=1)

    page = await client.get("/log")
    token = csrf_of(page.text)
    response = await client.post(
        "/log",
        data={
            "choice": "nothing",
            CSRF_FIELD_NAME: token,
            "date": tomorrow.isoformat(),
        },
        headers={CSRF_HEADER_NAME: token},
    )

    assert response.status_code == 400
    assert "not happened yet" in response.text


async def test_logging_without_a_csrf_token_is_refused(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The form's hidden field is checked, not merely rendered."""
    user = await _user(session)
    await _sign_in(client)
    day = _yesterday()

    response = await client.post(
        "/log",
        data={"choice": "nothing", "day": day.isoformat()},
    )

    assert response.status_code == 403
    assert await bm_service.get_day(session, user, day) is None


async def test_the_note_is_shown_as_superseded_after_a_bm(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The exact wording the owner sees when their note is overtaken."""
    await _user(session)
    await _sign_in(client)
    day = _yesterday()

    page = await client.get(f"/log?date={day.isoformat()}")
    token = csrf_of(page.text)
    await client.post(
        "/log",
        data={
            "choice": "nothing",
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "notes": "empty day",
        },
        headers={CSRF_HEADER_NAME: token},
    )
    await client.post(
        "/log",
        data={
            "choice": "bm:4",
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "time": "08:00",
        },
        headers={CSRF_HEADER_NAME: token},
    )

    # A superseded day-note is not published, so the feed does not show it.
    # That is the point of supersession: the day is described by its BMs.
    shown = await client.get("/")

    assert "empty day" not in shown.text


# --- dashboard ------------------------------------------------------------


async def test_dashboard_shows_derived_numbers(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Points, streaks and counts, all from the derivation."""
    user = await _user(session)
    for offset in range(3):
        day = now_in("UTC")[0] - timedelta(days=offset)
        await bm_service.log_nothing_today(
            session, user, day, logged_at=datetime(day.year, day.month, day.day, 20, 0)
        )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/dashboard")

    assert page.status_code == 200
    # 10 + 11 + 12, and a 3-day streak.
    assert "33" in page.text
    assert "day streak" in page.text


async def test_dashboard_is_empty_without_data(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A first-run dashboard says so rather than showing zeroes everywhere."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/dashboard")

    assert "Nothing logged" in page.text


async def test_dashboard_respects_the_year(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Last year's days are not counted in this year."""
    user = await _user(session)
    for day in (date(2025, 12, 30), date(2025, 12, 31)):
        await bm_service.log_nothing_today(
            session, user, day, logged_at=datetime(day.year, day.month, day.day, 20, 0)
        )
    await session.commit()
    await _sign_in(client)

    this_year = await client.get("/dashboard")
    last_year = await client.get("/dashboard?year=2025")

    assert "Nothing logged" in this_year.text
    assert "Nothing logged" not in last_year.text


async def test_logging_a_bm_records_strain_or_leaves_it_blank(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Strain is stored when given and left null when not.

    The blank case is the one that matters: it means "not recorded", which is
    not the same claim as level 1, and the column has to be able to say so.
    """
    await _user(session)
    await _sign_in(client)
    day = _yesterday()
    token = csrf_of((await client.get("/log")).text)

    for index, strain_value in enumerate(("3", ""), start=1):
        response = await client.post(
            "/log",
            data={
                "choice": "bm:4",
                CSRF_FIELD_NAME: token,
                "date": day.isoformat(),
                "time": f"0{7 + index}:30",
                "strain": strain_value,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

    rows = (
        await session.scalars(select(BmEntry).order_by(BmEntry.occurred_local))
    ).all()
    assert [row.strain for row in rows] == [3, None]


async def test_urgent_is_stored_as_a_flag_not_derived_from_the_delay(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Urgency is what the user ticked, not how fast they logged it.

    It was once shown as "quick" whenever the entry was written inside the
    ten-minute window, which asserted something about the BM that the BM does
    not know. Now it is a boolean on the row, and the two are independent: an
    entry written immediately can be unticked, and one written hours later can
    be ticked.
    """
    await _user(session)
    await _sign_in(client)
    day = _yesterday()
    token = csrf_of((await client.get("/log")).text)

    for hour, ticked in (("07", True), ("21", False)):
        response = await client.post(
            "/log",
            data={
                "choice": "bm:4",
                CSRF_FIELD_NAME: token,
                "date": day.isoformat(),
                "time": f"{hour}:00",
                "urgent": "on" if ticked else "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

    rows = (
        await session.scalars(select(BmEntry).order_by(BmEntry.occurred_local))
    ).all()
    assert [bool(row.urgent) for row in rows] == [True, False]


async def test_a_nonsense_strain_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """An out-of-range level is refused rather than stored."""
    await _user(session)
    await _sign_in(client)
    token = csrf_of((await client.get("/log")).text)

    response = await client.post(
        "/log",
        data={
            "choice": "bm:4",
            CSRF_FIELD_NAME: token,
            "day": _yesterday().isoformat(),
            "time": "09:00",
            "strain": "9",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert (await session.scalars(select(BmEntry))).all() == []


async def test_the_database_refuses_an_out_of_range_strain(
    session: AsyncSession,
) -> None:
    """The CHECK constraint exists in the database, not just the model.

    Autogenerate emitted the column without the constraint, because SQLite
    cannot add one without rebuilding the table. This is the test that would
    notice if someone regenerated the migration and dropped it again.
    """
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9),
        bristol_type=4,
    )
    await session.commit()
    log_id = (
        (await session.scalars(select(DailyLog).where(DailyLog.user_id == user.id)))
        .one()
        .id
    )

    session.add(
        BmEntry(
            daily_log_id=log_id,
            occurred_local=datetime(day.year, day.month, day.day, 10),
            bristol_type=4,
            strain=9,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_all_entries_paginates_thirty_to_a_page(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The full table pages at 30, and a stale page number lands somewhere real.

    The page size is a stated part of the feature, so it is pinned. The
    out-of-range behaviour is pinned too: a bookmark that outlives the data
    should show the last page, not an empty table that looks like data loss.
    """
    user = await _user(session)
    day = now_in("UTC")[0] - timedelta(days=1)
    for _ in range(35):
        await bm_service.log_bm(
            session,
            user,
            day,
            occurred_local=datetime(day.year, day.month, day.day, 9, 0),
            bristol_type=4,
            notes="a good one",
        )
    await session.commit()
    await _sign_in(client)

    first = await client.get("/dashboard/entries")
    assert first.status_code == 200
    assert first.text.count("<tr>") == 31, "a header row plus thirty entries"
    assert "Page 1 of 2" in first.text
    assert "More \u2014 all 35 of your entries" in (await client.get("/dashboard")).text

    second = await client.get("/dashboard/entries", params={"page": 2})
    assert second.text.count("<tr>") == 6, "the remainder is five entries"

    # Past the end lands on the last real page...
    past_end = await client.get("/dashboard/entries", params={"page": 99})
    assert past_end.status_code == 200
    assert "Page 2 of 2" in past_end.text

    # ...while a page number that is not one at all falls back to the first.
    for params in ({"page": "not-a-number"}, {"page": 0}, {"page": -3}):
        got = await client.get("/dashboard/entries", params=params)
        assert got.status_code == 200
        assert "Page 1 of 2" in got.text


async def test_all_entries_show_only_the_owner(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Someone else's entries never appear on your own table."""
    mine = await _user(session)
    theirs = await _user(session, username="dana")
    day = now_in("UTC")[0] - timedelta(days=1)
    await bm_service.log_bm(
        session,
        mine,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9, 0),
        bristol_type=4,
        notes="mine",
    )
    await bm_service.log_bm(
        session,
        theirs,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9, 0),
        bristol_type=7,
        notes="not yours to read",
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/dashboard/entries")

    assert "mine" in page.text
    assert "not yours to read" not in page.text


async def test_bristol_bars_are_capped_at_the_busiest_type(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Bar widths are a share of the busiest type, never a multiple of a count.

    They used to be ``count * 1.5rem``, so one popular type rendered a bar
    thousands of characters wide and the page scrolled sideways. Bounding the
    width to the busiest type is also what makes the bars comparable, which is
    the only reason a bar chart is a bar chart.
    """
    user = await _user(session)
    day = now_in("UTC")[0] - timedelta(days=1)
    for _ in range(60):
        await bm_service.log_bm(
            session,
            user,
            day,
            occurred_local=datetime(day.year, day.month, day.day, 9, 0),
            bristol_type=4,
        )
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 10, 0),
        bristol_type=1,
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/dashboard")

    widths = [int(m) for m in re.findall(r"--w: (\d+)", page.text)]
    assert widths, "no bars rendered"
    assert max(widths) == 100, "the busiest type is the full width"
    assert min(widths) == 0, "an unlogged type has no bar"

    # The one rare entry is a sliver next to the sixty, which is the whole point
    # of scaling to the maximum. 1/60 rounds to 2%.
    rare = [w for w in widths if 0 < w < 100]
    assert rare == [2], f"expected one sliver, got {rare}"


# --- the feed -------------------------------------------------------------


async def test_the_feed_shows_your_own_bms_in_full_and_nobody_elses(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Your own history is complete; other people contribute notes and badges.

    This is the privacy model, and the assertion has to be the strict one: the
    other user's *note* is visible and their *BM detail* is not, even though both
    live in the same year and the same feed.
    """
    mine = await _user(session)
    theirs = await _user(session, username="dana")
    day = _yesterday()

    await bm_service.log_bm(
        session,
        mine,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 7, 15),
        bristol_type=1,
        strain=3,
        urgent=True,
        spicy=True,
        notes="mine, and unmistakably so",
    )
    await bm_service.log_bm(
        session,
        theirs,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 6, 5),
        bristol_type=6,
        notes="their note, which is public",
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/")

    assert page.status_code == 200
    # My BM detail is there.
    assert "mine, and unmistakably so" in page.text
    assert "logged a BM" in page.text
    # Their note is there.
    assert "their note, which is public" in page.text
    # Their BM detail is not, anywhere in the response. Times are written the
    # way a person says them, so the marker is 12-hour too.
    assert "7:15 am" in page.text, "my own time should be shown"
    assert "6:05 am" not in page.text, "another person's BM time leaked"
    assert "Urgent" not in page.text, "another person's flags leaked"


async def test_the_feed_shows_your_own_empty_days(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A run of empty days is the scoring premise, so it has to be visible.

    Without this, logging nothing leaves no trace anywhere on the screen, which
    is precisely the behaviour the whole design is trying to encourage.
    """
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_nothing_today(session, user, day)
    await session.commit()
    await _sign_in(client)

    page = await client.get("/")

    assert "logged nothing today" in page.text


async def test_the_feed_does_not_show_per_note_points(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A note card carries no points badge.

    "+1 point for the note" on every card was noise: the note is the thing
    worth reading, and the point is in the badge bar and the leaderboard.
    """
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 8, 0),
        bristol_type=4,
        notes="a note worth reading",
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/")

    assert "a note worth reading" in page.text
    assert "point for the note" not in page.text


# --- leaderboard ----------------------------------------------------------


async def test_leaderboard_ranks_by_logging_plus_achievements(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Best first, with each person's real total."""
    strong = await _user(session, "cal")
    weak = await _user(session, "bee")
    for offset in range(5):
        day = now_in("UTC")[0] - timedelta(days=offset)
        await bm_service.log_nothing_today(
            session,
            strong,
            day,
            logged_at=datetime(day.year, day.month, day.day, 20, 0),
        )
    await bm_service.log_nothing_today(
        session, weak, now_in("UTC")[0], logged_at=now_in("UTC")[1]
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/leaderboard")

    assert page.status_code == 200
    body = page.text
    assert body.index("Cal") < body.index("Bee"), "higher score should rank first"
    assert "Ranked on everything you earned" in body


async def test_leaderboard_excludes_suspended_users(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A suspended account is not on the board."""
    await _user(session, "cal")
    gone = await _user(session, "bee")
    gone.is_active = False
    await session.commit()
    await _sign_in(client)

    page = await client.get("/leaderboard")

    assert "Bee" not in page.text


async def test_protected_pages_redirect_when_signed_out(
    client: AsyncClient,
) -> None:
    """Every one of them, not just one."""
    for path in ("/", "/log", "/dashboard", "/leaderboard", "/admin", "/settings"):
        response = await client.get(path, follow_redirects=False)
        assert response.status_code == 303, f"{path} did not redirect"
        assert response.headers.get("location") == "/login", path


# --- the help page --------------------------------------------------------


async def test_every_page_carries_the_navigation(
    session: AsyncSession, client: AsyncClient
) -> None:
    """No page is orphaned: the tab bar is on all of them."""
    await _user(session, "bee", admin=True)
    await _sign_in(client, "bee")

    for path in (
        "/",
        "/log",
        "/people",
        "/leaderboard",
        "/dashboard",
        "/help",
        "/settings",
        "/admin",
    ):
        page = await client.get(path)
        assert page.status_code == 200, path
        assert 'class="app-tabs"' in page.text, f"{path} has no tab bar"
        for href in ("/log", "/", "/people", "/leaderboard"):
            assert f'href="{href}"' in page.text, f"{path} is missing a tab"


async def test_the_homepage_reaches_back_past_new_year(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A note from last year is on the feed, without a year selector to find it.

    The year selector went so that reading your own history does not stop at
    1 January. This checks the route, not just the service: the route takes no
    year at all, so a filter reintroduced there would be invisible from below.
    """
    user = await _user(session)
    await bm_service.log_nothing_today(
        session,
        user,
        date(2025, 6, 1),
        notes="a note from last year",
        logged_at=datetime(2025, 6, 1, 20, 0),
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/")

    assert page.status_code == 200
    assert "a note from last year" in page.text
    assert "<select" not in page.text, "the year selector is still here"


async def test_the_homepage_pages_thirty_at_a_time(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Thirty cards, and a way on to the next page.

    Both halves matter: a page that silently returned everything would look
    correct until the feed got long, and a page with no onward link would be a
    dead end.
    """
    user = await _user(session)
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
    await _sign_in(client)

    first = await client.get("/")
    assert first.text.count('class="card feed__card') == 30
    assert "?page=2" in first.text

    second = await client.get("/?page=2")
    assert second.text.count('class="card feed__card') == 5
    # The last page keeps the way back but offers no way on.
    assert "Older" not in second.text, "the last page still offers a next"
    assert "?page=1" in second.text

    # A page past the end is empty rather than an error or a repeat.
    past = await client.get("/?page=99")
    assert past.status_code == 200
    assert "Nothing further back" in past.text


async def test_nothing_today_ignores_the_per_bm_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A day logged as empty cannot also be spicy and urgent.

    The interface greys those fields out, but that is a convenience. A request
    that carries them anyway — a stale tab, a script that did not run, a
    hand-rolled client — must still record an empty day, because there is no
    such thing as a spicy bowel movement on a day with no bowel movements.
    """
    user = await _user(session)
    await _sign_in(client)
    day = _yesterday()
    token = csrf_of((await client.get("/log")).text)

    response = await client.post(
        "/log",
        data={
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "choice": "nothing",
            "spicy": "on",
            "urgent": "on",
            "strain": "3",
            "time": "07:30",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 0
    assert (await session.scalars(select(BmEntry))).all() == []


async def test_the_log_form_offers_one_grid_for_both_answers(
    client: AsyncClient, session: AsyncSession
) -> None:
    """One form, one grid, one submit — not two forms in collapsed sections."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/log")

    assert page.text.count('action="/log"') == 1, (
        "there should be exactly one form on the page"
    )
    assert 'method="post" action="/log"' in page.text
    # The old shapes are gone.
    assert "Log an empty day</button>" not in page.text
    assert "Save note" not in page.text, "the day-note section should be gone"
    assert "/log/nothing" not in page.text
    assert "/log/note" not in page.text
    assert "data-log-form" in page.text


async def test_the_form_script_is_loaded(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Without the script the cards still work; it only does the greying."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/log")

    assert "/static/js/logform.js" in page.text
    script = await client.get("/static/js/logform.js")
    assert script.status_code == 200
    assert "data-bm-only" in script.text


async def test_the_log_form_is_only_a_form(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The page is a statement about a moment, not a view of a day.

    It used to carry a date to jump to, a header naming the day, the BMs
    already on it and the day's note — a second copy of what the dashboard and
    the entries list already say, on the one page opened in a hurry.
    """
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9, 0),
        bristol_type=4,
        notes="already logged",
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/log")

    assert page.status_code == 200
    # Date and time are fields, at the top, defaulting to now.
    assert 'type="date"' in page.text
    assert 'name="date"' in page.text
    assert 'type="time"' in page.text
    assert 'name="time"' in page.text
    assert f'value="{now_in(user.timezone)[0].isoformat()}"' in page.text
    # None of the day view.
    assert "Jump to a day" not in page.text
    assert day.strftime("%A") not in page.text
    assert "already logged" not in page.text
    assert "1 logged" not in page.text
    assert "Delete this day" not in page.text
    assert "bm-card" not in page.text


async def test_an_entry_can_be_removed_from_the_entries_list(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Correction moved to where the entry is listed.

    Removing a thing you typed is not something to do by re-visiting the page
    you typed it on, so the Remove control lives on the entries list — and it
    had to be fixed on the way, because both delete handlers read the CSRF token
    from a header while these are ordinary form posts, so the button was
    rejecting its own submission with a 403.
    """
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9, 0),
        bristol_type=4,
        notes="a mistake",
    )
    await session.commit()
    await _sign_in(client)

    listing = await client.get(f"/dashboard/entries?year={day.year}")
    assert "a mistake" in listing.text
    token = csrf_of(listing.text)

    response = await client.post(
        f"/log/entry/{(await session.scalars(select(BmEntry))).one().id}/delete",
        data={
            CSRF_FIELD_NAME: token,
            "return_to": f"/dashboard/entries?year={day.year}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/dashboard/entries?year={day.year}"
    assert (await session.scalars(select(BmEntry))).all() == []


async def test_a_delete_cannot_redirect_off_site(
    client: AsyncClient, session: AsyncSession
) -> None:
    """`return_to` is a redirect target from a form, so it is checked.

    Only a path on this site is honoured; `//evil.example` is protocol-relative
    and would otherwise leave the site entirely.
    """
    user = await _user(session)
    day = _yesterday()
    entry = await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9, 0),
        bristol_type=4,
    )
    await session.commit()
    await _sign_in(client)
    token = csrf_of((await client.get("/log")).text)

    response = await client.post(
        f"/log/entry/{entry.id}/delete",
        data={CSRF_FIELD_NAME: token, "return_to": "//evil.example/"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/entries"


async def test_the_leaderboard_names_its_columns_in_full(
    client: AsyncClient, session: AsyncSession
) -> None:
    """ "Streak" and "Longest" were ambiguous next to each other.

    A reader looking at a row cannot tell which of the two numbers is the
    current run and which was the best ever, and the shorter label was what
    caused it.
    """
    # The board lists only people who are in the year, so somebody has to be in
    # it. An account with nothing logged is not on the board at all, which is
    # its own test.
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9),
        bristol_type=4,
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/leaderboard")

    for label in ("Current streak", "Longest streak", "Days logged", "BMs"):
        assert f"<dt>{label}</dt>" in page.text, f"{label} is not labelled"
    assert ">Streak<" not in page.text
    assert ">Longest<" not in page.text


async def test_the_leaderboard_year_control_shares_the_heading(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The title and the year control are one decision, so they are one line."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/leaderboard")

    assert 'class="board__head"' in page.text
    assert 'class="board__title"' in page.text
    assert 'class="board__year"' in page.text
    assert 'name="year"' in page.text
    assert "Show</button>" in page.text
    # It is a list of people now, not a seven-column table.
    assert 'class="board"' in page.text
    assert "<table" not in page.text


async def test_settings_offers_light_dark_and_auto(
    client: AsyncClient, session: AsyncSession
) -> None:
    """All three, as cards, with the current one already chosen."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/settings")

    for value in ("light", "dark", "auto"):
        assert f'value="{value}"' in page.text
    # Jinja puts the attributes on their own line, so match across whitespace.
    assert re.search(r'value="light"\s+checked', page.text), (
        "light is the default and should be preselected"
    )


async def test_saving_a_theme_stores_it_and_sets_the_cookie(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Stored twice: in the account, and in a cookie the sign-in page can read."""
    user = await _user(session)
    await _sign_in(client)
    token = csrf_of((await client.get("/settings")).text)

    response = await client.post(
        "/settings/theme",
        data={CSRF_FIELD_NAME: token, "theme": "dark"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings", (
        "the confirmation should not live in the URL"
    )
    assert "bm_theme" in response.cookies
    await session.refresh(user)
    assert user.theme == "dark"


async def test_a_nonsense_theme_is_rejected_rather_than_stored(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A hand-crafted post cannot put a value in the column that is not a theme."""
    user = await _user(session)
    await _sign_in(client)
    token = csrf_of((await client.get("/settings")).text)

    response = await client.post(
        "/settings/theme",
        data={CSRF_FIELD_NAME: token, "theme": "sepia"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    await session.refresh(user)
    assert user.theme == theme.DEFAULT_THEME


async def test_the_theme_is_applied_before_the_stylesheet(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The script that sets the scheme has to run before the first paint.

    A theme applied in the body, or after the stylesheet, is a flash of the
    wrong colour on a phone at night — which is the exact moment anybody notices.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/settings")

    script_at = page.text.index("data-bs-theme")
    css_at = page.text.index("custom.css")
    assert script_at < css_at, "the theme script runs after the stylesheet"
    assert "prefers-color-scheme" in page.text


async def test_the_name_can_be_edited_on_the_settings_page(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The name is editable, and the field is prefilled with the current one."""
    user = await _user(session)
    await _sign_in(client)

    page = await client.get("/settings")

    assert 'action="/settings/name"' in page.text
    assert f'value="{user.display_name}"' in page.text

    token = csrf_of(page.text)
    response = await client.post(
        "/settings/name",
        data={CSRF_FIELD_NAME: token, "display_name": "  Cal   the   Surgeon  "},
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    await session.refresh(user)
    # Whitespace collapsed: a name is what a person types, and a stray double
    # space is a typing accident rather than a choice.
    assert user.display_name == "Cal the Surgeon"


async def test_clearing_the_name_falls_back_to_the_sign_in_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    """An empty field is a decision, not an error: go back to the username."""
    user = await _user(session)
    await _sign_in(client)
    token = csrf_of((await client.get("/settings")).text)

    response = await client.post(
        "/settings/name",
        data={CSRF_FIELD_NAME: token, "display_name": "   "},
        follow_redirects=False,
    )

    assert response.status_code == 303
    await session.refresh(user)
    assert user.display_name == user.username


async def test_a_name_that_is_too_long_is_refused(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The column is 60 characters, so the form says so before the database does."""
    user = await _user(session)
    await _sign_in(client)
    token = csrf_of((await client.get("/settings")).text)

    response = await client.post(
        "/settings/name",
        data={CSRF_FIELD_NAME: token, "display_name": "x" * 61},
        follow_redirects=False,
    )

    assert response.status_code == 400
    await session.refresh(user)
    assert user.display_name == "Cal", "a rejected name must not be stored"


async def test_the_settings_sections_are_divided(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Each section is separated by a rule, not by whitespace alone.

    The divider was written as `.settings-section:first-of-type`, which matches
    the first element of each *type*: the `<form>` and the first `<section>`
    alike, so the line above "Your details" silently disappeared.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/settings")

    # Exactly the section containers, not the __title and __submit inside them.
    assert len(re.findall(r'class="settings-section(?: |")', page.text)) == 4
    # One of them opts out of the top border; the other two keep it.
    assert page.text.count("settings-section--first") == 1
    assert (
        ".settings-section--first" in (await client.get("/static/css/custom.css")).text
    )


async def test_the_drawer_and_the_tab_bar_agree(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The same destinations, in the same order, in both navigation surfaces.

    They were two hand-written lists that had drifted: the tab bar led with
    Log, the drawer started at Feed, and the only thing they agreed on was the
    middle. A person who learned the tab bar had to re-learn the drawer.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/")

    tabs = re.findall(r'class="app-tab[^"]*"[^>]*href="([^"]+)"', page.text)
    drawer = re.findall(r'class="app-drawer__list".*?</ul>', page.text, re.S)
    assert drawer, "no drawer list"
    links = re.findall(r'href="([^"]+)"', drawer[0])

    assert tabs, "no tab bar"
    assert links[: len(tabs)] == tabs, (
        f"the drawer should open with the tab bar, in order: {links[: len(tabs)]} vs {tabs}"
    )


async def test_the_drawer_marks_the_page_you_are_on(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The active item is the same comparison in both surfaces.

    Checked on a page that is in both. People is a drawer-only destination
    now — it moved out of the tab bar when Achievements took its slot — so
    highlighting it can only ever produce one marker, and asking for two
    there would be asking for a tab that is not there.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/leaderboard")

    assert 'aria-current="page"' in page.text
    assert page.text.count("aria-current") == 2, "one in the tabs, one in the drawer"

    drawer_only = await client.get("/people")
    assert drawer_only.text.count("aria-current") == 1, (
        "a drawer-only destination should mark itself once, in the drawer"
    )


async def test_the_dashboard_has_no_log_button(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Logging is a tap away in the tab bar; the dashboard does not repeat it."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/dashboard")

    assert "Log a BM" not in page.text
    assert 'class="app-tab' in page.text
    assert 'href="/log"' in page.text


async def test_the_entries_page_has_one_header_line(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Title, count, year and button on one line, and no summary tiles.

    The three tiles repeated what that line and the pager at the bottom already
    said, and on a phone they were three screens of scrolling before the first
    entry.
    """
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9, 0),
        bristol_type=4,
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/dashboard/entries")

    assert 'class="entries-bar"' in page.text
    assert page.text.count('name="year"') == 1
    assert "Show</button>" in page.text
    assert 'class="tile"' not in page.text, "the summary tiles should be gone"
    assert "<h1>All entries</h1>" not in page.text, "the title moved into the bar"


async def test_removing_an_entry_asks_first(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Destructive and not undoable, so it says so before it does it."""
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 9, 0),
        bristol_type=4,
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/dashboard/entries")

    assert "onsubmit" in page.text
    assert "confirm(" in page.text
    assert "cannot be undone" in page.text


async def test_times_are_written_the_way_a_person_says_them(
    client: AsyncClient, session: AsyncSession
) -> None:
    """No 24-hour clock anywhere in the rendered text.

    The one exception is the value of the time input on the log form, which has
    to be 24-hour because that is what the element expects — the browser shows
    it in whatever format the reader's locale asks for.
    """
    user = await _user(session)
    day = _yesterday()
    await bm_service.log_bm(
        session,
        user,
        day,
        occurred_local=datetime(day.year, day.month, day.day, 19, 30),
        bristol_type=4,
    )
    await session.commit()
    await _sign_in(client)

    for path in ("/dashboard/entries", "/dashboard"):
        page = await client.get(path)
        assert "7:30 pm" in page.text, f"{path} is not using a 12-hour clock"
        assert "19:30" not in page.text, f"{path} is rendering a 24-hour clock"


async def test_achievement_tiers_are_ordered_by_what_they_are_worth(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The collection reads cheapest first, hardest last.

    It was rendering in the order the TOML file defined the tiers — Common,
    Rare, Uncommon, Legendary, which is 2, 10, 5, 20 points. A page of
    achievements laid out to be skimmed cannot present them in an order that
    means nothing.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/achievements")

    # The heading wraps across lines, so match with whitespace rather than
    # assuming one line of markup.
    headings = re.findall(r"<h2>\s*([A-Za-z]+)\s*<span[^>]*> · (\d+) pts", page.text)
    assert headings, "no tier headings found"
    points = [int(value) for _, value in headings]
    assert points == sorted(points), f"tiers are out of order: {headings}"
    assert [name for name, _ in headings] == [
        name.capitalize() for name, _ in headings
    ], "every tier should appear"


async def test_the_settings_confirmation_does_not_outlive_the_moment(
    client: AsyncClient, session: AsyncSession
) -> None:
    """It appears once, on the way back from saving, and then it is gone.

    It was a query parameter, which means a refresh brought it back, a bookmark
    kept it, and a link to `/settings?saved=dark` showed somebody else a
    confirmation for a change they had not made. A session flash, popped on
    read, cannot be any of those.
    """
    await _user(session)
    await _sign_in(client)
    token = csrf_of((await client.get("/settings")).text)

    saved = await client.post(
        "/settings/theme",
        data={CSRF_FIELD_NAME: token, "theme": "dark"},
        follow_redirects=False,
    )
    assert "saved=" not in saved.headers["location"]

    first = await client.get("/settings")
    assert "Appearance saved." in first.text

    again = await client.get("/settings")
    assert "Appearance saved." not in again.text, "the confirmation came back"


async def test_your_own_name_is_one_tab_stop_however_many_cards(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The name is always a link, but the repeats are not tab stops.

    Making your own name plain text fixed the tab order and broke the link,
    which is not a trade anybody wanted. So every card's name is a link to that
    person's page, and the repeats carry `tabindex="-1"`: still clickable with a
    mouse, still in the accessibility tree, but only the first one is somewhere
    a keyboard stops on the way through the feed.
    """
    user = await _user(session)
    day = _yesterday()
    for hour in (8, 9, 10):
        await bm_service.log_bm(
            session,
            user,
            day,
            occurred_local=datetime(day.year, day.month, day.day, hour, 0),
            bristol_type=4,
        )
    await session.commit()
    await _sign_in(client)

    page = await client.get("/")
    body = page.text

    assert body.count('href="/people/cal"') >= 3, (
        "your name should be a link on every one of your cards"
    )
    # One of them is reachable by Tab; the rest are not.
    assert body.count('href="/people/cal" tabindex="-1"') >= 2, (
        "the repeats should be clickable but not tab stops"
    )
    assert 'href="/people/cal">\n' in body or 'href="/people/cal">' in body


async def test_the_reward_screen_itemises_what_was_earned(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Every rule that fired, one line each, then the total, then the message.

    A single number does not teach anyone how the scoring works, and this is the
    one moment where they would listen. The order is the argument: a total shown
    first is a number that means nothing yet.
    """
    await _user(session)
    await _sign_in(client)
    day = now_in("Europe/London")[0]
    token = csrf_of((await client.get("/log")).text)

    await client.post(
        "/log",
        data={
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "time": now_in("Europe/London")[1].strftime("%H:%M"),
            "choice": "bm:4",
            "notes": "a note is worth a point",
        },
        follow_redirects=False,
    )
    page = await client.get("/log")

    assert "reward__panel" in page.text
    assert "Logged today" in page.text
    assert "Wrote a note" in page.text
    assert "Total" in page.text
    assert "reward__total-points" in page.text
    assert "reward__dismiss" in page.text
    # The animation reveals everything eventually; nothing is left hidden.
    assert "reward__pending" not in page.text


async def test_the_reward_total_is_the_sum_of_its_lines(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The breakdown and the total are derived together, so they cannot drift.

    Each line comes from the same constants the scorer uses. A total that was
    added up separately would be a second implementation of the scoring rules,
    and would be wrong the day one of them changed.
    """
    await _user(session)
    await _sign_in(client)
    day = now_in("Europe/London")[0]
    token = csrf_of((await client.get("/log")).text)
    await client.post(
        "/log",
        data={
            CSRF_FIELD_NAME: token,
            "date": day.isoformat(),
            "time": now_in("Europe/London")[1].strftime("%H:%M"),
            "choice": "bm:6",
            "notes": "with a note",
        },
        follow_redirects=False,
    )
    page = await client.get("/log")

    points = [int(m) for m in re.findall(r'reward__points">\+(\d+)', page.text)]
    total = int(re.search(r'reward__total-points">\+(\d+)', page.text).group(1))
    assert points, "no itemised lines"
    assert sum(points) == total, f"lines sum to {sum(points)}, total says {total}"


async def test_the_log_form_no_longer_counts_down_the_quick_window(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The bonus is revealed on the reward screen instead, after submitting.

    Counting it down beforehand was me over-correcting. The window is not
    something to manage while filling in a form; it is something to be paid for,
    and being told afterwards is the reward rather than a nag.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/log")

    assert "quick-entry" not in page.text
    assert "data-quick-window" not in page.text
    assert "/static/js/quickentry.js" not in page.text


async def test_achievement_points_reach_the_leaderboard(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A pile of unlocks can lift someone above a better logger.

    It used to be impossible: the board sorted on logging points alone, so doing
    everything — logging every day and filling the collection — still lost to
    somebody who only logged. The plan argued that a growing catalogue must not
    silently rebalance the board; the cost was that the board lied about who had
    done more, which is worse. One number now, with the split shown per row so
    you can still see where it came from.
    """
    grinder = await _user(session, "cal")
    collector = await _user(session, "bee")
    for offset in range(4):
        await bm_service.log_nothing_today(
            session, grinder, _yesterday() - timedelta(days=offset)
        )
    await bm_service.log_nothing_today(session, collector, _yesterday())
    session.add(
        AchievementUnlock(
            user_id=collector.id,
            achievement_key="ghost_writer",
            year=now_in("UTC")[0].year,
            points=20,
        )
    )
    await session.commit()
    await _sign_in(client)

    page = await client.get(f"/leaderboard?year={now_in('UTC')[0].year}")
    body = page.text
    rows = re.findall(r"class=\"board__row.*?</li>", body, re.S)
    assert len(rows) == 2
    first = rows[0]
    assert "bee" in first.lower(), (
        "the achievement points should have lifted Bee above Cal"
    )
    # Named as points, because it is points. "Of which achievements" sat among a
    # row of counts, so 348 read as three hundred and forty-eight achievements
    # out of a hundred and fifty-eight available.
    assert "Achievement points" in first, "the row should say where it came from"
    assert "Achievements earned" in first, "and how many that was"


async def test_a_locked_tier_shows_question_marks_and_what_it_costs(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A tier you have not earned the right to see says so, and shows nothing else.

    A catalogue of 300 revealed on day one is a list of things to grind rather
    than a collection to look at, and the names are the entire reward. So the
    names, the descriptions and the icons are all gone, and the header says how
    many points it would take.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/achievements")
    body = page.text

    assert "You need" in body
    assert "points to view these achievements" in body
    assert "???" in body
    # And nothing from a locked tier leaks: no name, no description, no icon.
    for hidden in ("Blatherer", "Ghost Writer", "ten in a single day"):
        assert hidden not in body, f"{hidden!r} leaked from a locked tier"


async def test_an_earned_achievement_shows_whatever_its_tier(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Hiding something you already have is a bug wearing a disguise.

    The thresholds gate discovery, not the record. Somebody who unlocked a
    legendary achievement in their first week has earned the right to see it
    named forever.
    """
    user = await _user(session)
    await _sign_in(client)

    earned = next(a for a in engine.REGISTRY.achievements if a.tier == "legendary")
    page = await client.get("/achievements")
    assert (
        f"You need {engine.REGISTRY.points_to_reveal('legendary')} points" in page.text
    )
    assert earned.name not in page.text, "an unearned legendary should be hidden"

    session.add(
        AchievementUnlock(
            user_id=user.id,
            achievement_key=earned.key,
            year=now_in("UTC")[0].year,
            points=earned.points,
        )
    )
    await session.commit()

    after = await client.get("/achievements")
    assert earned.name in after.text, (
        "an achievement you have earned must stay visible whatever the threshold"
    )


async def test_the_reveal_thresholds_track_real_usage(
    client: AsyncClient, session: AsyncSession
) -> None:
    """They are computed from the scoring, not guessed at.

    `scoring.total_for_run` is what a perfect run of n days is worth, so the
    thresholds are the points a diligent person actually reaches at one, three,
    six and ten weeks. A test that only asserted the numbers exist would not
    notice them drifting away from the rules.
    """
    from bm_tracker import scoring  # noqa: PLC0415

    reveal = engine.REGISTRY.reveal_at
    assert set(reveal) == set(engine.REGISTRY.tiers), (
        "every tier needs a threshold, or a new one is visible from the start"
    )

    # Ascending, and none beyond a plausible two-year run.
    values = [reveal[t] for t in sorted(reveal, key=lambda t: reveal[t])]
    assert values == sorted(values)
    assert values[0] <= scoring.total_for_run(7), (
        "the first tier should open within about a week of use"
    )
    assert values[-1] < scoring.total_for_run(365), (
        "the last tier should open within a year, not never"
    )


async def test_an_unlock_says_what_you_did_to_earn_it(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The reward screen names the achievement *and* says what earns it.

    "The Marathon" on its own does not say five entries in a single day, so a
    reader who has just earned it learns nothing about what they did — and
    showing the unlock at all is only worth it if they can take the lesson.
    """
    await _user(session)
    await _sign_in(client)
    day = now_in("Europe/London")[0]
    token = csrf_of((await client.get("/log")).text)

    # Five entries today is The Marathon; the fifth is the one that earns it.
    #
    # The flash is popped on read, so the page that carries the reward is the
    # *first* GET after the final POST. Fetching another one to refresh the
    # token would spend it, and this test asserted on nothing.
    for index, hour in enumerate((8, 9, 10, 11, 12)):
        response = await client.post(
            "/log",
            data={
                CSRF_FIELD_NAME: token,
                "date": day.isoformat(),
                "time": f"{hour:02d}:00",
                "choice": "bm:3",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        page = await client.get("/log")
        if index < 4:
            token = csrf_of(page.text)

    assert "reward__award" in page.text, "no unlock on the reward screen"
    assert "The Marathon" in page.text
    assert "five in a single day" in page.text.lower(), (
        "the unlock must say what earns it, not only what it is called"
    )


async def test_a_tile_is_never_a_full_bar_and_locked_at_once(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A backfilled year satisfies its rules but records no unlock.

    `unlocked` came from the unlocks table and `progress` from live rules, so
    looking back at a year you had backfilled into rendered a full progress bar
    beside the word "Locked" — one tile saying two opposite things. The page now
    evaluates the year being viewed before reading it, so the table is the only
    thing that decides.
    """

    user = await _user(session)
    await _sign_in(client)

    old = date.today().year - 3
    day = date(old, 6, 15)
    await bm_service.log_bm(
        session, user, day, occurred_local=datetime(old, 6, 15, 9, 0), bristol_type=4
    )
    await session.commit()

    page = await client.get(f"/achievements?year={old}")

    assert 'aria-valuenow="100"' not in page.text, (
        "a locked achievement is showing a full progress bar"
    )
    first_blood = re.search(
        r'achievement-tile__name">First Blood</span>.*?(?=</li>)', page.text, re.S
    )
    assert first_blood, "First Blood tile not found"
    assert "badge text-bg-success" in first_blood.group(0), (
        "a satisfied rule with no unlock row is still shown as locked"
    )


async def test_an_empty_year_names_itself_rather_than_ranking_nobody(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A board of people with nothing in it is a list of everybody, not a board.

    Looking at a year before anybody used the app listed all eight users in a
    row, most at zero points, zero days and zero entries — and cost a scoring
    pass per user to produce.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/leaderboard?year=1998")

    assert "board__row" not in page.text, "an empty year should rank nobody"
    assert "Nobody has logged anything in 1998 yet." in page.text


async def test_the_collection_total_does_not_shrink_with_your_points(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The header names the whole collection, not just what it is allowed to show.

    It used to say "of N" where N was the number of tiles rendered, so a person
    on 3,000 points read "of 158" and a person on 800 read "of 120" — two people
    comparing collections were comparing different-sized ones, and neither figure
    was how many achievements there are.
    """
    await _user(session)
    await _sign_in(client)

    page = await client.get("/achievements")
    text = re.sub(r"<[^>]+>", " ", page.text)
    text = " ".join(text.split())

    total = len(registry.load()) + len(note_defs.load())
    assert f"of {total} earned" in text, (
        f"the collection should be {total}: {text[:120]}"
    )


async def test_resetting_a_person_leaves_them_an_account_and_no_history(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Wipe the logging, keep the login.

    For testing and for a beta tester who wants a clean start: the account, its
    password, its name and whether it is an administrator all survive, and the
    entries, days, notes, unlocks and streak facts all go. What is left is an
    account that has signed in and done nothing.
    """

    admin = await _user(session, "bee", admin=True)
    person = await _user(session, "sam")
    day = _yesterday()
    for hour in (8, 9):
        await bm_service.log_bm(
            session,
            person,
            day,
            occurred_local=datetime(day.year, day.month, day.day, hour),
            bristol_type=4,
            notes="a note that should not survive",
        )
    await session.commit()

    entries_before = await session.scalar(
        select(func.count())
        .select_from(BmEntry)
        .where(
            BmEntry.daily_log_id.in_(
                select(DailyLog.id).where(DailyLog.user_id == person.id)
            )
        )
    )
    assert entries_before, "the fixture should have logged something"
    unlocks_before = await session.scalar(
        select(func.count())
        .select_from(AchievementUnlock)
        .where(AchievementUnlock.user_id == person.id)
    )

    await _sign_in(client, "bee")
    token = (await client.get("/admin")).text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', token).group(1)

    wrong = await client.post(
        "/admin/users/sam/reset",
        data={"confirm": "not-sam"},
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert wrong.status_code in (303, 422, 403), wrong.status_code
    still = await session.scalar(
        select(func.count())
        .select_from(AchievementUnlock)
        .where(AchievementUnlock.user_id == person.id)
    )
    assert still == unlocks_before, "a wrong confirmation must not delete anything"

    ok = await client.post(
        "/admin/users/sam/reset",
        data={"confirm": "sam"},
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert ok.status_code == 303, ok.status_code

    left = await session.scalar(
        select(func.count())
        .select_from(BmEntry)
        .where(
            BmEntry.daily_log_id.in_(
                select(DailyLog.id).where(DailyLog.user_id == person.id)
            )
        )
    )
    assert left == 0, f"{left} entries survived"
    for model in (DailyLog, AchievementUnlock):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.user_id == person.id)
            )
            == 0
        ), f"{model.__tablename__} survived"

    survivor = await session.scalar(select(User).where(User.id == person.id))
    assert survivor is not None, "the account itself must survive"
    assert survivor.username == "sam"
    assert admin.id != person.id


async def test_a_person_cannot_reset_themselves_or_others(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The reset is an admin action, and an ordinary person has no route to it."""
    await _user(session, "sam")
    await _sign_in(client, "sam")

    page = await client.get("/admin")

    assert page.status_code in (403, 404), page.status_code
    assert "/reset" not in page.text


async def test_every_admin_action_accepts_a_plain_form_post(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Each admin form posts its token as a hidden field.

    Six of the seven admin routes read `X-CSRF-Token` and nothing else. Every
    form on that page posts `csrf_token` in a hidden input and no script sets the
    header, so all six answered 403 for every admin action — including Delete and
    Reset data. Only "Add someone" worked, because it alone fell back to the
    form field.

    The test posts the way a browser does, with the token in the body and no
    header, and asserts none of them answers 403.
    """
    await _user(session, "bee", admin=True)
    await _user(session, "sam")
    await _sign_in(client, "bee")

    page = await client.get("/admin")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    for action in ("deactivate", "reissue", "admin", "reset", "delete"):
        response = await client.post(
            f"/admin/users/sam/{action}",
            data={"csrf_token": token, "confirm": "sam"},
            follow_redirects=False,
        )
        assert response.status_code != 403, (
            f"{action} rejected a form post: {response.text[:120]}"
        )
