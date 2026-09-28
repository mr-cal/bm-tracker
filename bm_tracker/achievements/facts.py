"""Derived per-user facts, the input to achievement evaluation.

Re-scanning history for each of 300 achievements on every write would be
900,000 row visits. Instead the engine reads a small record of scalars per user,
which turns each achievement into a handful of integer comparisons.

Facts are maintained incrementally on every write, and `rebuild` recomputes them
from raw data. The difference between the two is asserted in the tests, which is
what makes drift a non-issue rather than a worry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Final

from sqlalchemy import delete, func, select

from bm_tracker import scoring
from bm_tracker.achievements import rules
from bm_tracker.achievements.rules import Facts
from bm_tracker.models import DailyLog, User, UserFact

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: Facts every evaluation reads. A missing one is zero, not an error, so a new
#: achievement can use a fact before any user has earned it.
#: Saturday. `date.weekday()` is Monday-0, so the weekend is the last two.
FIRST_WEEKEND_DAY = 5
#: Friday, and the thirteenth.
THIRTEENTH = 13
FRIDAY = 4

#: Dates worth an achievement, as a fact name to the month and day it needs.
#: The names are the rule's vocabulary, so adding one here and one fact in
#: FACT_KEYS is the whole cost of a new occasion.
OCCASIONS: Final[dict[str, tuple[int, int]]] = {
    "jan_1": (1, 1),
    "feb_2": (2, 2),
    "feb_14": (2, 14),
    "feb_29": (2, 29),
    "mar_15": (3, 15),
    "apr_1": (4, 1),
    "may_1": (5, 1),
    "jun_21": (6, 21),
    "oct_31": (10, 31),
    "nov_5": (11, 5),
    "dec_21": (12, 21),
    "dec_24": (12, 24),
    "dec_25": (12, 25),
    "dec_26": (12, 26),
    "dec_31": (12, 31),
}

#: The facts every evaluation reads, and the ones a rule may name. One list, in
#: `rules`, because two lists that must agree is how they drift — and they had.
FACT_KEYS: Final[tuple[str, ...]] = tuple(sorted(rules.KNOWN_FACTS))


@dataclass
class FactSet(Facts):
    """A user's facts, with the protocol `get` the rules call."""

    values: dict[str, float] = field(default_factory=dict)

    def get(self, key: str) -> float:
        """Return a fact, or zero when it is unknown or unset.

        Args:
            key: The fact name.

        Returns:
            The value, defaulting to zero.

        """
        return self.values.get(key, 0.0)

    def __getitem__(self, key: str) -> float:
        """Return a fact, so callers can treat it like a mapping.

        Args:
            key: The fact name.

        Returns:
            The value, defaulting to zero.

        """
        return self.get(key)


async def build(
    session: AsyncSession,
    user: User,
    year: int,
    *,
    window_minutes: int = 10,
) -> FactSet:
    """Derive a user's facts for a year from raw data.

    The reference implementation. The incremental path must agree with this, and
    a test asserts it does.

    Args:
        session: The session to read through.
        user: The user to derive.
        year: The calendar year.
        window_minutes: The ten-minute bonus window.

    Returns:
        The derived `FactSet`.

    """
    from bm_tracker.models import BmEntry  # noqa: PLC0415

    rows = (
        await session.execute(
            select(DailyLog, BmEntry)
            .outerjoin(BmEntry, BmEntry.daily_log_id == DailyLog.id)
            .where(
                DailyLog.user_id == user.id,
                DailyLog.day >= date(year, 1, 1),
                DailyLog.day <= date(year, 12, 31),
            )
            .order_by(DailyLog.day, BmEntry.occurred_local)
        )
    ).all()

    days = [day for day, _ in rows]
    entries = [entry for _, entry in rows if entry is not None]

    score = await scoring.score_year(session, user, year, window_minutes=window_minutes)

    seen_types = {e.bristol_type for e in entries}
    delays = [
        abs((e.created_at - e.occurred_local).total_seconds()) / 60 for e in entries
    ]
    hour_values = [
        e.occurred_local.hour + e.occurred_local.minute / 60 for e in entries
    ]

    consecutive_spicy = 0
    best_spicy_run = 0
    for day in days:
        spicy_that_day = any(
            entry is not None and entry.spicy
            for candidate, entry in rows
            if candidate.day == day.day
        )
        if spicy_that_day:
            consecutive_spicy += 1
            best_spicy_run = max(best_spicy_run, consecutive_spicy)
        elif any(
            entry is not None for candidate, entry in rows if candidate.day == day.day
        ):
            consecutive_spicy = 0

    gaps = _gaps(days)
    first_day = days[0].day if days else None
    last_day = days[-1].day if days else None

    # Calendar and self-denial facts, all derived in this one pass so the
    # builder stays a single scan of the year.
    entry_days = [e.occurred_local.date() for e in entries]
    weekdays = {d.weekday() for d in entry_days}
    months = {d.month for d in entry_days}
    weekend_count = float(
        sum(1 for d in entry_days if d.weekday() >= FIRST_WEEKEND_DAY)
    )
    notes_per_day = {
        day.day: sum(
            1 for e in entries if e.occurred_local.date() == day.day and e.has_note
        )
        for day in days
    }

    run_without_note = 0
    best_run_without_note = 0
    for day in days:
        if day.n_bms == 0 or day.notes and day.notes.strip():
            run_without_note = 0
            continue
        if notes_per_day.get(day.day):
            run_without_note = 0
            continue
        run_without_note += 1
        best_run_without_note = max(best_run_without_note, run_without_note)

    backfilled_days = float(
        sum(
            1
            for day in days
            if not scoring.qualifies(day.day, day.logged_at, user.timezone)
        )
    )
    deleted_entries = float(await _deleted_count(session, user.id, year))

    entry_dates = set(entry_days)
    occasions: dict[str, float] = {
        f"logged_{name}": float(1 if (month, day) in entry_dates else 0)
        for name, (month, day) in OCCASIONS.items()
    }
    occasions["logged_friday_13"] = float(
        sum(1 for d in entry_dates if d.day == THIRTEENTH and d.weekday() == FRIDAY)
    )

    values: dict[str, float] = {
        **occasions,
        "bm_count_total": float(len(entries)),
        "bm_count_day": float(max((d.n_bms for d in days), default=0)),
        "max_bms_in_day": float(max((d.n_bms for d in days), default=0)),
        "days_logged_total": float(len(days)),
        "note_count": float(
            sum(1 for d in days if d.notes and d.notes.strip())
            + sum(1 for e in entries if e.has_note)
        ),
        "spicy_count": float(sum(1 for e in entries if e.spicy)),
        "noted_entry_count": float(sum(1 for e in entries if e.has_note)),
        "bristol_type": float(max(seen_types, default=0)),
        "bristol_types_seen": float(len(seen_types)),
        "streak_current": float(score.current_streak),
        "streak_longest": float(score.longest_streak),
        "time_of_day": max(hour_values, default=0.0),
        "fastest_entry_delay": min(delays, default=0.0) if delays else 0.0,
        "logged_same_day": 1.0 if (last_day and _is_today(last_day, user)) else 0.0,
        "gap_since_previous_days": float(max(gaps, default=0)),
        "max_spicy_consecutive_days": float(best_spicy_run),
        "distinct_weekdays_logged": float(len(weekdays)),
        "distinct_months_logged": float(len(months)),
        "weekend_entry_count": weekend_count,
        "longest_run_without_note": float(best_run_without_note),
        "all_entries_noted": float(
            bool(entries)
            and len(notes_per_day and {e.id for e in entries if e.has_note})
            == len(entries)
        ),
        "backfilled_days": backfilled_days,
        "deleted_entries": deleted_entries,
    }
    if first_day is not None:
        values["logged_same_day"] = (
            1.0 if _is_today(last_day or first_day, user) else 0.0
        )

    return FactSet(values=values)


async def _deleted_count(session: AsyncSession, user_id: int, year: int) -> int:
    """Return how many entries this person deleted in the year.

    Read from the audit log rather than counted from the data, because a deleted
    row is by definition not there any more — the only surviving trace of it is
    the record that it was removed.

    Args:
        session: The session to read through.
        user_id: Whose deletions to count.
        year: The calendar year.

    Returns:
        How many entries were deleted.

    """
    from bm_tracker.models import AuditLog  # noqa: PLC0415

    return int(
        await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.user_id == user_id,
                AuditLog.action == "entry.delete",
                func.strftime("%Y", AuditLog.at) == str(year),
            )
        )
        or 0
    )


def _is_today(day: date, user: User) -> bool:
    """Return whether a day is the user's today.

    Args:
        day: The day to check.
        user: The user whose timezone decides.

    Returns:
        Whether it is today for them.

    """
    from bm_tracker.timezones import today_for  # noqa: PLC0415

    return day == today_for(user.timezone)


def _gaps(days: list[DailyLog]) -> list[int]:
    """Return the sizes of the gaps between consecutive logged days.

    Args:
        days: The logged days, in order.

    Returns:
        The gap lengths in days, one fewer than the number of days.

    """
    ordered = sorted({d.day for d in days})
    return [
        (later - earlier).days
        for earlier, later in zip(ordered, ordered[1:], strict=False)
    ]


async def load(session: AsyncSession, user_id: int, year: int) -> FactSet:
    """Return a user's stored facts for a year.

    Args:
        session: The session to read through.
        user_id: Whose facts.
        year: The calendar year.

    Returns:
        The stored `FactSet`, empty if the user has none yet.

    """
    rows = (
        await session.execute(
            select(UserFact).where(
                UserFact.user_id == user_id,
                UserFact.fact_key.like(f"{year}:%"),
            )
        )
    ).all()
    return FactSet(values={row.fact_key: row.fact_value for row in rows})


async def store(session: AsyncSession, user_id: int, year: int, facts: FactSet) -> None:
    """Write a user's facts for a year, replacing whatever was there.

    Args:
        session: The session to write through.
        user_id: Whose facts.
        year: The calendar year.
        facts: The values to persist.

    """
    await session.execute(
        delete(UserFact).where(
            UserFact.user_id == user_id, UserFact.fact_key.like(f"{year}:%")
        )
    )
    session.add_all(
        UserFact(user_id=user_id, fact_key=f"{year}:{key}", fact_value=value)
        for key, value in facts.values.items()
    )


__all__ = ["FACT_KEYS", "FactSet", "build", "load", "store"]
