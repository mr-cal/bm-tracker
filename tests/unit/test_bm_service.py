"""Tests for writing days and BMs.

Two properties carry the most weight and get the most attention:

- `daily_logs.n_bms` must never disagree with the number of entries pointing at
  the day. It is denormalised for the dashboard, which is only worth doing if it
  cannot drift.
- A day-note must be live on an empty day and superseded once a BM exists, and
  come back when that BM is deleted — with nothing written to make any of that
  happen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.models.base import utcnow
from bm_tracker.services import bm_service
from bm_tracker.timezones import parse_date, parse_time
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _user(session: AsyncSession, timezone: str = "UTC") -> User:
    """Create a user with no password set, which the log path does not need.

    Args:
        session: The session to write through.
        timezone: The user's IANA timezone.

    Returns:
        The created `User`.
    """
    user = User(username="cal", display_name="Cal", timezone=timezone)
    session.add(user)
    await session.commit()
    return user


def _at(day: date, hour: int = 7) -> datetime:
    """Return a naive wall-clock datetime on a day.

    Args:
        day: The date.
        hour: The hour.

    Returns:
        The naive datetime.
    """
    return datetime(day.year, day.month, day.day, hour, 0)


def _yesterday() -> date:
    """Return yesterday, so "same day" tests are not clock-dependent."""
    return utcnow().date() - timedelta(days=1)


async def _count(session: AsyncSession, day: DailyLog) -> int:
    """Return the real number of entries on a day.

    Args:
        session: The session to read through.
        day: The day.

    Returns:
        The count.
    """
    return int(
        await session.scalar(
            select(func.count())
            .select_from(BmEntry)
            .where(BmEntry.daily_log_id == day.id)
        )
        or 0
    )


# --- logging a BM ---------------------------------------------------------


async def test_logging_a_bm_creates_the_day_and_the_entry(
    session: AsyncSession,
) -> None:
    """The first BM creates the day row, so the day counts as logged."""
    user = await _user(session)
    day = _yesterday()

    entry = await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=4
    )
    await session.commit()

    assert entry.id is not None
    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 1


async def test_a_second_bm_increments_the_count(session: AsyncSession) -> None:
    """The counter tracks the entries, transactionally."""
    user = await _user(session)
    day = _yesterday()

    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=4
    )
    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 9), bristol_type=6
    )
    await session.commit()

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 2 == await _count(session, row)


async def test_a_second_day_is_a_second_row(session: AsyncSession) -> None:
    """Days do not accumulate onto one another."""
    user = await _user(session)
    first, second = _yesterday(), _yesterday() - timedelta(days=1)

    await bm_service.log_bm(
        session, user, first, occurred_local=_at(first, 7), bristol_type=4
    )
    await bm_service.log_bm(
        session, user, second, occurred_local=_at(second, 7), bristol_type=4
    )
    await session.commit()

    rows = (await session.scalars(select(DailyLog))).all()
    assert len(rows) == 2
    assert {row.n_bms for row in rows} == {1}


async def test_logging_the_same_day_twice_reuses_the_row(
    session: AsyncSession,
) -> None:
    """The uniqueness constraint is what makes "a day is logged" one fact."""
    user = await _user(session)
    day = _yesterday()

    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=4
    )
    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 8), bristol_type=4
    )
    await session.commit()

    assert len((await session.scalars(select(DailyLog))).all()) == 1


# --- nothing today --------------------------------------------------------


async def test_nothing_today_creates_an_empty_day(session: AsyncSession) -> None:
    """A day with no BMs is a real, logged day."""
    user = await _user(session)
    day = _yesterday()

    row = await bm_service.log_nothing_today(session, user, day)
    await session.commit()

    assert row.n_bms == 0
    assert row.id is not None


async def test_future_days_are_refused(session: AsyncSession) -> None:
    """A BM cannot have happened tomorrow."""
    user = await _user(session)
    tomorrow = utcnow().date() + timedelta(days=1)

    with pytest.raises(bm_service.DayInFutureError):
        await bm_service.log_nothing_today(session, user, tomorrow)
    with pytest.raises(bm_service.DayInFutureError):
        await bm_service.log_bm(
            session,
            user,
            tomorrow,
            occurred_local=_at(tomorrow),
            bristol_type=4,
        )


async def test_today_is_allowed(session: AsyncSession) -> None:
    """The boundary is inclusive of today, or nobody could ever log."""
    user = await _user(session)
    today = utcnow().date()

    row = await bm_service.log_nothing_today(session, user, today)
    await session.commit()
    assert row.id is not None


# --- note supersession ----------------------------------------------------


async def test_day_note_is_live_on_an_empty_day(session: AsyncSession) -> None:
    """The nothing-today case, with a note attached."""
    user = await _user(session)
    day = _yesterday()

    row = await bm_service.log_nothing_today(
        session, user, day, notes="long flight, nothing happened"
    )
    await session.commit()
    await session.refresh(row)

    assert row.is_note_live
    assert not row.is_superseded


async def test_day_note_is_superseded_by_the_first_bm(
    session: AsyncSession,
) -> None:
    """Adding a BM overtakes the note, and nothing is written to do it.

    The note is retained, not discarded: the text is still there, it just no
    longer counts or displays as live.
    """
    user = await _user(session)
    day = _yesterday()

    row = await bm_service.log_nothing_today(
        session, user, day, notes="nothing happened"
    )
    assert row.is_note_live

    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=6
    )
    await session.commit()
    await session.refresh(row)

    assert not row.is_note_live
    assert row.is_superseded
    assert row.notes == "nothing happened"


async def test_day_note_returns_when_the_last_bm_goes(
    session: AsyncSession,
) -> None:
    """The reverse transition, equally free of writes."""
    user = await _user(session)
    day = _yesterday()

    row = await bm_service.log_nothing_today(
        session, user, day, notes="nothing happened"
    )
    entry = await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=6
    )
    await session.commit()
    await session.refresh(row)
    assert row.is_superseded

    await bm_service.delete_entry(session, entry)
    await session.commit()
    await session.refresh(row)

    assert row.n_bms == 0
    assert row.is_note_live
    assert row.notes == "nothing happened"


async def test_a_note_is_not_superseded_while_other_bms_remain(
    session: AsyncSession,
) -> None:
    """Only the transition through zero matters, not the number of BMs."""
    user = await _user(session)
    day = _yesterday()

    row = await bm_service.log_nothing_today(session, user, day, notes="rough day")
    first = await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=4
    )
    await session.commit()
    await session.refresh(row)
    assert row.is_superseded

    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 12), bristol_type=4
    )
    await session.commit()
    await session.refresh(row)
    assert row.n_bms == 2
    assert row.is_superseded

    await bm_service.delete_entry(session, first)
    await session.commit()
    await session.refresh(row)
    assert row.n_bms == 1
    assert row.is_superseded, "still one BM left, so the note stays superseded"


async def test_whitespace_is_not_a_note(session: AsyncSession) -> None:
    """A stray space must not earn the point or show as a live note."""
    user = await _user(session)
    day = _yesterday()

    row = await bm_service.log_nothing_today(session, user, day, notes="   \n  ")
    await session.commit()
    await session.refresh(row)

    assert row.notes is None
    assert not row.is_note_live


async def test_logging_an_empty_day_twice_replaces_the_note(
    session: AsyncSession,
) -> None:
    """A day holds exactly one day-note, and re-logging replaces it.

    The day-note used to have its own endpoint and its own form. It is now
    written by logging the day as empty, which is the only thing that produces
    one, so this is the whole of that behaviour.
    """
    user = await _user(session)
    day = _yesterday()

    await bm_service.log_nothing_today(session, user, day, notes="first thought")
    await bm_service.log_nothing_today(session, user, day, notes="second thought")
    await session.commit()

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.notes == "second thought"


async def test_clearing_a_note(session: AsyncSession) -> None:
    """An empty submission clears rather than storing whitespace."""
    user = await _user(session)
    day = _yesterday()

    await bm_service.log_nothing_today(session, user, day, notes="something")
    await bm_service.log_nothing_today(session, user, day, notes=None)
    await session.commit()

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.notes is None


# --- deletion and the counter --------------------------------------------


async def test_deleting_an_entry_decrements_the_count(
    session: AsyncSession,
) -> None:
    """The counter follows its children both ways."""
    user = await _user(session)
    day = _yesterday()

    first = await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=4
    )
    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 9), bristol_type=5
    )
    await session.commit()

    await bm_service.delete_entry(session, first)
    await session.commit()

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 1
    assert row.n_bms == await _count(session, row)


async def test_deleting_a_day_removes_its_entries(session: AsyncSession) -> None:
    """The cascade, and the day goes with them."""
    user = await _user(session)
    day = _yesterday()

    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=4
    )
    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 9), bristol_type=4
    )
    await session.commit()

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    await bm_service.delete_day(session, row)
    await session.commit()

    assert await session.scalar(select(func.count()).select_from(DailyLog)) == 0
    assert await session.scalar(select(func.count()).select_from(BmEntry)) == 0


async def test_recount_repairs_a_drifted_counter(session: AsyncSession) -> None:
    """A drifted counter is correctable without hand-editing SQL."""
    user = await _user(session)
    day = _yesterday()

    await bm_service.log_bm(
        session, user, day, occurred_local=_at(day, 7), bristol_type=4
    )
    await session.commit()

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    row.n_bms = 99
    await session.commit()

    assert await bm_service.recount(session, row) == 1
    await session.commit()
    await session.refresh(row)
    assert row.n_bms == 1


async def test_the_counter_never_drifted(session: AsyncSession) -> None:
    """A mixed day, checked end to end against the real count."""
    user = await _user(session)
    day = _yesterday()

    entries = [
        await bm_service.log_bm(
            session, user, day, occurred_local=_at(day, hour), bristol_type=4
        )
        for hour in (7, 9, 14)
    ]
    await session.commit()

    row = await bm_service.get_day(session, user, day)
    assert row is not None
    assert row.n_bms == 3 == await _count(session, row)

    await bm_service.delete_entry(session, entries[1])
    await session.commit()
    await session.refresh(row)

    assert row.n_bms == 2 == await _count(session, row)


# --- validation -----------------------------------------------------------


@pytest.mark.parametrize("bad_type", [0, 8, -1, 99])
async def test_an_out_of_range_type_is_refused(
    session: AsyncSession, bad_type: int
) -> None:
    """The service refuses it before the database has to."""
    user = await _user(session)
    day = _yesterday()

    with pytest.raises(ValueError, match="Bristol"):
        await bm_service.log_bm(
            session, user, day, occurred_local=_at(day), bristol_type=bad_type
        )


def test_time_parsing_accepts_and_rejects() -> None:
    """`HH:MM` in, `HH:MM` out; rubbish rejected rather than guessed."""
    assert parse_time("7:05") == "07:05"
    assert parse_time("23:59") == "23:59"
    assert parse_time("24:00") is None
    assert parse_time("7:60") is None
    assert parse_time("half seven") is None
    assert parse_time("") is None
    assert parse_time(None) is None


def test_date_parsing_rejects_rubbish() -> None:
    """A bad date is `None`, not an exception from deep in a handler."""
    assert parse_date("2026-01-09") == date(2026, 1, 9)
    assert parse_date("not-a-date") is None
    assert parse_date("") is None
    assert parse_date("2026-13-01") is None
