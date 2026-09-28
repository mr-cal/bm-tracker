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
from bm_tracker import auth
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
    """All seven types are offered, as radio buttons in a fieldset."""
    await _user(session)
    await _sign_in(client)

    page = await client.get("/log")

    for value in range(1, 8):
        assert f'value="{value}"' in page.text
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
        "/log/bm",
        data={
            CSRF_FIELD_NAME: token,
            "day": day.isoformat(),
            "time": "07:30",
            "bristol_type": "4",
            "notes": "first of the day",
        },
        headers={CSRF_HEADER_NAME: token},
    )
    assert response.status_code == 303

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 1

    shown = await client.get(f"/log?date={day.isoformat()}")
    assert "first of the day" in shown.text
    assert "1 logged" in shown.text


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
        "/log/nothing",
        data={CSRF_FIELD_NAME: token, "day": day.isoformat(), "notes": "all quiet"},
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
        "/log/bm",
        data={
            CSRF_FIELD_NAME: token,
            "day": day.isoformat(),
            "time": "07:30",
            "bristol_type": "9",
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
        "/log/nothing",
        data={CSRF_FIELD_NAME: token, "day": tomorrow.isoformat()},
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
        "/log/nothing",
        data={"day": day.isoformat()},
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
        "/log/nothing",
        data={CSRF_FIELD_NAME: token, "day": day.isoformat(), "notes": "empty day"},
        headers={CSRF_HEADER_NAME: token},
    )
    await client.post(
        "/log/bm",
        data={
            CSRF_FIELD_NAME: token,
            "day": day.isoformat(),
            "time": "08:00",
            "bristol_type": "6",
        },
        headers={CSRF_HEADER_NAME: token},
    )

    shown = await client.get(f"/log?date={day.isoformat()}")

    assert "empty day" in shown.text
    assert "superseded" in shown.text


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
            "/log/bm",
            data={
                CSRF_FIELD_NAME: token,
                "day": day.isoformat(),
                "time": f"0{7 + index}:30",
                "bristol_type": "4",
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
            "/log/bm",
            data={
                CSRF_FIELD_NAME: token,
                "day": day.isoformat(),
                "time": f"{hour}:00",
                "bristol_type": "4",
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
        "/log/bm",
        data={
            CSRF_FIELD_NAME: token,
            "day": _yesterday().isoformat(),
            "time": "09:00",
            "bristol_type": "4",
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
