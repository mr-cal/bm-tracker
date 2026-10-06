"""What a single log actually earned, itemised.

The dashboard can tell you a year totals 2,742 points, and a number that size
does not teach anything. This works the other way up: it takes one action — a
BM or an empty day — and says which of the rules it triggered, one line at a
time, so the scoring stops being arithmetic happening somewhere.

Every line comes from the same constants and the same helpers the scorer uses,
rather than from a second copy of the arithmetic. A reward screen that disagreed
with the leaderboard would be worse than no reward screen at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from bm_tracker import scoring
from bm_tracker.models import DailyLog
from bm_tracker.timezones import year_bounds

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from bm_tracker.models import BmEntry, User


@dataclass(frozen=True, slots=True)
class RewardLine:
    """One thing that earned points, and why."""

    label: str
    points: int
    # A line with no detail reads worse than one with, so the detail is part of
    # the line rather than an afterthought in the template.
    detail: str | None = None

    @property
    def signed(self) -> str:
        """Return the points with an explicit plus, for the animation."""
        return f"+{self.points}"


async def _rows_of(session: AsyncSession, user: User, day: date) -> list[DailyLog]:
    """Return the owner's days for that year, for the streak walk.

    One query. It has to be the real run: the whole point of the streak line is
    that it says how long the run is, and a breakdown computed from the day
    alone would report every entry as the first of a new streak and never pay
    the bonus at all.

    Args:
        session: The session to read through.
        user: Whose days to load.
        day: A day in the year of interest.

    Returns:
        Their days in that year.

    """
    start, end = year_bounds(day.year)
    return list(
        (
            await session.scalars(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.day >= start,
                    DailyLog.day <= end,
                )
            )
        ).all()
    )


def _day_lines(day: DailyLog, user: User, rows: list[DailyLog]) -> list[RewardLine]:
    """Return the lines for the day itself: its base, and any streak bonus.

    Args:
        day: The day just written.
        user: Its owner.
        rows: The owner's days for the year, for the streak walk.

    Returns:
        The day's lines.

    """
    qualified = scoring.qualifies(day.day, day.logged_at, user.timezone)
    position = 0
    if qualified:
        position = scoring.position_in_run(rows, user.timezone).get(day.day, 0)

    if not qualified:
        return [
            RewardLine(
                label="Filled in a day you missed",
                points=scoring.POINTS_BACKFILLED_DAY,
                detail=day.day.strftime("%-d %b"),
            )
        ]

    lines = [
        RewardLine(
            label="Logged today",
            points=scoring.POINTS_PER_QUALIFYING_DAY,
            detail=day.day.strftime("%-d %b"),
        )
    ]
    bonus = scoring.streak_bonus(position)
    if bonus:
        lines.append(
            RewardLine(
                label=f"Streak bonus, day {position}",
                points=bonus,
                detail=(
                    f"Capped at {scoring.STREAK_BONUS_MAX_STEPS} days"
                    if position > scoring.STREAK_BONUS_MAX_STEPS
                    else None
                ),
            )
        )
    return lines


async def for_entry(
    session: AsyncSession,
    entry: BmEntry,
    day: DailyLog,
    user: User,
    *,
    window_minutes: int,
) -> list[RewardLine]:
    """Return what logging one BM earned.

    Args:
        session: The session to read through.
        entry: The entry just written.
        day: The day it belongs to.
        user: Its owner.
        window_minutes: The quick-entry window, from the same setting the
            scorer reads, so the reward cannot promise a bonus the score will
            not pay.

    Returns:
        The lines, cheapest rule first, so the reading order matches how the
        points stack up.

    """
    lines = _day_lines(day, user, await _rows_of(session, user, day.day))

    if entry.has_note:
        lines.append(RewardLine(label="Wrote a note", points=scoring.POINTS_NOTE))

    if scoring.is_quick(
        entry.created_at, entry.occurred_local, window_minutes, user.timezone
    ):
        lines.append(
            RewardLine(
                label="Logged it on the spot",
                points=scoring.POINTS_QUICK_ENTRY,
                detail=f"within {window_minutes} minutes",
            )
        )
    return lines


async def for_empty_day(
    session: AsyncSession, day: DailyLog, user: User
) -> list[RewardLine]:
    """Return what logging a day with no BMs earned.

    Args:
        session: The session to read through.
        day: The day written.
        user: Its owner.

    Returns:
        The lines.

    """
    lines = _day_lines(day, user, await _rows_of(session, user, day.day))
    if day.is_note_live:
        lines.append(RewardLine(label="Wrote a note", points=scoring.POINTS_NOTE))
    return lines


def total_of(lines: list[RewardLine]) -> int:
    """Return the sum of a breakdown.

    Args:
        lines: The lines to add up.

    Returns:
        The total.

    """
    return sum(line.points for line in lines)
