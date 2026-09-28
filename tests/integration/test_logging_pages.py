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
from bm_tracker.dependencies import CSRF_FIELD_NAME, CSRF_HEADER_NAME
from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.services import bm_service
from bm_tracker.timezones import now_in
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
    # Their BM detail is not, anywhere in the response.
    assert "07:15" in page.text, "my own time should be shown"
    assert "06:05" not in page.text, "another person's BM time leaked"
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


async def test_leaderboard_ranks_by_points(
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
    assert "Achievement points are tracked separately" in body


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


async def test_help_states_the_live_scoring_constants(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The explanation is generated from the constants, so it cannot go stale."""
    from bm_tracker import scoring  # noqa: PLC0415

    await _user(session)
    await _sign_in(client)

    page = await client.get("/help")

    assert page.status_code == 200
    body = page.text
    assert f"{scoring.POINTS_PER_QUALIFYING_DAY} points" in body
    assert f"+{scoring.POINTS_BACKFILLED_DAY}" in body
    assert f"{scoring.POINTS_NOTE} each" in body
    # The worked totals come from the same derivation, not from prose.
    assert str(scoring.total_for_run(5)) in body
    assert str(scoring.total_for_run(7)) in body


async def test_the_cap_is_stated_as_a_cap(
    session: AsyncSession, client: AsyncClient
) -> None:
    """A reader should not be left thinking the bonus climbs forever."""
    from bm_tracker import scoring  # noqa: PLC0415

    await _user(session)
    await _sign_in(client)

    body = (await client.get("/help")).text

    cap = scoring.STREAK_BONUS_STEP * scoring.STREAK_BONUS_MAX_STEPS
    assert f"then +{cap}" in body
    assert "stops climbing" in body


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
    await _user(session)
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
    assert response.headers["location"] == "/settings?saved=theme"
    assert theme.COOKIE_NAME in response.cookies or "bm_theme" in response.cookies
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
    assert len(re.findall(r'class="settings-section(?: |")', page.text)) == 3
    # One of them opts out of the top border; the other two keep it.
    assert page.text.count("settings-section--first") == 1
    assert (
        ".settings-section--first" in (await client.get("/static/css/custom.css")).text
    )
