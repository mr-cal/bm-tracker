"""Scoring: points, streaks and the year boundary.

Every rule lives here, and nothing is stored. Points are *derived* on read
because a backfill or an edit changes what a day was worth — a materialised
score would be wrong the moment either happened, and wrong silently. The
constants below are the whole of the game economy; retuning one re-scores
everyone's history instantly, with no migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.timezones import resolve_timezone, year_bounds

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# --- the rules ------------------------------------------------------------

POINTS_PER_QUALIFYING_DAY: Final = 10
# +1 on the second day of a run, +2 on the third, and so on. Capped so that a
# long streak cannot become an unrecoverable lead that one missed day turns into
# a permanent deficit.
STREAK_BONUS_STEP: Final = 1
STREAK_BONUS_MAX_STEPS: Final = 5

# Small on purpose. A year of perfect logging is 365 x 15 = 5,475, so 3 is
# roughly 0.05% of a year: enough to reward filling in what actually happened,
# not enough to be a strategy.
POINTS_BACKFILLED_DAY: Final = 3

POINTS_QUICK_ENTRY: Final = 1
POINTS_NOTE: Final = 1

# A day qualifies only if it was recorded on the same calendar day it happened,
# in the user's own timezone. There is no grace period and no way to waive a
# missed day: the game is to log it as it occurs.
SAME_DAY_REQUIRED: Final = True


@dataclass(frozen=True, slots=True)
class DayScore:
    """One day's contribution to a total."""

    day: date
    logged_at: datetime
    n_bms: int
    points: int
    qualified: bool
    backfilled: bool
    position: int
    note_points: int
    entry_points: int
    has_live_note: bool

    @property
    def total(self) -> int:
        """Return the day's whole contribution, bonuses included."""
        return self.points + self.note_points + self.entry_points


@dataclass(frozen=True, slots=True)
class UserScore:
    """A user's derived standing for one year."""

    user_id: int
    year: int
    days: tuple[DayScore, ...]

    @property
    def day_points(self) -> int:
        """Return points from days, including streak and backfill awards."""
        return sum(day.points for day in self.days)

    @property
    def note_points(self) -> int:
        """Return points from notes, on days or on individual BMs."""
        return sum(day.note_points for day in self.days)

    @property
    def entry_points(self) -> int:
        """Return points from the ten-minute bonus."""
        return sum(day.entry_points for day in self.days)

    @property
    def logging_points(self) -> int:
        """Return everything earned by logging. The competitive total."""
        return self.day_points + self.note_points + self.entry_points

    @property
    def days_logged(self) -> int:
        """Return how many days were recorded at all, on time or late."""
        return len(self.days)

    @property
    def qualifying_days(self) -> int:
        """Return how many days were recorded on the day they happened."""
        return sum(1 for day in self.days if day.qualified)

    @property
    def bms(self) -> int:
        """Return how many BMs were recorded."""
        return sum(day.n_bms for day in self.days)

    @property
    def current_streak(self) -> int:
        """Return the length of the run ending on the most recently recorded day.

        `position` is already the length of the contiguous run that ends at its
        day, so the answer is the last day's position — unless the last day was
        not qualifying, in which case the run ended earlier and the streak is
        over.

        Taking the largest position anywhere in the year would instead report an
        old, abandoned run as the current one.
        """
        if not self.days:
            return 0
        last = self.days[-1]
        return last.position if last.qualified else 0

    @property
    def longest_streak(self) -> int:
        """Return the longest run of qualifying days in the year."""
        return max((day.position for day in self.days if day.qualified), default=0)


def qualifies(day: date, logged_at: datetime, timezone_name: str) -> bool:
    """Return whether a day was recorded on the day it happened.

    Args:
        day: The occurrence date.
        logged_at: When the user recorded it, as naive UTC.
        timezone_name: The user's IANA timezone.

    Returns:
        Whether it was same-day for that user.

    """
    if not SAME_DAY_REQUIRED:
        return True
    # `logged_at` is naive UTC. Attaching the user's zone with `replace` would
    # *interpret* the UTC clock time as local time; the instant has to be
    # anchored to UTC first and then converted.
    local = (
        logged_at.replace(tzinfo=resolve_timezone("UTC"))
        .astimezone(resolve_timezone(timezone_name))
        .date()
    )
    return local == day


def streak_bonus(position: int) -> int:
    """Return the streak bonus for a day at a given position in its run.

    Args:
        position: 1-based position within the run of qualifying days.

    Returns:
        The bonus, capped at `STREAK_BONUS_MAX_STEPS * STREAK_BONUS_STEP`.

    """
    if position < 1:
        return 0
    return STREAK_BONUS_STEP * min(position - 1, STREAK_BONUS_MAX_STEPS)


def total_for_run(days: int) -> int:
    """Return the points a run of consecutive qualifying days is worth.

    The same derivation the scorer uses, so the worked example on the help page
    cannot drift from the scoring it is explaining.

    Args:
        days: How many consecutive days.

    Returns:
        The total across all of them.

    """
    return sum(
        POINTS_PER_QUALIFYING_DAY + streak_bonus(position)
        for position in range(1, max(days, 0) + 1)
    )


def day_points(*, qualified: bool, position: int) -> int:
    """Return the base points for a day.

    Args:
        qualified: Whether it was recorded on the day it happened.
        position: Its position in its run, when qualified.

    Returns:
        The base points: the full award when qualified, the backfill award when
        not.

    """
    if not qualified:
        return POINTS_BACKFILLED_DAY
    return POINTS_PER_QUALIFYING_DAY + streak_bonus(position)


def note_points(
    *,
    has_live_day_note: bool,
    noted_entry_ids: set[int],
    entry_ids: set[int],
) -> int:
    """Return the points earned by notes on a day.

    A live day-note pays, and so does each individual BM note. A day-note that
    has been superseded by a BM does not pay: the day is described by its
    entries, and the note is retained but overtaken.

    Args:
        has_live_day_note: Whether the day-note is currently live.
        noted_entry_ids: The ids of entries carrying a note.
        entry_ids: The ids of every entry on the day.

    Returns:
        The note points.

    """
    total = POINTS_NOTE if has_live_day_note else 0
    return total + POINTS_NOTE * len(noted_entry_ids & entry_ids)


def entry_points(*, quick_ids: set[int], entry_ids: set[int]) -> int:
    """Return the points earned by the ten-minute bonus on a day.

    The window has already been applied by the caller when it built `quick_ids`,
    so this only has to intersect and count.

    Args:
        quick_ids: The ids of entries the caller found within the window.
        entry_ids: The ids of every entry on the day.

    Returns:
        One point per qualifying entry.

    """
    return POINTS_QUICK_ENTRY * len(quick_ids & entry_ids)


def is_quick(
    created_at: datetime, occurred_local: datetime, window_minutes: int
) -> bool:
    """Return whether an entry was recorded close enough to when it happened.

    The comparison is absolute, so a user who types "07:00" and submits at 06:57
    still qualifies: they were close, and penalising a rounding slip is not the
    intent.

    Args:
        created_at: When the entry was written, as naive UTC.
        occurred_local: The wall-clock time the user typed, unconverted.
        window_minutes: The window size, in minutes.

    Returns:
        Whether the bonus applies.

    """
    delta = abs((created_at - occurred_local).total_seconds())
    return delta <= window_minutes * 60


async def score_year(
    session: AsyncSession,
    user: User,
    year: int,
    *,
    window_minutes: int = 10,
) -> UserScore:
    """Derive a user's whole standing for a year.

    Reads the days, then walks backwards from each to find its position in its
    run. The walk is bounded at 1 January, so a streak never crosses the year
    boundary: a new year is a fresh start, and everybody competes over the same
    window.

    Args:
        session: The session to read through.
        user: The user to score.
        year: The calendar year.
        window_minutes: The ten-minute bonus window.

    Returns:
        A `UserScore` with one `DayScore` per recorded day.

    """
    start, end = year_bounds(year)
    rows = list(
        (
            await session.scalars(
                select(DailyLog)
                .where(
                    DailyLog.user_id == user.id,
                    DailyLog.day >= start,
                    DailyLog.day <= end,
                )
                .order_by(DailyLog.day)
            )
        ).all()
    )
    if not rows:
        return UserScore(user_id=user.id, year=year, days=())

    entries_by_day = await _entries_by_day(session, [row.id for row in rows])
    return _derive(
        user=user,
        year=year,
        rows=rows,
        entries_by_day=entries_by_day,
        window_minutes=window_minutes,
    )


async def _entries_by_day(
    session: AsyncSession, daily_log_ids: list[int]
) -> dict[int, list[BmEntry]]:
    """Return every entry on the given days, grouped by its day.

    One query for all of them. It used to be one per day, which on a two-year
    history is hundreds of round trips to produce the same answer.

    Args:
        session: The session to read through.
        daily_log_ids: The days to load entries for.

    Returns:
        Entries keyed by `daily_log_id`; a day with no entries is absent.

    """
    if not daily_log_ids:
        return {}
    rows = (
        await session.scalars(
            select(BmEntry).where(BmEntry.daily_log_id.in_(daily_log_ids))
        )
    ).all()
    grouped: dict[int, list[BmEntry]] = {}
    for entry in rows:
        grouped.setdefault(entry.daily_log_id, []).append(entry)
    return grouped


def _derive(
    *,
    user: User,
    year: int,
    rows: list[DailyLog],
    entries_by_day: dict[int, list[BmEntry]],
    window_minutes: int,
) -> UserScore:
    """Build a `UserScore` from rows already in hand.

    The arithmetic half of `score_year`, with no database in it. Split out so
    the leaderboard can load every user's year once and derive from memory
    rather than re-querying per person.

    Args:
        user: The user to score.
        year: The calendar year.
        rows: Their days in the year, in order.
        entries_by_day: Their entries, keyed by `daily_log_id`.
        window_minutes: The ten-minute bonus window.

    Returns:
        A `UserScore` with one `DayScore` per recorded day.

    """
    start, _ = year_bounds(year)
    by_day = {row.day: row for row in rows}
    entry_ids_by_day: dict[date, set[int]] = {}
    noted_by_day: dict[date, set[int]] = {}
    quick_by_day: dict[date, set[int]] = {}

    for row in rows:
        entries = entries_by_day.get(row.id, [])
        entry_ids_by_day[row.day] = {entry.id for entry in entries}
        noted_by_day[row.day] = {entry.id for entry in entries if entry.has_note}
        quick_by_day[row.day] = {
            entry.id
            for entry in entries
            if is_quick(entry.created_at, entry.occurred_local, window_minutes)
        }

    positions: dict[date, int] = {}
    floor = start - timedelta(days=1)
    for row in rows:
        if not qualifies(row.day, row.logged_at, user.timezone):
            continue
        position = 1
        cursor = row.day - timedelta(days=1)
        while cursor >= floor and cursor >= start - timedelta(days=1):
            previous = by_day.get(cursor)
            if previous is None or not qualifies(
                previous.day, previous.logged_at, user.timezone
            ):
                break
            position += 1
            cursor -= timedelta(days=1)
        positions[row.day] = position

    days: list[DayScore] = []
    for row in rows:
        qualified = qualifies(row.day, row.logged_at, user.timezone)
        position = positions.get(row.day, 0)
        live_note = bool(row.is_note_live)
        days.append(
            DayScore(
                day=row.day,
                logged_at=row.logged_at,
                n_bms=row.n_bms,
                points=day_points(qualified=qualified, position=position),
                qualified=qualified,
                backfilled=not qualified,
                position=position,
                note_points=note_points(
                    has_live_day_note=live_note,
                    noted_entry_ids=noted_by_day[row.day],
                    entry_ids=entry_ids_by_day[row.day],
                ),
                entry_points=entry_points(
                    quick_ids=quick_by_day[row.day],
                    entry_ids=entry_ids_by_day[row.day],
                ),
                has_live_note=live_note,
            )
        )

    return UserScore(user_id=user.id, year=year, days=tuple(days))


async def score_all_users(
    session: AsyncSession,
    users: list[User],
    year: int,
    *,
    window_minutes: int = 10,
) -> list[UserScore]:
    """Derive several users' standings for a leaderboard.

    Three queries for everybody, not three per person. It used to await
    `score_year` for each user in turn, and `score_year` itself issued a query
    per day, so eight people with two years of history came to roughly four
    thousand round trips — about 400ms of the leaderboard's time, against 5ms
    for the log form.

    Args:
        session: The session to read through.
        users: The users to score.
        year: The calendar year.
        window_minutes: The ten-minute bonus window.

    Returns:
        One `UserScore` per user, in the order given.

    """
    start, end = year_bounds(year)
    day_rows = list(
        (
            await session.scalars(
                select(DailyLog).where(
                    DailyLog.user_id.in_([u.id for u in users]),
                    DailyLog.day >= start,
                    DailyLog.day <= end,
                )
            )
        ).all()
    )
    entries_by_day = await _entries_by_day(session, [day.id for day in day_rows])

    rows_by_user: dict[int, list[DailyLog]] = {}
    for day in day_rows:
        rows_by_user.setdefault(day.user_id, []).append(day)
    for rows in rows_by_user.values():
        rows.sort(key=lambda r: r.day)

    return [
        _derive(
            user=user,
            year=year,
            rows=rows_by_user.get(user.id, []),
            entries_by_day=entries_by_day,
            window_minutes=window_minutes,
        )
        for user in users
    ]


def rank(
    scores: list[UserScore], users_by_id: dict[int, User]
) -> list[tuple[User, UserScore]]:
    """Order standings for a leaderboard.

    Sorted by logging points, so achievement points cannot reorder the board.
    Ties break on the longest streak, then on the username, so the order is
    stable between renders rather than depending on dict ordering.

    Args:
        scores: The standings to order.
        users_by_id: A lookup from user id to `User`, for tie-breaking.

    Returns:
        `(user, score)` pairs, best first.

    """

    def _key(pair: tuple[int, UserScore]) -> tuple[int, int, str]:
        user_id, score = pair
        username = users_by_id[user_id].username if user_id in users_by_id else ""
        return (-score.logging_points, -score.longest_streak, username)

    pairs = [(score.user_id, score) for score in scores]
    pairs.sort(key=_key)
    return [(users_by_id[uid], score) for uid, score in pairs if uid in users_by_id]
