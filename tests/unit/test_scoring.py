"""Tests for the scoring rules.

Each row of the verified-behaviour table in the plan has a test here, so a
change to the rules has to update a test rather than alter behaviour silently.
The cases that matter most are the ones where a careless implementation would
look right: the backfill invariant, the year boundary, and the fact that
"nothing today" is worth the same as a busy day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from bm_tracker import scoring
from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.services import bm_service
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

YEAR = 2026


async def _user(session: AsyncSession, username: str = "cal") -> User:
    """Create a user with no password, which scoring does not need.

    Args:
        session: The session to write through.
        username: The account name.

    Returns:
        The created `User`.
    """
    user = User(username=username, display_name=username.title(), timezone="UTC")
    session.add(user)
    await session.commit()
    return user


def _naive(day: date, hour: int) -> datetime:
    """Return a naive UTC datetime, standing in for a same-day recording.

    Args:
        day: The date.
        hour: The hour.

    Returns:
        The naive datetime.
    """
    return datetime(day.year, day.month, day.day, hour, 0)


def _run(start_day: int, count: int) -> list[date]:
    """Return consecutive January dates.

    Args:
        start_day: The starting day of the month.
        count: How many days.

    Returns:
        The dates, in order.
    """
    return [date(YEAR, 1, start_day + offset) for offset in range(count)]


async def _log(
    session: AsyncSession,
    user: User,
    days: list[date],
    *,
    entries_per_day: int = 0,
    logged_at_offset: timedelta | None = None,
    note: str | None = None,
    quick_entries: bool = False,
) -> list[DailyLog]:
    """Create day rows with entries, all recorded at the same hour.

    Args:
        session: The session to write through.
        user: The owner.
        days: The occurrence dates, in order.
        entries_per_day: How many BMs to add to each day.
        logged_at_offset: How late each record was written. `None` means
            same-day, which is what qualifies.
        note: A day-note to attach.
        quick_entries: Whether each entry was written minutes after it
            happened, which is what earns the ten-minute bonus.

    Returns:
        The created `DailyLog` rows.
    """
    rows: list[DailyLog] = []
    for day in days:
        logged_at = _naive(day, 20)
        if logged_at_offset is not None:
            logged_at = logged_at + logged_at_offset
        row = DailyLog(
            user_id=user.id,
            day=day,
            n_bms=entries_per_day,
            notes=note,
            logged_at=logged_at,
        )
        session.add(row)
        await session.flush()
        occurred = datetime(day.year, day.month, day.day, 7, 0)
        for _ in range(entries_per_day):
            session.add(
                BmEntry(
                    daily_log_id=row.id,
                    occurred_local=occurred,
                    bristol_type=4,
                    created_at=occurred + timedelta(minutes=3)
                    if quick_entries
                    else logged_at,
                )
            )
        rows.append(row)
    await session.commit()
    return rows


# --- the unit rules -------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "expected"),
    [(1, 0), (2, 1), (3, 2), (4, 3), (5, 4), (6, 5), (7, 5), (30, 5)],
)
def test_streak_bonus_rises_by_one_then_caps(position: int, expected: int) -> None:
    """+1 on day two, +5 on day six, no higher however long the run.

    The cap is deliberate: an uncapped streak makes one missed day an
    unrecoverable deficit.
    """
    assert scoring.streak_bonus(position) == expected


def test_a_qualifying_day_earns_the_base_plus_its_bonus() -> None:
    """Base plus the streak bonus."""
    assert scoring.day_points(qualified=True, position=1) == 10
    assert scoring.day_points(qualified=True, position=3) == 12
    assert scoring.day_points(qualified=True, position=50) == 15


def test_a_backfill_earns_the_backfill_award() -> None:
    """Three points: too small to farm, too large to be free."""
    assert scoring.day_points(qualified=False, position=0) == 3


@pytest.mark.parametrize(
    ("delta_minutes", "expected"),
    [(3, True), (10, True), (10.02, False), (600, False), (-3, True)],
)
def test_the_quick_bonus_is_absolute(delta_minutes: float, expected: bool) -> None:
    """Within ten minutes either way.

    Absolute, so someone who types 07:00 and submits at 06:57 is not punished
    for a rounding slip.
    """
    occurred = datetime(YEAR, 1, 9, 7, 0)
    created = occurred + timedelta(minutes=delta_minutes)
    assert scoring.is_quick(created, occurred, 10, "UTC") is expected


def test_the_quick_bonus_reads_the_typed_zone() -> None:
    """A wall clock off the meridian still counts as quick.

    `created_at` is stored as UTC and `occurred_local` as the
    wall clock the user typed, so the two can only be compared
    through the zone the wall clock names. Subtracting one from
    the other directly measured the user's offset as if it were
    the writing time, which made the bonus unreachable for
    everybody not on the meridian.
    """
    # January: Chicago is CST, six hours behind UTC.
    occurred = datetime(YEAR, 1, 9, 7, 0)
    created = datetime(YEAR, 1, 9, 13, 5)  # 07:05 CST
    assert scoring.is_quick(created, occurred, 10, "America/Chicago")


def test_a_note_pays_once_per_note() -> None:
    """A live day-note plus each noted entry."""
    assert (
        scoring.note_points(
            has_live_day_note=True, noted_entry_ids=set(), entry_ids=set()
        )
        == 1
    )
    assert (
        scoring.note_points(
            has_live_day_note=True, noted_entry_ids={1, 2}, entry_ids={1, 2, 3}
        )
        == 3
    )


def test_a_superseded_day_note_does_not_pay() -> None:
    """Once a BM exists, the day is described by its entries."""
    assert (
        scoring.note_points(
            has_live_day_note=False, noted_entry_ids=set(), entry_ids=set()
        )
        == 0
    )


# --- qualification --------------------------------------------------------


def test_qualification_is_the_local_calendar_day() -> None:
    """A recording made late in the UTC day can already be the next day locally."""
    logged_at = datetime(YEAR, 1, 9, 23, 30)  # 23:30 UTC

    assert scoring.qualifies(date(YEAR, 1, 9), logged_at, "UTC")
    # Auckland is UTC+13 in January, so 23:30 UTC is already the 10th there.
    assert not scoring.qualifies(date(YEAR, 1, 9), logged_at, "Pacific/Auckland")


def test_qualification_across_midnight_utc() -> None:
    """The same instant, judged from two sides of the date line."""
    logged_at = datetime(YEAR, 1, 10, 0, 30)  # 00:30 UTC

    assert scoring.qualifies(date(YEAR, 1, 10), logged_at, "UTC")
    assert not scoring.qualifies(date(YEAR, 1, 9), logged_at, "UTC")


# --- the verified-behaviour table ----------------------------------------


async def test_four_consecutive_logs_accrue_the_bonus(
    session: AsyncSession,
) -> None:
    """Ten, eleven, twelve, thirteen. Nothing needs revising afterwards."""
    user = await _user(session)
    await _log(session, user, _run(9, 4))

    score = await scoring.score_year(session, user, YEAR)

    assert [day.points for day in score.days] == [10, 11, 12, 13]
    assert score.current_streak == 4
    assert score.longest_streak == 4
    assert score.logging_points == 46


async def test_the_bonus_caps_at_day_six(session: AsyncSession) -> None:
    """A long run plateaus rather than climbing forever."""
    user = await _user(session)
    await _log(session, user, _run(1, 30))

    score = await scoring.score_year(session, user, YEAR)

    assert [day.points for day in score.days[:8]] == [10, 11, 12, 13, 14, 15, 15, 15]
    assert max(day.points for day in score.days) == 15
    assert score.current_streak == 30


async def test_a_gap_resets_the_run(session: AsyncSession) -> None:
    """A missing day breaks the chain, and the next run starts at one."""
    user = await _user(session)
    await _log(session, user, [date(YEAR, 1, 9), date(YEAR, 1, 10), date(YEAR, 1, 11)])
    await _log(session, user, [date(YEAR, 1, 13), date(YEAR, 1, 14)])

    score = await scoring.score_year(session, user, YEAR)

    assert [day.position for day in score.days] == [1, 2, 3, 1, 2]
    assert [day.points for day in score.days] == [10, 11, 12, 10, 11]
    assert score.current_streak == 2
    assert score.longest_streak == 3


async def test_a_backfill_changes_nobody_elses_score(
    session: AsyncSession,
) -> None:
    """The invariant the whole design exists to protect.

    Scored, then a late day inserted, then scored again: every pre-existing
    day's score must be byte-identical.
    """
    user = await _user(session)
    await _log(session, user, _run(9, 4))
    before = await scoring.score_year(session, user, YEAR)

    await _log(session, user, [date(YEAR, 1, 8)], logged_at_offset=timedelta(days=12))
    after = await scoring.score_year(session, user, YEAR)

    assert all(before.days[index] == after.days[index + 1] for index in range(4))

    backfilled = after.days[0]
    assert backfilled.backfilled
    assert not backfilled.qualified
    assert backfilled.points == scoring.POINTS_BACKFILLED_DAY
    assert backfilled.position == 0
    # A backfill is not in the streak either.
    assert after.current_streak == 4


async def test_an_overnight_log_scores_nothing(session: AsyncSession) -> None:
    """Logged the next morning: no streak, no qualifying day, three points.

    The cost of having no grace period, and the sharpest edge in the product.
    Asserted deliberately so a future change to the rules updates this test
    rather than altering the behaviour silently.
    """
    user = await _user(session)
    await _log(session, user, [date(YEAR, 1, 9)], logged_at_offset=timedelta(hours=9))

    score = await scoring.score_year(session, user, YEAR)

    assert score.days[0].points == 3
    assert score.current_streak == 0
    assert score.qualifying_days == 0
    assert score.days_logged == 1


async def test_a_streak_does_not_cross_new_year(session: AsyncSession) -> None:
    """A new year is a fresh start: the run does not carry over.

    Otherwise somebody who started in January would carry a lead into a year
    nobody else can compete in.
    """
    user = await _user(session)
    await _log(session, user, [date(2025, 12, 30), date(2025, 12, 31)])

    last_year = await scoring.score_year(session, user, 2025)
    assert last_year.current_streak == 2

    await _log(session, user, [date(YEAR, 1, 2)])
    this_year = await scoring.score_year(session, user, YEAR)

    assert this_year.days[0].position == 1, "the walk must stop at 1 January"
    assert this_year.days[0].points == 10
    assert this_year.current_streak == 1


async def test_nothing_today_earns_a_days_points(
    session: AsyncSession,
) -> None:
    """An empty day is worth the same as one with three BMs.

    The game rewards reporting honestly, not producing output.
    """
    empty_user = await _user(session)
    busy_user = await _user(session, "bee")

    await _log(session, empty_user, [date(YEAR, 1, 9)])
    await _log(session, busy_user, [date(YEAR, 1, 9)], entries_per_day=3)

    empty = await scoring.score_year(session, empty_user, YEAR)
    busy = await scoring.score_year(session, busy_user, YEAR)

    assert empty.days[0].points == busy.days[0].points == 10
    assert empty.current_streak == busy.current_streak == 1
    assert empty.bms == 0
    assert busy.bms == 3


async def test_a_nothing_today_note_pays(session: AsyncSession) -> None:
    """An empty day with a note earns the note point like any other."""
    user = await _user(session)
    await _log(session, user, [date(YEAR, 1, 9)], note="long flight, nothing happened")

    score = await scoring.score_year(session, user, YEAR)

    assert score.days[0].has_live_note
    assert score.days[0].note_points == scoring.POINTS_NOTE
    assert score.note_points == 1


async def test_a_superseded_note_pays_nothing(session: AsyncSession) -> None:
    """Once a BM exists the day-note is retained, but overtaken."""
    user = await _user(session)
    await _log(
        session, user, [date(YEAR, 1, 9)], note="nothing happened", entries_per_day=1
    )

    score = await scoring.score_year(session, user, YEAR)

    assert not score.days[0].has_live_note
    assert score.days[0].note_points == 0


async def test_the_quick_bonus_pays_per_entry(session: AsyncSession) -> None:
    """Each entry recorded in time earns its own point."""
    user = await _user(session)
    await _log(session, user, [date(YEAR, 1, 9)], entries_per_day=3, quick_entries=True)

    score = await scoring.score_year(session, user, YEAR)

    assert score.days[0].entry_points == 3 * scoring.POINTS_QUICK_ENTRY
    assert score.entry_points == 3


async def test_a_late_entry_earns_no_quick_bonus(session: AsyncSession) -> None:
    """The same BM, recorded twelve hours later, pays nothing extra."""
    user = await _user(session)
    day = date(YEAR, 1, 9)
    row = DailyLog(user_id=user.id, day=day, n_bms=1, logged_at=_naive(day, 20))
    session.add(row)
    await session.flush()
    session.add(
        BmEntry(
            daily_log_id=row.id,
            occurred_local=datetime(YEAR, 1, 9, 7, 0),
            bristol_type=4,
            created_at=_naive(day, 19),  # twelve hours after it happened
        )
    )
    await session.commit()

    score = await scoring.score_year(session, user, YEAR)
    assert score.entry_points == 0


# --- aggregates -----------------------------------------------------------


async def test_a_year_with_nothing_in_it_scores_zero(
    session: AsyncSession,
) -> None:
    """No rows, no points, and no division by zero anywhere."""
    user = await _user(session)

    score = await scoring.score_year(session, user, 1999)

    assert score.days == ()
    assert score.logging_points == 0
    assert score.current_streak == 0
    assert score.longest_streak == 0


async def test_scoring_is_scoped_to_its_year(session: AsyncSession) -> None:
    """One year's history does not leak into the other's totals."""
    user = await _user(session)
    await _log(session, user, [date(2025, 12, 30), date(2025, 12, 31)])
    await _log(session, user, [date(YEAR, 1, 9)])

    this_year = await scoring.score_year(session, user, YEAR)
    last_year = await scoring.score_year(session, user, 2025)

    assert len(this_year.days) == 1
    assert len(last_year.days) == 2


async def test_the_current_streak_ignores_a_trailing_backfill(
    session: AsyncSession,
) -> None:
    """A backfill recorded last does not become the current streak."""
    user = await _user(session)
    await _log(session, user, _run(9, 5))
    await _log(session, user, [date(YEAR, 1, 20)], logged_at_offset=timedelta(days=3))

    score = await scoring.score_year(session, user, YEAR)

    assert score.days_logged == 6
    assert score.qualifying_days == 5
    assert score.current_streak == 0, "the most recent day was a backfill"
    assert score.longest_streak == 5


async def test_the_longest_streak_is_the_best_run_not_the_last(
    session: AsyncSession,
) -> None:
    """A long run followed by a short one reports the long one."""
    user = await _user(session)
    await _log(session, user, _run(1, 10))
    await _log(session, user, [date(YEAR, 2, 1), date(YEAR, 2, 2)])

    score = await scoring.score_year(session, user, YEAR)

    assert score.longest_streak == 10
    assert score.current_streak == 2


# --- leaderboard ----------------------------------------------------------


async def test_ranking_sorts_by_logging_points(session: AsyncSession) -> None:
    """Achievement points must not be able to reorder the board."""
    strong = await _user(session)
    weak = await _user(session, "bee")
    await _log(session, strong, _run(1, 5))
    await _log(session, weak, _run(1, 1))

    scores = await scoring.score_all_users(session, [strong, weak], YEAR)
    ordered = scoring.rank(scores, {strong.id: strong, weak.id: weak})

    assert [user.username for user, _ in ordered] == ["cal", "bee"]


async def test_ranking_breaks_ties_deterministically(
    session: AsyncSession,
) -> None:
    """Equal points, equal streaks, alphabetical — the same order every time."""
    one = await _user(session)
    two = await _user(session, "bee")
    await _log(session, one, _run(1, 3))
    await _log(session, two, _run(1, 3))

    users_by_id = {one.id: one, two.id: two}
    forwards = [
        u.username
        for u, _ in scoring.rank(
            await scoring.score_all_users(session, [one, two], YEAR), users_by_id
        )
    ]
    backwards = [
        u.username
        for u, _ in scoring.rank(
            await scoring.score_all_users(session, [two, one], YEAR), users_by_id
        )
    ]

    assert forwards == backwards == ["bee", "cal"]


async def test_scoring_a_group_costs_the_same_queries_as_scoring_one_person(
    session: AsyncSession,
) -> None:
    """`score_all_users` loads everybody's year once, not once per person.

    It used to await `score_year` for each user in turn, and `score_year` issued
    a query per *day*, so a leaderboard of eight people with two years of history
    was thousands of round trips. This counts the statements, which is the thing
    that was actually wrong: the numbers came out the same either way, so only
    the cost said anything.
    """
    people = []
    for name in ("cal", "bee", "sam", "jay"):
        user = await _user(session, name)
        for offset in range(6):
            await bm_service.log_nothing_today(
                session, user, date(2026, 3, 1) + timedelta(days=offset)
            )
        people.append(user)
    await session.commit()

    counted: list[str] = []

    def record(*args: object) -> None:
        cursor = args[1]
        counted.append(str(getattr(cursor, "statement", "")))

    engine = session.get_bind()
    sync_engine = getattr(engine, "sync_engine", engine)
    event.listen(sync_engine, "before_cursor_execute", record)
    try:
        everyone = await scoring.score_all_users(session, people, 2026)
        everyone_statements = len(counted)
        counted.clear()
        await scoring.score_year(session, people[0], 2026)
        one_person_statements = len(counted)
    finally:
        event.remove(sync_engine, "before_cursor_execute", record)

    assert len(everyone) == 4
    # Four people, four times the work, but the queries do not scale with the
    # number of people: three for the group against three for one.
    assert everyone_statements <= one_person_statements + 1, (
        f"group scoring took {everyone_statements} queries for 4 people; "
        f"one person took {one_person_statements}"
    )


async def test_scoring_a_group_agrees_with_scoring_each_person(
    session: AsyncSession,
) -> None:
    """Batching is an optimisation, so it must not change a single number."""
    people = []
    for name in ("cal", "bee"):
        user = await _user(session, name)
        for offset in range(4):
            day = date(2026, 4, 1) + timedelta(days=offset)
            await bm_service.log_bm(
                session,
                user,
                day,
                occurred_local=datetime(2026, 4, 1, 8 + offset, 0),
                bristol_type=4,
                notes="a note",
            )
        people.append(user)
    await session.commit()

    batched = await scoring.score_all_users(session, people, 2026)
    one_at_a_time = [await scoring.score_year(session, user, 2026) for user in people]

    assert [s.logging_points for s in batched] == [
        s.logging_points for s in one_at_a_time
    ]
    assert [s.current_streak for s in batched] == [
        s.current_streak for s in one_at_a_time
    ]
    assert batched[0].days == one_at_a_time[0].days
    assert batched[1].days == one_at_a_time[1].days
