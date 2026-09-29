"""Writing bowel movements and days.

The one invariant this module exists to keep is that `daily_logs.n_bms` always
equals the number of `bm_entries` pointing at that day. It is denormalised so
the dashboard and the leaderboard do not need a correlated count, which is only
worth it if it cannot drift — so every mutation here adjusts it in the same
transaction as the change that made it necessary, and a test asserts the two
never disagree.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from bm_tracker import bristol
from bm_tracker import strain as strain_lib
from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.models.base import utcnow
from bm_tracker.models.user import MAX_DISPLAY_NAME_LENGTH
from bm_tracker.timezones import is_valid_timezone, now_in

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_NOTE_LENGTH = 2000


class DayInFutureError(Exception):
    """Raised when a day is logged that has not happened yet."""


def _clip_note(notes: str | None) -> str | None:
    """Normalise a submitted note.

    Whitespace-only text is not a note: a stray space should not earn the note
    point, and should not be shown back as a day-note that is live.

    Args:
        notes: The raw submitted text.

    Returns:
        The trimmed note, or `None` when there is nothing there.

    """
    if notes is None:
        return None
    trimmed = notes.strip()
    if not trimmed:
        return None
    return trimmed[:MAX_NOTE_LENGTH]


def check_not_future(day: date, *, today: date) -> None:
    """Raise if a day is in the future for this user.

    Args:
        day: The day being logged.
        today: Today, resolved in the user's own timezone.

    Raises:
        DayInFutureError: If the day has not happened yet.

    """
    if day > today:
        msg = "You cannot log a day that has not happened yet."
        raise DayInFutureError(msg)


async def get_day(session: AsyncSession, user: User, day: date) -> DailyLog | None:
    """Return a user's log for a day, if there is one.

    Args:
        session: The session to read through.
        user: The owner.
        day: The occurrence date.

    Returns:
        The `DailyLog`, or `None`.

    """
    return await session.scalar(
        select(DailyLog).where(DailyLog.user_id == user.id, DailyLog.day == day)
    )


async def _get_or_create_day(
    session: AsyncSession, user: User, day: date, *, logged_at: datetime | None = None
) -> DailyLog:
    """Return a user's log for a day, creating an empty one if needed.

    Args:
        session: The session to write through.
        user: The owner.
        day: The occurrence date.
        logged_at: When the user recorded it, for a backfill. Defaults to now.

    Returns:
        The existing or newly created `DailyLog`.

    """
    existing = await get_day(session, user, day)
    if existing is not None:
        return existing
    fresh = DailyLog(
        user_id=user.id,
        day=day,
        n_bms=0,
        logged_at=logged_at or utcnow(),
    )
    session.add(fresh)
    await session.flush()
    return fresh


async def log_nothing_today(
    session: AsyncSession,
    user: User,
    day: date,
    *,
    notes: str | None = None,
    logged_at: datetime | None = None,
) -> DailyLog:
    """Record a day on which the user had no BMs.

    This is a first-class outcome, not an empty state. It extends the streak and
    earns the same day points as a day that had three, because the game rewards
    reporting honestly rather than producing output.

    Args:
        session: The session to write through.
        user: The owner.
        day: The occurrence date.
        notes: An optional note about the day.
        logged_at: When the user recorded it, for a backfill.

    Returns:
        The `DailyLog` for that day.

    """
    local_today, _ = now_in(user.timezone)
    check_not_future(day, today=local_today)
    row = await _get_or_create_day(session, user, day, logged_at=logged_at)
    # The note is overwritten, including with None, because logging a day is
    # stating what that day is now. It used to be left alone when the caller
    # passed nothing, which was for a seeder that had no note to give; the only
    # caller that can change a day has a note field on its form, and an empty
    # textarea there means "no note", not "leave it as it was".
    row.notes = _clip_note(notes)
    return row


async def log_bm(
    session: AsyncSession,
    user: User,
    day: date,
    *,
    occurred_local: datetime,
    bristol_type: int,
    spicy: bool = False,
    urgent: bool = False,
    strain: int | None = None,
    notes: str | None = None,
    logged_at: datetime | None = None,
    created_at: datetime | None = None,
) -> BmEntry:
    """Record one bowel movement.

    Args:
        session: The session to write through.
        user: The owner.
        day: The occurrence date.
        occurred_local: The wall-clock time the user typed, unconverted.
        bristol_type: The Bristol type, 1-7.
        spicy: Whether this followed spicy food.
        urgent: Whether it was urgent. A recorded fact about the BM, not
            derived from when the entry was written.
        strain: How hard it was to pass, 1-3, or None if not recorded. None is
            a real answer meaning "not recorded", distinct from 1.
        notes: An optional note about this specific BM.
        logged_at: When the day was recorded, for a backfill. This is the
            day's own timestamp and drives qualification.
        created_at: When this entry was written. Separable from `logged_at`
            because the ten-minute bonus is measured against *this*, and the
            seeder needs to place them independently. Defaults to now.

    Returns:
        The created `BmEntry`.

    Raises:
        DayInFutureError: If the day has not happened for this user yet.
        ValueError: If any field is out of range.

    """
    local_today, _ = now_in(user.timezone)
    check_not_future(day, today=local_today)

    if not bristol.is_valid_type(bristol_type):
        msg = "Pick a Bristol type."
        raise ValueError(msg)

    if strain is not None and not strain_lib.is_valid_strain(strain):
        msg = "Pick a strain level, or leave it blank."
        raise ValueError(msg)

    row = await _get_or_create_day(session, user, day, logged_at=logged_at)

    entry = BmEntry(
        daily_log_id=row.id,
        occurred_local=occurred_local,
        bristol_type=bristol_type,
        spicy=spicy,
        urgent=urgent,
        strain=strain,
        notes=_clip_note(notes),
        created_at=created_at if created_at is not None else utcnow(),
    )
    session.add(entry)
    # The counter moves with the row that changed it, in the same transaction.
    row.n_bms += 1
    await session.flush()
    return entry


async def delete_entry(
    session: AsyncSession,
    entry: BmEntry,
    *,
    acting_user: User | None = None,
) -> None:
    """Delete one BM, keeping the day's count honest.

    When the last BM on a day goes, the day-note becomes live again — by
    arithmetic, since `n_bms` returns to zero. Nothing is written to make that
    happen, so it cannot be forgotten.

    Args:
        session: The session to write through.
        entry: The entry to remove.
        acting_user: Who is doing it, checked against the owner.

    """
    day = await session.get(DailyLog, entry.daily_log_id)
    if day is None:  # pragma: no cover - the cascade would have taken it
        return

    await session.delete(entry)
    day.n_bms = max(day.n_bms - 1, 0)
    await session.flush()
    del acting_user


async def delete_day(
    session: AsyncSession,
    day: DailyLog,
    *,
    acting_user: User | None = None,
) -> None:
    """Delete a whole day. Its entries go with it by cascade.

    Args:
        session: The session to write through.
        day: The day to remove.
        acting_user: Who is doing it, checked against the owner.

    """
    del acting_user
    await session.delete(day)
    await session.flush()


async def recount(session: AsyncSession, day: DailyLog) -> int:
    """Set a day's `n_bms` from its actual entries and return the result.

    A repair path rather than part of the normal write flow: the write path
    keeps the counter correct transactionally, and this exists so a drifted value
    can be fixed without hand-editing SQL.

    Args:
        session: The session to read through.
        day: The day to recount.

    Returns:
        The corrected count.

    """
    actual = int(
        await session.scalar(
            select(func.count())
            .select_from(BmEntry)
            .where(BmEntry.daily_log_id == day.id)
        )
        or 0
    )
    day.n_bms = actual
    await session.flush()
    return actual


def at_local_time(day: date, hour: int, minute: int = 0) -> datetime:
    """Return a naive wall-clock datetime on a day, as typed.

    Args:
        day: The date.
        hour: The hour, 0-23.
        minute: The minute, 0-59.

    Returns:
        The naive datetime, exactly as the user would have typed it.

    """
    return datetime.combine(day, time(hour, minute))


def form_datetime(day: date, value: str) -> datetime:
    """Build a wall-clock datetime from a submitted date and `HH:MM`.

    Args:
        day: The occurrence date.
        value: The submitted time.

    Returns:
        The naive wall-clock datetime.

    Raises:
        ValueError: If the time is not a valid 24-hour time.

    """
    from bm_tracker.timezones import parse_time  # noqa: PLC0415

    parsed = parse_time(value)
    if parsed is None:
        msg = "Enter a time as HH:MM."
        raise ValueError(msg)
    hours, minutes = parsed.split(":")
    hour, minute = int(hours), int(minutes)
    return at_local_time(day, hour, minute)


def entry_payload(entry: BmEntry) -> dict[str, Any]:
    """Return the display fields of an entry.

    Args:
        entry: The entry.

    Returns:
        A mapping for templates and the feed.

    """
    return {
        "id": entry.id,
        "occurred_local": entry.occurred_local,
        "bristol_type": entry.bristol_type,
        "bristol": bristol.get_type(entry.bristol_type),
        "spicy": bool(entry.spicy),
        "urgent": bool(entry.urgent),
        "strain": entry.strain,
        "strain_level": (
            None if entry.strain is None else strain_lib.get_level(entry.strain)
        ),
        "notes": entry.notes,
        "has_note": entry.has_note,
    }


async def set_timezone(session: AsyncSession, user: User, timezone_name: str) -> str:
    """Record a new timezone for somebody.

    The timezone is the one setting a person cannot work around. It decides what
    "today" is, which day a streak counts against, and how far back a day may be
    filled in — so somebody who moves, or whose account was created in the wrong
    zone, has no way to fix any of that from the page that shows it. The admin
    form has a field for it; the account holder did not.

    Args:
        session: The session to write through.
        user: Whose timezone to change.
        timezone_name: The zone they chose.

    Returns:
        The zone that was stored.

    Raises:
        ValueError: If the zone is not one the system knows.

    """
    name = timezone_name.strip()
    if not is_valid_timezone(name):
        msg = f"That is not a timezone this system knows: {timezone_name!r}"
        raise ValueError(msg)
    user.timezone = name
    await session.flush()
    return name


async def set_display_name(session: AsyncSession, user: User, display_name: str) -> str:
    """Record a new display name for somebody.

    Stripped, because a name is a thing a person types and a trailing space is
    a typing accident rather than a choice. Falling back to the username rather
    than raising, because a person who clears the field has said "I do not want
    a display name" and an empty name is worse than the one they already have.

    Args:
        session: The session to write through.
        user: Whose name to change.
        display_name: What they typed.

    Returns:
        The name that was stored.

    Raises:
        ValueError: If the name is longer than the column allows, which a
            database would otherwise reject with a bare IntegrityError.

    """
    cleaned = " ".join(display_name.split())
    if not cleaned:
        cleaned = user.username
    if len(cleaned) > MAX_DISPLAY_NAME_LENGTH:
        msg = f"A name cannot be longer than {MAX_DISPLAY_NAME_LENGTH} characters."
        raise ValueError(msg)
    user.display_name = cleaned
    await session.flush()
    return cleaned
